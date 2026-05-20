"""Unit tests for xcli.tools.feed and xcli.tools.profile.

All browser calls are monkeypatched so these tests are hermetic.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_feed_result(n: int = 2) -> dict:
    posts = [
        {
            "id": str(1000 + i),
            "url": f"https://x.com/user/status/{1000 + i}",
            "author": {"username": "user", "display_name": "User", "verified": False},
            "text": f"Post {i}",
            "innertext": f"Post {i} inner",
            "posted_at": "2026-05-19T10:00:00Z",
            "metrics": {"likes": i, "replies": 0, "reposts": 0, "views": 0, "bookmarks": 0},
            "links": [],
            "media": [],
            "is_repost": False,
            "reposted_by": None,
            "is_ad": False,
            "comments": [],
            "comments_captured": 0,
            "comments_partial": False,
        }
        for i in range(n)
    ]
    return {
        "captured_at": "2026-05-19T12:00:00Z",
        "feed_account": "testuser",
        "count_requested": n,
        "count_captured": n,
        "comments_per_requested": 0,
        "posts": posts,
        "warnings": [],
    }


def _make_profile_result(username: str = "elonmusk") -> dict:
    return {
        "captured_at": "2026-05-19T12:00:00Z",
        "username": username,
        "url": f"https://x.com/{username}/",
        "profile": {
            "display_name": "Elon Musk",
            "handle": f"@{username}",
            "bio": "CEO",
            "bio_innertext": "CEO",
            "verified": True,
            "verified_kind": "blue",
            "location": "Earth",
            "website": None,
            "joined": "Joined June 2009",
            "joined_iso": "2009-06",
            "following_count": 200,
            "followers_count": 200_000_000,
            "links": [],
            "protected": False,
            "suspended": False,
            "not_found": False,
        },
        "posts": [],
        "warnings": [],
    }


def _make_mock_browser():
    """Return a minimal mock BrowserManager with a page attribute."""
    browser = MagicMock()
    browser.page = MagicMock()
    browser.is_authenticated = True
    return browser


# ---------------------------------------------------------------------------
# FeedTool.run
# ---------------------------------------------------------------------------


class TestFeedToolRun:
    @pytest.mark.asyncio
    async def test_run_returns_feed_dict(self):
        """run() should return the extractor result directly."""
        from xcli.tools.feed import run

        expected = _make_feed_result(2)
        mock_browser = _make_mock_browser()

        with (
            patch(
                "xcli.tools.feed.get_or_create_browser", new=AsyncMock(return_value=mock_browser)
            ),
            patch("xcli.tools.feed.ensure_authenticated", new=AsyncMock()),
            patch(
                "xcli.scraping.extractor.XExtractor.fetch_feed",
                new=AsyncMock(return_value=expected),
            ),
        ):
            result = await run(count=2, comments_per=0)

        assert result == expected

    @pytest.mark.asyncio
    async def test_run_uses_config_jitter_by_default(self):
        """When jitter_pct=None, run() reads config.browser.jitter_pct."""
        from xcli.tools.feed import run

        expected = _make_feed_result(1)
        mock_browser = _make_mock_browser()
        captured_jitter: list[float] = []

        async def _fake_fetch_feed(self_extractor, count, comments_per):
            captured_jitter.append(self_extractor._jitter_pct)
            return expected

        with (
            patch(
                "xcli.tools.feed.get_or_create_browser", new=AsyncMock(return_value=mock_browser)
            ),
            patch("xcli.tools.feed.ensure_authenticated", new=AsyncMock()),
            patch("xcli.scraping.extractor.XExtractor.fetch_feed", new=_fake_fetch_feed),
        ):
            await run(count=1, comments_per=0, jitter_pct=None)

        # Default jitter_pct from BrowserConfig is 0.2
        assert len(captured_jitter) == 1
        assert captured_jitter[0] == pytest.approx(0.2)

    @pytest.mark.asyncio
    async def test_run_overrides_jitter_pct(self):
        """Explicit jitter_pct overrides config."""
        from xcli.tools.feed import run

        expected = _make_feed_result(1)
        mock_browser = _make_mock_browser()
        captured_jitter: list[float] = []

        async def _fake_fetch_feed(self_extractor, count, comments_per):
            captured_jitter.append(self_extractor._jitter_pct)
            return expected

        with (
            patch(
                "xcli.tools.feed.get_or_create_browser", new=AsyncMock(return_value=mock_browser)
            ),
            patch("xcli.tools.feed.ensure_authenticated", new=AsyncMock()),
            patch("xcli.scraping.extractor.XExtractor.fetch_feed", new=_fake_fetch_feed),
        ):
            await run(count=1, comments_per=0, jitter_pct=0.0)

        assert captured_jitter[0] == 0.0

    @pytest.mark.asyncio
    async def test_run_headless_passed_through(self):
        """headless parameter is forwarded to get_or_create_browser."""
        from xcli.tools.feed import run

        expected = _make_feed_result(1)
        mock_browser = _make_mock_browser()
        captured: list[dict] = []

        async def _fake_get_browser(headless=None):
            captured.append({"headless": headless})
            return mock_browser

        with (
            patch("xcli.tools.feed.get_or_create_browser", new=_fake_get_browser),
            patch("xcli.tools.feed.ensure_authenticated", new=AsyncMock()),
            patch(
                "xcli.scraping.extractor.XExtractor.fetch_feed",
                new=AsyncMock(return_value=expected),
            ),
        ):
            await run(count=1, comments_per=0, headless=False)

        assert captured[0]["headless"] is False


# ---------------------------------------------------------------------------
# ProfileTool.run
# ---------------------------------------------------------------------------


class TestProfileToolRun:
    @pytest.mark.asyncio
    async def test_run_returns_profile_dict(self):
        """run() should return the extractor result directly."""
        from xcli.tools.profile import run

        expected = _make_profile_result("elonmusk")
        mock_browser = _make_mock_browser()

        with (
            patch(
                "xcli.tools.profile.get_or_create_browser",
                new=AsyncMock(return_value=mock_browser),
            ),
            patch("xcli.tools.profile.ensure_authenticated", new=AsyncMock()),
            patch(
                "xcli.scraping.extractor.XExtractor.research_profile",
                new=AsyncMock(return_value=expected),
            ),
        ):
            result = await run(username="elonmusk", posts=1, comments_per=0)

        assert result == expected

    @pytest.mark.asyncio
    async def test_run_uses_config_jitter_by_default(self):
        """When jitter_pct=None, run() reads config.browser.jitter_pct."""
        from xcli.tools.profile import run

        expected = _make_profile_result("elonmusk")
        mock_browser = _make_mock_browser()
        captured_jitter: list[float] = []

        async def _fake_research(self_extractor, username, posts, comments_per):
            captured_jitter.append(self_extractor._jitter_pct)
            return expected

        with (
            patch(
                "xcli.tools.profile.get_or_create_browser",
                new=AsyncMock(return_value=mock_browser),
            ),
            patch("xcli.tools.profile.ensure_authenticated", new=AsyncMock()),
            patch("xcli.scraping.extractor.XExtractor.research_profile", new=_fake_research),
        ):
            await run(username="elonmusk", posts=1, comments_per=0, jitter_pct=None)

        assert captured_jitter[0] == pytest.approx(0.2)

    @pytest.mark.asyncio
    async def test_run_explicit_jitter_pct(self):
        """Explicit jitter_pct is wired into XExtractor."""
        from xcli.tools.profile import run

        expected = _make_profile_result("elonmusk")
        mock_browser = _make_mock_browser()
        captured_jitter: list[float] = []

        async def _fake_research(self_extractor, username, posts, comments_per):
            captured_jitter.append(self_extractor._jitter_pct)
            return expected

        with (
            patch(
                "xcli.tools.profile.get_or_create_browser",
                new=AsyncMock(return_value=mock_browser),
            ),
            patch("xcli.tools.profile.ensure_authenticated", new=AsyncMock()),
            patch("xcli.scraping.extractor.XExtractor.research_profile", new=_fake_research),
        ):
            await run(username="elonmusk", posts=1, comments_per=0, jitter_pct=0.5)

        assert captured_jitter[0] == pytest.approx(0.5)

    @pytest.mark.asyncio
    async def test_run_headless_passed_through(self):
        """headless parameter is forwarded to get_or_create_browser."""
        from xcli.tools.profile import run

        expected = _make_profile_result("elonmusk")
        mock_browser = _make_mock_browser()
        captured: list[dict] = []

        async def _fake_get_browser(headless=None):
            captured.append({"headless": headless})
            return mock_browser

        with (
            patch("xcli.tools.profile.get_or_create_browser", new=_fake_get_browser),
            patch("xcli.tools.profile.ensure_authenticated", new=AsyncMock()),
            patch(
                "xcli.scraping.extractor.XExtractor.research_profile",
                new=AsyncMock(return_value=expected),
            ),
        ):
            await run(username="elonmusk", posts=1, comments_per=0, headless=True)

        assert captured[0]["headless"] is True
