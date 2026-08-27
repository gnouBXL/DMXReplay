from __future__ import annotations

from dmxreplay.codec import (
    GRAYSCALE_WIDTH,
    RGB_PACKED_ROW_BYTES,
    RGB_PACKED_WIDTH,
    dmxframe_to_pixel_rows,
    grayscale_row_to_universe,
    pixel_rows_to_dmxframe,
    rgb_row_to_universe,
    universe_to_grayscale_row,
    universe_to_rgb_row,
)
from dmxreplay.dmx import CHANNELS_PER_UNIVERSE, DMXFrame, Universe


def _ramp_universe(offset: int = 0) -> Universe:
    return Universe(channels=tuple((offset + ch) % 256 for ch in range(CHANNELS_PER_UNIVERSE)))


def test_grayscale_row_is_1to1_and_512_wide():
    u = _ramp_universe()
    row = universe_to_grayscale_row(u)
    assert len(row) == GRAYSCALE_WIDTH == 512
    assert row == u.to_bytes()
    assert grayscale_row_to_universe(row) == u


def test_rgb_packed_width_and_row_size():
    assert RGB_PACKED_WIDTH == 171
    # 4 bytes/pixel (bgr0), not 3: FFV1 has no 8-bit tightly-packed RGB format
    # (only bgr0/bgra) -- see SPECIFICATION.md §5.2 and FORMAT-RESEARCH.md.
    assert RGB_PACKED_ROW_BYTES == 171 * 4 == 684


def test_rgb_packed_row_round_trips_and_padding_is_zero():
    u = _ramp_universe()
    row = universe_to_rgb_row(u)
    assert len(row) == 684
    # Every pixel's 4th byte (bgr0's own pad component) must be 0.
    for p in range(171):
        assert row[p * 4 + 3] == 0
    # Pixel 170 (channels 511,512,[513 oob]) has an unused B slot too: byte
    # index 170*4 (its B/first byte) covers the out-of-range 513th channel.
    assert row[170 * 4] == 0
    assert rgb_row_to_universe(row) == u


def test_rgb_packed_channel_to_pixel_mapping_matches_spec_worked_example():
    # SPECIFICATION.md §5.2 worked example: pixel 0 = (ch1,ch2,ch3), pixel 1 =
    # (ch4,ch5,ch6) logically (channel -> R,G,B), physically stored bgr0
    # (byte order B,G,R,pad) -- see SPECIFICATION.md §5.2/CONTAINER.md §2.
    channels = [0] * CHANNELS_PER_UNIVERSE
    channels[0], channels[1], channels[2] = 10, 20, 30  # channel 1,2,3 -> pixel 0 R,G,B
    channels[3], channels[4], channels[5] = 40, 50, 60  # channel 4,5,6 -> pixel 1 R,G,B
    u = Universe(channels=tuple(channels))
    row = universe_to_rgb_row(u)
    assert tuple(row[0:4]) == (30, 20, 10, 0)  # pixel 0: B,G,R,pad
    assert tuple(row[4:8]) == (60, 50, 40, 0)  # pixel 1: B,G,R,pad


def test_dmxframe_pixel_rows_round_trip_grayscale():
    frame = DMXFrame(timestamp_ns=1_000, universes=(_ramp_universe(0), _ramp_universe(7)))
    rows = dmxframe_to_pixel_rows(frame, "grayscale")
    assert len(rows) == 2
    rebuilt = pixel_rows_to_dmxframe(rows, timestamp_ns=1_000, encoding="grayscale")
    assert rebuilt == frame


def test_dmxframe_pixel_rows_round_trip_rgb_packed():
    frame = DMXFrame(timestamp_ns=2_000, universes=(_ramp_universe(3),))
    rows = dmxframe_to_pixel_rows(frame, "rgb_packed")
    rebuilt = pixel_rows_to_dmxframe(rows, timestamp_ns=2_000, encoding="rgb_packed")
    assert rebuilt == frame
