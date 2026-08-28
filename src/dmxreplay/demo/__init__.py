"""A bundled demo show. Exists so the Player GUI can open *something*
immediately -- no real recording, no lighting rig, no user-supplied file
required -- to explore playback/timeline/output-configuration UI. This is
explicitly a synthetic file for exploring the GUI, not a stand-in for real
Art-Net/sACN content (see `dmxreplay.dmx.demo_source`'s docstring for the
same distinction on the Recorder side).

Generated once and cached under the platform's standard per-user cache
directory (`demo_show_path()`), not regenerated on every launch -- the
pattern is fully deterministic (`DemoDMXSource`), so there's nothing to
gain from redoing the work every time, only startup latency to lose.
`DEMO_SHOW_VERSION` exists so a future change to the pattern invalidates
any already-cached file rather than silently continuing to serve a stale
one.
"""
from __future__ import annotations

import math
import os
import struct
import sys
import wave
from datetime import datetime, timezone
from pathlib import Path

from ..codec import ENCODINGS
from ..container import DMXReplayWriter
from ..dmx import DemoDMXSource, DMXFrame
from ..metadata import Manifest, UniverseMapping

__all__ = ["demo_show_path"]

DEMO_SHOW_VERSION = 1
DEMO_UNIVERSE_COUNT = 4
DEMO_FPS = 30.0
DEMO_DURATION_SECONDS = 8.0
DEMO_AUDIO_SAMPLE_RATE = 22050


def _cache_dir() -> Path:
    """Platform-appropriate per-user cache directory -- deliberately
    hand-rolled per platform (XDG on Linux, ~/Library/Caches on macOS,
    %LOCALAPPDATA% on Windows) rather than a new dependency, since it's a
    one-line decision per `sys.platform` and this is the only place in the
    project that needs it."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = str(Path.home() / "Library" / "Caches")
    else:
        base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "dmxreplay"


def demo_show_path() -> str:
    """The path to the bundled demo show, generating it (once, cached) if
    it doesn't already exist. Safe to call repeatedly/from any entry point
    (CLI, Player GUI, launcher) -- generation is idempotent and cheap
    (a few hundred small frames)."""
    cache_dir = _cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"demo_show_v{DEMO_SHOW_VERSION}.dmxr"
    if not path.exists():
        _generate_demo_show(str(path))
    return str(path)


def _write_demo_tone_wav(path: str) -> None:
    """A short, clearly-audible sweep (not silence, not a pure single tone)
    so "Audio: present" in the Player GUI has something worth noticing.
    Same stdlib-`wave`-based synthesis this project already uses for real
    tests (tests/test_container_audio.py) and benchmarks
    (benchmark/realtime_playback_benchmark.py) -- not a new technique."""
    n = int(DEMO_DURATION_SECONDS * DEMO_AUDIO_SAMPLE_RATE)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(DEMO_AUDIO_SAMPLE_RATE)
        frames = bytearray()
        for i in range(n):
            freq = 330.0 + 220.0 * (i / n)  # a slow upward sweep, 330Hz -> 550Hz
            v = int(6000 * math.sin(2 * math.pi * freq * i / DEMO_AUDIO_SAMPLE_RATE))
            frames += struct.pack("<h", v)
        w.writeframes(bytes(frames))


def _generate_demo_show(path: str) -> None:
    frame_count = int(DEMO_DURATION_SECONDS * DEMO_FPS)
    period_ns = round(1_000_000_000 / DEMO_FPS)
    # port_address starts at 0 so row 0 maps to raw Art-Net universe 0 --
    # matches benchmark/realtime_playback_benchmark.py's own note on why
    # (the raw field is 4 bits and repeats past 16, but DEMO_UNIVERSE_COUNT
    # is well under that here regardless).
    mapping = [
        UniverseMapping.from_artnet_port_address(row=i, port_address=i)
        for i in range(DEMO_UNIVERSE_COUNT)
    ]
    manifest = Manifest(
        encoding="grayscale", fps=DEMO_FPS, vfr=False, timestamp_resolution_ns=1_000_000,
        width=ENCODINGS["grayscale"]["width"], height=DEMO_UNIVERSE_COUNT,
        universes=mapping, created_at=datetime.now(timezone.utc).isoformat(),
        duration_seconds=frame_count / DEMO_FPS,
        show_name="DMXReplay Demo Show",
        description=(
            "A synthetic chase pattern generated locally by dmxreplay.demo -- "
            "not a real recording. For exploring the Player GUI without a lighting rig."
        ),
        recorder={"name": "dmxreplay-demo-generator", "version": "0.1.0-dev"},
    )

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        audio_path = f"{tmp}/demo_tone.wav"
        _write_demo_tone_wav(audio_path)
        source = DemoDMXSource(DEMO_UNIVERSE_COUNT)
        with DMXReplayWriter(path, manifest, audio_path=audio_path) as w:
            for t in range(frame_count):
                w.write_frame(DMXFrame(timestamp_ns=t * period_ns, universes=source.tick()))
