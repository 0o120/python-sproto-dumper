# Usage guide

## Basic command

```text
python sproto_dumper.py INPUT.lua [MORE_INPUTS.lua ...] [options]
```

Run from the repository folder, or pass the full path to `sproto_dumper.py`.
The script works independently of the rest of the repository. Its copyright
and license notice are included in the file.

## Files and output names

```sh
python sproto_dumper.py "input files/schema.lua" -o "output files"
```

This creates `output files/schema.sproto` and `output files/schema.md`.
Without `--output`, files go into `sproto_files` in your current working directory.

The default module name is the input filename without its extension. A final
`c2s` or `s2c` component separated by `_`, `.`, or `-` is shortened to `c2s` or
`s2c`, case-insensitively. These are common client-to-server/server-to-client
naming conventions. `--name` overrides the module name for a single input:

```sh
python sproto_dumper.py schema.lua --name messages -o output
```

Module names may contain ASCII letters, digits, underscores, dots, and hyphens,
and must start with a letter, digit, or underscore. If input filenames would
produce the same output name, process them separately with distinct `--name`
values.

Existing output is protected. Use `--force` to replace it. All inputs are
extracted and checked before writing starts. Input files are not modified.

## Static Lua examples

A quoted string:

```lua
return ".Message {\n    id 0 : integer\n}\n"
```

A long-bracket string:

```lua
return [=[
.Message {
    id 0 : integer
}
]=]
```

Local string constants and concatenation:

```lua
local schema = ".Message { id 0 : integer }"
return schema .. "\nfetch 1 { request Message }\n"
```

The extractor supports single/double quoted strings, long-bracket delimiters
with any number of `=` signs, parentheses, Lua comments, and string constants.
It decodes control escapes, decimal byte escapes, hexadecimal byte escapes,
escaped line breaks, and `\z` whitespace skipping. Lua files may start with a
UTF-8 BOM.

The extracted schema must be UTF-8. Dynamic Lua expressions are rejected rather
than executed. The declaration parser checks structure, duplicate names/tags,
and endpoint references; it is not a complete semantic type checker or a binary
schema compiler.

## Line endings

Output defaults to CRLF. To generate LF files:

```sh
python sproto_dumper.py schema.lua -o output --newline lf
```

To retain the decoded schema's newline bytes:

```sh
python sproto_dumper.py schema.lua -o output --newline preserve
```

`preserve` applies to `.sproto`; Markdown uses CRLF in that mode. Lua's own
long-bracket string rules normalize embedded newlines during extraction.
The Markdown index has no trailing newline.

Protocol MD5 hashes always use LF-normalized UTF-8 text, regardless of output
newline settings. They include text from the protocol name through the matching
outer closing brace. Indentation before the name, surrounding blank lines, and
comments outside that span are excluded.

## Comparing with expected output

Supply a directory containing matching `.sproto` and `.md` filenames:

```sh
python sproto_dumper.py schema.lua -o output --compare reference_output
```

Schema bytes must match exactly. Markdown comparison accepts the current format
and older indexes with linked names or explicit request/response type names.
Those names are normalized to the current ✓ / — indicators. Missing MD5 columns
are derived from the reference schema; existing MD5 values must match as written.
Table alignment is normalized, so earlier centered indexes can still be used.
References are read only, and a mismatch prevents writing the new output.

To try the feature using the bundled example:

```sh
python sproto_dumper.py examples/sample.lua -o reference_output
python sproto_dumper.py examples/sample.lua -o output --compare reference_output --force
```

## Complete option reference

| Option | Purpose |
| --- | --- |
| `inputs...` | One or more Lua files returning static sproto text. |
| `-o`, `--output PATH` | Output directory; default `sproto_files`. |
| `--name NAME` | Output module name; requires one input. |
| `--newline crlf\|lf\|preserve` | Schema newline policy; default `crlf`. |
| `-f`, `--force` | Replace existing generated files. |
| `--compare PATH` | Verify outputs against this reference directory before writing. |
| `-h`, `--help` | Display command-line help. |

## Troubleshooting

| Message or symptom | What to do |
| --- | --- |
| `Output already exists` | Choose another output directory or add `--force`. |
| `Duplicate output name` | Run the files separately with distinct `--name` values. |
| `dynamic Lua is not supported` | Provide a file that returns static schema text. |
| `expected ...` with a Lua line number | Check the string literal or return expression. |
| `no sproto declarations found` | Check that the returned string contains sproto declarations. |
| `undefined endpoint type` | Include the referenced type in the schema. |
| `not UTF-8` | Check the schema text's encoding and byte escapes. |
| `Output does not match reference` | Check filenames, contents, and newline settings. |

Commands return a nonzero exit status on input, comparison, or write errors.

## Format references

The parser follows the supported subset described above, informed by the
[Lua lexical conventions](https://www.lua.org/manual/5.5/manual.html#3.1) and
the [sproto declaration grammar](https://github.com/cloudwu/sproto/blob/master/sprotoparser.lua).
