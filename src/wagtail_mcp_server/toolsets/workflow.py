"""Workflow toolset.

Off by default. Drives Wagtail's moderation workflow over MCP:

    workflow.submit      Submit a page for moderation.
    workflow.approve     Approve the current task.
    workflow.reject      Reject the current task with a comment.
    workflow.cancel      Cancel an in-flight workflow.
    workflow.state       Inspect the current workflow state for a page.

Two gates guard every action:

    1. The toolset itself must be enabled (handled at registration).
    2. The user must hold the matching Wagtail permission for the page
       (``submit_for_moderation`` on submit/cancel, ``publish`` implies
       approve authority, etc.).

Workflow actions are not "destructive" in the ``pages.delete`` sense and
therefore do **not** require ``LIMITS.ALLOW_DESTRUCTIVE``. Rejecting or
cancelling an in-flight workflow is recoverable: the page's draft state
is preserved and the workflow can be resubmitted.
"""

from __future__ import annotations

from typing import Any

from django.core.exceptions import PermissionDenied


class WorkflowToolset:
    """django-mcp-server toolset for Wagtail moderation workflows."""

    name = "workflow"
    version = "0.3.0"

    # ---------------------------------------------------------------- workflow.submit

    def workflow_submit(
        self,
        user: Any,
        *,
        page_id: int,
        workflow_id: int | None = None,
    ) -> dict[str, Any]:
        """Submit a page for moderation.

        If ``workflow_id`` is omitted the workflow assigned to the page
        (or one of its ancestors) by Wagtail's workflow-assignment rules
        is used. If the page has no assigned workflow, a ``ValueError``
        is raised.
        """
        _require_authenticated(user)

        page = _get_page_or_404(page_id).specific
        if not _can_submit(user, page):
            raise PermissionDenied(
                f"User lacks submit permission for page {page_id}."
            )

        workflow = _resolve_workflow(page, workflow_id)
        if workflow is None:
            raise ValueError(
                f"Page {page_id} has no workflow assigned and no workflow_id was given."
            )

        revision = page.latest_revision
        if revision is None:
            # Wagtail's workflow machinery requires a revision to attach to.
            revision = page.save_revision(user=user)

        workflow_state = workflow.start(page, user)
        return _workflow_state_payload(workflow_state)

    # --------------------------------------------------------------- workflow.approve

    def workflow_approve(
        self,
        user: Any,
        *,
        task_state_id: int,
        comment: str = "",
    ) -> dict[str, Any]:
        """Approve the current task of a workflow state."""
        _require_authenticated(user)

        task_state = _get_task_state_or_404(task_state_id)
        page = task_state.workflow_state.page.specific
        if not _can_moderate_task(user, task_state, page):
            raise PermissionDenied(
                f"User lacks permission to approve task_state {task_state_id}."
            )
        task_state.approve(user=user, comment=comment)
        task_state.refresh_from_db()
        return _task_state_payload(task_state)

    # ---------------------------------------------------------------- workflow.reject

    def workflow_reject(
        self,
        user: Any,
        *,
        task_state_id: int,
        comment: str = "",
    ) -> dict[str, Any]:
        """Reject the current task of a workflow state.

        Wagtail's reject semantics return the page to the submitter
        (workflow state moves to ``needs_changes``). This is not a
        destructive op -- the draft is preserved.
        """
        _require_authenticated(user)

        task_state = _get_task_state_or_404(task_state_id)
        page = task_state.workflow_state.page.specific
        if not _can_moderate_task(user, task_state, page):
            raise PermissionDenied(
                f"User lacks permission to reject task_state {task_state_id}."
            )
        task_state.reject(user=user, comment=comment)
        task_state.refresh_from_db()
        return _task_state_payload(task_state)

    # ---------------------------------------------------------------- workflow.cancel

    def workflow_cancel(
        self,
        user: Any,
        *,
        workflow_state_id: int,
    ) -> dict[str, Any]:
        """Cancel an in-flight workflow state."""
        _require_authenticated(user)

        workflow_state = _get_workflow_state_or_404(workflow_state_id)
        page = workflow_state.page.specific
        if not _can_submit(user, page):
            raise PermissionDenied(
                f"User lacks permission to cancel workflow_state {workflow_state_id}."
            )
        workflow_state.cancel(user=user)
        workflow_state.refresh_from_db()
        return _workflow_state_payload(workflow_state)

    # ----------------------------------------------------------------- workflow.state

    def workflow_state(
        self,
        user: Any,
        *,
        page_id: int,
    ) -> dict[str, Any] | None:
        """Return the current workflow state for a page, or ``None``.

        Read-only. Requires only that the caller can view the page
        (i.e. authenticated).
        """
        _require_authenticated(user)

        page = _get_page_or_404(page_id).specific
        workflow_state = page.current_workflow_state
        if workflow_state is None:
            return None
        return _workflow_state_payload(workflow_state)


