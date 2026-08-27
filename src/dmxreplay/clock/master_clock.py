"""Capture-side clock. See docs/TIMING.md §3 and docs/SPECIFICATION.md §11."""
from __future__ import annotations

from .providers import ClockProvider, InternalClockProvider


class MasterClock:
    """The single, monotonic, high-resolution clock a recorder uses to
    timestamp every captured DMX frame (docs/SPECIFICATION.md §11).

    Distinct from Timeline (clock.timeline.Timeline), which tracks *playback*
    position and supports seek/speed/reverse -- MasterClock only ever moves
    forward at real-time rate; it is the capture-side timestamp source, not a
    player transport.
    """

    def __init__(self, provider: ClockProvider | None = None) -> None:
        self._provider = provider or InternalClockProvider()
        self._epoch_ns = self._provider.position_ns()

    def now_ns(self) -> int:
        """Nanoseconds since this MasterClock was constructed (recording start),
        per docs/SPECIFICATION.md §11's recording-local epoch requirement."""
        return self._provider.position_ns() - self._epoch_ns
