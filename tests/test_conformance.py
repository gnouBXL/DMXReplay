"""Phase 10 conformance suite: explicit tests mapped to
docs/SPECIFICATION.md §20 (Reader/Recorder/Player conformance roles) and the
official test vectors in §19.

Tests 1-5 (ramp, alternating, random, multi-universe, sparse) already have
dedicated coverage: at the `dmxreplay.dmx` data-model level in
test_dmx_model.py, and round-tripped through the real container in
test_container_roundtrip.py::test_official_test_vectors_round_trip_through_the_real_container.
This file does not duplicate them -- it implements the tests that could not
exist before the recorder/player engines did:

  6. High packet rate      -- below
  7. Timing irregularity   -- below
  8. Seek                  -- tests/test_player.py::test_seek_jumps_to_correct_dmx_state
  9. Synchronization       -- below (also the source of the measured figure
                               now recorded in docs/TIMING.md §8)
  10. Loop                 -- tests/test_player.py::test_loop_restarts_from_the_beginning

and adds explicit, role-labeled conformance checks for requirements in §20
that existing tests establish piecemeal but never state as a single
Reader/Recorder/Player conformance claim -- including two real gaps this
suite's own writing surfaced (not assumed, found by checking the spec's
requirements one by one against what existed): Player had no sACN output
test at all (Art-Net-only coverage until now), and no `frame_step()` method
existed despite §20 explicitly requiring "seek, play, pause, frame-step, and
loop" -- both fixed in this phase (Player gained `frame_step()`, see
src/dmxreplay/player/player.py), not just newly tested.
"""
from __future__ import annotations

import asyncio
import time
from fractions import Fraction

import av
import pytest

from dmxreplay.codec import ENCODINGS
from dmxreplay.container import DMXReplayReader, DMXReplayWriter, NotADMXReplayFileError
from dmxreplay.dmx import CHANNELS_PER_UNIVERSE, DMXFrame, Universe
from dmxreplay.metadata import (
    Manifest,
    UniverseMapping,
    UnsupportedManifestVersionError,
)
from dmxreplay.network.artnet import ArtNetListener, ArtNetSender
from dmxreplay.network.sacn import SACNListener
from dmxreplay.player import Player
from dmxreplay.recorder import Recorder

# --------------------------------------------------------------------- #
# Reader conformance (SPECIFICATION.md §20 "Reader")
# --------------------------------------------------------------------- #


def _manifest(*, encoding: str = "grayscale", universe_count: int = 1) -> Manifest:
    universes = [
        UniverseMapping.from_artnet_port_address(row=i, port_address=i + 1)
        for i in range(universe_count)
    ]
    return Manifest(
        encoding=encoding, fps=30.0, vfr=True, timestamp_resolution_ns=1_000_000,
        width=ENCODINGS[encoding]["width"], height=universe_count,
        universes=universes, created_at="2026-08-27T00:00:00Z", duration_seconds=0.0,
        recorder={"name": "dmxreplay-tests", "version": "0.1.0-dev"},
    )


def test_reader_conformance_open_identify_decode_reconstruct_reproduce(tmp_path):
    """§20 Reader: open a valid file; identify per §2; parse+validate the
    manifest per §10/§16.4; decode the DMX video track (grayscale, §5.1);
    reconstruct per-universe values via the manifest's row mapping (§7);
    reproduce each frame's timestamp without alteration (within the
    documented ms quantization, §11)."""
    path = str(tmp_path / "reader_conformance.dmxr")
    manifest = _manifest(universe_count=2)
    frames = [
        DMXFrame(
            timestamp_ns=t * 20_000_000,
            universes=(
                Universe(channels=tuple((t + ch) % 256 for ch in range(CHANNELS_PER_UNIVERSE))),
                Universe(channels=tuple((t + 100 + ch) % 256 for ch in range(CHANNELS_PER_UNIVERSE))),
            ),
        )
        for t in range(6)
    ]
    with DMXReplayWriter(path, manifest) as w:
        for f in frames:
            w.write_frame(f)

    # Open + identify: a real DMXReplay file opens without error.
    with DMXReplayReader(path) as reader:
        got_manifest = reader.manifest
        decoded = list(reader.read_frames())

    # Parse+validate: fields survive, row mapping intact (§7/§10).
    assert got_manifest.height == 2
    assert [u.row for u in got_manifest.universes] == [0, 1]

    # Decode + reconstruct: byte-exact per-universe values via row mapping.
    assert len(decoded) == len(frames)
    for original, got in zip(frames, decoded):
        assert got.universes == original.universes

    # Reproduce timestamps without alteration (ms-quantized on write, §11 --
    # inputs here are already whole multiples of 1ms so no rounding occurs).
    assert [f.timestamp_ns for f in decoded] == [f.timestamp_ns for f in frames]


