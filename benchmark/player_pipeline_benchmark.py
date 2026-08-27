#!/usr/bin/env python3
"""Player pipeline benchmark: .dmxr decode -> DMX state -> Art-Net/sACN output.

This measures the actual bottleneck path a headless DMXReplay Player will run
(docs/RASPBERRY_PI.md): decode each video frame via DMXReplayReader, then
immediately send every active universe out over real UDP (ArtNetSender /
SACNSender, looped back on localhost so the send path -- packet building,
socket syscalls -- is fully exercised, not skipped).

The loop runs *unthrottled* (as fast as it can go, not paced to real time) so
the result is a measured maximum throughput; comparing that to the nominal
real-time requirement (frame_count / fps seconds) gives a safety margin. This
script is run as its own process (invoked under `/usr/bin/time -v` by the
caller) so CPU/RSS figures reflect one isolated player-pipeline run.

Usage:
    python3 benchmark/player_pipeline_benchmark.py <universes> <frames> <fps> <protocol> <encoding>
    protocol: artnet | sacn
    encoding: grayscale | rgb_packed

Prints one JSON line to stdout with the measured results.
"""
from __future__ import annotations

import asyncio
import json
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dmxreplay.container import DMXReplayWriter  # noqa: E402
from dmxreplay.container.reader import DMXReplayReader  # noqa: E402
from dmxreplay.dmx import CHANNELS_PER_UNIVERSE, DMXFrame, Universe  # noqa: E402
from dmxreplay.metadata import Manifest, UniverseMapping  # noqa: E402
from dmxreplay.network.artnet import ArtNetListener, ArtNetSender  # noqa: E402
from dmxreplay.network.sacn import SACNListener, SACNSender  # noqa: E402


def _bump_rcvbuf(transport) -> None:
    """Raise the loopback listener's kernel receive buffer for this benchmark
    only (not shipped in ArtNetListener/SACNListener). An unthrottled sender
    hammering a same-box loopback listener can overflow the OS default UDP
    receive buffer well before any real capacity limit is hit -- that's a
    test-harness artifact, not a statement about real Art-Net/sACN receiver
    capacity on separate physical hardware. Widening it here keeps the
    reported received_packets figure meaningful rather than dominated by
    that artifact."""
    sock = transport.get_extra_info("socket")
    if sock is not None:
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8 * 1024 * 1024)
        except OSError:
            pass


def build_source_frames(universes: int, frames: int, fps: int) -> list[DMXFrame]:
    period_ns = round(1_000_000_000 / fps)
    out = []
    for t in range(frames):
        us = tuple(
            Universe(channels=tuple((t + u + ch) % 256 for ch in range(CHANNELS_PER_UNIVERSE)))
            for u in range(universes)
        )
        out.append(DMXFrame(timestamp_ns=t * period_ns, universes=us))
    return out


def write_dmxr(path: str, frames: list[DMXFrame], universes: int, fps: int, encoding: str) -> None:
    from dmxreplay.codec import ENCODINGS

    mapping = [
        UniverseMapping.from_artnet_port_address(row=i, port_address=i + 1)
        for i in range(universes)
    ]
    manifest = Manifest(
        encoding=encoding, fps=float(fps), vfr=True,
        timestamp_resolution_ns=1_000_000,
        width=ENCODINGS[encoding]["width"], height=universes,
        universes=mapping, created_at="2026-08-27T00:00:00Z",
        duration_seconds=len(frames) / fps,
        recorder={"name": "dmxreplay-benchmark", "version": "0.1.0-dev"},
    )
    with DMXReplayWriter(path, manifest) as w:
        for f in frames:
            w.write_frame(f)


