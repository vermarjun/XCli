"""Smoke tests for xcli.__main__ and xcli.core.browser non-browser helpers."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# __main__ importable test
# ---------------------------------------------------------------------------


def test_main_module_exports_app() -> None:
    """xcli.__main__ should export the 'app' symbol from xcli.cli."""
    # We patch the app() call that happens at module level when run as __main__
    # by simply verifying the module *file* contains the expected import.
    from pathlib import Path as _Path

    main_path = _Path(__file__).parent.parent.parent / "xcli" / "__main__.py"
    source = main_path.read_text()
    assert "from xcli.cli import app" in source
    assert "app()" in source


# ---------------------------------------------------------------------------
# core.browser helpers (no browser launch required)
# ---------------------------------------------------------------------------


def test_harden_xcli_tree_no_op_outside_xcli_dir(tmp_path: Path) -> None:
    """_harden_xcli_tree should be a no-op for paths not inside a .xcli directory."""
    from xcli.core.browser import _harden_xcli_tree

    outside = tmp_path / "somedir"
    outside.mkdir()

    # Should not raise and should not change permissions for unrelated paths
    _harden_xcli_tree(outside)


def test_harden_xcli_tree_hardens_xcli_subtree(tmp_path: Path) -> None:
    """_harden_xcli_tree should chmod directories inside .xcli to 0o700."""
    if os.name == "nt":
        pytest.skip("chmod not applicable on Windows")

    from xcli.core.browser import _harden_xcli_tree

    xcli_root = tmp_path / ".xcli"
    xcli_root.mkdir(mode=0o755)  # start with loose permissions
    profile_dir = xcli_root / "profile"
    profile_dir.mkdir(mode=0o755)

    _harden_xcli_tree(profile_dir)

    assert stat.S_IMODE(xcli_root.stat().st_mode) == 0o700


def test_browser_manager_constants_exist() -> None:
    """X_COOKIE_NAMES and X_DOMAINS should be non-empty frozensets."""
    from xcli.core.browser import _X_COOKIE_NAMES, _X_DOMAINS

    assert "auth_token" in _X_COOKIE_NAMES
    assert "ct0" in _X_COOKIE_NAMES
    assert any("x.com" in d for d in _X_DOMAINS)


def test_browser_manager_default_user_data_dir() -> None:
    """_DEFAULT_USER_DATA_DIR should be inside ~/.xcli/."""
    from xcli.core.browser import _DEFAULT_USER_DATA_DIR

    assert ".xcli" in str(_DEFAULT_USER_DATA_DIR)


# ---------------------------------------------------------------------------
# BrowserManager: export_cookies with mock context
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_cookies_writes_json(tmp_path: Path) -> None:
    """export_cookies should write a JSON file with filtered X cookies."""
    from unittest.mock import AsyncMock

    from xcli.core.browser import BrowserManager

    bm = BrowserManager.__new__(BrowserManager)
    # Inject a fake context
    mock_context = MagicMock()
    mock_context.cookies = AsyncMock(
        return_value=[
            {
                "name": "auth_token",
                "value": "tok123",
                "domain": ".x.com",
                "path": "/",
                "expires": -1,
                "httpOnly": True,
                "secure": True,
                "sameSite": "None",
            },
            {
                "name": "ct0",
                "value": "csrfval",
                "domain": ".x.com",
                "path": "/",
                "expires": -1,
                "httpOnly": False,
                "secure": True,
                "sameSite": "None",
            },
            {
                "name": "irrelevant_cookie",
                "value": "should_not_be_exported",
                "domain": ".x.com",
                "path": "/",
                "expires": -1,
                "httpOnly": False,
                "secure": True,
                "sameSite": "None",
            },
        ]
    )
    bm._context = mock_context

    cookie_path = tmp_path / "cookies.json"
    result = await bm.export_cookies(cookie_path)

    assert result is True
    assert cookie_path.exists()
    import json

    cookies = json.loads(cookie_path.read_text())
    names = {c["name"] for c in cookies}
    assert "auth_token" in names
    assert "ct0" in names
    assert "irrelevant_cookie" not in names


@pytest.mark.asyncio
async def test_export_cookies_returns_false_no_context() -> None:
    """export_cookies should return False when no browser context is available."""
    from xcli.core.browser import BrowserManager

    bm = BrowserManager.__new__(BrowserManager)
    bm._context = None

    result = await bm.export_cookies("/tmp/test_cookies.json")
    assert result is False
