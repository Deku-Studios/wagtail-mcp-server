# `pages_query` — read pages

The default-on read surface for pages. Lists, gets, walks the tree,
previews drafts, and exposes per-type schemas so an agent can
discover what fields each page type supports.

```python
WAGTAIL_MCP_SERVER = {
    "TOOLSETS": {
        "pages_query": {"enabled": True},  # on by default
    },
}
```

## Tools

### `pages.list`

Paginated list of pages, optionally filtered.

| Param         | Type    | Notes                                              |
|---------------|---------|----------------------------------------------------|
| `parent_id`   | int?    | Restrict to direct children of this page id        |
| `type`        | str?    | Filter by app-qualified page type, e.g. `home.HomePage` |
| `locale`      | str?    | Wagtail locale code                                |
| `search`      | str?    | Full-text search (Wagtail backend)                 |
| `live_only`   | bool    | Defaults `True` for anonymous, configurable for auth |
| `page`        | int     | 1-indexed                                          |
| `page_size`   | int     | Capped by `LIMITS.MAX_PAGE_SIZE` (default 50)      |

Returns `{items: [...], page, page_size, total}`.

### `pages.get`

Single page by id, returning the full API payload (including
StreamField content as the configured `RICHTEXT_FORMAT`).

### `pages.tree`

Page hierarchy from a root id. Useful for nav generation and
sitemap-style traversal.

### `pages.preview`

Returns the latest *revision* (draft) state for a page rather than
the published state. Requires `view_revision` permission. Distinct
from `pages.get`, which always returns the live version.

Use this when an agent is reviewing in-flight edits before publish.

### `pages.search`

Wagtail-search-backed full-text query. Honours
`LIMITS.MAX_SEARCH_RESULTS`.

### `pages.types`

Lists every concrete `Page` subclass registered in the project,
including the app label and verbose name. No parameters.

### `pages.types.schema`

Returns the JSON schema for a specific page type, including
StreamField block definitions. The shape is the same one
`pages.create` and `pages.update` will accept on writes — meaning
an agent can introspect the schema, then construct a valid payload
without trial-and-error.

## Permissions

Anonymous callers see live pages only. Authenticated callers see
pages they have `view_page` permission for. Drafts surfaced through
`pages.preview` additionally require `view_revision`.

## Gotchas

* StreamField in the response uses `{"type": ..., "id": ..., "value": ...}` envelopes per Wagtail's own API. Same shape goes back in on `pages.update`.
* `RICHTEXT_FORMAT = "html"` (default) returns RichText as serialized HTML. Switch to `"draftail"` if your agent needs to round-trip edits without semantic loss.
* `pages.types.schema` reflects the *current* model definitions; if you ship a migration that adds a field, the schema picks it up at the next request.
