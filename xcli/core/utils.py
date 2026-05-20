"""Scraping utility helpers for xcli.

Phase 0 content:
    - dismiss_modals: close X's bottom-bar sign-up nag and overlay modals.

Phase 1 additions:
    - capture_as_you_scroll: virtualized-timeline capture loop.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from patchright.async_api import Page
from patchright.async_api import TimeoutError as PlaywrightTimeoutError

from xcli.core.human import HumanPaceConfig, human_read_pause, human_scroll_burst
from xcli.scraping.selectors import MODAL_CLOSE_BTNS

logger = logging.getLogger(__name__)


async def dismiss_modals(page: Page) -> bool:
    """Close any overlay modals or the bottom-bar sign-up nag on X.

    Returns True if at least one modal was dismissed.
    """
    try:
        close_btn = page.locator(MODAL_CLOSE_BTNS).first
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


async def capture_as_you_scroll(
    page: Page,
    *,
    extract_fn: Callable[[Page], Awaitable[list[dict]]],
    target: int,
    max_scrolls: int = 15,
    max_stale: int = 3,
    wheel_delta: int = 1500,
    pause_seconds: float = 1.0,
    skip_first_id: str | None = None,
    human_pace: HumanPaceConfig | None = None,
) -> list[dict]:
    """Capture target records from a virtualized timeline by scrolling.

    Strategy: mouse.move to viewport center, then alternate mouse.wheel(delta)
    with extract_fn() calls. Dedupe by record["id"]. Stop when:
    - ``target`` unique records captured, OR
    - ``max_stale`` consecutive scrolls produce no new records, OR
    - ``max_scrolls`` total scrolls reached.

    Returns the first ``target`` records in insertion order.

    Why mouse.wheel and not window.scrollTo:
        X's timeline lives in a virtual-scroll container; scrollTo is
        unreliable, and real wheel events also feed behavioral telemetry
        favorably (stealth posture).

    Args:
        page:           Active Patchright page.
        extract_fn:     Async callable that reads the currently visible tweet
                        records from ``page``. Must return a list of dicts,
                        each with at least an ``"id"`` key (str).
        target:         Number of unique records to collect.
        max_scrolls:    Hard cap on scroll iterations (safety valve).
        max_stale:      Stop after this many consecutive scroll iterations
                        that produce no new records.
        wheel_delta:    Pixels to scroll per mouse.wheel call (positive = down).
        pause_seconds:  Seconds to wait after each wheel event for DOM to update.
        skip_first_id:  If set, skip the record with this id (used in thread
                        mode to skip the OP tweet so only replies are returned).
        human_pace:     HumanPaceConfig controlling scroll chunking and read
                        pauses. Pass ``HumanPaceConfig(enabled=False)`` in
                        tests for the original single-wheel-event behavior.
                        Default ``None`` uses ``default_human_pace()`` which
                        reads the ``XCLI_HUMAN_PACE`` environment variable.
    """
    seen: dict[str, dict] = {}  # id → record (insertion-ordered)
    stale = 0

    # Resolve human pace config: use provided config, or read from env via factory.
    from xcli.core.human import default_human_pace  # local import to avoid circular

    pace_cfg = human_pace if human_pace is not None else default_human_pace()

    vw = page.viewport_size or {"width": 1920, "height": 1080}
    cx, cy = vw["width"] // 2, vw["height"] // 2
    await page.mouse.move(cx, cy)

    for i in range(max_scrolls):
        # Extract all currently visible records
        try:
            records = await extract_fn(page)
        except Exception as e:
            logger.debug("extract_fn error on scroll %d: %s", i, e)
            records = []

        added = 0
        for rec in records:
            rec_id: str = rec.get("id") or ""
            if not rec_id:
                continue
            if skip_first_id and rec_id == skip_first_id:
                continue
            if rec_id not in seen:
                seen[rec_id] = rec
                added += 1

        logger.debug(
            "Scroll %d: +%d new records (%d total, target=%d)",
            i,
            added,
            len(seen),
            target,
        )

        if len(seen) >= target:
            break

        if added == 0:
            stale += 1
            logger.debug("Stale scroll %d/%d", stale, max_stale)
            if stale >= max_stale:
                logger.debug("Stopping: %d consecutive stale scrolls", stale)
                break
        else:
            stale = 0

        await human_scroll_burst(page, total_distance=wheel_delta, config=pace_cfg)
        await human_read_pause(seconds=pause_seconds, intent="browse", config=pace_cfg)

    return list(seen.values())[:target]
