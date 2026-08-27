"""DMXFrame <-> pixel rows for one video frame. Still no video/container
dependency -- see docs/SPECIFICATION.md §4-§5."""
from __future__ import annotations

from typing import Literal

from ..dmx import DMXFrame, Universe
from .pixels import ENCODINGS

Encoding = Literal["grayscale", "rgb_packed"]


def dmxframe_to_pixel_rows(frame: DMXFrame, encoding: Encoding) -> list[bytes]:
    """One row per active universe, in row order (SPECIFICATION.md §7)."""
    to_row = ENCODINGS[encoding]["to_row"]
    return [to_row(universe) for universe in frame.universes]


def pixel_rows_to_dmxframe(rows: list[bytes], timestamp_ns: int, encoding: Encoding) -> DMXFrame:
    from_row = ENCODINGS[encoding]["from_row"]
    universes: tuple[Universe, ...] = tuple(from_row(row) for row in rows)
    return DMXFrame(timestamp_ns=timestamp_ns, universes=universes)
