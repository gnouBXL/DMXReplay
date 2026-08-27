"""DMX universe <-> pixel row packing. Pure Python, no video/container
dependency -- see docs/SPECIFICATION.md §5. This is the "logical vs physical"
seam (brief §3): everything above this module is dmxreplay.dmx bytes; below
it (video_frame.py, container/) is video/container-specific.
"""
from __future__ import annotations

from ..dmx import CHANNELS_PER_UNIVERSE, Universe

GRAYSCALE_WIDTH = CHANNELS_PER_UNIVERSE  # 512
RGB_PACKED_WIDTH = -(-CHANNELS_PER_UNIVERSE // 3)  # ceil(512/3) = 171
# 4 bytes/pixel, not 3: FFV1 has no 3-byte-packed 8-bit RGB format (confirmed
# via av.codec.Codec("ffv1", "w").video_formats -- only bgr0/bgra among 8-bit
# RGB-like formats). DMXReplay uses bgr0: byte order (B, G, R, pad), pad
# always 0. The *logical* channel->component mapping stays the brief's
# intuitive (channel 3p+1 -> R, 3p+2 -> G, 3p+3 -> B); only the on-disk byte
# order and the extra always-zero 4th byte differ from a hypothetical tight
# rgb24 packing. See docs/SPECIFICATION.md §5.2 and FORMAT-RESEARCH.md.
RGB_PACKED_ROW_BYTES = RGB_PACKED_WIDTH * 4  # 684


def universe_to_grayscale_row(universe: Universe) -> bytes:
    """SPECIFICATION.md §5.1: pixel(x) = channel x+1, 1:1, no packing needed."""
    return universe.to_bytes()


def grayscale_row_to_universe(row: bytes) -> Universe:
    if len(row) != GRAYSCALE_WIDTH:
        raise ValueError(f"grayscale row must be {GRAYSCALE_WIDTH} bytes, got {len(row)}")
    return Universe.from_bytes(row)


def universe_to_rgb_row(universe: Universe) -> bytes:
    """SPECIFICATION.md §5.2: 3 DMX channels per pixel (channel 3p+1 -> R,
    3p+2 -> G, 3p+3 -> B, 1-based), physically stored as bgr0 (byte order
    B, G, R, pad -- see RGB_PACKED_ROW_BYTES). The pad byte is always 0.
    For the final pixel, channel indices that run past 512 are also 0."""
    channels = universe.channels  # 512 values, 0-based
    row = bytearray(RGB_PACKED_ROW_BYTES)  # zero-initialized: pad bytes are correct by default
    for p in range(RGB_PACKED_WIDTH):
        base = p * 3
        r = channels[base] if base < CHANNELS_PER_UNIVERSE else 0
        g = channels[base + 1] if base + 1 < CHANNELS_PER_UNIVERSE else 0
        b = channels[base + 2] if base + 2 < CHANNELS_PER_UNIVERSE else 0
        offset = p * 4
        row[offset] = b
        row[offset + 1] = g
        row[offset + 2] = r
        # row[offset + 3] (pad) stays 0.
    return bytes(row)


def rgb_row_to_universe(row: bytes) -> Universe:
    if len(row) != RGB_PACKED_ROW_BYTES:
        raise ValueError(f"rgb_packed row must be {RGB_PACKED_ROW_BYTES} bytes, got {len(row)}")
    channels: list[int] = []
    for p in range(RGB_PACKED_WIDTH):
        offset = p * 4
        b, g, r = row[offset], row[offset + 1], row[offset + 2]
        for value in (r, g, b):
            if len(channels) < CHANNELS_PER_UNIVERSE:
                channels.append(value)
    return Universe(channels=tuple(channels))


ENCODINGS = {
    "grayscale": {
        "width": GRAYSCALE_WIDTH,
        "row_bytes": GRAYSCALE_WIDTH,
        "pix_fmt": "gray",
        "to_row": universe_to_grayscale_row,
        "from_row": grayscale_row_to_universe,
    },
    "rgb_packed": {
        "width": RGB_PACKED_WIDTH,
        "row_bytes": RGB_PACKED_ROW_BYTES,
        "pix_fmt": "bgr0",
        "to_row": universe_to_rgb_row,
        "from_row": rgb_row_to_universe,
    },
}
