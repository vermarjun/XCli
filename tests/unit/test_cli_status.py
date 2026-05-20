"""Tests for xcli.cli._status_cmd and _login_cmd internals.

Tests the async command handlers directly to lift CLI coverage.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# _status_cmd — no source state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_status_cmd_no_source_state() -> None:
    """_status_cmd should return authenticated=False when no source state exists."""
    from xcli.cli import _status_cmd

    mock_source_state = None
    mock_cookie_path = MagicMock()
    mock_cookie_path.exists.return_value = False

    with (
        patch("xcli.session_state.load_source_state", return_value=mock_source_state),
        patch("xcli.session_state.profile_exists", return_value=False),
        patch("xcli.session_state.portable_cookie_path", return_value=mock_cookie_path),
    ):
        result = await _status_cmd()

    assert result["authenticated"] is False
    assert result["profile_exists"] is False
    assert result["source_state"] is None


@pytest.mark.asyncio
async def test_status_cmd_no_profile() -> None:
    """_status_cmd should return authenticated=False when no profile dir exists."""
    from xcli.cli import _status_cmd

    mock_source_state = MagicMock()
    mock_source_state.created_at = "2026-05-01T12:00:00Z"
    mock_source_state.login_generation = "uuid-test"

    mock_cookie_path = MagicMock()
    mock_cookie_path.exists.return_value = True

    with (
        patch("xcli.session_state.load_source_state", return_value=mock_source_state),
        patch("xcli.session_state.profile_exists", return_value=False),
        patch("xcli.session_state.portable_cookie_path", return_value=mock_cookie_path),
    ):
        result = await _status_cmd()

    assert result["authenticated"] is False


@pytest.mark.asyncio
async def test_status_cmd_auth_exception_returns_false() -> None:
    """_status_cmd should return authenticated=False on AuthenticationError from browser."""
    from xcli.cli import _status_cmd
    from xcli.exceptions import AuthenticationError

    mock_source_state = MagicMock()
    mock_source_state.created_at = "2026-05-01T12:00:00Z"
    mock_source_state.login_generation = "uuid-test"

    mock_cookie_path = MagicMock()
    mock_cookie_path.exists.return_value = True

    with (
        patch("xcli.session_state.load_source_state", return_value=mock_source_state),
        patch("xcli.session_state.profile_exists", return_value=True),
        patch("xcli.session_state.portable_cookie_path", return_value=mock_cookie_path),
        patch(
            "xcli.drivers.browser.get_or_create_browser",
            new=AsyncMock(side_effect=AuthenticationError("expired")),
        ),
    ):
        result = await _status_cmd()

    assert result["authenticated"] is False


@pytest.mark.asyncio
async def test_status_cmd_authenticated() -> None:
    """_status_cmd should return authenticated=True when browser check passes."""
    from xcli.cli import _status_cmd

    mock_source_state = MagicMock()
    mock_source_state.created_at = "2026-05-01T12:00:00Z"
    mock_source_state.login_generation = "uuid-test"

    mock_cookie_path = MagicMock()
    mock_cookie_path.exists.return_value = True

    mock_browser = MagicMock()
    mock_browser.page = MagicMock()

    with (
        patch("xcli.session_state.load_source_state", return_value=mock_source_state),
        patch("xcli.session_state.profile_exists", return_value=True),
        patch("xcli.session_state.portable_cookie_path", return_value=mock_cookie_path),
        patch(
            "xcli.drivers.browser.get_or_create_browser",
            new=AsyncMock(return_value=mock_browser),
        ),
        patch("xcli.core.auth.is_logged_in", new=AsyncMock(return_value=True)),
        patch(
            "xcli.scraping.extractor.read_authenticated_handle",
            new=AsyncMock(return_value="testuser"),
        ),
        patch("xcli.drivers.browser.close_browser", new=AsyncMock()),
    ):
        result = await _status_cmd()

    assert result["authenticated"] is True


# ---------------------------------------------------------------------------
# drivers.browser helpers (validate_session, ensure_authenticated)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_validate_session_returns_true_when_authenticated() -> None:
    """validate_session should return True when browser is authenticated."""
    import xcli.drivers.browser as drv

    mock_browser = MagicMock()
    mock_browser.is_authenticated = True
    drv._browser = mock_browser

    from xcli.drivers.browser import validate_session

    result = await validate_session()
    assert result is True

    drv.reset_browser_for_testing()


@pytest.mark.asyncio
async def test_validate_session_returns_false_on_auth_error() -> None:
    """validate_session should return False on AuthenticationError."""
    import xcli.drivers.browser as drv
    from xcli.exceptions import AuthenticationError

    drv.reset_browser_for_testing()

    with patch(
        "xcli.drivers.browser.get_or_create_browser",
        new=AsyncMock(side_effect=AuthenticationError("no profile")),
    ):
        from xcli.drivers.browser import validate_session

        result = await validate_session()

    assert result is False
    drv.reset_browser_for_testing()


@pytest.mark.asyncio
async def test_ensure_authenticated_raises_when_not_authed() -> None:
    """ensure_authenticated should raise AuthenticationError if session invalid."""
    import xcli.drivers.browser as drv
    from xcli.exceptions import AuthenticationError

    drv.reset_browser_for_testing()

    mock_page = MagicMock()
    mock_page.url = "https://x.com/home"

    mock_browser = MagicMock()
    mock_browser.is_authenticated = False
    mock_browser.page = mock_page

    with (
        patch(
            "xcli.drivers.browser.get_or_create_browser",
            new=AsyncMock(return_value=mock_browser),
        ),
        patch("xcli.drivers.browser.is_logged_in", new=AsyncMock(return_value=False)),
    ):
        from xcli.drivers.browser import ensure_authenticated

        with pytest.raises(AuthenticationError):
            await ensure_authenticated()

    drv.reset_browser_for_testing()
