# XCli

<p align="left">
  <a href="https://github.com/vermarjun/XCli/blob/main/LICENSE" target="_blank"><img src="https://img.shields.io/badge/License-MIT-%233fb950?labelColor=32383f" alt="License"></a>
  <a href="#"><img src="https://img.shields.io/badge/python-3.12%20%7C%203.13%20%7C%203.14-blue?labelColor=32383f" alt="Python"></a>
</p>

A small CLI that pulls your X (Twitter) home feed and any profile's posts plus threaded comments and writes them as JSON. It drives a real, logged-in Chrome session via [Patchright](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright) (an undetected Playwright fork), so X sees a normal browser, not a script. Built for agents and pipelines: stdout is JSON, stderr is logs, exit codes tell you what went wrong. No private APIs, no XHR injection, no headless tells.

> [!IMPORTANT]
> **Read this before you run anything**
>
> **Will my account get banned?** This tool drives a real browser session that you log into yourself. It doesn't exploit any private API or bypass authentication. That said, X's TOS does prohibit automated scraping, so use a throwaway account, keep volume low, and don't run it on your main. With personal use (a few feed pulls per day, not bulk scraping) you're unlikely to get flagged. So far nobody has.
>
> **What's the difference vs. snscrape, twscrape, or nitter?** Those rely on guest tokens, private GraphQL endpoints, or third party mirrors. They break every few weeks as X rotates `doc_id`s, tightens CSRF, and shuts down nitter instances. XCli reads the rendered DOM from your own logged-in session, so it survives backend changes. The tradeoff: it's slower, and you need to log in once.

| Tool | What it does | Status |
|------|--------------|--------|
| `xcli login` | One time interactive login in a visible Chrome window. Handles 2FA, Arkose captcha, and email challenges manually | working |
| `xcli logout` | Moves the stored session aside (recoverable, not deleted) | working |
| `xcli status` | Checks whether the stored session is still authenticated | working |
| `xcli feed` | Pulls top N posts from your home feed with top Y comments on each | working |
| `xcli profile` | Pulls a user's profile (bio, links, metadata) plus top N posts plus top Y comments on each | working |
| `xcli doctor` | Runs stealth fingerprint checks across five bot detection sites and verifies x.com reachability | working |

<br/>

## 🤖 Built for agents and pipelines

XCli is a CLI so it runs anywhere a shell does: Claude Code, Cursor, Aider, LangChain `ShellTool`, n8n, plain Python `subprocess`, cron jobs. You log in once with your throwaway account and the agent calls the CLI like a function.

The contract is intentionally simple.

