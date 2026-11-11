from pathlib import Path
import hashlib
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sproto_dumper import (DumpError, dump_files, extract_sproto, index_sproto,
                           module_name, render_markdown)


class LuaStringTests(unittest.TestCase):
    def test_utf8_bom_and_comments(self):
        source = '\ufeff-- header\nreturn "\\n.Item { # 数据\\n}\\n"; -- end\n'.encode('utf-8')
        self.assertEqual(extract_sproto(source), '\n.Item { # 数据\n}\n'.encode('utf-8'))

    def test_named_escapes(self):
        self.assertEqual(extract_sproto(br'''return "\a\b\f\n\r\t\v\\\"\'"'''),
                         b'\a\b\f\n\r\t\v\\"\'')

    def test_all_decimal_and_hex_byte_values(self):
        expected = bytes(range(256))
        decimal = ''.join(f'\\{value:03d}' for value in expected).encode('ascii')
        hexa = ''.join(f'\\x{value:02x}' for value in expected).encode('ascii')
        self.assertEqual(extract_sproto(b'return "' + decimal + b'"'), expected)
        self.assertEqual(extract_sproto(b'return "' + hexa + b'"'), expected)
        self.assertEqual(extract_sproto(br'return "\0656\07x"'), b'A6\ax')

    def test_escaped_utf8_is_decoded_as_bytes(self):
        self.assertEqual(extract_sproto(br'return "\228\184\173"'), '中'.encode('utf-8'))

    def test_escaped_line_breaks(self):
        for newline in (b'\n', b'\r', b'\r\n', b'\n\r'):
            with self.subTest(newline=newline):
                self.assertEqual(extract_sproto(b'return "a\\' + newline + b'b"'), b'a\nb')

    def test_whitespace_escape(self):
        self.assertEqual(extract_sproto(b'return "a\\z \t\r\n\v\fb"'), b'ab')

    def test_long_strings_and_long_comments(self):
        source = b'--[==[ return "ignored" ]==]\nreturn [=[\r\nfirst ]] \\n\r\nsecond\rthird]=]'
        self.assertEqual(extract_sproto(source), b'first ]] \\n\nsecond\nthird')
        self.assertEqual(extract_sproto(b'return [[\n\nkept]]'), b'\nkept')
        self.assertEqual(extract_sproto(b'return [====[text]====]'), b'text')

    def test_concatenation_and_local_constants(self):
        source = b'local schema = "a"; local schema = schema .. \'b\'\nreturn (schema .. [[c]]) .. "d"'
        self.assertEqual(extract_sproto(source), b'abcd')

    def test_rejects_dynamic_or_extra_code(self):
        cases = [b'return require("schema")', b'os.execute("anything")',
                 b'return "schema"; do_something()', b'return "a", "b"',
                 b'return unknown', b'local value = 1; return value']
        for source in cases:
            with self.subTest(source=source), self.assertRaises(DumpError):
                extract_sproto(source)

    def test_rejects_bad_literals(self):
        cases = [br'return "\256"', br'return "\xG0"', br'return "\q"',
                 b'return "unfinished', b'return [[unfinished', b'return "a\nb"',
                 b'return ("a"', b'--[[unfinished']
        for source in cases:
            with self.subTest(source=source), self.assertRaises(DumpError):
                extract_sproto(source)


