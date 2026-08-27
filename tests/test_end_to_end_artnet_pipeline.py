"""End-to-end validation: Art-Net input -> DMXReplay recording -> .dmxr ->
DMXReplay playback -> Art-Net output, with byte-for-byte DMX comparison.

This is the "critère principal" integration test from docs/RASPBERRY_PI.md /
the brief's validation requirement: a live Art-Net source's DMX values must
survive the full round trip through the DMXReplay format unchanged.

The dedicated Recorder/Player orchestration classes (docs/API.md §4-§5) are
Phase 5/6 work and don't exist yet, but the actual data path they will wrap
is fully implemented now (Phase 2 Art-Net + Phase 4 codec/container), so this
test exercises that real path directly:

    ArtNetSender (simulated console)
        --UDP-->  ArtNetListener  (recorder input)
                        |
                  DMXReplayWriter  (recorder output: writes a real .dmxr)
                        |
                  DMXReplayReader  (player input: reads the real .dmxr)
                        |
    ArtNetSender (player output)
        --UDP-->  ArtNetListener  (simulated lighting rig)

Not mocked anywhere: every arrow above is a real UDP send/receive or a real
Matroska+FFV1 encode/decode.
"""
from __future__ import annotations

import asyncio

from dmxreplay.codec import ENCODINGS
from dmxreplay.container import DMXReplayReader, DMXReplayWriter
from dmxreplay.dmx import CHANNELS_PER_UNIVERSE, DMXFrame, Universe
from dmxreplay.metadata import Manifest, UniverseMapping
from dmxreplay.network.artnet import ArtNetListener, ArtNetSender


def _pattern_universe(t: int, u: int) -> Universe:
    return Universe(channels=tuple((t * 7 + u * 31 + ch) % 256 for ch in range(CHANNELS_PER_UNIVERSE)))


def test_artnet_to_dmxr_to_artnet_round_trip_is_byte_exact(tmp_path):
    SOURCE_UNIVERSES = [1, 2, 5]  # sparse Port-Addresses, exercises row-packing too
    FRAME_COUNT = 20

    async def record_from_artnet() -> tuple[list[DMXFrame], dict[int, int]]:
        """Simulated console -> ArtNetListener, exactly as a real recorder's
        input stage would receive it. Returns (frames in row order,
        {port_address: row})."""
        captured: dict[tuple[int, int, int], list[tuple[int, bytes]]] = {}
        row_of_key: dict[tuple[int, int, int], int] = {}

        def on_packet(pkt, ip, ts):
            key = (pkt.net, pkt.subnet, pkt.universe)
            if key not in row_of_key:
                row_of_key[key] = len(row_of_key)
                captured[key] = []
            captured[key].append((ts, pkt.data))

        listener = ArtNetListener(on_packet=on_packet)
        await listener.start(interface_ip="127.0.0.1", port=0)
        port = listener._transport.get_extra_info("sockname")[1]

        sender = ArtNetSender()
        await sender.start(interface_ip="127.0.0.1")

        for t in range(FRAME_COUNT):
            for u_idx, port_address in enumerate(SOURCE_UNIVERSES):
                net, subnet, universe = port_address >> 8, (port_address >> 4) & 0xF, port_address & 0xF
                data = _pattern_universe(t, u_idx).to_bytes()
                sender.send(net=net, subnet=subnet, universe=universe, data=data,
                            destination_ip="127.0.0.1", port=port)
            await asyncio.sleep(0.001)  # let the recorder's event loop drain each "frame"

        await asyncio.sleep(0.1)
        sender.stop()
        listener.stop()

        # Reassemble into DMXFrame-per-timestamp, one universe per row, in
        # first-seen order -- exactly SPECIFICATION.md §7's row assignment.
        rows = sorted(row_of_key.items(), key=lambda kv: kv[1])
        frames_by_t: list[DMXFrame] = []
        for t in range(FRAME_COUNT):
            universes = tuple(Universe.from_bytes(captured[key][t][1]) for key, _row in rows)
            ts = captured[rows[0][0]][t][0]
            frames_by_t.append(DMXFrame(timestamp_ns=ts, universes=universes))

        port_address_by_row = {
            row: (net << 8) | (subnet << 4) | universe
            for (net, subnet, universe), row in row_of_key.items()
        }
        return frames_by_t, port_address_by_row

    frames, port_address_by_row = asyncio.run(record_from_artnet())
    assert len(frames) == FRAME_COUNT
    assert [port_address_by_row[r] for r in sorted(port_address_by_row)] == SOURCE_UNIVERSES

    # --- "Recorder": write a real .dmxr file from what was captured -------
    universe_count = len(SOURCE_UNIVERSES)
    mapping = [
        UniverseMapping.from_artnet_port_address(row=row, port_address=pa)
        for row, pa in sorted(port_address_by_row.items())
    ]
    manifest = Manifest(
        encoding="grayscale", fps=30.0, vfr=True, timestamp_resolution_ns=1_000_000,
        width=ENCODINGS["grayscale"]["width"], height=universe_count,
        universes=mapping, created_at="2026-08-27T00:00:00Z",
        duration_seconds=FRAME_COUNT / 30.0,
        recorder={"name": "dmxreplay-e2e-test", "version": "0.1.0-dev"},
    )
    dmxr_path = str(tmp_path / "e2e.dmxr")
    with DMXReplayWriter(dmxr_path, manifest) as writer:
        for frame in frames:
            writer.write_frame(frame)

    # --- "Player": read the .dmxr back and re-transmit over Art-Net -------
    async def play_to_artnet(decoded_frames: list[DMXFrame]) -> list[DMXFrame]:
        received: dict[tuple[int, int, int], list[bytes]] = {}
        row_of_key: dict[tuple[int, int, int], int] = {}

        def on_packet(pkt, ip, ts):
            key = (pkt.net, pkt.subnet, pkt.universe)
            if key not in row_of_key:
                row_of_key[key] = len(row_of_key)
                received[key] = []
            received[key].append(pkt.data)

        listener = ArtNetListener(on_packet=on_packet)  # simulated lighting rig
        await listener.start(interface_ip="127.0.0.1", port=0)
        port = listener._transport.get_extra_info("sockname")[1]

        sender = ArtNetSender()  # player output stage
        await sender.start(interface_ip="127.0.0.1")

        for frame in decoded_frames:
            for row, universe in enumerate(frame.universes):
                port_address = port_address_by_row[row]
                net, subnet, u = port_address >> 8, (port_address >> 4) & 0xF, port_address & 0xF
                sender.send(net=net, subnet=subnet, universe=u, data=universe.to_bytes(),
                            destination_ip="127.0.0.1", port=port)
            await asyncio.sleep(0.001)

        await asyncio.sleep(0.1)
        sender.stop()
        listener.stop()

        rows = sorted(row_of_key.items(), key=lambda kv: kv[1])
        rebuilt = []
        for t in range(len(decoded_frames)):
            universes = tuple(Universe.from_bytes(received[key][t]) for key, _row in rows)
            rebuilt.append(DMXFrame(timestamp_ns=decoded_frames[t].timestamp_ns, universes=universes))
        return rebuilt

    with DMXReplayReader(dmxr_path) as reader:
        decoded = list(reader.read_frames())
    assert len(decoded) == FRAME_COUNT

    replayed = asyncio.run(play_to_artnet(decoded))

    # --- Final check: what the "lighting rig" received over Art-Net must be
    #     byte-for-byte identical to what the original console sent. --------
    assert len(replayed) == len(frames)
    for original, final in zip(frames, replayed):
        assert final.universes == original.universes