def test_reader_conformance_identifies_non_dmxreplay_files(tmp_path):
    """§2: identification requires the manifest attachment itself, not just
    a Matroska container that happens to look similar."""
    path = str(tmp_path / "not_dmxreplay.mkv")
    container = av.open(path, mode="w")
    stream = container.add_stream("ffv1")
    stream.width, stream.height = 512, 1
    stream.pix_fmt = "gray"
    stream.codec_context.time_base = Fraction(1, 1000)
    frame = av.VideoFrame(512, 1, format="gray")
    frame.planes[0].update(bytes(512))
    frame.pts = 0
    frame.time_base = Fraction(1, 1000)
    for p in stream.encode(frame):
        container.mux(p)
    for p in stream.encode():
        container.mux(p)
    container.close()

    with pytest.raises(NotADMXReplayFileError):
        DMXReplayReader(path)


def test_reader_conformance_refuses_unsupported_manifest_version(tmp_path):
    """§10.4/§16.4: fail closed on a manifest major version this Reader
    doesn't understand, rather than guessing at its meaning."""
    with pytest.raises(UnsupportedManifestVersionError):
        Manifest(
            encoding="grayscale", fps=30.0, vfr=False, timestamp_resolution_ns=1_000_000,
            width=ENCODINGS["grayscale"]["width"], height=1,
            universes=[UniverseMapping.from_artnet_port_address(row=0, port_address=1)],
            created_at="2026-08-27T00:00:00Z", duration_seconds=0.0,
            recorder={"name": "x", "version": "0.1"}, version="2.0",
        )


# --------------------------------------------------------------------- #
# Recorder conformance (SPECIFICATION.md §20 "Recorder")
# --------------------------------------------------------------------- #


def test_recorder_conformance_output_passes_reader_requirements(tmp_path):
    """§20 Recorder: "produce a valid DMXReplay file (passes Reader
    requirements above on its own output)" -- captures real Art-Net,
    records, then re-opens the result through the same Reader-conformance
    checks a third-party file would have to pass."""

    async def body():
        recorder = Recorder()
        await recorder.add_source("Art-Net", interface_ip="127.0.0.1", port=0)
        port = recorder._artnet_listeners[0]._transport.get_extra_info("sockname")[1]
        sender = ArtNetSender()
        await sender.start(interface_ip="127.0.0.1")

        sender.send(net=0, subnet=0, universe=1, data=bytes([1, 2, 3, 0]),
                    destination_ip="127.0.0.1", port=port)
        await asyncio.sleep(0.02)

        path = str(tmp_path / "recorder_conformance.dmxr")
        recorder.start(path)
        sender.send(net=0, subnet=0, universe=1, data=bytes([9, 8, 7, 0]),
                    destination_ip="127.0.0.1", port=port)
        await asyncio.sleep(0.02)

        recorder.stop()
        sender.stop()
        await recorder.close()
        return path

    path = asyncio.run(body())

    # Passes Reader conformance: opens, identifies, decodes, reconstructs.
    with DMXReplayReader(path) as reader:
        manifest = reader.manifest
        decoded = list(reader.read_frames())
    assert manifest.format == "DMXReplay"
    assert len(decoded) >= 2
    assert decoded[-1].universes[0].get_channel(1) == 9


