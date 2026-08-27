from __future__ import annotations

from dmxreplay.dmx import CHANNELS_PER_UNIVERSE, Universe
from dmxreplay.preview import (
    LED_PIXELS_PER_UNIVERSE,
    compute_preview,
    raw_channel_grid,
    rgb_hex,
    rgb_led_pixels,
)


def _ramp_universe(offset: int = 0) -> Universe:
    return Universe(channels=tuple((offset + ch) % 256 for ch in range(CHANNELS_PER_UNIVERSE)))


def test_raw_channel_grid_is_exactly_the_channel_values():
    u = _ramp_universe()
    assert raw_channel_grid(u) == u.channels


def test_raw_preview_never_mutates_the_universe():
    u = _ramp_universe()
    original = u.channels
    raw_channel_grid(u)
    assert u.channels == original  # Universe is frozen/immutable anyway, but assert the contract


def test_rgb_led_pixel_count():
    u = Universe.blank()
    pixels = rgb_led_pixels(u)
    assert len(pixels) == LED_PIXELS_PER_UNIVERSE == 171


def test_rgb_led_mapping_matches_spec_worked_example():
    # SPECIFICATION.md §5.2 / brief §7: pixel 0 = (ch1,ch2,ch3), pixel 1 = (ch4,ch5,ch6).
    channels = [0] * CHANNELS_PER_UNIVERSE
    channels[0], channels[1], channels[2] = 10, 20, 30
    channels[3], channels[4], channels[5] = 40, 50, 60
    u = Universe(channels=tuple(channels))
    pixels = rgb_led_pixels(u)
    assert pixels[0] == (10, 20, 30)
    assert pixels[1] == (40, 50, 60)


def test_rgb_led_last_pixel_pads_with_zero():
    # 512 channels -> 170 full pixels (510 channels) + 1 pixel with only 2
    # real components (channels 511, 512); the 3rd (B) is unused, must be 0.
    channels = [0] * CHANNELS_PER_UNIVERSE
    channels[510] = 111  # channel 511
    channels[511] = 222  # channel 512
    u = Universe(channels=tuple(channels))
    pixels = rgb_led_pixels(u)
    assert pixels[170] == (111, 222, 0)


def test_rgb_hex_matches_spec_worked_example():
    # brief §37: R=255, G=128, B=64 -> "#FF8040"
    assert rgb_hex((255, 128, 64)) == "#FF8040"


def test_rgb_hex_uses_raw_values_no_gamma_or_dimming_curve():
    # A literal value must map 1:1 to its hex byte -- brief §37 explicitly
    # forbids gamma/dimming-curve adjustment in this mode.
    assert rgb_hex((0, 0, 0)) == "#000000"
    assert rgb_hex((255, 255, 255)) == "#FFFFFF"
    assert rgb_hex((1, 2, 3)) == "#010203"


def test_compute_preview_dispatches_correctly():
    u = _ramp_universe()
    assert compute_preview(u, "raw") == raw_channel_grid(u)
    assert compute_preview(u, "rgb_led") == rgb_led_pixels(u)


def test_compute_preview_rejects_unknown_mode():
    import pytest

    with pytest.raises(ValueError):
        compute_preview(Universe.blank(), "not_a_real_mode")  # type: ignore[arg-type]


def test_preview_functions_do_not_change_dmx_frame_identity(tmp_path):
    """Integration-style check: computing a preview from a decoded DMXFrame
    must not alter what gets written back out (brief §8's "MUST NOT modify
    stored DMX values"), verified against the real container round trip."""
    from dmxreplay.codec import ENCODINGS
    from dmxreplay.container import DMXReplayReader, DMXReplayWriter
    from dmxreplay.dmx import DMXFrame
    from dmxreplay.metadata import Manifest, UniverseMapping

    mapping = [UniverseMapping.from_artnet_port_address(row=0, port_address=1)]
    manifest = Manifest(
        encoding="grayscale", fps=30.0, vfr=False, timestamp_resolution_ns=1_000_000,
        width=ENCODINGS["grayscale"]["width"], height=1,
        universes=mapping, created_at="2026-08-27T00:00:00Z", duration_seconds=0.0,
        recorder={"name": "dmxreplay-tests", "version": "0.1.0-dev"},
    )
    path = str(tmp_path / "preview.dmxr")
    original = _ramp_universe(7)
    with DMXReplayWriter(path, manifest) as w:
        w.write_frame(DMXFrame(timestamp_ns=0, universes=(original,)))

    with DMXReplayReader(path) as reader:
        frame = next(reader.read_frames())

    # Compute both preview modes -- must not affect the decoded frame at all.
    compute_preview(frame.universes[0], "raw")
    compute_preview(frame.universes[0], "rgb_led")
    assert frame.universes[0] == original
