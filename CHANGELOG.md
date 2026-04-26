# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.5.2] - 2026-04-26

### Changed
- **Django pin widened from `>=5.0,<5.2` to `>=5.0,<6.0`** so the library installs on Django 5.2.x. Required for host projects running Python 3.14: Django 5.1 has a `copy(super())` pattern in `django.template.context.BaseContext.__copy__` that Python 3.14 broke, surfacing as `AttributeError: 'super' object has no attribute 'dicts' and no __dict__ for setting new attributes` on Wagtail's `/cms/login/` template render. Django 5.2 fixed this. Wagtail 7.3 already supports Django 5.2 per its compatibility matrix; the library itself uses no Django 5.1-only APIs, so the previous pin was conservatism, not principle. Discovered while integrating Wagtail into the Claret project (Python 3.14 + Django 5.1.15 + Wagtail 7.3); see `claret-platform-sprint-06.md` §3.3 #14 for the host-project context.
- **Trove classifiers extended** with `Framework :: Django :: 5.2`, `Programming Language :: Python :: 3.13`, and `Programming Language :: Python :: 3.14` to reflect the broader compat surface.

### Notes for host projects
- No code changes. This is a packaging-only release.
- Lex (the original adopter) currently pins to v0.5.1; v0.5.2 is opt-in for host projects that need Django 5.2 or Python 3.14 support. Bumping is strictly safe; the library binary is byte-identical to v0.5.1.

## [0.5.1] - 2026-04-23

### Fixed
- **`pages.get` Locale serialization.** `_serialize_meta` surfaced the `locale` field by pushing the raw `wagtail.models.Locale` instance through `_to_json_safe`, which only coerced datetimes. The MCP JSON encoder downstream then raised `Unable to serialize unknown type: <class 'wagtail.models.i18n.Locale'>`, breaking `pages.get` for every page on Wagtail 7.3+ (every `Page` carries a locale FK). `_to_json_safe` now converts `Locale` instances to their `language_code` string, matching the documented `"meta.locale": "en"` shape. Other tools were unaffected because they emit the lean `{_raw_id, id, title, slug, url_path, page_type}` page dict rather than the full serialized payload. Added a regression test in `tests/test_page_serializer.py::test_meta_locale_is_language_code_string` that `json.dumps` the full payload to catch encoder-level regressions too.

## [0.5.0] - 2026-04-22

