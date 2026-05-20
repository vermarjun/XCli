# XCli

**Stealth X (Twitter) CLI — authenticated DOM scraping via Patchright.**

XCli lets you pull your own feed, profile data, and post metrics from X.com
using your existing browser session. It drives a persistent Chromium profile
(stored under `~/.xcli/`) with Patchright — the undetected Playwright fork —
so the browser fingerprint is indistinguishable from a regular Chrome instance.
All data is returned as machine-readable JSON, ready to pipe into `jq` or any
downstream tool.

---

## What it does

| Capability | Details |
|---|---|
| **Feed scraping** | Scroll your home timeline, extract posts with full metrics |
| **Profile scraping** | Pull any public profile's bio and recent posts |
| **Cookie import / export** | Seed a session from a Netscape-format cookie file |
| **Login via real browser** | Interactive login in a visible Chromium window |
| **Bot-detection checks** | Run sannysoft / CreepJS / X.com home health checks |
| **Session status** | Verify whether the stored session is still valid |

---

## Quick start

```bash
# 1. Install (Python 3.12–3.14 required)
pip install -e ".[dev]"

# 2. Install Patchright's Chromium
patchright install chromium

# 3. Log in (opens a visible browser window — complete the flow manually)
xcli login

# 4. Verify the session
xcli status

# 5. Pull your home feed (20 posts, JSON to stdout)
#    A visible browser window opens by default — this is intentional (see stealth notes below).
xcli feed --count 20 | jq .

# 6. Scrape a profile
xcli profile @TwitterDev | jq .
```

---

## Commands

| Command | Key options | Description |
|---|---|---|
| `xcli login` | — | Interactive login via Chromium (always headful) |
| `xcli logout` | — | Clear stored session cookies |
| `xcli status` | — | Check whether the current session is valid |
| `xcli feed` | `--count N`, `--comments-per N`, `--headless`, `--channel CHAN`, `--jitter-pct F`, `--output FILE` | Scrape home timeline (headful by default) |
| `xcli profile` | `@handle`, `--posts N`, `--headless`, `--channel CHAN`, `--jitter-pct F`, `--output FILE` | Scrape a user profile (headful by default) |
| `xcli doctor` | `--json`, `--channel CHAN` | Run bot-detection sanity checks |

---

## Output schemas

### `xcli feed` — array of PostSchema

```json
[
  {
    "id": "1234567890123456789",
    "author": {
      "handle": "@xcli_user",
      "display_name": "XCli User",
      "verified": false
    },
    "text": "Hello, world!",
    "media": [
      { "type": "image", "url": "https://pbs.twimg.com/media/..." }
    ],
    "metrics": {
      "likes": 42,
      "reposts": 7,
      "replies": 3,
      "views": 1500
    },
    "posted_at": "2026-05-01T12:00:00Z",
    "posted_at_text": "12:00 PM · May 1, 2026",
    "url": "https://x.com/xcli_user/status/1234567890123456789",
    "comments": []
  }
]
```

### `xcli profile` — ProfileSchema

```json
{
  "handle": "@TwitterDev",
  "display_name": "Twitter Dev",
  "bio": "The voice of the X Platform developer community.",
  "location": "127.0.0.1",
  "website": "https://developer.x.com",
  "joined": "2007-02",
  "verified": true,
  "stats": {
    "following": 2048,
    "followers": 571234
  },
  "posts": []
}
```

---

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | Unexpected / internal error |
| `2` | Configuration or environment error |
| `3` | Authentication error (not logged in, session expired) |
| `4` | Target not found, suspended, or protected |
| `5` | Rate-limited by X |

---

## How it stays undetected

1. **Patchright** — patches Chromium's automation flags so `navigator.webdriver` is `false`.
2. **Persistent profile** — reuses the same `~/.xcli/profile/` across runs; cookies and localStorage survive.
3. **Warm-up navigation** — visits neutral sites (Google, Wikipedia, GitHub) before touching X.
4. **Jitter** — configurable ± percentage applied to all navigation delays (`--jitter-pct`, default 0.20).
5. **No API / XHR injection** — all data is read from the rendered DOM, not intercepted network traffic.
6. **`data-testid` selectors only** — uses X's own stable e2e-test hooks (never fragile CSS class selectors).
7. **Modal dismissal** — automatically closes cookie-consent and sign-up prompts before extracting.
8. **Rate-limit detection** — aborts with exit code 5 rather than hammering X on a soft-block.

### Headful by default for feed and profile

`xcli feed` and `xcli profile` open a **visible** browser window by default. This is intentional.
Headless Chromium has three well-known bot tells that X can detect:

- **HeadlessChrome UA** — the User-Agent string contains `HeadlessChrome/...` instead of `Chrome/...`.
- **WebGL OffScreen renderer** — headless mode reports `"Canvas has no webgl context"` (no GPU), a
  clear fingerprint tell on sites like bot.sannysoft.com.
- **Plugins Length 0** — headless Chromium ships with no browser plugins; real Chrome has several.

Running headful (`headless=False`, the default) avoids all three tells. Use `--headless` only in
CI/Docker environments without a display.

