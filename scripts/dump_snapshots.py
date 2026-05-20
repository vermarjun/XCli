"""Dump live X.com DOM snapshots for fixture refresh.

When X redesigns and our handcrafted fixtures drift, run this script against a
real authenticated session to capture the current DOM structure to disk. The
dumps live in tests/integration/dumps/ (git-ignored scratch artefacts).

Usage:
    uv run python scripts/dump_snapshots.py --target feed
    uv run python scripts/dump_snapshots.py --target profile --user elonmusk
    uv run python scripts/dump_snapshots.py --target thread --url https://x.com/user/status/123

Targets:
    feed     → navigates to https://x.com/home (main timeline)
    profile  → navigates to https://x.com/<user> (requires --user)
    thread   → navigates to the given --url (requires --url)

Outputs (per target):
    tests/integration/dumps/<target>_<timestamp>.html   — full outerHTML
    tests/integration/dumps/<target>_<timestamp>.png    — full-page screenshot

Requirements:
    - xcli login must have been run (profile at ~/.xcli/profile)
    - Network access to x.com
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

# Add project root to sys.path so this script can be run directly
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

DUMPS_DIR = _PROJECT_ROOT / "tests" / "integration" / "dumps"

# Page-ready selector (matches selectors.py PRIMARY_COLUMN)
_PRIMARY_COLUMN_SELECTOR = '[data-testid="primaryColumn"]'
_PROFILE_NAME_SELECTOR = '[data-testid="UserName"]'


# ---------------------------------------------------------------------------
# Core dump logic
# ---------------------------------------------------------------------------


async def _dump(
    target: str,
    user: str | None,
    url: str | None,
    *,
    headless: bool,
) -> None:
    from xcli.core.auth import detect_auth_barrier_quick
    from xcli.core.browser import BrowserManager
    from xcli.core.utils import dismiss_modals
    from xcli.session_state import get_source_profile_dir, profile_exists

    if not profile_exists():
        print(
            "ERROR: No authenticated session found at ~/.xcli/profile.\nRun `xcli login` first.",
            file=sys.stderr,
        )
        sys.exit(2)

    DUMPS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = f"{target}_{timestamp}"

    profile_dir = get_source_profile_dir()
    bm = BrowserManager(user_data_dir=profile_dir, headless=headless)
    await bm.start()

    try:
        page = bm.page

        # --- Resolve target URL ---
        if target == "feed":
            nav_url = "https://x.com/home"
            ready_selector = _PRIMARY_COLUMN_SELECTOR
        elif target == "profile":
            if not user:
                print("ERROR: --target profile requires --user <handle>", file=sys.stderr)
                sys.exit(1)
            nav_url = f"https://x.com/{user}"
            ready_selector = _PROFILE_NAME_SELECTOR
        elif target == "thread":
            if not url:
                print("ERROR: --target thread requires --url <tweet_url>", file=sys.stderr)
                sys.exit(1)
            nav_url = url
            ready_selector = _PRIMARY_COLUMN_SELECTOR
        else:
            print(
                f"ERROR: Unknown target '{target}'. Choose: feed, profile, thread", file=sys.stderr
            )
            sys.exit(1)

        print(f"Navigating to: {nav_url}")
        await page.goto(nav_url, wait_until="domcontentloaded", timeout=30_000)

        # Check for auth barrier
        barrier = await detect_auth_barrier_quick(page)
        if barrier:
            print(
                f"ERROR: Authentication barrier detected: {barrier}\n"
                "Run `xcli login` to refresh the session.",
                file=sys.stderr,
            )
            sys.exit(2)

        # Wait for page-ready signal
        print(f"Waiting for page-ready signal: {ready_selector}")
        try:
            await page.wait_for_selector(ready_selector, timeout=20_000)
        except Exception:
            print("WARNING: page-ready selector not found within 20s — dumping anyway")

        # Dismiss modals / overlays before capture
        await dismiss_modals(page)

        # --- Capture outerHTML ---
        html: str = await page.evaluate("() => document.documentElement.outerHTML")
        html_path = DUMPS_DIR / f"{prefix}.html"
        html_path.write_text(html, encoding="utf-8")
        print(f"HTML dump  → {html_path} ({len(html):,} chars)")

        # --- Full-page screenshot ---
        png_path = DUMPS_DIR / f"{prefix}.png"
        await page.screenshot(path=str(png_path), full_page=True)
        print(f"Screenshot → {png_path}")

        print(f"\nDone. Artefacts in {DUMPS_DIR}/")

    finally:
        await bm.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dump_snapshots.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--target",
        required=True,
        choices=["feed", "profile", "thread"],
        help="Which page to capture.",
    )
    p.add_argument(
        "--user",
        default=None,
        metavar="HANDLE",
        help="X handle for --target profile (without leading @).",
    )
    p.add_argument(
        "--url",
        default=None,
        metavar="URL",
        help="Full X tweet URL for --target thread.",
    )
    p.add_argument(
        "--headless",
        action="store_true",
        default=False,
        help="Run browser in headless mode (default: False — visible for debugging).",
    )
    return p


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    asyncio.run(
        _dump(
            target=args.target,
            user=args.user,
            url=args.url,
            headless=args.headless,
        )
    )


if __name__ == "__main__":
    main()
