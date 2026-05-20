"""Runtime-aware authentication state for xcli.

Mirrors the LinkedIn MCP Server's session_state.py shape, adapted for X.

On-disk layout:
    ~/.xcli/                  ← auth_root_dir()
    ~/.xcli/profile/          ← get_source_profile_dir() (persistent Chrome profile, 0o700)
    ~/.xcli/cookies.json      ← portable_cookie_path()   (X auth cookies, 0o600)
    ~/.xcli/source-state.json ← source_state_path()      (session metadata, 0o600)

Container detection: ``runtime_id()`` returns ``<os>-<arch>-host`` for Phase 0/1;
full container detection (via /.dockerenv, /proc/1/cgroup etc.) is stubbed for v1
and documented as a Phase 4 extension point.
"""

from __future__ import annotations

import json
import logging
import platform
import shutil
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any
from uuid import uuid4

from xcli.common_utils import secure_write_text, utcnow_iso
from xcli.config import get_config

logger = logging.getLogger(__name__)

_SOURCE_STATE_FILE = "source-state.json"

_SOURCE_STATE_FIELDS = frozenset(
    field.name
    for field in fields(
        # forward-declared below; we'll recompute after class definition
        type("_Placeholder", (), {"__dataclass_fields__": {}})
    )
)


@dataclass
class SourceState:
    """Metadata written after a successful ``xcli login`` run."""

    version: int
    source_runtime_id: str
    login_generation: str
    created_at: str
    profile_path: str
    cookies_path: str


# Re-compute the field set now that the dataclass exists
_SOURCE_STATE_FIELDS = frozenset(f.name for f in fields(SourceState))


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def auth_root_dir() -> Path:
    """Return the root directory that contains all xcli auth artifacts.

    This is the *parent* of the profile directory, i.e. ``~/.xcli/``.
    """
    return Path(get_config().browser.user_data_dir).expanduser().resolve().parent


def get_source_profile_dir() -> Path:
    """Return the configured source profile directory (``~/.xcli/profile``)."""
    return Path(get_config().browser.user_data_dir).expanduser()


def portable_cookie_path() -> Path:
    """Return the portable cookie export path (``~/.xcli/cookies.json``)."""
    return auth_root_dir() / "cookies.json"


def source_state_path() -> Path:
    """Return the source session metadata path (``~/.xcli/source-state.json``)."""
    return auth_root_dir() / _SOURCE_STATE_FILE


# ---------------------------------------------------------------------------
# Runtime identity
# ---------------------------------------------------------------------------


def runtime_id() -> str:
    """Return a deterministic identity string for the current runtime.

    Format: ``<os>-<arch>-host``

    Container detection is intentionally stubbed for v1 (always returns "host").
    Full /.dockerenv / cgroup detection is a Phase 4 extension point.
    """
    os_name = _normalize_os(platform.system())
    arch = _normalize_arch(platform.machine())
    kind = "container" if _is_container_runtime() else "host"
    return f"{os_name}-{arch}-{kind}"


def _normalize_os(system: str) -> str:
    mapping = {"Darwin": "macos", "Linux": "linux", "Windows": "windows"}
    return mapping.get(system, system.lower() or "unknown")


def _normalize_arch(machine: str) -> str:
    value = machine.lower()
    if value in {"x86_64", "amd64"}:
        return "amd64"
    if value in {"arm64", "aarch64"}:
        return "arm64"
    return value or "unknown"


def _is_container_runtime() -> bool:
    """Detect common container runtimes (Docker, Podman, containerd).

    Stubbed for v1: always returns False on platforms without /proc.
    """
    for probe in (Path("/.dockerenv"), Path("/run/.containerenv"), Path("/run/containerenv")):
        if probe.exists():
            return True

    markers = ("docker", "containerd", "kubepods", "podman", "libpod")
    for cgroup in (Path("/proc/1/cgroup"), Path("/proc/self/cgroup")):
        if cgroup.exists():
            try:
                text = cgroup.read_text(encoding="utf-8", errors="ignore").lower()
                if any(m in text for m in markers):
                    return True
            except OSError:
                pass

    return False


# ---------------------------------------------------------------------------
# Profile existence
# ---------------------------------------------------------------------------


def profile_exists(profile_dir: Path | None = None) -> bool:
    """Return True if the browser profile directory exists and is non-empty."""
    d = (profile_dir or get_source_profile_dir()).expanduser()
    return d.is_dir() and any(d.iterdir())


# ---------------------------------------------------------------------------
# Source-state read / write
# ---------------------------------------------------------------------------


def load_source_state() -> SourceState | None:
    """Load the source session metadata if present; return None on missing/corrupt."""
    data = _load_json(source_state_path())
    if not data:
        return None
    try:
        return SourceState(**{k: v for k, v in data.items() if k in _SOURCE_STATE_FIELDS})
    except TypeError:
        logger.warning("Ignoring invalid source-state.json")
        return None


def write_source_state() -> SourceState:
    """Write a fresh source session after a successful login.

    Bumps ``login_generation`` (UUID4) so downstream runtime profiles can detect
    staleness.
    """
    profile_dir = get_source_profile_dir().expanduser().resolve()
    state = SourceState(
        version=1,
        source_runtime_id=runtime_id(),
        login_generation=str(uuid4()),
        created_at=utcnow_iso(),
        profile_path=str(profile_dir),
        cookies_path=str(portable_cookie_path()),
    )
    _write_json(source_state_path(), asdict(state))
    return state


def clear_auth_state() -> bool:
    """Move ``~/.xcli/`` aside to ``~/.xcli-invalid-<ts>/`` rather than deleting.

    This preserves the profile for manual recovery.  Returns True if the move
    succeeded (or there was nothing to move).
    """
    root = auth_root_dir()
    if not root.exists():
        return True

    ts = utcnow_iso().replace(":", "-").replace("T", "-")
    destination = root.parent / f".xcli-invalid-{ts}"
    try:
        shutil.move(str(root), str(destination))
        logger.info("Moved auth state aside to %s", destination)
        return True
    except OSError as exc:
        logger.warning("Could not move auth state from %s to %s: %s", root, destination, exc)
        return False


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        logger.warning("Ignoring unreadable auth state file: %s", path)
        return None
    if not isinstance(data, dict):
        logger.warning("Ignoring malformed auth state file: %s", path)
        return None
    return data


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    secure_write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")
