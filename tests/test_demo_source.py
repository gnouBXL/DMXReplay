"""Real, deterministic tests for dmxreplay.dmx.DemoDMXSource -- the
synthetic, no-hardware-needed DMX source used by the Recorder GUI's demo
mode and the bundled demo show generator."""
from __future__ import annotations

import pytest

from dmxreplay.dmx import CHANNELS_PER_UNIVERSE, DemoDMXSource


def test_tick_returns_one_universe_per_configured_count():
    source = DemoDMXSource(universe_count=3)
    universes = source.tick()
    assert len(universes) == 3
    for u in universes:
        assert len(u.channels) == CHANNELS_PER_UNIVERSE


def test_tick_count_advances_by_exactly_one_per_call():
    source = DemoDMXSource()
    assert source.tick_count == 0
    source.tick()
    assert source.tick_count == 1
    source.tick()
    assert source.tick_count == 2


def test_pattern_is_deterministic_given_the_same_tick_count():
    a = DemoDMXSource(universe_count=2)
    b = DemoDMXSource(universe_count=2)
    for _ in range(5):
        assert a.tick() == b.tick()


def test_pattern_actually_moves_between_ticks():
    source = DemoDMXSource(universe_count=1)
    first = source.tick()[0]
    second = source.tick()[0]
    assert first.channels != second.channels


def test_different_universes_in_the_same_tick_are_offset_from_each_other():
    """The whole point of the per-row offset: two universes in the same
    tick must not be identical, or a multi-universe monitor would show
    every universe doing the exact same thing."""
    source = DemoDMXSource(universe_count=2)
    universes = source.tick()
    assert universes[0].channels != universes[1].channels


def test_rejects_zero_or_negative_universe_count():
    with pytest.raises(ValueError, match="universe_count"):
        DemoDMXSource(universe_count=0)