async def run_artnet_pipeline(path: str, universes: int) -> dict:
    received = {"count": 0}

    def on_packet(pkt, ip, ts):
        received["count"] += 1

    listener = ArtNetListener(on_packet=on_packet)
    await listener.start(interface_ip="127.0.0.1", port=0)
    _bump_rcvbuf(listener._transport)
    port = listener._transport.get_extra_info("sockname")[1]
    sender = ArtNetSender()
    await sender.start(interface_ip="127.0.0.1")

    reader = DMXReplayReader(path)
    t0 = time.perf_counter()
    decoded_frames = 0
    sent_packets = 0
    for frame in reader.read_frames():
        decoded_frames += 1
        for row, universe in enumerate(frame.universes):
            sender.send(net=0, subnet=0, universe=row % 16, data=universe.to_bytes(),
                        destination_ip="127.0.0.1", port=port)
            sent_packets += 1
    send_done_t = time.perf_counter()
    reader.close()

    # Let the loopback listener drain its socket buffer.
    await asyncio.sleep(0.3)
    t1 = time.perf_counter()

    sender.stop()
    listener.stop()

    return {
        "decoded_frames": decoded_frames,
        "sent_packets": sent_packets,
        "received_packets": received["count"],
        "decode_and_send_wall_seconds": send_done_t - t0,
        "total_wall_seconds_incl_drain": t1 - t0,
    }


async def run_sacn_pipeline(path: str, universes: int) -> dict:
    received = {"count": 0}

    def on_packet(pkt, ip, ts):
        received["count"] += 1

    listener = SACNListener(on_packet=on_packet)
    await listener.start(interface_ip="127.0.0.1", port=0)
    _bump_rcvbuf(listener._transport)
    port = listener._transport.get_extra_info("sockname")[1]
    sender = SACNSender()
    await sender.start(interface_ip="127.0.0.1")

    reader = DMXReplayReader(path)
    t0 = time.perf_counter()
    decoded_frames = 0
    sent_packets = 0
    for frame in reader.read_frames():
        decoded_frames += 1
        for row, universe in enumerate(frame.universes):
            sender.send(universe=(row % 63999) + 1, dmx_data=universe.to_bytes(),
                        destination_ip="127.0.0.1", port=port)
            sent_packets += 1
    send_done_t = time.perf_counter()
    reader.close()

    await asyncio.sleep(0.3)
    t1 = time.perf_counter()

    sender.stop()
    listener.stop()

    return {
        "decoded_frames": decoded_frames,
        "sent_packets": sent_packets,
        "received_packets": received["count"],
        "decode_and_send_wall_seconds": send_done_t - t0,
        "total_wall_seconds_incl_drain": t1 - t0,
    }


def main() -> None:
    universes = int(sys.argv[1])
    frames = int(sys.argv[2])
    fps = int(sys.argv[3])
    protocol = sys.argv[4]
    encoding = sys.argv[5]

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        path = f"{tmp}/bench.dmxr"
        source_frames = build_source_frames(universes, frames, fps)

        t_enc0 = time.perf_counter()
        write_dmxr(path, source_frames, universes, fps, encoding)
        encode_wall_seconds = time.perf_counter() - t_enc0
        file_size = Path(path).stat().st_size

        runner = run_artnet_pipeline if protocol == "artnet" else run_sacn_pipeline
        pipeline_result = asyncio.run(runner(path, universes))

    nominal_realtime_seconds = frames / fps
    result = {
        "universes": universes,
        "frames": frames,
        "fps": fps,
        "protocol": protocol,
        "encoding": encoding,
        "file_size_bytes": file_size,
        "encode_wall_seconds": round(encode_wall_seconds, 4),
        "nominal_realtime_seconds": nominal_realtime_seconds,
        **{k: (round(v, 4) if isinstance(v, float) else v) for k, v in pipeline_result.items()},
    }
    result["decode_and_send_realtime_factor"] = round(
        nominal_realtime_seconds / result["decode_and_send_wall_seconds"], 2
    ) if result["decode_and_send_wall_seconds"] > 0 else None
    print(json.dumps(result))


if __name__ == "__main__":
    main()
