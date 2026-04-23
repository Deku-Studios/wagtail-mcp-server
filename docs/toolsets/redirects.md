# `redirects` — manage `wagtail.contrib.redirects`

Wraps Wagtail's redirects contrib app. Uses the **split-flag**
config pattern so the read side can ship on by default while the
write side stays opt-in.

```python
WAGTAIL_MCP_SERVER = {
    "TOOLSETS": {
        "redirects": {
            "enabled_read":  True,   # default
            "enabled_write": False,  # opt in
        },
    },
    "LIMITS": {
        # Required for redirects.delete (and other destructive ops).
        "ALLOW_DESTRUCTIVE": True,
    },
}
```

`redirects` is the only toolset in v0.5 that uses split flags.
The rationale: read access to a redirect map is something an agent
realistically needs even at "audit my staging site" tier, but write
access is high-blast-radius (a wrong redirect can take down a
section of the site). Splitting them lets a host enable reads
without thinking about whether they want writes too.

## Read tools (on by default)

### `redirects.list`

Paginated list of redirects, optionally filtered by:

* `site_id` — restrict to a specific Wagtail Site
* `is_permanent` — filter by 301 vs 302
* `search` — substring match on `old_path` and on the redirect target

### `redirects.get`

Single redirect by id, including the resolved target (page id or
external link).

## Write tools (off by default)

Enable with `redirects.enabled_write = True`. The toolset class is
unloaded entirely when `enabled_write` is false, so even an
authenticated user with `wagtailredirects.add_redirect` cannot
invoke writes through MCP unless the host has flipped the flag.

### `redirects.create`

| Param            | Type | Notes                                              |
|------------------|------|----------------------------------------------------|
| `old_path`       | str  | Required. Normalised to lowercase + trailing-slash stripped. |
| `site_id`        | int? | Optional; null means site-agnostic.                |
| `is_permanent`   | bool | Default `True` (301).                              |
| `redirect_page_id` | int?  | Mutually exclusive with `redirect_link`.        |
| `redirect_link`  | str? | External URL. Mutually exclusive with `redirect_page_id`. |

Exactly one of `redirect_page_id` or `redirect_link` must be set.

### `redirects.update`

Patches one or more fields on an existing redirect. Same
mutual-exclusion rule on the target.

### `redirects.delete`

Hard-delete. **Three gates required:**

1. `redirects.enabled_write = True`.
2. `LIMITS.ALLOW_DESTRUCTIVE = True`.
3. Caller has `wagtailredirects.delete_redirect`.

## Permissions

* Reads: any authenticated caller.
* Create / update: `wagtailredirects.add_redirect` or `change_redirect`.
* Delete: `wagtailredirects.delete_redirect` (in addition to the destructive flag).

## Gotchas

* `old_path` normalisation matches the contrib app: `/Foo/Bar/` becomes `/foo/bar`. If you store paths uppercase elsewhere they will not match.
* The split-flag pattern applies *only* to `redirects` in v0.5. Other toolsets either ship as a unit (read+write together, off by default) or as read-only (no write side at all).
* Wagtail's redirects contrib app is required for either side to load. If it's missing from `INSTALLED_APPS`, the toolset is silently skipped (logged at INFO).
