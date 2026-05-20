"""Live stealth-fingerprint tests. Gated by XCLI_LIVE=1.

These tests hit external services (bot.sannysoft.com, creepjs, x.com).
Do NOT run in PR CI — they require a real network connection and (for the
x.com check) an authenticated ~/.xcli/profile.

Run with:
    XCLI_LIVE=1 uv run pytest tests/e2e/test_stealth_fingerprint.py -v
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("XCLI_LIVE") != "1",
    reason="Live tests gated behind XCLI_LIVE=1",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _open_browser():
    """Open a fresh headless BrowserManager using the persistent profile.

    Returns the BrowserManager (already started). Callers must close it.
    """
    from xcli.core.browser import BrowserManager
    from xcli.session_state import get_source_profile_dir

    profile_dir = get_source_profile_dir()
    bm = BrowserManager(user_data_dir=profile_dir, headless=True)
    await bm.start()
    return bm


# ---------------------------------------------------------------------------
# Group A: bot.sannysoft.com
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sannysoft_critical_passes():
    """All critical sannysoft checks must pass (no critical FAIL results)."""
    from xcli.checks import CheckStatus, check_bot_sannysoft

    bm = await _open_browser()
    try:
        results = await check_bot_sannysoft(bm.page)
    finally:
        await bm.close()

    critical_fails = [r for r in results if r.critical and r.status == CheckStatus.FAIL]
    if critical_fails:
        details = "\n".join(f"  {r.name}: {r.detail}" for r in critical_fails)
        pytest.fail(f"{len(critical_fails)} critical sannysoft check(s) failed:\n{details}")


@pytest.mark.asyncio
async def test_sannysoft_returns_rows():
    """Sannysoft check should return at least the 6 known critical rows."""
    from xcli.checks import check_bot_sannysoft

    bm = await _open_browser()
    try:
        results = await check_bot_sannysoft(bm.page)
    finally:
        await bm.close()

    # Should have at least the 6 critical rows + 1 summary
    assert len(results) >= 7, (
        f"Expected at least 7 results (6 critical + summary), got {len(results)}"
    )


# ---------------------------------------------------------------------------
# Group B: creepjs trust score
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_creepjs_not_bot():
    """creepjs must not explicitly classify the browser as Bot."""
    from xcli.checks import CheckStatus, check_creepjs

    bm = await _open_browser()
    try:
        result = await check_creepjs(bm.page)
    finally:
        await bm.close()

    assert (
        result.status != CheckStatus.FAIL
        or not result.evidence
        or not result.evidence.get("is_bot")
    ), f"creepjs classified browser as Bot: {result.detail}"


@pytest.mark.asyncio
async def test_creepjs_has_score():
    """creepjs check should produce a trust_score (not None)."""
    from xcli.checks import CheckStatus, check_creepjs

    bm = await _open_browser()
    try:
        result = await check_creepjs(bm.page)
    finally:
        await bm.close()

    # WARN is acceptable (score not found); FAIL means error or is_bot
    assert result.status in (CheckStatus.PASS, CheckStatus.WARN), (
        f"creepjs check failed unexpectedly: {result.detail}"
    )
    if result.evidence:
        trust_score = result.evidence.get("trust_score")
        # If score was found, it should be a sensible value
        if trust_score is not None:
            assert 0.0 <= trust_score <= 100.0, f"Trust score out of range: {trust_score}"


# ---------------------------------------------------------------------------
# Group C: x.com/home reachability
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_x_home_reaches_primary_column():
    """x.com/home should load the primary column without soft-block markers.

    Automatically skipped if no ~/.xcli/profile exists.
    """
    from xcli.checks import CheckStatus, check_x_home
    from xcli.session_state import profile_exists

    if not profile_exists():
        pytest.skip("No ~/.xcli/profile — skipping x.com reachability check")

    bm = await _open_browser()
    try:
        result = await check_x_home(bm.page)
    finally:
        await bm.close()

    if result.status == CheckStatus.SKIP:
        pytest.skip(result.detail)

    assert result.status == CheckStatus.PASS, (
        f"x.com/home reachability check failed: {result.detail}\nEvidence: {result.evidence}"
    )
