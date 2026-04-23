# Toolsets overview

A *toolset* is a Python class that bundles related MCP tools and the
permission rules they share. Toolsets are gated by config: a toolset
that isn't `enabled` in `WAGTAIL_MCP_SERVER["TOOLSETS"]` is never
imported, never registered with the MCP dispatcher, and never appears
on the wire.

## What ships in v0.5

| Toolset                | Default | What it does                                      | Needs                                       |
|------------------------|---------|---------------------------------------------------|---------------------------------------------|
| `pages_query`          | **on**  | List, get, tree, search, preview, type schemas    | View permission on target pages             |
| `seo_query`            | **on**  | Per-page SEO read, site-wide audit, sitemap       | View permission                             |
| `collections_query`    | **on**  | List/get/tree of Wagtail Collections              | Authenticated user                          |
| `snippets_query`       | **on**  | Enumerate registered snippet types and instances  | Authenticated user; per-type view perm      |
| `redirects` (read)     | **on**  | List/get from `wagtail.contrib.redirects`         | Authenticated user                          |
| `pages_write`          | off     | Create, update, publish, unpublish, move, delete  | Wagtail page perms; delete needs `ALLOW_DESTRUCTIVE` |
| `seo_write`            | off     | Narrow SEO field updates + sitemap regen          | Edit perm; admin perm for regen             |
| `media`                | off     | Image and document upload + metadata              | S3-compatible storage; collection perms     |
| `workflow`             | off     | Submit, approve, reject, cancel moderation        | Wagtail workflow / task perms               |
| `redirects` (write)    | off     | Create, update, delete redirects                  | `wagtailredirects.*` perms; delete needs `ALLOW_DESTRUCTIVE` |

## Two design principles

### Reads default on, writes default off

Every read toolset is enabled out of the box because reads are
non-destructive and pose minimal risk. Every write toolset is
explicitly opt-in. This matches the principle that an agent dropped
into an unfamiliar Wagtail should be able to *answer questions* about
the site without anyone having to think about safety, but should not
be able to *change anything* without an explicit configuration choice.

### Three gates for destructive operations

Anything that cannot be trivially undone (page delete, redirect delete,
hard-delete media) requires three things to be true at the same time:

1. The toolset is enabled in `WAGTAIL_MCP_SERVER["TOOLSETS"]`.
2. `LIMITS.ALLOW_DESTRUCTIVE = True`.
3. The acting user has the underlying Wagtail permission.

Recoverable mutations (page update, page unpublish, workflow reject,
workflow cancel, redirect create) only need the toolset flag plus the
permission. The third gate exists to make `delete` decisions
deliberate, not to make routine editing painful.

## Discovering what's loaded

```bash
python manage.py mcp_introspect
```

Prints the resolved toolset list, the tools each one exposes, and
their input/output schemas. Use it to verify the surface an agent
will see before pointing it at production.

```python
from wagtail_mcp_server.registry import loaded_toolsets

loaded_toolsets()
# {'pages_query', 'seo_query', 'collections_query', 'snippets_query', 'redirects'}
```

`loaded_toolsets()` is the supported way to introspect the live
surface from inside Django. `registry.TOOLSET_MAP` is a stable
re-export and continues to work for older code that imported it
directly.

## Per-toolset reference

Each page below covers the tools the toolset exposes, the parameters
they accept, the permissions they require, and the gotchas worth
knowing before you wire an agent at it.

* [Pages (read)](pages-query.md)
* [Pages (write)](pages-write.md)
* [SEO](seo.md)
* [Media](media.md)
* [Workflow](workflow.md)
* [Collections + Snippets](collections-snippets.md)
* [Redirects](redirects.md)
