"""Stealth verification checks — the core of Phase 3.

This module contains:
  - Pure parser functions (testable without network):
      parse_sannysoft_rows(rows)  → list[CheckResult]
      parse_creepjs_payload(payload)  → CheckResult

  - Async network functions (live, open browser first):
      check_bot_sannysoft(page)  → list[CheckResult]
      check_creepjs(page)        → CheckResult
      check_x_home(page)         → CheckResult

  - Orchestrator:
      run_all_checks(*, include_x_home, timeout_ms) → list[CheckResult]

NOTE on selector placement:
  Per plan §6, X.com selectors belong exclusively in scraping/selectors.py.
  Selectors for *external* third-party sites (bot.sannysoft.com, creepjs) are
  OK to define here — they are not part of the X stable-surface contract.
  Only PRIMARY_COLUMN and SOFT_BLOCK_BODY_MARKERS (X selectors) are imported
  from selectors.py.
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict as _asdict  # noqa: F401  (re-exported for cli.py)
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# External-site selectors (bot.sannysoft.com + creepjs — NOT X selectors)
# ---------------------------------------------------------------------------

# bot.sannysoft.com table is rendered once domcontentloaded + JS populates it.
# We wait until the table has > 10 rows.
_SANNYSOFT_URL = "https://bot.sannysoft.com/"
_SANNYSOFT_TABLE_READY_JS = "document.querySelectorAll('table tr').length > 10"

# creepjs is a SPA; trust score renders after a few seconds.
# Selectors tried in order:
_CREEPJS_URL = "https://abrahamjuliot.github.io/creepjs/"
_CREEPJS_SELECTORS_ORDERED = [
    "#fingerprint-data .trust-score-text",
    '[data-testid="trust-score"]',
    "#fingerprint-data .header .score",
]
# Fallback regex if no selector matches:
_CREEPJS_SCORE_REGEX = re.compile(r"Trust\s+Score[^0-9]*(\d+(?:\.\d+)?)\s*%", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------


class CheckStatus(str, Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    SKIP = "skip"


@dataclass
class CheckResult:
    name: str
    category: str  # "fingerprint" | "trust" | "reachability"
    status: CheckStatus
    detail: str
    critical: bool = False  # if True and status == FAIL → overall exit non-zero
    evidence: dict[str, Any] | None = field(default=None)


# ---------------------------------------------------------------------------
# Known critical/advisory rows on bot.sannysoft.com
# ---------------------------------------------------------------------------

# Critical rows: failure here → overall exit 1
_CRITICAL_ROW_LABELS: frozenset[str] = frozenset(
    {
        "WebDriver (New)",
        "Chrome (New)",
        "Permissions (New)",
        "Plugins Length (Old)",
        "Languages (Old)",
        "WebGL Vendor & Renderer (New)",
    }
)

# Values that betray a headless/virtual renderer (WebGL check)
_HEADLESS_WEBGL_STRINGS: tuple[str, ...] = (
    "Brian Paul",
    "Mesa OffScreen",
    "Mesa/X.org",
    "SwiftShader",
    "llvmpipe",
)

# "Passing" result strings from the table cells
_PASS_RESULT_STRINGS: frozenset[str] = frozenset({"passed", "present"})
# "Failing" result strings
_FAIL_RESULT_STRINGS: frozenset[str] = frozenset({"failed", "missing", "detected"})


# ---------------------------------------------------------------------------
# Pure parser functions (no network — tested by tests/unit/test_checks.py)
# ---------------------------------------------------------------------------


def _classify_sannysoft_row(label: str, result: str) -> CheckResult:
    """Classify a single bot.sannysoft.com table row into a CheckResult.

    Special case: the WebGL row value is the *renderer string*, not
    passed/failed — we check it against known headless renderer substrings.
    """
    is_critical = label in _CRITICAL_ROW_LABELS
    result_lower = result.strip().lower()
    raw_result = result.strip()

    if label == "WebGL Vendor & Renderer (New)":
        # Check for headless tell-tale substrings in the renderer string.
        is_headless_tell = any(s.lower() in raw_result.lower() for s in _HEADLESS_WEBGL_STRINGS)
        if is_headless_tell:
            return CheckResult(
                name=label,
                category="fingerprint",
                status=CheckStatus.FAIL,
                detail=f"Headless WebGL renderer detected: {raw_result!r}",
                critical=is_critical,
                evidence={"webgl_value": raw_result},
            )
        elif raw_result in ("", "N/A", "n/a"):
            return CheckResult(
                name=label,
                category="fingerprint",
                status=CheckStatus.WARN,
                detail=f"WebGL value empty or N/A: {raw_result!r}",
                critical=False,
                evidence={"webgl_value": raw_result},
            )
        else:
            return CheckResult(
                name=label,
                category="fingerprint",
                status=CheckStatus.PASS,
                detail=f"WebGL renderer OK: {raw_result!r}",
                critical=is_critical,
                evidence={"webgl_value": raw_result},
            )

    # Normal pass/fail logic
    if result_lower in _PASS_RESULT_STRINGS:
        return CheckResult(
            name=label,
            category="fingerprint",
            status=CheckStatus.PASS,
            detail=f"{result_lower}",
            critical=is_critical,
            evidence={"raw_result": raw_result},
        )
    elif result_lower in _FAIL_RESULT_STRINGS:
        return CheckResult(
            name=label,
            category="fingerprint",
            status=CheckStatus.FAIL,
            detail=f"Result: {result_lower!r}",
            critical=is_critical,
            evidence={"raw_result": raw_result},
        )
    else:
        # Unknown result — treat as warning (advisory rows), or fail if critical
        status = CheckStatus.FAIL if is_critical else CheckStatus.WARN
        return CheckResult(
            name=label,
            category="fingerprint",
            status=status,
            detail=f"Unexpected result: {result_lower!r}",
            critical=is_critical,
            evidence={"raw_result": raw_result},
        )


def parse_sannysoft_rows(rows: list[dict[str, str]]) -> list[CheckResult]:
    """Turn raw bot.sannysoft.com row dicts into CheckResults.

    Args:
        rows: List of {"label": "...", "result": "..."} dicts from the table.

    Returns:
        One CheckResult per row.  An extra summary CheckResult is appended at
        the end (category="fingerprint", name="sannysoft_summary").
    """
    results: list[CheckResult] = []
    for row in rows:
        label = row.get("label", "").strip()
        result = row.get("result", "").strip()
        if not label:
            continue
        results.append(_classify_sannysoft_row(label, result))

    # Summary entry
    critical_fails = [r for r in results if r.critical and r.status == CheckStatus.FAIL]
    advisory_fails = [r for r in results if not r.critical and r.status == CheckStatus.FAIL]
    if critical_fails:
        summary_status = CheckStatus.FAIL
        summary_detail = (
            f"{len(critical_fails)} critical check(s) failed: "
            f"{', '.join(r.name for r in critical_fails)}"
        )
    elif advisory_fails:
        summary_status = CheckStatus.WARN
        summary_detail = (
            f"All critical checks passed; {len(advisory_fails)} advisory check(s) flagged."
        )
    else:
        summary_status = CheckStatus.PASS
        summary_detail = f"All {len(results)} sannysoft checks passed."

    results.append(
        CheckResult(
            name="sannysoft_summary",
            category="fingerprint",
            status=summary_status,
            detail=summary_detail,
            critical=bool(critical_fails),
            evidence={"total": len(results) - 1, "critical_fails": len(critical_fails)},
        )
    )
    return results


def parse_creepjs_payload(payload: dict[str, Any]) -> CheckResult:
    """Parse a synthetic creepjs payload dict into a CheckResult.

    The payload schema used here (from the live scraper and unit tests):
        {
            "trust_score": float | None,
            "lies": int,
            "is_bot": bool,
            "raw_text": str | None,   # optional; body text for trend logging
        }

    The test is **advisory** — trust scores fluctuate per browser version and
    creepjs algorithm changes.  We only fail hard if the page explicitly marks
    us as "Bot" OR the trust score is 0.
    """
    trust_score = payload.get("trust_score")
    is_bot = bool(payload.get("is_bot", False))
    lies = payload.get("lies", 0)

    if is_bot or trust_score == 0:
        return CheckResult(
            name="creepjs_trust",
            category="trust",
            status=CheckStatus.FAIL,
            detail=(f"creepjs classified browser as Bot (trust_score={trust_score}, lies={lies})"),
            critical=False,  # advisory; doesn't gate CI
            evidence=payload,
        )
    elif trust_score is None:
        return CheckResult(
            name="creepjs_trust",
            category="trust",
            status=CheckStatus.WARN,
            detail="Could not read trust score from creepjs page.",
            critical=False,
            evidence=payload,
        )
    else:
        return CheckResult(
            name="creepjs_trust",
            category="trust",
            status=CheckStatus.PASS,
            detail=f"Trust score: {trust_score}%  lies: {lies}",
            critical=False,
            evidence=payload,
        )


# ---------------------------------------------------------------------------
# Async network functions (live — require a running Patchright Page)
# ---------------------------------------------------------------------------


async def check_bot_sannysoft(page: Any) -> list[CheckResult]:
    """Visit bot.sannysoft.com and parse the fingerprint table.

    Args:
        page: A Patchright ``Page`` object with an already-started browser context.

    Returns:
        list[CheckResult] — one per table row, plus a summary entry.

    On timeout / network error: returns a single FAIL CheckResult.
    """
    try:
        await page.goto(_SANNYSOFT_URL, wait_until="domcontentloaded", timeout=30_000)
        # Wait until the table has populated (JS renders the results)
        await page.wait_for_function(_SANNYSOFT_TABLE_READY_JS, timeout=20_000)

        rows: list[dict[str, str]] = await page.evaluate(
            """
            () => {
                return Array.from(document.querySelectorAll('tr')).map(tr => {
                    const tds = tr.querySelectorAll('td');
                    if (tds.length < 2) return null;
                    return {
                        label: tds[0].innerText.trim(),
                        result: tds[1].innerText.trim()
                    };
                }).filter(Boolean);
            }
            """
        )
        logger.info("bot.sannysoft.com: extracted %d rows", len(rows))
        return parse_sannysoft_rows(rows)

    except Exception as exc:
        logger.error("check_bot_sannysoft failed: %s", exc)
        return [
            CheckResult(
                name="sannysoft_summary",
                category="fingerprint",
                status=CheckStatus.FAIL,
                detail=f"Failed to load bot.sannysoft.com: {exc}",
                critical=True,
                evidence={"error": str(exc)},
            )
        ]


async def check_creepjs(page: Any) -> CheckResult:
    """Visit creepjs and extract the trust score.

    Args:
        page: A Patchright ``Page`` object.

    Returns:
        A single CheckResult.  Advisory (critical=False) because trust scores
        fluctuate per browser version and algorithm changes.
    """
    try:
        await page.goto(_CREEPJS_URL, wait_until="domcontentloaded", timeout=30_000)

        # Try each known selector in order; fall back to body regex.
        score_text: str | None = None
        for sel in _CREEPJS_SELECTORS_ORDERED:
            try:
                elem = page.locator(sel).first
                count = await elem.count()
                if count > 0:
                    await elem.wait_for(state="visible", timeout=15_000)
                    score_text = await elem.inner_text()
                    logger.info("creepjs: found score via selector %r: %r", sel, score_text)
                    break
            except Exception:
                continue

        # Body text regex fallback
        if not score_text:
            body_text: str = await page.inner_text("body")
            m = _CREEPJS_SCORE_REGEX.search(body_text)
            if m:
                score_text = m.group(0)
                logger.info("creepjs: score via body regex: %r", score_text)

        # Parse trust score from whatever text we found
        trust_score: float | None = None
        if score_text:
            # Extract the first numeric value (possibly with decimal)
            m2 = re.search(r"(\d+(?:\.\d+)?)", score_text)
            if m2:
                trust_score = float(m2.group(1))

        # Check for "Bot" classification in the page
        body_text_full: str = await page.inner_text("body")
        # Narrow: only treat as bot if "Bot" appears near detection language
        is_bot_classified = bool(
            re.search(
                r"(detected as|classified as|you are)[^.]*\bbot\b", body_text_full, re.IGNORECASE
            )
        )

        # Scrape lies count (advisory context)
        lies = 0
        lies_m = re.search(r"(\d+)\s+lies?\b", body_text_full[:3000], re.IGNORECASE)
        if lies_m:
            lies = int(lies_m.group(1))

        payload: dict[str, Any] = {
            "trust_score": trust_score,
            "lies": lies,
            "is_bot": is_bot_classified,
        }
        return parse_creepjs_payload(payload)

    except Exception as exc:
        logger.error("check_creepjs failed: %s", exc)
        return CheckResult(
            name="creepjs_trust",
            category="trust",
            status=CheckStatus.FAIL,
            detail=f"Failed to load creepjs: {exc}",
            critical=False,
            evidence={"error": str(exc)},
        )


async def check_x_home(page: Any) -> CheckResult:
    """Visit x.com/home with the authenticated profile and verify feed loads.

    Requires an existing ``~/.xcli/profile`` persistent browser profile.
    If no profile exists, returns status=SKIP (not FAIL).

    Args:
        page: A Patchright ``Page`` object backed by the persistent profile.

    Returns:
        A single CheckResult.  Critical=True because this is the real test.
    """
    from xcli.scraping.selectors import PRIMARY_COLUMN, SOFT_BLOCK_BODY_MARKERS
    from xcli.session_state import profile_exists

    if not profile_exists():
        return CheckResult(
            name="x_home_reachability",
            category="reachability",
            status=CheckStatus.SKIP,
            detail="No ~/.xcli/profile found — skipping x.com/home check. Run `xcli login`.",
            critical=False,
        )

    try:
        await page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=30_000)

        # Wait up to 10s for the primary column to appear
        try:
            await page.wait_for_selector(PRIMARY_COLUMN, timeout=10_000)
        except Exception:
            body_text = await page.inner_text("body")
            return CheckResult(
                name="x_home_reachability",
                category="reachability",
                status=CheckStatus.FAIL,
                detail=f"primaryColumn did not appear within 10s. URL: {page.url}",
                critical=True,
                evidence={"url": page.url, "body_snippet": body_text[:300]},
            )

        # Check for soft-block markers
        body_text = await page.inner_text("body")
        hit_markers = [m for m in SOFT_BLOCK_BODY_MARKERS if m in body_text]
        if hit_markers:
            return CheckResult(
                name="x_home_reachability",
                category="reachability",
                status=CheckStatus.FAIL,
                detail=f"Soft-block markers found in body: {hit_markers}",
                critical=True,
                evidence={"markers": hit_markers, "url": page.url},
            )

        return CheckResult(
            name="x_home_reachability",
            category="reachability",
            status=CheckStatus.PASS,
            detail=f"primaryColumn loaded, no soft-block markers. URL: {page.url}",
            critical=True,
            evidence={"url": page.url},
        )

    except Exception as exc:
        logger.error("check_x_home failed: %s", exc)
        return CheckResult(
            name="x_home_reachability",
            category="reachability",
            status=CheckStatus.FAIL,
            detail=f"Failed to load x.com/home: {exc}",
            critical=True,
            evidence={"error": str(exc)},
        )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


async def run_all_checks(
    *,
    include_x_home: bool = True,
    timeout_ms: int = 30_000,
    channel: str | None = None,
) -> list[CheckResult]:
    """Run all stealth checks in sequence (NEVER concurrently).

    Opens a fresh BrowserManager headless (using the persistent profile so
    that browser fingerprint matches production), runs checks one by one, then
    closes the browser.

    Args:
        include_x_home: If False, skip the x.com/home reachability check.
        timeout_ms: Per-page timeout in milliseconds (currently used as a
                    reference; individual checks pass it to goto).
        channel:    Browser channel to use (e.g. ``"chrome"``).  None → use
                    config default (``XCLI_CHANNEL`` env or ``"chromium"``).

    Returns:
        Flat list of CheckResult objects (all groups concatenated).
    """
    from xcli.config import get_config
    from xcli.core.browser import BrowserManager
    from xcli.session_state import get_source_profile_dir

    all_results: list[CheckResult] = []
    profile_dir = get_source_profile_dir()

    # Resolve effective channel
    effective_channel = channel
    if effective_channel is None:
        effective_channel = get_config().browser.channel
    browser_channel: str | None = effective_channel if effective_channel != "chromium" else None

    async with BrowserManager(
        user_data_dir=profile_dir, headless=True, channel=browser_channel
    ) as bm:
        page = bm.page

        # Group A: bot.sannysoft.com fingerprint table
        logger.info("Running Group A: bot.sannysoft.com")
        sannysoft_results = await check_bot_sannysoft(page)
        all_results.extend(sannysoft_results)

        # Group B: creepjs trust score (advisory)
        logger.info("Running Group B: creepjs trust score")
        creepjs_result = await check_creepjs(page)
        all_results.append(creepjs_result)

        # Group C: x.com/home reachability
        if include_x_home:
            logger.info("Running Group C: x.com/home reachability")
            x_result = await check_x_home(page)
            all_results.append(x_result)

    return all_results
