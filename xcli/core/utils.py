"""Scraping utility helpers for xcli.

Phase 0 content:
    - dismiss_modals: close X's bottom-bar sign-up nag and overlay modals.

Phase 1 additions (not here yet):
    - capture_as_you_scroll: virtualized-timeline capture loop.
"""

import asyncio
import logging

from patchright.async_api import Page
from patchright.async_api import TimeoutError as PlaywrightTimeoutError

logger = logging.getLogger(__name__)

# Selectors for overlay / modal close buttons on X
# data-testid first (most stable), then aria-label (locale-independent attribute presence)
_MODAL_CLOSE_SELECTOR = (
    '[data-testid="app-bar-close"], [aria-label="Close"], [data-testid="sheetDialogCancel"]'
)


async def dismiss_modals(page: Page) -> bool:
    """Close any overlay modals or the bottom-bar sign-up nag on X.

    Returns True if at least one modal was dismissed.
    """
    try:
        close_btn = page.locator(_MODAL_CLOSE_SELECTOR).first
        if await close_btn.is_visible(timeout=1000):
            await close_btn.click()
            await asyncio.sleep(0.5)
            logger.debug("Dismissed modal/overlay")
            return True
    except PlaywrightTimeoutError:
        pass
    except Exception as e:
        logger.debug("Error dismissing modal: %s", e)
    return False
