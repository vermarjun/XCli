# XCli

<p align="left">
  <a href="https://github.com/vermarjun/XCli/actions/workflows/ci.yml" target="_blank"><img src="https://github.com/vermarjun/XCli/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI"></a>
  <a href="https://github.com/vermarjun/XCli/blob/main/LICENSE" target="_blank"><img src="https://img.shields.io/badge/License-MIT-%233fb950?labelColor=32383f" alt="License"></a>
  <a href="#"><img src="https://img.shields.io/badge/python-3.12%20%7C%203.13%20%7C%203.14-blue?labelColor=32383f" alt="Python"></a>
  <a href="#"><img src="https://img.shields.io/badge/tests-462%20passing-%233fb950?labelColor=32383f" alt="Tests"></a>
</p>

A stealth CLI that pulls your X (Twitter) home feed and any profile's posts + threaded comments as clean JSON — driven by a real, persistent Chrome session via [Patchright](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright). No private APIs, no XHR injection, no headless tells.

> [!IMPORTANT]
> **FAQ**
>
> **Is this safe? Will my account get banned?**
> The tool drives a real browser session that you log into manually. It doesn't exploit undocumented APIs or bypass authentication. X's TOS does prohibit automated scraping, so use a throwaway account, keep volume low, and don't run it on your main. With normal personal use (a handful of feed pulls per day, not bulk scraping) you're unlikely to get flagged.
>
> **What's the difference vs. snscrape / twscrape / nitter?**
> Those rely on guest tokens, private GraphQL endpoints, or third-party mirrors — which break every few weeks as X rotates `doc_id`s, tightens CSRF, and shuts down nitter instances. XCli reads the *rendered DOM* from your authenticated session, so it survives backend changes. The tradeoff: slower, and you need to log in once.

| Tool | Description | Status |
|------|-------------|--------|
| `xcli login` | One-time interactive login in a visible Chromium window — handles 2FA, Arkose captcha, email challenges manually | working |
| `xcli logout` | Move stored session aside (recoverable, not deleted) | working |
| `xcli status` | Check whether the stored session is still authenticated | working |
| `xcli feed` | Pull top N posts from your home feed with top Y comments on each | working |
| `xcli profile` | Pull a user's profile (bio, links, metadata) + top N posts + top Y comments on each | working |
| `xcli doctor` | Run stealth fingerprint checks (bot.sannysoft + CreepJS) and X reachability | working |

<br/>

## 🚀 Quick start

