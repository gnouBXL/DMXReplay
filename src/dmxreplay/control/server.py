"""HTTP + WebSocket Control API server (cross-platform extension Phase D).
A thin `aiohttp` wrapper over `CommandRouter` (router.py) -- see that
module's docstring for why the real-time DMX playback loop never lives
here. Wire protocol documented in docs/API.md §10 and docs/MOBILE_API.md.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Callable

from aiohttp import WSMsgType, web

from .auth import ApiToken
from .logbuffer import RingBufferLogHandler
from .router import CommandError, CommandRouter, UnknownCommandError
from .webui import _with_token, render_config_page, render_logs_page, render_message_page

logger = logging.getLogger("dmxreplay.control")

API_VERSION = "1.0"
STATUS_BROADCAST_INTERVAL_S = 1.0
WS_AUTH_TIMEOUT_S = 10.0
# Generous for a real show file (docs/RASPBERRY_PI.md's benchmarks are all
# well under this for V1 show lengths) but not unbounded -- the whole
# upload is buffered in memory (see _handle_upload_show), so this is the
# cap on how much of the device's RAM one upload can claim. Streaming
# straight to disk would remove the need for a cap entirely; not done here
# -- a documented tradeoff, not an oversight (Phase H's hardware
# validation is where this would get stress-tested against a real Pi's
# available memory).
MAX_SHOW_UPLOAD_BYTES = 512 * 1024 * 1024


def _error(message: str, status: int) -> web.Response:
    return web.json_response({"ok": False, "error": message}, status=status)


class ControlServer:
    """Construct once per process; `.app` is a real `aiohttp.web.Application`
    -- run it with `aiohttp.web.run_app(server.app, ...)` or under
    `aiohttp.test_utils` in tests. `token=None` disables authentication
    entirely (local dev only -- never the default; see auth.py)."""

    def __init__(
        self, router: CommandRouter, token: ApiToken | None, *,
        device_name: str = "DMXReplay", dmxreplay_version: str = "0.1.0-dev",
        exit_fn: Callable[[int], None] | None = None,
        log_handler: RingBufferLogHandler | None = None,
    ) -> None:
        self.router = router
        self.token = token
        self.device_name = device_name
        self.dmxreplay_version = dmxreplay_version
        # Injectable so tests can assert "restart called exit(1)" without
        # actually terminating the test process -- os._exit (not sys.exit)
        # is the real default: sys.exit()/SystemExit raised inside an
        # asyncio Task is caught by the task machinery and reported as an
        # unhandled exception rather than terminating the interpreter, so
        # it would silently fail to actually restart/shut down anything.
        self._exit_fn = exit_fn or os._exit
        self.log_handler = log_handler or RingBufferLogHandler()
        dmxreplay_logger = logging.getLogger("dmxreplay")
        dmxreplay_logger.addHandler(self.log_handler)
        # A logger with no level explicitly set defers to its ancestors,
        # all the way up to the root logger's default of WARNING -- a real
        # bug this test suite caught: without this, INFO-level messages
        # (including this module's own "restart requested" logging) never
        # reached the ring buffer at all, silently making /config/logs far
        # less useful than intended.
        if dmxreplay_logger.level == logging.NOTSET or dmxreplay_logger.level > logging.INFO:
            dmxreplay_logger.setLevel(logging.INFO)

        self._ws_clients: set[web.WebSocketResponse] = set()
        self._broadcast_task: asyncio.Task | None = None

        app = web.Application(middlewares=[self._auth_middleware])
        app.router.add_get("/api/v1/version", self._handle_version)
        app.router.add_get("/api/v1/status", self._handle_status)
        app.router.add_get("/api/v1/shows", self._handle_shows)
        app.router.add_post("/api/v1/command", self._handle_command)
        app.router.add_put("/api/v1/shows/{name}", self._handle_upload_show)
        app.router.add_get("/api/v1/ws", self._handle_ws)
        # Local web config UI (extension brief §7/§18) -- docs/MOBILE_API.md
        # doesn't cover these; they serve HTML, not the JSON command
        # protocol, and are meant for a human with a browser, not an app.
        app.router.add_get("/config", self._handle_config_page)
        app.router.add_post("/config", self._handle_config_submit)
        app.router.add_post("/config/restart", self._handle_restart)
        app.router.add_post("/config/shutdown", self._handle_shutdown)
        app.router.add_get("/config/logs", self._handle_logs)
        app.on_startup.append(self._on_startup)
        app.on_cleanup.append(self._on_cleanup)
        self.app = app

    # --- Auth ----------------------------------------------------------------

    def _http_authorized(self, request: web.Request) -> bool:
        if self.token is None:
            return True
        header = request.headers.get("Authorization", "")
        if header.startswith("Bearer ") and self.token.matches(header[len("Bearer "):]):
            return True
        # /config* only: also accept ?token=... -- a human typing a URL
        # into a browser can't easily set a custom header, unlike the JSON
        # API (docs/MOBILE_API.md §4), where a query-string token is
        # deliberately rejected (it leaks into logs/history far more
        # readily). Scoped to /config* specifically, not a blanket
        # allowance, and documented here as the one deliberate exception
        # to that rule rather than an inconsistency.
        if request.path.startswith("/config") and self.token.matches(request.query.get("token")):
            return True
        return False

    @web.middleware
    async def _auth_middleware(self, request: web.Request, handler):
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
        except (CommandError, ValueError, OSError, RuntimeError) as exc:
            # CommandError is the router's own "recognized but couldn't be
            # carried out" signal; the other three are what the underlying
            # Player/Recorder/ShowLibrary calls actually raise (a missing
            # show file, an invalid fps, a disk error deleting/saving a
            # show, ...) -- docs/MOBILE_API.md §7 documents ALL of these as
            # one 409 row ("A Player/Recorder call itself raises"), so this
            # catches what that row promises rather than only the router's
            # own validation errors.
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

    async def _handle_upload_show(self, request: web.Request) -> web.Response:
        """`PUT /api/v1/shows/{name}`, raw `.dmxr` bytes as the body --
        Phase G's "upload from client to Pi". Deliberately its own HTTP
        endpoint, not a JSON command: the command protocol (§5's
        `POST /api/v1/command`) is JSON in and out, not a place to smuggle
        an arbitrarily large binary payload through, and this way a client
        gets normal HTTP upload semantics (Content-Length, a PUT-to-a-named-
        resource shape) instead of base64-in-JSON overhead."""
        name = request.match_info["name"]
        if request.content_length is not None and request.content_length > MAX_SHOW_UPLOAD_BYTES:
            return _error(f"upload exceeds the {MAX_SHOW_UPLOAD_BYTES}-byte limit", 413)
        data = await request.read()
        if len(data) > MAX_SHOW_UPLOAD_BYTES:
            return _error(f"upload exceeds the {MAX_SHOW_UPLOAD_BYTES}-byte limit", 413)
        try:
            player = self.router.require_player()
            result = player.upload_show(name, data)
        except (CommandError, ValueError, OSError) as exc:
            return _error(str(exc), 409)
        return web.json_response({"ok": True, "result": result})

    # --- Local web config UI (extension brief §7/§18) ---------------------------

    def _request_token(self, request: web.Request) -> str | None:
        """The token to embed in the rendered page's links/forms, so
        continued navigation stays authenticated -- only meaningful when
        this request itself was authenticated via ?token= (see
        _http_authorized); a header-authenticated request has no token to
        carry forward into a browser's next navigation anyway."""
        return request.query.get("token")

    async def _handle_config_page(self, request: web.Request) -> web.Response:
        token = self._request_token(request)
        try:
            status = await self.router.dispatch("GET_STATUS")
            config = await self.router.dispatch("GET_CONFIG")  # already merges network settings, router.py
        except CommandError as exc:
            return web.Response(
                text=render_message_page(title="DMXReplay -- not ready", message=str(exc), token=token),
                content_type="text/html", status=409,
            )
        body = render_config_page(
            device_name=self.device_name, dmxreplay_version=self.dmxreplay_version,
            status=status, config=config, network=config, token=token,
        )
        return web.Response(text=body, content_type="text/html")

    async def _handle_config_submit(self, request: web.Request) -> web.Response:
        token = self._request_token(request)
        data = await request.post()
        params: dict = {"loop": "loop" in data}
        if data.get("speed"):
            params["speed"] = float(data["speed"])
        params["fps"] = float(data["fps"]) if data.get("fps") else None
        if data.get("protocol"):
            params["protocol"] = data["protocol"]
            params["interface_ip"] = data.get("interface_ip") or "0.0.0.0"
            params["destination_ip"] = data.get("destination_ip") or None
            params["port"] = int(data["port"]) if data.get("port") else None
            params["priority"] = int(data["priority"]) if data.get("priority") else 100
        try:
            await self.router.dispatch("SET_CONFIG", params)
        except (CommandError, ValueError) as exc:
            return web.Response(
                text=render_message_page(title="DMXReplay -- could not apply settings", message=str(exc), token=token),
                content_type="text/html", status=409,
            )
        raise web.HTTPFound(_with_token("/config", token))

    async def _handle_restart(self, request: web.Request) -> web.Response:
        """Stops services cleanly, then exits with a NON-ZERO status so
        the systemd unit's Restart=on-failure policy (docs/RASPBERRY_PI_INSTALL.md
        §4, packaging/systemd/dmxreplay-player.service) brings the process
        back -- not systemctl restart (would need elevated permissions
        this process shouldn't assume it has), and not sys.exit() (see the
        __init__ docstring note on why that's silently wrong inside
        asyncio)."""
        logger.info("Restart requested via local web config UI")
        await self._shutdown_services()
        self._exit_fn(1)
        return web.Response(text="restarting")

    async def _handle_shutdown(self, request: web.Request) -> web.Response:
        """Same mechanism as restart, but exits 0 -- systemd's
        Restart=on-failure does NOT trigger on a clean exit, matching
        "safe shutdown"'s intent exactly (docs/RASPBERRY_PI_INSTALL.md §4)."""
        logger.info("Safe shutdown requested via local web config UI")
        await self._shutdown_services()
        self._exit_fn(0)
        return web.Response(text="shutting down")

    async def _shutdown_services(self) -> None:
        if self.router.player is not None:
            await self.router.player.shutdown()
        if self.router.recorder is not None:
            await self.router.recorder.shutdown()

    async def _handle_logs(self, request: web.Request) -> web.Response:
        token = self._request_token(request)
        body = render_logs_page(device_name=self.device_name, lines=self.log_handler.lines(), token=token)
        return web.Response(text=body, content_type="text/html")

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
        except (UnknownCommandError, CommandError, ValueError, OSError, RuntimeError) as exc:
            # Same broadened set as _dispatch_to_response's HTTP path --
            # see that method's comment.
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
