# MOBILE_API.md — DMXReplay Control API wire protocol

Companion to [API.md](API.md) §10 (the Python `dmxreplay.control` implementation) and
[ARCHITECTURE.md](ARCHITECTURE.md) (Phase D). This document specifies the network
protocol itself — endpoints, commands, parameters, responses, errors, authentication,
WebSocket events, connection lifecycle, and versioning — so that a mobile app, a web
dashboard, or any other client can be built against it without reading the Python
implementation. Everything here is implemented and tested (`tests/test_control_server.py`,
real HTTP + WebSocket traffic against a real server, not mocked).

## 1. Transport and base URL

HTTP and WebSocket, both served by one process (`dmxreplay-server`) on one port
(default `8080`):

```
http://<device-ip>:8080/api/v1/...
ws://<device-ip>:8080/api/v1/ws
```

There is no HTTPS/WSS today — this is designed for a trusted local lighting network
(the extension brief's own framing), not the public internet. Don't port-forward this
port to the internet.

## 2. The one architectural rule this whole document exists to uphold

**This API never contains the real-time DMX playback loop.** Every command below is a
one-shot request/response that calls into `dmxreplay.service.PlayerService`/
`RecorderService` (`docs/API.md` §9), which itself calls `dmxreplay.player.Player`/
`dmxreplay.recorder.Recorder`. The device's own `Player._run_loop()` — its master
clock — is what actually paces DMX/audio/video output, continuously, on the device,
regardless of whether any client is connected. A client sends `PLAY`/`PAUSE`/`SEEK`;
it never sends individual DMX frames, and it is never required to stay connected for
playback to continue (`docs/ARCHITECTURE.md` §4's acceptance test). If your client
implementation is tempted to poll `GET_STATUS` faster than a few times a second "to
keep timing tight," that's a sign something is using this API for the wrong purpose —
use the WebSocket status broadcast (§6) for anything closer to real-time, and never
build a feature that depends on this connection's latency for correct lighting output.

## 3. Versioning

```
GET /api/v1/version
```

No authentication required (a client needs to be able to check this before it has a
token). Response:

```json
{"api_version": "1.0", "auth_required": true}
```

`api_version` follows the URL path's own `v1` prefix — a breaking change to this
protocol will be a new `/api/v2/...` path, not a silent change to `v1`'s behavior.
`auth_required` tells a client whether it needs to authenticate at all (a server
started with `--no-auth`, local development only, reports `false`).

## 4. Authentication

One shared bearer token per DMXReplay instance (`dmxreplay.control.ApiToken`),
generated on first run of `dmxreplay-server` and printed to its console/log, and
persisted to disk so restarting the service doesn't invalidate every already-paired
client. See `docs/API.md` §10/`docs/RASPBERRY_PI_INSTALL.md` for how an installer
surfaces it.

**"Pairing"** is: whoever set up the device reads the token once (console output,
`journalctl -u dmxreplay-server`, or eventually a QR code on a local web config page,
`docs/ARCHITECTURE.md` Phase E) and enters it into the mobile app. There is no
over-the-network pairing handshake — the brief's own framing for this API is staying
simple on a trusted local network, not building a full PKI for a LAN appliance.

**HTTP**: every endpoint except `GET /api/v1/version` requires

```
Authorization: Bearer <token>
```

A missing or incorrect token gets `401 Unauthorized`, body `{"ok": false, "error":
"unauthorized"}`.

**WebSocket**: the token is deliberately **not** sent as a query-string parameter
(those leak into access logs, browser history, and intermediate proxies far more
readily than a header or message payload does). Instead, the *first* message sent
immediately after the WebSocket upgrade must be:

```json
{"type": "auth", "token": "<token>"}
```

The server replies `{"type": "auth_ok"}` and the connection is now authenticated for
its lifetime, or `{"type": "error", "error": "unauthorized"}` followed by the server
closing the connection. A client that sends no message within 10 seconds of connecting
is also closed. If the server was started with `--no-auth`, this handshake is skipped
entirely — connect and send commands immediately.

## 5. Commands

Both transports dispatch the *same* commands through the *same* router
(`dmxreplay.control.CommandRouter`) — command names, parameters, and results never
diverge between HTTP and WebSocket.

| Command | Params | Requires |
|---|---|---|
| `GET_STATUS` | — | Player |
| `GET_SHOWS` | — | Player (with a show library configured) |
| `GET_SHOW_INFO` | `name` (string) | Player |
| `DELETE_SHOW` | `name` (string) | Player + show library |
| `LOAD_SHOW` | `name` (string — bare filename from `GET_SHOWS`, or a path) | Player |
| `PLAY` | — | Player, output configured |
| `PAUSE` | — | Player |
| `STOP` | — | Player |
| `SEEK` | `seconds` (number) | Player |
| `NEXT` | — | Player + show library |
| `PREVIOUS` | — | Player + show library |
| `RECORD_START` | `filename` (string) | Recorder (`dmxreplay-server --enable-recorder`) |
| `RECORD_STOP` | — | Recorder |
| `GET_RECORDER_STATUS` | — | Recorder |
| `GET_CONFIG` | — | Player |
| `SET_CONFIG` | `loop`?, `speed`?, `fps`?, `protocol`?, `interface_ip`?, `destination_ip`?, `port`?, `priority`? (all optional; output fields only applied if `protocol` is present) | Player |
| `GET_NETWORK_STATUS` | — | Player |

"Requires Player"/"Requires Recorder" means the server must have been started with
that service configured (`dmxreplay-server` always configures a `PlayerService`;
`--enable-recorder` adds a `RecorderService`) — calling `RECORD_START` against a
player-only server returns an error (§7), it does not silently no-op.

`NEXT`/`PREVIOUS` clamp at the ends of the show list (no wrap-around), the same
convention `Player.seek()`/`frame_step()` already use. `LOAD_SHOW`/`NEXT`/`PREVIOUS`
never reset output configuration — `SET_CONFIG`'s output fields persist across show
changes (verified: `tests/test_service_player.py`'s
`test_next_and_previous_show_switch_within_the_library_and_preserve_output`).

`GET_SHOW_INFO` returns per-show metadata (duration/fps/encoding/universe count/
has_audio/has_external_video/created_at/show_name/description/file_size_bytes) for any
show in the library, not just the currently-loaded one — see §6's `ShowInfo` shape.
`DELETE_SHOW` removes a show from the library and returns the updated `GET_SHOWS`
listing as `result`; it refuses (§7's 409) to delete the show that is currently
*playing* (stop it first) but permits deleting a show that's merely loaded-but-stopped.

`GET_RECORDER_STATUS` is a read-only poll of the same `RecorderStatus` shape
`RECORD_START`/`RECORD_STOP` already return (§6) — added for clients that need to
show live recording duration/frame/packet counts while a recording is in
progress, without re-issuing `RECORD_START` (which
would restart the recording, discarding what's already captured) and without
waiting for the operator to call `RECORD_STOP`. Calling it repeatedly never
changes recorder state (verified:
`tests/test_control_router.py::test_get_recorder_status_polls_without_restarting_recording`).

### HTTP request shape

```
POST /api/v1/command
Authorization: Bearer <token>
Content-Type: application/json

{"command": "SEEK", "params": {"seconds": 42.5}}
```

Two read-only convenience GET routes exist for the two most common polls, equivalent
to `POST /api/v1/command {"command": "GET_STATUS"}` / `{"command": "GET_SHOWS"}`:

```
GET /api/v1/status
GET /api/v1/shows
```

One more HTTP-only route, outside the JSON command protocol entirely — uploading a
show (Phase G's "upload from client to Pi"). JSON isn't a reasonable transport for an
arbitrarily large binary file, so this is a plain `PUT` with the raw `.dmxr` bytes as
the body, not a command:

```
PUT /api/v1/shows/{name}
Authorization: Bearer <token>

<raw .dmxr file bytes>
```

`{name}` becomes the file's name in the show library — must be a bare filename ending
in `.dmxr` (no path separators; rejected with a 409, §7). The body is capped at 512 MiB
(the whole upload is buffered in memory server-side — a documented tradeoff, not a
silent limitation). On success:

```json
{"ok": true, "result": {"name": "MyShow.dmxr", "size_bytes": 88412031}}
```

The server re-opens the uploaded file to confirm it's actually a valid DMXReplay
container before accepting it (not just any bytes with a `.dmxr` name) — an
interrupted, truncated, or wrong-format upload gets a 409 and is deleted immediately,
never left sitting in the library looking like a real, loadable show.

### WebSocket message shape

```json
{"command": "SEEK", "params": {"seconds": 42.5}}
```

## 6. Responses and WebSocket events

**HTTP**, on success (`200`):

```json
{"ok": true, "command": "SEEK", "result": { ...GET_STATUS-shaped object... }}
```

Every mutating command (`LOAD_SHOW`/`PLAY`/`PAUSE`/`STOP`/`SEEK`/`NEXT`/`PREVIOUS`)
returns the resulting `PlayerStatus` as `result`, so a client never needs a follow-up
`GET_STATUS` call just to see the effect of the command it just sent.
`RECORD_START`/`RECORD_STOP` similarly return `RecorderStatus`.

**`PlayerStatus`** shape (`GET_STATUS`'s `result`, and every transport command above
that returns one):

```json
{
  "loaded": true,
  "show_name": "MyShow.dmxr",
  "universe_count": 2,
  "duration_ns": 342000000000,
  "position_ns": 15230000000,
  "playing": true,
  "loop": false,
  "speed": 1.0,
  "fps": null,
  "has_audio": true,
  "has_external_video": false,
  "output_configured": true
}
```

**`ShowInfo`** shape (`GET_SHOW_INFO`'s `result`):

```json
{
  "name": "MyShow.dmxr",
  "duration_seconds": 342.0,
  "fps": 44.0,
  "vfr": false,
  "encoding": "grayscale",
  "universe_count": 2,
  "has_audio": true,
  "has_external_video": false,
  "created_at": "2026-08-27T00:00:00Z",
  "show_name": null,
  "description": null,
  "file_size_bytes": 88412031
}
```

**`RecorderStatus`** shape (`RECORD_START`/`RECORD_STOP`'s `result`):

```json
{
  "recording": true,
  "duration_seconds": 12.4,
  "universe_count": 3,
  "frame_count": 812,
  "total_packets": 815,
  "malformed_packets": 0,
  "file_size_bytes": 4213004
}
```

**WebSocket**, on a command response:

```json
{"type": "response", "command": "SEEK", "ok": true, "result": { ...PlayerStatus... }}
```

or on failure:

```json
{"type": "response", "command": "RECORD_START", "ok": false, "error": "this server has no Recorder service configured"}
```

**WebSocket status broadcast** — the real-time push the extension brief specifically
asks WebSocket for: every connected, authenticated client receives, roughly once per
second (whenever at least one client is connected — the server does no work otherwise),
unsolicited:

```json
{"type": "status", "data": { ...PlayerStatus... }}
```

This is the mechanism for a mobile app's timeline/play-state UI to stay live without
polling `GET_STATUS` itself — see §2's warning about not building anything that
depends on faster-than-this-broadcast timing.

## 7. Error handling

| Situation | HTTP status | Body / WS `error` |
|---|---|---|
| Missing/wrong auth | `401` | `{"ok": false, "error": "unauthorized"}` |
| Unknown command name | `404` | `{"ok": false, "error": "unknown command '...'"}` |
| Malformed JSON body | `400` | `{"ok": false, "error": "malformed JSON body"}` |
| Missing required param (e.g. `SEEK` with no `seconds`) | `409` | `{"ok": false, "error": "SEEK requires 'seconds'"}` |
| Command needs a service the server wasn't started with | `409` | `{"ok": false, "error": "this server has no Recorder service configured"}` |
| A `Player`/`Recorder` call itself raises (e.g. `LOAD_SHOW` on a file that no longer exists) | `409` | the underlying exception's message |

On WebSocket, malformed JSON or a non-string `command` field gets `{"type": "error",
"error": "..."}` (no `"command"` key, since none was successfully parsed) rather than
closing the connection — one bad message doesn't kill the session.

## 8. Connection lifecycle

- **HTTP** is stateless — no session, no lifecycle beyond each request. A client can
  send commands with no persistent connection at all.
- **WebSocket**: connect → send the `auth` message (§4, skipped if `--no-auth`) →
  receive `auth_ok` → send/receive commands and status broadcasts freely → either side
  closes. If the client disconnects (backgrounded app, Wi-Fi drop, `docs/ARCHITECTURE.md`
  §4's disconnect acceptance test), the server simply stops broadcasting to that socket
  and playback **continues completely unaffected** — this is not a special case in the
  implementation, it falls directly out of §2's architecture: the connection was never
  part of the playback loop to begin with.
- Reconnection is a plain new WebSocket connection with a fresh auth handshake; there is
  no session/resume token to carry over — a reconnecting client should immediately send
  `GET_STATUS` to resynchronize its UI.

## 9. What's covered elsewhere, and what's still missing

- **Discovery** (finding a DMXReplay device's IP on the LAN without typing it in) is
  implemented (Phase E) but is **not part of this JSON API** — it's mDNS/Zeroconf,
  specified in [NETWORKING.md](NETWORKING.md) §3, not an `/api/v1/...` endpoint.
  Discovery is never required: connecting directly by IP:port always works (§1).
- **The local web config UI** (`GET/POST /config`, `/config/restart`, `/config/shutdown`,
  `/config/logs`) is implemented (Phase E) but is also **not part of this JSON API** —
  it serves HTML forms for a human with a browser, documented in `docs/API.md` §10's
  "Discovery, local web config UI, and logs" section, not here. It authenticates
  differently from everything in this document (`?token=` is accepted there
  specifically, unlike §4's rule for the JSON/WebSocket API).
- **File transfer**: uploading a `.dmxr` file to the device's show library is
  implemented (Phase G) — `PUT /api/v1/shows/{name}` (§5). An external-video companion
  file (`load_external_video`, `docs/API.md` §9) has no upload path of its own yet;
  today it has to already be present on the device's filesystem at whatever path
  `LOAD_SHOW`'s external-video pairing expects, same as before this phase.
- **`GET_NETWORK_STATUS`** currently reports only the configured Art-Net/sACN output
  settings (protocol/interface/destination/port/priority), not general host network
  interface status (link state, IP addresses of all interfaces, etc.) — the local web
  config UI's `/config` page shows playback/output settings for editing, but doesn't
  yet surface raw host network interface state either; genuinely not implemented
  anywhere yet, not just missing from this command.
