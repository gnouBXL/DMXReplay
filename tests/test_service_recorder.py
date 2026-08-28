"""Real RecorderService tests: real Art-Net traffic, real .dmxr output,
verified by reading it back -- same rigor as tests/test_recorder.py, via
the service layer Phase D's Control API will call."""
from __future__ import annotations

import asyncio

from dmxreplay.container import DMXReplayReader
from dmxreplay.network.artnet import ArtNetSender
from dmxreplay.service import RecorderService


async def _send_and_wait(sender: ArtNetSender, port: int, **kwargs) -> None:
    sender.send(destination_ip="127.0.0.1", port=port, **kwargs)
    await asyncio.sleep(0.02)


def test_add_source_and_universe_discovery():
    async def body():
        service = RecorderService()
        await service.add_source("Art-Net", "127.0.0.1", port=0)
        port = service._recorder._artnet_listeners[0]._transport.get_extra_info("sockname")[1]

        sender = ArtNetSender()
        await sender.start(interface_ip="127.0.0.1")
        await _send_and_wait(sender, port, net=0, subnet=0, universe=1, data=bytes([10, 20]))

        rows = service.get_universes()
        sender.stop()
        await service.shutdown()
        return rows

    rows = asyncio.run(body())
    assert len(rows) == 1
    assert rows[0].universe == 1


def test_record_start_stop_via_library_produces_a_real_readable_dmxr(tmp_path):
    async def body():
        service = RecorderService(shows_directory=str(tmp_path))
        await service.add_source("Art-Net", "127.0.0.1", port=0)
        port = service._recorder._artnet_listeners[0]._transport.get_extra_info("sockname")[1]

        sender = ArtNetSender()
        await sender.start(interface_ip="127.0.0.1")
        await _send_and_wait(sender, port, net=0, subnet=0, universe=1, data=bytes([1, 0]))

        service.record_start("recorded.dmxr")  # bare name, resolved into the library
        status = service.get_status()
        assert status.recording is True
        assert service.output_filename == "recorded.dmxr"

        await _send_and_wait(sender, port, net=0, subnet=0, universe=1, data=bytes([99, 0]))

        service.record_stop()
        assert service.get_status().recording is False
        sender.stop()
        await service.shutdown()

    asyncio.run(body())

    with DMXReplayReader(str(tmp_path / "recorded.dmxr")) as reader:
        decoded = list(reader.read_frames())
    assert decoded[-1].universes[0].get_channel(1) == 99


def test_record_start_by_full_path_without_a_library(tmp_path):
    path = str(tmp_path / "direct.dmxr")

    async def body():
        service = RecorderService()  # no shows_directory
        await service.add_source("Art-Net", "127.0.0.1", port=0)
        port = service._recorder._artnet_listeners[0]._transport.get_extra_info("sockname")[1]

        sender = ArtNetSender()
        await sender.start(interface_ip="127.0.0.1")
        await _send_and_wait(sender, port, net=0, subnet=0, universe=1, data=bytes([5, 0]))

        service.record_start(path)
        service.record_stop()
        sender.stop()
        await service.shutdown()

    asyncio.run(body())
    with DMXReplayReader(path) as reader:
        assert list(reader.read_frames())
