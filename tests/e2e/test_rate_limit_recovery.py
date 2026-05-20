"""Live rate-limit detection test. Gated by XCLI_LIVE=1.

Tests that a "Something went wrong" injection causes RateLimitError to be raised.

Design decision: this test asserts the CURRENT behavior — RateLimitError is raised
when a soft-block page is served. Automatic single-retry is Future Work (Phase 5
candidate per plan §7 _RATE_LIMIT_RETRY_DELAY comment). The test documents this
decision explicitly.

Implementation: uses Patchright page.route() to intercept the first GET of
https://x.com/home and respond with a fixture HTML that contains the soft-block
markers ("Something went wrong", no [data-testid="primaryColumn"]). Subsequent
calls are forwarded normally.

Run with:
    XCLI_LIVE=1 uv run pytest tests/e2e/test_rate_limit_recovery.py -v
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("XCLI_LIVE") != "1",
    reason="Live tests gated behind XCLI_LIVE=1",
)

# Minimal HTML page that triggers soft-block detection:
# - body contains all SOFT_BLOCK_BODY_MARKERS
# - no [data-testid="primaryColumn"] present
_SOFT_BLOCK_HTML = """<!DOCTYPE html>
<html>
<head><title>Something went wrong</title></head>
<body>
  <p>Something went wrong. Try reloading.</p>
  <p>Rate limit exceeded</p>
</body>
</html>"""


@pytest.mark.asyncio
async def test_soft_block_raises_rate_limit_error() -> None:
    """Injecting a soft-block page into x.com/home should raise RateLimitError.

    Future work: once Phase 5 single-retry is implemented, update this test to
    assert that the retry succeeds instead of raising.

    NOTE: automatic retry is intentionally NOT implemented in Phase 4.
    The plan §13 soft-block mitigation is: detect → 5s back-off → single retry.
    Currently only detection and raise are implemented (Phase 1). Retry is a
    Phase 5 candidate.
    """
    from xcli.core.browser import BrowserManager
    from xcli.exceptions import RateLimitError
    from xcli.scraping.extractor import XExtractor
    from xcli.session_state import get_source_profile_dir, profile_exists

    if not profile_exists():
        pytest.skip("No ~/.xcli/profile — cannot run rate-limit recovery test without auth")

    profile_dir = get_source_profile_dir()
    bm = BrowserManager(user_data_dir=profile_dir, headless=True)
    await bm.start()

    injected = {"count": 0}

    async def intercept(route, request):
        # Inject only the first request to x.com/home
        if injected["count"] == 0 and "x.com/home" in request.url:
            injected["count"] += 1
            await route.fulfill(
                status=200,
                content_type="text/html",
                body=_SOFT_BLOCK_HTML,
            )
        else:
            await route.continue_()

    try:
        await bm.page.route("**/*", intercept)
        extractor = XExtractor(bm.page, jitter_pct=0.0)

        with pytest.raises(RateLimitError):
            await extractor.fetch_feed(count=1, comments_per=0)

    finally:
        await bm.page.unroute("**/*")
        await bm.close()
