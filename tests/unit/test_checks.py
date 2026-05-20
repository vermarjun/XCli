"""Unit tests for xcli.checks pure parser functions.

These tests exercise parse_sannysoft_rows and parse_creepjs_payload
without hitting the network — all inputs are hand-crafted dicts.

Run with:
    uv run pytest tests/unit/test_checks.py -v
"""

from __future__ import annotations

from xcli.checks import (
    CheckStatus,
    parse_creepjs_payload,
    parse_sannysoft_rows,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_rows(*pairs: tuple[str, str]) -> list[dict[str, str]]:
    """Build a list of row dicts from (label, result) tuples."""
    return [{"label": label, "result": result} for label, result in pairs]


# ---------------------------------------------------------------------------
# parse_sannysoft_rows — happy paths
# ---------------------------------------------------------------------------


class TestParseSannysoftRowsHappyPath:
    def test_all_critical_pass(self):
        rows = _make_rows(
            ("WebDriver (New)", "passed"),
            ("Chrome (New)", "present"),
            ("Permissions (New)", "passed"),
            ("Plugins Length (Old)", "passed"),
            ("Languages (Old)", "passed"),
            (
                "WebGL Vendor & Renderer (New)",
                "Google Inc. (Apple), ANGLE (Apple, Apple M1, OpenGL 4.1)",
            ),
        )
        results = parse_sannysoft_rows(rows)
        # Last result is the summary; all preceding are per-row
        per_row = [r for r in results if r.name != "sannysoft_summary"]
        assert len(per_row) == 6
        for r in per_row:
            assert (
                r.status == CheckStatus.PASS
            ), f"Expected PASS for {r.name!r} but got {r.status!r}: {r.detail}"

    def test_summary_appended(self):
        rows = _make_rows(("WebDriver (New)", "passed"))
        results = parse_sannysoft_rows(rows)
        summary = results[-1]
        assert summary.name == "sannysoft_summary"
        assert summary.category == "fingerprint"

    def test_summary_pass_when_all_pass(self):
        rows = _make_rows(
            ("WebDriver (New)", "passed"),
            ("Chrome (New)", "present"),
        )
        results = parse_sannysoft_rows(rows)
        summary = results[-1]
        assert summary.status == CheckStatus.PASS

    def test_empty_rows_produces_pass_summary(self):
        results = parse_sannysoft_rows([])
        assert results[-1].name == "sannysoft_summary"
        assert results[-1].status == CheckStatus.PASS

    def test_rows_with_empty_label_are_skipped(self):
        rows = [{"label": "", "result": "passed"}, {"label": "WebDriver (New)", "result": "passed"}]
        results = parse_sannysoft_rows(rows)
        per_row = [r for r in results if r.name != "sannysoft_summary"]
        assert len(per_row) == 1
        assert per_row[0].name == "WebDriver (New)"


# ---------------------------------------------------------------------------
# parse_sannysoft_rows — critical failure cases
# ---------------------------------------------------------------------------


class TestParseSannysoftRowsCriticalFails:
    def test_webdriver_failed_is_critical_fail(self):
        rows = _make_rows(("WebDriver (New)", "failed"))
        results = parse_sannysoft_rows(rows)
        row_result = next(r for r in results if r.name == "WebDriver (New)")
        assert row_result.status == CheckStatus.FAIL
        assert row_result.critical is True

    def test_summary_fails_when_critical_row_fails(self):
        rows = _make_rows(("WebDriver (New)", "failed"), ("Chrome (New)", "present"))
        results = parse_sannysoft_rows(rows)
        summary = results[-1]
        assert summary.status == CheckStatus.FAIL
        assert summary.critical is True

    def test_advisory_row_fail_does_not_fail_summary(self):
        """Non-critical rows produce WARN, not FAIL in summary (unless critical)."""
        rows = _make_rows(
            ("WebDriver (New)", "passed"),
            ("SomeOtherCheck", "failed"),
        )
        results = parse_sannysoft_rows(rows)
        summary = results[-1]
        # SomeOtherCheck is not in CRITICAL_ROW_LABELS → advisory fail → WARN summary
        assert summary.status == CheckStatus.WARN
        assert summary.critical is False

    def test_missing_result_treated_as_fail(self):
        rows = _make_rows(("Permissions (New)", "missing"))
        results = parse_sannysoft_rows(rows)
        row_result = next(r for r in results if r.name == "Permissions (New)")
        assert row_result.status == CheckStatus.FAIL
        assert row_result.critical is True


# ---------------------------------------------------------------------------
# WebGL special-case detection
# ---------------------------------------------------------------------------


class TestWebGLSpecialCase:
    def test_good_webgl_renderer_passes(self):
        rows = _make_rows(
            (
                "WebGL Vendor & Renderer (New)",
                "Google Inc. (Apple), ANGLE (Apple, Apple M1, OpenGL 4.1)",
            )
        )
        results = parse_sannysoft_rows(rows)
        row_result = next(r for r in results if r.name == "WebGL Vendor & Renderer (New)")
        assert row_result.status == CheckStatus.PASS
        assert row_result.critical is True

    def test_mesa_offscreen_is_headless_tell(self):
        rows = _make_rows(("WebGL Vendor & Renderer (New)", "Brian Paul, Mesa OffScreen"))
        results = parse_sannysoft_rows(rows)
        row_result = next(r for r in results if r.name == "WebGL Vendor & Renderer (New)")
        assert row_result.status == CheckStatus.FAIL
        assert row_result.critical is True
        assert "headless" in row_result.detail.lower()

    def test_mesa_x_org_is_headless_tell(self):
        rows = _make_rows(("WebGL Vendor & Renderer (New)", "Mesa/X.org"))
        results = parse_sannysoft_rows(rows)
        row_result = next(r for r in results if r.name == "WebGL Vendor & Renderer (New)")
        assert row_result.status == CheckStatus.FAIL

    def test_swiftshader_is_headless_tell(self):
        rows = _make_rows(("WebGL Vendor & Renderer (New)", "Google SwiftShader"))
        results = parse_sannysoft_rows(rows)
        row_result = next(r for r in results if r.name == "WebGL Vendor & Renderer (New)")
        assert row_result.status == CheckStatus.FAIL

    def test_llvmpipe_is_headless_tell(self):
        rows = _make_rows(("WebGL Vendor & Renderer (New)", "Mesa llvmpipe"))
        results = parse_sannysoft_rows(rows)
        row_result = next(r for r in results if r.name == "WebGL Vendor & Renderer (New)")
        assert row_result.status == CheckStatus.FAIL

    def test_empty_webgl_value_is_warn(self):
        rows = _make_rows(("WebGL Vendor & Renderer (New)", ""))
        results = parse_sannysoft_rows(rows)
        row_result = next(r for r in results if r.name == "WebGL Vendor & Renderer (New)")
        assert row_result.status == CheckStatus.WARN
        assert row_result.critical is False

    def test_webgl_evidence_contains_value(self):
        renderer = "NVIDIA Corporation, GeForce RTX 3080/PCIe/SSE2"
        rows = _make_rows(("WebGL Vendor & Renderer (New)", renderer))
        results = parse_sannysoft_rows(rows)
        row_result = next(r for r in results if r.name == "WebGL Vendor & Renderer (New)")
        assert row_result.evidence is not None
        assert row_result.evidence.get("webgl_value") == renderer


# ---------------------------------------------------------------------------
# parse_creepjs_payload — happy paths
# ---------------------------------------------------------------------------


class TestParseCreepjsPayloadHappyPath:
    def test_normal_score_passes(self):
        payload = {"trust_score": 67.3, "lies": 4, "is_bot": False}
        result = parse_creepjs_payload(payload)
        assert result.status == CheckStatus.PASS
        assert "67.3" in result.detail
        assert result.critical is False

    def test_zero_score_fails(self):
        payload = {"trust_score": 0, "is_bot": False, "lies": 100}
        result = parse_creepjs_payload(payload)
        assert result.status == CheckStatus.FAIL
        assert result.critical is False  # advisory

    def test_is_bot_true_fails(self):
        payload = {"trust_score": 0, "is_bot": True, "lies": 0}
        result = parse_creepjs_payload(payload)
        assert result.status == CheckStatus.FAIL

    def test_none_score_is_warn(self):
        payload = {"trust_score": None, "is_bot": False, "lies": 0}
        result = parse_creepjs_payload(payload)
        assert result.status == CheckStatus.WARN

    def test_high_score_not_bot_passes(self):
        payload = {"trust_score": 95.0, "lies": 0, "is_bot": False}
        result = parse_creepjs_payload(payload)
        assert result.status == CheckStatus.PASS

    def test_evidence_is_attached(self):
        payload = {"trust_score": 67.3, "lies": 4, "is_bot": False}
        result = parse_creepjs_payload(payload)
        assert result.evidence == payload

    def test_result_name_and_category(self):
        payload = {"trust_score": 50.0, "lies": 2, "is_bot": False}
        result = parse_creepjs_payload(payload)
        assert result.name == "creepjs_trust"
        assert result.category == "trust"


# ---------------------------------------------------------------------------
# CheckResult dataclass — basic contract
# ---------------------------------------------------------------------------


class TestCheckResultContract:
    def test_status_is_str_enum(self):
        assert CheckStatus.PASS == "pass"
        assert CheckStatus.FAIL == "fail"
        assert CheckStatus.WARN == "warn"
        assert CheckStatus.SKIP == "skip"

    def test_parse_sannysoft_returns_list(self):
        result = parse_sannysoft_rows([])
        assert isinstance(result, list)

    def test_parse_creepjs_returns_single_result(self):
        from xcli.checks import CheckResult

        result = parse_creepjs_payload({"trust_score": 50.0, "is_bot": False, "lies": 0})
        assert isinstance(result, CheckResult)

    def test_critical_flag_defaults_false(self):
        from xcli.checks import CheckResult

        r = CheckResult(name="x", category="y", status=CheckStatus.PASS, detail="ok")
        assert r.critical is False

    def test_evidence_defaults_none(self):
        from xcli.checks import CheckResult

        r = CheckResult(name="x", category="y", status=CheckStatus.PASS, detail="ok")
        assert r.evidence is None
