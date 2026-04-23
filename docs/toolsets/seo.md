# SEO toolsets

SEO is split into two toolsets so reads can ship on by default
without dragging mutation along with them.

* `seo_query` — read SEO metadata, run audits, generate sitemaps. **On by default.**
* `seo_write` — narrow SEO field updates and sitemap regeneration. **Off by default.**

```python
WAGTAIL_MCP_SERVER = {
    "TOOLSETS": {
        "seo_query": {"enabled": True},   # default
        "seo_write": {"enabled": True},   # opt in
    },
}
```

## `seo_query` tools

### `seo.get`

Returns the SEO-relevant fields for a single page: `seo_title`,
`search_description`, canonical URL, `og_image` reference, and a
`findings` list of any audit issues that apply.

### `seo.audit`

Walks live pages and returns audit findings keyed by page id.
Filterable by `min_severity` (`info` < `warn` < `error`) and
optional page-id list.

The rule table is intentionally stable across releases:

| Code                       | Severity | Triggers when                              |
|----------------------------|----------|--------------------------------------------|
| `title_missing`            | error    | `seo_title` (or `title` fallback) is empty |
| `title_too_short`          | warn     | < 30 characters                            |
| `title_too_long`           | warn     | > 60 characters                            |
| `description_missing`      | warn     | `search_description` is empty              |
| `description_too_short`    | info     | < 50 characters                            |
| `description_too_long`     | warn     | > 160 characters                           |
| `og_image_missing`         | info     | No `og_image` set                          |

Agents can rely on the `(code, severity)` tuple — adding a rule is
additive, removing one is a breaking change and would bump the
toolset's contract version.

### `seo.sitemap`

Returns a sitemap-style list of `{loc, lastmod, changefreq, priority}`
for every live page that resolves to a full URL. Independent of
`wagtail.contrib.sitemaps` — works whether or not the contrib app is
installed.

## `seo_write` tools

### `seo.update`

A narrow alternative to `pages.update` that only accepts the four
SEO fields:

* `seo_title`
* `search_description`
* `slug`
* `og_image` — image id or `null` to clear

Anything else in the payload raises (strict, not silently dropped
like `pages.update`). Returns the post-write `findings` so the agent
can verify the fix actually moved the rule into a passing range.

### `seo.sitemap.regenerate`

Site-wide regeneration trigger. New in v0.5. Counts live pages,
optionally clears configured cache keys, and fires the
`sitemap_regenerated` signal so a host project can hook into it
(CDN purge, reverse-proxy invalidation, queue another job, etc.).

Requires `wagtailadmin.access_admin`.

## Gotchas

* `seo.audit` skips draft and unpublished pages by design. Agents that need pre-publish QA should pair this with `pages.preview`.
* `og_image` is exposed as a Wagtail Image id, not a URL. Agents that need a fillsize URL should call `media.images.get` and read the rendition.
* `seo.sitemap.regenerate` doesn't *write* a sitemap file — it triggers your project's own regeneration pipeline via the signal. The library has no opinion on whether you serve the sitemap from disk, from Redis, or compute it per-request.