* **stdout** is always JSON. Pipe it into `jq`, an LLM, or `json.loads` and you're done.
* **stderr** is progress and logs. It won't pollute the JSON.
* **Exit code** signals failure mode. `0` ok, `2` re-login needed, `3` rate limited (back off), `4` profile not found or suspended or protected, `1` other. The agent decides what to do.
* **Schemas are stable.** Same shape every call. See [Output schemas](#-setup-help) below.

**From a Python agent:**

```python
import json, subprocess

result = subprocess.run(
    ["uv", "run", "xcli", "feed", "-n", "20", "-y", "5", "--headless"],
    capture_output=True, text=True,
)
if result.returncode == 2:
    raise RuntimeError("Session expired. Run `xcli login` once on a human terminal.")
if result.returncode == 3:
    # Rate limited. Back off and retry later.
    ...
data = json.loads(result.stdout)
for post in data["posts"]:
    print(post["author"]["username"], post["metrics"]["likes"])
```

**From a shell agent:**

```bash
# Pipe a freshly scraped timeline into an LLM
xcli feed -n 20 -y 5 | llm -m claude-4.7-opus "Summarize trends and top engagement in this X feed JSON"

# Research a handle and pipe to jq for a quick view
xcli profile elonmusk -n 10 -y 5 | jq '.profile, [.posts[] | {id, likes: .metrics.likes, text}]'
```

**Why not MCP?** A CLI works in any agent runtime, not just MCP-aware clients. If you specifically target Claude Desktop or Cursor and want a warm browser between calls, an MCP wrapper around this CLI is roughly a day of work. The scraper underneath stays the same. Open an issue if you'd like that.

<br/>

## 🚀 Quick start

**What you need before starting:**

* macOS or Linux. Windows is untested but should mostly work.
* A display attached. Headed mode is the default for stealth reasons. You can opt into headless with `--headless` for CI or remote servers, just expect lower stealth.
* A throwaway X account. Don't use your main.
* [uv](https://docs.astral.sh/uv/getting-started/installation/) installed. uv will pull the right Python version automatically; you don't need to install Python yourself.
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```

**Then:**

```bash
# 1. Clone and install
git clone https://github.com/vermarjun/XCli.git
cd XCli
uv sync                              # creates .venv, installs deps from uv.lock
uv run patchright install chromium   # downloads bundled Chromium, about 150 MB

# 2. Log in (opens a visible Chrome window, 5 minute timeout)
uv run xcli login
# Sign in manually. 2FA, Arkose, email codes all work because there's a real human
# at the keyboard. Cookies and profile persist to ~/.xcli/profile (0o700).

# 3. Sanity check the session and stealth posture
uv run xcli status
uv run xcli doctor

# 4. Actually use it
uv run xcli feed --count 10 --comments-per 5 -o feed.json
uv run xcli profile elonmusk --posts 10 --comments-per 5 -o profile.json
```

Output is JSON to stdout by default. Pipe through `jq` or use `-o file.json`. Logs go to stderr so piping stays clean.

> [!NOTE]
> `xcli feed` and `xcli profile` open a visible browser window by default. This is the safest stealth posture because it avoids the three classic headless tells (the `HeadlessChrome` UA, missing WebGL, zero plugins). Add `--headless` only if you have no display, like in CI or Docker.

<br/>

## 🔧 Setup help

<details>
<summary><b>Commands and options</b></summary>

**Common flags on `feed` and `profile`:**

* `-n, --count N` or `--posts N`: number of posts to fetch (1 to 100, default 10)
* `-y, --comments-per N`: comments per post (0 to 50, default 3)
* `-o, --output FILE`: write JSON to file instead of stdout
* `--headless`: force headless mode (default is visible, see stealth notes)
* `--channel CHAN`: `chromium` (default, bundled), `chrome` (installed Chrome, best stealth), `chrome-beta`, `chrome-dev`, `msedge`
* `--jitter-pct F`: fractional jitter on navigation delays (0.0 to 1.0, default 0.2)
* `--no-human-pace`: revert to the old single wheel event scrolling (faster, less human looking)

**Examples:**

```bash
# Best stealth: real installed Chrome, visible window, jittered timing
uv run xcli feed -n 20 -y 5 --channel chrome

# Quiet headless for CI or remote machines
uv run xcli feed -n 5 -y 1 --headless -o /tmp/feed.json

# Profile deep dive
uv run xcli profile TwitterDev -n 10 -y 5 -o td.json
```

</details>

<details>
<summary><b>Environment variables</b></summary>

All flags have env var equivalents. `.env` files are supported via python-dotenv.

| Variable | Default | What it does |
|----------|---------|--------------|
| `XCLI_HEADLESS` | `false` | Default headless mode for feed and profile. The CLI flag overrides this. |
| `XCLI_CHANNEL` | `chromium` | Browser channel. Use `chrome` for the strongest stealth posture. |
| `XCLI_PROFILE_DIR` | `~/.xcli/profile` | Path to the persistent Chromium profile |
| `XCLI_VIEWPORT_WIDTH` | `1920` | Viewport width. Used in headless mode only; headed mode uses the OS window size. |
| `XCLI_VIEWPORT_HEIGHT` | `1080` | Viewport height (headless only) |
| `XCLI_JITTER_PCT` | `0.20` | Jitter applied to nav delays |
| `XCLI_HUMAN_PACE` | `1` | Set to `0` to disable humanized scrolling (tests use this) |
| `XCLI_LOG_LEVEL` | `WARNING` | Python logging level |
| `XCLI_COOKIE_FILE` | (none) | Netscape cookie file to import on login |
| `XCLI_LIVE` | (none) | Set to `1` to enable live e2e tests |

</details>

<details>
<summary><b>Output schemas</b></summary>

**`xcli feed`** returns `{captured_at, feed_account, count_*, posts: [...], warnings}`.

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

**`xcli profile`** returns `{captured_at, username, url, profile, posts, warnings}`.

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

**Exit codes:** `0` ok, `1` generic error, `2` auth (`xcli login` needed), `3` rate limited, `4` profile not found, suspended, or protected.

</details>

<details>
<summary><b>Troubleshooting</b></summary>

**`xcli doctor` flags WebGL, Plugins, and Chrome as critical fails.** Those are inherent to headless Chromium. Run feed or profile in headed mode (the default) or with `--channel chrome` to clear them.

**`x.com/home` returns a soft block ("Something went wrong").** Wait 30 seconds and retry. The tool exits with code 3 rather than hammering X.

**Session expired.** Re-run `xcli login`. The old profile is moved aside to `~/.xcli-invalid-<ts>/` so you can recover it if needed.

**A visible browser window pops up.** That's the default and it's intentional for stealth. Add `--headless` to suppress it.

**Patchright Chromium download failed.** Try `uv run patchright install chromium --with-deps`.

</details>

<br/>

## 🥷 How it stays undetected

1. **[Patchright](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright)** is a maintained Playwright fork that patches Chromium's automation tells. `navigator.webdriver` is `undefined`, there's no CDP runtime fingerprint, and the chrome-runtime injector is patched out. We don't write any of this ourselves.

2. **Persistent profile.** `~/.xcli/profile/` is a real on-disk Chromium user-data directory. Cookies, localStorage, IndexedDB, and your auth tokens (`auth_token`, `ct0`) all survive across runs. To X, this looks like the same Chrome returning.

3. **Headed by default.** `xcli feed` and `xcli profile` open a visible window. Headless mode produces three classic bot tells (the `HeadlessChrome` UA, "Canvas has no WebGL context", and zero plugins). Running headed kills all three at the source.

4. **`--channel chrome` for max stealth.** Uses your installed Google Chrome instead of bundled Chromium, restoring real GPU-accelerated WebGL, real plugins, and a non-HeadlessChrome UA even when run headless.

5. **DOM only, never API.** Reads rendered `innerText` and `data-testid` selectors (X's own e2e test hooks). No private GraphQL, no XHR replay, no guest tokens. When X rotates `doc_id`s it doesn't break us.

6. **Humanized scrolling.** Each scroll burst is 7 to 24 wheel events with calibrated delta sizes and timing gaps drawn from trackpad and mouse profiles. About 10% of bursts include an upward overshoot (real users scroll past and correct). Read pauses between bursts are tagged by intent: browse, deep, or skim.

7. **Maximized window.** Headed mode launches with `--start-maximized` and `no_viewport=True` so the page uses the real OS window size, not a fixed 1280×720 render rectangle that screams "automation".

8. **Boundary detection.** Comment scrapes stop at the "Discover more" recommendation section so unrelated tweets never leak into the comments array.

<br/>

## 🐍 Development

<details>
<summary><b>Local dev setup</b></summary>

```bash
# Install dev dependencies (pre-commit, ruff, pytest-cov, etc.)
uv sync --all-extras

# Fast feedback: unit and integration tests, no coverage gate
uv run pytest tests/unit tests/integration -q

# With coverage gate (>=80%)
uv run pytest tests/unit tests/integration --cov=xcli --cov-fail-under=80 -q

# Lint and format
uv run ruff check . && uv run ruff format .

# Pre-commit hooks (ruff plus a selector-leak grep)
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
├── cli.py               # Typer app: all commands and async wrappers
├── config.py            # BrowserConfig and env var loading
├── checks.py            # Bot detection checks (5 fingerprint sites + x.com reachability)
├── session_state.py     # Profile-dir and cookie-path helpers
├── core/
│   ├── auth.py          # is_logged_in, detect_rate_limit, warm_up_browser
│   ├── browser.py       # BrowserManager (Patchright wrapper)
│   ├── human.py         # Humanized wheel bursts and read pauses
│   └── utils.py         # capture_as_you_scroll, dismiss_modals
├── scraping/
│   ├── selectors.py     # Single source of truth for all X selectors
│   ├── extractor.py     # XExtractor: DOM extraction + jitter
│   └── parsing.py       # parse_metric_count, parse_post_id_from_href, etc.
└── tools/
    ├── feed.py          # FeedTool orchestrator
    └── profile.py       # ProfileTool orchestrator

tests/
├── unit/                # Pure unit tests, no browser
├── integration/         # Hermetic tests against local HTTP fixtures
└── e2e/                 # Live tests, gated by XCLI_LIVE=1
```

</details>

<br/>

## Limitations and Terms of Service

XCli is a personal use automation tool. It reads only data your account already sees when browsing normally. No access controls are bypassed, no private accounts are scraped, no API endpoints are called.

X's Terms of Service do prohibit automated scraping. Running this against the ToS is your responsibility. The authors make no representation that this tool is compliant with X's ToS, robots.txt, or any other platform policy. Use a throwaway account, keep volume low, and don't run it on accounts you can't afford to lose.

The tool is rate-limit aware. It exits cleanly when X shows a soft block (exit code 3) rather than retrying aggressively. No data is transmitted to any third party. Everything lives at `~/.xcli/` (mode `0o700`) and whatever output path you specify.

<br/>

## Acknowledgements

* [Patchright](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright), the undetected Playwright fork that makes the stealth posture possible.
* [Typer](https://typer.tiangolo.com/), the CLI framework.
* Architectural inspiration from [stickerdaniel/linkedin-mcp-server](https://github.com/stickerdaniel/linkedin-mcp-server). Same persistent-context, DOM-only philosophy, ported to a CLI for X.

## License

MIT. See [LICENSE](LICENSE).
