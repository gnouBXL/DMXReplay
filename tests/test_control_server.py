"""Real HTTP + WebSocket tests for dmxreplay.control.ControlServer, using
aiohttp's own test utilities directly (TestServer/TestClient -- a real
server bound to a real ephemeral port, a real client, not mocked; no
pytest-aiohttp plugin needed, matching this project's existing convention
of `def test_x(): asyncio.run(body())` for every other async test rather
than a pytest-asyncio-style fixture), plus real Art-Net traffic underneath
to confirm PLAY actually plays.
"""
from __future__ import annotations

import asyncio

from aiohttp.test_utils import TestClient, TestServer

from dmxreplay.codec import ENCODINGS
from dmxreplay.container import DMXReplayWriter
from dmxreplay.control import ApiToken, CommandRouter, ControlServer
from dmxreplay.dmx import CHANNELS_PER_UNIVERSE, DMXFrame, Universe
from dmxreplay.metadata import Manifest, UniverseMapping
from dmxreplay.network.artnet import ArtNetListener
from dmxreplay.service import PlayerService

FRAME_PERIOD_NS = 20_000_000


def _write_show(path: str, frame_count: int = 20) -> None:
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


def test_version_endpoint_needs_no_auth():
    async def body():
        server = ControlServer(CommandRouter(), token=ApiToken.generate())
        async with TestClient(TestServer(server.app)) as client:
            resp = await client.get("/api/v1/version")
            assert resp.status == 200
            payload = await resp.json()
            assert payload["api_version"] == "1.0"
            assert payload["auth_required"] is True

    asyncio.run(body())


def test_status_endpoint_rejects_missing_auth():
    async def body():
        server = ControlServer(CommandRouter(player_service=PlayerService()), token=ApiToken.generate())
        async with TestClient(TestServer(server.app)) as client:
            resp = await client.get("/api/v1/status")
            assert resp.status == 401

    asyncio.run(body())


def test_status_endpoint_rejects_wrong_token():
    async def body():
        server = ControlServer(CommandRouter(player_service=PlayerService()), token=ApiToken.generate())
        async with TestClient(TestServer(server.app)) as client:
            resp = await client.get("/api/v1/status", headers={"Authorization": "Bearer wrong-token"})
            assert resp.status == 401

    asyncio.run(body())


def test_status_endpoint_accepts_correct_token():
    async def body():
        token = ApiToken.generate()
        server = ControlServer(CommandRouter(player_service=PlayerService()), token=token)
        async with TestClient(TestServer(server.app)) as client:
            resp = await client.get("/api/v1/status", headers={"Authorization": f"Bearer {token.value}"})
            assert resp.status == 200
            payload = await resp.json()
            assert payload["ok"] is True
            assert payload["result"]["loaded"] is False

    asyncio.run(body())


def test_no_token_configured_disables_auth():
    async def body():
        server = ControlServer(CommandRouter(player_service=PlayerService()), token=None)
        async with TestClient(TestServer(server.app)) as client:
            resp = await client.get("/api/v1/status")
            assert resp.status == 200

    asyncio.run(body())


def test_command_endpoint_full_play_sequence_over_real_artnet(tmp_path):
    show_path = str(tmp_path / "s.dmxr")
    _write_show(show_path)

    async def body():
        listener_received: list[int] = []
        listener = ArtNetListener(on_packet=lambda pkt, ip, ts: listener_received.append(pkt.data[0]))
        await listener.start(interface_ip="127.0.0.1", port=0)
        rig_port = listener._transport.get_extra_info("sockname")[1]

        token = ApiToken.generate()
        player = PlayerService()
        player.load_show(show_path)
        server = ControlServer(CommandRouter(player_service=player), token=token)
        headers = {"Authorization": f"Bearer {token.value}"}

        async with TestClient(TestServer(server.app)) as client:
            resp = await client.post("/api/v1/command", json={
                "command": "SET_CONFIG",
                "params": {
                    "protocol": "Art-Net", "interface_ip": "127.0.0.1",
                    "destination_ip": "127.0.0.1", "port": rig_port,
                },
            }, headers=headers)
            assert resp.status == 200
            assert (await resp.json())["ok"] is True

            resp = await client.post("/api/v1/command", json={"command": "PLAY"}, headers=headers)
            assert resp.status == 200

            await asyncio.sleep(0.2)

            resp = await client.get("/api/v1/status", headers=headers)
            status = (await resp.json())["result"]
            assert status["playing"] is True
            assert len(listener_received) >= 3

            resp = await client.post("/api/v1/command", json={"command": "STOP"}, headers=headers)
            assert resp.status == 200
        listener.stop()

    asyncio.run(body())


