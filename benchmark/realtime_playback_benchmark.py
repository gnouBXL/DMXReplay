#!/usr/bin/env python3
"""Real-time playback benchmark (Phase H, docs/ARCHITECTURE.md).

`player_pipeline_benchmark.py` measures *unthrottled* max decode+send
throughput -- useful for "how much CPU headroom exists," but it says nothing
about two things Phase H's matrix also promises: (1) the real master clock's
actual packet-timing accuracy/jitter when genuinely paced to real time, and
(2) the incremental cost of decoding an audio track and/or an external video
file *alongside* DMX -- both run on their own PyAV streams the real `Player`
coordinates off the same `Timeline` (docs/API.md §5), not inside the DMX
decode path itself, so they don't show up in the DMX-only benchmark at all.

This script runs the real `dmxreplay.player.Player` -- not a synthetic
stand-in -- at real fps, real-time paced, against a real Art-Net loopback
listener, for each of DMX-only / +audio / +video / +audio+video, and reports:

  - Packet-arrival jitter for one representative universe (mean/max deviation
    from the nominal inter-frame period), i.e. actual real-time timing
    accuracy, not throughput.
  - Process CPU time consumed during the run (`resource.getrusage`), as a
    fraction of the real wall-clock duration -- directly comparable to
    RASPBERRY_PI.md §4's "CPU needed for real-time playback" figures.

Usage:
    python3 benchmark/realtime_playback_benchmark.py <universes> <fps> <seconds> <variant>
    variant: dmx | audio | video | audio_video

Prints one JSON line to stdout with the measured results.
"""
from __future__ import annotations

import asyncio
import json
import math
import resource
import struct
import sys
import time
import wave
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import av  # noqa: E402

from dmxreplay.codec import ENCODINGS  # noqa: E402
from dmxreplay.container import DMXReplayWriter  # noqa: E402
from dmxreplay.dmx import CHANNELS_PER_UNIVERSE, DMXFrame, Universe  # noqa: E402
from dmxreplay.metadata import Manifest, UniverseMapping  # noqa: E402
from dmxreplay.network.artnet import ArtNetListener, ArtNetSender  # noqa: E402
from dmxreplay.metadata.schema import artnet_port_address_to_fields  # noqa: E402
from dmxreplay.player import Player  # noqa: E402


def _write_tone_wav(path: str, seconds: float, sample_rate: int = 22050) -> None:
    """Same synthesis approach as tests/test_container_audio.py -- a real
    audio file, not a stub -- so DMXReplayWriter's real AAC re-encode path
    (via PyAV) actually runs, same as it would for a real recording."""
    n = int(seconds * sample_rate)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        frames = bytearray()
        for i in range(n):
            v = int(8000 * math.sin(2 * math.pi * 440.0 * i / sample_rate))
            frames += struct.pack("<h", v)
        w.writeframes(bytes(frames))


def _write_video(path: str, seconds: float, fps: int, width: int = 64, height: int = 48) -> None:
    """Same approach as tests/test_player_video.py's _make_test_video --
    a real H.264 file the real ExternalVideoReader decodes, not a stub."""
    frame_count = int(seconds * fps)
    container = av.open(path, mode="w")
    stream = container.add_stream("libx264", rate=fps)
    stream.width, stream.height = width, height
    stream.pix_fmt = "yuv420p"
    stream.codec_context.time_base = Fraction(1, 1000)
    stream.codec_context.options = {"crf": "0", "preset": "ultrafast"}
    for i in range(frame_count):
        frame = av.VideoFrame(width, height, format="yuv420p")
        y, u, v = frame.planes
        y.update(bytes([i % 256]) * y.buffer_size)
        u.update(bytes([128]) * u.buffer_size)
        v.update(bytes([128]) * v.buffer_size)
        frame.pts = int(i * (1000 / fps))
        for packet in stream.encode(frame):
            container.mux(packet)
    for packet in stream.encode():
        container.mux(packet)
    container.close()


