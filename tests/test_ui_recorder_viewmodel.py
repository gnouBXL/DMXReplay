"""RecorderViewModel tests -- no Tkinter import, real Art-Net traffic
through the real async bridge, same pattern as
test_ui_player_viewmodel.py."""
from __future__ import annotations

import asyncio
import time

from dmxreplay.container import DMXReplayReader
from dmxreplay.network.artnet import ArtNetSender
from dmxreplay.ui.async_bridge import AsyncLoopThread
from dmxreplay.ui.recorder_viewmodel import RecorderViewModel


def _start_sender() -> tuple[ArtNetSender, AsyncLoopThread]:
    sender = ArtNetSender()
    sender_loop = AsyncLoopThread()
    future = asyncio.run_coroutine_threadsafe(sender.start(interface_ip="127.0.0.1"), sender_loop.loop)
    future.result(timeout=2.0)
    return sender, sender_loop


def _stop_sender(sender: ArtNetSender, sender_loop: AsyncLoopThread) -> None:
    sender_loop.loop.call_soon_threadsafe(sender.stop)
    sender_loop.stop()


def test_add_source_and_universe_discovery(tmp_path):
    sender, sender_loop = _start_sender()
    vm = RecorderViewModel()
    try:
        vm.add_source("Art-Net", "127.0.0.1", port=0)
        time.sleep(0.05)
        port = vm._recorder._artnet_listeners[0]._transport.get_extra_info("sockname")[1]

        sender.send(net=0, subnet=0, universe=1, data=bytes([10, 20]),
                    destination_ip="127.0.0.1", port=port)
        time.sleep(0.05)

        rows = vm.refresh_universes()
        assert len(rows) == 1
        assert rows[0].universe == 1
        assert vm.snapshot().error_text is None
    finally:
        vm.shutdown()
        _stop_sender(sender, sender_loop)


def test_start_stop_produces_a_real_readable_dmxr(tmp_path):
    sender, sender_loop = _start_sender()
    vm = RecorderViewModel()
    try:
        vm.add_source("Art-Net", "127.0.0.1", port=0)
        time.sleep(0.05)
        port = vm._recorder._artnet_listeners[0]._transport.get_extra_info("sockname")[1]

        sender.send(net=0, subnet=0, universe=1, data=bytes([1, 2]),
                    destination_ip="127.0.0.1", port=port)
        time.sleep(0.05)

        path = str(tmp_path / "recorded.dmxr")
        vm.start(path)
        snap = vm.snapshot()
        assert snap.status.recording is True
        assert snap.output_path == path

        sender.send(net=0, subnet=0, universe=1, data=bytes([99, 0]),
                    destination_ip="127.0.0.1", port=port)
        time.sleep(0.05)

        vm.stop()
        assert vm.snapshot().status.recording is False
    finally:
        vm.shutdown()
        _stop_sender(sender, sender_loop)

    with DMXReplayReader(path) as reader:
        decoded = list(reader.read_frames())
    assert decoded[-1].universes[0].get_channel(1) == 99


def test_start_before_discovery_reports_error_instead_of_raising(tmp_path):
    vm = RecorderViewModel()
    try:
        vm.start(str(tmp_path / "empty.dmxr"))
        snap = vm.snapshot()
        assert snap.error_text is not None
        assert snap.status.recording is False
    finally:
        vm.shutdown()
