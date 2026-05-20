"""Unit tests for xcli.core.auth pure/synchronous helpers.

Tests _is_auth_blocker_url (the only pure function in that module).
The async helpers (is_logged_in, detect_auth_barrier, detect_rate_limit) require
a Patchright Page and are covered by the integration suite.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# _is_auth_blocker_url
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url, expected",
    [
        # Exact auth blocker paths
        ("https://x.com/i/flow/login", True),
        ("https://x.com/login", True),
        ("https://x.com/account/access", True),
        ("https://x.com/i/flow/signup", True),
        # With trailing slash
        ("https://x.com/i/flow/login/", True),
        ("https://x.com/account/access/", True),
        # Sub-paths
        ("https://x.com/i/flow/login/substep", True),
        ("https://x.com/account/access/confirm", True),
        # Normal pages — NOT auth blockers
        ("https://x.com/home", False),
        ("https://x.com/elonmusk", False),
        ("https://x.com/notifications", False),
        ("https://x.com/messages", False),
        # Edge: partial match without path boundary
        ("https://x.com/i/flow/login_something_else", False),
        # With query string — path extracted correctly
        ("https://x.com/i/flow/login?next=home", True),
        # Empty URL
        ("", False),
        # Non-X URL with matching path — _is_auth_blocker_url checks path only (not domain).
        # /login is in AUTH_BLOCKER_URL_PATHS so this returns True (path match, not domain match).
        ("https://other.com/login", True),
    ],
)
def test_is_auth_blocker_url(url: str, expected: bool) -> None:
    from xcli.core.auth import _is_auth_blocker_url

    result = _is_auth_blocker_url(url)
    assert result == expected, f"_is_auth_blocker_url({url!r}) → {result!r}, expected {expected!r}"


# ---------------------------------------------------------------------------
# Selectors / constants imported in auth.py (smoke-test the import surface)
# ---------------------------------------------------------------------------


def test_auth_module_constants_exist() -> None:
    """Smoke test that key constants used by auth module are importable."""
    from xcli.scraping.selectors import (
        AUTH_BLOCKER_URL_PATHS,
        AUTHED_URL_SEGMENTS,
        LOGGED_IN_SELECTORS,
        LOGIN_TITLE_PATTERNS,
        PRIMARY_COLUMN,
        SOFT_BLOCK_BODY_MARKERS,
    )

    assert AUTH_BLOCKER_URL_PATHS
    assert AUTHED_URL_SEGMENTS
    assert LOGGED_IN_SELECTORS
    assert LOGIN_TITLE_PATTERNS
    assert PRIMARY_COLUMN
    assert SOFT_BLOCK_BODY_MARKERS


# ---------------------------------------------------------------------------
# detect_auth_barrier_quick / detect_auth_barrier — async, page-dependent
# Tested here with a minimal mock Page to exercise the URL-branch code paths.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detect_auth_barrier_quick_auth_blocker_url() -> None:
    """detect_auth_barrier_quick should return a string when URL is an auth blocker."""
    from unittest.mock import AsyncMock, MagicMock

    from xcli.core.auth import detect_auth_barrier_quick

    mock_page = MagicMock()
    mock_page.url = "https://x.com/i/flow/login"
    mock_page.title = AsyncMock(return_value="Log in to X")

    result = await detect_auth_barrier_quick(mock_page)
    assert result is not None
    assert "auth blocker" in result.lower() or "flow/login" in result.lower()


@pytest.mark.asyncio
async def test_detect_auth_barrier_quick_normal_page_returns_none() -> None:
    """detect_auth_barrier_quick should return None on a normal page."""
    from unittest.mock import AsyncMock, MagicMock

    from xcli.core.auth import detect_auth_barrier_quick

    mock_page = MagicMock()
    mock_page.url = "https://x.com/home"
    mock_page.title = AsyncMock(return_value="X / Home")

    result = await detect_auth_barrier_quick(mock_page)
    assert result is None


@pytest.mark.asyncio
async def test_detect_auth_barrier_quick_login_title() -> None:
    """detect_auth_barrier_quick should detect login title patterns."""
    from unittest.mock import AsyncMock, MagicMock

    from xcli.core.auth import detect_auth_barrier_quick

    mock_page = MagicMock()
    mock_page.url = "https://x.com/some_page"
    mock_page.title = AsyncMock(return_value="Log in to X / Twitter")

    result = await detect_auth_barrier_quick(mock_page)
    assert result is not None
    assert "login title" in result.lower()
