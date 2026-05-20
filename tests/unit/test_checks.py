"""Unit tests for xcli.checks pure parser functions.

These tests exercise parse_sannysoft_rows and parse_creepjs_payload
without hitting the network — all inputs are hand-crafted dicts.

Run with:
    uv run pytest tests/unit/test_checks.py -v
"""

from __future__ import annotations

import pytest

from xcli.checks import (
    CheckStatus,
    parse_creepjs_payload,
    parse_sannysoft_rows,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_rows(*triples: tuple[str, str, str]) -> list[dict[str, str]]:
    """Build a list of row dicts from (label, result, result_class) tuples."""
    return [
        {"label": label, "result": result, "result_class": result_class}
        for label, result, result_class in triples
    ]


def _make_rows_no_class(*pairs: tuple[str, str]) -> list[dict[str, str]]:
    """Build a list of legacy row dicts from (label, result) tuples (no result_class)."""
    return [{"label": label, "result": result} for label, result in pairs]


# ---------------------------------------------------------------------------
# parse_sannysoft_rows — happy paths
# ---------------------------------------------------------------------------


class TestParseSannysoftRowsHappyPath:
    def test_all_critical_pass(self):
        rows = _make_rows(
            ("WebDriver (New)", "passed", ""),
            ("Chrome (New)", "present", ""),
            ("Permissions (New)", "passed", ""),
            ("Plugins Length (Old)", "passed", ""),
            ("Languages (Old)", "passed", ""),
            (
                "WebGL Vendor & Renderer (New)",
                "Google Inc. (Apple), ANGLE (Apple, Apple M1, OpenGL 4.1)",
                "",
            ),
        )
        results = parse_sannysoft_rows(rows)
        # Last result is the summary; all preceding are per-row
        per_row = [r for r in results if r.name != "sannysoft_summary"]
        assert len(per_row) == 6
        for r in per_row:
            assert r.status == CheckStatus.PASS, (
                f"Expected PASS for {r.name!r} but got {r.status!r}: {r.detail}"
            )

    def test_summary_appended(self):
        rows = _make_rows(("WebDriver (New)", "passed", ""))
        results = parse_sannysoft_rows(rows)
        summary = results[-1]
        assert summary.name == "sannysoft_summary"
        assert summary.category == "fingerprint"

    def test_summary_pass_when_all_pass(self):
        rows = _make_rows(
            ("WebDriver (New)", "passed", ""),
            ("Chrome (New)", "present", ""),
        )
        results = parse_sannysoft_rows(rows)
        summary = results[-1]
        assert summary.status == CheckStatus.PASS

    def test_empty_rows_produces_pass_summary(self):
        results = parse_sannysoft_rows([])
        assert results[-1].name == "sannysoft_summary"
        assert results[-1].status == CheckStatus.PASS

    def test_rows_with_empty_label_are_skipped(self):
        rows = [
            {"label": "", "result": "passed", "result_class": ""},
            {"label": "WebDriver (New)", "result": "passed", "result_class": ""},
        ]
        results = parse_sannysoft_rows(rows)
        per_row = [r for r in results if r.name != "sannysoft_summary"]
        assert len(per_row) == 1
        assert per_row[0].name == "WebDriver (New)"

    def test_legacy_no_class_key_still_works(self):
        """Rows without result_class key should not raise (backward compat)."""
        rows = _make_rows_no_class(
            ("WebDriver (New)", "passed"),
            ("Chrome (New)", "present"),
        )
        results = parse_sannysoft_rows(rows)
        per_row = [r for r in results if r.name != "sannysoft_summary"]
        assert all(r.status == CheckStatus.PASS for r in per_row)


# ---------------------------------------------------------------------------
# parse_sannysoft_rows — critical failure cases
# ---------------------------------------------------------------------------


class TestParseSannysoftRowsCriticalFails:
    def test_webdriver_failed_is_critical_fail(self):
        rows = _make_rows(("WebDriver (New)", "failed", ""))
        results = parse_sannysoft_rows(rows)
        row_result = next(r for r in results if r.name == "WebDriver (New)")
        assert row_result.status == CheckStatus.FAIL
        assert row_result.critical is True

    def test_summary_fails_when_critical_row_fails(self):
        rows = _make_rows(("WebDriver (New)", "failed", ""), ("Chrome (New)", "present", ""))
        results = parse_sannysoft_rows(rows)
        summary = results[-1]
        assert summary.status == CheckStatus.FAIL
        assert summary.critical is True

    def test_advisory_row_fail_does_not_fail_summary(self):
        """Non-critical rows that produce FAIL should not make summary FAIL."""
        rows = _make_rows(
            ("WebDriver (New)", "passed", ""),
            ("SomeOtherCheck", "failed", ""),
        )
        results = parse_sannysoft_rows(rows)
        summary = results[-1]
        # SomeOtherCheck is not critical → FAIL but non-critical → summary PASS
        assert summary.status == CheckStatus.PASS
        assert summary.critical is False

    def test_missing_result_standalone_critical_row_is_warn(self):
        """Standalone 'missing' on a critical row → WARN (can't determine)."""
        rows = _make_rows(("Permissions (New)", "missing", ""))
        results = parse_sannysoft_rows(rows)
        row_result = next(r for r in results if r.name == "Permissions (New)")
        assert row_result.status == CheckStatus.WARN
        assert row_result.critical is False

    def test_summary_evidence_tracks_critical_fails(self):
        rows = _make_rows(
            ("WebDriver (New)", "failed", ""),
            ("Chrome (New)", "missing (failed)", ""),
        )
        results = parse_sannysoft_rows(rows)
        summary = results[-1]
        assert summary.evidence is not None
        assert summary.evidence["critical_fails"] == 2

    def test_summary_evidence_zero_critical_fails_on_pass(self):
        rows = _make_rows(("WebDriver (New)", "passed", ""))
        results = parse_sannysoft_rows(rows)
        summary = results[-1]
        assert summary.evidence["critical_fails"] == 0


# ---------------------------------------------------------------------------
# WebGL special-case detection (legacy combined row)
# ---------------------------------------------------------------------------


class TestWebGLSpecialCase:
    def test_good_webgl_renderer_passes(self):
        rows = _make_rows(
            (
                "WebGL Vendor & Renderer (New)",
                "Google Inc. (Apple), ANGLE (Apple, Apple M1, OpenGL 4.1)",
                "",
            )
        )
        results = parse_sannysoft_rows(rows)
        row_result = next(r for r in results if r.name == "WebGL Vendor & Renderer (New)")
        assert row_result.status == CheckStatus.PASS
        assert row_result.critical is True

    def test_mesa_offscreen_is_headless_tell(self):
        rows = _make_rows(("WebGL Vendor & Renderer (New)", "Brian Paul, Mesa OffScreen", ""))
        results = parse_sannysoft_rows(rows)
        row_result = next(r for r in results if r.name == "WebGL Vendor & Renderer (New)")
        assert row_result.status == CheckStatus.FAIL
        assert row_result.critical is True
        assert "headless" in row_result.detail.lower()

    def test_mesa_x_org_is_headless_tell(self):
        rows = _make_rows(("WebGL Vendor & Renderer (New)", "Mesa/X.org", ""))
        results = parse_sannysoft_rows(rows)
        row_result = next(r for r in results if r.name == "WebGL Vendor & Renderer (New)")
        assert row_result.status == CheckStatus.FAIL

    def test_swiftshader_is_headless_tell(self):
        rows = _make_rows(("WebGL Vendor & Renderer (New)", "Google SwiftShader", ""))
        results = parse_sannysoft_rows(rows)
        row_result = next(r for r in results if r.name == "WebGL Vendor & Renderer (New)")
        assert row_result.status == CheckStatus.FAIL

    def test_llvmpipe_is_headless_tell(self):
        rows = _make_rows(("WebGL Vendor & Renderer (New)", "Mesa llvmpipe", ""))
        results = parse_sannysoft_rows(rows)
        row_result = next(r for r in results if r.name == "WebGL Vendor & Renderer (New)")
        assert row_result.status == CheckStatus.FAIL

    def test_empty_webgl_value_is_warn(self):
        rows = _make_rows(("WebGL Vendor & Renderer (New)", "", ""))
        results = parse_sannysoft_rows(rows)
        row_result = next(r for r in results if r.name == "WebGL Vendor & Renderer (New)")
        assert row_result.status == CheckStatus.WARN
        assert row_result.critical is False

    def test_webgl_evidence_contains_value(self):
        renderer = "NVIDIA Corporation, GeForce RTX 3080/PCIe/SSE2"
        rows = _make_rows(("WebGL Vendor & Renderer (New)", renderer, ""))
        results = parse_sannysoft_rows(rows)
        row_result = next(r for r in results if r.name == "WebGL Vendor & Renderer (New)")
        assert row_result.evidence is not None
        assert row_result.evidence.get("webgl_value") == renderer


# ---------------------------------------------------------------------------
# New separated WebGL rows (WebGL Vendor / WebGL Renderer)
# ---------------------------------------------------------------------------


class TestSeparatedWebGLRows:
    def test_canvas_no_webgl_context_vendor_is_critical_fail(self):
        """'Canvas has no webgl context' on WebGL Vendor → FAIL critical=True."""
        rows = _make_rows(("WebGL Vendor", "Canvas has no webgl context", ""))
        results = parse_sannysoft_rows(rows)
        row_result = next(r for r in results if r.name == "WebGL Vendor")
        assert row_result.status == CheckStatus.FAIL
        assert row_result.critical is True

    def test_canvas_no_webgl_context_renderer_is_critical_fail(self):
        """'Canvas has no webgl context' on WebGL Renderer → FAIL critical=True."""
        rows = _make_rows(("WebGL Renderer", "Canvas has no webgl context", ""))
        results = parse_sannysoft_rows(rows)
        row_result = next(r for r in results if r.name == "WebGL Renderer")
        assert row_result.status == CheckStatus.FAIL
        assert row_result.critical is True

    def test_swiftshader_on_renderer_row_is_critical_fail(self):
        """SwiftShader on WebGL Renderer → FAIL critical=True via strict-FAIL pattern."""
        rows = _make_rows(("WebGL Renderer", "SwiftShader", ""))
        results = parse_sannysoft_rows(rows)
        row_result = next(r for r in results if r.name == "WebGL Renderer")
        assert row_result.status == CheckStatus.FAIL
        assert row_result.critical is True

    def test_good_webgl_vendor_with_bg_success_passes(self):
        """'Google Inc.' with bg-success class → PASS (class beats text)."""
        rows = _make_rows(("WebGL Vendor", "Google Inc. (Apple), ANGLE...", "bg-success"))
        results = parse_sannysoft_rows(rows)
        row_result = next(r for r in results if r.name == "WebGL Vendor")
        assert row_result.status == CheckStatus.PASS

    def test_webgl_vendor_with_bg_danger_is_critical_fail(self):
        """Any value with bg-danger on a WebGL row → FAIL critical=True (class beats text)."""
        rows = _make_rows(("WebGL Vendor", "passed", "bg-danger"))
        results = parse_sannysoft_rows(rows)
        row_result = next(r for r in results if r.name == "WebGL Vendor")
        assert row_result.status == CheckStatus.FAIL
        assert row_result.critical is True


# ---------------------------------------------------------------------------
# New table-driven tests from docoutput.json rows
# ---------------------------------------------------------------------------


class TestDocOutputRowClassification:
    """Verify every row type seen in the live docoutput.json is classified correctly."""

    @pytest.mark.parametrize(
        "label, result, result_class, expected_status, expected_critical",
        [
            # Parenthetical pass — "missing (passed)" means the property is absent
            # and sannysoft considers that a PASS for this test
            ("WebDriver (New)", "missing (passed)", "", CheckStatus.PASS, True),
            # Parenthetical fail — "missing (failed)" means the property is absent
            # and sannysoft considers that a FAIL for this test
            ("Chrome (New)", "missing (failed)", "", CheckStatus.FAIL, True),
            # Strict-FAIL: "Canvas has no webgl context" is a hard headless tell
            ("WebGL Vendor", "Canvas has no webgl context", "", CheckStatus.FAIL, True),
            # CSS class beats result text: bg-success → PASS regardless of text
            (
                "WebGL Renderer",
                "Google Inc. (Apple), ANGLE...",
                "bg-success",
                CheckStatus.PASS,
                True,
            ),
            # "Plugins is of type PluginArray" is NOT in critical substrings
            (
                "Plugins is of type PluginArray",
                "failed",
                "",
                CheckStatus.FAIL,
                False,
            ),
            # Advisory informational row — language value is just emitted, treat as PASS
            ("Languages (Old)", "en-US", "", CheckStatus.PASS, False),
            # Advisory informational row — platform value
            ("navigator.platform", "MacIntel", "", CheckStatus.PASS, False),
            # Advisory informational row — canvas hash
            ("Canvas1", "Hash: -2016801316", "", CheckStatus.PASS, False),
            # CSS class beats text: "passed" text but bg-danger → FAIL critical
            ("WebDriver (New)", "passed", "bg-danger", CheckStatus.FAIL, True),
            # Advisory: Permissions (New) with a real value → PASS advisory
            ("Permissions (New)", "prompt", "", CheckStatus.PASS, False),
            # Strict-FAIL: SwiftShader on WebGL Renderer → FAIL critical
            ("WebGL Renderer", "SwiftShader", "", CheckStatus.FAIL, True),
        ],
    )
    def test_row_classification(
        self, label, result, result_class, expected_status, expected_critical
    ):
        rows = _make_rows((label, result, result_class))
        results = parse_sannysoft_rows(rows)
        row_result = next(r for r in results if r.name != "sannysoft_summary")
        assert row_result.status == expected_status, (
            f"label={label!r} result={result!r} class={result_class!r}: "
            f"expected status {expected_status!r}, got {row_result.status!r} ({row_result.detail})"
        )
        assert row_result.critical == expected_critical, (
            f"label={label!r} result={result!r} class={result_class!r}: "
            f"expected critical={expected_critical}, got {row_result.critical!r}"
        )

    def test_advisory_informational_rows_do_not_fail_summary(self):
        """Many advisory rows that just emit values should keep summary at PASS."""
        rows = _make_rows(
            ("navigator.platform", "MacIntel", ""),
            ("navigator.appName", "Netscape", ""),
            ("navigator.vendor", "Google Inc.", ""),
            ("Canvas1", "Hash: -2016801316", ""),
            ("screen.width", "1280", ""),
            ("navigator.doNotTrack", "null", ""),
        )
        results = parse_sannysoft_rows(rows)
        summary = results[-1]
        assert summary.status == CheckStatus.PASS, f"Summary should be PASS: {summary.detail}"

    def test_two_critical_webgl_fails_make_summary_fail_critical(self):
        """If WebGL Vendor + WebGL Renderer both return 'Canvas has no webgl context',
        summary should be FAIL critical=True with critical_fails=2."""
        rows = _make_rows(
            ("WebGL Vendor", "Canvas has no webgl context", ""),
            ("WebGL Renderer", "Canvas has no webgl context", ""),
        )
        results = parse_sannysoft_rows(rows)
        summary = results[-1]
        assert summary.status == CheckStatus.FAIL
        assert summary.critical is True
        assert summary.evidence["critical_fails"] == 2

    def test_zero_critical_fails_summary_pass(self):
        rows = _make_rows(
            ("WebDriver (New)", "passed", ""),
            ("navigator.platform", "MacIntel", ""),
        )
        results = parse_sannysoft_rows(rows)
        summary = results[-1]
        assert summary.status == CheckStatus.PASS
        assert summary.evidence["critical_fails"] == 0


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
# parse_creepjs_payload — new threshold tests
# ---------------------------------------------------------------------------


class TestParseCreepjsPayloadThreshold:
    def test_score_67_passes(self):
        """Score 67 → well above threshold → PASS."""
        payload = {"trust_score": 67.0, "lies": 0, "is_bot": False}
        result = parse_creepjs_payload(payload)
        assert result.status == CheckStatus.PASS

    def test_score_4_fails(self):
        """Score 4 (< 5) → FAIL."""
        payload = {"trust_score": 4.0, "lies": 0, "is_bot": False}
        result = parse_creepjs_payload(payload)
        assert result.status == CheckStatus.FAIL

    def test_score_2_fails(self):
        """Score 2 (very low, < 5) → FAIL."""
        payload = {"trust_score": 2.0, "lies": 0, "is_bot": False}
        result = parse_creepjs_payload(payload)
        assert result.status == CheckStatus.FAIL

    def test_score_5_passes(self):
        """Score exactly 5 (not < 5) → PASS."""
        payload = {"trust_score": 5.0, "lies": 0, "is_bot": False}
        result = parse_creepjs_payload(payload)
        assert result.status == CheckStatus.PASS

    def test_no_score_no_bot_is_warn(self):
        """No score, no bot → WARN (advisory, cannot determine)."""
        payload = {"trust_score": None, "lies": 0, "is_bot": False}
        result = parse_creepjs_payload(payload)
        assert result.status == CheckStatus.WARN

    def test_is_bot_true_no_score_fails(self):
        """is_bot=True with no score → FAIL."""
        payload = {"trust_score": None, "lies": 0, "is_bot": True}
        result = parse_creepjs_payload(payload)
        assert result.status == CheckStatus.FAIL

    def test_is_bot_true_good_score_still_fails(self):
        """is_bot=True overrides a good trust score → FAIL."""
        payload = {"trust_score": 80.0, "lies": 0, "is_bot": True}
        result = parse_creepjs_payload(payload)
        assert result.status == CheckStatus.FAIL


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
