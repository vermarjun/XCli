"""Shared pytest fixtures for xcli tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture()
def tmp_profile_dir(tmp_path: Path) -> Path:
    """Return a temporary directory for use as a browser profile."""
    d = tmp_path / "xcli-test-profile"
    d.mkdir(mode=0o700)
    return d


@pytest.fixture(autouse=True)
def reset_singletons(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset config and browser singletons between tests for isolation."""
    # Reset config singleton
    import xcli.config as cfg_module

    monkeypatch.setattr(cfg_module, "_config", None)

    # Reset browser singleton
    import xcli.drivers.browser as drv_module

    monkeypatch.setattr(drv_module, "_browser", None)
    monkeypatch.setattr(drv_module, "_headless", True)

    yield

    # Cleanup after test (belt-and-suspenders)
    cfg_module._config = None
    drv_module._browser = None
    drv_module._headless = True


@pytest.fixture()
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove all XCLI_ environment variables for a clean config baseline."""
    for key in list(os.environ):
        if key.startswith("XCLI_"):
            monkeypatch.delenv(key, raising=False)