class SchemaTests(unittest.TestCase):
    def test_nested_types_counts_and_numeric_protocol_order(self):
        schema = b'''.Container {
    value 9 : integer
    .Child { id 0 : integer }
    child 2 : Child
}
later 10 { request Container.Child response nil }
earlier 2 { request { .Nested {} value 0 : integer } response {} }
'''
        index = index_sproto(schema)
        self.assertEqual(set(index.types), {'Container', 'Container.Child',
                         'earlier.request', 'earlier.request.Nested', 'earlier.response'})
        self.assertEqual([protocol.tag for protocol in index.protocols], [2, 10])
        self.assertEqual(index.types['Container'].documentation_line, 4)
        md = render_markdown(index, 'test').decode('utf-8')
        self.assertIn('earlier|2|✓|—', md)
        self.assertIn('later|10|✓|—', md)

    def test_comments_do_not_create_declarations_or_braces(self):
        schema = b'# .Fake { } bogus 99 {}\r\n.Type { # }\r\n id 0 : integer # {\r\n}\r\ncall 1 { request Type }\r\n'
        index = index_sproto(schema)
        self.assertEqual(len(index.types), 1)
        self.assertEqual(len(index.protocols), 1)
        self.assertEqual(index.types['Type'].documentation_line, 3)
        self.assertEqual(index.protocols[0].line, 5)

    def test_forward_endpoint_reference_and_qualified_fields(self):
        index = index_sproto(b'call 1 { request Outer.Inner } .Outer { .Inner { id 0 : integer } ref 0 : Outer.Inner }')
        self.assertEqual(index.protocols[0].request, 'Outer.Inner')

    def test_array_keys_and_integer_precision(self):
        index = index_sproto(b'.Row { id 0 : integer } .Data { values 0 : *Row(id) all 1 : *Row() amount 2 : integer(4) flag 3 : boolean raw 4 : binary ratio 5 : double }')
        self.assertEqual(len(index.types['Data'].fields), 6)

    def test_empty_type_is_counted_but_endpoint_is_empty(self):
        index = index_sproto(b'ping 1 { request {} response {} }')
        self.assertEqual(len(index.types), 2)
        md = render_markdown(index, 'test')
        self.assertTrue(md.decode('utf-8').endswith('ping|1|—|—|b0896a6a70243d778f6187e9f235a462'))

    def test_all_request_response_indicator_combinations(self):
        index = index_sproto(b'''.Value { id 0 : integer }
both 1 { request Value response Value }
request_only 2 { request Value }
response_only 3 { response Value }
neither 4 {}
confirmation 5 { response nil }
''')
        rows = render_markdown(index, 'test').decode('utf-8').splitlines()
        self.assertEqual([row.rsplit('|', 1)[0] for row in rows[-5:]],
                         ['both|1|✓|✓', 'request_only|2|✓|—',
                          'response_only|3|—|✓', 'neither|4|—|—',
                          'confirmation|5|—|—'])

    def test_reference_markdown_layout(self):
        index = index_sproto(b'.Record {\n value 0 : string\n}\nget 4 {\n request Record\n}\n')
        expected = (
            '# sproto list\r\ngenerated by sprotodump DO NOT EDIT!!\r\n\r\n\r\n'
            '## sum\r\nkind|sum\r\n:------:|:------:\r\nprotocol|1\r\ntype|1\r\n\r\n'
            '## module\r\nmodule|range|info|protocol sum|type sum\r\n'
            ':------:|:------:|:------:|:------:|:------:\r\n'
            'test|`nil`|`nil`|1|1\r\n\r\n'
            '## list\r\nprotocol|tag|request|response|md5\r\n:------|------:|:------:|:------:|:------\r\n'
            'get|4|✓|—|c903bfb47d9c1d347b5bc42b340457c4'
        ).encode('utf-8')
        self.assertEqual(render_markdown(index, 'test'), expected)

    def test_schema_line_shifts_do_not_change_markdown(self):
        schema = b'.Record {\n value 0 : string\n}\nget 4 {\n request Record\n}\n'
        shifted = b'# Added comment\n\n' + schema.replace(b' value', b'\n # More detail\n value')
        original = render_markdown(index_sproto(schema), 'test')
        self.assertEqual(render_markdown(index_sproto(shifted), 'test'), original)
        self.assertNotIn(b'](', original)
        self.assertNotIn(b'#L', original)

    def test_added_protocol_keeps_existing_rows_identical(self):
        schema = b'.Record { value 0 : string }\nget 4 { request Record }\n'
        old = render_markdown(index_sproto(schema), 'test').splitlines()
        new = render_markdown(index_sproto(b'ping 1 {}\n' + schema), 'test').splitlines()
        self.assertEqual([row for row in old if row.startswith(b'get|')],
                         [row for row in new if row.startswith(b'get|')])
        self.assertTrue(any(row.startswith('ping|1|—|—|'.encode('utf-8')) for row in new))

    def test_invalid_schema_reports_errors(self):
        cases = [b'', b'.A {', b'.A { name 0 integer }', b'.A {} .A {}',
                 b'a 1 {} b 1 {}', b'a 1 {} a 2 {}', b'.A { a 0 : string b 0 : string }',
                 b'.A { a 0 : string a 1 : string }', b'a 1 { request Missing }',
                 b'a 1 { response {} response {} }', b'a 1 { other {} }', b'.A { @ }', b'\xff']
        for source in cases:
            with self.subTest(source=source), self.assertRaises(DumpError):
                index_sproto(source)


