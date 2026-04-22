"""Tests for ``WorkflowToolset``.

Three shapes are covered:

    1. Auth gate — anonymous users cannot call any method.
    2. No-workflow path — ``workflow.state`` returns ``None`` and
       ``workflow.submit`` raises ``ValueError`` when the page has no
       workflow assigned and none was passed explicitly.
    3. Happy path — with a minimal Workflow + Task assigned, a superuser
       can submit, approve, and cancel.

The tests deliberately avoid exercising every Task subclass. Wagtail's
``get_actions`` contract is what the toolset depends on, and the base
``Task`` model honors it via its concrete subclass registration. For
projects that use ``GroupApprovalTask``, the behavior is identical — the
toolset just forwards to ``task.get_actions(page, user)``.
"""

from __future__ import annotations

import pytest
from django.core.exceptions import PermissionDenied

from wagtail_mcp_server.toolsets.workflow import WorkflowToolset


@pytest.fixture
def toolset():
    return WorkflowToolset()


@pytest.fixture
def superuser(db):
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return User.objects.create_user(
        username="alice",
        password="x",  # noqa: S106
        is_superuser=True,
        is_staff=True,
    )


@pytest.fixture
def workflow(db):
    """A minimal Wagtail workflow with one Task, not yet assigned to any page.

    Tests that need the workflow attached to a page pass ``workflow.pk``
    explicitly to ``workflow.submit`` rather than relying on tree-walk
    assignment, which keeps the fixture surface small.
    """
    from wagtail.models import Task, Workflow, WorkflowTask

    wf = Workflow.objects.create(name="Test workflow")
    task = Task.objects.create(name="Test task")
    WorkflowTask.objects.create(workflow=wf, task=task, sort_order=0)
    return wf


# -------------------------------------------------------------------- auth gate


@pytest.mark.django_db
def test_workflow_submit_rejects_anonymous(toolset, stream_page):
    with pytest.raises(PermissionDenied):
        toolset.workflow_submit(None, page_id=stream_page.pk)


@pytest.mark.django_db
def test_workflow_state_rejects_anonymous(toolset, stream_page):
    with pytest.raises(PermissionDenied):
        toolset.workflow_state(None, page_id=stream_page.pk)


@pytest.mark.django_db
def test_workflow_approve_rejects_anonymous(toolset):
    with pytest.raises(PermissionDenied):
        toolset.workflow_approve(None, task_state_id=1)


@pytest.mark.django_db
def test_workflow_reject_rejects_anonymous(toolset):
    with pytest.raises(PermissionDenied):
        toolset.workflow_reject(None, task_state_id=1)


@pytest.mark.django_db
def test_workflow_cancel_rejects_anonymous(toolset):
    with pytest.raises(PermissionDenied):
        toolset.workflow_cancel(None, workflow_state_id=1)


# ------------------------------------------------------------- no-workflow path


@pytest.mark.django_db
def test_workflow_state_returns_none_when_no_workflow(
    toolset, superuser, stream_page
):
    """Page with no workflow in flight returns ``None``."""
    assert toolset.workflow_state(superuser, page_id=stream_page.pk) is None


@pytest.mark.django_db
def test_workflow_submit_without_assignment_raises(
    toolset, superuser, stream_page
):
    """Page with no assigned workflow and no explicit id -> ValueError.

    Wagtail ships a data migration that creates a default "Moderators
    approval" workflow assigned to the root page, which would otherwise
    be picked up by ``page.get_workflow()``. Clear it for this test so
    we can exercise the "no workflow anywhere" path.
    """
    from wagtail.models import Workflow, WorkflowContentType, WorkflowPage

    WorkflowPage.objects.all().delete()
    WorkflowContentType.objects.all().delete()
    Workflow.objects.all().update(active=False)

    with pytest.raises(ValueError):
        toolset.workflow_submit(superuser, page_id=stream_page.pk)


@pytest.mark.django_db
def test_workflow_submit_with_unknown_workflow_id_raises(
    toolset, superuser, stream_page
):
    with pytest.raises(ValueError):
        toolset.workflow_submit(
            superuser, page_id=stream_page.pk, workflow_id=999_999
        )


# ---------------------------------------------------------------- happy path


@pytest.mark.django_db
def test_workflow_submit_starts_a_workflow(
    toolset, superuser, stream_page, workflow
):
    """Explicit workflow_id + superuser -> WorkflowState is created."""
    stream_page.save_revision(user=superuser)
    payload = toolset.workflow_submit(
        superuser, page_id=stream_page.pk, workflow_id=workflow.pk
    )
    assert payload["page_id"] == stream_page.pk
    assert payload["workflow_id"] == workflow.pk
    assert payload["status"] == "in_progress"
    # Current task state must be populated so the agent can immediately
    # approve/reject without a second round-trip.
    assert payload["current_task_state"] is not None
    assert payload["current_task_state"]["status"] == "in_progress"


@pytest.mark.django_db
def test_workflow_state_after_submit_matches(
    toolset, superuser, stream_page, workflow
):
    stream_page.save_revision(user=superuser)
    submit_payload = toolset.workflow_submit(
        superuser, page_id=stream_page.pk, workflow_id=workflow.pk
    )
    state_payload = toolset.workflow_state(superuser, page_id=stream_page.pk)
    assert state_payload is not None
    assert state_payload["id"] == submit_payload["id"]


@pytest.mark.django_db
def test_workflow_cancel_marks_workflow_cancelled(
    toolset, superuser, stream_page, workflow
):
    stream_page.save_revision(user=superuser)
    submitted = toolset.workflow_submit(
        superuser, page_id=stream_page.pk, workflow_id=workflow.pk
    )
    cancelled = toolset.workflow_cancel(
        superuser, workflow_state_id=submitted["id"]
    )
    # Wagtail's cancel sets status to "cancelled".
    assert cancelled["status"] == "cancelled"


@pytest.mark.django_db
def test_workflow_approve_advances_task(
    toolset, superuser, stream_page, workflow
):
    """Superuser can approve -- the task state moves to approved/finished."""
    stream_page.save_revision(user=superuser)
    submitted = toolset.workflow_submit(
        superuser, page_id=stream_page.pk, workflow_id=workflow.pk
    )
    task_state_id = submitted["current_task_state"]["id"]
    payload = toolset.workflow_approve(
        superuser, task_state_id=task_state_id, comment="lgtm"
    )
    # Wagtail's Task.approve() transitions status to "approved".
    assert payload["status"] == "approved"
    assert payload["comment"] == "lgtm"


@pytest.mark.django_db
def test_workflow_approve_on_missing_task_state_raises(toolset, superuser):
    with pytest.raises(ValueError):
        toolset.workflow_approve(superuser, task_state_id=999_999)


@pytest.mark.django_db
def test_workflow_cancel_on_missing_state_raises(toolset, superuser):
    with pytest.raises(ValueError):
        toolset.workflow_cancel(superuser, workflow_state_id=999_999)
