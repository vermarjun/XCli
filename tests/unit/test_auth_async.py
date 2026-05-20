"""Unit tests for xcli.core.auth async functions with mock Page objects.

These test the browser-facing auth helpers without a real Patchright instance.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_page(url: str = "https://x.com/home") -> MagicMock:
    page = MagicMock()
    page.url = url
    page.goto = AsyncMock()
    page.title = AsyncMock(return_value="X / Home")
    page.evaluate = AsyncMock(return_value="")
    page.locator = MagicMock()
    page.locator.return_value.count = AsyncMock(return_value=0)
    page.locator.return_value.inner_text = AsyncMock(return_value="")
    return page


# ---------------------------------------------------------------------------
# warm_up_browser
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_warm_up_browser_visits_sites() -> None:
    """warm_up_browser should attempt to visit normal sites."""
    from xcli.core.auth import warm_up_browser

    page = _make_mock_page()
    visited: list[str] = []

    async def _fake_goto(url, **kwargs):
        visited.append(url)

    page.goto = _fake_goto

    await warm_up_browser(page)

    # Should visit at least one site (some might fail, that's OK)
    assert len(visited) >= 1
    assert any("google.com" in v or "wikipedia.org" in v or "github.com" in v for v in visited)


@pytest.mark.asyncio
async def test_warm_up_browser_tolerates_network_failures() -> None:
    """warm_up_browser should not raise if all warm-up sites are unreachable."""
    from xcli.core.auth import warm_up_browser

    page = _make_mock_page()
    page.goto = AsyncMock(side_effect=Exception("Network unreachable"))

    # Should not raise
    await warm_up_browser(page)


# ---------------------------------------------------------------------------
# is_logged_in
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_is_logged_in_false_on_login_url() -> None:
    """is_logged_in should return False if the page URL is an auth blocker."""
    from xcli.core.auth import is_logged_in

    page = _make_mock_page(url="https://x.com/i/flow/login")
    result = await is_logged_in(page)
    assert result is False


@pytest.mark.asyncio
async def test_is_logged_in_true_when_nav_element_present() -> None:
    """is_logged_in should return True when the account-switcher button is found."""
    from xcli.core.auth import is_logged_in

    page = _make_mock_page(url="https://x.com/home")

    nav_locator = MagicMock()
    nav_locator.count = AsyncMock(return_value=1)

    def _locator(selector):
        return nav_locator

    page.locator = _locator

    result = await is_logged_in(page)
    assert result is True


@pytest.mark.asyncio
async def test_is_logged_in_false_when_no_nav_and_not_authed_url() -> None:
    """is_logged_in should return False with no nav elements on a non-authed page."""
    from xcli.core.auth import is_logged_in

    page = _make_mock_page(url="https://x.com/somerandompagepath")

    no_nav_locator = MagicMock()
    no_nav_locator.count = AsyncMock(return_value=0)
    page.locator = MagicMock(return_value=no_nav_locator)

    result = await is_logged_in(page)
    assert result is False


@pytest.mark.asyncio
async def test_is_logged_in_body_fallback_on_authed_page() -> None:
    """On an authenticated-only page without nav elements, check body text."""
    from xcli.core.auth import is_logged_in

    page = _make_mock_page(url="https://x.com/home")
    # No nav elements
    no_nav_locator = MagicMock()
    no_nav_locator.count = AsyncMock(return_value=0)
    page.locator = MagicMock(return_value=no_nav_locator)
    # But body has content
    page.evaluate = AsyncMock(return_value="Some feed content")

    result = await is_logged_in(page)
    # /home is in AUTHED_URL_SEGMENTS → body check → True (non-empty body)
    assert result is True


@pytest.mark.asyncio
async def test_is_logged_in_false_empty_body_on_authed_page() -> None:
    """On authenticated page with no nav and empty body → False."""
    from xcli.core.auth import is_logged_in

    page = _make_mock_page(url="https://x.com/home")
    no_nav_locator = MagicMock()
    no_nav_locator.count = AsyncMock(return_value=0)
    page.locator = MagicMock(return_value=no_nav_locator)
    page.evaluate = AsyncMock(return_value="")

    result = await is_logged_in(page)
    assert result is False


# ---------------------------------------------------------------------------
# detect_rate_limit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detect_rate_limit_raises_on_account_access() -> None:
    """detect_rate_limit should raise RateLimitError on /account/access URL."""
    from xcli.core.auth import detect_rate_limit
    from xcli.exceptions import RateLimitError

    page = _make_mock_page(url="https://x.com/account/access")

    with pytest.raises(RateLimitError):
        await detect_rate_limit(page)


@pytest.mark.asyncio
async def test_detect_rate_limit_no_raise_on_normal_page() -> None:
    """detect_rate_limit should not raise on a normal page."""
    from xcli.core.auth import detect_rate_limit

    page = _make_mock_page(url="https://x.com/home")

    # primaryColumn is present (count > 0)
    primary_locator = MagicMock()
    primary_locator.count = AsyncMock(return_value=1)
    page.locator = MagicMock(return_value=primary_locator)

    # Should not raise
    await detect_rate_limit(page)


@pytest.mark.asyncio
async def test_detect_rate_limit_raises_on_soft_block_body() -> None:
    """detect_rate_limit should raise RateLimitError when body has soft-block markers."""
    from xcli.core.auth import detect_rate_limit
    from xcli.exceptions import RateLimitError

    page = _make_mock_page(url="https://x.com/home")

    # No primary column
    primary_locator = MagicMock()
    primary_locator.count = AsyncMock(return_value=0)

    # Body with soft-block text
    body_locator = MagicMock()
    body_locator.inner_text = AsyncMock(return_value="Something went wrong Try reloading")

    def _locator(selector):
        if "primaryColumn" in selector:
            return primary_locator
        return body_locator

    page.locator = _locator

    with pytest.raises(RateLimitError):
        await detect_rate_limit(page)
