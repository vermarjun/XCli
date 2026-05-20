"""xcli CLI — Typer application.

Commands implemented in Phase 0:
    login    — interactive headful login
    logout   — move ~/.xcli/ aside (safe recovery, not delete)
    status   — headless session check

Stubs (print "not implemented yet" + exit 1):
    feed     — Phase 1
    profile  — Phase 2
    doctor   — Phase 3

Logs / progress → stderr (via rich Console(stderr=True))
JSON output    → stdout (via typer.echo)

Exit codes (plan §10):
    0  success
    1  generic error
    2  authentication required
    3  rate-limited / soft-block
    4  profile not found / suspended / protected
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

import typer
from rich.console import Console

from xcli.exceptions import (
    AuthenticationError,
    RateLimitError,
    XCliError,
)

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="Stealth X (Twitter) CLI — authenticated DOM scraping via Patchright.",
)
console = Console(stderr=True)  # All logs/progress go to stderr; JSON to stdout


# ---------------------------------------------------------------------------
# login
# ---------------------------------------------------------------------------


@app.command()
def login() -> None:
    """One-time interactive login. Opens a real browser window.

    Navigates to https://x.com/login and waits up to 5 minutes for you to
    complete authentication (including 2FA, Arkose captcha, email verify, etc.).
    Exports cookies and writes ~/.xcli/source-state.json on success.
    """
    try:
        success = asyncio.run(_login_cmd())
        if not success:
            console.print("[red]Login failed.[/red]")
            raise typer.Exit(code=1)
        console.print("[green]Login successful.[/green]")
    except AuthenticationError as e:
        console.print(f"[red]Authentication error:[/red] {e}")
        raise typer.Exit(code=2) from e
    except XCliError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=e.exit_code) from e
    except Exception as e:
        console.print(f"[red]Unexpected error:[/red] {e}")
        raise typer.Exit(code=1) from e


async def _login_cmd() -> bool:
    from xcli.setup import interactive_login

    return await interactive_login()


# ---------------------------------------------------------------------------
# logout
# ---------------------------------------------------------------------------


@app.command()
def logout() -> None:
    """Clear the stored session by moving ~/.xcli/ aside (not deleted — recoverable)."""
    from xcli.session_state import auth_root_dir, clear_auth_state

    root = auth_root_dir()
    if not root.exists():
        console.print("No active session found — nothing to clear.")
        return

    # Close any running browser singleton first
    try:
        from xcli.drivers.browser import _browser, close_browser

        if _browser is not None:
            asyncio.run(close_browser())
    except Exception:
        pass

    if clear_auth_state():
        console.print(
            f"[green]Session cleared.[/green] "
            f"Auth directory moved aside from {root}. "
            f"Run [bold]xcli login[/bold] to create a new session."
        )
    else:
        console.print(
            "[yellow]Partial clear.[/yellow] Some files could not be moved. Check logs for details."
        )
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


@app.command()
def status() -> None:
    """Print session state and exit.

    Output is JSON to stdout. Exit code 0 if authenticated, 2 if not.
    """
    try:
        result = asyncio.run(_status_cmd())
        typer.echo(json.dumps(result, indent=2))
        if not result.get("authenticated"):
            raise typer.Exit(code=2)
    except typer.Exit:
        raise
    except AuthenticationError as e:
        out = {"authenticated": False, "error": str(e)}
        typer.echo(json.dumps(out, indent=2))
        raise typer.Exit(code=2) from e
    except XCliError as e:
        out = {"authenticated": False, "error": str(e)}
        typer.echo(json.dumps(out, indent=2))
        raise typer.Exit(code=e.exit_code) from e
    except Exception as e:
        out = {"authenticated": False, "error": str(e)}
        typer.echo(json.dumps(out, indent=2))
        raise typer.Exit(code=1) from e


async def _status_cmd() -> dict:
    from xcli.common_utils import utcnow_iso
    from xcli.session_state import (
        load_source_state,
        portable_cookie_path,
        profile_exists,
    )

    source_state = load_source_state()
    profile_ok = profile_exists()
    cookie_ok = portable_cookie_path().exists()

    if not source_state or not profile_ok:
        return {
            "authenticated": False,
            "profile_exists": profile_ok,
            "cookie_exists": cookie_ok,
            "source_state": None,
            "checked_at": utcnow_iso(),
        }

    # Compute age of the source state
    age_days: float | None = None
    try:
        from datetime import UTC, datetime

        created = datetime.fromisoformat(source_state.created_at.replace("Z", "+00:00"))
        delta = datetime.now(UTC) - created
        age_days = round(delta.total_seconds() / 86400, 1)
    except Exception:
        pass

    # Do a lightweight headless browser check
    authed = False
    handle: str | None = None
    try:
        from xcli.core.auth import is_logged_in
        from xcli.drivers.browser import close_browser, get_or_create_browser

        browser = await get_or_create_browser(headless=True)
        authed = await is_logged_in(browser.page)

        # Try to extract handle from sidebar account switcher
        try:
            from xcli.scraping.extractor import read_authenticated_handle

            handle = await read_authenticated_handle(browser.page)
        except Exception:
            pass

        await close_browser()
    except AuthenticationError:
        authed = False
    except Exception as e:
        console.print(f"[yellow]Warning:[/yellow] browser check failed: {e}", file=sys.stderr)
        authed = False

    return {
        "authenticated": authed,
        "handle": f"@{handle}" if handle else None,
        "source_state_age_days": age_days,
        "login_generation": source_state.login_generation,
        "profile_exists": profile_ok,
        "cookie_exists": cookie_ok,
        "checked_at": utcnow_iso(),
    }


# ---------------------------------------------------------------------------
# feed
# ---------------------------------------------------------------------------


@app.command()
def feed(
    count: int = typer.Option(10, "--count", "-n", min=1, max=100),
    comments_per: int = typer.Option(3, "--comments-per", "-y", min=0, max=50),
    output: Path | None = typer.Option(None, "--output", "-o"),
    headless: bool = typer.Option(
        False,
        "--headless",
        help=(
            "Run browser headless (default: visible). "
            "Visible mode has better stealth: no HeadlessChrome UA, real WebGL, real plugins. "
            "Use --headless only when running in CI/Docker without a display."
        ),
    ),
    channel: str | None = typer.Option(
        None,
        "--channel",
        help=(
            "Browser channel: chromium (default, bundled), "
            "chrome (installed Chrome — better stealth), "
            "chrome-beta, chrome-dev, msedge."
        ),
    ),
    jitter_pct: float | None = typer.Option(
        None,
        "--jitter-pct",
        min=0.0,
        max=1.0,
        help="Fractional jitter on nav delays (0.0–1.0). Overrides XCLI_JITTER_PCT.",
    ),
) -> None:
    """Fetch top N posts from your home feed with top Y comments each.

    Runs with a visible browser by default for best stealth (avoids HeadlessChrome
    UA, WebGL OffScreen renderer, and Plugins Length 0 tells). Use ``--headless``
    only in CI/Docker environments without a display.

    Requires an authenticated session. Run ``xcli login`` first if needed.

    Output is JSON (stdout) unless ``--output`` is specified.
    Exit codes: 0 ok, 2 auth needed, 3 rate-limited, 1 other error.
    """
    _setup_logging()
    try:
        result = asyncio.run(_feed_cmd(count, comments_per, headless, jitter_pct, channel))
        payload = json.dumps(result, indent=2, ensure_ascii=False)
        if output:
            output.write_text(payload + "\n", encoding="utf-8")
            console.print(f"[green]Feed written to[/green] {output}")
        else:
            typer.echo(payload)
    except AuthenticationError as e:
        console.print(f"[red]Authentication required:[/red] {e}")
        console.print("Run [bold]xcli login[/bold] to establish a session.")
        raise typer.Exit(code=2) from e
    except RateLimitError as e:
        console.print(
            f"[yellow]Rate limited:[/yellow] {e}  (suggested wait: {e.suggested_wait_seconds}s)"
        )
        raise typer.Exit(code=3) from e
    except XCliError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=e.exit_code) from e
    except Exception as e:
        console.print(f"[red]Unexpected error:[/red] {e}")
        raise typer.Exit(code=1) from e


async def _feed_cmd(
    count: int,
    comments_per: int,
    headless: bool,
    jitter_pct: float | None = None,
    channel: str | None = None,
) -> dict:
    from xcli.tools.feed import run

    return await run(count, comments_per, headless=headless, jitter_pct=jitter_pct, channel=channel)


# ---------------------------------------------------------------------------
# profile
# ---------------------------------------------------------------------------


@app.command()
def profile(
    username: str = typer.Argument(...),
    posts: int = typer.Option(10, "--posts", "-n", min=1, max=100),
    comments_per: int = typer.Option(3, "--comments-per", "-y", min=0, max=50),
    output: Path | None = typer.Option(None, "--output", "-o"),
    headless: bool = typer.Option(
        False,
        "--headless",
        help=(
            "Run browser headless (default: visible). "
            "Visible mode has better stealth: no HeadlessChrome UA, real WebGL, real plugins. "
            "Use --headless only when running in CI/Docker without a display."
        ),
    ),
    channel: str | None = typer.Option(
        None,
        "--channel",
        help=(
            "Browser channel: chromium (default, bundled), "
            "chrome (installed Chrome — better stealth), "
            "chrome-beta, chrome-dev, msedge."
        ),
    ),
    jitter_pct: float | None = typer.Option(
        None,
        "--jitter-pct",
        min=0.0,
        max=1.0,
        help="Fractional jitter on nav delays (0.0–1.0). Overrides XCLI_JITTER_PCT.",
    ),
) -> None:
    """Deep-research a user's profile + their top N posts + Y comments each.

    Runs with a visible browser by default for best stealth (avoids HeadlessChrome
    UA, WebGL OffScreen renderer, and Plugins Length 0 tells). Use ``--headless``
    only in CI/Docker environments without a display.

    Requires an authenticated session. Run ``xcli login`` first if needed.

    Output is JSON (stdout) unless ``--output`` is specified.
    Exit codes: 0 ok, 2 auth needed, 3 rate-limited, 4 not-found/suspended/protected, 1 other.
    """
    _setup_logging()
    try:
        result = asyncio.run(
            _profile_cmd(username, posts, comments_per, headless, jitter_pct, channel)
        )
        payload = json.dumps(result, indent=2, ensure_ascii=False)
        if output:
            output.write_text(payload + "\n", encoding="utf-8")
            console.print(f"[green]Profile written to[/green] {output}")
        else:
            typer.echo(payload)

        # Exit code 4 for profile-error states (not_found, suspended, protected)
        profile_data = result.get("profile") or {}
        if (
            profile_data.get("not_found")
            or profile_data.get("suspended")
            or profile_data.get("protected")
        ):
            raise typer.Exit(code=4)

    except typer.Exit:
        raise
    except AuthenticationError as e:
        console.print(f"[red]Authentication required:[/red] {e}")
        console.print("Run [bold]xcli login[/bold] to establish a session.")
        raise typer.Exit(code=2) from e
    except RateLimitError as e:
        console.print(
            f"[yellow]Rate limited:[/yellow] {e}  (suggested wait: {e.suggested_wait_seconds}s)"
        )
        raise typer.Exit(code=3) from e
    except XCliError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=e.exit_code) from e
    except Exception as e:
        console.print(f"[red]Unexpected error:[/red] {e}")
        raise typer.Exit(code=1) from e


async def _profile_cmd(
    username: str,
    posts: int,
    comments_per: int,
    headless: bool,
    jitter_pct: float | None = None,
    channel: str | None = None,
) -> dict:
    from xcli.tools.profile import run

    return await run(
        username, posts, comments_per, headless=headless, jitter_pct=jitter_pct, channel=channel
    )


# ---------------------------------------------------------------------------
# doctor (Phase 3)
# ---------------------------------------------------------------------------


@app.command()
def doctor(
    skip_x: bool = typer.Option(False, "--skip-x", help="Skip the x.com reachability check."),
    json_output: bool = typer.Option(False, "--json", help="Write JSON summary to stdout."),
    channel: str | None = typer.Option(
        None,
        "--channel",
        help=(
            "Browser channel: chromium (default, bundled), "
            "chrome (installed Chrome — better stealth), "
            "chrome-beta, chrome-dev, msedge."
        ),
    ),
) -> None:
    """Run stealth fingerprint checks and print a PASS/FAIL report.

    Runs:
      - bot.sannysoft.com fingerprint detection
      - creepjs trust score (advisory)
      - x.com/home reachability (if logged in)

    Exit 0 if all critical checks pass, 1 otherwise.
    JSON output (--json) goes to stdout; the human-readable table goes to stderr.
    """
    try:
        results = asyncio.run(_doctor_cmd(skip_x=skip_x, channel=channel))
    except Exception as e:
        console.print(f"[red]doctor failed:[/red] {e}")
        raise typer.Exit(code=1) from e

    if json_output:
        from dataclasses import asdict

        typer.echo(json.dumps([asdict(r) for r in results], indent=2, default=str))
    else:
        _render_doctor_table(results)

    if any(r.status.value == "fail" and r.critical for r in results):
        raise typer.Exit(code=1)


async def _doctor_cmd(*, skip_x: bool, channel: str | None = None) -> list:
    from xcli.checks import run_all_checks

    return await run_all_checks(include_x_home=not skip_x, channel=channel)


def _render_doctor_table(results: list) -> None:
    """Render a rich.Table of CheckResults to stderr."""
    from rich.table import Table

    from xcli.checks import CheckStatus

    _STATUS_COLOR = {
        CheckStatus.PASS: "green",
        CheckStatus.WARN: "yellow",
        CheckStatus.FAIL: "red",
        CheckStatus.SKIP: "dim",
    }

    table = Table(title="xcli doctor — stealth check results", show_lines=True)
    table.add_column("Name", style="bold", no_wrap=True)
    table.add_column("Category")
    table.add_column("Status", no_wrap=True)
    table.add_column("Detail", overflow="fold")

    for r in results:
        color = _STATUS_COLOR.get(r.status, "white")
        status_text = f"[{color}]{r.status.value.upper()}[/{color}]"
        if r.critical and r.status.value == "fail":
            status_text += " [red bold]CRITICAL[/red bold]"
        table.add_row(r.name, r.category, status_text, r.detail)

    # Table → stderr so JSON piping (--json) stays clean
    from rich.console import Console as _Console

    _Console(stderr=True).print(table)


# ---------------------------------------------------------------------------
# Logging setup helper (called by commands that need it)
# ---------------------------------------------------------------------------


def _setup_logging() -> None:
    from xcli.config import get_config

    config = get_config()
    logging.basicConfig(
        level=getattr(logging, config.log_level, logging.WARNING),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )
