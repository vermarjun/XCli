"""DOM-to-Python parsing utilities for X.com content.

All functions are pure (no I/O, no side effects) and thoroughly docstrings-ed.

Locale notes
------------
X's aria-label engagement counts are formatted per the user's locale, which
can vary widely. For example, 12,300 in English may be rendered as ``12.3K``
or ``12,3 K`` (European decimal-comma) or ``1.2万`` (CJK). The
``parse_metric_count`` function handles:

- Western: ``12``, ``12.3K``, ``1.2M``, ``3.4B``, ``1,234``
- European decimal-comma: ``12,3 K`` (comma as decimal separator when followed
  by a single digit cluster, then a suffix)
- CJK suffix table: ``万`` (10 000), ``億`` (100 000 000)
- Mixed: ``123 Likes``, ``1.2K Reposts`` (strip trailing word, parse number)

Limitation: if X adds new locale suffix styles (e.g. South Asian lakh/crore)
they would need to be added to the ``_METRIC_SUFFIX_TABLE`` dict.
"""

from __future__ import annotations

import re
from datetime import datetime

# ---------------------------------------------------------------------------
# parse_metric_count
# ---------------------------------------------------------------------------

# Suffix multiplier table, checked in iteration order (longer suffixes first
# to avoid partial matches — e.g. "億" before "万").
_METRIC_SUFFIX_TABLE: dict[str, float] = {
    "億": 1e8,
    "万": 1e4,
    "B": 1e9,
    "M": 1e6,
    "K": 1e3,
    "b": 1e9,
    "m": 1e6,
    "k": 1e3,
}

# Regex: find first numeric token (digits with optional separators)
# Handles: 12, 12.3, 1,234, 12,3 (European comma-decimal)
_METRIC_NUMBER_RE = re.compile(
    r"""
    (?<![A-Za-z0-9])          # not preceded by word char
    (\d[\d,.]*)               # digits with optional , or . separators
    \s*                       # optional whitespace
    ([億万BMKbmk])?           # optional multiplier suffix
    (?![A-Za-z0-9])           # not followed by word char (avoid "B" in "Bob")
    """,
    re.VERBOSE,
)


def parse_metric_count(s: str | None) -> int | None:
    """Parse an engagement count string into an integer.

    Handles all known X.com aria-label locale variants:

    - Plain integers: ``"12"`` → ``12``
    - K/M/B suffixes: ``"12.3K"`` → ``12300``, ``"1.2M"`` → ``1200000``
    - Comma-thousands: ``"1,234"`` → ``1234``
    - European decimal-comma: ``"12,3 K"`` → ``12300`` (comma before single
      digit followed by suffix is treated as decimal separator)
    - CJK: ``"1.2万"`` → ``12000``, ``"1.2億"`` → ``120000000``
    - With trailing word: ``"123 Likes"`` → ``123``, ``"1.2K Reposts"`` → ``1200``
    - No digits: ``"Likes"`` → ``None``
    - Empty / None: ``None``

    Limitation: Whitespace between number and suffix is tolerated (``"12,3 K"``).
    The comma-as-decimal-separator heuristic only fires when the comma is
    followed by exactly 1–2 digits and then a suffix or end-of-token.
    """
    if s is None:
        return None
    if not isinstance(s, str):
        return None
    text = s.strip()
    if not text:
        return None

    match = _METRIC_NUMBER_RE.search(text)
    if not match:
        return None

    raw_num = match.group(1)
    suffix = match.group(2) or ""

    # Determine if comma is a decimal separator or thousands separator.
    # Heuristic: if the raw_num ends with ",<1-2 digits>" and there is a suffix,
    # treat the comma as a decimal point (European locale).
    # Otherwise, treat commas as thousands separators and remove them.
    if "," in raw_num and suffix:
        # Check if it looks like European decimal: "12,3" (comma then 1-2 digits at end)
        european = re.match(r"^(\d+),(\d{1,2})$", raw_num)
        if european:
            raw_num = f"{european.group(1)}.{european.group(2)}"
        else:
            # Treat commas as thousands separators
            raw_num = raw_num.replace(",", "")
    else:
        raw_num = raw_num.replace(",", "")

    try:
        value = float(raw_num)
    except ValueError:
        return None

    if suffix:
        multiplier = _METRIC_SUFFIX_TABLE.get(suffix, 1.0)
        value *= multiplier

    return int(round(value))


# ---------------------------------------------------------------------------
# parse_post_id_from_href
# ---------------------------------------------------------------------------

_STATUS_ID_RE = re.compile(r"/status/(\d+)(?:/|$|\?|#)")


def parse_post_id_from_href(href: str | None) -> str | None:
    """Extract a numeric tweet ID from a status URL.

    Works with relative and absolute URLs. Ignores trailing path components
    like ``/photo/1`` or ``/video/1``.

    Examples:
        >>> parse_post_id_from_href("/elonmusk/status/123")
        '123'
        >>> parse_post_id_from_href("/elonmusk/status/123/photo/1")
        '123'
        >>> parse_post_id_from_href("https://x.com/user/status/999/")
        '999'
        >>> parse_post_id_from_href(None)
        None
    """
    if not href:
        return None
    m = _STATUS_ID_RE.search(href)
    if m:
        return m.group(1)
    # Also match when the URL ends exactly at the ID (no trailing slash/query)
    m2 = re.search(r"/status/(\d+)$", href)
    if m2:
        return m2.group(1)
    return None


# ---------------------------------------------------------------------------
# parse_username_from_avatar_testid
# ---------------------------------------------------------------------------


