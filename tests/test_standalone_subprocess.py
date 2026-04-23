"""Subprocess smoke tests for the standalone ``wagtail-mcp-serve``.

These tests fork a fresh Python interpreter to invoke the standalone
runtime exactly the way an operator would after ``pip install``. They
validate the things that the in-process unit tests in
``test_standalone.py`` cannot:

    1. The console-script entrypoint is reachable as a Python module
       (``python -m wagtail_mcp_server.standalone.serve``) and exits
       cleanly on ``--help``.
    2. A full ``--stdio`` boot under a tmp data dir runs migrate and
       mints a bootstrap token. The MCP transport itself is currently
       a scaffold (see ``management/commands/mcp_serve.py``) so the
       process exits 0 immediately after the dispatch line; once the
       transport is wired in a future release this test should
       continue to pass and a *new* test should add the actual
       JSON-RPC ``initialize`` round trip.
    3. ``--no-bootstrap --no-migrate --settings=tests.settings`` runs
       end-to-end against the test settings module without touching
       a tmp dir, proving the dispatcher is wired correctly.

Why a subprocess and not the in-process ``main()``?
    The standalone settings module mutates Django settings at import
    time (``DJANGO_SETTINGS_MODULE``, secret-key file, mkdir), and
    pytest-django has already pinned ``tests.settings``. Forking is
    the cleanest isolation; trying to swap settings mid-process risks
    contaminating later tests.

Skips:
    The tests skip if ``django-mcp-server`` is not importable in the
    subprocess environment (e.g. someone running the suite under a
    minimal Python with only the lib's hard deps and no extras).
    Local Python 3.10 sandboxes hit this skip; CI on 3.11+ does not.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# Module path for ``python -m`` invocation. Console-script form
# (``wagtail-mcp-serve``) only resolves after ``pip install``, which
# is not guaranteed in every test environment.
MODULE = "wagtail_mcp_server.standalone.serve"


def _can_subprocess_django_mcp() -> bool:
    """Probe whether the subprocess Python can import django-mcp-server.

    The standalone runtime hard-imports ``django.setup`` and (eventually)
    ``mcp_server`` via the management command. If the latter is missing
    we want to skip rather than spam tracebacks.
    """
    try:
        result = subprocess.run(
            [sys.executable, "-c", "import mcp_server"],
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False
    return result.returncode == 0


_HAS_DEPS = _can_subprocess_django_mcp()


def _run(*args, env_extra=None, timeout=30) -> subprocess.CompletedProcess:
    """Helper: invoke ``python -m wagtail_mcp_server.standalone.serve``.

    Inherits the parent environment so ``PYTHONPATH`` / venv site-packages
    are visible to the child. Returns the completed process so tests can
    assert on returncode, stdout, and stderr.
    """
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    # Force the bundled standalone settings to win even if the parent
    # process has DJANGO_SETTINGS_MODULE pinned (pytest-django does).
    env.pop("DJANGO_SETTINGS_MODULE", None)
    return subprocess.run(
        [sys.executable, "-m", MODULE, *args],
        capture_output=True,
        timeout=timeout,
        check=False,
        env=env,
    )


# --------------------------------------------------------------------- --help


def test_help_exits_zero_and_lists_transport_flags():
    """``--help`` must work even with no Django bootstrap.

    argparse handles ``--help`` before any of our env/import wiring
    runs, so this test passes regardless of whether django-mcp-server
    is installed -- a useful sanity check that the entrypoint is
    correctly registered.
    """
    cp = _run("--help")
    assert cp.returncode == 0, (
        f"--help exit={cp.returncode} stderr={cp.stderr.decode()[:400]}"
    )
    out = cp.stdout.decode()
    assert "--stdio" in out
    assert "--http" in out
    assert "--data-dir" in out
    assert "--no-bootstrap" in out


def test_help_mentions_zero_config_pitch():
    """The help blurb should sell the zero-config story.

    This is a soft-contract test: the marketing copy is what gets
    pasted into Hacker News threads, and it must not silently drop
    the "no host Django project required" claim. If someone rewrites
    the help text and forgets the pitch, this test breaks.
    """
    cp = _run("--help")
    out = cp.stdout.decode().lower()
    assert "self-contained" in out or "no host" in out


# ------------------------------------------------------- full bootstrap path


@pytest.mark.skipif(not _HAS_DEPS, reason="django-mcp-server not importable")
def test_full_stdio_boot_under_tmp_dir_creates_db_and_token(tmp_path):
    """End-to-end: bootstrap should migrate + mint a token + dispatch.

    The ``mcp_serve`` management command in v0.5 is still a scaffold
    that prints a banner and exits 0; once the real transport lands
    this test stays valid (the bootstrap side-effects don't change)
    but the assertion on stdout shape must be revisited.
    """
    cp = _run("--data-dir", str(tmp_path), "--stdio", timeout=60)
    assert cp.returncode == 0, (
        f"stdio boot failed: rc={cp.returncode} "
        f"stderr={cp.stderr.decode()[:600]}"
    )

    # On-disk artefacts the standalone settings module owns:
    assert (tmp_path / "db.sqlite3").exists()
    assert (tmp_path / "secret_key").exists()

    # Bootstrap printed the token to stderr (NOT stdout, which is
    # reserved for MCP frames).
    err = cp.stderr.decode()
    assert "first-boot bootstrap complete" in err
    assert "MCP token:" in err


@pytest.mark.skipif(not _HAS_DEPS, reason="django-mcp-server not importable")
def test_full_stdio_boot_is_idempotent(tmp_path):
    """A second boot under the same data dir must not re-mint a token.

    The ``UserMcpToken.objects.exists()`` early-return in
    ``_bootstrap_credentials`` is the load-bearing check here.
    """
    first = _run("--data-dir", str(tmp_path), "--stdio", timeout=60)
    assert first.returncode == 0
    assert "first-boot bootstrap complete" in first.stderr.decode()

    second = _run("--data-dir", str(tmp_path), "--stdio", timeout=60)
    assert second.returncode == 0
    # The bootstrap banner must NOT appear on the second boot.
    assert "first-boot bootstrap complete" not in second.stderr.decode()


@pytest.mark.skipif(not _HAS_DEPS, reason="django-mcp-server not importable")
def test_full_stdio_boot_persists_secret_key_across_restarts(tmp_path):
    """The standalone SECRET_KEY must be sticky across boots.

    Sessions and signed cookies/values issued by the first boot must
    remain valid when the process restarts under the same data dir.
    """
    first = _run("--data-dir", str(tmp_path), "--stdio", timeout=60)
    assert first.returncode == 0
    key1 = (tmp_path / "secret_key").read_text().strip()

    second = _run("--data-dir", str(tmp_path), "--stdio", timeout=60)
    assert second.returncode == 0
    key2 = (tmp_path / "secret_key").read_text().strip()

    assert key1 == key2 and len(key1) >= 40


# --------------------------------------------- no-bootstrap + custom settings


@pytest.mark.skipif(not _HAS_DEPS, reason="django-mcp-server not importable")
def test_no_bootstrap_no_migrate_under_test_settings_module(tmp_path):
    """Lets a host point us at their own settings + skip our bootstrap.

    Useful for containerized deployments where credentials are seeded
    out-of-band and the data dir lives on a read-only mount.
    """
    # We run from inside the project root so ``tests.settings`` is
    # importable. The pytest invocation ensures cwd is project root.
    cp = _run(
        "--no-bootstrap",
        "--no-migrate",
        "--settings",
        "tests.settings",
        "--stdio",
        timeout=60,
        env_extra={"PYTHONPATH": str(Path.cwd())},
    )
    assert cp.returncode == 0, (
        f"custom-settings boot failed: rc={cp.returncode} "
        f"stderr={cp.stderr.decode()[:600]}"
    )

    # No bootstrap banner since we passed --no-bootstrap.
    assert "first-boot bootstrap complete" not in cp.stderr.decode()


# --------------------------------------------------------------- arg errors


def test_stdio_and_http_together_returns_nonzero():
    """argparse rejects mutually exclusive transports without bootstrapping."""
    cp = _run("--stdio", "--http")
    assert cp.returncode != 0
    # argparse prints "not allowed with" to stderr.
    assert b"not allowed with" in cp.stderr.lower()


def test_unknown_flag_returns_nonzero():
    cp = _run("--this-is-not-a-real-flag")
    assert cp.returncode != 0


# --------------------------------------------------------------- housekeeping


@pytest.fixture(autouse=True)
def _cleanup_default_data_dir():
    """Don't let standalone runs littering the developer's home dir.

    If a test forgets to pass ``--data-dir`` we fall back to the
    bundled default (``~/.local/share/wagtail-mcp-server`` on Linux,
    etc.). That's fine in production, but in tests we want zero
    filesystem footprint outside of pytest's tmp_path. This fixture
    snapshots the default dir's existence before each test and only
    cleans up if the dir was created during the test.
    """
    from wagtail_mcp_server.standalone.settings import _default_data_dir

    target = _default_data_dir()
    pre_existed = target.exists()
    yield
    if not pre_existed and target.exists():
        # Only nuke directories we ourselves created.
        shutil.rmtree(target, ignore_errors=True)
