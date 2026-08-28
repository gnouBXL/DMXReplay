"""Real TOML parsing tests for dmxreplay.config.PlayerConfig -- writes
actual .toml files to disk and loads them, per docs/RASPBERRY_PI.md §14's
proposed headless config shape."""
from __future__ import annotations

from pathlib import Path

import pytest

from dmxreplay.config import InvalidPlayerConfigError, PlayerConfig

EXAMPLE_CONFIG_PATH = (
    Path(__file__).resolve().parent.parent / "packaging" / "raspberrypi" / "player.toml.example"
)


def _write(path, text: str) -> str:
    p = str(path)
    with open(p, "w") as f:
        f.write(text)
    return p


def test_minimal_config_only_show_required(tmp_path):
    path = _write(tmp_path / "player.toml", 'show = "MyShow.dmxr"\n')
    config = PlayerConfig.from_toml_file(path)
    assert config.show == "MyShow.dmxr"
    assert config.output == "artnet"
    assert config.loop is False
    assert config.autoplay is True
    assert config.speed == 1.0


def test_full_config_round_trips_every_field(tmp_path):
    text = """
show = "/var/lib/dmxreplay/shows/MyShow.dmxr"
video = "/var/lib/dmxreplay/shows/MyShow.mp4"
output = "sacn"
interface = "eth0"
destination = "192.168.1.100"
port = 5568
priority = 150
loop = true
autoplay = false
fps = 44.0
speed = 1.0
"""
    path = _write(tmp_path / "player.toml", text)
    config = PlayerConfig.from_toml_file(path)
    assert config.show == "/var/lib/dmxreplay/shows/MyShow.dmxr"
    assert config.video == "/var/lib/dmxreplay/shows/MyShow.mp4"
    assert config.output == "sacn"
    assert config.interface == "eth0"
    assert config.destination == "192.168.1.100"
    assert config.port == 5568
    assert config.priority == 150
    assert config.loop is True
    assert config.autoplay is False
    assert config.fps == 44.0


def test_missing_show_is_rejected(tmp_path):
    path = _write(tmp_path / "player.toml", 'output = "artnet"\n')
    with pytest.raises(InvalidPlayerConfigError, match="show"):
        PlayerConfig.from_toml_file(path)


def test_unknown_key_is_rejected_not_silently_ignored(tmp_path):
    # A realistic typo -- "desintation" instead of "destination" -- must be
    # caught, not silently produce a config that broadcasts instead of
    # unicasting because the intended field was never actually set.
    path = _write(tmp_path / "player.toml", 'show = "x.dmxr"\ndesintation = "192.168.1.1"\n')
    with pytest.raises(InvalidPlayerConfigError, match="desintation"):
        PlayerConfig.from_toml_file(path)


def test_invalid_output_protocol_is_rejected(tmp_path):
    path = _write(tmp_path / "player.toml", 'show = "x.dmxr"\noutput = "dmx512"\n')
    with pytest.raises(InvalidPlayerConfigError, match="artnet"):
        PlayerConfig.from_toml_file(path)


def test_malformed_toml_is_rejected_with_a_clear_error(tmp_path):
    path = _write(tmp_path / "player.toml", 'show = "unterminated string\n')
    with pytest.raises(InvalidPlayerConfigError, match="malformed TOML"):
        PlayerConfig.from_toml_file(path)


def test_shipped_example_config_is_valid():
    """packaging/raspberrypi/player.toml.example is what install.sh copies
    to /etc/dmxreplay/player.toml -- it must always actually parse (real
    regression protection against the example silently rotting out of sync
    with PlayerConfig's fields)."""
    config = PlayerConfig.from_toml_file(str(EXAMPLE_CONFIG_PATH))
    assert config.show  # the one required field, non-empty
