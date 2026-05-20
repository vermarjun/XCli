"""Unit tests for xcli.scraping.selectors.

Verifies:
1. Every public string constant is non-empty.
2. Spot-checks on format invariants.
3. AUTH_BLOCKER_URL_PATHS has no overlapping prefixes.
4. Tuple constants are tuples of non-empty strings.
"""

from __future__ import annotations

import inspect

import pytest

import xcli.scraping.selectors as sel_module
from xcli.scraping.selectors import (
    AUTH_BLOCKER_URL_PATHS,
    LOGGED_IN_NAV,
    PRIMARY_COLUMN,
    TWEET_ARTICLE,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _public_string_constants() -> list[tuple[str, str]]:
    """Return all public module-level string constants as (name, value) pairs."""
    result = []
    for name, value in inspect.getmembers(sel_module):
        if name.startswith("_"):
            continue
        if isinstance(value, str):
            result.append((name, value))
    return result


def _public_tuple_constants() -> list[tuple[str, tuple]]:
    """Return all public module-level tuple constants."""
    result = []
    for name, value in inspect.getmembers(sel_module):
        if name.startswith("_"):
            continue
        if isinstance(value, tuple):
            result.append((name, value))
    return result


# ---------------------------------------------------------------------------
# Test: every public string constant is non-empty
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name,value", _public_string_constants())
def test_string_constant_non_empty(name: str, value: str) -> None:
    """Every public string constant must be a non-empty string."""
    assert isinstance(value, str), f"{name} should be str, got {type(value)}"
    assert value.strip(), f"{name} is empty or whitespace-only"


# ---------------------------------------------------------------------------
# Test: every public tuple constant has non-empty string elements
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name,value", _public_tuple_constants())
def test_tuple_constant_elements_non_empty(name: str, value: tuple) -> None:
    """Every element of a public tuple constant must be a non-empty string or tuple of strings.

    AUTH_BARRIER_TEXT_MARKERS is a tuple of tuples (grouped markers), so we
    recurse one level for tuples whose elements are themselves tuples.
    """
    for i, elem in enumerate(value):
        if isinstance(elem, tuple):
            # Nested tuple (e.g. AUTH_BARRIER_TEXT_MARKERS groups) — recurse one level
            for j, sub in enumerate(elem):
                assert isinstance(sub, str), f"{name}[{i}][{j}] should be str, got {type(sub)}"
                assert sub.strip(), f"{name}[{i}][{j}] is empty or whitespace-only"
        else:
            assert isinstance(elem, str), f"{name}[{i}] should be str, got {type(elem)}"
            assert elem.strip(), f"{name}[{i}] is empty or whitespace-only"


# ---------------------------------------------------------------------------
# Spot-checks: format invariants
# ---------------------------------------------------------------------------


def test_tweet_article_starts_with_article() -> None:
    """TWEET_ARTICLE must start with 'article[data-testid='."""
    assert TWEET_ARTICLE.startswith(
        "article[data-testid="
    ), f"TWEET_ARTICLE should start with 'article[data-testid=', got: {TWEET_ARTICLE!r}"


def test_primary_column_starts_with_data_testid() -> None:
    """PRIMARY_COLUMN must start with '[data-testid='."""
    assert PRIMARY_COLUMN.startswith(
        "[data-testid="
    ), f"PRIMARY_COLUMN should start with '[data-testid=', got: {PRIMARY_COLUMN!r}"


def test_logged_in_nav_contains_SideNav() -> None:
    """LOGGED_IN_NAV must reference SideNav_AccountSwitcher_Button."""
    assert "SideNav_AccountSwitcher_Button" in LOGGED_IN_NAV


def test_logged_in_nav_contains_AppTabBar() -> None:
    """LOGGED_IN_NAV must reference AppTabBar_Profile_Link."""
    assert "AppTabBar_Profile_Link" in LOGGED_IN_NAV


def test_auth_blocker_url_paths_start_with_slash() -> None:
    """Every AUTH_BLOCKER_URL_PATHS entry must start with '/'."""
    for path in AUTH_BLOCKER_URL_PATHS:
        assert path.startswith("/"), f"Expected path starting with '/', got: {path!r}"


def test_auth_blocker_url_paths_no_overlapping_prefixes() -> None:
    """No AUTH_BLOCKER_URL_PATHS entry should be a strict prefix of another.

    For example, having both '/login' and '/login/extra' would cause the
    shorter one to shadow the longer.  We allow exact duplicates (which would
    be caught as a separate bug) but not prefix relationships.
    """
    paths = list(AUTH_BLOCKER_URL_PATHS)
    for i, p1 in enumerate(paths):
        for j, p2 in enumerate(paths):
            if i == j:
                continue
            # p1 is a prefix of p2 (strict — same string excluded separately)
            if p2.startswith(p1 + "/") or p2.startswith(p1 + "?"):
                pytest.fail(
                    f"Overlapping paths in AUTH_BLOCKER_URL_PATHS: {p1!r} is a prefix of {p2!r}"
                )


def test_no_class_name_selectors_in_string_constants() -> None:
    """Spot-check: no selector should be a CSS class selector (starts with '.')."""
    for name, value in _public_string_constants():
        # Some constants are URL path strings (start with '/') or title strings
        # — those can contain dots in different contexts.
        # We only check values that look like CSS selectors (contain '[' or start with '[').
        if "[" not in value and not value.startswith("."):
            continue
        # The value must not start with a class selector
        assert not value.strip().startswith(
            "."
        ), f"{name}={value!r} appears to be a CSS class selector — not allowed"


def test_ad_text_labels_is_dict_with_en() -> None:
    """AD_TEXT_LABELS must be a dict with an 'en' key."""
    from xcli.scraping.selectors import AD_TEXT_LABELS

    assert isinstance(AD_TEXT_LABELS, dict), "AD_TEXT_LABELS should be a dict"
    assert "en" in AD_TEXT_LABELS, "AD_TEXT_LABELS should have an 'en' key"
    assert AD_TEXT_LABELS["en"] == "Ad"