class ProtocolHashTests(unittest.TestCase):
    def test_hash_covers_complete_block_including_unicode_and_nested_comments(self):
        block = '''query 7 { # header comment
    request {
        .Nested { id 0 : integer }
        data 0 : Nested # 中文 } comment braces do not close the protocol
    }
    response { ok 0 : boolean }
}'''
        schema = '# Prefix 数据\n\n' + block + ' # Outside trailing comment\n'
        protocol = index_sproto(schema.encode('utf-8')).protocols[0]
        self.assertEqual(protocol.md5, hashlib.md5(block.encode('utf-8'), usedforsecurity=False).hexdigest())
        self.assertRegex(protocol.md5, r'^[0-9a-f]{32}$')

    def test_line_endings_do_not_change_hash(self):
        schema = b'query 1 {\n request { id 0 : integer }\n}\n'
        expected = index_sproto(schema).protocols[0].md5
        for ending in (b'\n', b'\r\n', b'\r'):
            with self.subTest(ending=ending):
                self.assertEqual(index_sproto(schema.replace(b'\n', ending)).protocols[0].md5, expected)

    def test_moving_whole_blocks_preserves_all_markdown_rows(self):
        first = b'first 1 { request { id 0 : integer } }'
        second = b'second 2 { response { result 0 : string } }'
        before = index_sproto(first + b'\n' + second)
        after = index_sproto(b'# Intro\n\n' + second + b'\n\n# More text\n' + first + b'\n\n')
        self.assertEqual(render_markdown(before, 'test'), render_markdown(after, 'test'))

    def test_field_edit_changes_only_its_protocol_row(self):
        schema = b'first 1 { request { id 0 : integer } }\nsecond 2 { response { result 0 : string } }'
        before = render_markdown(index_sproto(schema), 'test').splitlines()
        after = render_markdown(index_sproto(schema.replace(b'id 0 : integer', b'id 0 : string')), 'test').splitlines()
        changed = [(old, new) for old, new in zip(before, after) if old != new]
        self.assertEqual(len(changed), 1)
        old, new = changed[0]
        self.assertTrue(old.startswith(b'first|1|'))
        self.assertEqual(old.rsplit(b'|', 1)[0], new.rsplit(b'|', 1)[0])
        self.assertNotEqual(old.rsplit(b'|', 1)[1], new.rsplit(b'|', 1)[1])

    def test_comments_whitespace_header_and_nested_fields_inside_block_change_hash(self):
        block = b'query 1 {\n request {\n .Nested { id 0 : integer }\n data 0 : Nested # note\n }\n}'
        original = index_sproto(block).protocols[0].md5
        variants = [block.replace(b'# note', b'# updated note'),
                    block.replace(b' data', b'  data'),
                    block.replace(b'query 1', b'query 2'),
                    block.replace(b'id 0 : integer', b'id 0 : string')]
        for schema in variants:
            with self.subTest(schema=schema):
                self.assertNotEqual(index_sproto(schema).protocols[0].md5, original)

    def test_separately_declared_shared_types_are_outside_protocol_hash(self):
        schema = b'.Shared { id 0 : integer }\nquery 1 { request Shared }'
        before = index_sproto(schema).protocols[0].md5
        after = index_sproto(schema.replace(b'id 0 : integer', b'id 0 : string')).protocols[0].md5
        self.assertEqual(before, after)