### Added
- **`CollectionsQueryToolset`** (on by default): `collections.list`, `collections.get`, `collections.tree`. Read-only access to Wagtail's Collection tree — the unit of access control for the media toolset and a frequent ask from agents that want to scope listings to a specific section. Tree assembly happens in Python after a single pre-fetch; `collections.get` returns `None` (not an error) for unknown ids.
- **`SnippetsQueryToolset`** (on by default): `snippets.types`, `snippets.list`, `snippets.get`. Enumerates `@register_snippet` models, paginates instances, and returns a single instance by type + id. Reads `api_fields` if defined, falls back to plain Django fields. M2M is intentionally skipped (round-trip is ambiguous in v0.5).
- **`RedirectsToolset`** with split-flag config: `enabled_read` on by default, `enabled_write` off by default. Read tools `redirects.list` / `redirects.get`; write tools `redirects.create` / `redirects.update` / `redirects.delete`. Delete is gated by the three-gate destructive pattern (toolset + `LIMITS.ALLOW_DESTRUCTIVE` + `wagtailredirects.delete_redirect`). The split-flag pattern is `redirects`-only in v0.5; other toolsets continue using the single `enabled` key.
- **`pages.preview`** under `pages_query`: returns the latest *revision* state for a page rather than the published state. Requires `view_revision`. Pairs with `seo.audit` for pre-publish QA without a publish step.
- **`seo.sitemap.regenerate`** under `seo_write`: site-wide sitemap regeneration trigger. Counts live pages, optionally clears configured cache keys, fires the new `sitemap_regenerated` signal so host projects can plug in CDN purge / reverse-proxy invalidation. Independent of `wagtail.contrib.sitemaps`.
- **`media.images.focal_point`**: sets the focal-point rectangle Wagtail uses for fill-size renditions, with bounds validation against the source image. Distinct from `media.images.update`, which is lenient about partial-state field updates.
- **`mcp_prune_audit` management command**: enforces `AUDIT.RETENTION_DAYS` against the `ToolCall` table. Flags: `--dry-run`, `--batch-size N`, `--older-than DAYS`. Designed to be wired into cron or Celery beat; the library does not run a scheduler of its own.
- **Standalone `wagtail-mcp-serve` console script**: bundles a self-contained Django settings module (`wagtail_mcp_server.standalone.settings`), a per-OS data dir (XDG on Linux, `~/Library/Application Support` on macOS, `%LOCALAPPDATA%` on Windows), a sticky `SECRET_KEY` persisted to a 0600 file, and an idempotent first-boot bootstrap that mints a superuser plus an MCP token (printed to **stderr** — stdout is reserved for MCP frames). Default toolset surface is reads-only; flips to writes via `WMS_OVERRIDE_*` env vars or a custom settings module. New flag set: `--stdio` / `--http`, `--host`, `--port`, `--data-dir`, `--settings`, `--no-migrate`, `--no-bootstrap`, `--bootstrap-username`.
- **MkDocs Material documentation site** under `docs/`, with a `.github/workflows/docs.yml` that builds + deploys to GitHub Pages on push to main. Per-toolset reference pages, operations pages (auditing, OpenTelemetry, tokens), and a dedicated standalone-runtime guide.
- 17 in-process tests for the standalone runtime (`tests/test_standalone.py`) and 8 subprocess smoke tests (`tests/test_standalone_subprocess.py`) covering `--help`, full bootstrap, idempotence, sticky `SECRET_KEY`, custom settings, mutex flag rejection. New HTTP endpoint tests for the valid-token gate, impersonation regression, empty-auth-classes path, and `_load_enabled` toolset toggle. Full suite: 155 → 200+, all green.

### Changed
- **`AUDIT.EMIT_OTEL` defaults to `True`**. The library imports only the OpenTelemetry *API* (never the SDK), so when no SDK is configured in the host process spans go to the API's no-op tracer for ~µs of overhead and zero network I/O. Hosts that have wired up a tracer provider get spans for free; hosts that haven't pay nothing. Set to `False` to suppress emission explicitly.
- `registry.TOOLSET_MAP` now includes `collections_query`, `snippets_query`, and `redirects` alongside the v0.4 toolsets. `registry.loaded_toolsets()` continues to be the supported way to introspect the live surface.
- `pyproject.toml` adds a `docs` optional-dependencies group (`mkdocs`, `mkdocs-material`, `pymdown-extensions`) for the docs build pipeline. A new `[project.scripts]` entry registers `wagtail-mcp-serve` alongside the existing `wagtail-mcp-server` dispatcher.

### Notes for host projects
- **Action required for `collections_query` / `snippets_query`**: these are on by default. If you have a strict allow-list of toolsets in your `WAGTAIL_MCP_SERVER["TOOLSETS"]`, you must explicitly disable them or include them — they are not silently grandfathered in.
- **Action required for `redirects`**: the split-flag pattern means existing config that passed `{"enabled": True}` for redirects will be ignored; use `{"enabled_read": True, "enabled_write": False}` instead. The library logs a warning at startup if it sees the old shape.
- **Action recommended for `AUDIT.EMIT_OTEL`**: hosts that want to suppress emission must now do so explicitly. The default flip is safe — emission to a no-op tracer costs nothing — but it changes observable behavior for hosts that have an OTel SDK configured but didn't expect MCP traffic in their span ingest.
- **Standalone runtime is for laptops and demos**, not production. For production, embed the app in your existing Wagtail project so you get its database, auth, and asset storage. See `docs/standalone.md` for the full caveats list.
- No new migrations. Upgrading from 0.4.0 requires no DB changes.

## [0.4.0] - 2026-04-22

