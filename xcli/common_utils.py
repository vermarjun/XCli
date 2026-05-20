"""Small shared helpers used across xcli modules."""

from __future__ import annotations

import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path


def utcnow_iso() -> str:
    """Return the current UTC timestamp in compact ISO-8601 form.

    Example: ``"2026-05-19T12:34:56Z"``
    """
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def slugify_fragment(s: str) -> str:
    """Return a lowercase, file-safe fragment from *s*.

    Non-alphanumeric runs are replaced with ``-``; leading/trailing dashes
    are stripped.

    Example: ``"Hello World!"`` → ``"hello-world"``
    """
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def secure_mkdir(path: Path, mode: int = 0o700) -> None:
    """Create a directory tree with restrictive permissions (0o700 by default).

    Unlike ``Path.mkdir(parents=True, mode=...)``, this applies *mode* to
    every newly created directory in the chain, not just the leaf.

    No-op on Windows (chmod not applied; directory is still created).
    """
    if path.exists() and not path.is_dir():
        raise NotADirectoryError(f"Path exists and is not a directory: {path}")

    missing: list[Path] = []
    p = path
    while not p.exists():
        missing.append(p)
        p = p.parent
    for part in reversed(missing):
        part.mkdir(mode=mode, exist_ok=True)
        if os.name != "nt":
            part.chmod(mode)


def secure_write_text(path: Path, content: str, mode: int = 0o600) -> None:
    """Atomically write *content* to *path* with owner-only permissions.

    Uses a temp file + ``os.replace`` in the same directory so the write is
    atomic on the same filesystem and avoids TOCTOU permission races.

    No-op chmod on Windows.
    """
    secure_mkdir(path.parent)
    fd_int, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd_int, "w") as f:
            f.write(content)
        if os.name != "nt":
            os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
