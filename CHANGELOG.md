# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
