# Contributing

Thanks for considering a contribution. This project is early and the API is still in flux, so coordination up front saves rework.

## Ground rules

- Open a [Discussion](https://github.com/Deku-Studios/wagtail-mcp-server/discussions) before writing a non-trivial PR. Bug fixes are fine to PR directly.
- The project is BSD-3-Clause. By submitting a PR you agree your contribution is licensed the same way.
- Write toolsets must be off by default. New tools ship with a test that verifies the default config leaves them disabled.
- The Wagtail version floor is 7.3.1. We do not accept patches that target older Wagtail versions.

## Development setup

```bash
git clone https://github.com/Deku-Studios/wagtail-mcp-server
cd wagtail-mcp-server
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
pre-commit install  # optional, when hooks land
```

Run the tests and linter:

```bash
pytest
ruff check .
```

## Writing a new tool

1. Pick the right toolset file under `src/wagtail_mcp_server/toolsets/`. Read toolsets end in `_query`; write toolsets either stand alone (`workflow`, `media`) or end in `_write`.
2. Define the tool's input with a Pydantic model. Keep field names lowercase\_snake.
3. Use the serializers in `src/wagtail_mcp_server/serializers/` for anything that crosses the wire. StreamField walks always use the `{type, id, value}` envelope.
4. Every tool has a test in `tests/`. Write-tool tests assert the tool is a no-op when the toolset flag is off.

## Commit style

Conventional Commits preferred (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`), but not enforced. Keep commits focused.

## Reporting security issues

Do not open a public issue. Email `security@dekustudios.com`. We will acknowledge within 72 hours.
