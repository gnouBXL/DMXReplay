"""Playback master timeline. See docs/TIMING.md §1-§2, §6 and docs/API.md §2.

This is the single source of truth a DMXReplay player uses to answer "what time
is it" for DMX, audio, and external video alike (docs/TIMING.md §1). Every
subsystem asks *this* object for the current position; none of them keep an
independent clock.
"""
from __future__ import annotations

from .providers import ClockProvider, InternalClockProvider


class Timeline:
    """Tracks playback position (nanoseconds), independent of what produces
    the underlying wall-clock ticks (see ClockProvider, docs/TIMING.md §7).

    position_ns() is direction-agnostic: reverse playback (speed < 0) and
    forward playback both flow through the same formula, per docs/TIMING.md §6.
    """

    def __init__(self, provider: ClockProvider | None = None) -> None:
        self._provider = provider or InternalClockProvider()
        self._position_ns: int = 0
        self._speed: float = 1.0
        self._playing: bool = False
        self._play_started_wall_ns: int = 0

    def position_ns(self) -> int:
        if not self._playing:
            return self._position_ns
        elapsed_wall_ns = self._provider.position_ns() - self._play_started_wall_ns
        return self._position_ns + int(elapsed_wall_ns * self._speed)

    def seek(self, position_ns: int) -> None:
        """Jump to an absolute timeline position. Valid whether playing, paused,
        or stopped -- all subsystems must reflect the new position immediately
        (docs/TIMING.md §6)."""
        self._position_ns = position_ns
        if self._playing:
            self._play_started_wall_ns = self._provider.position_ns()

    def play(self, speed: float = 1.0) -> None:
        """Start (or resume) advancing the timeline. speed < 0 plays in reverse
        (docs/TIMING.md §6 / brief §22)."""
        if speed == 0:
            raise ValueError("speed must be non-zero; use pause() to stop advancing")
        if self._playing:
            self._position_ns = self.position_ns()
        self._speed = speed
        self._playing = True
        self._play_started_wall_ns = self._provider.position_ns()

    def pause(self) -> None:
        self._position_ns = self.position_ns()
        self._playing = False

    @property
    def playing(self) -> bool:
        return self._playing

    @property
    def speed(self) -> float:
        return self._speed
