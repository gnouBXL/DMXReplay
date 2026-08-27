from __future__ import annotations

from dmxreplay.clock import MasterClock, Timeline


class FakeClockProvider:
    """A manually-advanceable ClockProvider for deterministic tests."""

    def __init__(self, start_ns: int = 0) -> None:
        self._now_ns = start_ns

    def position_ns(self) -> int:
        return self._now_ns

    def advance(self, delta_ns: int) -> None:
        self._now_ns += delta_ns


def test_master_clock_starts_at_zero_and_is_monotonic():
    provider = FakeClockProvider(start_ns=1_000_000)
    clock = MasterClock(provider=provider)
    assert clock.now_ns() == 0
    provider.advance(500)
    assert clock.now_ns() == 500
    provider.advance(500)
    assert clock.now_ns() == 1000


def test_timeline_starts_stopped_at_zero():
    tl = Timeline(provider=FakeClockProvider())
    assert tl.position_ns() == 0
    assert not tl.playing


def test_timeline_play_advances_position_with_wall_time():
    provider = FakeClockProvider()
    tl = Timeline(provider=provider)
    tl.play(speed=1.0)
    provider.advance(1_000_000_000)  # 1 second
    assert tl.position_ns() == 1_000_000_000


def test_timeline_pause_freezes_position():
    provider = FakeClockProvider()
    tl = Timeline(provider=provider)
    tl.play()
    provider.advance(500_000_000)
    tl.pause()
    frozen = tl.position_ns()
    provider.advance(500_000_000)
    assert tl.position_ns() == frozen
    assert not tl.playing


def test_timeline_seek_sets_absolute_position_while_stopped():
    tl = Timeline(provider=FakeClockProvider())
    tl.seek(42_000_000_000)
    assert tl.position_ns() == 42_000_000_000


def test_timeline_seek_while_playing_keeps_advancing_from_new_position():
    provider = FakeClockProvider()
    tl = Timeline(provider=provider)
    tl.play()
    provider.advance(1_000_000_000)
    tl.seek(10_000_000_000)
    provider.advance(1_000_000_000)
    assert tl.position_ns() == 11_000_000_000


def test_timeline_reverse_playback_decreases_position():
    provider = FakeClockProvider()
    tl = Timeline(provider=provider)
    tl.seek(10_000_000_000)
    tl.play(speed=-1.0)
    provider.advance(2_000_000_000)
    assert tl.position_ns() == 8_000_000_000


def test_timeline_speed_scales_advancement():
    provider = FakeClockProvider()
    tl = Timeline(provider=provider)
    tl.play(speed=2.0)
    provider.advance(1_000_000_000)
    assert tl.position_ns() == 2_000_000_000


def test_timeline_rejects_zero_speed():
    tl = Timeline(provider=FakeClockProvider())
    try:
        tl.play(speed=0)
        assert False, "expected ValueError"
    except ValueError:
        pass