def test_unknown_command_returns_404():
    async def body():
        token = ApiToken.generate()
        server = ControlServer(CommandRouter(player_service=PlayerService()), token=token)
        async with TestClient(TestServer(server.app)) as client:
            resp = await client.post(
                "/api/v1/command", json={"command": "FLY_TO_THE_MOON"},
                headers={"Authorization": f"Bearer {token.value}"},
            )
            assert resp.status == 404

    asyncio.run(body())


def test_command_missing_required_service_returns_409():
    async def body():
        token = ApiToken.generate()
        server = ControlServer(CommandRouter(), token=token)  # no player, no recorder
        async with TestClient(TestServer(server.app)) as client:
            resp = await client.post(
                "/api/v1/command", json={"command": "GET_STATUS"},
                headers={"Authorization": f"Bearer {token.value}"},
            )
            assert resp.status == 409

    asyncio.run(body())


def test_websocket_requires_auth_message_first():
    async def body():
        token = ApiToken.generate()
        server = ControlServer(CommandRouter(player_service=PlayerService()), token=token)
        async with TestClient(TestServer(server.app)) as client:
            ws = await client.ws_connect("/api/v1/ws")
            await ws.send_json({"type": "auth", "token": "wrong"})
            reply = await ws.receive_json()
            assert reply["type"] == "error"
            await ws.close()

    asyncio.run(body())


def test_websocket_auth_then_command_round_trip(tmp_path):
    show_path = str(tmp_path / "s.dmxr")
    _write_show(show_path)

    async def body():
        token = ApiToken.generate()
        player = PlayerService()
        player.load_show(show_path)
        server = ControlServer(CommandRouter(player_service=player), token=token)
        async with TestClient(TestServer(server.app)) as client:
            ws = await client.ws_connect("/api/v1/ws")
            await ws.send_json({"type": "auth", "token": token.value})
            ok = await ws.receive_json()
            assert ok["type"] == "auth_ok"

            await ws.send_json({"command": "GET_STATUS"})
            reply = await ws.receive_json()
            assert reply["type"] == "response"
            assert reply["ok"] is True
            assert reply["result"]["loaded"] is True
            await ws.close()

    asyncio.run(body())


def test_websocket_broadcasts_status_to_connected_clients(tmp_path, monkeypatch):
    """The real-time status push the extension brief specifically asks
    WebSocket for -- not just request/response."""
    import dmxreplay.control.server as server_module
    monkeypatch.setattr(server_module, "STATUS_BROADCAST_INTERVAL_S", 0.05)  # keep the test fast

    show_path = str(tmp_path / "s.dmxr")
    _write_show(show_path)

    async def body():
        listener = ArtNetListener()
        await listener.start(interface_ip="127.0.0.1", port=0)
        rig_port = listener._transport.get_extra_info("sockname")[1]

        token = ApiToken.generate()
        player = PlayerService()
        player.load_show(show_path)
        player.set_output("Art-Net", interface_ip="127.0.0.1", destination_ip="127.0.0.1", port=rig_port)
        server = ControlServer(CommandRouter(player_service=player), token=token)

        async with TestClient(TestServer(server.app)) as client:
            ws = await client.ws_connect("/api/v1/ws")
            await ws.send_json({"type": "auth", "token": token.value})
            await ws.receive_json()  # auth_ok

            await player.play()
            msg = await asyncio.wait_for(ws.receive_json(), timeout=2.0)
            while msg.get("type") != "status":
                msg = await asyncio.wait_for(ws.receive_json(), timeout=2.0)
            assert msg["type"] == "status"
            assert "playing" in msg["data"]

            await player.stop()
            await ws.close()
        listener.stop()

    asyncio.run(body())
