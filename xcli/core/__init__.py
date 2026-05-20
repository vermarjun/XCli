"""xcli.core — browser lifecycle and auth utilities.

Re-exports the key names consumed by drivers and tools.
"""

from xcli.core.auth import (
    detect_auth_barrier,
    detect_auth_barrier_quick,
    detect_rate_limit,
    is_logged_in,
    wait_for_manual_login,
    warm_up_browser,
)
from xcli.core.browser import BrowserManager
from xcli.exceptions import AuthenticationError

__all__ = [
    "AuthenticationError",
    "BrowserManager",
    "detect_auth_barrier",
    "detect_auth_barrier_quick",
    "detect_rate_limit",
    "is_logged_in",
    "wait_for_manual_login",
    "warm_up_browser",
]
