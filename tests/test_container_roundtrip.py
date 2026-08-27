"""Real, end-to-end DMXReplay file round-trip tests: build DMXFrames, write a
real .dmxr (Matroska + FFV1 + manifest attachment) via PyAV, read it back via
PyAV, and verify byte-exact DMX reconstruction. Not mocked -- this is the
actual chosen container/codec from FORMAT-RESEARCH.md.
"""
from __future__ import annotations

import json
from pathlib import Path

import av
import pytest

from dmxreplay.codec import ENCODINGS
from dmxreplay.container import DMXReplayReader, DMXReplayWriter, NotADMXReplayFileError
from dmxreplay.container.writer import STORAGE_TIMESTAMP_RESOLUTION_NS
from dmxreplay.dmx import CHANNELS_PER_UNIVERSE, DMXFrame, Universe
from dmxreplay.metadata import Manifest, UniverseMapping

VECTORS_DIR = Path(__file__).resolve().parent.parent / "test-vectors"


def _manifest(*, encoding: str, universe_count: int, fps: float = 30.0, vfr: bool = True) -> Manifest:
    # Port-Address, not the raw 4-bit Universe field (docs/ARTNET.md §1.1) --
    # a flat i+1 would overflow the field's [0,15] range past 16 universes.
    universes = [
        UniverseMapping.from_artnet_port_address(row=i, port_address=i + 1)
        for i in range(universe_count)
    ]
    return Manifest(
        encoding=encoding,
        fps=fps,
        vfr=vfr,
        timestamp_resolution_ns=STORAGE_TIMESTAMP_RESOLUTION_NS,
        width=ENCODINGS[encoding]["width"],
        height=universe_count,
        universes=universes,
        created_at="2026-08-27T00:00:00Z",
        duration_seconds=0.0,
        recorder={"name": "dmxreplay-tests", "version": "0.1.0-dev"},
    )


def _ramp_universe(offset: int) -> Universe:
    return Universe(channels=tuple((offset + ch) % 256 for ch in range(CHANNELS_PER_UNIVERSE)))


@pytest.mark.parametrize("encoding", ["grayscale", "rgb_packed"])
def test_round_trip_is_byte_exact(tmp_path, encoding):
    frames = [
        DMXFrame(timestamp_ns=t * 33_333_333, universes=(_ramp_universe(t), _ramp_universe(t + 100)))
        for t in range(10)
    ]
    manifest = _manifest(encoding=encoding, universe_count=2)
    path = str(tmp_path / "test.dmxr")

    with DMXReplayWriter(path, manifest) as writer:
        for frame in frames:
            writer.write_frame(frame)

    with DMXReplayReader(path) as reader:
        assert reader.manifest.encoding == encoding
        decoded = list(reader.read_frames())

    assert len(decoded) == len(frames)
    for original, got in zip(frames, decoded):
        assert got.universes == original.universes  # byte-exact DMX values


def test_timestamps_are_quantized_to_nearest_millisecond(tmp_path):
    frames = [
        DMXFrame(timestamp_ns=ts, universes=(Universe.blank(),))
        for ts in (0, 21_372_000, 42_891_333, 64_105_001)
    ]
    manifest = _manifest(encoding="grayscale", universe_count=1)
    path = str(tmp_path / "vfr.dmxr")

    with DMXReplayWriter(path, manifest) as writer:
        for frame in frames:
            writer.write_frame(frame)

    with DMXReplayReader(path) as reader:
        decoded = list(reader.read_frames())

    # Rounded to the nearest *whole* millisecond (STORAGE_TIMESTAMP_RESOLUTION_NS):
    # round(21_372_000 / 1e6) = round(21.372) = 21ms; round(42_891_333 / 1e6) =
    # round(42.891333) = 43ms; round(64_105_001 / 1e6) = round(64.105001) = 64ms.
    expected_ms = [0, 21_000_000, 43_000_000, 64_000_000]
    assert [f.timestamp_ns for f in decoded] == expected_ms
    # Confirms these are NOT equally spaced -- true VFR, not a 30fps grid.
    deltas = [b - a for a, b in zip(expected_ms, expected_ms[1:])]
    assert len(set(deltas)) > 1


