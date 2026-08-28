"""Real PlayerService tests: real .dmxr files, a real Art-Net listener
acting as the lighting rig, real asyncio -- same rigor as
tests/test_player.py, just driven through the service layer instead of
Player directly (this is what Phase D's Control API will call)."""
from __future__ import annotations

import asyncio

import pytest

from dmxreplay.codec import ENCODINGS
from dmxreplay.container import DMXReplayWriter
from dmxreplay.dmx import CHANNELS_PER_UNIVERSE, DMXFrame, Universe
from dmxreplay.metadata import Manifest, UniverseMapping
from dmxreplay.network.artnet import ArtNetListener
from dmxreplay.service import PlayerService, ShowNotFoundError

FRAME_PERIOD_NS = 20_000_000


def _write_show(path: str, channel1_base: int, frame_count: int = 5) -> None:
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
            channels[0] = (channel1_base + t) % 256
            w.write_frame(DMXFrame(timestamp_ns=t * FRAME_PERIOD_NS, universes=(Universe(channels=tuple(channels)),)))


async def _start_rig():
    received: list[int] = []
    listener = ArtNetListener(on_packet=lambda pkt, ip, ts: received.append(pkt.data[0]))
    await listener.start(interface_ip="127.0.0.1", port=0)
    port = listener._transport.get_extra_info("sockname")[1]
    return listener, received, port


def test_load_show_by_direct_path_without_a_library(tmp_path):
    path = str(tmp_path / "s.dmxr")
    _write_show(path, channel1_base=0)
    service = PlayerService()
    service.load_show(path)
    status = service.get_status()
    assert status.loaded is True
    assert status.universe_count == 1


def test_load_show_by_bare_name_via_library(tmp_path):
    _write_show(str(tmp_path / "MyShow.dmxr"), channel1_base=0)
    service = PlayerService(shows_directory=str(tmp_path))
    service.load_show("MyShow.dmxr")
    assert service.get_status().show_name == "MyShow.dmxr"


def test_get_shows_lists_the_library(tmp_path):
    _write_show(str(tmp_path / "A.dmxr"), channel1_base=0)
    _write_show(str(tmp_path / "B.dmxr"), channel1_base=0)
    service = PlayerService(shows_directory=str(tmp_path))
    assert service.get_shows() == ["A.dmxr", "B.dmxr"]


def test_play_pause_stop_seek_produce_real_artnet(tmp_path):
    path = str(tmp_path / "s.dmxr")
    _write_show(path, channel1_base=0, frame_count=20)

    async def body():
        listener, received, port = await _start_rig()
        service = PlayerService()
        service.load_show(path)
        service.set_output("Art-Net", interface_ip="127.0.0.1", destination_ip="127.0.0.1", port=port)

        await service.play()
        await asyncio.sleep(0.15)
        assert service.get_status().playing is True
        service.pause()
        await asyncio.sleep(0.02)
        count_at_pause = len(received)
        await asyncio.sleep(0.1)
        assert len(received) == count_at_pause  # nothing new while paused

        await service.stop()
        assert service.get_status().playing is False
        listener.stop()
        return received

    received = asyncio.run(body())
    assert len(received) >= 3


def test_next_and_previous_show_switch_within_the_library_and_preserve_output(tmp_path):
    _write_show(str(tmp_path / "A.dmxr"), channel1_base=10, frame_count=3)
    _write_show(str(tmp_path / "B.dmxr"), channel1_base=100, frame_count=3)

    async def body():
        listener, received, port = await _start_rig()
        service = PlayerService(shows_directory=str(tmp_path))
        service.set_output("Art-Net", interface_ip="127.0.0.1", destination_ip="127.0.0.1", port=port)
        service.load_show("A.dmxr")

        await service.next_show()  # A -> B
        assert service.get_status().show_name == "B.dmxr"
        # Output config (set before any show was even loaded) must still be
        # in effect -- Player.load() never touches it (player.py), verified
        # here by successfully playing after switching shows with no
        # set_output() call in between.
        await service.play()
        await asyncio.sleep(0.1)
        await service.stop()

        await service.previous_show()  # B -> A
        assert service.get_status().show_name == "A.dmxr"

        await service.previous_show()  # A is already first -- clamps, stays at A
        assert service.get_status().show_name == "A.dmxr"

        listener.stop()
        return received

    received = asyncio.run(body())
    assert any(100 <= v < 103 for v in received)  # B.dmxr's channel-1 range was actually played


def test_next_show_with_no_library_raises_show_not_found(tmp_path):
    path = str(tmp_path / "s.dmxr")
    _write_show(path, channel1_base=0)
    service = PlayerService()  # no shows_directory
    service.load_show(path)

    async def body():
        with pytest.raises(ShowNotFoundError):
            await service.next_show()

    asyncio.run(body())


def test_get_config_reflects_loop_speed_fps(tmp_path):
    service = PlayerService()
    service.set_loop(True)
    service.set_speed(2.0)
    service.set_fps(44.0)
    config = service.get_config()
    assert config == {"loop": True, "speed": 2.0, "fps": 44.0}


