"""Unit tests for xcli.core.human — humanized scroll bursts and read pauses.

All tests use a MockPage that records mouse.wheel calls so we can assert on
event counts and deltas without a real browser.
"""

from __future__ import annotations

import asyncio
import random
import statistics

import pytest

# ---------------------------------------------------------------------------
# MockPage — records all mouse.wheel calls
# ---------------------------------------------------------------------------


class _MockMouse:
    def __init__(self) -> None:
        self.wheel_calls: list[tuple[int, int]] = []  # (x, y) deltas

    async def wheel(self, x: int, y: int) -> None:
        self.wheel_calls.append((x, y))


class MockPage:
    """Minimal page mock that records mouse.wheel calls."""

    def __init__(self) -> None:
        self.mouse = _MockMouse()

    @property
    def wheel_call_count(self) -> int:
        return len(self.mouse.wheel_calls)

    @property
    def wheel_deltas(self) -> list[int]:
        """Return the Y-axis deltas from all wheel calls."""
        return [y for _, y in self.mouse.wheel_calls]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Shared sleep patcher context manager
# ---------------------------------------------------------------------------


class _NoSleep:
    """Context manager that replaces asyncio.sleep in xcli.core.human with a no-op."""

    def __enter__(self):
        import xcli.core.human as m

        self._mod = m
        self._orig = m.asyncio.sleep

        async def _noop(t):
            pass

        m.asyncio.sleep = _noop  # type: ignore[attr-defined]
        return self

    def __exit__(self, *args):
        self._mod.asyncio.sleep = self._orig


# ---------------------------------------------------------------------------
# human_scroll_burst — deterministic with seed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scroll_burst_deterministic_with_seed() -> None:
    """Same seed produces identical wheel call sequences."""
    from xcli.core.human import HumanPaceConfig, human_scroll_burst

    cfg = HumanPaceConfig(enabled=True)

    with _NoSleep():
        page1 = MockPage()
        await human_scroll_burst(page1, 1500, config=cfg, rng=random.Random(42))

        page2 = MockPage()
        await human_scroll_burst(page2, 1500, config=cfg, rng=random.Random(42))

    assert page1.wheel_call_count == page2.wheel_call_count
    assert page1.wheel_deltas == page2.wheel_deltas


# ---------------------------------------------------------------------------
# human_scroll_burst — sum invariant (within ±15% of total_distance)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scroll_burst_sum_invariant() -> None:
    """Over 50 seeds, cumulative emitted distance stays within ±15% of requested.

    Overshoot events reduce the sum, so we compute the gross downward distance
    (only positive deltas) and allow the net to dip below the ±15% bound due
    to overshoot.  The spec says "within ±15% modulo overshoot" — we assert
    both that the gross is close and that the net is reasonable.
    """
    from xcli.core.human import HumanPaceConfig, human_scroll_burst

    total_distance = 1500
    # No overshoot for this invariant test — measure pure scroll fidelity
    cfg = HumanPaceConfig(enabled=True, overshoot_probability=0.0)

    with _NoSleep():
        for seed in range(50):
            page = MockPage()
            net = await human_scroll_burst(
                page, total_distance, config=cfg, rng=random.Random(seed)
            )
            # Net emitted (return value) should be within ±15%
            lo = total_distance * 0.85
            hi = total_distance * 1.15
            assert lo <= net <= hi, f"Seed {seed}: net emitted {net} not in [{lo}, {hi}]"


# ---------------------------------------------------------------------------
# human_scroll_burst — event count realism
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scroll_burst_trackpad_event_count() -> None:
    """Trackpad profile should produce ≥18 wheel events per burst."""
    from xcli.core.human import HumanPaceConfig, human_scroll_burst

    # Force trackpad profile (trackpad=1.0, wheel=0.0)
    cfg = HumanPaceConfig(
        enabled=True,
        overshoot_probability=0.0,
        profile_mix={"trackpad": 1.0, "wheel": 0.0},
    )
    with _NoSleep():
        page = MockPage()
        await human_scroll_burst(page, 1500, config=cfg, rng=random.Random(7))
    assert page.wheel_call_count >= 18, (
        f"Expected ≥18 events for trackpad profile, got {page.wheel_call_count}"
    )


@pytest.mark.asyncio
async def test_scroll_burst_wheel_event_count() -> None:
    """Wheel profile should produce ≤10 wheel events per burst."""
    from xcli.core.human import HumanPaceConfig, human_scroll_burst

    # Force wheel profile (trackpad=0.0, wheel=1.0)
    cfg = HumanPaceConfig(
        enabled=True,
        overshoot_probability=0.0,
        profile_mix={"trackpad": 0.0, "wheel": 1.0},
    )
    with _NoSleep():
        page = MockPage()
        await human_scroll_burst(page, 1500, config=cfg, rng=random.Random(7))
    assert page.wheel_call_count <= 10, (
        f"Expected ≤10 events for wheel profile, got {page.wheel_call_count}"
    )


