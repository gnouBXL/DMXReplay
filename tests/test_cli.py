"""CLI tests: exercise dmxreplay-record/-play's real async logic in-process
(real network I/O and real .dmxr files underneath, no OS signals involved --
task cancellation stands in for Ctrl+C, which record.py's try/finally and
play.py's try/finally both handle), plus a subprocess smoke test of the
actually-installed dmxreplay-info console script (confirms pyproject.toml
entry-point wiring end-to-end)."""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys

from dmxreplay.cli import play as play_cli
from dmxreplay.cli import record as record_cli
from dmxreplay.codec import ENCODINGS
from dmxreplay.container import DMXReplayReader, DMXReplayWriter
from dmxreplay.dmx import CHANNELS_PER_UNIVERSE, DMXFrame, Universe
from dmxreplay.metadata import Manifest, UniverseMapping
from dmxreplay.network.artnet import ArtNetListener, ArtNetSender


def test_record_cli_parses_arguments():
    args = record_cli.build_parser().parse_args([
        "--input", "sacn", "--interface", "127.0.0.1", "--output", "show.dmxr", "--fps", "25",
    ])
    assert args.input == "sacn"
    assert args.fps == 25.0
    assert args.encoding == "grayscale"  # default


def test_play_cli_parses_arguments():
    args = play_cli.build_parser().parse_args([
        "show.dmxr", "--output", "artnet", "--loop", "--speed", "-1.0", "--seek", "2.5",
    ])
    assert args.output == "artnet"
    assert args.loop is True
    assert args.speed == -1.0
    assert args.seek == 2.5


def test_record_cli_end_to_end_over_real_artnet(tmp_path):
    """Drives dmxreplay-record's real _run() coroutine: real ArtNetSender
    traffic in, real .dmxr file out, verified by reading it back."""
    output_path = str(tmp_path / "recorded.dmxr")

    # Grab a free ephemeral port ourselves so both the CLI's listener and our
    # test sender agree on it up front (small bind/close/rebind race, common
    # and acceptable for a test -- avoids reaching into _run()'s internals).
    import socket as _socket
    probe = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()

    async def body():
        args = record_cli.build_parser().parse_args([
            "--input", "artnet",
            "--interface", "127.0.0.1",
            "--port", str(port),
            "--output", output_path,
            "--discovery-seconds", "0.05",
        ])
        run_task = asyncio.create_task(record_cli._run(args))
        await asyncio.sleep(0.03)  # let _run bind its listener on `port`
        bound_port = port

        sender = ArtNetSender()
        await sender.start(interface_ip="127.0.0.1")
        sender.send(net=0, subnet=0, universe=1, data=bytes([42, 43, 0, 0]),
                    destination_ip="127.0.0.1", port=bound_port)
        await asyncio.sleep(0.1)  # let discovery finish and recording start
        sender.send(net=0, subnet=0, universe=1, data=bytes([99, 0, 0, 0]),
                    destination_ip="127.0.0.1", port=bound_port)
        await asyncio.sleep(0.05)

        run_task.cancel()  # stands in for Ctrl+C; record.py's finally still runs
        try:
            await run_task
        except asyncio.CancelledError:
            pass
        sender.stop()

    asyncio.run(body())

    with DMXReplayReader(output_path) as reader:
        manifest = reader.manifest
        frames = list(reader.read_frames())
    assert manifest.height == 1
    assert len(frames) >= 2
    assert frames[-1].universes[0].get_channel(1) == 99


def test_play_cli_end_to_end_over_real_artnet(tmp_path):
    """Drives dmxreplay-play's real _run() coroutine against a real .dmxr
    file, verified by a real Art-Net listener acting as the lighting rig."""
    dmxr_path = str(tmp_path / "s.dmxr")
    frame_period_ns = 15_000_000  # 15ms/frame
    frames = [
        DMXFrame(timestamp_ns=t * frame_period_ns, universes=(Universe(channels=tuple((t * 5) % 256 for _ in range(CHANNELS_PER_UNIVERSE))),))
        for t in range(4)
    ]
    manifest = Manifest(
        encoding="grayscale", fps=66.0, vfr=False, timestamp_resolution_ns=1_000_000,
        width=ENCODINGS["grayscale"]["width"], height=1,
        universes=[UniverseMapping.from_artnet_port_address(row=0, port_address=1)],
        created_at="2026-08-27T00:00:00Z", duration_seconds=4 * frame_period_ns / 1e9,
        recorder={"name": "dmxreplay-tests", "version": "0.1.0-dev"},
    )
    with DMXReplayWriter(dmxr_path, manifest) as w:
        for f in frames:
            w.write_frame(f)

    received: list[int] = []

    async def body():
        listener = ArtNetListener(on_packet=lambda pkt, ip, ts: received.append(pkt.data[0]))
        await listener.start(interface_ip="127.0.0.1", port=0)
        rig_port = listener._transport.get_extra_info("sockname")[1]

        args = play_cli.build_parser().parse_args([
            dmxr_path, "--output", "artnet",
            "--interface", "127.0.0.1", "--destination", "127.0.0.1", "--port", str(rig_port),
        ])
        # Non-looping, short file: _run() completes naturally once playback
        # reaches the end (no cancellation/signal needed for this path).
        await asyncio.wait_for(play_cli._run(args), timeout=2.0)
        listener.stop()

    asyncio.run(body())

    assert len(received) >= 2
    assert received == sorted(received)  # forward playback: non-decreasing


def test_info_cli_subprocess_smoke_test(tmp_path):
    """Confirms the actually-installed dmxreplay-info console script (per
    pyproject.toml [project.scripts]) works end-to-end as a real subprocess."""
    dmxr_path = str(tmp_path / "s.dmxr")
    manifest = Manifest(
        encoding="grayscale", fps=30.0, vfr=True, timestamp_resolution_ns=1_000_000,
        width=ENCODINGS["grayscale"]["width"], height=1,
        universes=[UniverseMapping.from_artnet_port_address(row=0, port_address=1)],
        created_at="2026-08-27T00:00:00Z", duration_seconds=0.0,
        recorder={"name": "dmxreplay-tests", "version": "0.1.0-dev"}, show_name="CLI smoke test",
    )
    with DMXReplayWriter(dmxr_path, manifest) as w:
        w.write_frame(DMXFrame(timestamp_ns=0, universes=(Universe.blank(),)))

    proc = subprocess.run(
        [sys.executable, "-m", "dmxreplay.cli.info", dmxr_path],
        capture_output=True, text=True, timeout=15,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["format"] == "DMXReplay"
    assert payload["show_name"] == "CLI smoke test"
