"""Unit tests for xcli.core.utils — capture_as_you_scroll and dismiss_modals.

Uses mock Page objects to exercise all code paths without a real browser.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from xcli.core.human import HumanPaceConfig

# Use disabled human pace for all capture_as_you_scroll calls in this test module
# so assertions on exact wheel call counts remain deterministic.
_NO_HUMAN_PACE = HumanPaceConfig(enabled=False)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_page(viewport: dict | None = None) -> MagicMock:
    page = MagicMock()
    page.viewport_size = viewport or {"width": 1920, "height": 1080}
    page.mouse = MagicMock()
    page.mouse.move = AsyncMock()
    page.mouse.wheel = AsyncMock()
    return page


def _make_post(post_id: str) -> dict:
    return {"id": post_id, "text": f"post {post_id}"}


# ---------------------------------------------------------------------------
# capture_as_you_scroll
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_capture_as_you_scroll_collects_up_to_target() -> None:
    """Should stop collecting once target records are captured."""
    from xcli.core.utils import capture_as_you_scroll

    page = _make_mock_page()
    # Each call returns 2 new records; we want 3
    calls = 0

    async def extract_fn(p):
        nonlocal calls
        calls += 1
        base = (calls - 1) * 2
        return [_make_post(str(base + 1)), _make_post(str(base + 2))]

    results = await capture_as_you_scroll(
        page,
        extract_fn=extract_fn,
        target=3,
        max_scrolls=10,
        max_stale=3,
        pause_seconds=0,
        human_pace=_NO_HUMAN_PACE,
    )

    assert len(results) == 3


@pytest.mark.asyncio
async def test_capture_as_you_scroll_stops_on_stale() -> None:
    """Should stop after max_stale consecutive scrolls with no new records."""
    from xcli.core.utils import capture_as_you_scroll

    page = _make_mock_page()
    # Always returns the same record
    static_records = [_make_post("1"), _make_post("2")]

    async def extract_fn(p):
        return static_records

    results = await capture_as_you_scroll(
        page,
        extract_fn=extract_fn,
        target=100,
        max_scrolls=20,
        max_stale=3,
        pause_seconds=0,
        human_pace=_NO_HUMAN_PACE,
    )

    # First call produces 2, rest are all stale → stops after max_stale=3 stale scrolls
    assert len(results) == 2
    # mouse.wheel should have been called at most max_stale + 1 times (with disabled
    # human pace, each scroll iteration calls mouse.wheel exactly once)
    assert page.mouse.wheel.call_count <= 4


@pytest.mark.asyncio
async def test_capture_as_you_scroll_skips_first_id() -> None:
    """skip_first_id should exclude a specific record."""
    from xcli.core.utils import capture_as_you_scroll

    page = _make_mock_page()

    async def extract_fn(p):
        return [_make_post("op"), _make_post("reply1"), _make_post("reply2")]

    results = await capture_as_you_scroll(
        page,
        extract_fn=extract_fn,
        target=5,
        max_scrolls=3,
        max_stale=3,
        pause_seconds=0,
        skip_first_id="op",
        human_pace=_NO_HUMAN_PACE,
    )

    ids = [r["id"] for r in results]
    assert "op" not in ids
    assert "reply1" in ids
    assert "reply2" in ids


@pytest.mark.asyncio
async def test_capture_as_you_scroll_handles_extract_fn_error() -> None:
    """If extract_fn raises, the loop should continue (records=[])."""
    from xcli.core.utils import capture_as_you_scroll

    page = _make_mock_page()
    call_count = [0]

    async def extract_fn(p):
        call_count[0] += 1
        if call_count[0] == 1:
            raise RuntimeError("page error")
        return [_make_post("1")]

    results = await capture_as_you_scroll(
        page,
        extract_fn=extract_fn,
        target=1,
        max_scrolls=5,
        max_stale=3,
        pause_seconds=0,
        human_pace=_NO_HUMAN_PACE,
    )

    assert len(results) == 1


@pytest.mark.asyncio
async def test_capture_as_you_scroll_respects_max_scrolls() -> None:
    """Should never exceed max_scrolls iterations."""
    from xcli.core.utils import capture_as_you_scroll

    page = _make_mock_page()
    call_count = [0]

    async def extract_fn(p):
        call_count[0] += 1
        # Always returns a new unique record to prevent stale stops
        return [_make_post(str(call_count[0] * 100))]

    results = await capture_as_you_scroll(
        page,
        extract_fn=extract_fn,
        target=1000,  # very high target — will hit max_scrolls first
        max_scrolls=3,
        max_stale=100,
        pause_seconds=0,
        human_pace=_NO_HUMAN_PACE,
    )

    # call_count == max_scrolls (3 iterations)
    assert call_count[0] == 3
    # Results capped at target but we never reach 1000
    assert len(results) == 3


@pytest.mark.asyncio
async def test_capture_as_you_scroll_uses_viewport_size() -> None:
    """Should fall back to 1280x720 when viewport_size is None."""
    from xcli.core.utils import capture_as_you_scroll

    page = _make_mock_page(viewport=None)
    page.viewport_size = None  # Override to None

    async def extract_fn(p):
        return [_make_post("1")]

    results = await capture_as_you_scroll(
        page,
        extract_fn=extract_fn,
        target=1,
        max_scrolls=1,
        max_stale=3,
        pause_seconds=0,
        human_pace=_NO_HUMAN_PACE,
    )

    # Should succeed without error
    assert len(results) == 1
    # mouse.move should have been called with center of default 1920x1080 viewport
    page.mouse.move.assert_called_with(960, 540)


@pytest.mark.asyncio
async def test_capture_as_you_scroll_skips_records_without_id() -> None:
    """Records without an 'id' key should be silently skipped."""
    from xcli.core.utils import capture_as_you_scroll

    page = _make_mock_page()

    async def extract_fn(p):
        return [
            {"id": "", "text": "no id"},
            {"text": "also no id"},
            _make_post("valid_id"),
        ]

    results = await capture_as_you_scroll(
        page,
        extract_fn=extract_fn,
        target=5,
        max_scrolls=2,
        max_stale=3,
        pause_seconds=0,
        human_pace=_NO_HUMAN_PACE,
    )

    ids = [r["id"] for r in results]
    assert "valid_id" in ids
    assert "" not in ids


# ---------------------------------------------------------------------------
# dismiss_modals
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dismiss_modals_returns_true_when_modal_dismissed() -> None:
    """dismiss_modals should return True when a modal is clicked."""
    from xcli.core.utils import dismiss_modals

    page = MagicMock()
    close_locator = MagicMock()
    close_locator.is_visible = AsyncMock(return_value=True)
    close_locator.click = AsyncMock()

    first_locator = MagicMock()
    first_locator.first = close_locator

    page.locator = MagicMock(return_value=first_locator)

    result = await dismiss_modals(page)
    assert result is True
    close_locator.click.assert_called_once()


@pytest.mark.asyncio
async def test_dismiss_modals_returns_false_when_no_modal() -> None:
    """dismiss_modals should return False when no visible modal."""
    from xcli.core.utils import dismiss_modals

    page = MagicMock()
    close_locator = MagicMock()
    close_locator.is_visible = AsyncMock(return_value=False)

    first_locator = MagicMock()
    first_locator.first = close_locator

    page.locator = MagicMock(return_value=first_locator)

    result = await dismiss_modals(page)
    assert result is False


@pytest.mark.asyncio
async def test_dismiss_modals_handles_exception() -> None:
    """dismiss_modals should return False on exception."""
    from xcli.core.utils import dismiss_modals

    page = MagicMock()
    close_locator = MagicMock()
    close_locator.is_visible = AsyncMock(side_effect=RuntimeError("page closed"))

    first_locator = MagicMock()
    first_locator.first = close_locator

    page.locator = MagicMock(return_value=first_locator)

    # Should not raise
    result = await dismiss_modals(page)
    assert result is False
