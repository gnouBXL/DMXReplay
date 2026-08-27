"""Pixel rows <-> av.VideoFrame, handling plane stride/padding explicitly.

Requires the optional `av` (PyAV) dependency -- install via `pip install
dmxreplay[codec]`. Isolated in its own module so dmxreplay.dmx/.clock/
.metadata/.network stay importable without it.

Why this module exists at all: PyAV's VideoFrame.planes[i].update() requires
a buffer of exactly `plane.line_size * plane.height` bytes -- i.e. **stride-
padded** data, not tightly packed width*bytes_per_pixel rows. This was
confirmed empirically (not assumed), and confirmed again after switching the
rgb_packed pixel format to bgr0 (pixels.py): a 171-wide bgr0 frame's
line_size is 688 bytes, not the 684 an unpadded row (171*4) would need.
Hard-coding an assumed stride would silently corrupt or crash on some
width/format/libav-version combinations, so this module always reads
plane.line_size at run time rather than computing it from width and format.
"""
from __future__ import annotations

import av

from .pixels import ENCODINGS


def pixel_rows_to_video_frame(rows: list[bytes], encoding: str) -> "av.VideoFrame":
    spec = ENCODINGS[encoding]
    width = spec["width"]
    row_bytes = spec["row_bytes"]
    height = len(rows)
    for row in rows:
        if len(row) != row_bytes:
            raise ValueError(f"row must be {row_bytes} bytes for {encoding!r}, got {len(row)}")

    frame = av.VideoFrame(width, height, format=spec["pix_fmt"])
    plane = frame.planes[0]
    line_size = plane.line_size
    if row_bytes > line_size:
        raise AssertionError(
            f"unpadded row ({row_bytes} bytes) exceeds plane line_size ({line_size}) "
            f"-- unexpected libav stride behavior for {encoding!r}"
        )
    padded = bytearray(line_size * height)
    for i, row in enumerate(rows):
        offset = i * line_size
        padded[offset : offset + row_bytes] = row
    plane.update(bytes(padded))
    return frame


def video_frame_to_pixel_rows(frame: "av.VideoFrame", encoding: str) -> list[bytes]:
    spec = ENCODINGS[encoding]
    row_bytes = spec["row_bytes"]
    plane = frame.planes[0]
    line_size = plane.line_size
    raw = bytes(plane)
    return [raw[i * line_size : i * line_size + row_bytes] for i in range(frame.height)]
