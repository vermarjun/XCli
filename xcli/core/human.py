"""Human-paced browser interaction primitives.

Realistic wheel-event chunking, read pauses, and variable scroll direction
to defeat behavioral telemetry that flags uniform scroll-and-sleep loops.

Wheel-event distributions are calibrated against reference measurements of:
- Apple Magic Trackpad 2 (small frequent deltas, smooth inertia)
- Logitech MX Master 3 wheel (medium discrete deltas at detent clicks)
- Apple Magic Mouse touch surface (variable inertial scrolls)

Public API:
    human_scroll_burst(page, total_distance, *, config, rng) -> int
        Emits a realistic sequence of wheel events summing approximately to
        ``total_distance``. Returns the actual cumulative distance emitted.
        Sometimes includes an upward overshoot (~10% of calls).

    human_read_pause(seconds=None, *, intent="browse", config, rng) -> float
        Sleeps for a content-density-aware duration. ``intent`` is one of
        "browse" (default 0.8-2.0s), "deep" (1.5-3.5s for thread OP first read),
        "skim" (0.4-1.0s for quick passes). Returns actual seconds slept.

    default_human_pace() -> HumanPaceConfig
        Factory that reads ``XCLI_HUMAN_PACE`` env var. Returns
        ``HumanPaceConfig(enabled=False)`` when the var is set to "0", "false",
        or "no". Use this in production code; pass a custom config in tests.

    HumanPaceConfig dataclass: enabled, jitter_pct, profile_mix
        Allows callers to disable jittering for hermetic tests.
"""

from __future__ import annotations

import asyncio
import os
import random
from dataclasses import dataclass, field
from typing import Literal

# --- Reference distributions ---

# Each entry is (deltaY, gap_after_ms). One "burst" is a sequence of these
# that together approximate the requested total_distance.
#
# Trackpad: frequent small deltas with short gaps. 18-30 events per ~1500.
_TRACKPAD_DELTAS = [
    # 24 events totaling ~1500
    (35, 14),
    (62, 22),
    (88, 31),
    (110, 45),
    (95, 38),
    (75, 28),
    (50, 20),
    (40, 16),
    (72, 26),
    (95, 40),
    (130, 55),
    (98, 42),
    (60, 22),
    (85, 33),
    (70, 28),
    (105, 48),
    (55, 21),
    (48, 19),
    (78, 30),
    (40, 15),
    (45, 18),
    (62, 24),
    (38, 14),
    (35, 12),
]
# Wheel: bigger discrete deltas with longer gaps. 5-10 events per ~1500.
_WHEEL_DELTAS = [
    # 7 events totaling ~1500
    (180, 65),
    (240, 90),
    (380, 110),
    (200, 75),
    (340, 95),
    (160, 60),
    (0, 50),
]

# --- Config ---


@dataclass
class HumanPaceConfig:
    enabled: bool = True
    jitter_pct: float = 0.20
    profile_mix: dict[str, float] = field(default_factory=lambda: {"trackpad": 0.6, "wheel": 0.4})
    overshoot_probability: float = 0.10
    reverse_overshoot_deltaY: tuple[int, int] = (150, 400)  # range


def default_human_pace() -> HumanPaceConfig:
    """Return a HumanPaceConfig based on the XCLI_HUMAN_PACE environment variable.

    When ``XCLI_HUMAN_PACE`` is set to "0", "false", or "no" (case-insensitive),
    returns ``HumanPaceConfig(enabled=False)`` for hermetic test use.
    Otherwise returns a default-enabled config.

    This function reads the environment at call time — no module-level side effects.
    """
    _DISABLED_VALUES = {"0", "false", "no"}
    raw = os.getenv("XCLI_HUMAN_PACE", "1").strip().lower()
    enabled = raw not in _DISABLED_VALUES
    return HumanPaceConfig(enabled=enabled)


# --- Core primitives ---


def _jitter(value: float, pct: float, rng: random.Random) -> float:
    """Apply ±pct jitter to value. rng injected for determinism."""
    if pct <= 0:
        return value
    return value * (1.0 + rng.uniform(-pct, pct))


