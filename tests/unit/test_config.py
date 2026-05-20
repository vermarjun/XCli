"""Unit tests for xcli.config — env-var precedence, defaults, validation."""

from __future__ import annotations

import os

import pytest

import xcli.config as cfg_module
from xcli.config import AppConfig, BrowserConfig, ConfigurationError, get_config


@pytest.fixture(autouse=True)
def clear_xcli_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove all XCLI_ env vars before each test."""
    for key in list(os.environ):
        if key.startswith("XCLI_"):
            monkeypatch.delenv(key, raising=False)
    # Reset singleton too (conftest already does this, belt-and-suspenders)
    monkeypatch.setattr(cfg_module, "_config", None)


class TestDefaults:
    def test_user_data_dir_default(self) -> None:
        config = get_config()
        assert config.browser.user_data_dir == "~/.xcli/profile"

    def test_headless_default(self) -> None:
        config = get_config()
        assert config.browser.headless is True

    def test_timeout_default(self) -> None:
        config = get_config()
        assert config.browser.default_timeout == 5000

    def test_viewport_default(self) -> None:
        config = get_config()
        assert config.browser.viewport_width == 1280
        assert config.browser.viewport_height == 720

    def test_nav_delay_default(self) -> None:
        config = get_config()
        assert config.nav_delay_seconds == 2.0

    def test_log_level_default(self) -> None:
        config = get_config()
        assert config.log_level == "WARNING"


class TestEnvVarOverrides:
    def test_user_data_dir_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XCLI_USER_DATA_DIR", "/tmp/my-profile")
        monkeypatch.setattr(cfg_module, "_config", None)
        config = get_config()
        assert config.browser.user_data_dir == "/tmp/my-profile"

    def test_headless_false_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XCLI_HEADLESS", "false")
        monkeypatch.setattr(cfg_module, "_config", None)
        config = get_config()
        assert config.browser.headless is False

    def test_headless_true_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XCLI_HEADLESS", "true")
        monkeypatch.setattr(cfg_module, "_config", None)
        config = get_config()
        assert config.browser.headless is True

    def test_headless_0_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XCLI_HEADLESS", "0")
        monkeypatch.setattr(cfg_module, "_config", None)
        config = get_config()
        assert config.browser.headless is False

    def test_log_level_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XCLI_LOG_LEVEL", "DEBUG")
        monkeypatch.setattr(cfg_module, "_config", None)
        config = get_config()
        assert config.log_level == "DEBUG"

    def test_timeout_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XCLI_TIMEOUT_MS", "10000")
        monkeypatch.setattr(cfg_module, "_config", None)
        config = get_config()
        assert config.browser.default_timeout == 10000

    def test_nav_delay_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XCLI_NAV_DELAY_S", "3.5")
        monkeypatch.setattr(cfg_module, "_config", None)
        config = get_config()
        assert config.nav_delay_seconds == 3.5


class TestValidation:
    def test_invalid_timeout_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XCLI_TIMEOUT_MS", "not-a-number")
        monkeypatch.setattr(cfg_module, "_config", None)
        with pytest.raises(ConfigurationError):
            get_config()

    def test_invalid_nav_delay_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XCLI_NAV_DELAY_S", "not-a-number")
        monkeypatch.setattr(cfg_module, "_config", None)
        with pytest.raises(ConfigurationError):
            get_config()

    def test_negative_slow_mo_raises(self) -> None:
        config = BrowserConfig(slow_mo=-1)
        with pytest.raises(ConfigurationError):
            config.validate()

    def test_zero_timeout_raises(self) -> None:
        config = BrowserConfig(default_timeout=0)
        with pytest.raises(ConfigurationError):
            config.validate()

    def test_zero_viewport_raises(self) -> None:
        config = BrowserConfig(viewport_width=0, viewport_height=720)
        with pytest.raises(ConfigurationError):
            config.validate()

    def test_invalid_log_level_raises(self) -> None:
        config = AppConfig(log_level="VERBOSE")
        with pytest.raises(ConfigurationError):
            config.validate()

    def test_negative_nav_delay_raises(self) -> None:
        config = AppConfig(nav_delay_seconds=-1.0)
        with pytest.raises(ConfigurationError):
            config.validate()


class TestChannel:
    def test_channel_default_is_chromium(self) -> None:
        """BrowserConfig.channel should default to 'chromium'."""
        config = get_config()
        assert config.browser.channel == "chromium"

    def test_channel_env_override_chrome(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """XCLI_CHANNEL=chrome should set channel to 'chrome'."""
        monkeypatch.setenv("XCLI_CHANNEL", "chrome")
        monkeypatch.setattr(cfg_module, "_config", None)
        config = get_config()
        assert config.browser.channel == "chrome"

    def test_channel_env_override_msedge(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """XCLI_CHANNEL=msedge should set channel to 'msedge'."""
        monkeypatch.setenv("XCLI_CHANNEL", "msedge")
        monkeypatch.setattr(cfg_module, "_config", None)
        config = get_config()
        assert config.browser.channel == "msedge"

    def test_invalid_channel_raises_configuration_error(self) -> None:
        """An unknown channel value should raise ConfigurationError."""
        from xcli.config import BrowserConfig, ConfigurationError

        config = BrowserConfig(channel="firefox")
        with pytest.raises(ConfigurationError, match="channel"):
            config.validate()

    def test_allowed_channels_all_valid(self) -> None:
        """All declared allowed channels should pass validation."""
        from xcli.config import _ALLOWED_CHANNELS, BrowserConfig

        for ch in _ALLOWED_CHANNELS:
            BrowserConfig(channel=ch).validate()  # should not raise


class TestCaching:
    def test_get_config_returns_same_instance(self) -> None:
        a = get_config()
        b = get_config()
        assert a is b

    def test_reset_config_clears_singleton(self) -> None:
        from xcli.config import reset_config_for_testing

        a = get_config()
        reset_config_for_testing()
        b = get_config()
        assert a is not b
