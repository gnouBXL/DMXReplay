"""Real Player tests: build a real .dmxr, play it back, and verify the real
Art-Net UDP packets a simulated lighting rig receives."""
from __future__ import annotations

import asyncio

from dmxreplay.codec import ENCODINGS
from dmxreplay.container import DMXReplayWriter
from dmxreplay.dmx import CHANNELS_PER_UNIVERSE, DMXFrame, Universe
from dmxreplay.metadata import Manifest, UniverseMapping
from dmxreplay.network.artnet import ArtNetListener
from dmxreplay.player import Player

FRAME_PERIOD_NS = 20_000_000  # 20 ms/frame -> 50 fps content, fast enough for a snappy test


def _make_dmxr(path: str, frame_count: int = 10, universe_count: int = 2) -> None:
    frames = []
    for t in range(frame_count):
        universes = tuple(
            Universe(channels=tuple((t * 10 + u + ch) % 256 for ch in range(CHANNELS_PER_UNIVERSE)))
            for u in range(universe_count)
        )
        frames.append(DMXFrame(timestamp_ns=t * FRAME_PERIOD_NS, universes=universes))

    mapping = [
        UniverseMapping.from_artnet_port_address(row=i, port_address=i + 1)
        for i in range(universe_count)
    ]
    manifest = Manifest(
        encoding="grayscale", fps=50.0, vfr=False, timestamp_resolution_ns=1_000_000,
        width=ENCODINGS["grayscale"]["width"], height=universe_count,
        universes=mapping, created_at="2026-08-27T00:00:00Z",
        duration_seconds=frame_count * FRAME_PERIOD_NS / 1e9,
        recorder={"name": "dmxreplay-tests", "version": "0.1.0-dev"},
    )
    with DMXReplayWriter(path, manifest) as w:
        for f in frames:
            w.write_frame(f)


class _RigListener:
    """A simulated lighting rig: records every (row, channel-1-value) it
    receives over real Art-Net, in arrival order."""

    def __init__(self):
        self.received: list[tuple[int, int]] = []  # (universe_field, ch1_value)

    def on_packet(self, pkt, ip, ts):
        self.received.append((pkt.universe, pkt.data[0]))


async def _start_rig() -> tuple[ArtNetListener, _RigListener, int]:
    rig = _RigListener()
    listener = ArtNetListener(on_packet=rig.on_packet)
    await listener.start(interface_ip="127.0.0.1", port=0)
    port = listener._transport.get_extra_info("sockname")[1]
    return listener, rig, port


def test_player_load_reports_manifest_and_duration(tmp_path):
    path = str(tmp_path / "s.dmxr")
    _make_dmxr(path, frame_count=5, universe_count=1)
    player = Player()
    player.load(path)
    assert player.manifest.height == 1
    assert player.duration_ns == 4 * FRAME_PERIOD_NS


def test_play_sends_correct_dmx_over_real_artnet(tmp_path):
    path = str(tmp_path / "s.dmxr")
    _make_dmxr(path, frame_count=10, universe_count=1)

    async def body():
        listener, rig, port = await _start_rig()
        player = Player()
        player.load(path)
        player.set_output("Art-Net", interface_ip="127.0.0.1", destination_ip="127.0.0.1", port=port)

        await player.play()
        await asyncio.sleep(0.35)  # let ~10 frames' worth of 20ms-spaced content play
        await player.stop()
        listener.stop()
        return rig

    rig = asyncio.run(body())
    assert len(rig.received) >= 5  # most/all of the 10 frames should have been emitted
    # Channel 1 value for frame t is (t*10 + 0 + 0) % 256 = (t*10) % 256 -- strictly
    # increasing across the frames actually received, confirming real forward playback.
    values = [v for _u, v in rig.received]
    assert values == sorted(values)
    assert values[0] == 0  # first frame's channel 1 value


