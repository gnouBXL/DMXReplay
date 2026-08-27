"""A DMX frame: a full snapshot of all active universes at one capture-timeline
instant. See docs/SPECIFICATION.md §1 (Terminology) and §11 (Timestamp format)."""
from __future__ import annotations

from dataclasses import dataclass

from .universe import Universe


@dataclass(frozen=True, slots=True)
class DMXFrame:
    """One point on the capture timeline.

    `timestamp_ns` is nanoseconds since an arbitrary recording-local epoch
    (SPECIFICATION.md §11) -- never wall-clock/calendar time.

    `universes` is indexed by *row* (SPECIFICATION.md §7): `universes[0]` is
    whatever universe the recorder assigned row 0, with no implied relationship
    to that universe's original network address. The row -> source-address
    mapping lives in the metadata manifest (dmxreplay.metadata), not here --
    DMXFrame is protocol-agnostic by design.
    """

    timestamp_ns: int
    universes: tuple[Universe, ...]

    def __post_init__(self) -> None:
        if self.timestamp_ns < 0:
            raise ValueError(f"timestamp_ns must be >= 0, got {self.timestamp_ns}")

    @property
    def active_universe_count(self) -> int:
        return len(self.universes)