def _select_profile(mix: dict[str, float], rng: random.Random) -> list[tuple[int, int]]:
    """Choose between trackpad / wheel profiles per the mix."""
    r = rng.random()
    if r < mix.get("trackpad", 0.5):
        return _TRACKPAD_DELTAS
    return _WHEEL_DELTAS


async def human_scroll_burst(
    page: object,
    total_distance: int = 1500,
    *,
    config: HumanPaceConfig | None = None,
    rng: random.Random | None = None,
) -> int:
    """Emit a realistic wheel-event burst summing to ~total_distance.

    Args:
        page:           Active Patchright page (duck-typed — needs mouse.wheel).
        total_distance: Approximate total scroll distance in pixels.
        config:         HumanPaceConfig; defaults to ``HumanPaceConfig()`` if None.
        rng:            Optional seeded random.Random for deterministic tests.

    Returns:
        The actual distance scrolled (signed; can include overshoot reversal).
    """
    cfg = config or HumanPaceConfig()
    if not cfg.enabled:
        # Fall back to single wheel event (the old behavior)
        await page.mouse.wheel(0, total_distance)  # type: ignore[attr-defined]
        return total_distance
    rng = rng or random.Random()

    profile = _select_profile(cfg.profile_mix, rng)
    # Compute scale factor so the profile totals ≈ total_distance
    profile_total = sum(d for d, _ in profile) or 1
    scale = total_distance / profile_total

    emitted = 0
    for i, (delta_base, gap_ms_base) in enumerate(profile):
        # Jittered delta (rounded to int — wheel events are integer-only)
        delta = max(1, int(_jitter(delta_base * scale, cfg.jitter_pct, rng)))
        # Jittered gap
        gap_s = max(0.005, _jitter(gap_ms_base / 1000.0, cfg.jitter_pct, rng))

        await page.mouse.wheel(0, delta)  # type: ignore[attr-defined]
        emitted += delta
        # Don't sleep after the last event in the burst — the caller will
        # follow with human_read_pause anyway
        if i < len(profile) - 1:
            await asyncio.sleep(gap_s)

    # Occasional reverse overshoot — real users scroll past and come back
    if rng.random() < cfg.overshoot_probability:
        lo, hi = cfg.reverse_overshoot_deltaY
        overshoot = rng.randint(lo, hi)
        await asyncio.sleep(_jitter(0.12, cfg.jitter_pct, rng))
        await page.mouse.wheel(0, -overshoot)  # type: ignore[attr-defined]
        emitted -= overshoot

    return emitted


async def human_read_pause(
    seconds: float | None = None,
    *,
    intent: Literal["browse", "deep", "skim"] = "browse",
    config: HumanPaceConfig | None = None,
    rng: random.Random | None = None,
) -> float:
    """Sleep for a realistic read-pause duration.

    Args:
        seconds: If provided, sleep for approximately this many seconds (with
                 jitter applied). If None, choose duration based on ``intent``.
        intent:  One of "browse" (0.8-2.0s), "deep" (1.5-3.5s), "skim" (0.4-1.0s).
                 Only used when ``seconds`` is None.
        config:  HumanPaceConfig; defaults to ``HumanPaceConfig()`` if None.
        rng:     Optional seeded random.Random for deterministic tests.

    Returns:
        The actual number of seconds slept.
    """
    cfg = config or HumanPaceConfig()
    if not cfg.enabled:
        # Fall back to the old 1.0s gap
        await asyncio.sleep(seconds if seconds is not None else 1.0)
        return seconds or 1.0
    rng = rng or random.Random()

    if seconds is not None:
        actual = max(0.05, _jitter(seconds, cfg.jitter_pct, rng))
    else:
        ranges = {"browse": (0.8, 2.0), "deep": (1.5, 3.5), "skim": (0.4, 1.0)}
        lo, hi = ranges[intent]
        actual = rng.uniform(lo, hi)

    await asyncio.sleep(actual)
    return actual
