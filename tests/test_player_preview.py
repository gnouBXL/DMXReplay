from __future__ import annotations

from dmxreplay.codec import ENCODINGS
from dmxreplay.container import DMXReplayWriter
from dmxreplay.dmx import CHANNELS_PER_UNIVERSE, DMXFrame, Universe
from dmxreplay.metadata import Manifest, UniverseMapping
from dmxreplay.player import Player
from dmxreplay.preview import rgb_led_pixels


def _make_dmxr(path: str) -> None:
    channels = [0] * CHANNELS_PER_UNIVERSE
    channels[0], channels[1], channels[2] = 10, 20, 30
    u = Universe(channels=tuple(channels))
    mapping = [UniverseMapping.from_artnet_port_address(row=0, port_address=1)]
    manifest = Manifest(
        encoding="grayscale", fps=30.0, vfr=False, timestamp_resolution_ns=1_000_000,
        width=ENCODINGS["grayscale"]["width"], height=1,
        universes=mapping, created_at="2026-08-27T00:00:00Z", duration_seconds=0.0,
        recorder={"name": "dmxreplay-tests", "version": "0.1.0-dev"},
    )
    with DMXReplayWriter(path, manifest) as w:
        w.write_frame(DMXFrame(timestamp_ns=0, universes=(u,)))


def test_current_preview_defaults_to_raw(tmp_path):
    path = str(tmp_path / "s.dmxr")
    _make_dmxr(path)
    player = Player()
    player.load(path)
    preview = player.current_preview(0)
    assert preview[0] == 10
    assert preview[1] == 20
    assert preview[2] == 30


def test_current_preview_rgb_led_mode(tmp_path):
    path = str(tmp_path / "s.dmxr")
    _make_dmxr(path)
    player = Player()
    player.load(path)
    player.set_preview_mode("rgb_led")
    preview = player.current_preview(0)
    assert preview[0] == (10, 20, 30)


def test_current_preview_before_load_returns_none():
    player = Player()
    assert player.current_preview(0) is None


def test_preview_never_mutates_playback_state(tmp_path):
    path = str(tmp_path / "s.dmxr")
    _make_dmxr(path)
    player = Player()
    player.load(path)
    before = player.position_ns
    player.set_preview_mode("rgb_led")
    player.current_preview(0)
    player.current_preview(0)
    assert player.position_ns == before
