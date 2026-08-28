"""HTTP + WebSocket Control API server (cross-platform extension Phase D).
A thin `aiohttp` wrapper over `CommandRouter` (router.py) -- see that
module's docstring for why the real-time DMX playback loop never lives
here. Wire protocol documented in docs/API.md §10 and docs/MOBILE_API.md.
"""
from __future__ import annotations

import asyncio
import json
import logging

from aiohttp import WSMsgType, web

from .auth import ApiToken
from .router import CommandError, CommandRouter, UnknownCommandError

logger = logging.getLogger("dmxreplay.control")

API_VERSION = "1.0"
STATUS_BROADCAST_INTERVAL_S = 1.0
WS_AUTH_TIMEOUT_S = 10.0


def _error(message: str, status: int) -> web.Response:
    return web.json_response({"ok": False, "error": message}, status=status)


class ControlServer:
    """Construct once per process; `.app` is a real `aiohttp.web.Application`
    -- run it with `aiohttp.web.run_app(server.app, ...)` or under
    `aiohttp.test_utils` in tests. `token=None` disables authentication
    entirely (local dev only -- never the default; see auth.py)."""

    def __init__(self, router: CommandRouter, token: ApiToken | None) -> None:
        self.router = router
        self.token = token
        self._ws_clients: set[web.WebSocketResponse] = set()
        self._broadcast_task: asyncio.Task | None = None

        app = web.Application(middlewares=[self._auth_middleware])
        app.router.add_get("/api/v1/version", self._handle_version)
        app.router.add_get("/api/v1/status", self._handle_status)
        app.router.add_get("/api/v1/shows", self._handle_shows)
        app.router.add_post("/api/v1/command", self._handle_command)
        app.router.add_get("/api/v1/ws", self._handle_ws)
        app.on_startup.append(self._on_startup)
        app.on_cleanup.append(self._on_cleanup)
        self.app = app

    # --- Auth ----------------------------------------------------------------

    def _http_authorized(self, request: web.Request) -> bool:
        if self.token is None:
            return True
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return False
        return self.token.matches(header[len("Bearer "):])

    @web.middleware
    async def _auth_middleware(self, request: web.Request, handler):
        # /version is the one endpoint a client needs before it has a
        # /version needs no token at all (to confirm it's even talking to a
        # DMXReplay server, and which API version). /ws is also exempt HERE
        # -- not because it skips auth, but because it authenticates a
        # different way (the first WS message, _ws_authenticate() below,
        # not an Authorization header) -- a real bug this test suite caught
        # on the first run: the WS handshake itself was being rejected
        # with 401 by this middleware before _handle_ws ever got a chance
        # to run its own auth flow, since a WS client legitimately sends no
        # such header for the upgrade request.
        if request.path in ("/api/v1/version", "/api/v1/ws"):
            return await handler(request)
        if not self._http_authorized(request):
            return _error("unauthorized", 401)
        return await handler(request)

    # --- HTTP handlers ---------------------------------------------------------

    async def _handle_version(self, request: web.Request) -> web.Response:
        return web.json_response({"api_version": API_VERSION, "auth_required": self.token is not None})

    async def _dispatch_to_response(self, command: str, params: dict) -> web.Response:
        try:
            result = await self.router.dispatch(command, params)
        except UnknownCommandError as exc:
            return _error(str(exc), 404)
        except CommandError as exc:
            return _error(str(exc), 409)
        return web.json_response({"ok": True, "command": command, "result": result})

    async def _handle_status(self, request: web.Request) -> web.Response:
        return await self._dispatch_to_response("GET_STATUS", {})

    async def _handle_shows(self, request: web.Request) -> web.Response:
        return await self._dispatch_to_response("GET_SHOWS", {})

    async def _handle_command(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return _error("malformed JSON body", 400)
        if not isinstance(body, dict) or not isinstance(body.get("command"), str):
            return _error("body must be {'command': str, 'params'?: object}", 400)
        return await self._dispatch_to_response(body["command"], body.get("params") or {})

    # --- WebSocket -------------------------------------------------------------

    async def _handle_ws(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)

        if self.token is not None and not await self._ws_authenticate(ws):
            await ws.close()
            return ws

        self._ws_clients.add(ws)
        try:
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                await self._handle_ws_message(ws, msg.data)
        finally:
            self._ws_clients.discard(ws)
        return ws

    async def _ws_authenticate(self, ws: web.WebSocketResponse) -> bool:
        """The FIRST message on an authenticated connection must be
        `{"type": "auth", "token": "..."}`. Deliberately not a query-string
        token: those leak into access logs, browser history, and
        intermediate proxies far more readily than a message payload."""
        try:
            first = await asyncio.wait_for(ws.receive_json(), timeout=WS_AUTH_TIMEOUT_S)
        except (asyncio.TimeoutError, ValueError, TypeError):
            first = None
        ok = isinstance(first, dict) and first.get("type") == "auth" and self.token.matches(first.get("token"))
        if ok:
            await ws.send_json({"type": "auth_ok"})
        else:
            await ws.send_json({"type": "error", "error": "unauthorized"})
        return ok

    async def _handle_ws_message(self, ws: web.WebSocketResponse, raw: str) -> None:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            await ws.send_json({"type": "error", "error": "malformed JSON"})
            return
        command = payload.get("command") if isinstance(payload, dict) else None
        if not isinstance(command, str):
            await ws.send_json({"type": "error", "error": "'command' must be a string"})
            return
        params = payload.get("params") or {}
        try:
            result = await self.router.dispatch(command, params)
            await ws.send_json({"type": "response", "command": command, "ok": True, "result": result})
        except (UnknownCommandError, CommandError) as exc:
            await ws.send_json({"type": "response", "command": command, "ok": False, "error": str(exc)})

    # --- Real-time status broadcast (WebSocket only -- brief's own preference) ---

    async def _broadcast_status_loop(self) -> None:
        while True:
            await asyncio.sleep(STATUS_BROADCAST_INTERVAL_S)
            if not self._ws_clients or self.router.player is None:
                continue
            status = await self.router.dispatch("GET_STATUS")
            message = json.dumps({"type": "status", "data": status})
            dead = []
            for ws in list(self._ws_clients):
                try:
                    await ws.send_str(message)
                except ConnectionResetError:
                    dead.append(ws)
            for ws in dead:
                self._ws_clients.discard(ws)

    async def _on_startup(self, app: web.Application) -> None:
        self._broadcast_task = asyncio.create_task(self._broadcast_status_loop())

    async def _on_cleanup(self, app: web.Application) -> None:
        if self._broadcast_task is not None:
            self._broadcast_task.cancel()
            try:
                await self._broadcast_task
            except asyncio.CancelledError:
                pass
        for ws in list(self._ws_clients):
            await ws.close()
