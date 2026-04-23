# Standalone runtime

`wagtail-mcp-serve` is a console script bundled with the package that
spins up an MCP server with no host Django project required. It ships
its own SQLite database, a sticky `SECRET_KEY`, sensible read-only
toolsets, and an idempotent first-boot bootstrap that mints a
superuser plus an MCP token.

It's the fastest way to try the protocol against Wagtail and the
right answer for desktop clients that "just want a Wagtail to talk
to".

## Installation

```bash
pip install wagtail-mcp-server
```

The package registers two console scripts:

| Command | When to use it |
|---------|----------------|
| `wagtail-mcp-server` | Existing Django project. Dispatches into `manage.py` commands. |
| `wagtail-mcp-serve`  | Standalone. Bundles its own settings + SQLite. |

## Quick start

```bash
wagtail-mcp-serve --stdio
```

Or over HTTP:

```bash
wagtail-mcp-serve --http --host 127.0.0.1 --port 8765
```

## What it puts on disk

By default, all state lives under one directory. Override with
`--data-dir <path>` or `WMS_DATA_DIR=<path>`.

| OS      | Default location |
|---------|------------------|
| Linux   | `$XDG_DATA_HOME/wagtail-mcp-server` (or `~/.local/share/wagtail-mcp-server`) |
| macOS   | `~/Library/Application Support/wagtail-mcp-server` |
| Windows | `%LOCALAPPDATA%\wagtail-mcp-server` |

Inside that directory:

```
db.sqlite3        the Wagtail database
secret_key        regenerated only if missing (mode 0600)
media/            user-uploaded images, documents
static/           collected static (only after manage.py collectstatic)
```

The `secret_key` file is sticky — subsequent boots reuse the same
value, so signed cookies and sessions survive restarts.

## First boot

The first time you run `wagtail-mcp-serve` against an empty data dir
it prints something like this **to stderr** (stdout is reserved for
MCP frames):

```
wagtail-mcp-serve: first-boot bootstrap complete.
  Superuser: admin  (random password set; use `manage.py changepassword admin` if you need to log in)
  MCP token: r5Tw0X-EXAMPLE-SaveThisNow
  Save the token now -- it will not be shown again.
```

Hand the token to your MCP client. It's the only credential the
client needs.

The bootstrap is idempotent: if any `UserMcpToken` row exists, the
bootstrap step is a no-op on subsequent boots.

## Default toolsets

The standalone runtime ships with **only the read-only toolsets** on:

| Toolset            | Default in standalone |
|--------------------|-----------------------|
| `pages_query`      | enabled |
| `seo_query`        | enabled |
| `collections_query`| enabled |
| `snippets_query`   | enabled |
| `redirects` (read) | enabled |
| `pages_write`      | **disabled** |
| `workflow`         | **disabled** |
| `media`            | **disabled** |
| `seo_write`        | **disabled** |
| `redirects` (write)| **disabled** |

This matches the library's safe-by-default posture. Writes are off
because the standalone runtime is most often used for "tinker on my
laptop" or "let an agent read my staging site" — situations where
mutation isn't expected.

## Enabling write toolsets

Two routes:

### Quick: env-var overrides

For one-off experiments, the standalone settings module honours these
environment variables (any truthy value flips them on):

```bash
WMS_OVERRIDE_PAGES_WRITE=1 wagtail-mcp-serve --stdio
WMS_OVERRIDE_REDIRECTS_WRITE=1 wagtail-mcp-serve --stdio
WMS_OVERRIDE_ALLOW_DESTRUCTIVE=1 wagtail-mcp-serve --stdio
WMS_OVERRIDE_ALLOW_IMPERSONATION=1 wagtail-mcp-serve --stdio
```

Recognised: `WMS_OVERRIDE_PAGES_WRITE`, `WMS_OVERRIDE_WORKFLOW`,
`WMS_OVERRIDE_MEDIA`, `WMS_OVERRIDE_SEO_WRITE`,
`WMS_OVERRIDE_REDIRECTS_WRITE`, `WMS_OVERRIDE_ALLOW_DESTRUCTIVE`,
`WMS_OVERRIDE_ALLOW_IMPERSONATION`.

### Proper: a custom settings module

For anything beyond a flag flip, write a real Django settings module
and point `wagtail-mcp-serve` at it:

```python
# my_wms_settings.py
from wagtail_mcp_server.standalone.settings import *  # noqa: F401, F403

WAGTAIL_MCP_SERVER["TOOLSETS"]["pages_write"] = {"enabled": True}
WAGTAIL_MCP_SERVER["LIMITS"]["MAX_PAGE_SIZE"] = 100
```

```bash
wagtail-mcp-serve --settings my_wms_settings --stdio
```

The `--settings` flag is equivalent to setting
`DJANGO_SETTINGS_MODULE` before launch.

## Flag reference

```text
--stdio                       Run over stdio (default if no transport given)
--http                        Run over HTTP+SSE
--host HOST                   HTTP bind host (default 127.0.0.1)
--port PORT                   HTTP bind port (default 8765)
--data-dir DATA_DIR           Override the data directory
--settings SETTINGS           Use a custom Django settings module
--no-migrate                  Skip the auto-migrate step on boot
--no-bootstrap                Skip the first-boot superuser+token bootstrap
--bootstrap-username USER     Username to create on first boot (default admin)
```

## Production caveats

The standalone runtime is for laptops and demos. For production:

* Use the embedded path (`INSTALLED_APPS += ["wagtail_mcp_server"]`)
  in your existing Wagtail project so you get its database, auth,
  and asset storage.
* The standalone runtime hosts media and static files in its data
  dir; that's fine for one user, but won't scale.
* The bundled `SECRET_KEY` lives in a plain file; production
  deployments should use a secrets manager.

If you need standalone-style ergonomics in production (e.g. running
the MCP transport as a sidecar), write your own settings module
that points at your real database and use `--settings my_settings`.
