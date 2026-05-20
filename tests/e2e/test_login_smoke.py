"""Live login smoke test. Gated by XCLI_LIVE=1.

Assumes ~/.xcli/profile/ already exists (i.e. xcli login was previously run).
Verifies that xcli status returns authenticated=True and a non-empty handle.

Run with:
    XCLI_LIVE=1 uv run pytest tests/e2e/test_login_smoke.py -v
"""

from __future__ import annotations

import json
import os

import pytest
from typer.testing import CliRunner

pytestmark = pytest.mark.skipif(
    os.getenv("XCLI_LIVE") != "1",
    reason="Live tests gated behind XCLI_LIVE=1",
)

runner = CliRunner()


def test_status_reports_authenticated() -> None:
    """xcli status should exit 0 and report authenticated=True with a handle."""
    from xcli.cli import app

    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0, (
        f"xcli status exited {result.exit_code}\nOutput: {result.output}\n"
        f"Stderr: {result.stderr if hasattr(result, 'stderr') else '(no stderr attr)'}"
    )

    try:
        data = json.loads(result.output)
    except json.JSONDecodeError as exc:
        pytest.fail(f"xcli status did not produce valid JSON: {exc}\nOutput: {result.output}")

    assert data.get("authenticated") is True, f"Expected authenticated=True, got: {data}"
    handle = data.get("handle")
    assert handle, f"Expected a non-empty handle, got: {handle!r}"
    assert handle.startswith("@"), f"Handle should start with '@', got: {handle!r}"
