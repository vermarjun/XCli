"""Interactive login flow for xcli.

Mirrors linkedin_mcp_server/setup.py but adapted for X (Twitter):
- Navigates to https://x.com/login (not LinkedIn)
- No remember-me prompt resolution (X does not have that UI)
- Exports auth_token / ct0 / guest_id / twid / kdt cookies
- Writes source-state.json with a new login_generation UUID
"""

import asyncio
import logging
from pathlib import Path
from typing import Any

from xcli.config import get_config
from xcli.core import BrowserManager, wait_for_manual_login, warm_up_browser
from xcli.drivers.browser import get_profile_dir
from xcli.session_state import portable_cookie_path, write_source_state

logger = logging.getLogger(__name__)


async def interactive_login(user_data_dir: Path | None = None, warm_up: bool = True) -> bool:
    """Open a headful browser for manual X login with persistent profile.

    Args:
        user_data_dir: Path to browser profile. Defaults to config value.
        warm_up:       Visit normal sites first to appear more human-like.

    Returns:
        True on success.

    Raises:
        AuthenticationError: If the 5-minute login window expires.
    """
    if user_data_dir is None:
        user_data_dir = get_profile_dir()

    print("Opening browser for X login...")
    print("   Please log in manually. You have 5 minutes to complete authentication.")
    print("   (This handles 2FA, Arkose FunCaptcha, email verification, etc.)")

    config = get_config()
    launch_options: dict[str, Any] = {}
    if config.browser.chrome_path:
        launch_options["executable_path"] = config.browser.chrome_path

    viewport = {
        "width": config.browser.viewport_width,
        "height": config.browser.viewport_height,
    }

    async with BrowserManager(
        user_data_dir=user_data_dir,
        headless=False,  # Always headful for manual login
        slow_mo=config.browser.slow_mo,
        user_agent=config.browser.user_agent,
        viewport=viewport,
        **launch_options,
    ) as browser:
        if warm_up:
            print("   Warming up browser (visiting normal sites first)...")
            await warm_up_browser(browser.page)

        # Navigate to the X login page
        await browser.page.goto("https://x.com/login")

        # 5-minute window for 2FA / captcha / unusual-login challenges
        await wait_for_manual_login(browser.page, timeout=300_000)

        # Allow persistent context to flush cookies to disk
        await asyncio.sleep(2)

        # Verify auth_token was persisted
        cookies = await browser.context.cookies()
        has_auth_token = any(c["name"] == "auth_token" for c in cookies)
        if not has_auth_token:
            print("   Warning: auth_token cookie not found. Login may not have persisted.")
            print("   Waiting a bit longer for cookie propagation...")
            await asyncio.sleep(5)

        # Export portable cookie subset
        cookie_path = portable_cookie_path()
        if await browser.export_cookies(cookie_path):
            print("   Cookies exported.")
            source_state = write_source_state()
            print(f"   Source session generation: {source_state.login_generation}")
        else:
            print("   Warning: cookie export failed. Run `xcli login` again to retry.")
            return False

        print(f"Profile saved to {user_data_dir}")
        return True
