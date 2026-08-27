#!/usr/bin/env python3
"""Generate DMXReplay's official test vectors (docs/SPECIFICATION.md §19, tests 1-5).

Each vector is written as:
  - <name>.raw  : concatenated frames, each frame = concatenated per-row universes
                  (512 bytes/universe), in row order -- the same layout
                  benchmark/format_benchmark.py feeds to ffmpeg, and what the
                  Phase 4 encoder will eventually consume as its pixel source.
  - <name>.json : a sidecar describing shape and (for the sparse vector) the
                  row -> source-universe mapping, so a future encoder/tester
                  doesn't have to guess the vector's structure.

This intentionally does not depend on dmxreplay.codec/container (Phase 4, not
yet implemented) -- it operates at the dmxreplay.dmx data-model level, and its
output round-trips through dmxreplay.dmx.Universe/DMXFrame, exercised in
tests/test_dmx_model.py.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dmxreplay.dmx import CHANNELS_PER_UNIVERSE, DMXFrame, Universe  # noqa: E402
from dmxreplay.metadata import artnet_port_address_to_fields  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent


def _write_vector(name: str, frames: list[DMXFrame], extra_meta: dict | None = None) -> None:
    raw_path = OUT_DIR / f"{name}.raw"
    with raw_path.open("wb") as f:
        for frame in frames:
            for universe in frame.universes:
                f.write(universe.to_bytes())

    meta = {
        "name": name,
        "frame_count": len(frames),
        "universes_per_frame": len(frames[0].universes) if frames else 0,
        "channels_per_universe": CHANNELS_PER_UNIVERSE,
        "timestamps_ns": [f.timestamp_ns for f in frames],
    }
    if extra_meta:
        meta.update(extra_meta)
    (OUT_DIR / f"{name}.json").write_text(json.dumps(meta, indent=2))
    print(f"wrote {raw_path.name} ({raw_path.stat().st_size} bytes) + {name}.json")


def test1_ramp(frame_count: int = 32, universe_count: int = 2) -> list[DMXFrame]:
    """Every channel cycles 0..255 over time (SPECIFICATION.md §19, test 1)."""
    frames = []
    for t in range(frame_count):
        universes = tuple(
            Universe(channels=tuple((t + ch) % 256 for ch in range(CHANNELS_PER_UNIVERSE)))
            for _u in range(universe_count)
        )
        frames.append(DMXFrame(timestamp_ns=t * 33_333_333, universes=universes))
    return frames


def test2_alternating(frame_count: int = 32, universe_count: int = 2) -> list[DMXFrame]:
    """Whole frame alternates 0x00/0xFF every frame (test 2)."""
    frames = []
    for t in range(frame_count):
        value = 0 if t % 2 == 0 else 255
        universe = Universe(channels=(value,) * CHANNELS_PER_UNIVERSE)
        frames.append(
            DMXFrame(timestamp_ns=t * 33_333_333, universes=(universe,) * universe_count)
        )
    return frames


def test3_random(frame_count: int = 32, universe_count: int = 2, seed: int = 1234) -> list[DMXFrame]:
    """Deterministic pseudo-random values across all channels (test 3)."""

    def det_random(t: int, universe_idx: int, ch: int) -> int:
        x = (seed * 2654435761 + t * 40503 + universe_idx * 999983 + ch * 2246822519) & 0xFFFFFFFF
        x ^= x >> 15
        x = (x * 2246822519) & 0xFFFFFFFF
        x ^= x >> 13
        return x & 0xFF

    frames = []
    for t in range(frame_count):
        universes = tuple(
            Universe(channels=tuple(det_random(t, u, ch) for ch in range(CHANNELS_PER_UNIVERSE)))
            for u in range(universe_count)
        )
        frames.append(DMXFrame(timestamp_ns=t * 33_333_333, universes=universes))
    return frames


def test4_multi_universe(frame_count: int = 8, universe_count: int = 128) -> list[DMXFrame]:
    """At least 128 active universes (test 4)."""
    return test1_ramp(frame_count=frame_count, universe_count=universe_count)


def test5_sparse_universes(frame_count: int = 8) -> tuple[list[DMXFrame], list[dict]]:
    """A small, non-contiguous set of source Art-Net universes, addressed by
    their flattened Port-Address (the "Universe N" number a console displays --
    see docs/ARTNET.md §1.1): 1, 5, 17, 42 (SPECIFICATION.md §19, test 5 /
    §7's worked example)."""
    source_port_addresses = [1, 5, 17, 42]
    frames = test1_ramp(frame_count=frame_count, universe_count=len(source_port_addresses))
    mapping = []
    for row, port_address in enumerate(source_port_addresses):
        net, subnet, universe = artnet_port_address_to_fields(port_address)
        mapping.append(
            {
                "row": row,
                "protocol": "Art-Net",
                "net": net,
                "subnet": subnet,
                "universe": universe,
                "port_address": port_address,
            }
        )
    return frames, mapping


def main() -> None:
    _write_vector("test1_ramp", test1_ramp())
    _write_vector("test2_alternating", test2_alternating())
    _write_vector("test3_random", test3_random())
    _write_vector("test4_multi_universe", test4_multi_universe())

    sparse_frames, sparse_mapping = test5_sparse_universes()
    _write_vector("test5_sparse_universes", sparse_frames, extra_meta={"universes": sparse_mapping})


if __name__ == "__main__":
    main()
