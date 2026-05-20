"""Unit tests for xcli.core.browser.BrowserManager.

Tests the constructor, property accessors, import_cookies,
and the close() no-op path — all without starting a real browser.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# BrowserManager constructor
# ---------------------------------------------------------------------------


def test_browser_manager_default_viewport() -> None:
    """Default viewport should be 1280x720."""
    from xcli.core.browser import BrowserManager

    bm = BrowserManager(user_data_dir="/tmp/test_profile")
    assert bm.viewport == {"width": 1280, "height": 720}


def test_browser_manager_custom_viewport() -> None:
    """Custom viewport is stored as-is."""
    from xcli.core.browser import BrowserManager

    bm = BrowserManager(user_data_dir="/tmp/test_profile", viewport={"width": 800, "height": 600})
    assert bm.viewport == {"width": 800, "height": 600}


def test_browser_manager_expands_user_data_dir() -> None:
    """user_data_dir with ~ should be expanded."""
    from xcli.core.browser import BrowserManager

    bm = BrowserManager(user_data_dir="~/.xcli/profile")
    assert "~" not in bm.user_data_dir


def test_browser_manager_headless_default() -> None:
    from xcli.core.browser import BrowserManager

    bm = BrowserManager(user_data_dir="/tmp/test_profile")
    assert bm.headless is True


def test_browser_manager_headless_false() -> None:
    from xcli.core.browser import BrowserManager

    bm = BrowserManager(user_data_dir="/tmp/test_profile", headless=False)
    assert bm.headless is False


# ---------------------------------------------------------------------------
# page / context / is_authenticated properties
# ---------------------------------------------------------------------------


def test_browser_manager_page_raises_when_not_started() -> None:
    """Accessing .page before start() should raise RuntimeError."""
    from xcli.core.browser import BrowserManager

    bm = BrowserManager(user_data_dir="/tmp/test_profile")
    with pytest.raises(RuntimeError, match="Browser not started"):
        _ = bm.page


def test_browser_manager_context_raises_when_not_started() -> None:
    """Accessing .context before start() should raise RuntimeError."""
    from xcli.core.browser import BrowserManager

    bm = BrowserManager(user_data_dir="/tmp/test_profile")
    with pytest.raises(RuntimeError, match="Browser context not initialized"):
        _ = bm.context


def test_browser_manager_is_authenticated_initially_false() -> None:
    from xcli.core.browser import BrowserManager

    bm = BrowserManager(user_data_dir="/tmp/test_profile")
    assert bm.is_authenticated is False


def test_browser_manager_is_authenticated_settable() -> None:
    from xcli.core.browser import BrowserManager

    bm = BrowserManager.__new__(BrowserManager)
    bm._is_authenticated = False
    bm.is_authenticated = True
    assert bm.is_authenticated is True


# ---------------------------------------------------------------------------
# close() — no-op when not started
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_browser_manager_close_noop_when_not_started() -> None:
    """close() should be a no-op when the browser was never started."""
    from xcli.core.browser import BrowserManager

    bm = BrowserManager(user_data_dir="/tmp/test_profile")
    # Should not raise
    await bm.close()


# ---------------------------------------------------------------------------
# start() → raises RuntimeError if called twice
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_browser_manager_start_raises_if_already_started() -> None:
    """start() should raise RuntimeError when called on an already-started manager."""
    from xcli.core.browser import BrowserManager

    bm = BrowserManager.__new__(BrowserManager)
    bm._context = MagicMock()  # inject a fake context to simulate started state

    with pytest.raises(RuntimeError, match="already started"):
        await bm.start()


# ---------------------------------------------------------------------------
# import_cookies — with a real JSON file
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_import_cookies_returns_true_when_auth_token_present(tmp_path: Path) -> None:
    """import_cookies should return True when auth_token is in the cookie file."""
    from xcli.core.browser import BrowserManager

    bm = BrowserManager.__new__(BrowserManager)
    bm._is_authenticated = False
    mock_context = MagicMock()
    mock_context.add_cookies = AsyncMock()
    bm._context = mock_context

    cookie_path = tmp_path / "cookies.json"
    cookies = [
        {"name": "auth_token", "value": "tok123", "domain": ".x.com", "path": "/"},
        {"name": "ct0", "value": "csrf", "domain": ".x.com", "path": "/"},
    ]
    cookie_path.write_text(json.dumps(cookies))

    result = await bm.import_cookies(cookie_path)
    assert result is True
    mock_context.add_cookies.assert_called_once()


@pytest.mark.asyncio
async def test_import_cookies_returns_false_no_context() -> None:
    """import_cookies should return False when no browser context is available."""
    from xcli.core.browser import BrowserManager

    bm = BrowserManager.__new__(BrowserManager)
    bm._context = None

    result = await bm.import_cookies("/tmp/nonexistent.json")
    assert result is False


@pytest.mark.asyncio
async def test_import_cookies_returns_false_missing_file(tmp_path: Path) -> None:
    """import_cookies should return False when the cookie file does not exist."""
    from xcli.core.browser import BrowserManager

    bm = BrowserManager.__new__(BrowserManager)
    mock_context = MagicMock()
    bm._context = mock_context

    result = await bm.import_cookies(tmp_path / "nonexistent.json")
    assert result is False


@pytest.mark.asyncio
async def test_import_cookies_returns_false_no_auth_token(tmp_path: Path) -> None:
    """import_cookies should return False when auth_token is not in the cookie file."""
    from xcli.core.browser import BrowserManager

    bm = BrowserManager.__new__(BrowserManager)
    mock_context = MagicMock()
    mock_context.add_cookies = AsyncMock()
    bm._context = mock_context

    cookie_path = tmp_path / "cookies.json"
    cookies = [{"name": "ct0", "value": "csrf", "domain": ".x.com", "path": "/"}]
    cookie_path.write_text(json.dumps(cookies))

    result = await bm.import_cookies(cookie_path)
    assert result is False
