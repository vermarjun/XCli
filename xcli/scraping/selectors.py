"""Stable X.com selectors — single source of truth.

All data-testid constants, URL path patterns, and structural selectors live
here. Every other module imports constants from this file; no raw CSS selector
strings appear outside this module.

Rules (enforced by pre-commit grep in Phase 4):
- No class-name selectors (X auto-generates and rotates class strings per deploy).
- No text-content selectors (locale-dependent). Where visible text is the only
  signal, it is hidden behind a per-locale table (e.g. AD_TEXT_LABELS).
- Engagement counts: parse digits from aria-label, not text.
- Auth/error classification: URL patterns first, then selector presence, then
  a tiny per-locale body-text table.
"""

# ---------------------------------------------------------------------------
# Page-ready signals
# ---------------------------------------------------------------------------

PRIMARY_COLUMN = '[data-testid="primaryColumn"]'
TIMELINE_CELL = '[data-testid="cellInnerDiv"]'  # row wrapper, sibling-able

# ---------------------------------------------------------------------------
# Tweet / post
# ---------------------------------------------------------------------------

TWEET_ARTICLE = 'article[data-testid="tweet"]'
TWEET_TEXT = '[data-testid="tweetText"]'
TWEET_USER_NAME_BLOCK = '[data-testid="User-Name"]'  # in-tweet author block
TWEET_TIME = "article time[datetime]"  # ISO datetime in datetime attr
TWEET_STATUS_LINK = 'a[href*="/status/"]'  # tweet permalink (id source)

# Most reliable username source: testid ends with the username
TWEET_USER_AVATAR_ANY = '[data-testid^="UserAvatar-Container-"]'

# Media
TWEET_MEDIA_PHOTO = '[data-testid="tweetPhoto"]'
TWEET_MEDIA_VIDEO = '[data-testid="videoPlayer"], video'

# Ad detection — structural, locale-independent
AD_INDICATOR = '[data-testid="placementTracking"]'

# Per-locale visible "Ad" text fallback (structural check preferred above)
AD_TEXT_LABELS: dict[str, str] = {"en": "Ad"}

# ---------------------------------------------------------------------------
# Engagement (counts live in aria-label, parse number out)
# ---------------------------------------------------------------------------

TWEET_REPLY_BTN = '[data-testid="reply"]'
TWEET_REPOST_BTN = '[data-testid="retweet"]'  # X kept the legacy testid
TWEET_LIKE_BTN = '[data-testid="like"], [data-testid="unlike"]'
TWEET_BOOKMARK_BTN = '[data-testid="bookmark"], [data-testid="removeBookmark"]'
TWEET_VIEW_COUNT_LINK = 'a[href$="/analytics"]'  # views shown as a link

# Social context (repost/pinned indicator above tweet)
SOCIAL_CONTEXT = '[data-testid="socialContext"]'
TWEET_SOCIAL_CONTEXT = SOCIAL_CONTEXT  # backward-compat alias

# ---------------------------------------------------------------------------
# Profile page
# ---------------------------------------------------------------------------

PROFILE_USER_NAME = '[data-testid="UserName"]'  # header name+handle block
PROFILE_DESCRIPTION = '[data-testid="UserDescription"]'  # bio (contains <a>)
PROFILE_URL_FIELD = '[data-testid="UserUrl"]'  # website
PROFILE_LOCATION = '[data-testid="UserLocation"]'
PROFILE_JOIN_DATE = '[data-testid="UserJoinDate"]'
PROFILE_FOLLOWERS_LINK = 'a[href$="/followers"], a[href$="/verified_followers"]'
PROFILE_FOLLOWING_LINK = 'a[href$="/following"]'
PROFILE_PINNED_BADGE = SOCIAL_CONTEXT  # backward-compat alias; "Pinned" on pinned post

# Phase 2 will rely on this; define now for completeness
EMPTY_STATE_HEADER = '[data-testid="empty_state_header_text"]'

