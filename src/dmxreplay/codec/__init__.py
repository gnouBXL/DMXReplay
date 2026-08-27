"""DMX <-> video frame codec (Phase 4). See docs/SPECIFICATION.md §4-§5.

`pixels` and `frame_codec` are pure Python (no extra dependency).
`video_frame` requires the optional `av` (PyAV) dependency
(`pip install dmxreplay[codec]`) and is imported lazily so the rest of this
package stays usable without it installed.
"""
from .frame_codec import Encoding, dmxframe_to_pixel_rows, pixel_rows_to_dmxframe
from .pixels import (
    ENCODINGS,
    GRAYSCALE_WIDTH,
    RGB_PACKED_ROW_BYTES,
    RGB_PACKED_WIDTH,
    grayscale_row_to_universe,
    rgb_row_to_universe,
    universe_to_grayscale_row,
    universe_to_rgb_row,
)

__all__ = [
    "Encoding",
    "dmxframe_to_pixel_rows",
    "pixel_rows_to_dmxframe",
    "ENCODINGS",
    "GRAYSCALE_WIDTH",
    "RGB_PACKED_WIDTH",
    "RGB_PACKED_ROW_BYTES",
    "universe_to_grayscale_row",
    "grayscale_row_to_universe",
    "universe_to_rgb_row",
    "rgb_row_to_universe",
]