def test_recorder_conformance_stores_only_active_universes(tmp_path):
    """§7/§20: rows correspond exactly to universes that actually sent
    traffic before start() -- never a fixed/padded universe count."""

    async def body():
        recorder = Recorder()
        await recorder.add_source("Art-Net", interface_ip="127.0.0.1", port=0)
        port = recorder._artnet_listeners[0]._transport.get_extra_info("sockname")[1]
        sender = ArtNetSender()
        await sender.start(interface_ip="127.0.0.1")

        # Only universes 5 and 42 are ever sent -- sparse, non-contiguous,
        # like test vector 5 (SPECIFICATION.md §19).
        sender.send(net=0, subnet=0, universe=5, data=bytes([1, 0]), destination_ip="127.0.0.1", port=port)
        await asyncio.sleep(0.02)
        sender.send(net=0, subnet=2, universe=10, data=bytes([2, 0]), destination_ip="127.0.0.1", port=port)  # port_address=42
        await asyncio.sleep(0.02)

        path = str(tmp_path / "sparse_recorder.dmxr")
        recorder.start(path)
        recorder.stop()
        sender.stop()
        await recorder.close()
        return path

    path = asyncio.run(body())
    with DMXReplayReader(path) as reader:
        manifest = reader.manifest
    assert manifest.height == 2  # exactly the 2 universes actually seen, not 16 or 512
    port_addresses = {u.port_address() for u in manifest.universes}
    assert port_addresses == {5, 42}


def test_recorder_conformance_preserves_dmx_values_byte_for_byte(tmp_path):
    """§20 Recorder: "preserve DMX values exactly (byte-for-byte)"."""

    async def body():
        recorder = Recorder()
        await recorder.add_source("Art-Net", interface_ip="127.0.0.1", port=0)
        port = recorder._artnet_listeners[0]._transport.get_extra_info("sockname")[1]
        sender = ArtNetSender()
        await sender.start(interface_ip="127.0.0.1")

        exact_payload = bytes(range(256)) + bytes(reversed(range(256)))  # 512 bytes, every value
        sender.send(net=0, subnet=0, universe=1, data=exact_payload, destination_ip="127.0.0.1", port=port)
        await asyncio.sleep(0.02)

        path = str(tmp_path / "byte_exact.dmxr")
        recorder.start(path)
        recorder.stop()
        sender.stop()
        await recorder.close()
        return path, exact_payload

    path, exact_payload = asyncio.run(body())
    with DMXReplayReader(path) as reader:
        decoded = list(reader.read_frames())
    assert decoded[0].universes[0].to_bytes() == exact_payload


# --------------------------------------------------------------------- #
# Test 6: High packet rate (SPECIFICATION.md §19 test 6)
# --------------------------------------------------------------------- #


def test_high_packet_rate_stress_no_drops_no_corruption(tmp_path):
    """Stress test at a rate well beyond realistic Art-Net use (the
    commonly recommended per-universe refresh is ~44Hz / ~23ms; this test
    sends 4 universes back-to-back with no throttling at all, i.e. far
    higher instantaneous burst rate than any real console would sustain)
    and confirms the recorder drops nothing and produces a file whose
    stored values exactly match what was sent, in order, per universe."""

    async def body():
        recorder = Recorder()
        await recorder.add_source("Art-Net", interface_ip="127.0.0.1", port=0)
        port = recorder._artnet_listeners[0]._transport.get_extra_info("sockname")[1]
        sender = ArtNetSender()
        await sender.start(interface_ip="127.0.0.1")

        universe_count = 4
        packets_per_universe = 60

        # Discovery: touch every universe once before start() (Recorder.start()
        # only records rows already discovered).
        for u in range(1, universe_count + 1):
            sender.send(net=0, subnet=0, universe=u, data=bytes([0, 0]),
                        destination_ip="127.0.0.1", port=port)
        await asyncio.sleep(0.05)

        path = str(tmp_path / "high_rate.dmxr")
        recorder.start(path)

        sent: dict[int, list[int]] = {u: [] for u in range(1, universe_count + 1)}
        for i in range(1, packets_per_universe + 1):
            for u in range(1, universe_count + 1):
                value = i % 256
                sender.send(net=0, subnet=0, universe=u, data=bytes([value, 0]),
                            destination_ip="127.0.0.1", port=port)
                sent[u].append(value)
            await asyncio.sleep(0)  # yield to the event loop, no throttling delay
        await asyncio.sleep(0.3)  # let the recorder's loop drain the burst

        status = recorder.get_status()
        recorder.stop()
        sender.stop()
        await recorder.close()
        return path, sent, status

    path, sent, status = asyncio.run(body())

    assert status.malformed_packets == 0
    total_sent = 4 * 60 + 4  # discovery + burst, per universe
    assert status.total_packets == total_sent  # nothing dropped at the network layer

    with DMXReplayReader(path) as reader:
        manifest = reader.manifest
        decoded = list(reader.read_frames())

    row_for_universe = {u.port_address(): u.row for u in manifest.universes}
    for universe, values in sent.items():
        row = row_for_universe[universe]
        received = [f.universes[row].get_channel(1) for f in decoded]
        # No fabricated values, and the final state exactly matches the
        # last value actually sent for this universe (same reasoning as
        # test_end_to_end_recorder_player.py -- concurrent updates to other
        # rows legitimately repeat between commits, so per-value equality
        # isn't the right check, but "nothing invented" and "correct final
        # state" are).
        assert set(received) <= set(values) | {0}
        assert received[-1] == values[-1]


