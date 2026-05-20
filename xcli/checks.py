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

NOTE on bot.sannysoft.com CSS classes:
  The ``bg-success`` / ``bg-danger`` / ``bg-warning`` class names used in the
  JS extractor below are Bootstrap classes applied by bot.sannysoft.com (an
  *external* site).  They are NOT X.com selectors and are therefore exempt
  from the plan §6 rule that restricts selector definitions to selectors.py.
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

# creepjs is a SPA; trust score renders after several seconds (~6-15s of JS).
# Selectors tried in order:
_CREEPJS_URL = "https://abrahamjuliot.github.io/creepjs/"
_CREEPJS_SELECTORS_ORDERED = [
    '[data-testid="trust-score"]',
    "#fingerprint-data .trust-score-text",
    "#fingerprint-data .header .score",
    '[class*="trust"]:has-text("%")',
    '[class*="score"]:has-text("%")',
]
# Fallback regexes if no selector matches:
_CREEPJS_SCORE_REGEXES = [
    re.compile(r"(?i)trust\s*score[^0-9]*(\d+(?:\.\d+)?)\s*%"),
    re.compile(r"(?i)\btrust\b[^a-z0-9]*([0-9]+)\s*%"),
]

# Bot-detected strings that creepjs might show (guard for false positives on
# generic page copy that mentions "bot"):
_CREEPJS_BOT_DETECTED_STRINGS: tuple[str, ...] = (
    "bot detected",
    "you are a bot",
    "detected as bot",
    "classified as bot",
)

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

# Critical row label substrings — matched by substring to be locale-independent.
# A row is critical if any of these substrings appears in the label.
_CRITICAL_ROW_SUBSTRINGS: tuple[str, ...] = (
    "WebDriver",
    "Chrome",
    "Permissions",
    "Plugins Length",
    "Languages",
    "WebGL",
)

# Legacy exact-match set kept for backward compatibility with existing tests
# that reference "WebGL Vendor & Renderer (New)".
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

# Strict-FAIL patterns — any of these in the result text is a hard headless tell.
# The first group handles the generic "canvas has no webgl context" message that
# sannysoft now emits for the separated WebGL Vendor / WebGL Renderer rows.
_STRICT_FAIL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"canvas has no webgl context", re.IGNORECASE),
    re.compile(r"swiftshader", re.IGNORECASE),
    re.compile(r"mesa offscreen", re.IGNORECASE),
    re.compile(r"brian paul,?\s*mesa", re.IGNORECASE),
    re.compile(r"llvmpipe", re.IGNORECASE),
    # Mesa/X.org (legacy combined row)
    re.compile(r"mesa/x\.org", re.IGNORECASE),
)

# Legacy headless substrings (kept for backward compat with tests referencing
# "WebGL Vendor & Renderer (New)"):
_HEADLESS_WEBGL_STRINGS: tuple[str, ...] = (
    "Brian Paul",
    "Mesa OffScreen",
    "Mesa/X.org",
    "SwiftShader",
    "llvmpipe",
)

# "Passing" / "Failing" result strings (exact, lowercased)
_PASS_RESULT_STRINGS: frozenset[str] = frozenset({"passed", "present"})
_FAIL_RESULT_STRINGS: frozenset[str] = frozenset({"failed", "missing", "detected"})

