"""Browser lifecycle management using Patchright with persistent context.

Mirrors linkedin_mcp_server/core/browser.py but adapted for X (Twitter).

Key differences from LinkedIn:
- Cookie subset: auth_token, ct0, guest_id, twid, kdt (not li_at / JSESSIONID)
- Domain filter: twitter.com / x.com (not linkedin.com)
- No remember-me prompt handling (X doesn't have that flow)
- No cross-runtime cookie bridge for v1 (single-runtime CLI only)
"""

import json
import logging
import os
import stat
from pathlib import Path
from typing import Any

from patchright.async_api import BrowserContext, Page, Playwright, async_playwright

from xcli.common_utils import secure_mkdir, secure_write_text
from xcli.exceptions import NetworkError

logger = logging.getLogger(__name__)

_DEFAULT_USER_DATA_DIR = Path.home() / ".xcli" / "profile"
_PRIVATE_DIR_MODE = 0o700
_PRIVATE_FILE_MODE = 0o600

# Cookies we export/import for portability (auth_token is the bearer token — treat as secret)
_X_COOKIE_NAMES = frozenset({"auth_token", "ct0", "guest_id", "twid", "kdt"})
_X_DOMAINS = (".twitter.com", ".x.com", "twitter.com", "x.com")


def _harden_xcli_tree(path: Path) -> None:
    """Ensure directories from *path* up to ``.xcli`` are owner-only (0o700).

    Complements :func:`~xcli.common_utils.secure_mkdir` by hardening
    pre-existing directories that may have been created with a loose umask.
    No-op on Windows or when *path* is not inside a ``.xcli`` directory.
    """
    if os.name == "nt":
        return
    d = path if path.is_dir() else path.parent
    if not any(p.name == ".xcli" for p in (d, *d.parents)):
        return
    for p in (d, *d.parents):
        if p.is_dir() and stat.S_IMODE(p.stat().st_mode) != _PRIVATE_DIR_MODE:
            p.chmod(_PRIVATE_DIR_MODE)
        if p.name == ".xcli":
            return