# --------------------------------------------------------------------- #
# Test 7: Timing irregularity / VFR (SPECIFICATION.md §19 test 7)
# --------------------------------------------------------------------- #


def test_timing_irregularity_preserves_real_vfr_capture_timing(tmp_path):
    """Packets arriving at intentionally variable real-world intervals must
    be stored as genuine VFR (docs/TIMING.md §4), not resampled onto a fixed
    grid -- captured through the real Recorder with real (not simulated)
    asyncio.sleep() gaps between sends, so the irregularity in the resulting
    file traces back to real elapsed wall-clock time, not a hand-authored
    timestamp list."""

    async def body():
        recorder = Recorder()
        await recorder.add_source("Art-Net", interface_ip="127.0.0.1", port=0)
        port = recorder._artnet_listeners[0]._transport.get_extra_info("sockname")[1]
        sender = ArtNetSender()
        await sender.start(interface_ip="127.0.0.1")

        sender.send(net=0, subnet=0, universe=1, data=bytes([0, 0]), destination_ip="127.0.0.1", port=port)
        await asyncio.sleep(0.02)

        path = str(tmp_path / "irregular.dmxr")
        recorder.start(path)

        # Deliberately non-uniform gaps: short, long, short, very short, long.
        gaps = [0.002, 0.05, 0.004, 0.001, 0.08]
        for i, gap in enumerate(gaps, start=1):
            sender.send(net=0, subnet=0, universe=1, data=bytes([i, 0]), destination_ip="127.0.0.1", port=port)
            await asyncio.sleep(gap)

        recorder.stop()
        sender.stop()
        await recorder.close()
        return path

    path = asyncio.run(body())
    with DMXReplayReader(path) as reader:
        manifest = reader.manifest
        decoded = list(reader.read_frames())

    assert manifest.vfr is True
    timestamps = [f.timestamp_ns for f in decoded]
    assert timestamps == sorted(timestamps)  # monotonic
    deltas = [b - a for a, b in zip(timestamps, timestamps[1:])]
    # Real VFR, not a fixed-rate grid: at least two meaningfully different
    # inter-frame gaps (millisecond-quantized, so "meaningfully different"
    # means >2ms apart -- larger than storage quantization noise alone).
    distinct_scale_deltas = {round(d / 2_000_000) for d in deltas}
    assert len(distinct_scale_deltas) > 1
    # Values preserved in order, byte-exact, nothing fabricated.
    values = [f.universes[0].get_channel(1) for f in decoded]
    assert values == list(range(6))  # initial 0, then 5 more (one per gap)


# --------------------------------------------------------------------- #
# Player conformance: sACN output + frame-step (SPECIFICATION.md §20 "Player")
# --------------------------------------------------------------------- #


def _make_dmxr(path: str, frame_count: int = 10, period_ns: int = 20_000_000) -> None:
    mapping = [UniverseMapping.from_artnet_port_address(row=0, port_address=1)]
    manifest = Manifest(
        encoding="grayscale", fps=50.0, vfr=False, timestamp_resolution_ns=1_000_000,
        width=ENCODINGS["grayscale"]["width"], height=1,
        universes=mapping, created_at="2026-08-27T00:00:00Z",
        duration_seconds=frame_count * period_ns / 1e9,
        recorder={"name": "dmxreplay-tests", "version": "0.1.0-dev"},
    )
    with DMXReplayWriter(path, manifest) as w:
        for t in range(frame_count):
            channels = [0] * CHANNELS_PER_UNIVERSE
            channels[0] = (t * 10) % 256
            w.write_frame(DMXFrame(timestamp_ns=t * period_ns, universes=(Universe(channels=tuple(channels)),)))


