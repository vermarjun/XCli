"""Unit tests for xcli.scraping.parsing.

All tests are table-driven (parametrize) to keep cases dense and readable.
"""

from __future__ import annotations

import pytest

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

# ---------------------------------------------------------------------------
# parse_metric_count
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "input_str, expected",
    [
        # Plain integers
        ("12", 12),
        ("0", 0),
        ("999", 999),
        # K suffix
        ("12.3K", 12300),
        ("1.5K", 1500),
        ("100K", 100000),
        # M suffix
        ("1.2M", 1200000),
        ("3.4M", 3400000),
        ("10M", 10000000),
        # B suffix
        ("3.4B", 3400000000),
        ("1B", 1000000000),
        # Comma as thousands separator
        ("1,234", 1234),
        ("12,345", 12345),
        # European decimal comma (comma before 1–2 digits then suffix)
        ("12,3 K", 12300),
        ("1,2M", 1200000),
        # CJK suffixes
        ("1.2万", 12000),
        ("3.5万", 35000),
        ("1.2億", 120000000),
        # Trailing word (locale aria-label)
        ("123 Likes", 123),
        ("1.2K Reposts", 1200),
        ("456 replies", 456),
        ("789 Retweets", 789),
        # Leading/trailing whitespace
        ("  42  ", 42),
        ("  1.5K  ", 1500),
        # No digits at all → None
        ("Likes", None),
        ("", None),
        (None, None),
        # Surrogate/weird input that has no parseable digit run
        ("+++", None),
        # Case-insensitive suffix
        ("1.5k", 1500),
        ("2.3m", 2300000),
        ("4.5b", 4500000000),
    ],
)
def test_parse_metric_count(input_str: str | None, expected: int | None) -> None:
    result = parse_metric_count(input_str)
    assert (
        result == expected
    ), f"parse_metric_count({input_str!r}) → {result!r}, expected {expected!r}"


# ---------------------------------------------------------------------------
# parse_post_id_from_href
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "href, expected",
    [
        # Basic relative URL
        ("/elonmusk/status/123456789", "123456789"),
        # With trailing slash
        ("/elonmusk/status/123/", "123"),
        # With trailing path component
        ("/elonmusk/status/123/photo/1", "123"),
        ("/elonmusk/status/123/video/1", "123"),
        # Absolute URL
        ("https://x.com/user/status/999", "999"),
        ("https://twitter.com/user/status/999/", "999"),
        # With query string
        ("/user/status/555?t=abc", "555"),
        # With fragment
        ("/user/status/777#x", "777"),
        # Not a status URL
        ("/elonmusk", None),
        ("/home", None),
        ("", None),
        (None, None),
        # Edge: /status/ with no digits
        ("/user/status/abc", None),
    ],
)
def test_parse_post_id_from_href(href: str | None, expected: str | None) -> None:
    result = parse_post_id_from_href(href)
    assert (
        result == expected
    ), f"parse_post_id_from_href({href!r}) → {result!r}, expected {expected!r}"


# ---------------------------------------------------------------------------
# parse_username_from_avatar_testid
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "testid, expected",
    [
        ("UserAvatar-Container-elonmusk", "elonmusk"),
        ("UserAvatar-Container-TwitterDev", "TwitterDev"),
        ("UserAvatar-Container-x", "x"),
        # Wrong prefix
        ("SomethingElse", None),
        ("UserAvatar-elonmusk", None),
        # Empty / None
        ("", None),
        (None, None),
        # Just the prefix without a username
        ("UserAvatar-Container-", None),
    ],
)
def test_parse_username_from_avatar_testid(testid: str | None, expected: str | None) -> None:
    result = parse_username_from_avatar_testid(testid)
    assert (
        result == expected
    ), f"parse_username_from_avatar_testid({testid!r}) → {result!r}, expected {expected!r}"


# ---------------------------------------------------------------------------
# parse_username_from_status_href
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "href, expected",
    [
        ("/elonmusk/status/123", "elonmusk"),
        ("/TwitterDev/status/456", "TwitterDev"),
        ("https://x.com/elonmusk/status/123", "elonmusk"),
        ("https://twitter.com/user_123/status/789", "user_123"),
        # Underscore in username
        ("/some_user/status/100", "some_user"),
        # Non-status URL
        ("/home", None),
        ("/settings/profile", None),
        ("", None),
        (None, None),
        # Username too long (>15 chars per Twitter rules) — regex enforces {1,15}
        # so the full slug won't match; returns None (correct behaviour).
        ("/a_really_very_long_username/status/1", None),
    ],
)
def test_parse_username_from_status_href(href: str | None, expected: str | None) -> None:
    result = parse_username_from_status_href(href)
    assert (
        result == expected
    ), f"parse_username_from_status_href({href!r}) → {result!r}, expected {expected!r}"


# ---------------------------------------------------------------------------
# parse_join_date
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "input_str, expected",
    [
        ("Joined June 2009", "2009-06"),
        ("Joined December 2023", "2023-12"),
        ("Joined January 2006", "2006-01"),
        ("Joined March 2015", "2015-03"),
        ("Joined September 2011", "2011-09"),
        # Without "Joined" prefix
        ("March 2015", "2015-03"),
        # Case variations
        ("joined june 2009", "2009-06"),
        ("JOINED JUNE 2009", "2009-06"),
        # Unknown format → None
        ("Unknown format", None),
        ("2009-06", None),  # ISO format, not X format
        ("", None),
        (None, None),
    ],
)
def test_parse_join_date(input_str: str | None, expected: str | None) -> None:
    result = parse_join_date(input_str)
    assert result == expected, f"parse_join_date({input_str!r}) → {result!r}, expected {expected!r}"


