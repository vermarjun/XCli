"""Shared pytest fixtures for xcli integration tests.

Two strategies for URL interception in integration tests:
1. page.route() — intercept requests to x.com and respond with local fixture HTML.
   This is the default strategy used by test_extractor_mocked.py because it is
   more realistic: the browser still navigates normally, retains request context,
   and exercises the full auth-check pipeline.
2. _test_only_base_url_override — simpler fallback that replaces the base URL
   in XExtractor.goto calls. Used only when route() is inconvenient (e.g. for
   testing _goto_with_auth_checks URL validation logic directly).

This conftest uses the route() strategy in `routed_extractor`.

Event-loop compatibility note:
    pytest-asyncio (asyncio_mode=auto) manages one event loop per function-scoped
    test. The fixture_server must therefore be function-scoped and started in the
    same loop as the test to avoid "Future attached to different loop" errors.
    A session-scoped server is not compatible with pytest-asyncio's per-test loops.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio


@pytest.fixture(autouse=True)
def disable_human_pace_for_integration(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disable humanized scroll timing during integration tests for hermetic timing.

    Set XCLI_HUMAN_PACE=0 so capture_as_you_scroll and human_read_pause use
    the original single-wheel-event / fixed-sleep behavior. This keeps tests
    deterministic and fast without changing the production code path.
    """
    monkeypatch.setenv("XCLI_HUMAN_PACE", "0")


FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Fixture server (aiohttp, function-scoped — shares the pytest-asyncio loop)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def fixture_server():
    """Start an aiohttp static file server serving the fixtures/ directory.

    Yields the base URL (http://127.0.0.1:<PORT>).

    Function-scoped: a fresh server per test to share the pytest-asyncio
    event loop and avoid "Future attached to different loop" errors.
    """
    import aiohttp.web as web

    app = web.Application()
    app.router.add_static("/", FIXTURES_DIR, show_index=True)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()

    # Extract the dynamically assigned port
    port = site._server.sockets[0].getsockname()[1]
    base_url = f"http://127.0.0.1:{port}"

    yield base_url

    await runner.cleanup()


# ---------------------------------------------------------------------------
# Browser fixture (function-scoped, headless)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def browser(tmp_path: Path):
    """Launch a headless BrowserManager with a temporary profile directory.

    Function-scoped: fresh browser for each test (isolation).
    """
    from xcli.core.browser import BrowserManager

    profile_dir = tmp_path / "xcli-test-profile"
    profile_dir.mkdir(mode=0o700)

    bm = BrowserManager(user_data_dir=profile_dir, headless=True)
    await bm.start()
    yield bm
    await bm.close()


# ---------------------------------------------------------------------------
# Extractor fixture (function-scoped)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def extractor(browser):
    """Yield an XExtractor wrapping the test browser's page."""
    from xcli.scraping.extractor import XExtractor

    yield XExtractor(browser.page)