For the **strongest stealth posture**, pair with `--channel chrome` to use your locally installed
Google Chrome instead of the bundled Patchright Chromium. Installed Chrome has real GPU-accelerated
WebGL, real browser plugins, and a standard (non-headless) UA even in new-headless mode:

```bash
xcli feed --count 20 --channel chrome | jq .
xcli profile elonmusk --posts 10 --channel chrome | jq .
```

---

## Configuration

All settings can be overridden via environment variables (or a `.env` file in the working directory).

| Variable | Default | Description |
|---|---|---|
| `XCLI_HEADLESS` | `true` | Run Chromium headless (`false` for visible window) |
| `XCLI_CHANNEL` | `chromium` | Browser channel: `chromium` (bundled), `chrome` (installed — best stealth), `chrome-beta`, `chrome-dev`, `msedge`. CLI `--channel` takes precedence. |
| `XCLI_PROFILE_DIR` | `~/.xcli/profile` | Path to the persistent Chromium profile |
| `XCLI_JITTER_PCT` | `0.20` | Fractional jitter on nav delays (0.0 = off, 1.0 = ±100%) |
| `XCLI_LOG_LEVEL` | `WARNING` | Python logging level |
| `XCLI_COOKIE_FILE` | — | Path to a Netscape cookie file to import on login |

---

## Project layout

```
xcli/
├── __main__.py          # python -m xcli entry point
├── cli.py               # Typer app — all commands + async wrappers
├── config.py            # BrowserConfig dataclass + env-var loading
├── exceptions.py        # AuthenticationError, RateLimitError, …
├── session_state.py     # Profile-dir helpers, cookie-path utils
├── checks.py            # Bot-detection checks (sannysoft, CreepJS, X home)
├── common_utils.py      # Shared small utilities
├── core/
│   ├── auth.py          # is_logged_in, detect_rate_limit, warm_up_browser
│   ├── browser.py       # BrowserManager (Patchright wrapper)
│   └── utils.py         # capture_as_you_scroll, dismiss_modals
├── drivers/
│   └── browser.py       # Singleton get_or_create_browser / close_browser
├── scraping/
│   ├── selectors.py     # single source of truth for all X selectors
│   ├── extractor.py     # XExtractor — DOM extraction + jitter
│   └── parsing.py       # Raw DOM -> PostSchema / ProfileSchema
└── tools/
    ├── feed.py          # FeedTool — orchestrates feed scrape
    └── profile.py       # ProfileTool — orchestrates profile scrape

scripts/
└── dump_snapshots.py    # CLI helper: dump live HTML + screenshots for tests

tests/
├── unit/                # Pure unit tests (no browser, fully mocked)
├── integration/         # Hermetic integration tests (local HTTP fixtures)
└── e2e/                 # Live tests (require XCLI_LIVE=1 + valid session)
```

---

## Development guide

```bash
# Install dev dependencies (includes pre-commit, ruff, pytest-cov, etc.)
uv sync --all-extras

# Run unit + integration tests — fast, no coverage gate
uv run pytest tests/unit tests/integration -q

# Run unit + integration tests with coverage gate (CI-equivalent local check, >=80%)
uv run pytest tests/unit tests/integration --cov=xcli --cov-fail-under=80 -q

# Run linter / formatter
uv run ruff check . && uv run ruff format .

# Install and run pre-commit hooks
uv run pre-commit install
uv run pre-commit run --all-files

# Run live e2e tests (requires a valid ~/.xcli session)
XCLI_LIVE=1 uv run pytest tests/e2e -v

# Dump live DOM snapshots for updating integration fixtures
python scripts/dump_snapshots.py --target feed
python scripts/dump_snapshots.py --target profile --user TwitterDev
```

### Updating integration fixtures

1. Run `python scripts/dump_snapshots.py --target <feed|profile|thread>` while logged in.
2. The script writes `tests/integration/dumps/<target>_<timestamp>.html`.
3. Copy the relevant HTML into the appropriate `tests/integration/fixtures/` file.
4. Re-run `pytest tests/integration` to confirm parsing still passes.

---

## Limitations & Terms of Service

XCli is a personal-use automation tool. It only accesses data your own account
can see when browsing normally — it does not bypass access controls, scrape
private accounts, or interact with X's API.

X's Terms of Service prohibit automated scraping. Using this tool against their
terms is solely your responsibility. The authors make no representation that
this tool is compliant with X's ToS, robots.txt, or any other platform policy.

The tool is intentionally rate-limit-aware and exits cleanly when X signals a
soft-block (exit code 5) rather than retrying aggressively. It stores no data
beyond what is written to the file path you specify. No credentials are
transmitted to any third party.

Use at your own risk. This project exists for personal research and
home-timeline backup purposes.

---

## License

MIT — see [LICENSE](LICENSE).

---

## Acknowledgements

- [Patchright](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright) — the undetected Playwright fork that makes stealth browsing possible.
- [Typer](https://typer.tiangolo.com/) — the CLI framework powering the command interface.

---

## Companion documents

- [`plan/`](plan/) — full design plan (phases 1–5, output schemas, hardening checklist).
