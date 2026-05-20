"""ProfileTool — deep-research a user's X profile, posts, and comments.

Exposes a single async entry point:
    run(username, posts, comments_per, headless) -> dict

Output schema matches plan §4.2.
"""

from __future__ import annotations

import asyncio
from typing import Any

from xcli.drivers.browser import ensure_authenticated, get_or_create_browser
from xcli.scraping.extractor import XExtractor

# Module-level lock — serialise all ProfileTool runs (only one browser instance).
_lock = asyncio.Lock()


async def run(
    username: str,
    posts: int,
    comments_per: int,
    headless: bool = True,
) -> dict[str, Any]:
    """Deep-research a user profile: bio + top N posts + Y comments each.

    Args:
        username:     X handle to research (without leading ``@``).
        posts:        Number of profile posts to return (ads excluded).
        comments_per: Number of top reply comments to fetch per post.
        headless:     Whether to run the browser in headless mode.

    Returns:
        Profile dict matching plan §4.2 schema:
        {captured_at, username, url, profile, posts, warnings}

    Raises:
        AuthenticationError: If session is expired or no login profile exists.
        RateLimitError: If X hard-blocks the session at /account/access.
        XCliError: For other xcli-level failures.
    """
    async with _lock:
        browser = await get_or_create_browser(headless=headless)
        await ensure_authenticated()
        extractor = XExtractor(browser.page)
        return await extractor.research_profile(username, posts, comments_per)
