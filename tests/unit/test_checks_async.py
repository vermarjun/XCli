"""Unit tests for xcli.checks async functions with mocked Patchright pages.

Tests check_bot_sannysoft, check_creepjs, check_x_home, and run_all_checks
using mock pages — no network access required.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_page(url: str = "https://x.com/home") -> MagicMock:
    page = MagicMock()
    page.url = url
    page.goto = AsyncMock()
    page.wait_for_function = AsyncMock()
    page.wait_for_selector = AsyncMock()
    page.evaluate = AsyncMock(return_value="")
    page.locator = MagicMock()
    page.locator.return_value.count = AsyncMock(return_value=0)
    page.locator.return_value.inner_text = AsyncMock(return_value="")
    page.inner_text = AsyncMock(return_value="")
    return page


# ---------------------------------------------------------------------------
# check_bot_sannysoft
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_bot_sannysoft_parses_rows() -> None:
    """check_bot_sannysoft should call parse_sannysoft_rows with the page-evaluate result."""
    from xcli.checks import CheckStatus, check_bot_sannysoft

    mock_page = _make_mock_page()
    mock_rows = [
        {"label": "WebDriver (New)", "result": "passed"},
        {"label": "Chrome (New)", "result": "present"},
    ]
    mock_page.evaluate = AsyncMock(return_value=mock_rows)

    results = await check_bot_sannysoft(mock_page)

    # Should produce 2 row results + 1 summary
    assert len(results) == 3
    summary = results[-1]
    assert summary.name == "sannysoft_summary"
    assert summary.status == CheckStatus.PASS


@pytest.mark.asyncio
async def test_check_bot_sannysoft_network_error_returns_fail() -> None:
    """On network error, check_bot_sannysoft should return a single FAIL result."""
    from xcli.checks import CheckStatus, check_bot_sannysoft

    mock_page = _make_mock_page()
    mock_page.goto = AsyncMock(side_effect=Exception("network timeout"))

    results = await check_bot_sannysoft(mock_page)

    assert len(results) == 1
    assert results[0].status == CheckStatus.FAIL
    assert "sannysoft" in results[0].name.lower()


@pytest.mark.asyncio
async def test_check_bot_sannysoft_timeout_returns_fail() -> None:
    """On wait_for_function timeout, should return FAIL."""
    from xcli.checks import CheckStatus, check_bot_sannysoft

    mock_page = _make_mock_page()
    mock_page.wait_for_function = AsyncMock(side_effect=Exception("Timeout"))

    results = await check_bot_sannysoft(mock_page)
    assert any(r.status == CheckStatus.FAIL for r in results)


# ---------------------------------------------------------------------------
# check_creepjs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_creepjs_extracts_score_from_selector() -> None:
    """check_creepjs should find trust score via one of its selectors."""
    from xcli.checks import check_creepjs

    mock_page = _make_mock_page()

    async def _selector_inner_text(*args, **kwargs):
        return "67.3%"

    mock_locator = MagicMock()
    mock_locator.count = AsyncMock(return_value=1)
    mock_locator.inner_text = AsyncMock(return_value="67.3%")
    mock_page.locator = MagicMock(return_value=mock_locator)

    result = await check_creepjs(mock_page)

    # Should at least not raise and return a CheckResult
    from xcli.checks import CheckResult

    assert isinstance(result, CheckResult)


@pytest.mark.asyncio
async def test_check_creepjs_network_error_returns_fail() -> None:
    """On network error, check_creepjs should return WARN or FAIL."""
    from xcli.checks import CheckStatus, check_creepjs

    mock_page = _make_mock_page()
    mock_page.goto = AsyncMock(side_effect=Exception("timeout"))

    result = await check_creepjs(mock_page)

    assert result.status in (CheckStatus.FAIL, CheckStatus.WARN)


# ---------------------------------------------------------------------------
# check_x_home
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_x_home_pass_when_primary_column_present() -> None:
    """check_x_home should PASS when primaryColumn is found on x.com/home."""
    from xcli.checks import CheckStatus, check_x_home

    mock_page = _make_mock_page("https://x.com/home")
    mock_page.goto = AsyncMock()
    # wait_for_selector succeeds (no exception = primary column found)
    mock_page.wait_for_selector = AsyncMock()
    # body.inner_text returns no soft-block markers
    mock_page.inner_text = AsyncMock(return_value="Your home feed content here")

    with patch("xcli.session_state.profile_exists", return_value=True):
        result = await check_x_home(mock_page)

    assert result.status == CheckStatus.PASS


@pytest.mark.asyncio
async def test_check_x_home_fail_when_soft_block() -> None:
    """check_x_home should FAIL when soft-block markers are present in body."""
    from xcli.checks import CheckStatus, check_x_home

    mock_page = _make_mock_page("https://x.com/home")
    mock_page.goto = AsyncMock()
    mock_page.wait_for_selector = AsyncMock()
    # Body has soft-block text
    mock_page.inner_text = AsyncMock(
        return_value="Something went wrong Try reloading Rate limit exceeded"
    )

    with patch("xcli.session_state.profile_exists", return_value=True):
        result = await check_x_home(mock_page)

    assert result.status == CheckStatus.FAIL


@pytest.mark.asyncio
async def test_check_x_home_skip_when_no_profile() -> None:
    """check_x_home should SKIP when no profile exists."""
    from xcli.checks import CheckStatus, check_x_home

    mock_page = _make_mock_page()

    with patch("xcli.session_state.profile_exists", return_value=False):
        result = await check_x_home(mock_page)

    assert result.status == CheckStatus.SKIP


@pytest.mark.asyncio
async def test_check_x_home_network_error_returns_fail() -> None:
    """On navigation error, check_x_home should return FAIL."""
    from xcli.checks import CheckStatus, check_x_home

    mock_page = _make_mock_page()
    mock_page.goto = AsyncMock(side_effect=Exception("network error"))

    with patch("xcli.session_state.profile_exists", return_value=True):
        result = await check_x_home(mock_page)

    assert result.status == CheckStatus.FAIL


# ---------------------------------------------------------------------------
# run_all_checks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_all_checks_skips_x_home_when_include_false() -> None:
    """run_all_checks with include_x_home=False should not call check_x_home."""
    from xcli.checks import CheckResult, CheckStatus

    mock_results = [
        CheckResult(
            name="WebDriver (New)",
            category="fingerprint",
            status=CheckStatus.PASS,
            detail="passed",
        )
    ]
    mock_creepjs = CheckResult(
        name="creepjs_trust",
        category="trust",
        status=CheckStatus.PASS,
        detail="Trust score: 80.0%",
    )
    x_home_called: list[bool] = [False]

    async def _fake_x_home(page):
        x_home_called[0] = True
        return CheckResult(
            name="x_home_reachability",
            category="reachability",
            status=CheckStatus.PASS,
            detail="ok",
        )

    mock_page = _make_mock_page()
    mock_bm = MagicMock()
    mock_bm.page = mock_page
    mock_bm.__aenter__ = AsyncMock(return_value=mock_bm)
    mock_bm.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("xcli.checks.check_bot_sannysoft", AsyncMock(return_value=mock_results)),
        patch("xcli.checks.check_creepjs", AsyncMock(return_value=mock_creepjs)),
        patch("xcli.checks.check_x_home", _fake_x_home),
    ):
        # Patch the local imports inside run_all_checks
        import xcli.core.browser as _core_browser
        import xcli.session_state as _sess

        orig_bm = _core_browser.BrowserManager
        orig_gpd = _sess.get_source_profile_dir
        _core_browser.BrowserManager = MagicMock(return_value=mock_bm)
        _sess.get_source_profile_dir = MagicMock(return_value="/tmp/fake")
        try:
            from xcli.checks import run_all_checks

            results = await run_all_checks(include_x_home=False)
        finally:
            _core_browser.BrowserManager = orig_bm
            _sess.get_source_profile_dir = orig_gpd

    assert not x_home_called[0], "check_x_home should not be called when include_x_home=False"
    names = [r.name for r in results]
    assert "x_home_reachability" not in names
    assert "creepjs_trust" in names


@pytest.mark.asyncio
async def test_run_all_checks_includes_x_home_by_default() -> None:
    """run_all_checks with include_x_home=True should call check_x_home."""
    from xcli.checks import CheckResult, CheckStatus

    mock_sannysoft = [
        CheckResult(
            name="sannysoft_summary", category="fingerprint", status=CheckStatus.PASS, detail="ok"
        )
    ]
    mock_creepjs = CheckResult(
        name="creepjs_trust", category="trust", status=CheckStatus.PASS, detail="80%"
    )
    mock_x_home = CheckResult(
        name="x_home_reachability", category="reachability", status=CheckStatus.PASS, detail="ok"
    )

    mock_page = _make_mock_page()
    mock_bm = MagicMock()
    mock_bm.page = mock_page
    mock_bm.__aenter__ = AsyncMock(return_value=mock_bm)
    mock_bm.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("xcli.checks.check_bot_sannysoft", AsyncMock(return_value=mock_sannysoft)),
        patch("xcli.checks.check_creepjs", AsyncMock(return_value=mock_creepjs)),
        patch("xcli.checks.check_x_home", AsyncMock(return_value=mock_x_home)),
    ):
        import xcli.core.browser as _core_browser
        import xcli.session_state as _sess

        orig_bm = _core_browser.BrowserManager
        orig_gpd = _sess.get_source_profile_dir
        _core_browser.BrowserManager = MagicMock(return_value=mock_bm)
        _sess.get_source_profile_dir = MagicMock(return_value="/tmp/fake")
        try:
            from xcli.checks import run_all_checks

            results = await run_all_checks(include_x_home=True)
        finally:
            _core_browser.BrowserManager = orig_bm
            _sess.get_source_profile_dir = orig_gpd

    names = [r.name for r in results]
    assert "x_home_reachability" in names
