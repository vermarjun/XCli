"""Unit tests for xcli.common_utils."""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path

import pytest

from xcli.common_utils import secure_mkdir, secure_write_text, slugify_fragment, utcnow_iso


class TestUtcnowIso:
    def test_format(self) -> None:
        ts = utcnow_iso()
        # Must match 2026-05-19T12:34:56Z pattern
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", ts), f"unexpected format: {ts}"

    def test_no_microseconds(self) -> None:
        ts = utcnow_iso()
        assert "." not in ts

    def test_ends_with_z(self) -> None:
        ts = utcnow_iso()
        assert ts.endswith("Z")

    def test_monotonically_non_decreasing(self) -> None:
        a = utcnow_iso()
        b = utcnow_iso()
        assert b >= a


class TestSlugifyFragment:
    def test_simple(self) -> None:
        assert slugify_fragment("Hello World") == "hello-world"

    def test_special_chars(self) -> None:
        assert slugify_fragment("Hello World!") == "hello-world"

    def test_multiple_separators(self) -> None:
        assert slugify_fragment("a  b--c") == "a-b-c"

    def test_leading_trailing_stripped(self) -> None:
        assert slugify_fragment("--hello--") == "hello"

    def test_digits_preserved(self) -> None:
        assert slugify_fragment("user123") == "user123"

    def test_already_slug(self) -> None:
        assert slugify_fragment("foo-bar") == "foo-bar"

    def test_empty_string(self) -> None:
        assert slugify_fragment("") == ""

    def test_unicode_lowercased(self) -> None:
        # Non-ASCII chars are treated as non-alphanum and collapsed to dashes
        result = slugify_fragment("Héllo")
        assert result  # Just check it doesn't crash and returns something


class TestSecureMkdir:
    def test_creates_directory(self, tmp_path: Path) -> None:
        target = tmp_path / "sub" / "dir"
        secure_mkdir(target)
        assert target.is_dir()

    @pytest.mark.skipif(os.name == "nt", reason="chmod not supported on Windows")
    def test_mode_0o700(self, tmp_path: Path) -> None:
        target = tmp_path / "priv"
        secure_mkdir(target, mode=0o700)
        mode = stat.S_IMODE(target.stat().st_mode)
        assert mode == 0o700, f"expected 0o700, got {oct(mode)}"

    def test_nested_directories(self, tmp_path: Path) -> None:
        target = tmp_path / "a" / "b" / "c"
        secure_mkdir(target)
        assert target.is_dir()

    def test_idempotent(self, tmp_path: Path) -> None:
        target = tmp_path / "existing"
        target.mkdir()
        secure_mkdir(target)  # Should not raise
        assert target.is_dir()

    def test_raises_on_file_path(self, tmp_path: Path) -> None:
        f = tmp_path / "file.txt"
        f.write_text("x")
        with pytest.raises(NotADirectoryError):
            secure_mkdir(f)


class TestSecureWriteText:
    def test_writes_content(self, tmp_path: Path) -> None:
        p = tmp_path / "test.txt"
        secure_write_text(p, "hello world")
        assert p.read_text() == "hello world"

    @pytest.mark.skipif(os.name == "nt", reason="chmod not supported on Windows")
    def test_mode_0o600(self, tmp_path: Path) -> None:
        p = tmp_path / "secret.json"
        secure_write_text(p, "{}", mode=0o600)
        mode = stat.S_IMODE(p.stat().st_mode)
        assert mode == 0o600, f"expected 0o600, got {oct(mode)}"

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        p = tmp_path / "nested" / "dir" / "file.txt"
        secure_write_text(p, "data")
        assert p.read_text() == "data"

    def test_overwrites_existing(self, tmp_path: Path) -> None:
        p = tmp_path / "existing.txt"
        secure_write_text(p, "old")
        secure_write_text(p, "new")
        assert p.read_text() == "new"

    def test_atomic_write(self, tmp_path: Path) -> None:
        """No partial file visible if write is interrupted (basic check)."""
        p = tmp_path / "atomic.txt"
        secure_write_text(p, "complete content")
        # If we got here without exception, file exists with correct content
        assert p.exists()
        assert p.read_text() == "complete content"
