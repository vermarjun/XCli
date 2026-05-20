"""Authentication helpers for X (Twitter).

Mirrors linkedin_mcp_server/core/auth.py but adapted for X's URL structure,
selector surface, and session semantics.

Key differences from LinkedIn:
- Auth blocker URLs: /i/flow/login, /login, /account/access, /i/flow/signup
- Logged-in signal: data-testid="SideNav_AccountSwitcher_Button" (primary)
- Rate-limit signal: /account/access URL OR "Something went wrong" body + no primaryColumn
- No remember-me prompt (X does not use that UI pattern)
- No resolve_remember_me_prompt helper
"""

import asyncio
import logging
import re
from urllib.parse import urlparse

from patchright.async_api import Page
from patchright.async_api import TimeoutError as PlaywrightTimeoutError

from xcli.exceptions import AuthenticationError, RateLimitError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants (inline here for Phase 0; Phase 1 will centralize in selectors.py)
# ---------------------------------------------------------------------------

_AUTH_BLOCKER_URL_PATHS = (
    "/i/flow/login",
    "/login",
    "/account/access",
    "/i/flow/signup",
)

_LOGIN_TITLE_PATTERNS = (
    "log in to x",
    "log in to twitter",
    "sign in to x",
    "sign in to twitter",
)

_AUTH_BARRIER_TEXT_MARKERS = (
    ("Don't miss what's happening", "Log in"),
    ("Sign up to continue",),
)

_SOFT_BLOCK_BODY_MARKERS = (
    "Something went wrong",
    "Try reloading",
    "Rate limit exceeded",
)

# Selector for the primary content column — absence signals a soft-block page
_PRIMARY_COLUMN_SELECTOR = '[data-testid="primaryColumn"]'

# Logged-in navigation signals (structural, not text-dependent)
_LOGGED_IN_SELECTORS = (
    '[data-testid="SideNav_AccountSwitcher_Button"]',
    '[data-testid="AppTabBar_Profile_Link"]',
)

# Authenticated-only URL segments (URL-based fallback for is_logged_in)
_AUTHED_URL_SEGMENTS = ("/home", "/notifications", "/messages")


# ---------------------------------------------------------------------------
# Warm-up
# ---------------------------------------------------------------------------


async def warm_up_browser(page: Page) -> None:
    """Visit ordinary sites to appear more human-like before any X.com hit."""
    sites = [
        "https://www.google.com",
        "https://www.wikipedia.org",
        "https://www.github.com",
    ]
    logger.info("Warming up browser by visiting normal sites...")
    failures = 0
    for site in sites:
        try:
            await page.goto(site, wait_until="domcontentloaded", timeout=10000)
            await asyncio.sleep(1)
            logger.debug("Visited %s", site)
        except Exception as e:
            failures += 1
            logger.debug("Could not visit %s: %s", site, e)
    if failures == len(sites):
        logger.warning("Browser warm-up failed: none of %d sites reachable", len(sites))
    else:
        logger.info("Browser warm-up complete")


# ---------------------------------------------------------------------------
# is_logged_in
# ---------------------------------------------------------------------------


async def is_logged_in(page: Page) -> bool:
    """Check whether the current page reflects an authenticated X session.

    Three-tier strategy (matches plan §9):
    1. Fail-fast on auth-blocker URLs.
    2. Check for navigation elements (SideNav_AccountSwitcher_Button, AppTabBar_Profile_Link).
    3. URL-based fallback for authenticated-only pages with non-empty body.
    """
    try:
        current_url = page.url

        # Tier 1: auth blocker URL
        if _is_auth_blocker_url(current_url):
            return False

        # Tier 2: selector check (primary signal)
        has_nav = False
        for selector in _LOGGED_IN_SELECTORS:
            try:
                count = await page.locator(selector).count()
                if count > 0:
                    has_nav = True
                    break
            except Exception:
                pass

        # Tier 3: URL-based fallback (authenticated-only pages)
        is_authed_page = any(seg in current_url for seg in _AUTHED_URL_SEGMENTS)

        if not is_authed_page:
            return has_nav

        if has_nav:
            return True

        # On authenticated-only pages without nav elements, require non-empty body
        # to guard against false positives during bridge/recovery situations.
        try:
            body_text = await page.evaluate("() => document.body?.innerText || ''")
            if not isinstance(body_text, str):
                return False
            return bool(body_text.strip())
        except Exception:
            return False

    except PlaywrightTimeoutError:
        logger.warning("Timeout checking login status on %s — treating as not logged in", page.url)
        return False
    except Exception:
        logger.error("Unexpected error checking login status", exc_info=True)
        raise


