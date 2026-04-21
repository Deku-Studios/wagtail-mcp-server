"""Django settings for the wagtail-mcp-server test suite.

Minimal configuration: SQLite, the usual Wagtail stack, and the app under
test. Tests opt into write toolsets by overriding ``WAGTAIL_MCP_SERVER``
inside ``override_settings`` / ``settings`` fixtures.
"""

from __future__ import annotations

SECRET_KEY = "test-only-not-a-secret"  # noqa: S105
DEBUG = False
ALLOWED_HOSTS = ["*"]
USE_TZ = True
TIME_ZONE = "UTC"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Wagtail core apps (minimal set sufficient for model imports):
    "taggit",
    "wagtail.admin",
    "wagtail.documents",
    "wagtail.images",
    "wagtail.sites",
    "wagtail.users",
    "wagtail.snippets",
    "wagtail.search",
    "wagtail.embeds",
    "wagtail.contrib.forms",
    "wagtail.contrib.redirects",
    "wagtail",
    # App under test:
    "wagtail_mcp_server",
]

MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

ROOT_URLCONF = "tests.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]

STATIC_URL = "/static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Explicit default so tests cover the validated path.
WAGTAIL_MCP_SERVER = {
    "TOOLSETS": {
        "pages_query": {"enabled": True},
        "seo_query": {"enabled": True},
    },
}

WAGTAIL_SITE_NAME = "Test"
