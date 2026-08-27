from __future__ import annotations

import json
from pathlib import Path

import pytest

from dmxreplay.dmx import CHANNELS_PER_UNIVERSE, DMXFrame, Universe

VECTORS_DIR = Path(__file__).resolve().parent.parent / "test-vectors"


def test_universe_requires_exactly_512_channels():
    with pytest.raises(ValueError):
        Universe(channels=(0,) * 511)
    with pytest.raises(ValueError):
        Universe(channels=(0,) * 513)


def test_universe_rejects_out_of_range_values():
    channels = [0] * CHANNELS_PER_UNIVERSE
    channels[10] = 256
    with pytest.raises(ValueError):
        Universe(channels=tuple(channels))
    channels[10] = -1
    with pytest.raises(ValueError):
        Universe(channels=tuple(channels))


def test_universe_blank_is_all_zero():
    u = Universe.blank()
    assert len(u.channels) == CHANNELS_PER_UNIVERSE
    assert all(v == 0 for v in u.channels)


def test_universe_channel_is_1_based():
    channels = [0] * CHANNELS_PER_UNIVERSE
    channels[0] = 42  # 0-based index 0 == DMX channel 1
    u = Universe(channels=tuple(channels))
    assert u.get_channel(1) == 42
    with pytest.raises(ValueError):
        u.get_channel(0)
    with pytest.raises(ValueError):
        u.get_channel(513)


def test_universe_with_channel_is_immutable_update():
    u1 = Universe.blank()
    u2 = u1.with_channel(1, 200)
    assert u1.get_channel(1) == 0  # original untouched
    assert u2.get_channel(1) == 200


def test_universe_bytes_round_trip():
    channels = tuple(i % 256 for i in range(CHANNELS_PER_UNIVERSE))
    u = Universe(channels=channels)
    raw = u.to_bytes()
    assert len(raw) == CHANNELS_PER_UNIVERSE
    u2 = Universe.from_bytes(raw)
    assert u2 == u


def test_dmxframe_rejects_negative_timestamp():
    with pytest.raises(ValueError):
        DMXFrame(timestamp_ns=-1, universes=(Universe.blank(),))


def test_dmxframe_active_universe_count():
    frame = DMXFrame(timestamp_ns=0, universes=(Universe.blank(), Universe.blank()))
    assert frame.active_universe_count == 2


# --- Test vector round-trip (docs/SPECIFICATION.md §19) -------------------- #

VECTOR_NAMES = [
    "test1_ramp",
    "test2_alternating",
    "test3_random",
    "test4_multi_universe",
    "test5_sparse_universes",
]


@pytest.fixture(scope="module", autouse=True)
def _ensure_vectors_generated():
    if not (VECTORS_DIR / "test1_ramp.raw").exists():
        import subprocess
        import sys

        subprocess.run(
            [sys.executable, str(VECTORS_DIR / "generate_test_vectors.py")],
            check=True,
        )


@pytest.mark.parametrize("name", VECTOR_NAMES)
def test_vector_round_trips_through_universe_model(name: str):
    meta = json.loads((VECTORS_DIR / f"{name}.json").read_text())
    raw = (VECTORS_DIR / f"{name}.raw").read_bytes()

    frame_count = meta["frame_count"]
    universes_per_frame = meta["universes_per_frame"]
    bytes_per_frame = universes_per_frame * CHANNELS_PER_UNIVERSE
    assert len(raw) == frame_count * bytes_per_frame

    frames: list[DMXFrame] = []
    for t in range(frame_count):
        frame_bytes = raw[t * bytes_per_frame : (t + 1) * bytes_per_frame]
        universes = tuple(
            Universe.from_bytes(
                frame_bytes[u * CHANNELS_PER_UNIVERSE : (u + 1) * CHANNELS_PER_UNIVERSE]
            )
            for u in range(universes_per_frame)
        )
        frames.append(DMXFrame(timestamp_ns=meta["timestamps_ns"][t], universes=universes))

    # Re-serialize and confirm exact byte-for-byte reconstruction (losslessness
    # requirement, SPECIFICATION.md §"File integrity" / brief §44).
    rebuilt = bytearray()
    for frame in frames:
        for universe in frame.universes:
            rebuilt.extend(universe.to_bytes())
    assert bytes(rebuilt) == raw


def test_sparse_vector_row_mapping_matches_worked_example():
    from dmxreplay.metadata import artnet_fields_to_port_address

    meta = json.loads((VECTORS_DIR / "test5_sparse_universes.json").read_text())
    rows = {
        entry["row"]: artnet_fields_to_port_address(entry["net"], entry["subnet"], entry["universe"])
        for entry in meta["universes"]
    }
    assert rows == {0: 1, 1: 5, 2: 17, 3: 42}


def test_multi_universe_vector_has_at_least_128_universes():
    meta = json.loads((VECTORS_DIR / "test4_multi_universe.json").read_text())
    assert meta["universes_per_frame"] >= 128