# --------------------------------------------------------------------- helpers


def _require_authenticated(user: Any) -> None:
    if user is None or not getattr(user, "is_authenticated", False):
        raise PermissionDenied("Anonymous users cannot call workflow tools.")


def _get_page_or_404(page_id: int) -> Any:
    from wagtail.models import Page

    try:
        return Page.objects.get(pk=page_id)
    except Page.DoesNotExist as exc:
        raise ValueError(f"Page id={page_id} does not exist.") from exc


def _get_workflow_state_or_404(workflow_state_id: int) -> Any:
    from wagtail.models import WorkflowState

    try:
        return WorkflowState.objects.get(pk=workflow_state_id)
    except WorkflowState.DoesNotExist as exc:
        raise ValueError(
            f"WorkflowState id={workflow_state_id} does not exist."
        ) from exc


def _get_task_state_or_404(task_state_id: int) -> Any:
    from wagtail.models import TaskState

    try:
        return TaskState.objects.get(pk=task_state_id).specific
    except TaskState.DoesNotExist as exc:
        raise ValueError(f"TaskState id={task_state_id} does not exist.") from exc


def _resolve_workflow(page: Any, workflow_id: int | None) -> Any:
    """Return the Workflow to start, or ``None`` if none applies."""
    from wagtail.models import Workflow

    if workflow_id is not None:
        try:
            return Workflow.objects.get(pk=workflow_id, active=True)
        except Workflow.DoesNotExist as exc:
            raise ValueError(
                f"Workflow id={workflow_id} does not exist or is inactive."
            ) from exc
    # Wagtail's page.get_workflow() walks the page tree looking for an
    # assigned workflow; returns None if none is found.
    return page.get_workflow()


# ---------------------------------------------------------- permission helpers


def _can_submit(user: Any, page: Any) -> bool:
    """Whether ``user`` may submit (or cancel) ``page`` for moderation."""
    if getattr(user, "is_superuser", False):
        return True
    perms = page.permissions_for_user(user)
    # Wagtail's PagePermissionTester exposes ``can_submit_for_moderation``;
    # fall back to edit permission if the method isn't available.
    can_submit = getattr(perms, "can_submit_for_moderation", None)
    if callable(can_submit):
        return bool(can_submit())
    return bool(perms.can_edit())


def _can_moderate_task(user: Any, task_state: Any, page: Any) -> bool:
    """Whether ``user`` may approve/reject ``task_state``.

    Delegates to the Task model's own ``user_can_access_editor`` /
    ``get_actions`` contract so custom Task subclasses (group-based,
    user-based, etc.) work out of the box.
    """
    if getattr(user, "is_superuser", False):
        return True
    task = task_state.task.specific
    actions_method = getattr(task, "get_actions", None)
    if callable(actions_method):
        actions = actions_method(page, user)
        # Wagtail returns a list of (name, verbose_name, requires_comment)
        # tuples. Any non-empty list means the user can act.
        return bool(actions)
    # Fallback for custom tasks that don't implement get_actions -- defer
    # to the page's publish permission (the common shape for the built-in
    # GroupApprovalTask).
    return bool(page.permissions_for_user(user).can_publish())


# ------------------------------------------------------------- payload builders


def _workflow_state_payload(workflow_state: Any) -> dict[str, Any]:
    current_task_state = workflow_state.current_task_state
    return {
        "id": workflow_state.pk,
        "page_id": workflow_state.page_id,
        "workflow_id": workflow_state.workflow_id,
        "status": workflow_state.status,
        "created_at": _isoformat(workflow_state.created_at),
        "current_task_state": (
            _task_state_payload(current_task_state)
            if current_task_state is not None
            else None
        ),
    }


def _task_state_payload(task_state: Any) -> dict[str, Any]:
    return {
        "id": task_state.pk,
        "workflow_state_id": task_state.workflow_state_id,
        "task_id": task_state.task_id,
        "task_name": str(task_state.task),
        "status": task_state.status,
        "started_at": _isoformat(task_state.started_at),
        "finished_at": _isoformat(task_state.finished_at),
        "finished_by_id": (
            task_state.finished_by_id
            if getattr(task_state, "finished_by_id", None) is not None
            else None
        ),
        "comment": getattr(task_state, "comment", "") or "",
    }


def _isoformat(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat()
