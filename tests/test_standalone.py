"""Tests for the standalone ``wagtail-mcp-serve`` entrypoint.

We do *not* spin up the actual MCP transport here -- that's Chunk 4c's
subprocess smoke test. The unit-level coverage we want is:

    1. ``_parse_args`` does what we expect for the common flag combos.
    2. ``_configure_environment`` honours --data-dir and --settings,
       falls back to the bundled settings module otherwise.
    3. ``_bootstrap_credentials`` is idempotent: a second call when a
       token already exists is a no-op.
    4. The bundled ``standalone.settings`` module imports cleanly when
       pointed at a tmp data dir, and lays down the on-disk artefacts
       (db.sqlite3, secret_key) under that dir on first import.
    5. The ``WMS_OVERRIDE_*`` escape hatches flip the right flags.

Importing the bundled settings is destructive (writes a secret_key
file), so the data-dir tests use a tmp dir and reload the module.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest

# ----------------------------------------------------------------- _parse_args


def _parse(argv):
    from wagtail_mcp_server.standalone.serve import _parse_args

    return _parse_args(argv)


def test_parse_args_defaults_to_stdio_with_canonical_host_port():
    args = _parse([])
    assert args.transport == "stdio"
    assert args.host == "127.0.0.1"
    assert args.port == 8765
    assert args.no_migrate is False
    assert args.no_bootstrap is False
    assert args.bootstrap_username == "admin"


def test_parse_args_http_with_overrides():
    args = _parse(["--http", "--host", "0.0.0.0", "--port", "9999"])  # noqa: S104
    assert args.transport == "http"
    assert args.host == "0.0.0.0"  # noqa: S104
    assert args.port == 9999


def test_parse_args_stdio_and_http_are_mutually_exclusive():
    with pytest.raises(SystemExit):
        _parse(["--stdio", "--http"])


def test_parse_args_data_dir_and_settings_round_trip():
    args = _parse(
        ["--data-dir", "/tmp/wms-x", "--settings", "myproj.settings"]  # noqa: S108
    )
    assert args.data_dir == "/tmp/wms-x"  # noqa: S108
    assert args.settings == "myproj.settings"


def test_parse_args_no_migrate_and_no_bootstrap_flags():
    args = _parse(["--no-migrate", "--no-bootstrap"])
    assert args.no_migrate is True
    assert args.no_bootstrap is True


# ---------------------------------------------------- _configure_environment


def test_configure_environment_sets_settings_to_bundled_default(monkeypatch):
    monkeypatch.delenv("DJANGO_SETTINGS_MODULE", raising=False)
    monkeypatch.delenv("WMS_DATA_DIR", raising=False)

    from wagtail_mcp_server.standalone.serve import _configure_environment

    args = _parse([])
    settings_module = _configure_environment(args)

    assert settings_module == "wagtail_mcp_server.standalone.settings"
    assert os.environ["DJANGO_SETTINGS_MODULE"] == settings_module
    # Without --data-dir, the env var should not be touched.
    assert "WMS_DATA_DIR" not in os.environ


def test_configure_environment_honours_explicit_settings_flag(monkeypatch):
    monkeypatch.delenv("DJANGO_SETTINGS_MODULE", raising=False)

    from wagtail_mcp_server.standalone.serve import _configure_environment

    args = _parse(["--settings", "tests.settings"])
    settings_module = _configure_environment(args)

    assert settings_module == "tests.settings"
    assert os.environ["DJANGO_SETTINGS_MODULE"] == "tests.settings"


def test_configure_environment_data_dir_flag_pins_env_var(monkeypatch, tmp_path):
    monkeypatch.delenv("DJANGO_SETTINGS_MODULE", raising=False)
    monkeypatch.delenv("WMS_DATA_DIR", raising=False)

    from wagtail_mcp_server.standalone.serve import _configure_environment

    args = _parse(["--data-dir", str(tmp_path)])
    _configure_environment(args)

    # WMS_DATA_DIR must be set *before* the settings module imports,
    # because that's how the settings module learns where to put files.
    assert os.environ["WMS_DATA_DIR"] == str(tmp_path)


# ------------------------------------------------ bundled settings on tmp dir


@pytest.fixture
def fresh_standalone_settings(monkeypatch, tmp_path):
    """Force a clean import of standalone.settings into a tmp DATA_DIR.

    The module reads ``WMS_DATA_DIR`` at import time, so we have to
    purge it from ``sys.modules`` to get a fresh read.
    """
    monkeypatch.setenv("WMS_DATA_DIR", str(tmp_path))
    sys.modules.pop("wagtail_mcp_server.standalone.settings", None)
    mod = importlib.import_module("wagtail_mcp_server.standalone.settings")
    yield mod
    sys.modules.pop("wagtail_mcp_server.standalone.settings", None)


def test_standalone_settings_creates_data_dir_and_secret_key(
    fresh_standalone_settings, tmp_path
):
    mod = fresh_standalone_settings
    assert Path(mod.DATA_DIR) == tmp_path
    assert (tmp_path / "secret_key").exists()
    assert (tmp_path / "secret_key").read_text().strip() == mod.SECRET_KEY
    assert len(mod.SECRET_KEY) >= 40  # token_urlsafe(48) -> 64 chars


def test_standalone_settings_secret_key_sticks_across_imports(
    monkeypatch, tmp_path
):
    """A second import in the same data dir should reuse the same key."""
    monkeypatch.setenv("WMS_DATA_DIR", str(tmp_path))
    sys.modules.pop("wagtail_mcp_server.standalone.settings", None)
    first = importlib.import_module("wagtail_mcp_server.standalone.settings")
    first_key = first.SECRET_KEY

    sys.modules.pop("wagtail_mcp_server.standalone.settings", None)
    second = importlib.import_module("wagtail_mcp_server.standalone.settings")
    sys.modules.pop("wagtail_mcp_server.standalone.settings", None)

    assert first_key == second.SECRET_KEY


def test_standalone_settings_database_points_at_data_dir(
    fresh_standalone_settings, tmp_path
):
    mod = fresh_standalone_settings
    assert mod.DATABASES["default"]["NAME"] == str(tmp_path / "db.sqlite3")


def test_standalone_settings_writes_off_reads_on_by_default(
    fresh_standalone_settings,
):
    """Safety invariant: stock standalone never enables a write toolset."""
    mod = fresh_standalone_settings
    cfg = mod.WAGTAIL_MCP_SERVER["TOOLSETS"]
    assert cfg["pages_query"]["enabled"] is True
    assert cfg["seo_query"]["enabled"] is True
    assert cfg["collections_query"]["enabled"] is True
    assert cfg["snippets_query"]["enabled"] is True
    assert cfg["redirects"]["enabled_read"] is True
    assert cfg["redirects"]["enabled_write"] is False
    # Write toolsets should NOT appear in the standalone overrides.
    for slug in ("pages_write", "workflow", "media", "seo_write"):
        assert slug not in cfg, (
            f"standalone settings shipped with {slug} -- "
            "writes must stay off in the safe default"
        )


# --------------------------------------------------- WMS_OVERRIDE_* env hatches


def _reload_settings(tmp_path):
    sys.modules.pop("wagtail_mcp_server.standalone.settings", None)
    return importlib.import_module("wagtail_mcp_server.standalone.settings")


def test_override_pages_write_flips_flag(monkeypatch, tmp_path):
    monkeypatch.setenv("WMS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("WMS_OVERRIDE_PAGES_WRITE", "1")
    try:
        mod = _reload_settings(tmp_path)
        assert mod.WAGTAIL_MCP_SERVER["TOOLSETS"]["pages_write"]["enabled"] is True
    finally:
        sys.modules.pop("wagtail_mcp_server.standalone.settings", None)


def test_override_redirects_write_flips_split_flag(monkeypatch, tmp_path):
    monkeypatch.setenv("WMS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("WMS_OVERRIDE_REDIRECTS_WRITE", "true")
    try:
        mod = _reload_settings(tmp_path)
        red = mod.WAGTAIL_MCP_SERVER["TOOLSETS"]["redirects"]
        assert red["enabled_read"] is True
        assert red["enabled_write"] is True
    finally:
        sys.modules.pop("wagtail_mcp_server.standalone.settings", None)


def test_override_allow_destructive_flips_limits(monkeypatch, tmp_path):
    monkeypatch.setenv("WMS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("WMS_OVERRIDE_ALLOW_DESTRUCTIVE", "yes")
    try:
        mod = _reload_settings(tmp_path)
        assert mod.WAGTAIL_MCP_SERVER["LIMITS"]["ALLOW_DESTRUCTIVE"] is True
    finally:
        sys.modules.pop("wagtail_mcp_server.standalone.settings", None)


def test_override_unknown_value_is_ignored(monkeypatch, tmp_path):
    monkeypatch.setenv("WMS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("WMS_OVERRIDE_PAGES_WRITE", "definitely-not-a-bool")
    try:
        mod = _reload_settings(tmp_path)
        assert "pages_write" not in mod.WAGTAIL_MCP_SERVER["TOOLSETS"]
    finally:
        sys.modules.pop("wagtail_mcp_server.standalone.settings", None)


# ------------------------------------------------ bootstrap idempotence


@pytest.mark.django_db
def test_bootstrap_credentials_is_idempotent_when_token_exists(capsys):
    """Second call with an existing token row must not mint a new one."""
    from django.contrib.auth import get_user_model

    from wagtail_mcp_server.models import UserMcpToken
    from wagtail_mcp_server.standalone.serve import _bootstrap_credentials

    User = get_user_model()
    seeded_user = User.objects.create_user(
        username="seed", password="x"  # noqa: S106
    )
    UserMcpToken.issue(user=seeded_user, label="pre-existing")
    assert UserMcpToken.objects.count() == 1

    _bootstrap_credentials("admin")

    # Still one token; the early-return must have fired.
    assert UserMcpToken.objects.count() == 1
    # And no admin user was minted, since the bootstrap shouldn't run.
    assert not User.objects.filter(username="admin").exists()


@pytest.mark.django_db
def test_bootstrap_credentials_mints_superuser_and_token_on_first_run(capsys):
    from django.contrib.auth import get_user_model

    from wagtail_mcp_server.models import UserMcpToken
    from wagtail_mcp_server.standalone.serve import _bootstrap_credentials

    User = get_user_model()
    assert UserMcpToken.objects.count() == 0
    assert not User.objects.filter(username="admin").exists()

    _bootstrap_credentials("admin")

    admin = User.objects.get(username="admin")
    assert admin.is_superuser is True
    assert admin.is_staff is True
    assert UserMcpToken.objects.filter(user=admin).count() == 1

    # The plaintext token was printed to stderr -- the test runner
    # captures stderr too, so we can sniff for the marker.
    captured = capsys.readouterr()
    assert "first-boot bootstrap complete" in captured.err
    assert "MCP token:" in captured.err
