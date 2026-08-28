"""CommandRouter tests: real PlayerService/RecorderService underneath
(real Art-Net traffic, real .dmxr files), no aiohttp/network transport
involved at all -- this file proves the command *semantics* are correct
independent of HTTP/WebSocket, which tests/test_control_server.py then
covers as a thin transport layer on top."""
from __future__ import annotations

import asyncio

import pytest

from dmxreplay.codec import ENCODINGS
from dmxreplay.container import DMXReplayReader, DMXReplayWriter
from dmxreplay.control import COMMANDS, CommandError, CommandRouter, UnknownCommandError
from dmxreplay.dmx import CHANNELS_PER_UNIVERSE, DMXFrame, Universe
from dmxreplay.metadata import Manifest, UniverseMapping
from dmxreplay.network.artnet import ArtNetListener
from dmxreplay.service import PlayerService, RecorderService, ShowNotFoundError

FRAME_PERIOD_NS = 20_000_000


def _write_show(path: str, frame_count: int = 10) -> None:
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


def test_all_thirteen_brief_commands_are_registered():
    # The exact command list the extension brief's §4/§8 specifies.
    required = {
        "GET_STATUS", "GET_SHOWS", "LOAD_SHOW", "PLAY", "PAUSE", "STOP", "SEEK",
        "NEXT", "PREVIOUS", "RECORD_START", "RECORD_STOP", "GET_CONFIG",
        "SET_CONFIG", "GET_NETWORK_STATUS",
    }
    assert required <= set(COMMANDS)


def test_unknown_command_raises_unknown_command_error():
    router = CommandRouter()

    async def body():
        with pytest.raises(UnknownCommandError):
            await router.dispatch("FLY_TO_THE_MOON")

    asyncio.run(body())


def test_command_without_configured_service_raises_command_error():
    router = CommandRouter()  # no player, no recorder

    async def body():
        with pytest.raises(CommandError, match="no Player service"):
            await router.dispatch("GET_STATUS")

    asyncio.run(body())


def test_full_command_sequence_over_real_artnet(tmp_path):
    """LOAD_SHOW -> SET_CONFIG (output) -> PLAY -> GET_STATUS -> PAUSE ->
    SEEK -> STOP, checked against a real Art-Net listener."""
    _write_show(str(tmp_path / "A.dmxr"))
    _write_show(str(tmp_path / "B.dmxr"))

    async def body():
        listener_received: list[int] = []
        listener = ArtNetListener(on_packet=lambda pkt, ip, ts: listener_received.append(pkt.data[0]))
        await listener.start(interface_ip="127.0.0.1", port=0)
        port = listener._transport.get_extra_info("sockname")[1]

        router = CommandRouter(player_service=PlayerService(shows_directory=str(tmp_path)))

        shows = await router.dispatch("GET_SHOWS")
        assert shows == ["A.dmxr", "B.dmxr"]

        status = await router.dispatch("LOAD_SHOW", {"name": "A.dmxr"})
        assert status["show_name"] == "A.dmxr"
        assert status["loaded"] is True

        config = await router.dispatch("SET_CONFIG", {
            "protocol": "Art-Net", "interface_ip": "127.0.0.1",
            "destination_ip": "127.0.0.1", "port": port, "loop": True, "speed": 1.0,
        })
        assert config["loop"] is True
        assert config["output_protocol"] == "Art-Net"

        await router.dispatch("PLAY")
        await asyncio.sleep(0.15)
        status = await router.dispatch("GET_STATUS")
        assert status["playing"] is True
        assert len(listener_received) >= 3

        await router.dispatch("PAUSE")
        status = await router.dispatch("GET_STATUS")
        assert status["playing"] is False

        status = await router.dispatch("SEEK", {"seconds": 0.0})
        assert status["position_ns"] == 0

        await router.dispatch("STOP")
        listener.stop()

    asyncio.run(body())


def test_next_and_previous_show_commands(tmp_path):
    _write_show(str(tmp_path / "A.dmxr"))
    _write_show(str(tmp_path / "B.dmxr"))

    async def body():
        router = CommandRouter(player_service=PlayerService(shows_directory=str(tmp_path)))
        await router.dispatch("LOAD_SHOW", {"name": "A.dmxr"})
        status = await router.dispatch("NEXT")
        assert status["show_name"] == "B.dmxr"
        status = await router.dispatch("PREVIOUS")
        assert status["show_name"] == "A.dmxr"

    asyncio.run(body())


def test_load_show_without_name_raises_command_error():
    router = CommandRouter(player_service=PlayerService())

    async def body():
        with pytest.raises(CommandError, match="name"):
            await router.dispatch("LOAD_SHOW", {})

    asyncio.run(body())


def test_seek_without_seconds_raises_command_error():
    router = CommandRouter(player_service=PlayerService())

    async def body():
        with pytest.raises(CommandError, match="seconds"):
            await router.dispatch("SEEK", {})

    asyncio.run(body())