# ---------------------------------------------------------------------------
# detect_auth_barrier
# ---------------------------------------------------------------------------


async def detect_auth_barrier(page: Page) -> str | None:
    """Detect X auth barriers on the current page (full check including body text)."""
    return await _detect_auth_barrier(page, include_body_text=True)


async def detect_auth_barrier_quick(page: Page) -> str | None:
    """Cheap auth-barrier check: URL and title only, no body-text fetch."""
    return await _detect_auth_barrier(page, include_body_text=False)


async def _detect_auth_barrier(page: Page, *, include_body_text: bool) -> str | None:
    try:
        current_url = page.url
        if _is_auth_blocker_url(current_url):
            return f"auth blocker URL: {current_url}"

        try:
            title = (await page.title()).strip().lower()
        except Exception:
            title = ""
        if any(pattern in title for pattern in _LOGIN_TITLE_PATTERNS):
            return f"login title: {title}"

        if not include_body_text:
            return None

        try:
            body_text = await page.evaluate("() => document.body?.innerText || ''")
        except Exception:
            body_text = ""
        if not isinstance(body_text, str):
            body_text = ""

        normalized = re.sub(r"\s+", " ", body_text).strip()
        for marker_group in _AUTH_BARRIER_TEXT_MARKERS:
            if all(marker in normalized for marker in marker_group):
                return f"auth barrier text: {' + '.join(marker_group)}"

        return None

    except PlaywrightTimeoutError:
        logger.warning(
            "Timeout checking auth barrier on %s — continuing without detection", page.url
        )
        return None
    except Exception:
        logger.error("Unexpected error checking auth barrier", exc_info=True)
        return None


# ---------------------------------------------------------------------------
# detect_rate_limit
# ---------------------------------------------------------------------------


async def detect_rate_limit(page: Page) -> None:
    """Detect if X has rate-limited or hard-blocked the current session.

    Checks (in order):
    1. URL is ``/account/access`` → hard block → RateLimitError immediately.
    2. Body contains a soft-block marker AND ``primaryColumn`` is absent
       → RateLimitError(suggested_wait_seconds=30).

    Raises:
        RateLimitError: If any rate-limiting or access challenge is detected.
    """
    current_url = page.url
    parsed_path = urlparse(current_url).path

    if parsed_path == "/account/access" or parsed_path.startswith("/account/access/"):
        raise RateLimitError(
            "X account access challenge detected at /account/access. "
            "You may need to verify your identity or wait before continuing.",
            suggested_wait_seconds=30,
        )

    try:
        has_primary_column = await page.locator(_PRIMARY_COLUMN_SELECTOR).count() > 0
        if has_primary_column:
            return  # Normal page with content; skip heuristic

        body_text = await page.locator("body").inner_text(timeout=2000)
        if body_text and any(marker in body_text for marker in _SOFT_BLOCK_BODY_MARKERS):
            raise RateLimitError(
                "X soft-block detected ('Something went wrong' / rate limit message). "
                "Wait before retrying.",
                suggested_wait_seconds=30,
            )
    except RateLimitError:
        raise
    except PlaywrightTimeoutError:
        pass
    except Exception:
        logger.debug("Non-critical error in detect_rate_limit", exc_info=True)


# ---------------------------------------------------------------------------
# wait_for_manual_login
# ---------------------------------------------------------------------------


async def wait_for_manual_login(page: Page, timeout: int = 300000) -> None:
    """Poll ``is_logged_in`` every 1 s until login is detected or timeout expires.

    Args:
        page:    Patchright page object.
        timeout: Timeout in milliseconds (default: 5 minutes).

    Raises:
        AuthenticationError: If timeout expires before login is detected.
    """
    logger.info(
        "Please complete the login process manually in the browser. Waiting up to 5 minutes..."
    )
    loop = asyncio.get_running_loop()
    start_time = loop.time()

    while True:
        if await is_logged_in(page):
            logger.info("Manual login completed successfully")
            return

        elapsed_ms = (loop.time() - start_time) * 1000
        if elapsed_ms > timeout:
            raise AuthenticationError(
                "Manual login timeout. Please try again and complete login within 5 minutes."
            )

        await asyncio.sleep(1)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _is_auth_blocker_url(url: str) -> bool:
    """Return True only for real X auth routes, not arbitrary slug substrings."""
    path = urlparse(url).path or "/"
    if path in _AUTH_BLOCKER_URL_PATHS:
        return True
    return any(
        path == f"{pattern}/" or path.startswith(f"{pattern}/")
        for pattern in _AUTH_BLOCKER_URL_PATHS
    )
