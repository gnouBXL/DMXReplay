"""A synthetic, no-hardware-needed DMX source. Exists so the Recorder/Player
GUIs (and anyone exploring the CLI) can be used and understood without a
real Art-Net/sACN lighting rig connected -- a deliberate "demo mode," not a
simulation of any specific real fixture.

Deliberately produces a clearly-moving, deterministic pattern (a sweeping
"chase") rather than random noise: a universe monitor watching it should
obviously show *something happening*, and the same tick count always
produces the same output, so a test can assert on it precisely.

Pure and side-effect-free -- no network, no file I/O, no asyncio -- so it's
usable from `Recorder.add_demo_source()` (recorder.py), the demo-show
generator (`dmxreplay.demo`), and tests alike without pulling in any of
those.
"""
from __future__ import annotations

from .universe import CHANNELS_PER_UNIVERSE, Universe

#: How many channels the chase pattern sweeps across -- deliberately less
#: than the full 512 so the moving pixel is a visible fraction of the strip
#: on a small preview widget, not a single-pixel needle in 512 dark ones.
CHASE_WIDTH = 32


class DemoDMXSource:
    """Generates one frame of synthetic DMX data per `tick()` call: a
    bright pixel sweeping across the first `CHASE_WIDTH` channels of each
    universe, with each universe offset from the others so multiple
    universes are visibly distinct, not just frame-to-frame movement in
    one. Fully deterministic in `tick_count` -- `tick()` always advances by
    exactly one and returns what that specific tick produces."""

    def __init__(self, universe_count: int = 4) -> None:
        if universe_count < 1:
            raise ValueError(f"universe_count must be >= 1, got {universe_count}")
        self.universe_count = universe_count
        self.tick_count = 0

    def tick(self) -> tuple[Universe, ...]:
        """Advance one frame and return the new per-universe channel state
        for every universe this source produces, in row order."""
        universes = tuple(self._universe_at(self.tick_count, u) for u in range(self.universe_count))
        self.tick_count += 1
        return universes

    def _universe_at(self, tick: int, row: int) -> Universe:
        position = (tick + row * 7) % CHASE_WIDTH
        channels = [0] * CHANNELS_PER_UNIVERSE
        for ch in range(CHASE_WIDTH):
            distance = min(abs(ch - position), CHASE_WIDTH - abs(ch - position))
            channels[ch] = max(0, 255 - distance * 60)
        return Universe(channels=tuple(channels))
