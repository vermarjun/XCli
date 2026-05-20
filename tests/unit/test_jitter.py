"""Unit tests for the _jitter helper in xcli.scraping.extractor.

Property tests confirm:
  - pct=0.0 → exact base value (no randomness)
  - pct=0.2, base=1.0 → result in [0.8, 1.2] over 5 000 samples
  - pct=1.0, base=2.0 → result in [0.0, 4.0] over 5 000 samples
  - result is always non-negative (never goes below 0.0)
"""

from __future__ import annotations

import pytest

from xcli.scraping.extractor import _jitter

# ---------------------------------------------------------------------------
# Deterministic cases
# ---------------------------------------------------------------------------


def test_jitter_zero_pct_returns_exact_base() -> None:
    """With pct=0.0, _jitter must return the base value unchanged."""
    assert _jitter(2.0, 0.0) == 2.0
    assert _jitter(0.0, 0.0) == 0.0
    assert _jitter(10.0, 0.0) == 10.0


@pytest.mark.parametrize("base", [0.0, 0.5, 1.0, 2.0, 5.0])
def test_jitter_zero_pct_parametrize(base: float) -> None:
    """Parametrized check: any base with pct=0.0 returns base exactly."""
    assert _jitter(base, 0.0) == base


# ---------------------------------------------------------------------------
# Distribution / range tests (5 000 samples each)
# ---------------------------------------------------------------------------

SAMPLES = 5_000


def test_jitter_pct_02_base_10_range() -> None:
    """pct=0.2, base=1.0 → all samples in [0.8, 1.2]."""
    results = [_jitter(1.0, 0.2) for _ in range(SAMPLES)]
    for v in results:
        assert 0.8 <= v <= 1.2, f"Value {v} out of expected range [0.8, 1.2]"


def test_jitter_pct_10_base_20_range() -> None:
    """pct=1.0, base=2.0 → all samples in [0.0, 4.0]."""
    results = [_jitter(2.0, 1.0) for _ in range(SAMPLES)]
    for v in results:
        assert 0.0 <= v <= 4.0, f"Value {v} out of expected range [0.0, 4.0]"


def test_jitter_pct_05_base_10() -> None:
    """pct=0.5, base=1.0 → all samples in [0.5, 1.5]."""
    results = [_jitter(1.0, 0.5) for _ in range(SAMPLES)]
    for v in results:
        assert 0.5 <= v <= 1.5, f"Value {v} out of expected range [0.5, 1.5]"


def test_jitter_never_negative() -> None:
    """_jitter must never return a negative value, even at pct=1.0 with a small base."""
    results = [_jitter(0.001, 1.0) for _ in range(SAMPLES)]
    for v in results:
        assert v >= 0.0, f"Got negative jitter result: {v}"


def test_jitter_mean_approximately_base() -> None:
    """With enough samples the mean should converge close to the base (within 5%)."""
    base = 2.0
    results = [_jitter(base, 0.2) for _ in range(SAMPLES)]
    mean = sum(results) / len(results)
    assert abs(mean - base) / base < 0.05, f"Mean {mean:.4f} is more than 5% away from base {base}"


# ---------------------------------------------------------------------------
# Config integration: jitter_pct is readable / validates
# ---------------------------------------------------------------------------


def test_config_jitter_pct_default() -> None:
    """Default BrowserConfig should have jitter_pct=0.2."""
    from xcli.config import BrowserConfig

    bc = BrowserConfig()
    assert bc.jitter_pct == 0.2


def test_config_jitter_pct_validate_valid_values() -> None:
    """jitter_pct values 0.0 and 1.0 are the valid boundary values."""
    from xcli.config import BrowserConfig

    bc0 = BrowserConfig(jitter_pct=0.0)
    bc0.validate()  # must not raise

    bc1 = BrowserConfig(jitter_pct=1.0)
    bc1.validate()  # must not raise

    bc05 = BrowserConfig(jitter_pct=0.5)
    bc05.validate()  # must not raise


def test_config_jitter_pct_validate_out_of_range() -> None:
    """jitter_pct outside [0, 1] must raise ConfigurationError."""
    from xcli.config import BrowserConfig, ConfigurationError

    bc_low = BrowserConfig(jitter_pct=-0.1)
    with pytest.raises(ConfigurationError, match="jitter_pct"):
        bc_low.validate()

    bc_high = BrowserConfig(jitter_pct=1.1)
    with pytest.raises(ConfigurationError, match="jitter_pct"):
        bc_high.validate()


def test_config_env_jitter_pct(monkeypatch: pytest.MonkeyPatch) -> None:
    """XCLI_JITTER_PCT env var should wire into BrowserConfig.jitter_pct."""
    import xcli.config as cfg_mod

    monkeypatch.setenv("XCLI_JITTER_PCT", "0.3")
    cfg_mod.reset_config_for_testing()
    try:
        config = cfg_mod.get_config()
        assert config.browser.jitter_pct == pytest.approx(0.3)
    finally:
        cfg_mod.reset_config_for_testing()
        monkeypatch.delenv("XCLI_JITTER_PCT", raising=False)


def test_config_env_jitter_pct_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    """XCLI_JITTER_PCT with a non-float value should raise ConfigurationError."""
    import xcli.config as cfg_mod
    from xcli.config import ConfigurationError

    monkeypatch.setenv("XCLI_JITTER_PCT", "not-a-float")
    cfg_mod.reset_config_for_testing()
    try:
        with pytest.raises(ConfigurationError, match="XCLI_JITTER_PCT"):
            cfg_mod.get_config()
    finally:
        cfg_mod.reset_config_for_testing()
        monkeypatch.delenv("XCLI_JITTER_PCT", raising=False)
