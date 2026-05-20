"""Unit tests for xcli.exceptions — exit_code attribute correctness."""

import pytest

from xcli.exceptions import (
    AuthenticationError,
    BrowserSetupError,
    ConfigurationError,
    NetworkError,
    ProfileNotFoundError,
    ProfileProtectedError,
    ProfileSuspendedError,
    RateLimitError,
    SoftBlockError,
    XCliError,
)


def test_base_exit_code() -> None:
    assert XCliError.exit_code == 1


def test_authentication_error_exit_code() -> None:
    assert AuthenticationError.exit_code == 2
    exc = AuthenticationError("bad session")
    assert exc.exit_code == 2
    assert "bad session" in str(exc)


def test_rate_limit_error_exit_code() -> None:
    assert RateLimitError.exit_code == 3
    exc = RateLimitError("rate limited", suggested_wait_seconds=60)
    assert exc.exit_code == 3
    assert exc.suggested_wait_seconds == 60


def test_rate_limit_error_default_wait() -> None:
    exc = RateLimitError()
    assert exc.suggested_wait_seconds == 30


def test_soft_block_error_exit_code() -> None:
    assert SoftBlockError.exit_code == 3


def test_profile_not_found_exit_code() -> None:
    assert ProfileNotFoundError.exit_code == 4


def test_profile_suspended_exit_code() -> None:
    assert ProfileSuspendedError.exit_code == 4


def test_profile_protected_exit_code() -> None:
    assert ProfileProtectedError.exit_code == 4


def test_network_error_exit_code() -> None:
    assert NetworkError.exit_code == 1


def test_configuration_error_exit_code() -> None:
    assert ConfigurationError.exit_code == 1


def test_browser_setup_error_exit_code() -> None:
    assert BrowserSetupError.exit_code == 1


def test_all_are_subclasses_of_xcli_error() -> None:
    for cls in (
        AuthenticationError,
        RateLimitError,
        SoftBlockError,
        ProfileNotFoundError,
        ProfileSuspendedError,
        ProfileProtectedError,
        NetworkError,
        ConfigurationError,
        BrowserSetupError,
    ):
        assert issubclass(cls, XCliError), f"{cls} should subclass XCliError"


def test_rate_limit_is_catchable_as_xcli_error() -> None:
    with pytest.raises(XCliError):
        raise RateLimitError("test")