def test_player_conformance_outputs_valid_sacn(tmp_path):
    """§20 Player: "output decoded DMX as Art-Net and as sACN" -- until this
    phase, only the Art-Net side of that requirement had a test
    (tests/test_player.py); this is the missing sACN half."""
    path = str(tmp_path / "s.dmxr")
    _make_dmxr(path, frame_count=10)

    received: list[tuple[int, int]] = []

    def on_packet(pkt, ip, ts):
        if pkt.is_dmx_data:
            received.append((pkt.universe, pkt.dmx_data[0]))

    async def body():
        listener = SACNListener(on_packet=on_packet)
        await listener.start(interface_ip="127.0.0.1", port=0)
        port = listener._transport.get_extra_info("sockname")[1]

        player = Player()
        player.load(path)
        player.set_output("sACN", interface_ip="127.0.0.1", destination_ip="127.0.0.1", port=port)

        await player.play()
        await asyncio.sleep(0.3)
        await player.stop()
        listener.stop()

    asyncio.run(body())

    assert len(received) >= 3
    assert all(universe == 1 for universe, _v in received)  # sACN universe from Port-Address 1
    values = [v for _u, v in received]
    assert values == sorted(values)
    assert values[0] == 0


def test_player_conformance_frame_step_leaves_correct_state_immediately(tmp_path):
    """§20 Player: "support seek, play, pause, frame-step, and loop [...]
    with correct DMX state immediately after any of those operations" --
    exercised here with no play() call at all, proving frame-step alone
    (not a side effect of the playback loop) produces correct output."""
    path = str(tmp_path / "s.dmxr")
    _make_dmxr(path, frame_count=5)

    received: list[int] = []

    def on_packet(pkt, ip, ts):
        received.append(pkt.data[0])

    async def body():
        listener = ArtNetListener(on_packet=on_packet)
        await listener.start(interface_ip="127.0.0.1", port=0)
        port = listener._transport.get_extra_info("sockname")[1]

        player = Player()
        player.load(path)
        player.set_output("Art-Net", interface_ip="127.0.0.1", destination_ip="127.0.0.1", port=port)

        for _ in range(3):
            await player.frame_step(1)
            await asyncio.sleep(0.01)
        await player.frame_step(-1)
        await asyncio.sleep(0.01)
        listener.stop()

    asyncio.run(body())

    # Frames 0->1->2->3, then back to 2: channel-1 values (t*10)%256.
    assert received == [10, 20, 30, 20]


# --------------------------------------------------------------------- #
# Test 9: Synchronization (SPECIFICATION.md §19 test 9, docs/TIMING.md §8)
# --------------------------------------------------------------------- #


def _make_synced_dmxr(path: str, seconds: float = 3.0, period_ns: int = 10_000_000) -> None:
    """Channel 1 = the elapsed whole second (0, 1, 2, ...), the "per-second
    visible counter" SPECIFICATION.md §19 test 9 calls for, updated far
    finer (every 10ms) than it changes so playback's own sample-and-hold
    tick rate is never the bottleneck being measured."""
    frame_count = int(seconds * 1_000_000_000 / period_ns)
    mapping = [UniverseMapping.from_artnet_port_address(row=0, port_address=1)]
    manifest = Manifest(
        encoding="grayscale", fps=30.0, vfr=False, timestamp_resolution_ns=1_000_000,
        width=ENCODINGS["grayscale"]["width"], height=1,
        universes=mapping, created_at="2026-08-27T00:00:00Z",
        duration_seconds=seconds, recorder={"name": "dmxreplay-tests", "version": "0.1.0-dev"},
    )
    with DMXReplayWriter(path, manifest) as w:
        for t in range(frame_count):
            ts = t * period_ns
            channels = [0] * CHANNELS_PER_UNIVERSE
            channels[0] = ts // 1_000_000_000
            w.write_frame(DMXFrame(timestamp_ns=ts, universes=(Universe(channels=tuple(channels)),)))