def test_two_frames_within_the_same_millisecond_get_distinct_monotonic_pts(tmp_path):
    frames = [
        DMXFrame(timestamp_ns=1_000_000, universes=(Universe.blank(),)),
        DMXFrame(timestamp_ns=1_000_200, universes=(Universe.blank().with_channel(1, 1),)),  # same ms
    ]
    manifest = _manifest(encoding="grayscale", universe_count=1)
    path = str(tmp_path / "collision.dmxr")

    with DMXReplayWriter(path, manifest) as writer:
        for frame in frames:
            writer.write_frame(frame)

    with DMXReplayReader(path) as reader:
        decoded = list(reader.read_frames())

    assert len(decoded) == 2
    assert decoded[0].timestamp_ns < decoded[1].timestamp_ns
    # DMX content for the bumped frame must still be exactly what was written.
    assert decoded[1].universes[0].get_channel(1) == 1


def test_manifest_survives_round_trip_including_universe_mapping(tmp_path):
    manifest = _manifest(encoding="grayscale", universe_count=3, fps=25.0)
    path = str(tmp_path / "manifest.dmxr")
    with DMXReplayWriter(path, manifest) as writer:
        writer.write_frame(DMXFrame(timestamp_ns=0, universes=tuple(Universe.blank() for _ in range(3))))

    with DMXReplayReader(path) as reader:
        restored = reader.manifest

    assert restored.fps == 25.0
    assert restored.height == 3
    assert [u.universe for u in restored.universes] == [1, 2, 3]


def test_reader_rejects_file_without_dmxreplay_manifest(tmp_path):
    # A plain Matroska/FFV1 file with no manifest attachment must be
    # identified as NOT a DMXReplay file (SPECIFICATION.md §2), even though
    # its video track is shaped like one.
    path = str(tmp_path / "not_dmxreplay.mkv")
    container = av.open(path, mode="w")
    stream = container.add_stream("ffv1", rate=30)
    stream.width, stream.height, stream.pix_fmt = 512, 1, "gray"
    frame = av.VideoFrame(512, 1, format="gray")
    frame.planes[0].update(bytes(frame.planes[0].buffer_size))
    frame.pts = 0
    for packet in stream.encode(frame):
        container.mux(packet)
    for packet in stream.encode():
        container.mux(packet)
    container.close()

    with pytest.raises(NotADMXReplayFileError):
        DMXReplayReader(path)


def _load_test_vector(name: str) -> list[DMXFrame]:
    meta = json.loads((VECTORS_DIR / f"{name}.json").read_text())
    raw = (VECTORS_DIR / f"{name}.raw").read_bytes()
    universes_per_frame = meta["universes_per_frame"]
    bytes_per_frame = universes_per_frame * CHANNELS_PER_UNIVERSE

    frames = []
    for t in range(meta["frame_count"]):
        frame_bytes = raw[t * bytes_per_frame : (t + 1) * bytes_per_frame]
        universes = tuple(
            Universe.from_bytes(frame_bytes[u * CHANNELS_PER_UNIVERSE : (u + 1) * CHANNELS_PER_UNIVERSE])
            for u in range(universes_per_frame)
        )
        frames.append(DMXFrame(timestamp_ns=meta["timestamps_ns"][t], universes=universes))
    return frames


@pytest.mark.parametrize(
    "vector_name",
    [
        "test1_ramp",
        "test2_alternating",
        "test3_random",
        "test4_multi_universe",  # 128 universes -- also exercises writer/reader at V1 scale ceiling
        "test5_sparse_universes",
    ],
)
@pytest.mark.parametrize("encoding", ["grayscale", "rgb_packed"])
def test_official_test_vectors_round_trip_through_the_real_container(tmp_path, vector_name, encoding):
    """Integration test tying every Phase 1 test vector (docs/SPECIFICATION.md
    §19) to the Phase 4 container, in both pixel encodings: write a real
    .dmxr, read it back, confirm byte-exact reconstruction."""
    frames = _load_test_vector(vector_name)
    universe_count = len(frames[0].universes)

    manifest = _manifest(encoding=encoding, universe_count=universe_count)
    path = str(tmp_path / f"{vector_name}.dmxr")
    with DMXReplayWriter(path, manifest) as writer:
        for frame in frames:
            writer.write_frame(frame)

    with DMXReplayReader(path) as reader:
        decoded = list(reader.read_frames())

    assert len(decoded) == len(frames)
    for original, got in zip(frames, decoded):
        assert got.universes == original.universes
