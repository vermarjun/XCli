"""Unit tests for xcli.drivers.browser — non-browser-launching paths.

Tests for the pure synchronous helpers and the simple reset/getter functions.
The actual get_or_create_browser/close_browser paths require a live Patchright
instance and are covered by the integration suite.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# reset_browser_for_testing
# ---------------------------------------------------------------------------


def test_reset_browser_for_testing_clears_singleton():
    """reset_browser_for_testing should set _browser to None."""
    import xcli.drivers.browser as drv

    # Force a fake browser into the module state
    drv._browser = MagicMock()
    assert drv._browser is not None

    drv.reset_browser_for_testing()
    assert drv._browser is None


def test_reset_browser_for_testing_resets_headless():
    """reset_browser_for_testing should reset _headless to True."""
    import xcli.drivers.browser as drv

    drv._headless = False
    drv.reset_browser_for_testing()
    assert drv._headless is True


# ---------------------------------------------------------------------------
# set_headless
# ---------------------------------------------------------------------------


def test_set_headless_false():
    import xcli.drivers.browser as drv

    drv.reset_browser_for_testing()
    drv.set_headless(False)
    assert drv._headless is False
    drv.reset_browser_for_testing()  # cleanup


def test_set_headless_true():
    import xcli.drivers.browser as drv

    drv.reset_browser_for_testing()
    drv._headless = False
    drv.set_headless(True)
    assert drv._headless is True
    drv.reset_browser_for_testing()  # cleanup


# ---------------------------------------------------------------------------
# get_profile_dir / profile_exists
# ---------------------------------------------------------------------------


def test_get_profile_dir_returns_path():
    """get_profile_dir should return a Path instance."""
    from xcli.drivers.browser import get_profile_dir

    result = get_profile_dir()
    assert isinstance(result, Path)


def test_profile_exists_false_for_missing_dir(tmp_path):
    """profile_exists should return False when the directory doesn't exist."""
    from xcli.drivers.browser import profile_exists

    non_existing = tmp_path / "nonexistent"
    assert profile_exists(non_existing) is False


def test_profile_exists_false_for_empty_dir(tmp_path):
    """profile_exists should return False for an existing but empty directory."""
    from xcli.drivers.browser import profile_exists

    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    # Our implementation calls session_state.profile_exists which checks non-empty
    result = profile_exists(empty_dir)
    # Empty dir → False (no profile files inside)
    assert result is False


# ---------------------------------------------------------------------------
# close_browser — when no browser is running (no-op)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_browser_no_op_when_no_singleton():
    """close_browser should be a no-op (no exception) when _browser is None."""
    import xcli.drivers.browser as drv

    drv.reset_browser_for_testing()
    assert drv._browser is None

    # Should not raise
    from xcli.drivers.browser import close_browser

    await close_browser()


@pytest.mark.asyncio
async def test_close_browser_calls_browser_close():
    """close_browser should call browser.close() on the singleton."""
    import xcli.drivers.browser as drv

    mock_browser = AsyncMock()
    mock_browser.close = AsyncMock()
    drv._browser = mock_browser

    from xcli.drivers.browser import close_browser

    await close_browser()

    mock_browser.close.assert_called_once()
    assert drv._browser is None


# ---------------------------------------------------------------------------
# get_or_create_browser — auth error when no profile
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_or_create_browser_raises_auth_error_no_profile():
    """get_or_create_browser should raise AuthenticationError when no profile exists."""
    import xcli.drivers.browser as drv
    from xcli.exceptions import AuthenticationError

    drv.reset_browser_for_testing()

    with (
        patch("xcli.drivers.browser.load_source_state", return_value=None),
    ):
        with pytest.raises(AuthenticationError, match="xcli login"):
            from xcli.drivers.browser import get_or_create_browser

            await get_or_create_browser()

    drv.reset_browser_for_testing()  # cleanup


@pytest.mark.asyncio
async def test_get_or_create_browser_returns_existing_singleton():
    """get_or_create_browser should return the existing browser without creating a new one."""
    import xcli.drivers.browser as drv

    mock_browser = MagicMock()
    drv._browser = mock_browser

    from xcli.drivers.browser import get_or_create_browser

    result = await get_or_create_browser()
    assert result is mock_browser

    drv.reset_browser_for_testing()  # cleanup