class BrowserManager:
    """Async context manager for a Patchright persistent browser context.

    Session persistence is handled by the persistent browser context — all
    cookies, localStorage, and session state are retained in ``user_data_dir``
    between runs.

    Usage::

        async with BrowserManager(user_data_dir="~/.xcli/profile") as bm:
            await bm.page.goto("https://x.com/home")
    """

    def __init__(
        self,
        user_data_dir: str | Path = _DEFAULT_USER_DATA_DIR,
        headless: bool = True,
        slow_mo: int = 0,
        viewport: dict[str, int] | None = None,
        user_agent: str | None = None,
        **launch_options: Any,
    ):
        self.user_data_dir = str(Path(user_data_dir).expanduser())
        self.headless = headless
        self.slow_mo = slow_mo
        self.viewport = viewport or {"width": 1280, "height": 720}
        self.user_agent = user_agent
        self.launch_options = launch_options

        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._is_authenticated = False

    async def __aenter__(self) -> "BrowserManager":
        await self.start()
        return self

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        await self.close()

    async def start(self) -> None:
        """Start Patchright and launch a persistent browser context."""
        if self._context is not None:
            raise RuntimeError("Browser already started. Call close() first.")
        try:
            self._playwright = await async_playwright().start()

            secure_mkdir(Path(self.user_data_dir))
            _harden_xcli_tree(Path(self.user_data_dir))

            context_options: dict[str, Any] = {
                "headless": self.headless,
                "slow_mo": self.slow_mo,
                "viewport": self.viewport,
                **self.launch_options,
                "locale": "en-US",
            }

            if self.user_agent:
                context_options["user_agent"] = self.user_agent

            # IMPORTANT: launch_persistent_context, never chromium.launch()
            # Patchright handles anti-detection patches — do NOT pass any
            # --disable-blink-features or automation args.
            self._context = await self._playwright.chromium.launch_persistent_context(
                self.user_data_dir,
                **context_options,
            )

            logger.info(
                "Persistent browser launched (headless=%s, user_data_dir=%s)",
                self.headless,
                self.user_data_dir,
            )

            if self._context.pages:
                self._page = self._context.pages[0]
            else:
                self._page = await self._context.new_page()

            logger.info("Browser context and page ready")

        except Exception as e:
            await self.close()
            raise NetworkError(f"Failed to start browser: {e}") from e

    async def close(self) -> None:
        """Close the persistent context and clean up resources."""
        context = self._context
        playwright = self._playwright
        self._context = None
        self._page = None
        self._playwright = None

        if context is None and playwright is None:
            return

        if context is not None:
            try:
                await context.close()
            except Exception as exc:
                logger.error("Error closing browser context: %s", exc)

        if playwright is not None:
            try:
                await playwright.stop()
            except Exception as exc:
                logger.error("Error stopping playwright: %s", exc)

        logger.info("Browser closed")

    @property
    def page(self) -> Page:
        """The active Patchright page."""
        if not self._page:
            raise RuntimeError("Browser not started. Use async context manager or call start().")
        return self._page

    @property
    def context(self) -> BrowserContext:
        """The active Patchright browser context."""
        if not self._context:
            raise RuntimeError("Browser context not initialized.")
        return self._context

    @property
    def is_authenticated(self) -> bool:
        """Whether startup authentication succeeded for this browser instance."""
        return self._is_authenticated

    @is_authenticated.setter
    def is_authenticated(self, value: bool) -> None:
        self._is_authenticated = value

    def _default_cookie_path(self) -> Path:
        return Path(self.user_data_dir).parent / "cookies.json"

    async def set_cookie(self, name: str, value: str, domain: str = ".x.com") -> None:
        """Inject a single cookie into the browser context."""
        if not self._context:
            raise RuntimeError("No browser context")
        await self._context.add_cookies(
            [{"name": name, "value": value, "domain": domain, "path": "/"}]
        )
        logger.debug("Cookie set: %s", name)

    async def export_cookies(self, cookie_path: str | Path | None = None) -> bool:
        """Export the X auth cookie subset to a portable JSON file (0o600).

        Exported names: auth_token, ct0, guest_id, twid, kdt.
        """
        if not self._context:
            logger.warning("Cannot export cookies: no browser context")
            return False

        path = Path(cookie_path) if cookie_path else self._default_cookie_path()
        try:
            all_cookies = await self._context.cookies()
            cookies = [
                c
                for c in all_cookies
                if any(c.get("domain", "").endswith(d.lstrip(".")) for d in _X_DOMAINS)
                and c.get("name") in _X_COOKIE_NAMES
            ]
            secure_mkdir(path.parent)
            _harden_xcli_tree(path.parent)
            secure_write_text(path, json.dumps(cookies, indent=2), mode=_PRIVATE_FILE_MODE)
            logger.info("Exported %d X cookies to %s", len(cookies), path)
            return True
        except Exception:
            logger.exception("Failed to export cookies")
            return False

    async def import_cookies(self, cookie_path: str | Path | None = None) -> bool:
        """Import the portable X cookie subset from a JSON file.

        Returns True if ``auth_token`` was present and imported.
        """
        if not self._context:
            logger.warning("Cannot import cookies: no browser context")
            return False

        path = Path(cookie_path) if cookie_path else self._default_cookie_path()
        if not path.exists():
            logger.debug("No portable cookie file at %s", path)
            return False

        try:
            all_cookies = json.loads(path.read_text())
            if not all_cookies:
                logger.debug("Cookie file is empty")
                return False

            cookies = [c for c in all_cookies if c.get("name") in _X_COOKIE_NAMES]
            has_auth_token = any(c.get("name") == "auth_token" for c in cookies)
            if not has_auth_token:
                logger.warning("No auth_token cookie found in %s", path)
                return False

            await self._context.add_cookies(cookies)  # type: ignore[arg-type]
            logger.info(
                "Imported %d X cookies from %s (auth_token=%s): %s",
                len(cookies),
                path,
                has_auth_token,
                ", ".join(c["name"] for c in cookies),
            )
            return True
        except Exception:
            logger.exception("Failed to import cookies from %s", path)
            return False

    def cookie_file_exists(self, cookie_path: str | Path | None = None) -> bool:
        """Return True if the portable cookie file exists."""
        path = Path(cookie_path) if cookie_path else self._default_cookie_path()
        return path.exists()
