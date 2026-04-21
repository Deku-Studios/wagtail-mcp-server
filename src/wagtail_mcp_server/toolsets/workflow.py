"""Workflow toolset.

Off by default. Drives Wagtail's moderation workflow:

    workflow.submit      Submit a page for moderation.
    workflow.approve     Approve the current task.
    workflow.reject      Reject the current task with a comment.
    workflow.cancel      Cancel an in-flight workflow.
    workflow.state       Inspect the current workflow state for a page.

Lands in v0.2.
"""

from __future__ import annotations


class WorkflowToolset:
    """django-mcp-server toolset for workflow actions."""

    name = "workflow"
    version = "0.1.0"
