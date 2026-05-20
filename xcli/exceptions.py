"""XCli exception hierarchy.

All public exceptions carry an ``exit_code`` class attribute so the CLI layer
can call ``raise typer.Exit(code=exc.exit_code)`` without importing the full
hierarchy everywhere.

Exit code conventions (mirrors plan §10):
    0  — success
    1  — generic / unexpected error
    2  — authentication required (analogous to sshd / HTTP 401)
    3  — rate-limited or soft-blocked (retry after delay)
    4  — target profile not found / suspended / protected
"""

from __future__ import annotations


class XCliError(Exception):
    """Base class for all xcli errors."""

    exit_code: int = 1


class AuthenticationError(XCliError):
    """Session is missing, expired, or invalid.

    Hint: run ``xcli login`` to establish a new session.
    """

    exit_code: int = 2


class RateLimitError(XCliError):
    """X.com has rate-limited or soft-blocked the current session.

    Back off for ``suggested_wait_seconds`` before retrying.
    """

    exit_code: int = 3

    def __init__(self, message: str = "Rate limit detected.", suggested_wait_seconds: int = 30):
        super().__init__(message)
        self.suggested_wait_seconds = suggested_wait_seconds


class SoftBlockError(XCliError):
    """X.com returned a 'Something went wrong' / 'Try reloading' page.

    A softer form of rate-limiting; usually clears after a short wait.
    """

    exit_code: int = 3


class ProfileNotFoundError(XCliError):
    """The requested X profile does not exist (404 / 'This account doesn't exist')."""

    exit_code: int = 4


class ProfileSuspendedError(XCliError):
    """The requested X profile has been suspended."""

    exit_code: int = 4


class ProfileProtectedError(XCliError):
    """The requested X profile is protected (tweets visible to followers only)."""

    exit_code: int = 4


class NetworkError(XCliError):
    """A network or browser-level failure occurred."""

    exit_code: int = 1


class ConfigurationError(XCliError):
    """Invalid or missing configuration value."""

    exit_code: int = 1


class BrowserSetupError(XCliError):
    """Failed to start or configure the Patchright browser."""

    exit_code: int = 1
