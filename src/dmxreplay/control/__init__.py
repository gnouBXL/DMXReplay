"""HTTP + WebSocket network Control API (cross-platform extension Phase D,
docs/API.md §10, docs/MOBILE_API.md). Requires the optional `aiohttp`
dependency (`pip install dmxreplay[control]`) -- not needed for the core
engine, the desktop GUIs, or the Phase C services this package sits on
top of, all of which import fine without it.
"""
from .auth import ApiToken
from .router import COMMANDS, CommandError, CommandRouter, UnknownCommandError
from .server import API_VERSION, ControlServer

__all__ = [
    "ApiToken",
    "CommandRouter",
    "CommandError",
    "UnknownCommandError",
    "COMMANDS",
    "ControlServer",
    "API_VERSION",
]