def test_record_start_stop_commands(tmp_path):
    from dmxreplay.network.artnet import ArtNetSender

    async def body():
        recorder = RecorderService(shows_directory=str(tmp_path))
        await recorder.add_source("Art-Net", "127.0.0.1", port=0)
        port = recorder._recorder._artnet_listeners[0]._transport.get_extra_info("sockname")[1]

        sender = ArtNetSender()
        await sender.start(interface_ip="127.0.0.1")
        sender.send(net=0, subnet=0, universe=1, data=bytes([7, 0]), destination_ip="127.0.0.1", port=port)
        await asyncio.sleep(0.02)

        router = CommandRouter(recorder_service=recorder)
        status = await router.dispatch("RECORD_START", {"filename": "captured.dmxr"})
        assert status["recording"] is True

        sender.send(net=0, subnet=0, universe=1, data=bytes([88, 0]), destination_ip="127.0.0.1", port=port)
        await asyncio.sleep(0.02)

        status = await router.dispatch("RECORD_STOP")
        assert status["recording"] is False
        sender.stop()
        await recorder.shutdown()

    asyncio.run(body())

    with DMXReplayReader(str(tmp_path / "captured.dmxr")) as reader:
        decoded = list(reader.read_frames())
    assert decoded[-1].universes[0].get_channel(1) == 88


def test_get_recorder_status_polls_without_restarting_recording(tmp_path):
    """A real gap found while building the Phase F mobile client: without
    this command, the only way to see live recording duration/packet
    counts was to call RECORD_START again -- which restarts the
    recording, corrupting exactly the state a status poll should just be
    reading."""
    from dmxreplay.network.artnet import ArtNetSender

    async def body():
        recorder = RecorderService(shows_directory=str(tmp_path))
        await recorder.add_source("Art-Net", "127.0.0.1", port=0)
        port = recorder._recorder._artnet_listeners[0]._transport.get_extra_info("sockname")[1]

        sender = ArtNetSender()
        await sender.start(interface_ip="127.0.0.1")
        sender.send(net=0, subnet=0, universe=1, data=bytes([1, 0]), destination_ip="127.0.0.1", port=port)
        await asyncio.sleep(0.02)

        router = CommandRouter(recorder_service=recorder)
        await router.dispatch("RECORD_START", {"filename": "polled.dmxr"})

        # Poll twice -- must not restart/reset the recording each time.
        first_poll = await router.dispatch("GET_RECORDER_STATUS")
        assert first_poll["recording"] is True
        frame_count_after_first_poll = first_poll["frame_count"]

        sender.send(net=0, subnet=0, universe=1, data=bytes([2, 0]), destination_ip="127.0.0.1", port=port)
        await asyncio.sleep(0.02)

        second_poll = await router.dispatch("GET_RECORDER_STATUS")
        assert second_poll["recording"] is True
        assert second_poll["frame_count"] > frame_count_after_first_poll  # kept accumulating, not reset

        await router.dispatch("RECORD_STOP")
        sender.stop()
        await recorder.shutdown()

    asyncio.run(body())


def test_get_recorder_status_without_recorder_service_raises_command_error():
    router = CommandRouter()  # no recorder_service

    async def body():
        with pytest.raises(CommandError, match="no Recorder service"):
            await router.dispatch("GET_RECORDER_STATUS")

    asyncio.run(body())


def test_get_show_info_and_delete_show_commands(tmp_path):
    _write_show(str(tmp_path / "A.dmxr"))
    _write_show(str(tmp_path / "B.dmxr"))

    async def body():
        router = CommandRouter(player_service=PlayerService(shows_directory=str(tmp_path)))

        info = await router.dispatch("GET_SHOW_INFO", {"name": "A.dmxr"})
        assert info["name"] == "A.dmxr"
        assert info["encoding"] == "grayscale"

        shows = await router.dispatch("DELETE_SHOW", {"name": "A.dmxr"})
        assert shows == ["B.dmxr"]  # DELETE_SHOW returns the updated library listing

    asyncio.run(body())
    assert not (tmp_path / "A.dmxr").exists()
    assert (tmp_path / "B.dmxr").exists()


def test_get_show_info_without_name_raises_command_error():
    router = CommandRouter(player_service=PlayerService())

    async def body():
        with pytest.raises(CommandError, match="name"):
            await router.dispatch("GET_SHOW_INFO", {})

    asyncio.run(body())


def test_delete_show_without_name_raises_command_error():
    router = CommandRouter(player_service=PlayerService())

    async def body():
        with pytest.raises(CommandError, match="name"):
            await router.dispatch("DELETE_SHOW", {})

    asyncio.run(body())


def test_load_show_on_a_file_that_no_longer_exists_raises_show_not_found_error(tmp_path):
    """docs/MOBILE_API.md §7's documented 409 row ("A Player/Recorder call
    itself raises") -- LOAD_SHOW propagates ShowLibrary's ShowNotFoundError,
    which the router itself doesn't catch (it's not a CommandError); it's
    dmxreplay.control.server's job to translate it into an HTTP 409, tested
    in test_control_server.py. Here we just confirm the router lets it
    through as a real exception rather than swallowing or mistranslating
    it."""
    router = CommandRouter(player_service=PlayerService(shows_directory=str(tmp_path)))

    async def body():
        with pytest.raises(ShowNotFoundError):
            await router.dispatch("LOAD_SHOW", {"name": "ghost.dmxr"})

    asyncio.run(body())


def test_record_start_without_filename_raises_command_error(tmp_path):
    router = CommandRouter(recorder_service=RecorderService(shows_directory=str(tmp_path)))

    async def body():
        with pytest.raises(CommandError, match="filename"):
            await router.dispatch("RECORD_START", {})

    asyncio.run(body())
