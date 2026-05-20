"""Live feed test. Gated by XCLI_LIVE=1.

Runs xcli feed --count 3 --comments-per 1 against the real X home feed.
Asserts structural correctness of the returned JSON without asserting content.

Run with:
    XCLI_LIVE=1 uv run pytest tests/e2e/test_feed_live.py -v
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


def test_feed_returns_valid_json_with_posts() -> None:
    """xcli feed --count 3 --comments-per 1 should return valid JSON with 3 posts."""
    from xcli.cli import app

    result = runner.invoke(app, ["feed", "--count", "3", "--comments-per", "1"])
    assert result.exit_code == 0, f"xcli feed exited {result.exit_code}\nOutput: {result.output}"

    try:
        data = json.loads(result.output)
    except json.JSONDecodeError as exc:
        pytest.fail(f"xcli feed did not produce valid JSON: {exc}\nOutput: {result.output}")

    posts = data.get("posts", [])
    assert (
        len(posts) == 3
    ), f"Expected 3 posts, got {len(posts)}. count_captured={data.get('count_captured')}"


def test_feed_post_structure() -> None:
    """Every post in the feed must have required fields with valid types."""
    from xcli.cli import app

    result = runner.invoke(app, ["feed", "--count", "3", "--comments-per", "1"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    posts = data.get("posts", [])

    for i, post in enumerate(posts):
        assert post.get("id"), f"Post[{i}] missing id"
        # At least one of text or media must be non-empty
        has_text = bool((post.get("text") or "").strip())
        has_media = bool(post.get("media"))
        assert has_text or has_media, f"Post[{i}] (id={post.get('id')}) has neither text nor media"
        metrics = post.get("metrics", {})
        assert (
            metrics.get("likes", -1) >= 0
        ), f"Post[{i}] metrics.likes must be >= 0, got {metrics.get('likes')}"


def test_feed_has_comment_or_partial_flag() -> None:
    """At least one post should have a comment, or comments_partial=True."""
    from xcli.cli import app

    result = runner.invoke(app, ["feed", "--count", "3", "--comments-per", "1"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    posts = data.get("posts", [])

    has_comment_or_partial = any(
        len(p.get("comments", [])) >= 1 or p.get("comments_partial") for p in posts
    )
    assert (
        has_comment_or_partial
    ), "Expected at least one post to have a comment or comments_partial=True"