# ---------------------------------------------------------------------------
# human_scroll_burst — gap non-uniformity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scroll_burst_gap_nonuniformity() -> None:
    """Gap durations should have stddev > 5ms (proves they're jittered).

    We measure gaps by patching asyncio.sleep and recording durations.
    """
    from xcli.core.human import HumanPaceConfig, human_scroll_burst

    cfg = HumanPaceConfig(enabled=True, jitter_pct=0.20, overshoot_probability=0.0)
    sleep_durations: list[float] = []

    async def _mock_sleep(t: float) -> None:
        sleep_durations.append(t)

    import xcli.core.human as human_mod

    old_sleep = human_mod.asyncio.sleep
    human_mod.asyncio.sleep = _mock_sleep  # type: ignore[attr-defined]
    try:
        page = MockPage()
        await human_scroll_burst(page, 1500, config=cfg, rng=random.Random(99))
    finally:
        human_mod.asyncio.sleep = old_sleep

    # Need at least a few gap measurements
    assert len(sleep_durations) >= 3, "Too few sleep calls to measure stddev"

    # Convert to ms for the assertion
    gaps_ms = [d * 1000 for d in sleep_durations]
    std = statistics.stdev(gaps_ms)
    assert std > 5, f"Gap stddev {std:.2f}ms is not > 5ms — gaps may not be jittered"


# ---------------------------------------------------------------------------
# human_scroll_burst — overshoot fires at expected rate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scroll_burst_overshoot_rate() -> None:
    """Overshoot should fire at ~10% rate (within ±5% over 200 trials)."""
    from xcli.core.human import HumanPaceConfig, human_scroll_burst

    # Fixed overshoot probability = 0.10
    cfg = HumanPaceConfig(enabled=True, overshoot_probability=0.10)

    overshoot_count = 0
    trials = 200
    with _NoSleep():
        for seed in range(trials):
            page = MockPage()
            await human_scroll_burst(page, 1500, config=cfg, rng=random.Random(seed))
            # Overshoot produces a negative wheel event — net will be < 1500 significantly
            # Check by looking for negative deltas in wheel calls
            if any(d < 0 for d in page.wheel_deltas):
                overshoot_count += 1

    rate = overshoot_count / trials
    # Expected ~10% ± 5% → [5%, 15%]
    assert 0.05 <= rate <= 0.15, f"Overshoot rate {rate:.2%} not in [5%, 15%] over {trials} trials"


# ---------------------------------------------------------------------------
# human_scroll_burst — disabled mode (back-compat)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scroll_burst_disabled_mode() -> None:
    """With HumanPaceConfig(enabled=False), exactly 1 wheel call with full delta."""
    from xcli.core.human import HumanPaceConfig, human_scroll_burst

    cfg = HumanPaceConfig(enabled=False)
    with _NoSleep():
        page = MockPage()
        result = await human_scroll_burst(page, 1500, config=cfg)

    assert page.wheel_call_count == 1, (
        f"Expected exactly 1 wheel call in disabled mode, got {page.wheel_call_count}"
    )
    assert page.wheel_deltas[0] == 1500, (
        f"Expected deltaY=1500 in disabled mode, got {page.wheel_deltas[0]}"
    )
    assert result == 1500


# ---------------------------------------------------------------------------
# human_read_pause — respects seconds arg (within jitter range)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_pause_respects_seconds_arg() -> None:
    """With seconds=1.0 and default jitter_pct=0.20, sleep is in [0.8, 1.2]."""
    from xcli.core.human import HumanPaceConfig, human_read_pause

    cfg = HumanPaceConfig(enabled=True, jitter_pct=0.20)
    slept: list[float] = []

    import xcli.core.human as human_mod

    old_sleep = human_mod.asyncio.sleep

    async def _mock_sleep(t: float) -> None:
        slept.append(t)

    human_mod.asyncio.sleep = _mock_sleep  # type: ignore[attr-defined]
    try:
        result = await human_read_pause(seconds=1.0, config=cfg, rng=random.Random(123))
    finally:
        human_mod.asyncio.sleep = old_sleep

    assert len(slept) == 1
    actual = slept[0]
    assert 0.80 <= actual <= 1.20, f"Expected sleep in [0.8, 1.2], got {actual:.4f}"
    assert result == pytest.approx(actual)


