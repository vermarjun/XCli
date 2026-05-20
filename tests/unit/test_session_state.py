"""Unit tests for xcli.session_state."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

import xcli.config as cfg_module


@pytest.fixture()
def fake_profile_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point config at a temp directory and reset the config singleton."""
    profile_dir = tmp_path / ".xcli" / "profile"
    profile_dir.mkdir(parents=True, mode=0o700)

    monkeypatch.setenv("XCLI_USER_DATA_DIR", str(profile_dir))
    monkeypatch.setattr(cfg_module, "_config", None)

    return profile_dir


class TestPathHelpers:
    def test_get_source_profile_dir(self, fake_profile_dir: Path) -> None:
        from xcli.session_state import get_source_profile_dir

        result = get_source_profile_dir()
        assert result == fake_profile_dir.expanduser()

    def test_auth_root_dir_is_parent(self, fake_profile_dir: Path) -> None:
        from xcli.session_state import auth_root_dir

        root = auth_root_dir()
        assert root == fake_profile_dir.parent.resolve()

    def test_portable_cookie_path(self, fake_profile_dir: Path) -> None:
        from xcli.session_state import portable_cookie_path

        p = portable_cookie_path()
        assert p.name == "cookies.json"
        assert p.parent == fake_profile_dir.parent.resolve()

    def test_source_state_path(self, fake_profile_dir: Path) -> None:
        from xcli.session_state import source_state_path

        p = source_state_path()
        assert p.name == "source-state.json"
        assert p.parent == fake_profile_dir.parent.resolve()


class TestProfileExists:
    def test_empty_dir_returns_false(self, fake_profile_dir: Path) -> None:
        from xcli.session_state import profile_exists

        # profile_dir exists but is empty
        assert not profile_exists()

    def test_non_empty_dir_returns_true(self, fake_profile_dir: Path) -> None:
        from xcli.session_state import profile_exists

        (fake_profile_dir / "sentinel.txt").write_text("x")
        assert profile_exists()

    def test_missing_dir_returns_false(self, tmp_path: Path) -> None:
        from xcli.session_state import profile_exists

        missing = tmp_path / "nonexistent"
        assert not profile_exists(missing)


class TestSourceState:
    def test_write_then_load(self, fake_profile_dir: Path) -> None:
        from xcli.session_state import load_source_state, write_source_state

        state = write_source_state()
        assert state.version == 1
        assert state.login_generation  # UUID4 string

        loaded = load_source_state()
        assert loaded is not None
        assert loaded.login_generation == state.login_generation
        assert loaded.created_at == state.created_at

    def test_login_generation_changes_on_each_write(self, fake_profile_dir: Path) -> None:
        from xcli.session_state import write_source_state

        s1 = write_source_state()
        s2 = write_source_state()
        assert s1.login_generation != s2.login_generation

    def test_load_returns_none_when_missing(self, fake_profile_dir: Path) -> None:
        from xcli.session_state import load_source_state

        result = load_source_state()
        assert result is None

    def test_load_returns_none_on_corrupt_json(self, fake_profile_dir: Path) -> None:
        from xcli.session_state import load_source_state, source_state_path

        state_file = source_state_path()
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text("NOT VALID JSON")
        result = load_source_state()
        assert result is None

    def test_written_file_is_owner_only(self, fake_profile_dir: Path) -> None:
        if os.name == "nt":
            pytest.skip("chmod not enforced on Windows")

        from xcli.session_state import source_state_path, write_source_state

        write_source_state()
        p = source_state_path()
        mode = stat.S_IMODE(p.stat().st_mode)
        assert mode == 0o600, f"expected 0o600, got {oct(mode)}"


class TestClearAuthState:
    def test_moves_not_deletes(self, fake_profile_dir: Path) -> None:
        from xcli.session_state import auth_root_dir, clear_auth_state, write_source_state

        write_source_state()
        root = auth_root_dir()
        assert root.exists()

        result = clear_auth_state()
        assert result is True
        # Root should be gone (moved aside)
        assert not root.exists()
        # But something with the invalid prefix should exist nearby
        parent = root.parent
        invalids = list(parent.glob(".xcli-invalid-*"))
        assert len(invalids) >= 1, "Expected an .xcli-invalid-* directory to be created"

    def test_idempotent_when_nothing_exists(self, fake_profile_dir: Path) -> None:
        from xcli.session_state import auth_root_dir, clear_auth_state

        root = auth_root_dir()
        # Remove the root if it exists from the fixture
        if root.exists():
            import shutil

            shutil.rmtree(root)

        result = clear_auth_state()
        assert result is True  # Nothing to move — should still return True


class TestRuntimeId:
    def test_runtime_id_format(self) -> None:
        from xcli.session_state import runtime_id

        rid = runtime_id()
        parts = rid.split("-")
        assert len(parts) >= 3, f"Expected at least 3 dash-separated parts: {rid}"
        assert parts[-1] in ("host", "container"), f"Unexpected kind: {parts[-1]}"

    def test_runtime_id_deterministic(self) -> None:
        from xcli.session_state import runtime_id

        a = runtime_id()
        b = runtime_id()
        assert a == b


class TestSecureMkdirIntegration:
    @pytest.mark.skipif(os.name == "nt", reason="chmod not supported on Windows")
    def test_new_dir_is_0o700(self, tmp_path: Path) -> None:
        from xcli.common_utils import secure_mkdir

        target = tmp_path / "secret_dir"
        secure_mkdir(target, mode=0o700)
        mode = stat.S_IMODE(target.stat().st_mode)
        assert mode == 0o700, f"expected 0o700, got {oct(mode)}"
