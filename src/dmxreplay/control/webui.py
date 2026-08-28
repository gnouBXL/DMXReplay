"""Local web configuration UI (cross-platform extension Phase E, extension
brief §7/§18). For first-time/no-app setup on a device that may have no
screen at all -- the native mobile app (Phase F) remains the preferred
interface once it exists (the brief's own stated priority); this is the
fallback that works from any browser on the same network, e.g.
`http://dmxreplay.local/config`.

Plain server-rendered HTML forms, no client-side framework or build step
-- appropriate for a page nobody is expected to use often. Rendering is
kept as pure functions (no `aiohttp` import in this file) so it's testable
without a live server; `server.py` wires these into actual routes.

Living in `dmxreplay.control`, not `dmxreplay.ui`: serving HTML strings
over HTTP is not "depending on a GUI toolkit" in CONTRIBUTING.md's
GUI-independence sense (no Tkinter/Qt/Electron import anywhere here) --
it's just another response format alongside the JSON API, the same way a
web framework serving HTML isn't a desktop GUI.
"""
from __future__ import annotations

import html
from typing import Any

_STYLE = """
body { font-family: system-ui, sans-serif; max-width: 640px; margin: 2rem auto; padding: 0 1rem; }
h1 { font-size: 1.4rem; } h2 { font-size: 1.1rem; margin-top: 2rem; }
fieldset { border: 1px solid #ccc; border-radius: 6px; margin-bottom: 1rem; }
label { display: block; margin: 0.5rem 0 0.2rem; }
input, select { width: 100%; box-sizing: border-box; padding: 0.4rem; }
button { padding: 0.5rem 1rem; margin-top: 0.5rem; }
.danger { background: #c0392b; color: white; border: none; border-radius: 4px; }
.status { color: #666; font-size: 0.9rem; }
pre { background: #f5f5f5; padding: 1rem; overflow-x: auto; white-space: pre-wrap; }
"""


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _with_token(path: str, token: str | None) -> str:
    """Threads `?token=...` (when the caller is authenticating via query
    param, server.py's one deliberate exception for /config* -- see its
    docstring) into a form action or link, so navigating the page doesn't
    silently drop back to an unauthenticated request. A no-op when
    `token` is None (header-authenticated caller, or auth disabled).
    Returns the raw (unescaped) URL -- callers must still pass this
    through `_esc()` themselves, exactly once, same as any other
    interpolated value; escaping here too would double-escape it."""
    return f"{path}?token={token}" if token else path


def render_config_page(
    *, device_name: str, dmxreplay_version: str,
    status: dict, config: dict, network: dict, token: str | None = None,
) -> str:
    checked_loop = "checked" if config.get("loop") else ""
    protocol_options = "".join(
        f'<option value="{p}" {"selected" if network.get("output_protocol") == p else ""}>{p}</option>'
        for p in ("Art-Net", "sACN")
    )
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>DMXReplay -- {_esc(device_name)}</title>
<style>{_STYLE}</style></head><body>
<h1>DMXReplay -- {_esc(device_name)}</h1>
<p class="status">Version {_esc(dmxreplay_version)} &middot;
{"Loaded: " + _esc(status.get("show_name")) if status.get("loaded") else "No show loaded"} &middot;
{"Playing" if status.get("playing") else "Stopped"}</p>

<form method="post" action="{_esc(_with_token('/config', token))}">
<fieldset>
<legend>Playback</legend>
<label><input type="checkbox" name="loop" {checked_loop}> Loop</label>
<label>Speed<input type="number" step="0.1" name="speed" value="{_esc(config.get("speed", 1.0))}"></label>
<label>FPS (blank = use the file's own)<input type="number" step="0.1" name="fps" value="{_esc(config.get("fps") or "")}"></label>
</fieldset>

<fieldset>
<legend>Network / Output</legend>
<label>Protocol<select name="protocol">{protocol_options}</select></label>
<label>Interface<input type="text" name="interface_ip" value="{_esc(network.get("interface_ip", "0.0.0.0"))}"></label>
<label>Destination IP (blank = broadcast/multicast)<input type="text" name="destination_ip" value="{_esc(network.get("destination_ip") or "")}"></label>
<label>Port (blank = protocol default)<input type="number" name="port" value="{_esc(network.get("port") or "")}"></label>
<label>sACN priority<input type="number" name="priority" value="{_esc(network.get("priority", 100))}"></label>
</fieldset>

<button type="submit">Apply</button>
</form>

<h2>System</h2>
<form method="post" action="{_esc(_with_token('/config/restart', token))}" onsubmit="return confirm('Restart the DMXReplay service now?');">
<button type="submit">Restart service</button>
</form>
<form method="post" action="{_esc(_with_token('/config/shutdown', token))}" onsubmit="return confirm('Stop the DMXReplay service? It will not restart automatically.');">
<button type="submit" class="danger">Safe shutdown</button>
</form>
<p><a href="{_esc(_with_token('/config/logs', token))}">View recent logs</a></p>
</body></html>"""


def render_message_page(*, title: str, message: str, back_href: str = "/config", token: str | None = None) -> str:
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>DMXReplay -- {_esc(title)}</title>
<style>{_STYLE}</style></head><body>
<h1>{_esc(title)}</h1>
<p>{_esc(message)}</p>
<p><a href="{_esc(_with_token(back_href, token))}">Back</a></p>
</body></html>"""


def render_logs_page(*, device_name: str, lines: list[str], token: str | None = None) -> str:
    body = "\n".join(lines) if lines else "(no log entries yet)"
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>DMXReplay -- {_esc(device_name)} logs</title>
<style>{_STYLE}</style></head><body>
<h1>Recent logs -- {_esc(device_name)}</h1>
<pre>{_esc(body)}</pre>
<p><a href="{_esc(_with_token('/config', token))}">Back</a></p>
</body></html>"""
