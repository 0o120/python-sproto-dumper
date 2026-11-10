#!/usr/bin/env python3
# MIT License
#
# Copyright (c) 2026 0o120
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
"""Extract embedded sproto text from static Lua modules and build an index.

Only Python's standard library is used. Lua input is parsed, never executed.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import hashlib
from pathlib import Path
import re
import sys
from typing import Optional


class DumpError(ValueError):
    """An input cannot be extracted or indexed safely."""


_LUA_NAME = re.compile(rb'[A-Za-z_][A-Za-z0-9_]*')
_LONG_OPEN = re.compile(rb'\[(=*)\[')
_SHORT_SPECIAL = {34: re.compile(rb'["\\\r\n]'), 39: re.compile(rb"['\\\r\n]")}
_ESCAPES = {ord(key): value for key, value in {
    'a': b'\a', 'b': b'\b', 'f': b'\f', 'n': b'\n', 'r': b'\r',
    't': b'\t', 'v': b'\v', '\\': b'\\', '"': b'"', "'": b"'",
}.items()}
_SPACE = b' \t\r\n\v\f'
_NEWLINES = re.compile(rb'\r\n|\n\r|\r|\n')


class LuaStrings:
    """Read a constant return expression, optionally preceded by local strings."""

    def __init__(self, source: bytes):
        self.source = source
        self.pos = 3 if source.startswith(b'\xef\xbb\xbf') else 0
        self.locals: dict[bytes, bytes] = {}

    def error(self, message: str) -> DumpError:
        line = len(_NEWLINES.findall(self.source, 0, self.pos)) + 1
        return DumpError(f'Lua line {line}: {message}')

    def long_string(self) -> Optional[bytes]:
        opening = _LONG_OPEN.match(self.source, self.pos)
        if not opening:
            return None
        closing = b']' + opening.group(1) + b']'
        end = self.source.find(closing, opening.end())
        if end < 0:
            raise self.error('unterminated long-bracket string or comment')
        data = self.source[opening.end():end]
        self.pos = end + len(closing)
        # Lua ignores one immediate opening newline and normalizes long strings.
        data = _NEWLINES.sub(b'\n', data)
        if data.startswith(b'\n'):
            data = data[1:]
        return data

    def skip(self) -> None:
        while self.pos < len(self.source):
            if self.source[self.pos] in _SPACE:
                self.pos += 1
            elif self.source.startswith(b'--', self.pos):
                self.pos += 2
                if self.long_string() is None:
                    end = _NEWLINES.search(self.source, self.pos)
                    self.pos = end.end() if end else len(self.source)
            else:
                break

    def take(self, token: bytes) -> bool:
        self.skip()
        if not self.source.startswith(token, self.pos):
            return False
        self.pos += len(token)
        return True

    def name(self) -> bytes:
        self.skip()
        match = _LUA_NAME.match(self.source, self.pos)
        if match is None:
            raise self.error('expected an identifier')
        self.pos = match.end()
        return match.group()

    def short_string(self) -> bytes:
        delimiter = self.source[self.pos]
        self.pos += 1
        pieces = []
        while True:
            special = _SHORT_SPECIAL[delimiter].search(self.source, self.pos)
            if special is None:
                raise self.error('unterminated quoted string')
            pieces.append(self.source[self.pos:special.start()])
            self.pos = special.end()
            char = special.group()[0]
            if char == delimiter:
                return b''.join(pieces)
            if char != 92:
                raise self.error('unescaped newline in quoted string')
            if self.pos == len(self.source):
                raise self.error('unfinished escape sequence')
            escaped = self.source[self.pos]
            self.pos += 1
            if escaped in _ESCAPES:
                pieces.append(_ESCAPES[escaped])
            elif escaped in (10, 13):
                if self.pos < len(self.source) and self.source[self.pos] in (10, 13) and self.source[self.pos] != escaped:
                    self.pos += 1
                pieces.append(b'\n')
            elif escaped == ord('z'):
                while self.pos < len(self.source) and self.source[self.pos] in _SPACE:
                    self.pos += 1
            elif escaped == ord('x'):
                digits = self.source[self.pos:self.pos + 2]
                if not re.fullmatch(rb'[0-9A-Fa-f]{2}', digits):
                    raise self.error('hexadecimal escapes require exactly two digits')
                pieces.append(bytes([int(digits, 16)]))
                self.pos += 2
            elif ord('0') <= escaped <= ord('9'):
                start = self.pos - 1
                while self.pos < min(start + 3, len(self.source)) and ord('0') <= self.source[self.pos] <= ord('9'):
                    self.pos += 1
                value = int(self.source[start:self.pos])
                if value > 255:
                    raise self.error('decimal byte escape is greater than 255')
                pieces.append(bytes([value]))
            else:
                raise self.error(f'unsupported escape byte: 0x{escaped:02X}')

    def primary(self) -> bytes:
        self.skip()
        if self.pos == len(self.source):
            raise self.error('expected a string expression')
        if self.source[self.pos] in (34, 39):
            return self.short_string()
        long = self.long_string()
        if long is not None:
            return long
        if self.take(b'('):
            result = self.expression()
            if not self.take(b')'):
                raise self.error('expected closing parenthesis')
            return result
        name = self.name()
        if name not in self.locals:
            raise self.error(f'unknown constant {name.decode("ascii")!r}; dynamic Lua is not supported')
        return self.locals[name]

    def expression(self) -> bytes:
        parts = [self.primary()]
        while self.take(b'..'):
            parts.append(self.primary())
        return b''.join(parts)

    def extract(self) -> bytes:
        while True:
            keyword = self.name()
            if keyword == b'local':
                name = self.name()
                if not self.take(b'='):
                    raise self.error('local constants require a string initializer')
                # Evaluate before rebinding, as in local value = value .. "...".
                value = self.expression()
                self.locals[name] = value
                self.take(b';')
            elif keyword == b'return':
                result = self.expression()
                self.take(b';')
                self.skip()
                if self.pos != len(self.source):
                    raise self.error('unexpected code after return expression; only static strings are supported')
                return result
            else:
                raise self.error('expected local string constants followed by return, or a direct return string')


def extract_sproto(source: bytes) -> bytes:
    """Decode Lua string bytes without running any Lua or external programs."""
    try:
        return LuaStrings(source).extract()
    except RecursionError as exc:
        raise DumpError('Lua expression nesting is too deep') from exc


@dataclass
class Token:
    value: str
    kind: str
    line: int
    start: int
    end: int


_SCHEMA_TOKEN = re.compile(
    r'(?P<skip>[ \t\r\n]+|\#[^\r\n]*)|(?P<name>[A-Za-z_][A-Za-z0-9_]*)'
    r'|(?P<number>[0-9]+)|(?P<symbol>[.{}:*()])'
)


def _schema_text(schema: bytes) -> str:
    try:
        return _NEWLINES.sub(b'\n', schema).decode('utf-8-sig')
    except UnicodeDecodeError as exc:
        raise DumpError(f'The extracted schema is not UTF-8: {exc}') from exc


def _tokens_from_text(text: str) -> list[Token]:
    pos, line = 0, 1
    result = []
    while pos < len(text):
        match = _SCHEMA_TOKEN.match(text, pos)
        if match is None:
            raise DumpError(f'Sproto line {line}: unexpected character {text[pos]!r}')
        value = match.group()
        if match.lastgroup != 'skip':
            result.append(Token(value, match.lastgroup, line, pos, match.end()))
        line += value.count('\n')
        pos = match.end()
    result.append(Token('', 'eof', line, pos, pos))
    return result


def schema_tokens(schema: bytes) -> list[Token]:
    return _tokens_from_text(_schema_text(schema))


@dataclass
class TypeInfo:
    name: str
    declaration_line: int
    fields: dict[int, int] = field(default_factory=dict)

    @property
    def documentation_line(self) -> Optional[int]:
        # The lowest-tag field's location, or None for a type without fields.
        return self.fields[min(self.fields)] if self.fields else None


@dataclass
class Protocol:
    name: str
    tag: int
    line: int
    request: Optional[str] = None
    response: Optional[str] = None
    md5: str = ''


@dataclass
class SchemaIndex:
    types: dict[str, TypeInfo]
    protocols: list[Protocol]


class SprotoParser:
    """Index declarations and hash protocol blocks without rewriting the schema."""

    def __init__(self, schema: bytes):
        self.text = _schema_text(schema)
        self.tokens = _tokens_from_text(self.text)
        self.pos = 0
        self.types: dict[str, TypeInfo] = {}
        self.protocols: list[Protocol] = []

    @property
    def current(self) -> Token:
        return self.tokens[self.pos]

    def error(self, message: str) -> DumpError:
        return DumpError(f'Sproto line {self.current.line}: {message}')

    def take(self, value: str) -> bool:
        if self.current.value != value:
            return False
        self.pos += 1
        return True

    def expect(self, value: str) -> Token:
        token = self.current
        if not self.take(value):
            raise self.error(f'expected {value!r}, found {self.current.value!r}')
        return token

    def typed(self, kind: str) -> Token:
        token = self.current
        if token.kind != kind:
            raise self.error(f'expected {kind}, found {token.value!r}')
        self.pos += 1
        return token

    def type_name(self) -> str:
        previous = self.typed('name')
        parts = [previous.value]
        # Dots in qualified names are adjacent to identifiers. A dot after
        # whitespace can instead start the next nested type declaration.
        while self.current.value == '.' and self.current.start == previous.end:
            dot = self.expect('.')
            previous = self.typed('name')
            if previous.start != dot.end:
                raise self.error('whitespace inside a qualified type name')
            parts.append(previous.value)
        return '.'.join(parts)

    def structure(self, name: str, line: int) -> None:
        if name in self.types:
            raise self.error(f'duplicate type {name!r}')
        info = TypeInfo(name, line)
        self.types[name] = info
        self.expect('{')
        field_names = set()
        while not self.take('}'):
            if self.take('.'):
                nested = self.typed('name')
                self.structure(name + '.' + nested.value, nested.line)
                continue
            token = self.typed('name')
            tag = int(self.typed('number').value)
            if token.value in field_names or tag in info.fields:
                raise self.error(f'duplicate field name or tag in {name!r}')
            field_names.add(token.value)
            info.fields[tag] = token.line
            self.expect(':')
            self.take('*')
            self.type_name()
            while self.take('('):
                if self.current.kind in ('name', 'number'):
                    self.pos += 1
                self.expect(')')

    def parse(self) -> SchemaIndex:
        protocol_names, protocol_tags = set(), set()
        while self.current.kind != 'eof':
            if self.take('.'):
                name = self.typed('name')
                self.structure(name.value, name.line)
                continue
            name = self.typed('name')
            tag = int(self.typed('number').value)
            if name.value in protocol_names or tag in protocol_tags:
                raise self.error(f'duplicate protocol name or tag: {name.value!r} / {tag}')
            protocol_names.add(name.value)
            protocol_tags.add(tag)
            protocol = Protocol(name.value, tag, name.line)
            self.expect('{')
            endpoints = set()
            while not self.take('}'):
                endpoint = self.typed('name')
                if endpoint.value not in ('request', 'response') or endpoint.value in endpoints:
                    raise self.error('expected a single request or response declaration')
                endpoints.add(endpoint.value)
                if self.current.value == '{':
                    target = name.value + '.' + endpoint.value
                    self.structure(target, endpoint.line)
                else:
                    target = self.type_name()
                setattr(protocol, endpoint.value, None if target == 'nil' else target)
            # The closing token was consumed by the loop condition. Use the
            # original normalized text to include comments and nested blocks,
            # while excluding surrounding whitespace and unrelated declarations.
            block = self.text[name.start:self.tokens[self.pos - 1].end]
            protocol.md5 = hashlib.md5(block.encode('utf-8'), usedforsecurity=False).hexdigest()
            self.protocols.append(protocol)
        if not self.types and not self.protocols:
            raise self.error('no sproto declarations found')
        for protocol in self.protocols:
            for endpoint in (protocol.request, protocol.response):
                if endpoint is not None and endpoint not in self.types:
                    raise DumpError(f'Sproto line {protocol.line}: undefined endpoint type {endpoint!r}')
        return SchemaIndex(self.types, sorted(self.protocols, key=lambda item: item.tag))


def index_sproto(schema: bytes) -> SchemaIndex:
    try:
        return SprotoParser(schema).parse()
    except RecursionError as exc:
        raise DumpError('Sproto type nesting is too deep') from exc


def render_markdown(index: SchemaIndex, module: str, newline: bytes = b'\r\n') -> bytes:
    """Keep stable protocol names and compact request/response indicators."""
    protocol_count, type_count = len(index.protocols), len(index.types)
    lines = [
        '# sproto list', 'generated by sprotodump DO NOT EDIT!!', '', '', '## sum',
        'kind|sum', ':------:|:------:', f'protocol|{protocol_count}', f'type|{type_count}', '',
        '## module', 'module|range|info|protocol sum|type sum',
        ':------:|:------:|:------:|:------:|:------:',
        f'{module}|`nil`|`nil`|{protocol_count}|{type_count}', '',
        '## list', 'protocol|tag|request|response|md5', ':------:|:------:|:------:|:------:|:------:',
    ]

    def endpoint_marker(name: Optional[str]) -> str:
        if name is None or not index.types[name].fields:
            return '—'
        return '✓'

    for protocol in index.protocols:
        lines.append(f'{protocol.name}|{protocol.tag}|'
                     f'{endpoint_marker(protocol.request)}|{endpoint_marker(protocol.response)}|{protocol.md5}')
    # Keep the final row unterminated for stable output.
    return newline.join(line.encode('utf-8') for line in lines)


def normalize_reference_markdown(data: bytes, protocol_hashes: dict[str, str]) -> bytes:
    """Upgrade legacy indexes using hashes from their reference schema.

    Existing MD5 cells are preserved so incorrect hashes fail comparison.
    """
    data = re.sub(rb'\[([A-Za-z0-9_.-]+)\]\([^\r\n)]*\)', rb'\1', data)

    def endpoint(value: bytes) -> bytes:
        if value == b'`nil`':
            return '—'.encode('utf-8')
        if re.fullmatch(rb'[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*', value):
            return '✓'.encode('utf-8')
        return value

    def protocol_row(match: re.Match[bytes]) -> bytes:
        row = match[1] + b'|' + match[2] + b'|' + endpoint(match[3]) + b'|' + endpoint(match[4])
        if match[5] is not None:
            return row + b'|' + match[5]
        name = match[1].decode('ascii')
        if name not in protocol_hashes:
            raise DumpError(f'Markdown reference has unknown protocol {name!r}')
        return row + b'|' + protocol_hashes[name].encode('ascii')

    data = re.sub(
        rb'^(protocol\|tag\|request\|response)(\r?\n)(:------:\|:------:\|:------:\|:------:)(?=\r?$)',
        lambda match: match[1] + b'|md5' + match[2] + match[3] + b'|:------:',
        data, flags=re.MULTILINE,
    )
    return re.sub(
        rb'^([A-Za-z_][A-Za-z0-9_]*)\|([0-9]+)\|([^|\r\n]+)\|([^|\r\n]+)(?:\|([^|\r\n]*))?(?=\r?$)',
        protocol_row, data, flags=re.MULTILINE,
    )


def module_name(path: Path) -> str:
    suffix = re.search(r'(?:^|[_.-])(c2s|s2c)$', path.stem, re.IGNORECASE)
    return suffix.group(1).lower() if suffix else path.stem


def dump_files(inputs: list[Path], output: Path, *, name: Optional[str] = None,
               newline: str = 'crlf',
               force: bool = False, compare: Optional[Path] = None) -> list[dict]:
    """Prepare and optionally verify every result before writing any files."""
    if name is not None and len(inputs) != 1:
        raise DumpError('--name can only be used with one input file')
    if newline not in ('crlf', 'lf', 'preserve'):
        raise DumpError('newline must be crlf, lf, or preserve')
    output = output.resolve()
    prepared, names = [], set()
    for source in inputs:
        module = name if name is not None else module_name(source)
        if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*', module):
            raise DumpError(f'Invalid output name {module!r}; use --name with letters, digits, dots, underscores, or hyphens')
        if module.casefold() in names:
            raise DumpError(f'Duplicate output name {module!r}; process those inputs separately with --name')
        names.add(module.casefold())
        try:
            raw = extract_sproto(source.read_bytes())
            separator = b'\n' if newline == 'lf' else b'\r\n'
            schema = raw if newline == 'preserve' else _NEWLINES.sub(separator, raw)
            index = index_sproto(schema)
        except DumpError as exc:
            raise DumpError(f'{source}: {exc}') from exc
        md = render_markdown(index, module, separator)
        prepared.append((module, schema, md, index))

    payloads = [(output / (module + suffix), data)
                for module, schema, md, _ in prepared
                for suffix, data in (('.sproto', schema), ('.md', md))]
    source_paths = {path.resolve() for path in inputs}
    for target, data in payloads:
        if target.resolve() in source_paths:
            raise DumpError(f'Output would replace an input: {target}')
        if target.exists() and not force:
            raise DumpError(f'Output already exists: {target}; use --force to replace it')
        if compare is not None:
            reference = compare / target.name
            expected = reference.read_bytes()
            if target.suffix == '.md':
                reference_index = index_sproto(reference.with_suffix('.sproto').read_bytes())
                hashes = {protocol.name: protocol.md5 for protocol in reference_index.protocols}
                expected = normalize_reference_markdown(expected, hashes)
            if expected != data:
                raise DumpError(f'Output does not match reference: {reference}')
    output.mkdir(parents=True, exist_ok=True)
    for target, data in payloads:
        with target.open('wb' if force else 'xb') as stream:
            stream.write(data)
    return [{
        'module': module, 'protocols': len(index.protocols), 'types': len(index.types),
        'sproto_bytes': len(schema), 'markdown_bytes': len(md),
        'sproto_sha256': hashlib.sha256(schema).hexdigest(),
        'markdown_sha256': hashlib.sha256(md).hexdigest(),
    } for module, schema, md, index in prepared]


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('inputs', type=Path, nargs='+', help='Lua files returning embedded sproto text')
    parser.add_argument('-o', '--output', type=Path, default=Path('sproto_files'), help='Output folder (default: sproto_files)')
    parser.add_argument('--name', help='Output module name for a single input; c2s/s2c suffixes are recognized automatically')
    parser.add_argument('--newline', choices=('crlf', 'lf', 'preserve'), default='crlf', help='Schema line endings (default: crlf)')
    parser.add_argument('-f', '--force', action='store_true', help='Replace existing generated files')
    parser.add_argument('--compare', type=Path, help='Check exact schema bytes and Markdown; upgrade legacy references using their schema for missing MD5 values')
    args = parser.parse_args(argv)
    try:
        results = dump_files(args.inputs, args.output, name=args.name, newline=args.newline,
                             force=args.force, compare=args.compare)
    except (DumpError, OSError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1
    for result in results:
        print(f"{result['module']}: {result['protocols']} protocols, {result['types']} types; "
              f"wrote .sproto and .md to {args.output}")
    if args.compare:
        print(f'All {2 * len(results)} generated files match: exact .sproto bytes; .md matches after upgrading legacy reference formatting and missing hashes.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
