"""Configuration schema and loader for xcli.

Environment variable prefix: ``XCLI_``

Load order (highest → lowest priority):
    1. Environment variables (``XCLI_*``)
    2. ``.env`` file in cwd (loaded once via python-dotenv)
    3. Hard-coded defaults
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Load .env on module import (no-op if file absent)
load_dotenv()

logger = logging.getLogger(__name__)

_TRUTHY = {"1", "true", "yes", "on"}
_FALSY = {"0", "false", "no", "off"}


class ConfigurationError(Exception):
    """Raised when configuration validation fails."""


_ALLOWED_CHANNELS: frozenset[str] = frozenset(
    {"chromium", "chrome", "chrome-beta", "chrome-dev", "msedge"}
)


@dataclass
class BrowserConfig:
    """Browser-related settings."""

    headless: bool = True
    slow_mo: int = 0  # ms between browser actions (debugging)
    user_agent: str | None = None
    viewport_width: int = 1280
    viewport_height: int = 720
    default_timeout: int = 5000  # ms for page operations
    chrome_path: str | None = None
    user_data_dir: str = "~/.xcli/profile"
    jitter_pct: float = 0.2  # fractional jitter applied to nav delays (0.0 = off, 1.0 = ±100%)
    channel: str = "chromium"
    # Allowed: "chromium" (bundled Patchright default), "chrome", "chrome-beta",
    # "chrome-dev", "msedge".  Using "chrome" or similar routes through the
    # user's installed browser, which has real plugins and real WebGL via GPU —
    # eliminating the three top headless tells (HeadlessChrome UA, WebGL
    # OffScreen renderer, Plugins Length 0).  CLI precedence: --channel >
    # XCLI_CHANNEL env var > this default.

    def validate(self) -> None:
        """Validate browser configuration values."""
        if self.slow_mo < 0:
            raise ConfigurationError(f"slow_mo must be non-negative, got {self.slow_mo}")
        if self.default_timeout <= 0:
            raise ConfigurationError(
                f"default_timeout must be positive, got {self.default_timeout}"
            )
        if self.viewport_width <= 0 or self.viewport_height <= 0:
            raise ConfigurationError(
                f"viewport dimensions must be positive, got "
                f"{self.viewport_width}x{self.viewport_height}"
            )
        if not (0.0 <= self.jitter_pct <= 1.0):
            raise ConfigurationError(
                f"jitter_pct must be between 0.0 and 1.0, got {self.jitter_pct}"
            )
        if self.channel not in _ALLOWED_CHANNELS:
            raise ConfigurationError(
                f"channel must be one of {sorted(_ALLOWED_CHANNELS)}, got '{self.channel}'"
            )
        if self.chrome_path:
            chrome = Path(self.chrome_path)
            if not chrome.exists():
                raise ConfigurationError(f"chrome_path '{self.chrome_path}' does not exist")
            if not chrome.is_file():
                raise ConfigurationError(f"chrome_path '{self.chrome_path}' is not a file")


@dataclass
class AppConfig:
    """Top-level application configuration."""

    browser: BrowserConfig = field(default_factory=BrowserConfig)
    log_level: str = "WARNING"
    nav_delay_seconds: float = 2.0

    def validate(self) -> None:
        """Validate all configuration values."""
        self.browser.validate()
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR"}
        if self.log_level not in valid_levels:
            raise ConfigurationError(
                f"log_level must be one of {valid_levels}, got '{self.log_level}'"
            )
        if self.nav_delay_seconds < 0:
            raise ConfigurationError(
                f"nav_delay_seconds must be non-negative, got {self.nav_delay_seconds}"
            )


# Module-level singleton — reset via reset_config_for_testing()
_config: AppConfig | None = None


def get_config() -> AppConfig:
    """Return (and lazily create) the cached application configuration."""
    global _config
    if _config is None:
        _config = _load_config()
    return _config


def reset_config_for_testing() -> None:
    """Reset the cached config singleton. For use in tests only."""
    global _config
    _config = None


# ---------------------------------------------------------------------------
# Internal loader
# ---------------------------------------------------------------------------


def _load_config() -> AppConfig:
    config = AppConfig()
    _apply_env(config)
    config.validate()
    return config


def _apply_env(config: AppConfig) -> None:
    """Override defaults with ``XCLI_*`` environment variables."""

    if v := os.environ.get("XCLI_USER_DATA_DIR"):
        config.browser.user_data_dir = v

    if v := os.environ.get("XCLI_HEADLESS"):
        low = v.strip().lower()
        if low in _FALSY:
            config.browser.headless = False
        elif low in _TRUTHY:
            config.browser.headless = True

    if v := os.environ.get("XCLI_LOG_LEVEL"):
        config.log_level = v.strip().upper()

    if v := os.environ.get("XCLI_TIMEOUT_MS"):
        try:
            config.browser.default_timeout = int(v)
        except ValueError:
            raise ConfigurationError(f"XCLI_TIMEOUT_MS must be an integer, got '{v}'")

    if v := os.environ.get("XCLI_NAV_DELAY_S"):
        try:
            config.nav_delay_seconds = float(v)
        except ValueError:
            raise ConfigurationError(f"XCLI_NAV_DELAY_S must be a float, got '{v}'")

    if v := os.environ.get("XCLI_CHROME_PATH"):
        config.browser.chrome_path = v

    if v := os.environ.get("XCLI_JITTER_PCT"):
        try:
            config.browser.jitter_pct = float(v)
        except ValueError:
            raise ConfigurationError(f"XCLI_JITTER_PCT must be a float, got '{v}'")

    if v := os.environ.get("XCLI_CHANNEL"):
        config.browser.channel = v.strip()
