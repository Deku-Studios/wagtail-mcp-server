"""Standalone runtime for ``wagtail-mcp-serve``.

This subpackage lets an operator do::

    pip install wagtail-mcp-server
    wagtail-mcp-serve --stdio

without writing a Django project. It bundles a minimal
:mod:`wagtail_mcp_server.standalone.settings` module (SQLite, persistent
``SECRET_KEY`` under ``$XDG_DATA_HOME/wagtail-mcp-server/``) and an
entrypoint at :func:`wagtail_mcp_server.standalone.serve.main` that
auto-migrates on first boot, mints a superuser + token if none exist,
and dispatches into the same code path as ``manage.py mcp_serve``.

The standalone settings ship with read-only toolsets enabled and every
write toolset disabled. Operators that want to grant write surface must
set ``WAGTAIL_MCP_SERVER`` overrides in their environment (see
:func:`wagtail_mcp_server.standalone.settings._user_overrides`).
"""

from __future__ import annotations