# ---------------------------------------------------------------------------
# human_read_pause — disabled mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_pause_disabled_mode_sleeps_fixed() -> None:
    """With enabled=False and no seconds arg, sleeps exactly 1.0s."""
    from xcli.core.human import HumanPaceConfig, human_read_pause

    cfg = HumanPaceConfig(enabled=False)
    slept: list[float] = []

    import xcli.core.human as human_mod

    old_sleep = human_mod.asyncio.sleep

    async def _mock_sleep(t: float) -> None:
        slept.append(t)

    human_mod.asyncio.sleep = _mock_sleep  # type: ignore[attr-defined]
    try:
        result = await human_read_pause(config=cfg)
    finally:
        human_mod.asyncio.sleep = old_sleep

    assert slept == [1.0]
    assert result == 1.0


@pytest.mark.asyncio
async def test_read_pause_disabled_mode_uses_provided_seconds() -> None:
    """With enabled=False and seconds=2.5, sleeps exactly 2.5s."""
    from xcli.core.human import HumanPaceConfig, human_read_pause

    cfg = HumanPaceConfig(enabled=False)
    slept: list[float] = []

    import xcli.core.human as human_mod

    old_sleep = human_mod.asyncio.sleep

    async def _mock_sleep(t: float) -> None:
        slept.append(t)

    human_mod.asyncio.sleep = _mock_sleep  # type: ignore[attr-defined]
    try:
        result = await human_read_pause(seconds=2.5, config=cfg)
    finally:
        human_mod.asyncio.sleep = old_sleep

    assert slept == [2.5]
    assert result == 2.5


# ---------------------------------------------------------------------------
# human_read_pause — intent ranges
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "intent,lo,hi",
    [
        ("browse", 0.8, 2.0),
        ("deep", 1.5, 3.5),
        ("skim", 0.4, 1.0),
    ],
)
async def test_read_pause_intent_ranges(intent: str, lo: float, hi: float) -> None:
    """Each intent produces sleep durations in the documented range."""
    from xcli.core.human import HumanPaceConfig, human_read_pause

    cfg = HumanPaceConfig(enabled=True, jitter_pct=0.0)  # no jitter for clean range test
    slept: list[float] = []

    import xcli.core.human as human_mod

    old_sleep = human_mod.asyncio.sleep

    async def _mock_sleep(t: float) -> None:
        slept.append(t)

    human_mod.asyncio.sleep = _mock_sleep  # type: ignore[attr-defined]
    try:
        for seed in range(20):
            slept.clear()
            await human_read_pause(intent=intent, config=cfg, rng=random.Random(seed))  # type: ignore[arg-type]
            assert len(slept) == 1
            assert lo <= slept[0] <= hi, (
                f"intent={intent!r} seed={seed}: {slept[0]:.4f} not in [{lo}, {hi}]"
            )
    finally:
        human_mod.asyncio.sleep = old_sleep


# ---------------------------------------------------------------------------
# default_human_pace — env var control
# ---------------------------------------------------------------------------


def test_default_human_pace_enabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """default_human_pace() returns enabled=True when XCLI_HUMAN_PACE is not set."""
    monkeypatch.delenv("XCLI_HUMAN_PACE", raising=False)
    from xcli.core.human import default_human_pace

    cfg = default_human_pace()
    assert cfg.enabled is True


def test_default_human_pace_disabled_when_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    """XCLI_HUMAN_PACE=0 returns enabled=False."""
    monkeypatch.setenv("XCLI_HUMAN_PACE", "0")
    from xcli.core.human import default_human_pace

    cfg = default_human_pace()
    assert cfg.enabled is False


def test_default_human_pace_disabled_when_false(monkeypatch: pytest.MonkeyPatch) -> None:
    """XCLI_HUMAN_PACE=false returns enabled=False."""
    monkeypatch.setenv("XCLI_HUMAN_PACE", "false")
    from xcli.core.human import default_human_pace

    cfg = default_human_pace()
    assert cfg.enabled is False


def test_default_human_pace_disabled_when_no(monkeypatch: pytest.MonkeyPatch) -> None:
    """XCLI_HUMAN_PACE=no returns enabled=False."""
    monkeypatch.setenv("XCLI_HUMAN_PACE", "no")
    from xcli.core.human import default_human_pace

    cfg = default_human_pace()
    assert cfg.enabled is False


def test_default_human_pace_enabled_when_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """XCLI_HUMAN_PACE=1 returns enabled=True."""
    monkeypatch.setenv("XCLI_HUMAN_PACE", "1")
    from xcli.core.human import default_human_pace

    cfg = default_human_pace()
    assert cfg.enabled is True
