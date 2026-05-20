"""Integration tests for auth detection against fixture HTML pages.

Tests navigate to each fixture using the local aiohttp server and assert the
expected verdicts from is_logged_in, detect_auth_barrier, detect_rate_limit.

All tests are async and use the `browser` + `fixture_server` fixtures from
conftest.py.
"""

from __future__ import annotations

import pytest

from xcli.core.auth import (
    detect_auth_barrier,
    detect_rate_limit,
    is_logged_in,
)
from xcli.exceptions import RateLimitError

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def goto(browser, fixture_server, filename: str) -> None:
    """Navigate browser to a fixture HTML file served from the local server."""
    url = f"{fixture_server}/{filename}"
    await browser.page.goto(url, wait_until="domcontentloaded")


# ---------------------------------------------------------------------------
# home_feed.html — authenticated feed page
# ---------------------------------------------------------------------------


async def test_home_feed_is_logged_in(browser, fixture_server) -> None:
    """Home feed fixture has SideNav_AccountSwitcher_Button → is_logged_in=True."""
    await goto(browser, fixture_server, "home_feed.html")
    result = await is_logged_in(browser.page)
    assert result is True


async def test_home_feed_no_auth_barrier(browser, fixture_server) -> None:
    """Home feed fixture should not trigger detect_auth_barrier."""
    await goto(browser, fixture_server, "home_feed.html")
    barrier = await detect_auth_barrier(browser.page)
    assert barrier is None, f"Unexpected auth barrier on feed page: {barrier!r}"


async def test_home_feed_no_rate_limit(browser, fixture_server) -> None:
    """Home feed fixture has primaryColumn → detect_rate_limit should not raise."""
    await goto(browser, fixture_server, "home_feed.html")
    # Should not raise
    await detect_rate_limit(browser.page)


# ---------------------------------------------------------------------------
# login_wall.html — auth barrier page
# ---------------------------------------------------------------------------


async def test_login_wall_not_logged_in(browser, fixture_server) -> None:
    """Login wall has no SideNav element → is_logged_in=False."""
    await goto(browser, fixture_server, "login_wall.html")
    result = await is_logged_in(browser.page)
    assert result is False


async def test_login_wall_detects_barrier(browser, fixture_server) -> None:
    """Login wall should be detected by detect_auth_barrier (title match)."""
    await goto(browser, fixture_server, "login_wall.html")
    barrier = await detect_auth_barrier(browser.page)
    assert barrier is not None, "Expected an auth barrier to be detected on login_wall.html"
    assert "login" in barrier.lower(), f"Barrier reason should mention login: {barrier!r}"


# ---------------------------------------------------------------------------
# something_went_wrong.html — soft-block page
# ---------------------------------------------------------------------------


async def test_soft_block_not_logged_in(browser, fixture_server) -> None:
    """Soft-block page has no SideNav element → is_logged_in=False."""
    await goto(browser, fixture_server, "something_went_wrong.html")
    result = await is_logged_in(browser.page)
    assert result is False


async def test_soft_block_raises_rate_limit(browser, fixture_server) -> None:
    """Soft-block page: body has 'Something went wrong' + no primaryColumn → RateLimitError."""
    await goto(browser, fixture_server, "something_went_wrong.html")
    with pytest.raises(RateLimitError):
        await detect_rate_limit(browser.page)


# ---------------------------------------------------------------------------
# profile_normal.html — authenticated profile page
# ---------------------------------------------------------------------------


async def test_profile_normal_is_logged_in(browser, fixture_server) -> None:
    """Profile page fixture has SideNav → is_logged_in=True."""
    await goto(browser, fixture_server, "profile_normal.html")
    result = await is_logged_in(browser.page)
    assert result is True


async def test_profile_normal_no_auth_barrier(browser, fixture_server) -> None:
    """Normal profile page should not trigger an auth barrier."""
    await goto(browser, fixture_server, "profile_normal.html")
    barrier = await detect_auth_barrier(browser.page)
    assert barrier is None, f"Unexpected auth barrier on profile page: {barrier!r}"
