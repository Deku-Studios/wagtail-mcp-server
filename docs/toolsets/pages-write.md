# `pages_write` — mutate pages

Off by default. Enables the create/update/publish/move/delete surface
for pages. Every tool is gated by Wagtail's per-page permission
machinery; `pages.delete` is gated additionally by
`LIMITS.ALLOW_DESTRUCTIVE`.

```python
WAGTAIL_MCP_SERVER = {
    "TOOLSETS": {
        "pages_write": {"enabled": True},
    },
    "LIMITS": {
        # Required for pages.delete (and any other destructive op).
        "ALLOW_DESTRUCTIVE": True,
    },
}
```

## Tools

### `pages.create`

Creates a new page under a parent.

| Param         | Type   | Notes                                              |
|---------------|--------|----------------------------------------------------|
| `parent_id`   | int    | Required. The page id to create under.             |
| `type`        | str    | App-qualified page type (`home.HomePage`).         |
| `title`       | str    | Required.                                          |
| `slug`        | str?   | Auto-derived from `title` if omitted.              |
| `fields`      | dict   | Per-type field values. StreamFields take the envelope shape from `pages.types.schema`. |
| `publish`     | bool   | Default `False` — creates as a draft.              |

Drafts land with `live=False, has_unpublished_changes=True` to
match the admin "Save draft" behavior.

### `pages.update`

Patches one or more fields on an existing page. Unknown fields are
silently dropped (use `WRITE_VALIDATION = "strict"` to raise instead).

`publish=True` shortcuts the publish step in the same call.

### `pages.publish`

Publishes the latest draft revision. Requires `publish_page`
permission.

### `pages.unpublish`

Hides the page from the live site without deleting it. Requires
`publish_page` permission. Recoverable, so not gated by
`ALLOW_DESTRUCTIVE`.

### `pages.move`

Moves a page (and its subtree) under a new parent. Requires both
`change_page` on the page and `add_page` on the new parent.

### `pages.delete`

Hard-deletes a page and its subtree. **Three gates required:**

1. `pages_write` toolset enabled.
2. `LIMITS.ALLOW_DESTRUCTIVE = True`.
3. Caller has `delete_page` permission for the page.

If any gate fails the request is rejected with a structured error
before any DB mutation runs.

## StreamField writes

Inputs use the same `{"type", "id", "value"}` envelope as Wagtail's
own API. The validator runs *before* the DB is touched and returns
errors with closed-vocabulary codes:

| Code                  | Meaning                                           |
|-----------------------|---------------------------------------------------|
| `unknown_block_type`  | Top-level block type not in the model's `StreamBlock` |
| `unknown_child`       | Child key in a `StructBlock` not in its definition |
| `missing_required`    | Required child of a `StructBlock` not provided   |
| `type_mismatch`       | Value did not coerce into the block's expected type |
| `invalid_chooser_ref` | `ChooserBlock` value did not resolve to a model instance |
| `invalid_richtext`    | RichText value failed parse for the configured format |
| `envelope_shape`      | Top-level shape was not `{type, value}`           |

Each error carries a `path` (e.g. `body[3].value.cta.label`), an
`expected` description, and the `got` value, so agents can self-correct.

`ChooserBlock` accepts any of:
* `int` — bare primary key
* `{"_raw_id": int}` — explicit raw-id form
* an already-resolved model instance (server-side use)

## Gotchas

* `pages.create` does not silently drop unknown fields — they raise. (The thinking: a typo on create produces a wrong-shaped page; a typo on update at worst doesn't apply the field.)
* `WRITE_VALIDATION = "permissive"` exists, but is unsupported. Strict is the only mode tested in the suite.
* `pages.delete` is the only tool in this toolset that needs `ALLOW_DESTRUCTIVE`. Update, move, unpublish, and publish are recoverable.
