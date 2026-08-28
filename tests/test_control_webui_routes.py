"""Real HTTP tests for the /config* local web config UI routes wired into
ControlServer (server.py) -- aiohttp's own test server, not mocked."""
from __future__ import annotations

import asyncio

from aiohttp.test_utils import TestClient, TestServer

from dmxreplay.codec import ENCODINGS
from dmxreplay.container import DMXReplayWriter
from dmxreplay.control import ApiToken, CommandRouter, ControlServer
from dmxreplay.dmx import CHANNELS_PER_UNIVERSE, DMXFrame, Universe
from dmxreplay.metadata import Manifest, UniverseMapping
from dmxreplay.service import PlayerService


def _write_show(path: str) -> None:
    mapping = [UniverseMapping.from_artnet_port_address(row=0, port_address=1)]
    manifest = Manifest(
        encoding="grayscale", fps=30.0, vfr=False, timestamp_resolution_ns=1_000_000,
        width=ENCODINGS["grayscale"]["width"], height=1,
        universes=mapping, created_at="2026-08-27T00:00:00Z", duration_seconds=0.0,
        recorder={"name": "dmxreplay-tests", "version": "0.1.0-dev"},
    )
    with DMXReplayWriter(path, manifest) as w:
        w.write_frame(DMXFrame(timestamp_ns=0, universes=(Universe.blank(),)))


def test_config_page_requires_auth():
    async def body():
        server = ControlServer(CommandRouter(player_service=PlayerService()), token=ApiToken.generate())
        async with TestClient(TestServer(server.app)) as client:
            resp = await client.get("/config")
            assert resp.status == 401

    asyncio.run(body())


def test_config_page_accepts_query_token(tmp_path):
    show_path = str(tmp_path / "s.dmxr")
    _write_show(show_path)

    async def body():
        token = ApiToken.generate()
        player = PlayerService()
        player.load_show(show_path)
        server = ControlServer(CommandRouter(player_service=player), token=token, device_name="Stage")
        async with TestClient(TestServer(server.app)) as client:
            resp = await client.get(f"/config?token={token.value}")
            assert resp.status == 200
            text = await resp.text()
            assert "Stage" in text
            assert "s.dmxr" in text
            # The page's own form actions must carry the token forward too.
            assert f"token={token.value}" in text

    asyncio.run(body())


def test_config_page_rejects_wrong_query_token():
    async def body():
        server = ControlServer(CommandRouter(player_service=PlayerService()), token=ApiToken.generate())
        async with TestClient(TestServer(server.app)) as client:
            resp = await client.get("/config?token=wrong")
            assert resp.status == 401

    asyncio.run(body())


def test_config_submit_applies_settings_live(tmp_path):
    show_path = str(tmp_path / "s.dmxr")
    _write_show(show_path)

    async def body():
        token = ApiToken.generate()
        player = PlayerService()
        player.load_show(show_path)
        server = ControlServer(CommandRouter(player_service=player), token=token)
        async with TestClient(TestServer(server.app)) as client:
            resp = await client.post(f"/config?token={token.value}", data={
                "loop": "on",
                "speed": "2.0",
                "protocol": "Art-Net",
                "interface_ip": "127.0.0.1",
                "destination_ip": "192.168.1.50",
                "port": "6454",
            }, allow_redirects=False)
            assert resp.status in (302, 303)

        status = player.get_status()
        assert status.loop is True
        assert status.speed == 2.0
        net = player.get_network_status()
        assert net["destination_ip"] == "192.168.1.50"

    asyncio.run(body())


def test_config_submit_unchecked_loop_checkbox_sets_loop_false(tmp_path):
    """HTML checkboxes are simply absent from form data when unchecked --
    this must be read as loop=False, not left unchanged."""
    show_path = str(tmp_path / "s.dmxr")
    _write_show(show_path)

    async def body():
        token = ApiToken.generate()
        player = PlayerService()
        player.load_show(show_path)
        player.set_loop(True)
        server = ControlServer(CommandRouter(player_service=player), token=token)
        async with TestClient(TestServer(server.app)) as client:
            await client.post(f"/config?token={token.value}", data={"speed": "1.0"}, allow_redirects=False)
        assert player.get_status().loop is False

    asyncio.run(body())


def test_restart_calls_injected_exit_fn_with_nonzero_and_stops_services(tmp_path):
    show_path = str(tmp_path / "s.dmxr")
    _write_show(show_path)
    exit_calls: list[int] = []

    async def body():
        token = ApiToken.generate()
        player = PlayerService()
        player.load_show(show_path)
        server = ControlServer(
            CommandRouter(player_service=player), token=token,
            exit_fn=lambda code: exit_calls.append(code),
        )
        async with TestClient(TestServer(server.app)) as client:
            resp = await client.post(f"/config/restart?token={token.value}")
            assert resp.status == 200

    asyncio.run(body())
    assert exit_calls == [1]  # non-zero -> systemd Restart=on-failure brings it back


def test_shutdown_calls_injected_exit_fn_with_zero():
    exit_calls: list[int] = []

    async def body():
        token = ApiToken.generate()
        server = ControlServer(
            CommandRouter(player_service=PlayerService()), token=token,
            exit_fn=lambda code: exit_calls.append(code),
        )
        async with TestClient(TestServer(server.app)) as client:
            resp = await client.post(f"/config/shutdown?token={token.value}")
            assert resp.status == 200

    asyncio.run(body())
    assert exit_calls == [0]  # clean exit -> systemd does NOT restart


def test_logs_page_shows_recent_log_lines():
    import logging

    async def body():
        token = ApiToken.generate()
        server = ControlServer(CommandRouter(player_service=PlayerService()), token=token)
        logging.getLogger("dmxreplay.test").info("something happened")
        async with TestClient(TestServer(server.app)) as client:
            resp = await client.get(f"/config/logs?token={token.value}")
            assert resp.status == 200
            text = await resp.text()
            assert "something happened" in text

    asyncio.run(body())