def _write_show(path: str, universes: int, fps: int, seconds: float, audio_path: str | None) -> None:
    frame_count = int(seconds * fps)
    period_ns = round(1_000_000_000 / fps)
    # port_address starts at 0 (not 1) so row 0 maps to raw Art-Net universe
    # 0 -- what on_packet() below filters on to isolate one representative
    # universe's packet-arrival timing regardless of how many are playing.
    mapping = [UniverseMapping.from_artnet_port_address(row=i, port_address=i) for i in range(universes)]
    manifest = Manifest(
        encoding="grayscale", fps=float(fps), vfr=False, timestamp_resolution_ns=1_000_000,
        width=ENCODINGS["grayscale"]["width"], height=universes,
        universes=mapping, created_at="2026-08-27T00:00:00Z",
        duration_seconds=frame_count / fps,
        recorder={"name": "dmxreplay-benchmark", "version": "0.1.0-dev"},
    )
    with DMXReplayWriter(path, manifest, audio_path=audio_path) as w:
        for t in range(frame_count):
            us = tuple(
                Universe(channels=tuple((t + u + ch) % 256 for ch in range(CHANNELS_PER_UNIVERSE)))
                for u in range(universes)
            )
            w.write_frame(DMXFrame(timestamp_ns=t * period_ns, universes=us))


async def _run(universes: int, fps: int, seconds: float, variant: str) -> dict:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        audio_path = None
        if variant in ("audio", "audio_video"):
            audio_path = f"{tmp}/tone.wav"
            _write_tone_wav(audio_path, seconds)

        video_path = None
        if variant in ("video", "audio_video"):
            video_path = f"{tmp}/clip.mp4"
            _write_video(video_path, seconds, fps)

        show_path = f"{tmp}/bench.dmxr"
        _write_show(show_path, universes, fps, seconds, audio_path)

        # Row 0's raw (net, subnet, universe) triple -- port_address=0 -- is
        # what identifies "row 0's packets" unambiguously. Filtering on
        # pkt.universe alone is wrong past 16 universes: the raw Art-Net
        # `universe` field is only 4 bits (0-15, packet.py), so e.g. row 0
        # (port_address=0) and row 16 (port_address=16, a different
        # subnet) both carry universe=0 -- an early version of this script
        # did exactly that and silently over-counted "row 0" arrivals by
        # ~4x at 50 universes, a real bug caught by the resulting numbers
        # looking implausible, not by inspection.
        target_net, target_subnet, target_universe = artnet_port_address_to_fields(0)

        arrivals: list[float] = []

        def on_packet(pkt, ip, ts):
            if (pkt.net, pkt.subnet, pkt.universe) == (target_net, target_subnet, target_universe):
                arrivals.append(time.perf_counter())

        listener = ArtNetListener(on_packet=on_packet)
        await listener.start(interface_ip="127.0.0.1", port=0)
        port = listener._transport.get_extra_info("sockname")[1]

        player = Player()
        player.load(show_path)
        if video_path is not None:
            player.load_external_video(video_path)
        player.set_output("Art-Net", interface_ip="127.0.0.1", destination_ip="127.0.0.1", port=port)

        rusage_before = resource.getrusage(resource.RUSAGE_SELF)
        wall_before = time.perf_counter()

        await player.play()
        await asyncio.sleep(seconds + 0.5)  # real content duration + drain margin
        await player.stop()

        wall_after = time.perf_counter()
        rusage_after = resource.getrusage(resource.RUSAGE_SELF)
        listener.stop()

    cpu_seconds = (rusage_after.ru_utime + rusage_after.ru_stime) - (rusage_before.ru_utime + rusage_before.ru_stime)
    wall_seconds = wall_after - wall_before

    nominal_period_ms = 1000.0 / fps
    deltas_ms = [(b - a) * 1000.0 for a, b in zip(arrivals, arrivals[1:])]
    deviations_ms = [abs(d - nominal_period_ms) for d in deltas_ms]

    return {
        "universes": universes,
        "fps": fps,
        "requested_seconds": seconds,
        "variant": variant,
        "packets_received": len(arrivals),
        "wall_seconds": round(wall_seconds, 4),
        "cpu_seconds": round(cpu_seconds, 4),
        "cpu_fraction_of_one_core": round(cpu_seconds / wall_seconds, 4) if wall_seconds > 0 else None,
        "nominal_period_ms": round(nominal_period_ms, 3),
        "mean_period_deviation_ms": round(sum(deviations_ms) / len(deviations_ms), 4) if deviations_ms else None,
        "max_period_deviation_ms": round(max(deviations_ms), 4) if deviations_ms else None,
    }


def main() -> None:
    universes = int(sys.argv[1])
    fps = int(sys.argv[2])
    seconds = float(sys.argv[3])
    variant = sys.argv[4]
    result = asyncio.run(_run(universes, fps, seconds, variant))
    print(json.dumps(result))


if __name__ == "__main__":
    main()
