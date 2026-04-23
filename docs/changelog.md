# Changelog

The full changelog lives at the repository root: see
[CHANGELOG.md](https://github.com/Deku-Studios/wagtail-mcp-server/blob/main/CHANGELOG.md).

A summary of headline changes per release follows.

## 0.5.0 — final for launch

* `CollectionsQueryToolset` (on by default).
* `SnippetsQueryToolset` (on by default).
* `RedirectsToolset` with split flags (`enabled_read` on, `enabled_write` off by default).
* `pages.preview` for in-flight draft inspection.
* `seo.sitemap.regenerate` for site-wide sitemap refresh.
* `media.images.focal_point` for fill-rendition crop control.
* `mcp_prune_audit` management command for retention enforcement.
* `AUDIT.EMIT_OTEL` defaults to `True` (no-op when no SDK is configured).
* Standalone `wagtail-mcp-serve` console script — bundles its own SQLite settings, no host Django project required.
* MkDocs Material documentation site published to GitHub Pages.

## 0.4.0

* HTTP transport wired in. `wagtail_mcp_server.urls` publishes
  the streamable HTTP view; `UserTokenDRFAuth` adapts the existing
  token backend for DRF.
* Config-gated autodiscover: disabled toolsets are not imported.
* Audit log + token introspection.

## 0.3.0

* WorkflowToolset, MediaToolset, SEOWriteToolset (all off by default).

## 0.2.0

* SEOQueryToolset (on by default).
* PageWriteToolset (off by default).
* StreamField write-path validator with closed-vocabulary errors.

## 0.1.0

* Initial scaffold: settings resolver, auth backends, token models,
  CLI wrapper, OTel emitter, StreamField envelope contract, toolset
  shells.