**Prerequisites:** [Install uv](https://docs.astral.sh/uv/getting-started/installation/), Python 3.12+.

```bash
# 1. Clone + install
git clone https://github.com/vermarjun/XCli.git
cd XCli
uv sync
uv run patchright install chromium

# 2. Log in (opens a real browser window — sign in manually, 5-min timeout)
uv run xcli login

# 3. Verify the session and stealth posture
uv run xcli status
uv run xcli doctor

# 4. Use it
uv run xcli feed --count 10 --comments-per 5 -o feed.json
uv run xcli profile elonmusk --posts 10 --comments-per 5 -o profile.json
```

Output is JSON to stdout by default — pipe through `jq` or use `-o file.json`. Logs go to stderr so piping stays clean.

> [!NOTE]
> `xcli feed` and `xcli profile` open a **visible** browser window by default — this is the safest stealth posture (see [How it stays undetected](#how-it-stays-undetected)). Add `--headless` only in CI/Docker without a display.

<br/>

## 🔧 Setup help

<details>
<summary><b>Commands & options</b></summary>

**Common flags on `feed` and `profile`:**

- `-n, --count N` / `--posts N` — number of posts to fetch (1–100, default 10)
- `-y, --comments-per N` — comments per post (0–50, default 3)
- `-o, --output FILE` — write JSON to file instead of stdout
- `--headless` — force headless mode (default is headful; see stealth notes)
- `--channel CHAN` — `chromium` (default, bundled), `chrome` (installed Chrome — best stealth), `chrome-beta`, `chrome-dev`, `msedge`
- `--jitter-pct F` — fractional jitter on navigation delays (0.0–1.0, default 0.2)

**Examples:**

```bash
# Best stealth (real Chrome, headful, jittered)
uv run xcli feed -n 20 -y 5 --channel chrome

# Quiet headless for CI
uv run xcli feed -n 5 -y 1 --headless -o /tmp/feed.json

# Profile deep-dive
uv run xcli profile TwitterDev -n 10 -y 5 -o td.json
```

</details>

<details>
<summary><b>Environment variables</b></summary>

All flags have env-var equivalents (`.env` files supported via python-dotenv):

| Variable | Default | Purpose |
|---|---|---|
| `XCLI_HEADLESS` | `false` | Default headless mode for feed/profile (CLI `--headless` overrides) |
| `XCLI_CHANNEL` | `chromium` | Browser channel — `chrome` for best stealth |
| `XCLI_PROFILE_DIR` | `~/.xcli/profile` | Path to the persistent Chromium profile |
| `XCLI_JITTER_PCT` | `0.20` | Jitter on nav delays |
| `XCLI_LOG_LEVEL` | `WARNING` | Python logging level |
| `XCLI_COOKIE_FILE` | — | Netscape cookie file to import on login |
| `XCLI_LIVE` | — | Set to `1` to enable live e2e tests |

</details>

<details>
<summary><b>Output schemas</b></summary>

**`xcli feed` → `{captured_at, feed_account, count_*, posts: [...], warnings}`**

```json
{
  "captured_at": "2026-05-20T13:01:43Z",
  "feed_account": "your_handle",
  "count_requested": 10,
  "count_captured": 10,
  "comments_per_requested": 5,
  "posts": [
    {
      "id": "2057075113229680854",
      "url": "https://x.com/elonmusk/status/2057075113229680854",
      "author": { "username": "elonmusk", "display_name": "Elon Musk", "verified": true },
      "text": "...",
      "innertext": "Elon Musk @elonmusk · 35m ... 4 6 78 1019",
      "posted_at": "2026-05-20T12:25:00.000Z",
      "posted_at_text": "35m",
      "metrics": { "replies": 4, "reposts": 6, "likes": 78, "views": 1019, "bookmarks": null },
      "links": [{ "url": "...", "raw_href": "...", "source": "tweet" }],
      "media": [{ "kind": "image", "url": null }],
      "is_repost": false,
      "reposted_by": null,
      "is_ad": false,
      "comments": [ /* same shape as a post */ ],
      "comments_captured": 5,
      "comments_partial": false
    }
  ],
  "warnings": []
}
```

**`xcli profile` → `{captured_at, username, url, profile, posts, warnings}`**

```json
{
  "captured_at": "2026-05-20T14:00:00Z",
  "username": "github",
  "url": "https://x.com/github/",
  "profile": {
    "display_name": "GitHub",
    "handle": "@github",
    "bio": "The AI-powered developer platform...",
    "verified": true,
    "verified_kind": "blue",
    "location": "San Francisco, CA",
    "website": null,
    "joined": "Joined February 2008",
    "joined_iso": "2008-02",
    "followers_count": 2600000,
    "following_count": 334,
    "links": [{ "url": "...", "raw_href": "...", "source": "bio" }],
    "protected": false,
    "suspended": false,
    "not_found": false
  },
  "posts": [ /* same shape as feed posts */ ],
  "warnings": []
}
```

**Exit codes:** `0` ok · `1` generic error · `2` auth (`xcli login` needed) · `3` rate-limited · `4` profile not-found/suspended/protected.

</details>

<details>
<summary><b>Troubleshooting</b></summary>

- **`xcli doctor` flags WebGL/Plugins/Chrome as critical fails** — those are inherent to headless Chromium. Run `feed`/`profile` headful (default) or with `--channel chrome` to clear them.
- **`x.com/home` returns soft-block ("Something went wrong")** — wait 30s and retry. The tool exits with code 3 rather than hammering.
- **Session expired** — re-run `xcli login`. The old profile is moved aside to `~/.xcli-invalid-<ts>/` (recoverable).
- **Visible browser window pops up** — that's the default; it's intentional for stealth. Add `--headless` to suppress.
- **Patchright Chromium download failed** — `uv run patchright install chromium --with-deps`.

</details>

<br/>

## 🥷 How it stays undetected

1. **[Patchright](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright)** — a maintained Playwright fork that patches Chromium's automation tells (`navigator.webdriver === false`, no CDP runtime fingerprint, etc.).
2. **Persistent profile** — `~/.xcli/profile/` is a real on-disk Chromium user-data dir. Cookies, localStorage, IndexedDB, and your auth tokens (`auth_token`, `ct0`) survive across runs. To X, it looks like the same returning Chrome.
3. **Headful by default** — `xcli feed`/`xcli profile` open a visible window. Headless mode produces three classic bot tells (`HeadlessChrome` UA, missing WebGL, zero plugins) — running headful kills all three at the source.
4. **`--channel chrome` for max stealth** — uses your installed Google Chrome instead of bundled Chromium, restoring real GPU-accelerated WebGL, real plugins, and a non-HeadlessChrome UA even in headless.
5. **DOM-only, never API** — reads rendered `innerText` + `data-testid` selectors (X's own e2e-test hooks). No private GraphQL, no XHR replay, no guest tokens — so when X rotates `doc_id`s it doesn't break us.
6. **Human pacing + jitter** — 2-second `NAV_DELAY` between navigations, ±20% jitter by default, real `mouse.wheel` scroll events. Single global async lock means no parallel hammering even if you script multiple invocations.
7. **Boundary detection** — comment scrapes stop at the "Discover more" recommendation section so unrelated tweets never leak into the `comments` array.

<br/>

## 🐍 Development

<details>
<summary><b>Local dev setup</b></summary>

```bash
# Install dev dependencies (pre-commit, ruff, pytest-cov, etc.)
uv sync --all-extras

# Fast feedback — unit + integration tests, no coverage gate
uv run pytest tests/unit tests/integration -q

# Full CI-equivalent — coverage gate ≥80%
uv run pytest tests/unit tests/integration --cov=xcli --cov-fail-under=80 -q

# Lint + format
uv run ruff check . && uv run ruff format .

# Pre-commit hooks (ruff + selector-leak grep)
uv run pre-commit install
uv run pre-commit run --all-files

# Live e2e tests (need a valid ~/.xcli session)
XCLI_LIVE=1 uv run pytest tests/e2e -v

# Dump live DOM for fixture refresh
uv run python scripts/dump_snapshots.py --target feed
uv run python scripts/dump_snapshots.py --target profile --user TwitterDev
```

</details>

<details>
<summary><b>Project layout</b></summary>

```
xcli/
├── cli.py               # Typer app — all commands + async wrappers
├── config.py            # BrowserConfig + env-var loading
├── checks.py            # Bot-detection checks (sannysoft / CreepJS / X home)
├── session_state.py     # Profile-dir + cookie-path helpers
├── core/
│   ├── auth.py          # is_logged_in, detect_rate_limit, warm_up_browser
│   ├── browser.py       # BrowserManager (Patchright wrapper)
│   └── utils.py         # capture_as_you_scroll, dismiss_modals
├── scraping/
│   ├── selectors.py     # single source of truth for all X selectors
│   ├── extractor.py     # XExtractor — DOM extraction + jitter
│   └── parsing.py       # parse_metric_count, parse_post_id_from_href, …
└── tools/
    ├── feed.py          # FeedTool orchestrator
    └── profile.py       # ProfileTool orchestrator

tests/
├── unit/                # 432 pure unit tests
├── integration/         # Hermetic tests against local HTTP fixtures
└── e2e/                 # Live tests, gated by XCLI_LIVE=1
```

</details>

<br/>

## Limitations & Terms of Service

XCli is a personal-use automation tool. It reads only data your account already sees when browsing normally — no access controls bypassed, no private accounts scraped, no API endpoints called.

X's Terms of Service prohibit automated scraping. Running this against the ToS is solely your responsibility. The authors make no representation that this tool is compliant with X's ToS, robots.txt, or any other platform policy. **Use a throwaway account, keep volume low, and don't run it on accounts you can't afford to lose.**

The tool is rate-limit-aware: it exits cleanly when X shows a soft-block (exit code 3) rather than retrying aggressively. No data is transmitted to any third party — everything lives at `~/.xcli/` (mode `0o700`) and whatever output path you specify.

<br/>

## Acknowledgements

- [Patchright](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright) — the undetected Playwright fork that makes the stealth posture possible
- [Typer](https://typer.tiangolo.com/) — the CLI framework
- Architectural inspiration from [stickerdaniel/linkedin-mcp-server](https://github.com/stickerdaniel/linkedin-mcp-server) — same persistent-context + DOM-only philosophy, ported to a CLI for X

## License

MIT — see [LICENSE](LICENSE).