# Per-locale profile error text labels (structural signals preferred first;
# text used only as disambiguation). Document: English-only in v1. When X
# adds new locales, extend this table — the detection code iterates all values.
PROFILE_ERROR_LABELS: dict[str, dict[str, tuple[str, ...]]] = {
    "en": {
        "not_found": ("This account doesn't exist",),
        "suspended": ("Account suspended", "has been suspended"),
        "protected": ("These posts are protected", "These Tweets are protected"),
    },
}

# ---------------------------------------------------------------------------
# Auth wall / blocker signals (URL- and structural-first)
# ---------------------------------------------------------------------------

LOGIN_BUTTON = '[data-testid="loginButton"]'
LOGIN_FORM_USER_INPUT = '[autocomplete="username"]'  # login form field

# Exact path match (not prefix) — see _is_auth_blocker_url for matching logic
AUTH_BLOCKER_URL_PATHS: tuple[str, ...] = (
    "/i/flow/login",
    "/login",
    "/account/access",
    "/i/flow/signup",
)

# Individual account-switcher button (used to read the logged-in handle)
ACCOUNT_SWITCHER_BUTTON = '[data-testid="SideNav_AccountSwitcher_Button"]'

# App tab bar profile link (used as fallback for reading logged-in handle)
APP_TAB_BAR_PROFILE_LINK = '[data-testid="AppTabBar_Profile_Link"]'

# Deny-list of path segments that are NOT user handles.
# Used in read_authenticated_handle fallback chain to filter out navigation paths.
RESERVED_HANDLE_PATHS: tuple[str, ...] = (
    "home",
    "explore",
    "notifications",
    "messages",
    "i",
    "search",
    "settings",
    "compose",
    "premium",
    "tos",
    "privacy",
    "verified-choose",
    "verified_choose",
    "bookmarks",
    "lists",
    "communities",
    "jobs",
    "logout",
    "login",
    "signup",
    "about",
    "help",
)

# Logged-in navigation signals (structural, not text-dependent)
# Combined CSS for convenience in auth.py's is_logged_in
LOGGED_IN_NAV = (
    '[data-testid="SideNav_AccountSwitcher_Button"], [data-testid="AppTabBar_Profile_Link"]'
)

# Individual selectors for iteration (auth.py loops over these)
LOGGED_IN_SELECTORS: tuple[str, ...] = (
    '[data-testid="SideNav_AccountSwitcher_Button"]',
    '[data-testid="AppTabBar_Profile_Link"]',
)

# Authenticated-only URL segments (URL-based fallback for is_logged_in)
AUTHED_URL_SEGMENTS: tuple[str, ...] = ("/home", "/notifications", "/messages")

# ---------------------------------------------------------------------------
# Login title patterns (per-locale fallback; English default)
# ---------------------------------------------------------------------------

LOGIN_TITLE_PATTERNS: tuple[str, ...] = (
    "log in to x",
    "log in to twitter",
    "sign in to x",
    "sign in to twitter",
)

# ---------------------------------------------------------------------------
# Auth barrier body text markers (per-locale; grouped — all must match)
# ---------------------------------------------------------------------------

AUTH_BARRIER_TEXT_MARKERS: tuple[tuple[str, ...], ...] = (
    ("Don't miss what's happening", "Log in"),
    ("Sign up to continue",),
)

# ---------------------------------------------------------------------------
# Soft-block / error states
# ---------------------------------------------------------------------------

ERROR_RETRY_BUTTON_HINT = '[role="button"]'  # combined with body text check
SOFT_BLOCK_BODY_MARKERS: tuple[str, ...] = (
    "Something went wrong",
    "Try reloading",
    "Rate limit exceeded",
)

# ---------------------------------------------------------------------------
# Modals / overlays to dismiss
# ---------------------------------------------------------------------------

MODAL_CLOSE_BTNS = (
    '[data-testid="app-bar-close"], [aria-label="Close"], [data-testid="sheetDialogCancel"]'
)
BOTTOM_BAR = '[data-testid="BottomBar"]'  # sign-up nag to hide
