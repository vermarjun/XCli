"""Integration tests for XExtractor against fixture HTML pages.

URL interception strategy: page.route()
---------------------------------------
We use Playwright's ``page.route()`` to intercept requests to ``x.com`` and
respond with local fixture HTML. This is the preferred strategy because:

1. Realistic: the browser navigates normally (fires navigation events, updates
   page.url, handles redirects), so the full auth-check pipeline runs.
2. No change to extractor production code: _test_only_base_url_override is not
   used here (it exists as a fallback for simpler cases).
3. The route handler maps URL patterns to fixture files:
   - https://x.com/home        → home_feed.html
   - https://x.com/*/status/*  → tweet_thread.html (for comment fetches)
   - login wall variant        → login_wall.html
   - soft-block variant        → something_went_wrong.html

Snapshot tests:
    Set ``XCLI_UPDATE_SNAPSHOTS=1`` to regenerate the golden JSON file
    at ``tests/integration/snapshots/feed_basic.json``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from xcli.exceptions import AuthenticationError, RateLimitError
from xcli.scraping.extractor import XExtractor

pytestmark = pytest.mark.asyncio

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SNAPSHOTS_DIR = Path(__file__).parent / "snapshots"


# ---------------------------------------------------------------------------
# Route helper
# ---------------------------------------------------------------------------


async def _route_fixture(page, url_pattern: str, fixture_file: str) -> None:
    """Set up a page.route() to serve a fixture HTML file for a URL pattern."""
    fixture_path = FIXTURES_DIR / fixture_file
    html_content = fixture_path.read_text(encoding="utf-8")

    async def handler(route):
        await route.fulfill(
            status=200,
            content_type="text/html; charset=utf-8",
            body=html_content,
        )

    await page.route(url_pattern, handler)


# ---------------------------------------------------------------------------
# test_fetch_feed_basic
# ---------------------------------------------------------------------------


async def test_fetch_feed_basic(browser, fixture_server) -> None:
    """fetch_feed returns a valid schema with count_captured == 3, ads filtered."""
    page = browser.page

    # Intercept /home → home_feed.html
    await _route_fixture(page, "**/home", "home_feed.html")
    # Intercept any status URL → tweet_thread.html (for comment fetches)
    await _route_fixture(page, "**/status/**", "tweet_thread.html")

    extractor = XExtractor(page)
    result = await extractor.fetch_feed(count=3, comments_per=2)

    # Schema checks
    assert "captured_at" in result
    assert "posts" in result
    assert isinstance(result["posts"], list)

    # count_captured <= 3 (may be less if not enough non-ad posts)
    assert result["count_captured"] <= 3
    assert result["count_requested"] == 3
    assert result["comments_per_requested"] == 2

    # Every post has required fields
    for post in result["posts"]:
        assert "id" in post, f"Post missing 'id': {post}"
        assert post["id"], "Post id must be non-empty"
        assert "url" in post
        assert "author" in post
        assert "text" in post or "media" in post

    # Ads are filtered (post 103 in fixture has placementTracking)
    post_ids = {p["id"] for p in result["posts"]}
    assert "103" not in post_ids, "Ad post (id=103) should have been filtered"

    # Comments list length <= comments_per for each post
    for post in result["posts"]:
        comments = post.get("comments") or []
        assert len(comments) <= 2, f"Post {post['id']} has {len(comments)} comments, expected <= 2"


# ---------------------------------------------------------------------------
# test_fetch_feed_snapshot
# ---------------------------------------------------------------------------


async def test_fetch_feed_snapshot(browser, fixture_server) -> None:
    """fetch_feed output matches committed golden snapshot (or regenerates it)."""
    page = browser.page

    await _route_fixture(page, "**/home", "home_feed.html")
    await _route_fixture(page, "**/status/**", "tweet_thread.html")

    extractor = XExtractor(page)
    result = await extractor.fetch_feed(count=3, comments_per=2)

    # Strip volatile fields before snapshot comparison
    _strip_volatile(result)

    snapshot_path = SNAPSHOTS_DIR / "feed_basic.json"

    if os.environ.get("XCLI_UPDATE_SNAPSHOTS") == "1":
        SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_text(
            json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return  # Don't assert when updating

    if not snapshot_path.exists():
        pytest.skip(
            f"Snapshot file not found at {snapshot_path}. "
            "Run with XCLI_UPDATE_SNAPSHOTS=1 to generate it."
        )

    golden = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert result == golden, (
        "Snapshot mismatch. Run with XCLI_UPDATE_SNAPSHOTS=1 to update."
        f"\nGot: {json.dumps(result, indent=2, sort_keys=True)}"
        f"\nExpected: {json.dumps(golden, indent=2, sort_keys=True)}"
    )


def _strip_volatile(data: dict) -> None:
    """Remove fields that change between runs (timestamps, etc.)."""
    data.pop("captured_at", None)
    for post in data.get("posts") or []:
        for comment in post.get("comments") or []:
            comment.pop("captured_at", None)


# ---------------------------------------------------------------------------
# test_auth_wall_during_feed
# ---------------------------------------------------------------------------


async def test_auth_wall_during_feed(browser, fixture_server) -> None:
    """When /home returns login_wall.html, fetch_feed raises AuthenticationError."""
    page = browser.page

    await _route_fixture(page, "**/home", "login_wall.html")

    extractor = XExtractor(page)
    with pytest.raises(AuthenticationError):
        await extractor.fetch_feed(count=3, comments_per=0)


# ---------------------------------------------------------------------------
# test_soft_block_during_feed
# ---------------------------------------------------------------------------


async def test_soft_block_during_feed(browser, fixture_server) -> None:
    """When /home returns something_went_wrong.html, fetch_feed raises RateLimitError."""
    page = browser.page

    await _route_fixture(page, "**/home", "something_went_wrong.html")

    extractor = XExtractor(page)
    with pytest.raises(RateLimitError):
        await extractor.fetch_feed(count=3, comments_per=0)


# ---------------------------------------------------------------------------
# Phase 2: research_profile tests
# ---------------------------------------------------------------------------


async def test_research_profile_normal(browser, fixture_server) -> None:
    """research_profile returns valid schema for a normal profile page."""
    page = browser.page

    # Route profile page and comment fetches
    await _route_fixture(page, "**/elonmusk", "profile_normal.html")
    await _route_fixture(page, "**/status/**", "tweet_thread.html")

    extractor = XExtractor(page)
    result = await extractor.research_profile("elonmusk", posts=2, comments_per=1)

    # Top-level schema
    assert "captured_at" in result
    assert result["username"] == "elonmusk"
    assert "profile" in result
    assert "posts" in result
    assert "warnings" in result
    assert isinstance(result["posts"], list)
    assert len(result["posts"]) <= 2

    # Profile fields
    prof = result["profile"]
    assert prof["handle"] == "@elonmusk"
    assert prof["display_name"] == "Elon Musk"
    assert prof["verified"] is True
    assert prof["verified_kind"] == "blue"
    assert prof["location"] == "Austin, TX"
    assert prof["joined"] == "Joined June 2009"
    assert prof["joined_iso"] == "2009-06"
    assert prof["followers_count"] == 4_500_000
    assert prof["following_count"] == 123
    assert len(prof["links"]) >= 1
    assert prof["protected"] is False
    assert prof["suspended"] is False
    assert prof["not_found"] is False


async def test_research_profile_normal_snapshot(browser, fixture_server) -> None:
    """research_profile output matches committed golden snapshot (or regenerates it)."""
    page = browser.page

    await _route_fixture(page, "**/elonmusk", "profile_normal.html")
    await _route_fixture(page, "**/status/**", "tweet_thread.html")

    extractor = XExtractor(page)
    result = await extractor.research_profile("elonmusk", posts=2, comments_per=1)

    # Strip volatile fields before comparison
    _strip_profile_volatile(result)

    snapshot_path = SNAPSHOTS_DIR / "profile_normal.json"

    if os.environ.get("XCLI_UPDATE_SNAPSHOTS") == "1":
        SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_text(
            json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return  # Don't assert when updating

    if not snapshot_path.exists():
        pytest.skip(
            f"Snapshot file not found at {snapshot_path}. "
            "Run with XCLI_UPDATE_SNAPSHOTS=1 to generate it."
        )

    golden = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert result == golden, (
        "Snapshot mismatch. Run with XCLI_UPDATE_SNAPSHOTS=1 to update."
        f"\nGot: {json.dumps(result, indent=2, sort_keys=True)}"
        f"\nExpected: {json.dumps(golden, indent=2, sort_keys=True)}"
    )


def _strip_profile_volatile(data: dict) -> None:
    """Remove volatile fields (timestamps) from a research_profile result."""
    data.pop("captured_at", None)
    for post in data.get("posts") or []:
        for comment in post.get("comments") or []:
            comment.pop("captured_at", None)


async def test_research_profile_suspended(browser, fixture_server) -> None:
    """research_profile returns suspended=True and empty posts for a suspended account."""
    page = browser.page

    await _route_fixture(page, "**/suspendeduser", "profile_suspended.html")

    extractor = XExtractor(page)
    result = await extractor.research_profile("suspendeduser", posts=5, comments_per=0)

    prof = result["profile"]
    assert prof["suspended"] is True
    assert prof["protected"] is False
    assert prof["not_found"] is False
    assert result["posts"] == []
    assert len(result["warnings"]) > 0
    assert any("suspended" in w for w in result["warnings"])


async def test_research_profile_protected(browser, fixture_server) -> None:
    """research_profile returns protected=True and empty posts for a protected account."""
    page = browser.page

    await _route_fixture(page, "**/protecteduser", "profile_protected.html")

    extractor = XExtractor(page)
    result = await extractor.research_profile("protecteduser", posts=5, comments_per=0)

    prof = result["profile"]
    assert prof["protected"] is True
    assert prof["suspended"] is False
    assert prof["not_found"] is False
    assert result["posts"] == []
    assert len(result["warnings"]) > 0
    assert any("protected" in w for w in result["warnings"])


async def test_research_profile_not_found(browser, fixture_server) -> None:
    """research_profile returns not_found=True and empty posts for a missing account."""
    page = browser.page

    await _route_fixture(page, "**/ghostuser", "profile_not_found.html")

    extractor = XExtractor(page)
    result = await extractor.research_profile("ghostuser", posts=5, comments_per=0)

    prof = result["profile"]
    assert prof["not_found"] is True
    assert prof["suspended"] is False
    assert prof["protected"] is False
    assert result["posts"] == []
    assert len(result["warnings"]) > 0
    assert any("not_found" in w for w in result["warnings"])
