# Contributing

## Development setup

Use Python 3.9 or newer. No package installation or Lua interpreter is needed.

```sh
python sproto_dumper.py --help
python -m unittest discover -s tests -v
```

The implementation is a standalone file, `sproto_dumper.py`. Tests are under
`tests/`, and `examples/sample.lua` is a small, original schema module.

## Making changes

Keep fixes focused and add a small regression case for changed behavior.
Tests should create their inputs in temporary directories and remain independent
of external file collections.

For extraction changes, check exact bytes, escapes, Unicode, comments, and
line endings. For indexing changes, check nested types, protocol ordering,
endpoint indicators, and duplicate declarations. For hashing changes, ensure
that moving an unchanged block does not change its MD5 and that an edit inside
one block changes only that protocol's row.

Keep the output as plain Markdown with one row per protocol and no line-number
links. Use the bundled example when updating documentation.

## Reporting an issue

Include the command, Python version, operating system, expected result, actual
result, and a small reproducer you can share. Avoid credentials, personal paths,
or private schema collections.

## Before a pull request

- Run the test suite and the documented example command.
- Update usage documentation when behavior changes.
- Review `git diff --cached` for unintended files or data.
- Keep generated output, caches, logs, and local validation artifacts out of Git.

The repository excludes `sproto_files/`, `output/`, `reference_output/`, and
`validation/` to keep local artifacts private. Do not force-add those folders.

## License

Contributions are distributed under the repository's MIT license. Preserve its
copyright and permission notice, including the notice in the standalone script.