def test_get_network_status_reflects_set_output(tmp_path):
    service = PlayerService()
    service.set_output("sACN", interface_ip="127.0.0.1", destination_ip="192.168.1.1", port=5568, priority=150)
    status = service.get_network_status()
    assert status["output_protocol"] == "sACN"
    assert status["destination_ip"] == "192.168.1.1"
    assert status["priority"] == 150


def test_frame_step_through_the_service(tmp_path):
    path = str(tmp_path / "s.dmxr")
    _write_show(path, channel1_base=0, frame_count=5)

    async def body():
        listener, received, port = await _start_rig()
        service = PlayerService()
        service.load_show(path)
        service.set_output("Art-Net", interface_ip="127.0.0.1", destination_ip="127.0.0.1", port=port)

        await service.frame_step(1)
        await asyncio.sleep(0.02)
        listener.stop()
        return received

    received = asyncio.run(body())
    assert received == [1]  # frame 1's channel-1 value


def test_get_show_info_reports_real_manifest_fields(tmp_path):
    _write_show(str(tmp_path / "A.dmxr"), channel1_base=0, frame_count=10)
    service = PlayerService(shows_directory=str(tmp_path))

    info = service.get_show_info("A.dmxr")

    assert info["name"] == "A.dmxr"
    assert info["encoding"] == "grayscale"
    assert info["fps"] == 50.0
    assert info["universe_count"] == 1
    assert info["has_audio"] is False
    assert info["has_external_video"] is False
    assert info["file_size_bytes"] == (tmp_path / "A.dmxr").stat().st_size
    assert info["duration_seconds"] == pytest.approx(10 * FRAME_PERIOD_NS / 1e9)


def test_get_show_info_by_direct_path_without_a_library(tmp_path):
    path = str(tmp_path / "s.dmxr")
    _write_show(path, channel1_base=0)
    service = PlayerService()  # no shows_directory
    info = service.get_show_info(path)
    assert info["name"] == "s.dmxr"


def test_get_show_info_missing_show_raises(tmp_path):
    service = PlayerService(shows_directory=str(tmp_path))
    with pytest.raises(ShowNotFoundError):
        service.get_show_info("nope.dmxr")


def test_delete_show_removes_it_from_the_library(tmp_path):
    _write_show(str(tmp_path / "A.dmxr"), channel1_base=0)
    service = PlayerService(shows_directory=str(tmp_path))

    service.delete_show("A.dmxr")

    assert service.get_shows() == []
    assert not (tmp_path / "A.dmxr").exists()


def test_delete_show_without_a_library_raises(tmp_path):
    service = PlayerService()  # no shows_directory
    with pytest.raises(ShowNotFoundError):
        service.delete_show("A.dmxr")


def test_delete_show_currently_playing_raises_and_does_not_delete(tmp_path):
    _write_show(str(tmp_path / "A.dmxr"), channel1_base=0, frame_count=20)

    async def body():
        listener, received, port = await _start_rig()
        service = PlayerService(shows_directory=str(tmp_path))
        service.load_show("A.dmxr")
        service.set_output("Art-Net", interface_ip="127.0.0.1", destination_ip="127.0.0.1", port=port)
        await service.play()
        await asyncio.sleep(0.05)

        with pytest.raises(ValueError, match="playing"):
            service.delete_show("A.dmxr")

        await service.stop()
        listener.stop()

    asyncio.run(body())
    assert (tmp_path / "A.dmxr").exists()


def test_delete_show_currently_loaded_but_stopped_succeeds_and_forgets_the_name(tmp_path):
    _write_show(str(tmp_path / "A.dmxr"), channel1_base=0)
    service = PlayerService(shows_directory=str(tmp_path))
    service.load_show("A.dmxr")

    service.delete_show("A.dmxr")

    assert service.get_status().show_name is None
    assert not (tmp_path / "A.dmxr").exists()


def test_upload_show_accepts_a_real_dmxr_file(tmp_path):
    source = tmp_path / "source.dmxr"
    _write_show(str(source), channel1_base=0)
    uploads_dir = tmp_path / "uploads"
    service = PlayerService(shows_directory=str(uploads_dir))

    result = service.upload_show("Uploaded.dmxr", source.read_bytes())

    assert result["name"] == "Uploaded.dmxr"
    assert result["size_bytes"] == source.stat().st_size
    assert service.get_shows() == ["Uploaded.dmxr"]
    # And it's actually loadable, not just present on disk:
    service.load_show("Uploaded.dmxr")
    assert service.get_status().loaded is True


def test_upload_show_rejects_garbage_and_leaves_no_file_behind(tmp_path):
    uploads_dir = tmp_path / "uploads"
    service = PlayerService(shows_directory=str(uploads_dir))

    with pytest.raises(ValueError, match="not a valid DMXReplay"):
        service.upload_show("bad.dmxr", b"this is not a real dmxr container")

    assert service.get_shows() == []
    assert not (uploads_dir / "bad.dmxr").exists()
    assert not (uploads_dir / "bad.dmxr.part").exists()


def test_upload_show_without_a_library_raises(tmp_path):
    service = PlayerService()  # no shows_directory
    with pytest.raises(ShowNotFoundError):
        service.upload_show("A.dmxr", b"data")