### Added
- **HTTP transport wiring**. `wagtail_mcp_server.urls` now publishes `MCPServerStreamableHttpView` at the empty path so host projects mount it with `path("mcp/", include("wagtail_mcp_server.urls"))`. A new `UserTokenDRFAuth` adapter (`wagtail_mcp_server.auth.UserTokenDRFAuth`) implements the DRF `BaseAuthentication` contract, delegates to the existing `UserTokenAuth` backend, and populates `request.user` before the MCP dispatcher captures the request. Auth class resolution reads `WAGTAIL_MCP_SERVER_AUTH_CLASSES` first, then `DJANGO_MCP_AUTHENTICATION_CLASSES`, and defaults to `UserTokenDRFAuth`. Missing Authorization header returns 401 with a `WWW-Authenticate: Bearer realm="wagtail-mcp-server"` prompt.
- **Config-gated autodiscover**. `wagtail_mcp_server.mcp` is the new entry point consumed by django-mcp-server's `autodiscover_modules('mcp')` pass. The module imports toolsets conditionally on `WAGTAIL_MCP_SERVER.TOOLSETS[<slug>].enabled`, so disabled toolsets never trigger `ToolsetMeta` registration and never leak onto the MCP wire. A broken toolset module is logged and skipped rather than taking the whole surface down. The frozen list of loaded slugs is surfaced via `registry.loaded_toolsets()`.
- **HTTP endpoint smoke tests** (`tests/test_http_endpoint.py`): 4 tests covering no-auth, GET with no auth, bogus bearer token (exercises the full `UserTokenDRFAuth` -> `UserTokenAuth` -> `UserMcpToken` lookup path), and non-Bearer schemes. Full tools/list round-trip with a seeded token is intentionally deferred to 0.5.0.

### Changed
- **Toolsets now inherit directly from `mcp_server.djangomcp.MCPToolset`** instead of going through an in-tree adapter. Tools resolve the caller from `self.request.user` (populated by DRF auth) rather than taking an explicit `user` positional argument. The adapter layer is gone; there is one class hierarchy, one source of truth for registration.
- **Test suite rewritten** for the new toolset constructor contract. A `bind_user` fixture attaches a `SimpleNamespace(user=user)` stand-in to `toolset.request` before each call, bypassing the HTTP layer while faithfully matching what the DRF auth class populates in production. 149 -> 155 tests, all green.
- `registry.TOOLSET_MAP` now re-exports the mapping defined in `wagtail_mcp_server.mcp` so existing operator imports keep working; `registry.loaded_toolsets()` is the supported way to introspect what actually went live.

### Notes for host projects
- **Action required**: host projects that previously included `mcp_server.urls` or `wagtail_mcp_server.urls` under a `mcp/` prefix should keep the same URL but rely on this library's `urls.py` (not upstream's). `mcp_server.urls` hard-codes an additional `DJANGO_MCP_ENDPOINT` prefix and would resolve the view at `/mcp/mcp/` under a canonical `/mcp/` mount. This library intentionally does not include upstream's urlconf.
- Auth resolution prefers `WAGTAIL_MCP_SERVER_AUTH_CLASSES` over `DJANGO_MCP_AUTHENTICATION_CLASSES` so hosts can layer project-specific auth classes without touching the upstream setting. Setting either to an empty list disables auth; do this only for local dev.
- No new migrations. Upgrading from 0.3.0 requires no DB changes.

## [0.3.0] - 2026-04-22

### Added
- **WorkflowToolset** (off by default): `workflow.submit`, `workflow.approve`, `workflow.reject`, `workflow.cancel`, `workflow.state`. Permission model delegates to Wagtail's `task.get_actions(page, user)` contract so custom Task subclasses (GroupApprovalTask and anything downstream projects register) work out of the box. Workflow actions are not gated by `LIMITS.ALLOW_DESTRUCTIVE` — reject and cancel are recoverable.
- **MediaToolset** (off by default): `media.images.list/get/get_upload_url/finalize/update` and `media.documents.*` equivalents. Presign-then-finalize flow means bytes never touch Django — the agent PUTs direct to the S3-compatible bucket (Cloudflare R2 in the Lex deployment). Content-type allow-lists (image: jpeg/png/gif/webp/svg+xml; document: pdf/doc/xlsx/pptx/csv/txt/md/json) guard against script-in-svg and similar foot-guns. Upload tokens are `TimestampSigner`-signed JSON blobs bound to user, key, content_type, max_size, and kind; TTL 10 min. `get_upload_url` refuses non-S3-compatible default_storage (loud failure, not silent fallback to filesystem).
- **SEOWriteToolset** (off by default): `seo.update` lets agents fix `seo_title`, `search_description`, `slug`, and `og_image` in one call, optionally publishing. Unknown fields raise before any DB mutation happens. Response carries post-write findings so the agent can verify the fix worked.
- 26 new tests: 11 for WorkflowToolset (auth, no-workflow path, happy path + cancel + approve), 8 for SEOWriteToolset (happy path, validation, findings round-trip), 20 for MediaToolset (auth, read path, content-type gate, S3-compatibility gate, presign, token tampering). Full suite: 103 → 137, all green.

