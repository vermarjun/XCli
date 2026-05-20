"""FeedTool — fetch authenticated home-feed posts with comments.

Exposes a single async entry point:
    run(count, comments_per, headless) -> dict

Output schema matches plan §4.1.
"""

from __future__ import annotations

import asyncio
from typing import Any

from xcli.drivers.browser import ensure_authenticated, get_or_create_browser
from xcli.scraping.extractor import XExtractor

# Module-level lock — serialise all FeedTool runs (only one browser instance).
_lock = asyncio.Lock()


async def run(
    count: int,
    comments_per: int,
    headless: bool = True,
) -> dict[str, Any]:
    """Fetch top ``count`` posts from the authenticated user's home feed.

    Args:
        count:        Number of posts to return (ads excluded).
        comments_per: Number of top reply comments to fetch per post.
        headless:     Whether to run the browser in headless mode.

    Returns:
        Feed dict matching plan §4.1 schema:
        {captured_at, feed_account, count_requested, count_captured,
         comments_per_requested, posts, warnings}

    Raises:
        AuthenticationError: If session is expired or no login profile exists.
        RateLimitError: If X hard-blocks the session at /account/access.
        XCliError: For other xcli-level failures.
    """
    async with _lock:
        browser = await get_or_create_browser(headless=headless)
        await ensure_authenticated()
        extractor = XExtractor(browser.page)
        return await extractor.fetch_feed(count, comments_per)
