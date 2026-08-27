"""Real Recorder tests: an actual ArtNetSender feeds an actual Recorder,
which writes a real .dmxr file, verified by reading it back."""
from __future__ import annotations

import asyncio

import pytest

from dmxreplay.container import DMXReplayReader
from dmxreplay.network.artnet import ArtNetSender
from dmxreplay.recorder import Recorder


async def _send_and_wait(sender: ArtNetSender, port: int, **kwargs) -> None:
    sender.send(destination_ip="127.0.0.1", port=port, **kwargs)
    await asyncio.sleep(0.02)  # let the recorder's event loop process it


def test_recorder_captures_real_artnet_traffic_into_a_dmxr_file(tmp_path):
    async def body():
        recorder = Recorder()
        await recorder.add_source("Art-Net", interface_ip="127.0.0.1", port=0)
        listener_port = recorder._artnet_listeners[0]._transport.get_extra_info("sockname")[1]

        sender = ArtNetSender()
        await sender.start(interface_ip="127.0.0.1")

        # Discovery phase: two universes, before recording starts.
        await _send_and_wait(sender, listener_port, net=0, subnet=0, universe=1, data=bytes([10, 20, 30, 0]))
        await _send_and_wait(sender, listener_port, net=0, subnet=0, universe=2, data=bytes([40, 50]))

        rows = recorder.get_universes()
        assert len(rows) == 2
        assert (rows[0].net, rows[0].subnet, rows[0].universe) == (0, 0, 1)
        assert (rows[1].net, rows[1].subnet, rows[1].universe) == (0, 0, 2)

        path = str(tmp_path / "captured.dmxr")
        recorder.start(path)

        # A few more updates while actively recording.
        await _send_and_wait(sender, listener_port, net=0, subnet=0, universe=1, data=bytes([99, 0]))
        await _send_and_wait(sender, listener_port, net=0, subnet=0, universe=2, data=bytes([200, 201]))

        status_while_recording = recorder.get_status()

        recorder.stop()
        sender.stop()
        await recorder.close()
        return path, status_while_recording

    path, status = asyncio.run(body())

    assert status.recording is True
    assert status.universe_count == 2
    assert status.frame_count >= 3  # initial snapshot + 2 updates
    assert status.malformed_packets == 0

    with DMXReplayReader(path) as reader:
        manifest = reader.manifest
        decoded = list(reader.read_frames())

    assert manifest.height == 2
    assert [u.universe for u in manifest.universes] == [1, 2]

    # First frame: state captured at start() -- row 0 = [10,20,30,0,...], row1=[40,50,0,...]
    first = decoded[0]
    assert first.universes[0].get_channel(1) == 10
    assert first.universes[0].get_channel(2) == 20
    assert first.universes[1].get_channel(1) == 40

    # Last frame reflects the most recent updates to both rows.
    last = decoded[-1]
    assert last.universes[0].get_channel(1) == 99
    assert last.universes[1].get_channel(1) == 200
    assert last.universes[1].get_channel(2) == 201


def test_recorder_rejects_start_before_any_universe_discovered(tmp_path):
    recorder = Recorder()
    with pytest.raises(RuntimeError):
        recorder.start(str(tmp_path / "empty.dmxr"))


def test_recorder_rejects_double_start(tmp_path):
    async def body():
        recorder = Recorder()
        await recorder.add_source("Art-Net", interface_ip="127.0.0.1", port=0)
        port = recorder._artnet_listeners[0]._transport.get_extra_info("sockname")[1]
        sender = ArtNetSender()
        await sender.start(interface_ip="127.0.0.1")
        await _send_and_wait(sender, port, net=0, subnet=0, universe=1, data=bytes([1, 0]))

        recorder.start(str(tmp_path / "a.dmxr"))
        with pytest.raises(RuntimeError):
            recorder.start(str(tmp_path / "b.dmxr"))

        recorder.stop()
        sender.stop()
        await recorder.close()

    asyncio.run(body())


def test_recorder_status_before_recording():
    recorder = Recorder()
    status = recorder.get_status()
    assert status.recording is False
    assert status.universe_count == 0
    assert status.file_size_bytes is None
