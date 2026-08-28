"""PlayerViewModel tests: no Tkinter import anywhere in this file or in
dmxreplay.ui.player_viewmodel/async_bridge -- these run in the normal test
venv, real asyncio-on-a-background-thread bridge, real Art-Net output over
a real UDP listener (same rig pattern as tests/test_player.py), just
driven through the view-model's synchronous-looking API instead of calling
Player directly. This is what proves the Tk <-> asyncio bridge design
(async_bridge.AsyncLoopThread) actually works before any widget exists.
"""
from __future__ import annotations

import asyncio
import time

from dmxreplay.codec import ENCODINGS
from dmxreplay.container import DMXReplayWriter
from dmxreplay.dmx import CHANNELS_PER_UNIVERSE, DMXFrame, Universe
from dmxreplay.metadata import Manifest, UniverseMapping
from dmxreplay.network.artnet import ArtNetListener
from dmxreplay.ui.async_bridge import AsyncLoopThread
from dmxreplay.ui.player_viewmodel import PlayerViewModel

FRAME_PERIOD_NS = 20_000_000  # 20ms/frame, matches tests/test_player.py


def _make_dmxr(path: str, frame_count: int = 10) -> None:
    mapping = [UniverseMapping.from_artnet_port_address(row=0, port_address=1)]
    manifest = Manifest(
        encoding="grayscale", fps=50.0, vfr=False, timestamp_resolution_ns=1_000_000,
        width=ENCODINGS["grayscale"]["width"], height=1,
        universes=mapping, created_at="2026-08-27T00:00:00Z",
        duration_seconds=frame_count * FRAME_PERIOD_NS / 1e9,
        recorder={"name": "dmxreplay-tests", "version": "0.1.0-dev"},
    )
    with DMXReplayWriter(path, manifest) as w:
        for t in range(frame_count):
            channels = [0] * CHANNELS_PER_UNIVERSE
            channels[0] = (t * 10) % 256
            w.write_frame(DMXFrame(timestamp_ns=t * FRAME_PERIOD_NS, universes=(Universe(channels=tuple(channels)),)))


def _start_rig() -> tuple[ArtNetListener, list, int, AsyncLoopThread]:
    """Real Art-Net listener, running on its own persistent background
    event-loop thread (same AsyncLoopThread the view-model itself uses) --
    NOT `asyncio.run()`, which would close its loop (and kill the
    transport) the instant `_start_rig()` returns, before any test body
    gets to use it. Caller must stop() both the listener and this loop at
    teardown."""
    received: list[tuple[int, int]] = []

    def on_packet(pkt, ip, ts):
        received.append((pkt.universe, pkt.data[0]))

    listener = ArtNetListener(on_packet=on_packet)
    rig_loop = AsyncLoopThread()
    future = asyncio.run_coroutine_threadsafe(
        listener.start(interface_ip="127.0.0.1", port=0), rig_loop.loop
    )
    future.result(timeout=2.0)
    port = listener._transport.get_extra_info("sockname")[1]
    return listener, received, port, rig_loop


def _stop_rig(listener: ArtNetListener, rig_loop: AsyncLoopThread) -> None:
    rig_loop.loop.call_soon_threadsafe(listener.stop)
    rig_loop.stop()


def test_open_file_updates_snapshot(tmp_path):
    path = str(tmp_path / "s.dmxr")
    _make_dmxr(path, frame_count=5)
    vm = PlayerViewModel()
    try:
        vm.open_file(path)
        snap = vm.snapshot()
        assert snap.loaded is True
        assert snap.filename == path
        assert snap.universe_count == 1
        assert snap.error_text is None
    finally:
        vm.shutdown()


def test_open_missing_file_sets_error_and_does_not_crash(tmp_path):
    vm = PlayerViewModel()
    try:
        vm.open_file(str(tmp_path / "does_not_exist.dmxr"))
        snap = vm.snapshot()
        assert snap.loaded is False
        assert snap.error_text is not None
    finally:
        vm.shutdown()


def test_play_without_output_reports_error_instead_of_raising(tmp_path):
    path = str(tmp_path / "s.dmxr")
    _make_dmxr(path)
    vm = PlayerViewModel()
    try:
        vm.open_file(path)
        vm.play()  # no configure_output() call
        snap = vm.snapshot()
        assert snap.error_text is not None
        assert snap.playing is False
    finally:
        vm.shutdown()


def test_play_pause_stop_through_the_view_model_produce_real_artnet(tmp_path):
    path = str(tmp_path / "s.dmxr")
    # 60 frames * 20ms = 1.2s of content -- long enough that "still playing
    # partway through" is a meaningful check, unlike the default 10-frame
    # (180ms) file, which would already be finished by a 0.3s sleep.
    _make_dmxr(path, frame_count=60)
    listener, received, port, rig_loop = _start_rig()
    vm = PlayerViewModel()
    try:
        vm.open_file(path)
        vm.configure_output("Art-Net", "127.0.0.1", "127.0.0.1", port)
        assert vm.snapshot().output_configured is True

        vm.play()
        time.sleep(0.3)
        assert vm.snapshot().playing is True
        assert len(received) >= 3

        vm.pause()
        time.sleep(0.05)
        count_at_pause = len(received)
        time.sleep(0.15)
        assert len(received) == count_at_pause  # nothing new while paused

        vm.stop()
        time.sleep(0.05)
        assert vm.snapshot().playing is False
    finally:
        vm.shutdown()
        _stop_rig(listener, rig_loop)


def test_seek_and_skip_reposition_correctly(tmp_path):
    path = str(tmp_path / "s.dmxr")
    _make_dmxr(path, frame_count=10)
    listener, received, port, rig_loop = _start_rig()
    vm = PlayerViewModel()
    try:
        vm.open_file(path)
        vm.configure_output("Art-Net", "127.0.0.1", "127.0.0.1", port)

        vm.seek_seconds(5 * FRAME_PERIOD_NS / 1e9)  # frame 5's timestamp
        vm.play()
        time.sleep(0.08)
        vm.stop()
        time.sleep(0.05)
        assert received[0][1] == 50  # frame 5's channel-1 value, (5*10)%256

        # stop() already left the timeline at position 0 (Player.stop()'s
        # own contract); skip forward from there. This file is only 180ms
        # long (10 * 20ms) and Player.seek() clamps to [0, duration_ns]
        # (player.py), so a 5-second fast-forward lands exactly at the
        # file's own end, not literally 5s in -- that clamping is real
        # Player behavior this test should observe, not paper over.
        vm.skip(1)  # fast-forward by SKIP_SECONDS
        time.sleep(0.05)  # let the call_soon_threadsafe-dispatched seek() land
        snap = vm.snapshot()
        assert snap.position_ns == snap.duration_ns
    finally:
        vm.shutdown()
        _stop_rig(listener, rig_loop)


def test_loop_and_speed_are_forwarded_to_player(tmp_path):
    path = str(tmp_path / "s.dmxr")
    _make_dmxr(path)
    vm = PlayerViewModel()
    try:
        vm.open_file(path)
        vm.set_loop(True)
        vm.set_speed(2.0)
        snap = vm.snapshot()
        assert snap.loop is True
        assert snap.speed == 2.0
    finally:
        vm.shutdown()
