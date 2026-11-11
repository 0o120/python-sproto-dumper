# Python Sproto Dumper

[![Tests](https://github.com/0o120/python-sproto-dumper/actions/workflows/tests.yml/badge.svg)](https://github.com/0o120/python-sproto-dumper/actions/workflows/tests.yml)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/downloads/)
[![MIT license](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Extract sproto schemas embedded in Lua files and generate readable Markdown
protocol indexes. Each protocol gets an MD5 hash, making changes inside its
definition visible in Git diffs.

**Python 3.9+ is the only requirement.** The tool uses the standard library,
parses static strings without executing Lua, and requires no Lua interpreter.

## Get started

[Download the ZIP](https://github.com/0o120/python-sproto-dumper/archive/refs/heads/main.zip)
and open a terminal in the extracted folder, or clone the repository:

```sh
git clone https://github.com/0o120/python-sproto-dumper.git
cd python-sproto-dumper
```

Try the included example:

```sh
python sproto_dumper.py examples/sample.lua -o output
```

This creates:

```text
output/
  sample.sproto
  sample.md
```

Open `sample.sproto` for the schema and `sample.md` for the protocol index.
Use `python3` instead of `python` if that is how your system names Python 3.

## Use your own files

Extract one Lua file:

```sh
python sproto_dumper.py schema.lua -o output
```

Extract several files in one command:

```sh
python sproto_dumper.py client.lua server.lua -o output
```

Choose the output name for a single input:

```sh
python sproto_dumper.py schema.lua --name client -o output
```

Existing files are protected. Add `--force` to replace generated output:

```sh
python sproto_dumper.py schema.lua -o output --force
```

Quote paths containing spaces. Input arguments must be files; directory scans
are not supported. Without `-o`, output goes into `sproto_files` in the current
working directory. Generated output folders are excluded from Git.

## What the Markdown looks like

The bundled [sample](examples/sample.lua) produces a protocol list like this:

| protocol | tag | request | response | md5 |
| --- | ---: | :---: | :---: | --- |
| get_items | 1 | ✓ | ✓ | d9eb0e2175bcda190f88af8da5987cf4 |
| notify_ready | 2 | — | — | 9f607f524e82845edcb54557c2d21090 |

- **✓** means the request or response has fields.
- **—** means it is absent or empty.
- Protocols are sorted by numeric tag, with one row per source line.
- Tables use plain Markdown, with no links or line-number anchors.
- Protocol names and hashes are left-aligned, tags are right-aligned, and the
  request/response indicators are centered.

The index also includes protocol/type totals and a module summary. The `.sproto`
file retains the full definitions, comments, indentation, and declaration order.
Only `.sproto` and `.md` files are generated.

## How change detection works

Each MD5 covers the protocol's text from its name through its matching closing
brace, including its tag, inline definitions, comments, and internal whitespace.
Line endings are normalized to LF before hashing.

Moving an unchanged block or adding text elsewhere leaves its hash unchanged.
Editing content inside the block changes its hash. Separately declared shared
types are outside the hash; changing those definitions does not change the hash
of a protocol that refers to them by name.

## Supported inputs

The Lua file must return a static schema string. Quoted strings, long-bracket
strings, concatenation, and preceding local string constants are supported.
Function calls, `require(...)`, loops, and other dynamic Lua are not evaluated.

See the [usage guide](docs/USAGE.md) for examples, newline options, reference
comparison, and the complete command-line reference.

## Tests and contributions

```sh
python -m unittest discover -s tests -v
```

The tests create their own small inputs and need no external file collection.
CI runs them on Windows and Linux. See [CONTRIBUTING.md](CONTRIBUTING.md) for
development and issue-reporting guidance.

## License

[MIT](LICENSE).
