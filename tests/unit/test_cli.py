"""Unit tests for xcli.cli — CLI command wiring via Typer test runner.

Uses typer.testing.CliRunner to invoke commands without a real browser or
network. All async tool functions are monkeypatched to synchronous stubs.

Coverage targets:
  - login: success path, login-failed path, exception paths
  - logout: no-session path, clear-success, clear-failure
  - status: auth success, auth failure, exception
  - feed: success path, auth error, rate-limit error, other error
  - profile: success path, not-found exit 4, auth error, rate-limit error
  - _setup_logging: smoke test
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from xcli.cli import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_feed_result(n: int = 3) -> dict:
    posts = []
    for i in range(n):
        posts.append(
            {
                "id": str(1000 + i),
                "url": f"https://x.com/user/status/{1000 + i}",
                "author": {"username": "user", "display_name": "User", "verified": False},
                "text": f"Post {i}",
                "innertext": f"Post {i} inner",
                "posted_at": "2026-05-19T10:00:00Z",
                "metrics": {"likes": i, "replies": 0, "reposts": 0, "views": 0, "bookmarks": 0},
                "links": [],
                "media": [],
                "is_repost": False,
                "reposted_by": None,
                "is_ad": False,
                "comments": [],
                "comments_captured": 0,
                "comments_partial": False,
            }
        )
    return {
        "captured_at": "2026-05-19T12:00:00Z",
        "feed_account": "testuser",
        "count_requested": n,
        "count_captured": n,
        "comments_per_requested": 0,
        "posts": posts,
        "warnings": [],
    }


def _make_profile_result(username: str = "elonmusk") -> dict:
    return {
        "captured_at": "2026-05-19T12:00:00Z",
        "username": username,
        "url": f"https://x.com/{username}/",
        "profile": {
            "display_name": "Elon Musk",
            "handle": f"@{username}",
            "bio": "CEO of stuff",
            "bio_innertext": "CEO of stuff",
            "verified": True,
            "verified_kind": "blue",
            "location": "Earth",
            "website": None,
            "joined": "Joined June 2009",
            "joined_iso": "2009-06",
            "following_count": 200,
            "followers_count": 200_000_000,
            "links": [],
            "protected": False,
            "suspended": False,
            "not_found": False,
        },
        "posts": [],
        "warnings": [],
    }


# ---------------------------------------------------------------------------
# login
# ---------------------------------------------------------------------------


class TestLoginCommand:
    def test_login_success(self):
        with patch("xcli.cli._login_cmd", new=AsyncMock(return_value=True)):
            result = runner.invoke(app, ["login"])
        assert result.exit_code == 0

    def test_login_failure(self):
        with patch("xcli.cli._login_cmd", new=AsyncMock(return_value=False)):
            result = runner.invoke(app, ["login"])
        assert result.exit_code == 1

    def test_login_authentication_error(self):
        from xcli.exceptions import AuthenticationError

        with patch("xcli.cli._login_cmd", new=AsyncMock(side_effect=AuthenticationError("bad"))):
            result = runner.invoke(app, ["login"])
        assert result.exit_code == 2

    def test_login_xcli_error(self):
        from xcli.exceptions import XCliError

        err = XCliError("oops")
        err.exit_code = 1
        with patch("xcli.cli._login_cmd", new=AsyncMock(side_effect=err)):
            result = runner.invoke(app, ["login"])
        assert result.exit_code == 1

    def test_login_unexpected_error(self):
        with patch("xcli.cli._login_cmd", new=AsyncMock(side_effect=RuntimeError("crash"))):
            result = runner.invoke(app, ["login"])
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# logout
# ---------------------------------------------------------------------------


class TestLogoutCommand:
    def test_logout_no_session(self, tmp_path):
        """If auth root does not exist, logout prints 'nothing to clear'."""
        with (
            patch("xcli.session_state.auth_root_dir", return_value=tmp_path / "nonexistent"),
            patch("xcli.session_state.clear_auth_state", return_value=True),
        ):
            result = runner.invoke(app, ["logout"])
        assert result.exit_code == 0
        assert "nothing to clear" in result.output.lower()

    def test_logout_clears_session(self, tmp_path):
        """With a session present, logout should succeed."""
        session_dir = tmp_path / ".xcli"
        session_dir.mkdir()
        with (
            patch("xcli.session_state.auth_root_dir", return_value=session_dir),
            patch("xcli.session_state.clear_auth_state", return_value=True),
        ):
            result = runner.invoke(app, ["logout"])
        assert result.exit_code == 0

    def test_logout_partial_failure(self, tmp_path):
        """If clear_auth_state returns False, exit code is 1."""
        session_dir = tmp_path / ".xcli"
        session_dir.mkdir()
        with (
            patch("xcli.session_state.auth_root_dir", return_value=session_dir),
            patch("xcli.session_state.clear_auth_state", return_value=False),
        ):
            result = runner.invoke(app, ["logout"])
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


class TestStatusCommand:
    def test_status_authenticated(self):
        status_result = {
            "authenticated": True,
            "handle": "@testuser",
            "source_state_age_days": 1.0,
            "login_generation": "uuid-123",
            "profile_exists": True,
            "cookie_exists": True,
            "checked_at": "2026-05-19T12:00:00Z",
        }
        with patch("xcli.cli._status_cmd", new=AsyncMock(return_value=status_result)):
            result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["authenticated"] is True
        assert data["handle"] == "@testuser"

    def test_status_not_authenticated(self):
        status_result = {
            "authenticated": False,
            "handle": None,
            "profile_exists": False,
            "cookie_exists": False,
            "source_state": None,
            "checked_at": "2026-05-19T12:00:00Z",
        }
        with patch("xcli.cli._status_cmd", new=AsyncMock(return_value=status_result)):
            result = runner.invoke(app, ["status"])
        assert result.exit_code == 2

    def test_status_auth_exception(self):
        from xcli.exceptions import AuthenticationError

        with patch(
            "xcli.cli._status_cmd", new=AsyncMock(side_effect=AuthenticationError("no session"))
        ):
            result = runner.invoke(app, ["status"])
        assert result.exit_code == 2
        data = json.loads(result.output)
        assert data["authenticated"] is False

    def test_status_generic_exception(self):
        with patch("xcli.cli._status_cmd", new=AsyncMock(side_effect=RuntimeError("crash"))):
            result = runner.invoke(app, ["status"])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["authenticated"] is False


# ---------------------------------------------------------------------------
# feed
# ---------------------------------------------------------------------------


class TestFeedCommand:
    def test_feed_success_stdout(self):
        feed_result = _make_feed_result(3)
        with patch("xcli.cli._feed_cmd", new=AsyncMock(return_value=feed_result)):
            result = runner.invoke(app, ["feed", "--count", "3", "--comments-per", "0"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["count_captured"] == 3

    def test_feed_success_to_file(self, tmp_path):
        out_file = tmp_path / "feed.json"
        feed_result = _make_feed_result(2)
        with patch("xcli.cli._feed_cmd", new=AsyncMock(return_value=feed_result)):
            result = runner.invoke(
                app, ["feed", "--count", "2", "--comments-per", "0", "--output", str(out_file)]
            )
        assert result.exit_code == 0
        assert out_file.exists()
        data = json.loads(out_file.read_text())
        assert data["count_captured"] == 2

    def test_feed_auth_error(self):
        from xcli.exceptions import AuthenticationError

        with patch("xcli.cli._feed_cmd", new=AsyncMock(side_effect=AuthenticationError("expired"))):
            result = runner.invoke(app, ["feed"])
        assert result.exit_code == 2

    def test_feed_rate_limit_error(self):
        from xcli.exceptions import RateLimitError

        with patch(
            "xcli.cli._feed_cmd",
            new=AsyncMock(side_effect=RateLimitError("throttled", suggested_wait_seconds=30)),
        ):
            result = runner.invoke(app, ["feed"])
        assert result.exit_code == 3

    def test_feed_xcli_error(self):
        from xcli.exceptions import XCliError

        err = XCliError("something broke")
        with patch("xcli.cli._feed_cmd", new=AsyncMock(side_effect=err)):
            result = runner.invoke(app, ["feed"])
        assert result.exit_code == 1

    def test_feed_unexpected_error(self):
        with patch("xcli.cli._feed_cmd", new=AsyncMock(side_effect=RuntimeError("crash"))):
            result = runner.invoke(app, ["feed"])
        assert result.exit_code == 1

    def test_feed_jitter_pct_option(self):
        """--jitter-pct is accepted and passed through."""
        feed_result = _make_feed_result(1)
        captured: list[dict] = []

        async def _mock_feed(count, comments_per, headless, jitter_pct=None):
            captured.append({"jitter_pct": jitter_pct})
            return feed_result

        with patch("xcli.cli._feed_cmd", new=_mock_feed):
            result = runner.invoke(
                app, ["feed", "--count", "1", "--comments-per", "0", "--jitter-pct", "0.3"]
            )
        assert result.exit_code == 0
        assert captured[0]["jitter_pct"] == pytest.approx(0.3)


# ---------------------------------------------------------------------------
# profile
# ---------------------------------------------------------------------------


class TestProfileCommand:
    def test_profile_success_stdout(self):
        profile_result = _make_profile_result("elonmusk")
        with patch("xcli.cli._profile_cmd", new=AsyncMock(return_value=profile_result)):
            result = runner.invoke(
                app, ["profile", "elonmusk", "--posts", "1", "--comments-per", "0"]
            )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["username"] == "elonmusk"

    def test_profile_success_to_file(self, tmp_path):
        out_file = tmp_path / "profile.json"
        profile_result = _make_profile_result("elonmusk")
        with patch("xcli.cli._profile_cmd", new=AsyncMock(return_value=profile_result)):
            result = runner.invoke(
                app,
                [
                    "profile",
                    "elonmusk",
                    "--posts",
                    "1",
                    "--comments-per",
                    "0",
                    "--output",
                    str(out_file),
                ],
            )
        assert result.exit_code == 0
        data = json.loads(out_file.read_text())
        assert data["username"] == "elonmusk"

    def test_profile_not_found_exit_4(self):
        profile_result = _make_profile_result("ghostuser")
        profile_result["profile"]["not_found"] = True
        with patch("xcli.cli._profile_cmd", new=AsyncMock(return_value=profile_result)):
            result = runner.invoke(app, ["profile", "ghostuser"])
        assert result.exit_code == 4

    def test_profile_suspended_exit_4(self):
        profile_result = _make_profile_result("badactor")
        profile_result["profile"]["suspended"] = True
        with patch("xcli.cli._profile_cmd", new=AsyncMock(return_value=profile_result)):
            result = runner.invoke(app, ["profile", "badactor"])
        assert result.exit_code == 4

    def test_profile_protected_exit_4(self):
        profile_result = _make_profile_result("private")
        profile_result["profile"]["protected"] = True
        with patch("xcli.cli._profile_cmd", new=AsyncMock(return_value=profile_result)):
            result = runner.invoke(app, ["profile", "private"])
        assert result.exit_code == 4

    def test_profile_auth_error(self):
        from xcli.exceptions import AuthenticationError

        with patch(
            "xcli.cli._profile_cmd", new=AsyncMock(side_effect=AuthenticationError("no auth"))
        ):
            result = runner.invoke(app, ["profile", "elonmusk"])
        assert result.exit_code == 2

    def test_profile_rate_limit_error(self):
        from xcli.exceptions import RateLimitError

        with patch(
            "xcli.cli._profile_cmd",
            new=AsyncMock(side_effect=RateLimitError("throttled", suggested_wait_seconds=30)),
        ):
            result = runner.invoke(app, ["profile", "elonmusk"])
        assert result.exit_code == 3

    def test_profile_xcli_error(self):
        from xcli.exceptions import XCliError

        with patch("xcli.cli._profile_cmd", new=AsyncMock(side_effect=XCliError("oops"))):
            result = runner.invoke(app, ["profile", "elonmusk"])
        assert result.exit_code == 1

    def test_profile_unexpected_error(self):
        with patch("xcli.cli._profile_cmd", new=AsyncMock(side_effect=RuntimeError("crash"))):
            result = runner.invoke(app, ["profile", "elonmusk"])
        assert result.exit_code == 1

    def test_profile_jitter_pct_option(self):
        """--jitter-pct is accepted and passed through."""
        profile_result = _make_profile_result("testuser")
        captured: list[dict] = []

        async def _mock_profile(username, posts, comments_per, headless, jitter_pct=None):
            captured.append({"jitter_pct": jitter_pct})
            return profile_result

        with patch("xcli.cli._profile_cmd", new=_mock_profile):
            result = runner.invoke(
                app,
                [
                    "profile",
                    "testuser",
                    "--posts",
                    "1",
                    "--comments-per",
                    "0",
                    "--jitter-pct",
                    "0.5",
                ],
            )
        assert result.exit_code == 0
        assert captured[0]["jitter_pct"] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# doctor (smoke — just checks the command parses without crashing)
# ---------------------------------------------------------------------------


class TestDoctorCommand:
    def test_doctor_invokes_run_all_checks(self):
        """Smoke test: doctor invokes run_all_checks and renders a table."""
        from xcli.checks import CheckResult, CheckStatus

        mock_results = [
            CheckResult(
                name="WebDriver (New)",
                category="fingerprint",
                status=CheckStatus.PASS,
                detail="passed",
                critical=True,
            )
        ]
        with patch("xcli.cli._doctor_cmd", new=AsyncMock(return_value=mock_results)):
            result = runner.invoke(app, ["doctor"])
        # Exit 0 because no critical FAIL
        assert result.exit_code == 0

    def test_doctor_exits_1_on_critical_fail(self):
        from xcli.checks import CheckResult, CheckStatus

        mock_results = [
            CheckResult(
                name="WebDriver (New)",
                category="fingerprint",
                status=CheckStatus.FAIL,
                detail="failed!",
                critical=True,
            )
        ]
        with patch("xcli.cli._doctor_cmd", new=AsyncMock(return_value=mock_results)):
            result = runner.invoke(app, ["doctor"])
        assert result.exit_code == 1

    def test_doctor_json_output(self):
        from xcli.checks import CheckResult, CheckStatus

        mock_results = [
            CheckResult(
                name="WebDriver (New)",
                category="fingerprint",
                status=CheckStatus.PASS,
                detail="passed",
                critical=True,
            )
        ]
        with patch("xcli.cli._doctor_cmd", new=AsyncMock(return_value=mock_results)):
            result = runner.invoke(app, ["doctor", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert data[0]["name"] == "WebDriver (New)"
