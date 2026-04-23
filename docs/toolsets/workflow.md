# `workflow` — drive Wagtail moderation

Off by default. Lets agents submit pages for moderation, advance them
through tasks, and walk back failed runs.

```python
WAGTAIL_MCP_SERVER = {
    "TOOLSETS": {
        "workflow": {"enabled": True},
    },
}
```

## Tools

### `workflow.submit`

Submits a page's latest revision into its assigned workflow.

| Param          | Type | Notes                                              |
|----------------|------|----------------------------------------------------|
| `page_id`      | int  | Required.                                          |
| `workflow_id`  | int? | Optional. If omitted, infers from the page's assignment rules. |
| `comment`      | str? | Attached to the workflow submission.               |

Requires `submit_for_moderation` (or `change_page` as a fallback)
on the page.

### `workflow.approve`

Approves the *current task* of an in-flight workflow run.

Permission delegates to `task.get_actions(page, user)` so custom
`Task` subclasses (Wagtail ships `GroupApprovalTask`; downstream
projects can register their own) work out of the box. Only actions
the user is authorized to take show up.

### `workflow.reject`

Rejects the current task. Recoverable — the page goes back to draft
and can be edited and resubmitted. Not gated by `ALLOW_DESTRUCTIVE`.

### `workflow.cancel`

Cancels the workflow run entirely. Same recoverability semantics as
`reject`; not destructive.

### `workflow.state`

Returns the current workflow state for a page: which workflow is
assigned, whether a run is in flight, the active task, and the
history of completed tasks (with author and timestamp).

## Permission model

The toolset never assumes a one-size-fits-all permission. Each tool
delegates to Wagtail's own contract:

* `workflow.submit` → `page.permissions_for_user(user).can_submit_for_moderation()`
* `workflow.approve` / `workflow.reject` → `task.get_actions(page, user)` returns the actions the user is allowed to take. The toolset checks that the requested action is in that set before invoking it.
* `workflow.cancel` → callable by the user who submitted the run, or by anyone with `change_page` on the page.

This means a project that ships a custom `Task` subclass with its
own approval rules (e.g. "only the legal team can approve a Privacy
Policy task") gets those rules for free — the toolset never bypasses
them.

## Gotchas

* `workflow_id` is optional on `submit`. If omitted, Wagtail resolves the workflow assigned to the page by the usual ancestor walk; if no workflow is assigned, submit raises with `no_workflow_assigned`.
* `workflow.state` is the way to discover the *current* task id when an agent doesn't already have it. Don't hardcode task ids.
* None of these actions are gated by `LIMITS.ALLOW_DESTRUCTIVE`. Reject and cancel are recoverable; submit and approve are forward-progress. The destructive flag is reserved for hard-deletes.