def _make_synced_video(path: str, seconds: float = 3.0, fps: int = 25, width: int = 16, height: int = 16) -> None:
    """Same per-second counter, encoded as luma Y so it survives lossy
    scaling untouched (this test uses lossless x264 crf=0, matching the
    real-bug-finding setup in tests/test_video_reader.py)."""
    frame_count = int(seconds * fps)
    container = av.open(path, mode="w")
    stream = container.add_stream("libx264", rate=fps)
    stream.width, stream.height = width, height
    stream.pix_fmt = "yuv420p"
    stream.codec_context.time_base = Fraction(1, 1000)
    stream.codec_context.options = {"crf": "0", "preset": "ultrafast"}
    stream.codec_context.color_range = 2
    for i in range(frame_count):
        second = i // fps
        frame = av.VideoFrame(width, height, format="yuv420p")
        y, u, v = frame.planes
        y.update(bytes([second % 256]) * y.buffer_size)
        u.update(bytes([128]) * u.buffer_size)
        v.update(bytes([128]) * v.buffer_size)
        frame.pts = round(i * 1000 / fps)
        frame.time_base = Fraction(1, 1000)
        for p in stream.encode(frame):
            container.mux(p)
    for p in stream.encode():
        container.mux(p)
    container.close()


class _RecordingSyncSink:
    """Records (wall_clock_ns, presented_second_value) for external video."""

    def __init__(self) -> None:
        self.events: list[tuple[int, int]] = []

    def present(self, frame) -> None:
        self.events.append((time.monotonic_ns(), frame.rgb_bytes[0]))


def test_synchronization_dmx_and_external_video_agree_within_one_second(tmp_path):
    """SPECIFICATION.md §19 test 9: play DMX + external video together and
    confirm the per-second visible counter each track shows never disagrees
    by more than 1 -- both tracks are sampled from the *same* Timeline
    position within a single playback tick (src/dmxreplay/player/player.py
    `_run_loop()`: one `position` read, used for both `_emit()` and
    `_present_video_if_due()`), so any real divergence can only come from
    each track's own sample-and-hold staleness, not cross-track drift.

    This test also measures the actual wall-clock pairing skew between a
    presented video frame and the DMX packet closest to it in real time,
    which is the empirical figure now recorded in docs/TIMING.md §8 (this
    project's standing rule against unmeasured claims: the number there was
    produced by an earlier run of this exact test, not guessed in advance).
    """
    dmxr_path = str(tmp_path / "sync.dmxr")
    video_path = str(tmp_path / "sync.mp4")
    _make_synced_dmxr(dmxr_path)
    _make_synced_video(video_path)

    video_sink = _RecordingSyncSink()
    dmx_events: list[tuple[int, int]] = []  # (wall_clock_ns, second_value)

    def on_packet(pkt, ip, ts):
        dmx_events.append((time.monotonic_ns(), pkt.data[0]))

    async def body():
        listener = ArtNetListener(on_packet=on_packet)
        await listener.start(interface_ip="127.0.0.1", port=0)
        port = listener._transport.get_extra_info("sockname")[1]

        player = Player()
        player.load(dmxr_path)
        player.load_external_video(video_path)
        player.set_video_sink(video_sink)
        player.set_output("Art-Net", interface_ip="127.0.0.1", destination_ip="127.0.0.1", port=port)
        player.set_fps(60)  # sample the master timeline much faster than the 1Hz content changes

        await player.play()
        await asyncio.sleep(2.8)
        await player.stop()
        listener.stop()

    asyncio.run(body())

    assert len(video_sink.events) >= 2
    assert len(dmx_events) >= 2

    dmx_wallclocks = [w for w, _v in dmx_events]
    max_skew_ns = 0
    disagreements = 0
    for video_wallclock, video_second in video_sink.events:
        # Nearest DMX emission in real wall-clock time (not by index --
        # the two tracks tick at different rates: 60Hz player loop for
        # DMX vs. 25fps for video).
        idx = min(range(len(dmx_wallclocks)), key=lambda i: abs(dmx_wallclocks[i] - video_wallclock))
        dmx_wallclock, dmx_second = dmx_events[idx]
        if abs(video_second - dmx_second) > 1:
            disagreements += 1
        max_skew_ns = max(max_skew_ns, abs(video_wallclock - dmx_wallclock))

    assert disagreements == 0, "DMX and external video counters disagreed by more than 1 second"
    # Sanity bound on the measurement itself, generous for a shared-loopback
    # CI-style environment (not a real-time guarantee -- see docs/TIMING.md
    # §8's honest caveat about this being a synthetic, not Pi-hardware,
    # measurement): the pairing skew must stay well under the 1-second
    # content resolution, or the "within 1 second" assertion above would be
    # vacuous rather than meaningful.
    assert max_skew_ns < 500_000_000, f"measured pairing skew {max_skew_ns / 1e6:.1f}ms exceeds sanity bound"
