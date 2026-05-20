"""Live profile test. Gated by XCLI_LIVE=1.

Runs xcli profile TwitterDev --posts 3 --comments-per 1 against the real X
profile page. TwitterDev (@TwitterDev) is a long-stable official handle.

Run with:
    XCLI_LIVE=1 uv run pytest tests/e2e/test_profile_live.py -v
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

# Handle to use for live profile test — stable, public, non-controversial account
_TEST_HANDLE = "TwitterDev"

runner = CliRunner()


def test_profile_returns_valid_json() -> None:
    """xcli profile TwitterDev should return valid JSON with exit code 0."""
    from xcli.cli import app

    result = runner.invoke(app, ["profile", _TEST_HANDLE, "--posts", "3", "--comments-per", "1"])
    assert result.exit_code in (
        0,
        4,
    ), f"xcli profile exited {result.exit_code}\nOutput: {result.output}"

    try:
        json.loads(result.output)
    except json.JSONDecodeError as exc:
        pytest.fail(f"xcli profile did not produce valid JSON: {exc}\nOutput: {result.output}")


def test_profile_fields_populated() -> None:
    """Profile block should have display_name and handle populated."""
    from xcli.cli import app

    result = runner.invoke(app, ["profile", _TEST_HANDLE, "--posts", "3", "--comments-per", "1"])
    if result.exit_code == 4:
        pytest.skip(f"{_TEST_HANDLE} appears to be not-found/suspended/protected — skipping")

    data = json.loads(result.output)
    prof = data.get("profile", {})

    assert not prof.get("not_found"), f"{_TEST_HANDLE} reported not_found"
    assert not prof.get("suspended"), f"{_TEST_HANDLE} reported suspended"

    assert prof.get("display_name"), f"profile.display_name is empty for {_TEST_HANDLE}"
    handle = prof.get("handle") or ""
    assert handle.startswith("@"), f"profile.handle should start with '@', got: {handle!r}"


def test_profile_posts_count() -> None:
    """Should capture exactly 3 posts."""
    from xcli.cli import app

    result = runner.invoke(app, ["profile", _TEST_HANDLE, "--posts", "3", "--comments-per", "1"])
    if result.exit_code == 4:
        pytest.skip(f"{_TEST_HANDLE} appears unavailable — skipping")

    data = json.loads(result.output)
    posts = data.get("posts", [])
    assert len(posts) == 3, f"Expected 3 posts, got {len(posts)}"