def test_seek_jumps_to_correct_dmx_state(tmp_path):
    path = str(tmp_path / "s.dmxr")
    _make_dmxr(path, frame_count=10, universe_count=1)

    async def body():
        listener, rig, port = await _start_rig()
        player = Player()
        player.load(path)
        player.set_output("Art-Net", interface_ip="127.0.0.1", destination_ip="127.0.0.1", port=port)

        player.seek(5 * FRAME_PERIOD_NS)  # jump straight to frame 5's timestamp
        await player.play()
        await asyncio.sleep(0.08)  # a couple of ticks, not the whole file
        await player.stop()
        listener.stop()
        return rig

    rig = asyncio.run(body())
    assert len(rig.received) >= 1
    # Frame 5's channel-1 value is (5*10) % 256 = 50 -- the very first packet
    # emitted after seeking must reflect that, not frame 0's value (0).
    assert rig.received[0][1] == 50


def test_pause_freezes_output(tmp_path):
    path = str(tmp_path / "s.dmxr")
    _make_dmxr(path, frame_count=10, universe_count=1)

    async def body():
        listener, rig, port = await _start_rig()
        player = Player()
        player.load(path)
        player.set_output("Art-Net", interface_ip="127.0.0.1", destination_ip="127.0.0.1", port=port)

        await player.play()
        await asyncio.sleep(0.05)
        player.pause()
        count_at_pause = len(rig.received)
        await asyncio.sleep(0.15)  # well past when more frames would have played
        count_after_wait = len(rig.received)
        await player.stop()
        listener.stop()
        return count_at_pause, count_after_wait

    count_at_pause, count_after_wait = asyncio.run(body())
    assert count_after_wait == count_at_pause  # no new packets while paused


def test_loop_restarts_from_the_beginning(tmp_path):
    path = str(tmp_path / "s.dmxr")
    _make_dmxr(path, frame_count=4, universe_count=1)  # short file: 4 * 20ms = 80ms total

    async def body():
        listener, rig, port = await _start_rig()
        player = Player()
        player.load(path)
        player.set_output("Art-Net", interface_ip="127.0.0.1", destination_ip="127.0.0.1", port=port)
        player.set_loop(True)

        await player.play()
        await asyncio.sleep(0.3)  # multiple loops of an 80ms file
        await player.stop()
        listener.stop()
        return rig

    rig = asyncio.run(body())
    values = [v for _u, v in rig.received]
    # Looping content is 0,10,20,30 repeating -- a value of 0 must reappear
    # after having advanced past it at least once (proof of an actual loop
    # restart, not just a single forward pass through 4 frames).
    assert values.count(0) >= 2


def test_reverse_playback_decreases_dmx_state(tmp_path):
    path = str(tmp_path / "s.dmxr")
    _make_dmxr(path, frame_count=10, universe_count=1)

    async def body():
        listener, rig, port = await _start_rig()
        player = Player()
        player.load(path)
        player.set_output("Art-Net", interface_ip="127.0.0.1", destination_ip="127.0.0.1", port=port)

        player.seek(9 * FRAME_PERIOD_NS)  # start near the end
        await player.play(speed=-1.0)
        await asyncio.sleep(0.15)
        await player.stop()
        listener.stop()
        return rig

    rig = asyncio.run(body())
    values = [v for _u, v in rig.received]
    assert len(values) >= 2
    # Scheduling jitter between seek() and the loop's first tick can shift
    # the very first emitted frame by one (180ms seek target vs. e.g. 179ms
    # by the time it's first checked), so allow frame 8 or 9 as the start --
    # what actually matters here is that playback runs backwards from near
    # the end, not the exact tick alignment.
    assert values[0] in (80, 90)
    assert values == sorted(values, reverse=True)  # non-increasing throughout


def test_universe_mapping_remaps_output_without_touching_the_file(tmp_path):
    path = str(tmp_path / "s.dmxr")
    _make_dmxr(path, frame_count=3, universe_count=1)  # recorded as Port-Address 1

    async def body():
        listener, rig, port = await _start_rig()
        player = Player()
        player.load(path)
        player.set_output("Art-Net", interface_ip="127.0.0.1", destination_ip="127.0.0.1", port=port)
        player.set_universe_mapping({0: 10})  # row 0 -> Port-Address 10 on output

        await player.play()
        await asyncio.sleep(0.1)
        await player.stop()
        listener.stop()
        return rig

    rig = asyncio.run(body())
    assert len(rig.received) >= 1
    assert all(universe_field == 10 for universe_field, _v in rig.received)
