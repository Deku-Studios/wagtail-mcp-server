"""Minimal URL conf for the test suite."""

from __future__ import annotations

from django.urls import include, path

urlpatterns = [
    path("mcp/", include("wagtail_mcp_server.urls")),
]
