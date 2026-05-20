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
    parse_iso_datetime,
    parse_metric_count,
    parse_post_id_from_href,
    parse_username_from_avatar_testid,
    parse_username_from_status_href,
)
from xcli.scraping.selectors import (
    ACCOUNT_SWITCHER_BUTTON,
    AD_INDICATOR,
    LOGIN_BUTTON,
    PRIMARY_COLUMN,
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

      // --- Time ---
      const timeEl = article.querySelector('time[datetime]');
      const postedAt = timeEl ? (timeEl.getAttribute('datetime') || '') : '';

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
        postedAt,
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
        "posted_at": parse_iso_datetime(raw.get("postedAt")),
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
(selector) => {
    const el = document.querySelector(selector);
    return el ? (el.getAttribute('aria-label') || '') : '';
}
"""


async def read_authenticated_handle(page: Page) -> str | None:
    """Read the logged-in user's handle from the account-switcher aria-label.

    Args:
        page: Active Patchright page (must be on an authenticated X page).

    Returns:
        The handle string (without leading ``@``), or ``None`` if not present
        or unparseable.
    """
    try:
        label = await page.evaluate(_READ_HANDLE_JS, ACCOUNT_SWITCHER_BUTTON)
        if isinstance(label, str) and "@" in label:
            return label.split("@")[-1].split()[0].strip("@")
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

    def __init__(self, page: Page) -> None:
        self._page = page
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

            await asyncio.sleep(NAV_DELAY)
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
