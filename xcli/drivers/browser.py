"""Patchright browser singleton for xcli.

Mirrors linkedin_mcp_server/drivers/browser.py but without the cross-runtime
cookie bridge (single-runtime CLI for v1; bridge documented as Phase 4).

The singleton is intentionally module-level so the async browser stays alive
across multiple tool calls in one process.  Tests reset it via
:func:`reset_browser_for_testing`.
"""

import logging
from pathlib import Path

from xcli.common_utils import secure_mkdir
from xcli.config import get_config
from xcli.core import (
    AuthenticationError,
    BrowserManager,
    detect_auth_barrier_quick,
    is_logged_in,
)
from xcli.session_state import (
    get_source_profile_dir,
    load_source_state,
    portable_cookie_path,
)
from xcli.session_state import (
    profile_exists as session_profile_exists,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_browser: BrowserManager | None = None
_headless: bool = True
_channel: str | None = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_profile_dir() -> Path:
    """Return the resolved profile directory from config."""
    return get_source_profile_dir()


def profile_exists(profile_dir: Path | None = None) -> bool:
    """Return True if the persistent browser profile exists and is non-empty."""
    return session_profile_exists(profile_dir or get_profile_dir())


def set_headless(headless: bool) -> None:
    """Set headless mode for future browser creation (affects next get_or_create_browser)."""
    global _headless
    _headless = headless


async def get_or_create_browser(
    headless: bool | None = None,
    channel: str | None = None,
) -> BrowserManager:
    """Return the existing singleton browser or create a new authenticated one.

    Args:
        headless: Override headless mode.  None → use current module-level flag.
        channel:  Browser channel override (e.g. ``"chrome"``).  None → pull
                  from config (``XCLI_CHANNEL`` env / default ``"chromium"``).
                  Passing ``"chrome"`` uses the user's installed Chrome, which
                  has real plugins, GPU WebGL, and a non-Headless UA — the
                  strongest stealth posture.

    Raises:
        AuthenticationError: If no valid source profile / cookies exist.
    """
    global _browser, _headless, _channel

    if headless is not None:
        _headless = headless

    if channel is not None:
        _channel = channel

    if _browser is not None:
        return _browser

    config = get_config()
    source_profile_dir = get_profile_dir()
    cookie_path = portable_cookie_path()
    source_state = load_source_state()

    if not source_state or not profile_exists(source_profile_dir) or not cookie_path.exists():
        raise AuthenticationError("No authentication found. Run `xcli login` to create a profile.")

    secure_mkdir(source_profile_dir)
    viewport = {"width": config.browser.viewport_width, "height": config.browser.viewport_height}
    launch_options: dict = {}
    if config.browser.chrome_path:
        launch_options["executable_path"] = config.browser.chrome_path

    # Resolve effective channel: CLI arg > module-level _channel > config default
    effective_channel = _channel if _channel is not None else config.browser.channel
    # Normalise: treat "chromium" as None so we omit the param (use bundled Patchright default)
    browser_channel: str | None = effective_channel if effective_channel != "chromium" else None

    browser = BrowserManager(
        user_data_dir=source_profile_dir,
        headless=_headless,
        slow_mo=config.browser.slow_mo,
        user_agent=config.browser.user_agent,
        viewport=viewport,
        channel=browser_channel,
        **launch_options,
    )
    try:
        await browser.start()
        browser.page.set_default_timeout(config.browser.default_timeout)

        # Validate session by navigating to /home
        await browser.page.goto("https://x.com/home", wait_until="domcontentloaded")
        barrier = await detect_auth_barrier_quick(browser.page)
        if barrier is not None:
            await browser.close()
            raise AuthenticationError(
                f"Session invalid ({barrier}). Run `xcli login` to re-authenticate."
            )

        browser.is_authenticated = True
        _browser = browser
        logger.info("Browser singleton created and authenticated")
        return _browser

    except AuthenticationError:
        await browser.close()
        raise
    except Exception as e:
        await browser.close()
        raise AuthenticationError(
            f"Failed to establish browser session: {e}. Run `xcli login`."
        ) from e


async def close_browser() -> None:
    """Close the singleton browser and clean up resources."""
    global _browser

    browser = _browser
    _browser = None

    if browser is None:
        return

    logger.info("Closing browser...")
    await browser.close()
    logger.info("Browser closed")


async def ensure_authenticated() -> None:
    """Confirm the shared browser completed startup authentication.

    Raises:
        AuthenticationError: If no authenticated browser session is available.
    """
    browser = await get_or_create_browser()
    if browser.is_authenticated:
        return
    if not await is_logged_in(browser.page):
        raise AuthenticationError("Session expired or invalid. Run `xcli login`.")


async def validate_session() -> bool:
    """Return True if the current browser session is authenticated."""
    try:
        browser = await get_or_create_browser()
        if browser.is_authenticated:
            return True
        return await is_logged_in(browser.page)
    except AuthenticationError:
        return False


def reset_browser_for_testing() -> None:
    """Reset global browser state for test isolation."""
    global _browser, _headless, _channel
    _browser = None
    _headless = True
    _channel = None