# Regex to capture parenthetical pass/fail wrappers like "missing (passed)"
_PARENTHETICAL_RE = re.compile(r"\((passed|failed)\)\s*$", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _is_critical_label(label: str) -> bool:
    """Return True if *label* matches any critical-row substring."""
    label_lower = label.lower()
    return any(sub.lower() in label_lower for sub in _CRITICAL_ROW_SUBSTRINGS)


# ---------------------------------------------------------------------------
# Pure parser functions (no network — tested by tests/unit/test_checks.py)
# ---------------------------------------------------------------------------


def _classify_sannysoft_row(label: str, result: str, result_class: str = "") -> CheckResult:
    """Classify a single bot.sannysoft.com table row into a CheckResult.

    Priority (highest first):
    1. result_class contains 'bg-success'  → PASS
    2. result_class contains 'bg-danger'   → FAIL (critical if label is critical)
    3. result_class contains 'bg-warning'  → WARN
    4. Text classification (widened vocabulary — see inline comments)

    The old "WebGL Vendor & Renderer (New)" combined row is handled via the
    _HEADLESS_WEBGL_STRINGS list for backward compatibility.  The new separated
    rows ("WebGL Vendor", "WebGL Renderer") are handled via _STRICT_FAIL_PATTERNS.
    """
    is_critical = _is_critical_label(label)
    result_lower = result.strip().lower()
    raw_result = result.strip()

    # ------------------------------------------------------------------
    # Priority 1-3: CSS class-based classification (authoritative)
    # ------------------------------------------------------------------
    if "bg-success" in result_class:
        return CheckResult(
            name=label,
            category="fingerprint",
            status=CheckStatus.PASS,
            detail="passed",
            critical=is_critical,
            evidence={"raw_result": raw_result},
        )
    if "bg-danger" in result_class:
        return CheckResult(
            name=label,
            category="fingerprint",
            status=CheckStatus.FAIL,
            detail=f"Result: {result_lower!r}",
            critical=is_critical,
            evidence={"raw_result": raw_result},
        )
    if "bg-warning" in result_class:
        return CheckResult(
            name=label,
            category="fingerprint",
            status=CheckStatus.WARN,
            detail=f"Unexpected result: {result_lower!r}",
            critical=False,
            evidence={"raw_result": raw_result},
        )

    # ------------------------------------------------------------------
    # Priority 4: Text classification (no class info available)
    # ------------------------------------------------------------------

    # Legacy combined WebGL row — keep old behavior for backward compat
    if label == "WebGL Vendor & Renderer (New)":
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

    # 4a. Exact pass/fail strings.
    # Special case: standalone "missing" on a *critical* row means the property
    # is absent and we can't determine pass/fail → WARN (not FAIL).
    # Standalone "missing" on a non-critical row is a FAIL (original behavior).
    if result_lower == "missing" and is_critical:
        return CheckResult(
            name=label,
            category="fingerprint",
            status=CheckStatus.WARN,
            detail=f"Property absent (cannot determine pass/fail): {raw_result!r}",
            critical=False,
            evidence={"raw_result": raw_result},
        )
    if result_lower in _PASS_RESULT_STRINGS:
        return CheckResult(
            name=label,
            category="fingerprint",
            status=CheckStatus.PASS,
            detail=f"{result_lower}",
            critical=is_critical,
            evidence={"raw_result": raw_result},
        )
    if result_lower in _FAIL_RESULT_STRINGS:
        return CheckResult(
            name=label,
            category="fingerprint",
            status=CheckStatus.FAIL,
            detail=f"Result: {result_lower!r}",
            critical=is_critical,
            evidence={"raw_result": raw_result},
        )

    # 4b. Parenthetical wrapper: "missing (passed)" / "missing (failed)"
    m = _PARENTHETICAL_RE.search(raw_result)
    if m:
        verdict = m.group(1).lower()
        if verdict == "passed":
            return CheckResult(
                name=label,
                category="fingerprint",
                status=CheckStatus.PASS,
                detail=f"passed (parenthetical): {raw_result!r}",
                critical=is_critical,
                evidence={"raw_result": raw_result},
            )
        else:  # "failed"
            return CheckResult(
                name=label,
                category="fingerprint",
                status=CheckStatus.FAIL,
                detail=f"failed (parenthetical): {raw_result!r}",
                critical=is_critical,
                evidence={"raw_result": raw_result},
            )

    # 4c. Strict-FAIL patterns (headless/virtual renderer tells)
    for pattern in _STRICT_FAIL_PATTERNS:
        if pattern.search(raw_result):
            return CheckResult(
                name=label,
                category="fingerprint",
                status=CheckStatus.FAIL,
                detail=f"Headless/virtual renderer detected: {raw_result!r}",
                critical=is_critical,
                evidence={"raw_result": raw_result},
            )

    # 4d. All other values → advisory PASS (informational row; the page just emits a value)
    return CheckResult(
        name=label,
        category="fingerprint",
        status=CheckStatus.PASS,
        detail=f"advisory: {raw_result!r}",
        critical=False,
        evidence={"raw_result": raw_result},
    )


def parse_sannysoft_rows(rows: list[dict[str, str]]) -> list[CheckResult]:
    """Turn raw bot.sannysoft.com row dicts into CheckResults.

    Args:
        rows: List of dicts from the table.  Accepted shapes:
              - {"label": "...", "result": "...", "result_class": "..."}  (new)
              - {"label": "...", "result": "..."}  (legacy; result_class defaults to "")

    Returns:
        One CheckResult per row.  An extra summary CheckResult is appended at
        the end (category="fingerprint", name="sannysoft_summary").

    Summary logic:
        - Any critical FAIL → summary is FAIL critical=True.
        - Zero fails → summary is PASS.
    """
    results: list[CheckResult] = []
    for row in rows:
        label = row.get("label", "").strip()
        result = row.get("result", "").strip()
        result_class = row.get("result_class", "")
        if not label:
            continue
        results.append(_classify_sannysoft_row(label, result, result_class))

    # Summary entry
    critical_fails = [r for r in results if r.critical and r.status == CheckStatus.FAIL]
    if critical_fails:
        summary_status = CheckStatus.FAIL
        summary_detail = (
            f"{len(critical_fails)} critical check(s) failed: "
            f"{', '.join(r.name for r in critical_fails)}"
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
            evidence={"total": len(results), "critical_fails": len(critical_fails)},
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

    creepjs's DOM changes frequently; this check is intentionally tolerant —
    the goal is to surface 'definitely a bot' signals, not to assert a specific
    score.

    Pass status logic:
        - FAIL if is_bot=True OR trust_score is not None and trust_score < 5.
        - WARN if trust_score is None (could not read score) and not is_bot.
        - PASS otherwise (score found, not flagged as bot).
    """
    trust_score = payload.get("trust_score")
    is_bot = bool(payload.get("is_bot", False))
    lies = payload.get("lies", 0)

    if is_bot or (trust_score is not None and trust_score < 5):
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

    NOTE: The JS extractor below reads the ``className`` of each result cell
    (the second <td>).  bot.sannysoft.com applies Bootstrap utility classes
    ``bg-success``, ``bg-danger``, and ``bg-warning`` to these cells — these
    are the page's own authoritative pass/fail signal and take priority over
    text-based classification.  These class names are external-site classes
    and are NOT X.com selectors; per plan §6 they do not belong in
    selectors.py.
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
                    const resultTd = tds[1];
                    return {
                        label: tds[0].innerText.trim(),
                        result: resultTd.innerText.trim(),
                        result_class: resultTd.className || ''
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

    creepjs's DOM changes frequently; this check is intentionally tolerant —
    the goal is to surface 'definitely a bot' signals, not to assert a specific
    score.

    Args:
        page: A Patchright ``Page`` object.

    Returns:
        A single CheckResult.  Advisory (critical=False) because trust scores
        fluctuate per browser version and algorithm changes.
    """
    try:
        await page.goto(_CREEPJS_URL, wait_until="domcontentloaded", timeout=30_000)

        # Try each known selector in order; wait up to 30s total for score to render
        # (creepjs runs ~6-15s of JS before exposing the score).
        score_text: str | None = None
        for sel in _CREEPJS_SELECTORS_ORDERED:
            try:
                elem = page.locator(sel).first
                count = await elem.count()
                if count > 0:
                    await elem.wait_for(state="visible", timeout=30_000)
                    score_text = await elem.inner_text()
                    logger.info("creepjs: found score via selector %r: %r", sel, score_text)
                    break
            except Exception:
                continue

        # Body text regex fallback — scan body innerText with multiple patterns
        body_text: str = await page.inner_text("body")
        if not score_text:
            for score_re in _CREEPJS_SCORE_REGEXES:
                m = score_re.search(body_text)
                if m:
                    score_text = m.group(0)
                    logger.info("creepjs: score via body regex: %r", score_text)
                    break

        # Parse trust score from whatever text we found
        trust_score: float | None = None
        if score_text:
            # Extract the first numeric value (possibly with decimal)
            m2 = re.search(r"(\d+(?:\.\d+)?)", score_text)
            if m2:
                trust_score = float(m2.group(1))

        # Check for "Bot" classification in the page.
        # Only treat as bot if the body contains one of the per-locale bot-detected
        # strings (guard against generic mentions of "bot" in page copy).
        body_lower = body_text.lower()
        is_bot_classified = any(s in body_lower for s in _CREEPJS_BOT_DETECTED_STRINGS)

        # Scrape lies count (advisory context)
        lies = 0
        lies_m = re.search(r"(\d+)\s+lies?\b", body_text[:3000], re.IGNORECASE)
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
