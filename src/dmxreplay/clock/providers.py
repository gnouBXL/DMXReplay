"""Clock providers: the abstraction that lets the master timeline be driven by
something other than a free-running internal timer in the future (SMPTE/LTC, MTC,
Art-Net TimeCode, ...). See docs/TIMING.md §7 and docs/API.md §6.

V1 ships exactly one provider: InternalClockProvider.
"""
from __future__ import annotations

import time
from typing import Protocol


class ClockProvider(Protocol):
    """Anything that can report a monotonically non-decreasing position in
    nanoseconds. Only deltas between calls are meaningful -- the epoch is
    provider-defined."""

    def position_ns(self) -> int: ...


class InternalClockProvider:
    """V1's only ClockProvider: a free-running monotonic timer.

    Backed by time.monotonic_ns() (CLOCK_MONOTONIC on POSIX,
    QueryPerformanceCounter-derived on Windows) -- never wall-clock time, which
    can step backward under NTP adjustment. See docs/TIMING.md §3.
    """

    def position_ns(self) -> int:
        return time.monotonic_ns()
