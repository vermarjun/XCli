"""XExtractor — high-level DOM extraction for X.com timelines and profiles.

Implements:
- XExtractor.fetch_feed(count, comments_per) → feed dict
- XExtractor.fetch_thread_comments(url, y) → list of reply dicts

Phase 2 will add:
- XExtractor.research_profile(username, posts, comments_per) → profile dict

URL override strategy for integration tests:
    Use ``page.route()`` to intercept x.com requests and respond with local
    fixture HTML. This is more realistic than base-URL patching because it
    exercises the actual Playwright navigation flow. An optional attribute
    ``_test_only_base_url_override`` (str | None, default None) is also
    provided as a fallback for simpler test setups; when set it replaces
    ``https://x.com`` in all goto calls. NEVER set this in production code.
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

from patchright.async_api import Page
from patchright.async_api import TimeoutError as PlaywrightTimeoutError

from xcli.common_utils import utcnow_iso
from xcli.core.auth import (
    _is_auth_blocker_url,
    detect_auth_barrier_quick,
    detect_rate_limit,
)
from xcli.core.utils import capture_as_you_scroll, dismiss_modals
from xcli.exceptions import AuthenticationError, RateLimitError
from xcli.scraping.parsing import (
    extract_links_from_anchors,
    parse_human_timestamp,
    parse_iso_datetime,
    parse_join_date,
    parse_metric_count,
    parse_post_id_from_href,
    parse_username_from_avatar_testid,
    parse_username_from_status_href,
)
from xcli.scraping.selectors import (
    ACCOUNT_SWITCHER_BUTTON,
    AD_INDICATOR,
    APP_TAB_BAR_PROFILE_LINK,
    EMPTY_STATE_HEADER,
    LOGIN_BUTTON,
    PRIMARY_COLUMN,
    PROFILE_DESCRIPTION,
    PROFILE_ERROR_LABELS,
    PROFILE_FOLLOWERS_LINK,
    PROFILE_FOLLOWING_LINK,
    PROFILE_JOIN_DATE,
    PROFILE_LOCATION,
    PROFILE_URL_FIELD,
    PROFILE_USER_NAME,
    RESERVED_HANDLE_PATHS,
    SOCIAL_CONTEXT,
    TIMELINE_CELL,
    TWEET_ARTICLE,
    TWEET_BOOKMARK_BTN,
    TWEET_LIKE_BTN,
    TWEET_MEDIA_PHOTO,
    TWEET_MEDIA_VIDEO,
    TWEET_REPLY_BTN,
    TWEET_REPOST_BTN,
    TWEET_STATUS_LINK,
    TWEET_TEXT,
    TWEET_USER_AVATAR_ANY,
    TWEET_USER_NAME_BLOCK,
    TWEET_VIEW_COUNT_LINK,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

NAV_DELAY: float = 2.0  # seconds between navigations (stealth pacing)
RATE_LIMIT_RETRY_DELAY: float = 5.0  # seconds to back off on soft rate-limit


# ---------------------------------------------------------------------------
# Jitter helper
# ---------------------------------------------------------------------------


def _jitter(base: float, pct: float) -> float:
    """Apply uniform random jitter to a base delay.

    Returns ``base * (1 + uniform(-pct, pct))``, clamped to a minimum of 0.0.

    Args:
        base: Base delay in seconds.
        pct:  Fractional jitter factor (0.0 = no jitter, 0.2 = ±20%).
              Must be in [0.0, 1.0] — callers are responsible for validation.

    Examples:
        _jitter(2.0, 0.0)  → 2.0 (exactly)
        _jitter(1.0, 0.2)  → value in [0.8, 1.2]
        _jitter(2.0, 1.0)  → value in [0.0, 4.0]
    """
    if pct == 0.0:
        return base
    factor = 1.0 + random.uniform(-pct, pct)
    return max(0.0, base * factor)


# ---------------------------------------------------------------------------
# JavaScript for extracting visible tweets (one page.evaluate per scroll)
# ---------------------------------------------------------------------------
# This JS is defensive — every access uses ?. and falls back to empty string
# because virtualized DOMs can have half-rendered nodes.

_EXTRACT_TWEETS_JS = r"""
({ articleSelector, tweetTextSelector, userNameSelector,
   avatarSelector, statusLinkSelector, replyBtnSelector,
   retweetBtnSelector, likeBtnSelector, bookmarkBtnSelector,
   viewCountLinkSelector, mediaPhotoSelector, mediaVideoSelector,
   adIndicatorSelector, socialContextSelector, cellSelector }) => {
  const normalize = v => (v || '').replace(/\s+/g, ' ').trim();
  const articles = Array.from(document.querySelectorAll(articleSelector));

  return articles.map(article => {
    try {
      // --- IDs and URLs ---
      const statusLinks = Array.from(
        article.querySelectorAll(statusLinkSelector)
      );
      let statusHref = '';
      for (const a of statusLinks) {
        const h = a.getAttribute('href') || '';
        if (/\/status\/\d+/.test(h)) { statusHref = h; break; }
      }

      // --- Username from avatar testid (most reliable in-tweet source) ---
      const avatarEl = article.querySelector(avatarSelector);
      const avatarTestid = avatarEl
        ? (avatarEl.getAttribute('data-testid') || '')
        : '';

      // --- Display name + handle from User-Name block ---
      const nameBlock = article.querySelector(userNameSelector);
      let displayName = '';
      let handle = '';
      if (nameBlock) {
        const spans = Array.from(nameBlock.querySelectorAll('span'));
        // First non-empty span that isn't an at-handle is the display name
        for (const sp of spans) {
          const t = normalize(sp.innerText || sp.textContent);
          if (t && !t.startsWith('@') && !displayName) displayName = t;
          if (t && t.startsWith('@') && !handle) handle = t.slice(1);
        }
        if (!displayName) displayName = normalize(nameBlock.innerText || '');
      }

      // --- Verified badge: look for aria-label on checkmark SVG ---
      let verified = false;
      const svgs = article.querySelectorAll('svg[aria-label]');
      for (const svg of svgs) {
        const lbl = (svg.getAttribute('aria-label') || '').toLowerCase();
        if (lbl.includes('verified') || lbl.includes('blue checkmark') ||
            lbl.includes('gold checkmark') || lbl.includes('checkmark')) {
          verified = true;
          break;
        }
      }

      // --- Tweet text ---
      const textEl = article.querySelector(tweetTextSelector);
      const text = textEl ? normalize(textEl.innerText || textEl.textContent) : '';

      // --- Full article innerText (for LLM consumption) ---
      const innertext = normalize(article.innerText || '');

      // --- Time (multi-source fallback for headless hydration delays) ---
      const timeEl = article.querySelector('time');  // any <time>, not requiring datetime attr
      const postedAtIso   = timeEl ? (timeEl.getAttribute('datetime') || '') : '';
      const postedAtAria  = timeEl ? (timeEl.getAttribute('aria-label') || '') : '';
      const postedAtTitle = timeEl ? (timeEl.getAttribute('title') || '') : '';
      const postedAtText  = timeEl ? (timeEl.innerText || timeEl.textContent || '') : '';

      // --- Metrics (from aria-label on action buttons) ---
      const getAriaNum = sel => {
        const el = article.querySelector(sel);
        return el ? (el.getAttribute('aria-label') || '') : '';
      };
      const replyLabel    = getAriaNum(replyBtnSelector);
      const retweetLabel  = getAriaNum(retweetBtnSelector);
      const likeLabel     = getAriaNum(likeBtnSelector);
      const bookmarkLabel = getAriaNum(bookmarkBtnSelector);
      const viewsEl = article.querySelector(viewCountLinkSelector);
      const viewsLabel = viewsEl
        ? (viewsEl.getAttribute('aria-label') || viewsEl.innerText || '') : '';

      // --- Links (anchors with status or external URLs) ---
      const anchors = Array.from(article.querySelectorAll('a[href]'))
        .filter(a => {
          const h = a.getAttribute('href') || '';
          return h && h !== '#' && !h.startsWith('/i/');
        })
        .map(a => ({
          href: a.href || a.getAttribute('href') || '',
          aria_label: a.getAttribute('aria-label') || '',
          expanded_url: a.dataset ? (a.dataset.expandedUrl || '') : '',
          text: normalize(a.innerText || a.textContent),
          source: 'tweet',
        }));

      // --- Media ---
      const hasPhoto = article.querySelector(mediaPhotoSelector) !== null;
      const hasVideo = article.querySelector(mediaVideoSelector) !== null;

      // --- Repost (socialContext above article contains repost icon) ---
      // socialContext is a sibling of the article's parent or inside the cell
      const cell = article.closest(cellSelector);
      const socialCtx = cell ? cell.querySelector(socialContextSelector) : null;
      const socialCtxText = socialCtx ? normalize(socialCtx.innerText || '') : '';
      // Repost indicator: contains "Reposted" or a repost icon label
      const isRepost = socialCtxText.toLowerCase().includes('repost') ||
                       socialCtxText.toLowerCase().includes('retweeted');
      const repostedBy = isRepost ? socialCtxText : null;

      // --- Ad detection (structural, locale-independent) ---
      const isAd = article.querySelector(adIndicatorSelector) !== null;

      return {
        statusHref,
        avatarTestid,
        displayName,
        handle,
        verified,
        text,
        innertext,
        postedAtIso,
        postedAtAria,
        postedAtTitle,
        postedAtText,
        replyLabel,
        retweetLabel,
        likeLabel,
        bookmarkLabel,
        viewsLabel,
        anchors,
        hasPhoto,
        hasVideo,
        isRepost,
        repostedBy,
        isAd,
      };
    } catch (err) {
      // Half-rendered node — return minimal sentinel so Python can skip it
      return { statusHref: '', avatarTestid: '', error: String(err) };
    }
  });
}
"""

# JS for waiting until at least one article has a time[datetime] element.
# Takes the article selector as argument so the string stays in selectors.py.
_WAIT_FOR_TIME_JS = """
(articleSelector) => {
    const articles = document.querySelectorAll(articleSelector);
    for (const a of articles) {
        if (a.querySelector('time[datetime]')) return true;
    }
    return false;
}
"""

# JS argument dict for selector injection — built once at module level
_JS_SELECTORS: dict[str, str] = {
    "articleSelector": TWEET_ARTICLE,
    "tweetTextSelector": TWEET_TEXT,
    "userNameSelector": TWEET_USER_NAME_BLOCK,
    "avatarSelector": TWEET_USER_AVATAR_ANY,
    "statusLinkSelector": TWEET_STATUS_LINK,
    "replyBtnSelector": TWEET_REPLY_BTN,
    "retweetBtnSelector": TWEET_REPOST_BTN,
    "likeBtnSelector": TWEET_LIKE_BTN,
    "bookmarkBtnSelector": TWEET_BOOKMARK_BTN,
    "viewCountLinkSelector": TWEET_VIEW_COUNT_LINK,
    "mediaPhotoSelector": TWEET_MEDIA_PHOTO,
    "mediaVideoSelector": TWEET_MEDIA_VIDEO,
    "adIndicatorSelector": AD_INDICATOR,
    "socialContextSelector": SOCIAL_CONTEXT,
    "cellSelector": TIMELINE_CELL,
}


# ---------------------------------------------------------------------------
# Helper: build a structured tweet record from raw JS output
# ---------------------------------------------------------------------------


def _build_tweet_record(raw: dict) -> dict | None:
    """Convert a raw JS extraction dict into a clean Python record.

    Returns None if the record is missing the ID (half-rendered or error node).
    """
    status_href: str = raw.get("statusHref") or ""
    tweet_id = parse_post_id_from_href(status_href)
    if not tweet_id:
        return None

    # Build the canonical tweet URL
    avatar_testid: str = raw.get("avatarTestid") or ""
    username_from_avatar = parse_username_from_avatar_testid(avatar_testid)
    username_from_href = parse_username_from_status_href(status_href)
    username = username_from_avatar or username_from_href or ""

    url = f"https://x.com{status_href}" if status_href.startswith("/") else status_href

    # Metrics — parse raw aria-label strings
    metrics = {
        "replies": parse_metric_count(raw.get("replyLabel")),
        "reposts": parse_metric_count(raw.get("retweetLabel")),
        "likes": parse_metric_count(raw.get("likeLabel")),
        "bookmarks": parse_metric_count(raw.get("bookmarkLabel")),
        "views": parse_metric_count(raw.get("viewsLabel")),
    }

    # Links — deduplicate via our parsing helper
    raw_anchors: list[dict] = raw.get("anchors") or []
    links = extract_links_from_anchors(raw_anchors)

    # Media
    media: list[dict] = []
    if raw.get("hasPhoto"):
        media.append({"kind": "image", "url": None})
    if raw.get("hasVideo"):
        # Only add video if not already covered by photo
        if not raw.get("hasPhoto"):
            media.append({"kind": "video", "url": None})

    # Timestamp: try multiple sources in priority order
    posted_at = (
        parse_iso_datetime(raw.get("postedAtIso"))
        or parse_human_timestamp(raw.get("postedAtAria"))
        or parse_human_timestamp(raw.get("postedAtTitle"))
        or None
    )
    posted_at_text = (
        raw.get("postedAtAria") or raw.get("postedAtTitle") or raw.get("postedAtText") or ""
    ).strip() or None

    return {
        "id": tweet_id,
        "url": url,
        "author": {
            "username": username,
            "display_name": raw.get("displayName") or "",
            "verified": bool(raw.get("verified")),
        },
        "text": raw.get("text") or "",
        "innertext": raw.get("innertext") or "",
        "posted_at": posted_at,
        "posted_at_text": posted_at_text,
        "metrics": metrics,
        "links": links,
        "media": media,
        "is_repost": bool(raw.get("isRepost")),
        "reposted_by": raw.get("repostedBy"),
        "is_ad": bool(raw.get("isAd")),
    }


# ---------------------------------------------------------------------------
# Module-level helper: read logged-in handle from account switcher
# ---------------------------------------------------------------------------

_READ_HANDLE_JS = """
(args) => {
    const { accountSwitcherSelector, profileLinkSelector, reservedPaths } = args;
    const HANDLE_RE = /^(?:https?:\\/\\/[^\\/]+)?\\/([A-Za-z0-9_]{1,15})\\/?$/;
    const reservedSet = new Set(reservedPaths);

    function extractFromHref(href) {
        if (!href) return null;
        // Strip query/fragment
        const clean = href.split('?')[0].split('#')[0];
        const m = HANDLE_RE.exec(clean);
        if (!m) return null;
        const candidate = m[1];
        if (reservedSet.has(candidate.toLowerCase())) return null;
        return candidate;
    }

    // 1. Account switcher aria-label: "Account switcher @handle" or similar
    const switcherEl = document.querySelector(accountSwitcherSelector);
    if (switcherEl) {
        const label = switcherEl.getAttribute('aria-label') || '';
        const atMatch = label.match(/@([A-Za-z0-9_]{1,15})/);
        if (atMatch) return atMatch[1];
    }

    // 2. AppTabBar Profile Link href
    const profileLinkEl = document.querySelector(profileLinkSelector);
    if (profileLinkEl) {
        const href = profileLinkEl.getAttribute('href') || '';
        const handle = extractFromHref(href);
        if (handle) return handle;
    }

    // 3. Any aside a[href^="/"] matching handle pattern
    const asideAnchors = Array.from(document.querySelectorAll('aside a[href^="/"]'));
    for (const a of asideAnchors) {
        const handle = extractFromHref(a.getAttribute('href') || '');
        if (handle) return handle;
    }

    // 4. Any header a[href^="/"] matching handle pattern
    const headerAnchors = Array.from(document.querySelectorAll('header a[href^="/"]'));
    for (const a of headerAnchors) {
        const handle = extractFromHref(a.getAttribute('href') || '');
        if (handle) return handle;
    }

    // 5. UserAvatar testid inside nav (left-rail context, not tweet body)
    const navAvatars = Array.from(
        document.querySelectorAll('nav [data-testid^="UserAvatar-Container-"]')
    );
    for (const el of navAvatars) {
        const testid = el.getAttribute('data-testid') || '';
        const suffix = testid.replace('UserAvatar-Container-', '');
        const validHandle = /^[A-Za-z0-9_]{1,15}$/.test(suffix);
        if (suffix && validHandle && !reservedSet.has(suffix.toLowerCase())) {
            return suffix;
        }
    }

    return '';
}
"""


async def read_authenticated_handle(page: Page) -> str | None:
    """Read the logged-in user's handle using a multi-step fallback chain.

    Tries in order:
    1. Aria-label of the account-switcher button (collapsed in headless mode).
    2. href of AppTabBar_Profile_Link.
    3. href of any ``aside a[href^="/"]`` that looks like a handle.
    4. href of any ``header a[href^="/"]`` that looks like a handle.
    5. UserAvatar testid inside a ``nav`` element (left-rail context).

    Reserved URL paths (``/home``, ``/explore``, etc.) are excluded via
    ``RESERVED_HANDLE_PATHS``.

    Args:
        page: Active Patchright page (must be on an authenticated X page).

    Returns:
        The handle string (without leading ``@``), or ``None`` if not found.
    """
    try:
        result = await page.evaluate(
            _READ_HANDLE_JS,
            {
                "accountSwitcherSelector": ACCOUNT_SWITCHER_BUTTON,
                "profileLinkSelector": APP_TAB_BAR_PROFILE_LINK,
                "reservedPaths": list(RESERVED_HANDLE_PATHS),
            },
        )
        if isinstance(result, str) and result:
            return result
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# XExtractor
# ---------------------------------------------------------------------------


class XExtractor:
    """High-level DOM extractor for X.com.

    Wraps a Patchright ``Page`` and provides async methods to scrape
    authenticated X content. All methods assume the page belongs to an
    authenticated session; call ``ensure_authenticated()`` from
    ``drivers.browser`` before constructing this object.

    Test-only attribute: ``_test_only_base_url_override``
        When set (str), replaces ``https://x.com`` in all goto calls.
        NEVER set this in production code. Prefer ``page.route()``
        interception in integration tests for more realistic coverage.
    """

    def __init__(self, page: Page, *, jitter_pct: float = 0.0) -> None:
        """Initialise XExtractor.

        Args:
            page:       Active Patchright page (must belong to an authenticated session).
            jitter_pct: Fractional jitter applied to ``NAV_DELAY`` sleeps.
                        Default is 0.0 (no jitter) so integration tests stay
                        fully deterministic.  Production tools pass the config
                        or CLI-override value here.
        """
        self._page = page
        self._jitter_pct: float = jitter_pct
        # Test-only: replaces https://x.com with a local server base URL.
        # Set in integration tests; always None in production.
        self._test_only_base_url_override: str | None = None

    def _resolve_url(self, url: str) -> str:
        """Apply base-URL override for tests (no-op in production)."""
        if self._test_only_base_url_override:
            return url.replace("https://x.com", self._test_only_base_url_override)
        return url

    # ------------------------------------------------------------------
    # _goto_with_auth_checks
    # ------------------------------------------------------------------

    async def _goto_with_auth_checks(
        self,
        url: str,
        *,
        wait_until: str = "domcontentloaded",
    ) -> None:
        """Navigate to a URL and fail fast on auth barriers or rate limits.

        Mirrors LinkedIn's ``_goto_with_auth_checks`` pattern, adapted for X:
        1. page.goto with 30 s timeout.
        2. Check if the resulting URL is an auth-blocker path.
        3. Check for a login button on the page.
        4. Run detect_rate_limit.

        Raises:
            AuthenticationError: On auth barrier.
            RateLimitError: On rate-limit or soft-block.
        """
        resolved_url = self._resolve_url(url)
        try:
            await self._page.goto(resolved_url, wait_until=wait_until, timeout=30000)
        except PlaywrightTimeoutError:
            logger.warning("Navigation timeout for %s — continuing with partial load", url)
        except Exception as e:
            logger.debug("Navigation error for %s: %s", url, e)
            # Check if we were redirected to an auth barrier before raising
            current = self._page.url
            if _is_auth_blocker_url(current):
                raise AuthenticationError(
                    f"Session expired (redirected to {current}). Run `xcli login`."
                ) from e
            raise

        # Check resulting URL
        current = self._page.url
        if _is_auth_blocker_url(current):
            raise AuthenticationError(
                f"Session expired (redirected to {current}). Run `xcli login`."
            )

        # Quick barrier check (URL + title, no body fetch — fast)
        barrier = await detect_auth_barrier_quick(self._page)
        if barrier:
            raise AuthenticationError(
                f"Authentication barrier detected: {barrier}. Run `xcli login`."
            )

        # Login button present on a page we expected to be authenticated
        try:
            if await self._page.locator(LOGIN_BUTTON).count() > 0:
                raise AuthenticationError(
                    "Login wall detected. Session may have expired. Run `xcli login`."
                )
        except AuthenticationError:
            raise
        except Exception:
            pass

        # Rate-limit / soft-block check
        await detect_rate_limit(self._page)

    # ------------------------------------------------------------------
    # _extract_visible_tweets
    # ------------------------------------------------------------------

    async def _extract_visible_tweets(
        self,
        *,
        scope_selector: str,
    ) -> list[dict]:
        """Extract all currently visible tweet records from the DOM.

        Runs ONE page.evaluate call that iterates all tweet article elements
        (``TWEET_ARTICLE`` selector) within ``scope_selector``.
        Returns a list of structured dicts ready for ``_build_tweet_record``.
        """
        try:
            raw_list: list[dict[str, Any]] = await self._page.evaluate(
                _EXTRACT_TWEETS_JS,
                _JS_SELECTORS,
            )
        except Exception as e:
            logger.debug("page.evaluate error in _extract_visible_tweets: %s", e)
            return []

        records: list[dict] = []
        for raw in raw_list:
            if raw.get("error"):
                logger.debug("Skipping half-rendered tweet node: %s", raw["error"])
                continue
            record = _build_tweet_record(raw)
            if record:
                records.append(record)
        return records

    # ------------------------------------------------------------------
    # fetch_feed
    # ------------------------------------------------------------------

    async def fetch_feed(self, count: int, comments_per: int) -> dict:
        """Fetch the authenticated user's home feed.

        Args:
            count:        Number of posts to collect (ads excluded).
            comments_per: Number of top reply comments to fetch per post.

        Returns:
            Feed dict matching the plan §4.1 output schema.

        Raises:
            AuthenticationError: If session is expired or login wall is hit.
            RateLimitError: If hard-blocked at /account/access (propagated up).
        """
        warnings: list[str] = []

        # 1. Navigate to home feed
        await self._goto_with_auth_checks(self._resolve_url("https://x.com/home"))

        # 2. Wait for primary column
        try:
            await self._page.wait_for_selector(PRIMARY_COLUMN, timeout=15000)
        except PlaywrightTimeoutError:
            logger.warning("primaryColumn did not appear; continuing anyway")
            warnings.append("primaryColumn did not appear within 15s — page may be partial")

        # 3. Dismiss modals, check rate limit
        await dismiss_modals(self._page)
        await detect_rate_limit(self._page)

        # 3b. Wait for at least one article with a time[datetime] to hydrate
        try:
            await self._page.wait_for_function(
                _WAIT_FOR_TIME_JS,
                arg=TWEET_ARTICLE,
                timeout=5000,
            )
        except PlaywrightTimeoutError:
            logger.debug("No article with time[datetime] appeared within 5s; continuing")

        # 4. Capture-as-you-scroll
        scope = PRIMARY_COLUMN

        async def _extract(p: Page) -> list[dict]:
            return await self._extract_visible_tweets(scope_selector=scope)

        raw_posts = await capture_as_you_scroll(
            self._page,
            extract_fn=_extract,
            target=count + 10,  # over-fetch to compensate for ad filtering
            max_scrolls=15,
            max_stale=3,
            wheel_delta=1500,
            pause_seconds=1.0,
        )

        # 5. Filter ads, truncate to count
        posts = [p for p in raw_posts if not p.get("is_ad")][:count]

        # 6. Fetch feed_account handle from account-switcher aria-label
        feed_account: str | None = None
        try:
            feed_account = await read_authenticated_handle(self._page)
        except Exception:
            warnings.append("Could not read feed_account handle from account switcher")

        # 7. Fetch comments for each post
        for post in posts:
            post_url = post.get("url") or ""
            if not post_url or not comments_per:
                post["comments"] = []
                post["comments_captured"] = 0
                post["comments_partial"] = False
                continue

            await asyncio.sleep(_jitter(NAV_DELAY, self._jitter_pct))
            try:
                comments = await self.fetch_thread_comments(post_url, comments_per)
                post["comments"] = comments
                post["comments_captured"] = len(comments)
                post["comments_partial"] = len(comments) < comments_per
            except RateLimitError as e:
                logger.warning(
                    "RateLimitError fetching comments for %s: %s — skipping comments",
                    post_url,
                    e,
                )
                warnings.append(
                    f"Rate limited fetching comments for post {post['id']} — comments skipped"
                )
                post["comments"] = []
                post["comments_captured"] = 0
                post["comments_partial"] = True
            except AuthenticationError:
                # Auth errors propagate — can't recover without a new login
                raise
            except Exception as e:
                logger.warning("Error fetching comments for %s: %s", post_url, e)
                warnings.append(f"Error fetching comments for post {post['id']}: {e}")
                post["comments"] = []
                post["comments_captured"] = 0
                post["comments_partial"] = True

        # 8. Build output schema
        return {
            "captured_at": utcnow_iso(),
            "feed_account": feed_account,
            "count_requested": count,
            "count_captured": len(posts),
            "comments_per_requested": comments_per,
            "posts": posts,
            "warnings": warnings,
        }

    # ------------------------------------------------------------------
    # fetch_thread_comments
    # ------------------------------------------------------------------

    async def fetch_thread_comments(self, post_url: str, y: int) -> list[dict]:
        """Fetch up to ``y`` top-level reply comments for a tweet thread.

        Args:
            post_url: Canonical tweet URL (``https://x.com/<user>/status/<id>``).
            y:        Maximum number of reply records to return.

        Returns:
            List of reply dicts (same schema as feed posts, minus nested comments).
        """
        if not y:
            return []

        resolved_url = self._resolve_url(post_url)

        # 1. Navigate to the thread page
        await self._goto_with_auth_checks(resolved_url)

        # 2. Wait for primary column and the OP tweet
        try:
            await self._page.wait_for_selector(PRIMARY_COLUMN, timeout=15000)
        except PlaywrightTimeoutError:
            logger.warning("primaryColumn not found on thread page %s", post_url)

        # 2b. Wait for at least one article with a time[datetime] to hydrate
        try:
            await self._page.wait_for_function(
                _WAIT_FOR_TIME_JS,
                arg=TWEET_ARTICLE,
                timeout=5000,
            )
        except PlaywrightTimeoutError:
            logger.debug(
                "No article with time[datetime] appeared within 5s on thread page; continuing"
            )

        # 3. Read the OP tweet's id to use as skip_first_id
        op_id: str | None = None
        try:
            op_articles = await self._page.query_selector_all(TWEET_ARTICLE)
            if op_articles:
                op_el = op_articles[0]
                # Find any status link in the first article
                links = await op_el.query_selector_all('a[href*="/status/"]')
                for lnk in links:
                    href = await lnk.get_attribute("href") or ""
                    op_id = parse_post_id_from_href(href)
                    if op_id:
                        break
        except Exception as e:
            logger.debug("Could not determine OP tweet id: %s", e)

        # 4. Capture-as-you-scroll — skip OP, collect replies
        scope = PRIMARY_COLUMN

        async def _extract(p: Page) -> list[dict]:
            return await self._extract_visible_tweets(scope_selector=scope)

        max_scrolls = max(5, y * 2)
        raw_replies = await capture_as_you_scroll(
            self._page,
            extract_fn=_extract,
            target=y + 5,  # over-fetch for ad/placeholder filtering
            max_scrolls=max_scrolls,
            max_stale=3,
            skip_first_id=op_id,
        )

        # 5. Filter: remove ads and "Show more replies" placeholder rows
        # A placeholder row has no tweetText AND no media AND no meaningful text
        def _is_placeholder(rec: dict) -> bool:
            if rec.get("is_ad"):
                return True
            text = (rec.get("text") or "").strip()
            media = rec.get("media") or []
            innertext = (rec.get("innertext") or "").strip()
            # If very short innertext and no text/media it's likely a separator row
            if not text and not media and len(innertext) < 10:
                return True
            return False

        replies = [r for r in raw_replies if not _is_placeholder(r)][:y]

        # Strip nested comment fields that don't apply to reply records
        for reply in replies:
            reply.pop("comments", None)
            reply.pop("comments_captured", None)
            reply.pop("comments_partial", None)

        return replies

    # ------------------------------------------------------------------
    # _detect_profile_error
    # ------------------------------------------------------------------

    async def _detect_profile_error(self, username: str) -> str | None:
        """Detect profile-level error states (not_found, suspended, protected).

        Detection is structural/URL-first; text matching is a final fallback
        using a per-locale label table (English-only in v1 — documented
        limitation in PROFILE_ERROR_LABELS).

        Args:
            username: The handle being looked up (used for not_found URL check).

        Returns:
            One of ``"not_found"``, ``"suspended"``, ``"protected"``, or
            ``None`` if the profile appears normal.
        """
        labels = PROFILE_ERROR_LABELS.get("en", {})
        try:
            body_text: str = await self._page.evaluate("() => document.body.innerText || ''")
        except Exception:
            body_text = ""

        # --- Suspended: title or body contains the suspended marker ---
        try:
            title: str = await self._page.evaluate("() => document.title || ''")
        except Exception:
            title = ""

        suspended_markers = labels.get("suspended", ())
        for marker in suspended_markers:
            if marker in title or marker in body_text:
                return "suspended"

        # --- Not found: EMPTY_STATE_HEADER present + body contains not_found text ---
        try:
            empty_state_count: int = await self._page.evaluate(
                f"() => document.querySelectorAll('{EMPTY_STATE_HEADER}').length"
            )
        except Exception:
            empty_state_count = 0

        if empty_state_count > 0:
            not_found_markers = labels.get("not_found", ())
            for marker in not_found_markers:
                if marker in body_text:
                    return "not_found"

        # --- Protected: body text contains protected marker AND no tweets ---
        protected_markers = labels.get("protected", ())
        for marker in protected_markers:
            if marker in body_text:
                # Also verify there are no tweets (profile header still visible but timeline locked)
                try:
                    tweet_count: int = await self._page.evaluate(
                        f"() => document.querySelectorAll('{TWEET_ARTICLE}').length"
                    )
                except Exception:
                    tweet_count = 0
                if tweet_count == 0:
                    return "protected"

        return None

    # ------------------------------------------------------------------
    # _profile_error_result
    # ------------------------------------------------------------------

    def _profile_error_result(
        self,
        url: str,
        username: str,
        error_kind: str,
        captured_at: str,
    ) -> dict:
        """Build a well-formed result dict for a profile error state.

        The result has the same top-level shape as a normal research_profile
        result, but with null profile fields and an appropriate warning.  The
        CLI layer translates any truthy not_found/suspended/protected flag to
        exit code 4.
        """
        canonical_url = url if url.endswith("/") else url + "/"
        return {
            "captured_at": captured_at,
            "username": username,
            "url": canonical_url,
            "profile": {
                "display_name": None,
                "handle": f"@{username}",
                "bio": None,
                "bio_innertext": None,
                "verified": False,
                "verified_kind": None,
                "location": None,
                "website": None,
                "joined": None,
                "joined_iso": None,
                "following_count": None,
                "followers_count": None,
                "links": [],
                "protected": error_kind == "protected",
                "suspended": error_kind == "suspended",
                "not_found": error_kind == "not_found",
            },
            "posts": [],
            "warnings": [f"Profile error: {error_kind}"],
        }

    # ------------------------------------------------------------------
    # _extract_profile_block
    # ------------------------------------------------------------------

    # JS selectors injected into _EXTRACT_PROFILE_JS at call time
    _EXTRACT_PROFILE_JS = r"""
    ({ userNameSelector, descriptionSelector, urlFieldSelector,
       locationSelector, joinDateSelector, followersSelector,
       followingSelector }) => {
      const normalize = v => (v || '').replace(/\s+/g, ' ').trim();

      // --- display name + handle ---
      // Strategy 1: iterate all text nodes / spans directly (most reliable —
      // inline spans may not produce newlines in innerText without CSS).
      let displayName = null;
      let handle = null;
      const nameBlock = document.querySelector(userNameSelector);
      if (nameBlock) {
        // Walk all leaf text nodes and span text content
        const walker = document.createTreeWalker(
          nameBlock, NodeFilter.SHOW_TEXT, null
        );
        let node;
        while ((node = walker.nextNode())) {
          const t = (node.textContent || '').trim();
          if (!t) continue;
          if (t.startsWith('@') && !handle) {
            handle = t;
          } else if (!displayName && !t.startsWith('@')) {
            // Skip svg title text or single-char artifacts
            if (t.length > 1) displayName = t;
          }
        }
        // Fallback: try newline split of innerText
        if (!handle || !displayName) {
          const lines = (nameBlock.innerText || '').split('\n').map(s => s.trim()).filter(Boolean);
          for (const line of lines) {
            if (line.startsWith('@') && !handle) {
              handle = line;
            } else if (!displayName && !line.startsWith('@') && line.length > 1) {
              displayName = line;
            }
          }
        }
        if (!displayName) displayName = normalize(nameBlock.innerText || '');
      }

      // --- verified / verified_kind (locale-limited: reads SVG aria-label in English) ---
      let verified = false;
      let verifiedKind = null;
      if (nameBlock) {
        const svgs = nameBlock.querySelectorAll('svg[aria-label]');
        for (const svg of svgs) {
          const lbl = (svg.getAttribute('aria-label') || '').toLowerCase();
          if (lbl.includes('verified')) {
            verified = true;
            if (lbl.includes('gold')) {
              verifiedKind = 'gold';
            } else if (lbl.includes('gray') || lbl.includes('grey')) {
              verifiedKind = 'gray';
            } else {
              verifiedKind = 'blue';
            }
            break;
          }
        }
      }

      // --- bio ---
      const descEl = document.querySelector(descriptionSelector);
      const bioInnertext = descEl ? (descEl.innerText || '') : '';
      const bio = normalize(bioInnertext);

      // --- bio links (anchors in description) ---
      const bioAnchors = descEl
        ? Array.from(descEl.querySelectorAll('a[href]')).map(a => ({
            href: a.href || a.getAttribute('href') || '',
            aria_label: a.getAttribute('aria-label') || '',
            expanded_url: a.dataset ? (a.dataset.expandedUrl || '') : '',
            text: normalize(a.innerText || a.textContent),
            source: 'bio',
          }))
        : [];

      // --- website ---
      let websiteUrl = null;
      const urlContainer = document.querySelector(urlFieldSelector);
      let websiteAnchor = null;
      if (urlContainer) {
        const a = urlContainer.querySelector('a[href]');
        if (a) {
          websiteAnchor = a;
          // Priority: data-expanded-url > aria-label (if URL) > href
          const expandedUrl = a.dataset ? (a.dataset.expandedUrl || '') : '';
          const ariaLabel = a.getAttribute('aria-label') || '';
          const href = a.href || a.getAttribute('href') || '';
          if (expandedUrl && expandedUrl.startsWith('http')) {
            websiteUrl = expandedUrl;
          } else if (ariaLabel && ariaLabel.startsWith('http')) {
            websiteUrl = ariaLabel;
          } else if (href && href.startsWith('http')) {
            websiteUrl = href;
          }
        }
      }

      const websiteAnchors = websiteAnchor
        ? [{
            href: websiteAnchor.href || websiteAnchor.getAttribute('href') || '',
            aria_label: websiteAnchor.getAttribute('aria-label') || '',
            expanded_url: websiteAnchor.dataset ? (websiteAnchor.dataset.expandedUrl || '') : '',
            text: normalize(websiteAnchor.innerText || websiteAnchor.textContent),
            source: 'website',
          }]
        : [];

      // --- location ---
      const locEl = document.querySelector(locationSelector);
      const location = locEl ? normalize(locEl.innerText || '') : null;

      // --- joined ---
      const joinEl = document.querySelector(joinDateSelector);
      const joined = joinEl ? normalize(joinEl.innerText || '') : null;

      // --- followers count (read innerText of matching anchor) ---
      let followersText = null;
      const followerLinks = Array.from(document.querySelectorAll(followersSelector));
      if (followerLinks.length > 0) {
        followersText = normalize(followerLinks[0].innerText || '');
      }

      // --- following count ---
      let followingText = null;
      const followingLinks = Array.from(document.querySelectorAll(followingSelector));
      if (followingLinks.length > 0) {
        followingText = normalize(followingLinks[0].innerText || '');
      }

      return {
        displayName,
        handle,
        verified,
        verifiedKind,
        bio,
        bioInnertext,
        bioAnchors,
        websiteUrl,
        websiteAnchors,
        location: location || null,
        joined: joined || null,
        followersText,
        followingText,
      };
    }
    """

    async def _extract_profile_block(self) -> dict:
        """Extract the profile header via a single page.evaluate call.

        Returns a flat profile dict with fields matching plan §4.2 schema.
        Python-side post-processing applies parse_join_date and
        extract_links_from_anchors.
        """
        js_args = {
            "userNameSelector": PROFILE_USER_NAME,
            "descriptionSelector": PROFILE_DESCRIPTION,
            "urlFieldSelector": PROFILE_URL_FIELD,
            "locationSelector": PROFILE_LOCATION,
            "joinDateSelector": PROFILE_JOIN_DATE,
            "followersSelector": PROFILE_FOLLOWERS_LINK,
            "followingSelector": PROFILE_FOLLOWING_LINK,
        }

        try:
            raw: dict = await self._page.evaluate(self._EXTRACT_PROFILE_JS, js_args)
        except Exception as e:
            logger.warning("_extract_profile_block evaluate error: %s", e)
            raw = {}

        # --- Python-side post-processing ---
        joined_raw: str | None = raw.get("joined")
        joined_iso = parse_join_date(joined_raw)

        followers_count = parse_metric_count(raw.get("followersText"))
        following_count = parse_metric_count(raw.get("followingText"))

        # Combine bio anchors + website anchors then deduplicate
        bio_anchors: list[dict] = raw.get("bioAnchors") or []
        website_anchors: list[dict] = raw.get("websiteAnchors") or []
        all_anchors = bio_anchors + website_anchors
        links = extract_links_from_anchors(all_anchors)

        return {
            "display_name": raw.get("displayName"),
            "handle": raw.get("handle"),
            "bio": raw.get("bio") or None,
            "bio_innertext": raw.get("bioInnertext") or None,
            "verified": bool(raw.get("verified")),
            "verified_kind": raw.get("verifiedKind"),
            "location": raw.get("location"),
            "website": raw.get("websiteUrl"),
            "joined": joined_raw,
            "joined_iso": joined_iso,
            "following_count": following_count,
            "followers_count": followers_count,
            "links": links,
            "protected": False,
            "suspended": False,
            "not_found": False,
        }

    # ------------------------------------------------------------------
    # research_profile
    # ------------------------------------------------------------------

    async def research_profile(self, username: str, posts: int, comments_per: int) -> dict:
        """Research a user's profile: bio + top N posts + Y comments each.

        Args:
            username:     X handle to research (without leading ``@``).
            posts:        Number of profile posts to return (ads excluded).
            comments_per: Number of top reply comments per post.

        Returns:
            Profile dict matching plan §4.2 schema:
            {captured_at, username, url, profile, posts, warnings}

        Raises:
            AuthenticationError: If session is expired or login wall is hit.
            RateLimitError: If hard-blocked at /account/access.
        """
        from urllib.parse import quote_plus

        url = f"https://x.com/{quote_plus(username)}"
        captured_at = utcnow_iso()
        warnings: list[str] = []

        # 1. Navigate to the profile page
        await self._goto_with_auth_checks(self._resolve_url(url))

        # 2. Detect profile errors FIRST (before waiting for normal selectors)
        error_kind = await self._detect_profile_error(username)
        if error_kind:
            return self._profile_error_result(url, username, error_kind, captured_at)

        # 3. Wait for the profile header to be present
        try:
            await self._page.wait_for_selector(PROFILE_USER_NAME, timeout=10000)
        except PlaywrightTimeoutError:
            warnings.append("Profile header did not render within timeout")

        await dismiss_modals(self._page)

        # 4. Extract the profile header block in one JS evaluate
        profile = await self._extract_profile_block()

        # 5. Capture-as-you-scroll to collect timeline posts
        scope = PRIMARY_COLUMN

        async def _extract(p: Page) -> list[dict]:
            return await self._extract_visible_tweets(scope_selector=scope)

        raw_posts = await capture_as_you_scroll(
            self._page,
            extract_fn=_extract,
            target=posts + 10,
            max_scrolls=15,
            max_stale=3,
            wheel_delta=1500,
            pause_seconds=1.0,
        )

        # Filter ads, truncate
        timeline_posts = [p for p in raw_posts if not p.get("is_ad")][:posts]

        # 6. Fetch comments for each post
        for post in timeline_posts:
            post_url = post.get("url") or ""
            if not post_url or comments_per == 0:
                post["comments"] = []
                post["comments_captured"] = 0
                post["comments_partial"] = False
                continue

            await asyncio.sleep(_jitter(NAV_DELAY, self._jitter_pct))
            try:
                comments = await self.fetch_thread_comments(post_url, comments_per)
                post["comments"] = comments
                post["comments_captured"] = len(comments)
                post["comments_partial"] = len(comments) < comments_per
            except RateLimitError as e:
                logger.warning(
                    "RateLimitError fetching comments for %s: %s — skipping",
                    post_url,
                    e,
                )
                warnings.append(f"Rate-limited fetching comments for {post.get('id')}: {e}")
                post["comments"] = []
                post["comments_captured"] = 0
                post["comments_partial"] = True
            except AuthenticationError:
                raise
            except Exception as e:
                logger.warning("Error fetching comments for %s: %s", post_url, e)
                warnings.append(f"Error fetching comments for {post.get('id')}: {e}")
                post["comments"] = []
                post["comments_captured"] = 0
                post["comments_partial"] = True

        # 7. Return the full result
        canonical_url = url if url.endswith("/") else url + "/"
        return {
            "captured_at": captured_at,
            "username": username,
            "url": canonical_url,
            "profile": profile,
            "posts": timeline_posts,
            "warnings": warnings,
        }