# ---------------------------------------------------------------------------
# parse_iso_datetime
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "input_str, expected",
    [
        ("2026-05-19T10:00:00.000Z", "2026-05-19T10:00:00.000Z"),
        ("2026-05-19T10:00:00Z", "2026-05-19T10:00:00Z"),
        ("2026-05-19T10:00:00+00:00", "2026-05-19T10:00:00+00:00"),
        ("2026-05-19T10:00:00", "2026-05-19T10:00:00"),
        # Invalid
        ("not-a-date", None),
        ("", None),
        (None, None),
        ("2026-13-01T00:00:00Z", None),  # month 13 is invalid
    ],
)
def test_parse_iso_datetime(input_str: str | None, expected: str | None) -> None:
    result = parse_iso_datetime(input_str)
    assert (
        result == expected
    ), f"parse_iso_datetime({input_str!r}) → {result!r}, expected {expected!r}"


# ---------------------------------------------------------------------------
# extract_links_from_anchors
# ---------------------------------------------------------------------------


def test_extract_links_prefers_expanded_url() -> None:
    """When expanded_url is present, it should be used as the canonical URL."""
    anchors = [
        {
            "href": "https://t.co/abc123",
            "expanded_url": "https://example.com/article",
            "aria_label": "",
            "source": "tweet",
        }
    ]
    result = extract_links_from_anchors(anchors)
    assert len(result) == 1
    assert result[0]["url"] == "https://example.com/article"
    assert result[0]["raw_href"] == "https://t.co/abc123"
    assert result[0]["source"] == "tweet"


def test_extract_links_falls_back_to_aria_label_url() -> None:
    """When aria_label is a URL and no expanded_url, use aria_label."""
    anchors = [
        {
            "href": "https://t.co/xyz",
            "expanded_url": "",
            "aria_label": "https://realsite.com/page",
            "source": "tweet",
        }
    ]
    result = extract_links_from_anchors(anchors)
    assert len(result) == 1
    assert result[0]["url"] == "https://realsite.com/page"


def test_extract_links_falls_back_to_href() -> None:
    """When no expanded_url or aria_label URL, resolve from href."""
    anchors = [
        {
            "href": "https://github.com/user/repo",
            "expanded_url": "",
            "aria_label": "some label without URL",
            "source": "tweet",
        }
    ]
    result = extract_links_from_anchors(anchors)
    assert len(result) == 1
    assert result[0]["url"] == "https://github.com/user/repo"


def test_extract_links_deduplicates_by_resolved_url() -> None:
    """Same resolved URL appearing twice should only produce one output entry."""
    anchors = [
        {
            "href": "https://t.co/abc",
            "expanded_url": "https://example.com",
            "aria_label": "",
            "source": "tweet",
        },
        {
            "href": "https://t.co/abc2",
            "expanded_url": "https://example.com",
            "aria_label": "",
            "source": "tweet",
        },
    ]
    result = extract_links_from_anchors(anchors)
    assert len(result) == 1
    assert result[0]["url"] == "https://example.com"


def test_extract_links_skips_relative_hrefs() -> None:
    """Relative hrefs without expanded_url or aria_label URL are skipped."""
    anchors = [
        {"href": "/user/status/123", "expanded_url": "", "aria_label": "", "source": "tweet"},
    ]
    result = extract_links_from_anchors(anchors)
    # /user/status/123 is not an absolute URL — should be skipped
    assert result == []


def test_extract_links_empty_input() -> None:
    assert extract_links_from_anchors([]) == []


# ---------------------------------------------------------------------------
# parse_human_timestamp
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "input_str, expected",
    [
        # Full X timestamp with time prefix
        ("12:34 PM · May 19, 2026", "2026-05-19"),
        # Date only
        ("May 19, 2026", "2026-05-19"),
        # Abbreviated month with day and year
        ("Mar 5, 2024", "2024-03-05"),
        # Full month name
        ("December 31, 1999", "1999-12-31"),
        # Relative timestamps — cannot resolve, return None
        ("5h", None),
        # Month+day only (no year) — no match, return None
        ("Mar 5", None),
        # Empty string
        ("", None),
        # None input
        (None, None),
        # Raw ISO datetime in aria-label — falls through to parse_iso_datetime
        ("2024-05-19T12:34:56.000Z", "2024-05-19T12:34:56.000Z"),
        # Completely unparseable text
        ("not a date", None),
        # Year only (no month) — no match
        ("2024", None),
    ],
)
def test_parse_human_timestamp(input_str: str | None, expected: str | None) -> None:
    result = parse_human_timestamp(input_str)
    assert (
        result == expected
    ), f"parse_human_timestamp({input_str!r}) → {result!r}, expected {expected!r}"


def test_extract_links_multiple_unique() -> None:
    anchors = [
        {"href": "https://a.com", "expanded_url": "", "aria_label": "", "source": "tweet"},
        {"href": "https://b.com", "expanded_url": "", "aria_label": "", "source": "bio"},
        {
            "href": "https://c.com",
            "expanded_url": "https://expanded-c.com",
            "aria_label": "",
            "source": "website",
        },
    ]
    result = extract_links_from_anchors(anchors)
    urls = [r["url"] for r in result]
    assert "https://a.com" in urls
    assert "https://b.com" in urls
    assert "https://expanded-c.com" in urls
    assert len(result) == 3
