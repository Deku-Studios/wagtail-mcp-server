# `collections_query` + `snippets_query`

Two read-only toolsets that surface Wagtail's organisational and
non-page model surfaces. Both ship on by default in v0.5.

```python
WAGTAIL_MCP_SERVER = {
    "TOOLSETS": {
        "collections_query": {"enabled": True},  # default
        "snippets_query":    {"enabled": True},  # default
    },
}
```

## `collections_query`

Wagtail Collections are the tree structure media (and sometimes
snippets) live under. They're the unit of access control for the
media toolset.

### Tools

| Tool                  | What it returns                                |
|-----------------------|------------------------------------------------|
| `collections.list`    | Flat list of every collection                  |
| `collections.get`     | Single collection by id, with ancestor chain   |
| `collections.tree`    | Nested hierarchy from a root id                |

### Permissions

Authenticated callers only. Anonymous calls are rejected. The toolset
exposes collection *names* and *structure* — not the documents or
images inside them; access to those is gated by the `media` toolset.

### Notes

* `collections.tree` is pre-fetched and assembled in Python rather than walked recursively over the DB.
* `collections.get` returns `None` (not an error) for an unknown id.
* Collections never expose deleted or "unfiled" placeholder rows.

## `snippets_query`

Wagtail snippets are arbitrary Django models registered with
`@register_snippet`. Common uses: site-wide menus, footer content,
authors, FAQ entries, anything reusable across pages.

### Tools

| Tool                  | What it returns                                |
|-----------------------|------------------------------------------------|
| `snippets.types`      | Every registered snippet model with app + verbose name |
| `snippets.list`       | Paginated list of instances of a given type    |
| `snippets.get`        | Single instance by type + id                   |

### Permissions

Authenticated callers only. Per-type view permission applies:
superusers and staff with `view_<modelname>` see everything;
everyone else sees what their permissions allow. Querying an
unregistered type raises (not silent empty list) so an agent's typo
doesn't masquerade as "no results".

### Field surfacing

The toolset reads `api_fields` if the snippet model defines it; if
not, falls back to plain Django fields.

* `ForeignKey` → integer pk
* `ManyToManyField` → skipped in v0.5 (round-trip is ambiguous)
* `RichTextField` → serialised per `RICHTEXT_FORMAT`
* `StreamField` → standard envelope

If a snippet model has methods you'd like exposed (e.g. computed
URLs), add them to its `api_fields`.

### Gotchas

* `snippets.list` paginates by `LIMITS.MAX_PAGE_SIZE` like the page tools.
* `snippets.get` doesn't follow custom URL patterns the snippet might define — use `snippets_query` for data, not for resolving links.
* Writes for snippets are not in v0.5. They're on the post-launch list because the per-type permission mapping needs to handle the long tail of `register_snippet` patterns; for now, agents that need to mutate snippets should do it through the Wagtail admin or a project-specific tool.
