"""AppConfig for the tests' Django app."""

from __future__ import annotations

from django.apps import AppConfig


class TestAppConfig(AppConfig):
    name = "tests.testapp"
    label = "wagtail_mcp_server_testapp"
    default_auto_field = "django.db.models.BigAutoField"