### Changed
- `registry.TOOLSET_MAP` and `AppConfig.ready` now load `WorkflowToolset`, `MediaToolset`, and `SEOWriteToolset` alongside the existing toolsets.

### Notes for host projects
- All three new toolsets are off by default. Opt in via `WAGTAIL_MCP_SERVER["TOOLSETS"][<name>]["enabled"] = True`.
- `media` requires django-storages' `S3Storage` (or any storage that exposes a boto3-style `.connection` + `.bucket_name`). The toolset refuses to mint presigned URLs against `FileSystemStorage`.
- No new migrations. Host projects upgrading from 0.2.0 need no DB changes.

## [0.2.0] - 2026-04-22

### Added
- **SEOQueryToolset** (on by default): `seo.get`, `seo.audit`, `seo.sitemap`. Ships a stable rule table (`title_missing`/`title_too_short`/`title_too_long`/`description_missing`/`description_too_short`/`description_too_long`/`og_image_missing`) with a frozen `(code, severity)` contract. Sitemap is intentionally independent of `wagtail.contrib.sitemaps`.
- **PageWriteToolset** (off by default): `pages.create`, `pages.update`, `pages.publish`, `pages.unpublish`, `pages.delete`, `pages.move`. Three-gate destructive writes: toolset enabled + `LIMITS.ALLOW_DESTRUCTIVE` + Wagtail permission. Draft-create flow sets `live=False, has_unpublished_changes=True` on the new page (matches the admin "Save draft" behavior).
- **StreamField write-path validator** (`deserialize_streamfield`): strict envelope validation with closed-vocabulary error codes (`unknown_block_type`, `unknown_child`, `missing_required`, `type_mismatch`, `invalid_chooser_ref`, `invalid_richtext`, `envelope_shape`). Errors carry `path`, `expected`, and `got` so the calling agent can self-correct. `DeserializeOptions(validation="strict"|"permissive")` selects the mode; default is strict. ChooserBlock writes accept `int`, `{"_raw_id": int}`, or an already-resolved instance.
- 40 new tests: 10 for the write validator, 12 for SEOQueryToolset, 18 for PageWriteToolset. Full suite: 63 → 103, all green.

### Changed
- `registry.TOOLSET_MAP` and `AppConfig.ready` now resolve and load `SEOQueryToolset` and `PageWriteToolset` alongside the existing toolsets.
- Hand-written `0001_initial` migration reconciled with Django 5.1's autogen shape (`verbose_name="ID"` on `BigAutoField`, canonical index name, `help_text` on `UserMcpToken.label`/`token_prefix`). `makemigrations --check` is now clean.

### Notes for host projects
- Run `./manage.py migrate wagtail_mcp_server` before issuing agent tokens.
- Write toolsets remain off until host explicitly opts in: `WAGTAIL_MCP_SERVER["TOOLSETS"]["pages_write"]["enabled"] = True` and `WAGTAIL_MCP_SERVER["LIMITS"]["ALLOW_DESTRUCTIVE"] = True` (the second is only required for `pages.delete`).

## [0.1.0] - 2026-04-21

### Added
- Initial scaffold: Django app, settings resolver, auth backends, token models, CLI wrapper, OTel emitter, StreamField envelope contract, toolset shells for pages_query, pages_write, workflow, media, seo_query, seo_write.
- BSD-3-Clause LICENSE.
- GitHub Actions CI matrix across Python 3.11 / 3.12 and Wagtail 7.3.1 / main.
- pytest suite covering settings validation, envelope shape, and import invariants.