def parse_username_from_avatar_testid(testid: str | None) -> str | None:
    """Extract the username from a UserAvatar data-testid attribute value.

    X sets ``data-testid="UserAvatar-Container-<username>"`` on avatar elements,
    making this the most reliable in-tweet username source.

    Examples:
        >>> parse_username_from_avatar_testid("UserAvatar-Container-elonmusk")
        'elonmusk'
        >>> parse_username_from_avatar_testid("SomethingElse")
        None
    """
    if not testid:
        return None
    prefix = "UserAvatar-Container-"
    if testid.startswith(prefix):
        username = testid[len(prefix) :]
        if username:
            return username
    return None


# ---------------------------------------------------------------------------
# parse_username_from_status_href
# ---------------------------------------------------------------------------

_USERNAME_FROM_STATUS_RE = re.compile(r"^(?:https?://[^/]+)?/([A-Za-z0-9_]{1,15})/status/\d+")


def parse_username_from_status_href(href: str | None) -> str | None:
    """Extract the username from a /status/ URL.

    Examples:
        >>> parse_username_from_status_href("/elonmusk/status/123")
        'elonmusk'
        >>> parse_username_from_status_href("https://x.com/TwitterDev/status/456")
        'TwitterDev'
        >>> parse_username_from_status_href("/not-a-status")
        None
    """
    if not href:
        return None
    m = _USERNAME_FROM_STATUS_RE.match(href.strip())
    if m:
        return m.group(1)
    return None


# ---------------------------------------------------------------------------
# parse_join_date
# ---------------------------------------------------------------------------

_MONTH_TABLE: dict[str, str] = {
    "january": "01",
    "february": "02",
    "march": "03",
    "april": "04",
    "may": "05",
    "june": "06",
    "july": "07",
    "august": "08",
    "september": "09",
    "october": "10",
    "november": "11",
    "december": "12",
}

_JOIN_DATE_RE = re.compile(
    r"(?:Joined\s+)?([A-Za-z]+)\s+(\d{4})",
    re.IGNORECASE,
)


def parse_join_date(s: str | None) -> str | None:
    """Parse an X-style join date string into ISO year-month format.

    Input is English-only (the locale limitation is documented here and in
    the module docstring). If X displays join date in a different locale,
    this function returns None and callers should add the joined string raw
    to ``warnings``.

    Examples:
        >>> parse_join_date("Joined June 2009")
        '2009-06'
        >>> parse_join_date("Joined December 2023")
        '2023-12'
        >>> parse_join_date("March 2015")
        '2015-03'
        >>> parse_join_date("Unknown format")
        None
    """
    if not s:
        return None
    m = _JOIN_DATE_RE.search(s)
    if not m:
        return None
    month_name = m.group(1).lower()
    year = m.group(2)
    month_num = _MONTH_TABLE.get(month_name)
    if not month_num:
        return None
    return f"{year}-{month_num}"


# ---------------------------------------------------------------------------
# parse_iso_datetime
# ---------------------------------------------------------------------------


def parse_iso_datetime(s: str | None) -> str | None:
    """Validate and normalise an ISO 8601 datetime string from a time[datetime] attr.

    Returns the normalised string (uppercase Z suffix) or None if unparseable.
    Python 3.11+ datetime.fromisoformat handles the trailing Z natively.

    Examples:
        >>> parse_iso_datetime("2026-05-19T10:00:00.000Z")
        '2026-05-19T10:00:00.000Z'
        >>> parse_iso_datetime("2026-05-19T10:00:00+00:00")
        '2026-05-19T10:00:00+00:00'
        >>> parse_iso_datetime("not-a-date")
        None
    """
    if not s:
        return None
    try:
        datetime.fromisoformat(s)
        return s
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# extract_links_from_anchors
# ---------------------------------------------------------------------------

_URL_RE = re.compile(r"^https?://", re.IGNORECASE)


def extract_links_from_anchors(anchors: list[dict]) -> list[dict]:
    """Build a deduplicated list of resolved link dicts from raw anchor metadata.

    Input is a list of dicts as produced by a ``page.evaluate`` that walks
    ``<a>`` tags:
    ``[{href, aria_label?, expanded_url?, text?}]``

    Output is a deduplicated list of:
    ``[{url, raw_href, source}]``

    where ``source`` is one of: ``"bio"``, ``"website"``, ``"pinned"``,
    ``"text"``, ``"tweet"``.

    Resolution priority (per plan §4.1):
    1. ``expanded_url`` (X stores the un-shortened URL in ``data-expanded-url``)
    2. ``aria_label`` if it looks like a URL (``http://`` / ``https://``)
    3. Resolved ``href`` (absolute URL)

    t.co short URLs are kept as ``raw_href`` even when an expanded URL is
    available, so callers can always trace the canonical redirect chain.

    Phase 1 only uses ``source="tweet"``; Phase 2 will add bio/website/pinned.
    For Phase 1 all links coming from tweet bodies are tagged ``"tweet"``.
    """
    seen_urls: set[str] = set()
    result: list[dict] = []

    for anchor in anchors:
        raw_href: str = anchor.get("href") or ""
        expanded_url: str = anchor.get("expanded_url") or ""
        aria_label: str = anchor.get("aria_label") or ""
        source: str = anchor.get("source") or "tweet"

        # Resolve best URL
        if expanded_url and _URL_RE.match(expanded_url):
            resolved = expanded_url
        elif aria_label and _URL_RE.match(aria_label):
            resolved = aria_label
        elif raw_href and _URL_RE.match(raw_href):
            resolved = raw_href
        else:
            # Relative href — skip (we only want full URLs)
            continue

        # Deduplicate by resolved URL
        if resolved in seen_urls:
            continue
        seen_urls.add(resolved)

        result.append(
            {
                "url": resolved,
                "raw_href": raw_href or resolved,
                "source": source,
            }
        )

    return result