class FileTests(unittest.TestCase):
    def test_module_names(self):
        self.assertEqual(module_name(Path('module_proto_c2s.lua')), 'c2s')
        self.assertEqual(module_name(Path('module-proto-S2C.lua')), 's2c')
        self.assertEqual(module_name(Path('schema.lua')), 'schema')

    def test_exact_extraction_preserves_whitespace_comments_and_unicode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'schema.lua'
            expected = '\n\n.Row { # 中文\n\tvalue 0 : integer  \n}\n\n'.encode('utf-8')
            source.write_bytes(b'return "' + expected.replace(b'\t', b'\\t').replace(b'\n', b'\\n') + b'"')
            output = root / 'sproto_files'
            results = dump_files([source], output)
            self.assertEqual((output / 'schema.sproto').read_bytes(), expected.replace(b'\n', b'\r\n'))
            self.assertEqual(results[0]['types'], 1)
            self.assertEqual({path.suffix for path in output.iterdir()}, {'.md', '.sproto'})
            self.assertEqual(source.read_bytes()[:8], b'return "')

    def test_line_ending_options(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'schema.lua'
            source.write_bytes(br'return "\r\n.Type {\n id 0 : integer\r\n}\n"')
            raw = b'\r\n.Type {\n id 0 : integer\r\n}\n'
            for style in ('crlf', 'lf', 'preserve'):
                output = root / style
                dump_files([source], output, newline=style)
                expected = raw if style == 'preserve' else raw.replace(b'\r\n', b'\n')
                if style == 'crlf':
                    expected = expected.replace(b'\n', b'\r\n')
                self.assertEqual((output / 'schema.sproto').read_bytes(), expected)

    def test_overwrite_protection_and_reference_comparison(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'schema.lua'
            source.write_bytes(b'return ".Type {}"')
            expected, output = root / 'expected', root / 'output'
            dump_files([source], expected)
            dump_files([source], output, compare=expected)
            with self.assertRaises(DumpError):
                dump_files([source], output)
            dump_files([source], output, compare=expected, force=True)
            (expected / 'schema.md').write_bytes(b'changed reference')
            with self.assertRaises(DumpError):
                dump_files([source], root / 'new', compare=expected)
            self.assertFalse((root / 'new').exists())

    def test_legacy_references_preserve_tag_and_endpoint_presence_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'schema.lua'
            source.write_bytes(b'return ".Type { id 0 : integer } query 2 { request Type }"')
            reference = root / 'reference'
            dump_files([source], reference)
            md = reference / 'schema.md'
            lines = md.read_bytes().split(b'\r\n')
            table = lines.index(b'protocol|tag|request|response|md5')
            for row in range(table, len(lines)):
                lines[row] = lines[row].rsplit(b'|', 1)[0]
            linked = b'\r\n'.join(lines).replace(b'schema|', b'[schema](./schema.sproto)|')
            linked = linked.replace('query|2|✓|—'.encode('utf-8'),
                                    b'[query](./schema.sproto#L200)|2|[Type](./schema.sproto#L900)|`nil`')
            self.assertIn(b'#L200', linked)
            self.assertNotIn(b'|md5', linked)
            md.write_bytes(linked)
            dump_files([source], root / 'output', compare=reference)
            named = linked.replace(b'[query](./schema.sproto#L200)', b'query')
            named = named.replace(b'[Type](./schema.sproto#L900)', b'Type')
            md.write_bytes(named)
            dump_files([source], root / 'named-output', compare=reference)
            md.write_bytes(linked.replace(b'|2|[Type]', b'|3|[Type]'))
            with self.assertRaises(DumpError):
                dump_files([source], root / 'different', compare=reference)
            self.assertFalse((root / 'different').exists())
            md.write_bytes(linked.replace(b'[Type](./schema.sproto#L900)', b'`nil`'))
            with self.assertRaises(DumpError):
                dump_files([source], root / 'missing-request', compare=reference)
            self.assertFalse((root / 'missing-request').exists())

    def test_reference_md5_is_verified_instead_of_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'schema.lua'
            source.write_bytes(b'return "query 1 { request { id 0 : integer } }"')
            reference = root / 'reference'
            dump_files([source], reference)
            dump_files([source], root / 'output', compare=reference)
            md = reference / 'schema.md'
            prefix, digest = md.read_bytes().rsplit(b'|', 1)
            self.assertEqual(len(digest), 32)
            md.write_bytes(prefix + b'|' + b'0' * 32)
            with self.assertRaises(DumpError):
                dump_files([source], root / 'invalid', compare=reference)
            self.assertFalse((root / 'invalid').exists())

    def test_bad_input_and_collisions_do_not_write_partial_results(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first, second = root / 'first_c2s.lua', root / 'second_c2s.lua'
            for source in (first, second):
                source.write_bytes(b'return ".Type {}"')
            with self.assertRaises(DumpError):
                dump_files([first, second], root / 'output')
            self.assertFalse((root / 'output').exists())
            second = root / 's2c.lua'
            second.write_bytes(b'return require("dynamic")')
            with self.assertRaisesRegex(DumpError, 's2c.lua'):
                dump_files([first, second], root / 'output')
            self.assertFalse((root / 'output').exists())
            with self.assertRaises(DumpError):
                dump_files([first], root / 'output', name='../escape')

    def test_cli_success_and_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            command = [sys.executable, str(ROOT / 'sproto_dumper.py'), str(ROOT / 'examples/sample.lua'), '-o', str(root / 'sproto_files')]
            result = subprocess.run(command, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(b'2 protocols', result.stdout)
            refused = subprocess.run(command, capture_output=True, timeout=30)
            self.assertNotEqual(refused.returncode, 0)


if __name__ == '__main__':
    unittest.main()
