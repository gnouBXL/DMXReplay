"""Central command dispatch for the Control API (Phase D). Both the
WebSocket command channel and the HTTP `POST /api/v1/command` endpoint
(server.py) go through this one class, so command semantics/validation
never diverges between the two transports.

Deliberately transport-agnostic -- no `aiohttp` import here at all -- and
deliberately NOT where the real-time DMX playback loop lives: every
handler below just calls a `PlayerService`/`RecorderService` method
(dmxreplay.service, Phase C), which itself just calls `Player`/`Recorder`.
The extension brief's instruction "the API must not contain the real-time
DMX playback loop" is honored by construction, not by convention -- there
is no timing/tick code anywhere in this file to accidentally grow one in.
"""
from __future__ import annotations

import dataclasses
from typing import Any, Awaitable, Callable

from ..service import PlayerService, RecorderService

__all__ = ["CommandRouter", "CommandError", "UnknownCommandError", "COMMANDS"]


class CommandError(ValueError):
    """A command was recognized but could not be carried out (missing
    required param, no show loaded, no Player/Recorder service configured
    on this server, ...) -- distinct from an unrecognized command name."""


class UnknownCommandError(ValueError):
    """The command name itself isn't one this router understands."""


def _to_jsonable(value: Any) -> Any:
    return dataclasses.asdict(value) if dataclasses.is_dataclass(value) else value


class CommandRouter:
    def __init__(
        self,
        player_service: PlayerService | None = None,
        recorder_service: RecorderService | None = None,
    ) -> None:
        self.player = player_service
        self.recorder = recorder_service

    async def dispatch(self, command: str, params: dict | None = None) -> Any:
        handler = _HANDLERS.get(command)
        if handler is None:
            raise UnknownCommandError(f"unknown command {command!r}")
        return await handler(self, params or {})

    def require_player(self) -> PlayerService:
        if self.player is None:
            raise CommandError("this server has no Player service configured")
        return self.player

    def require_recorder(self) -> RecorderService:
        if self.recorder is None:
            raise CommandError("this server has no Recorder service configured")
        return self.recorder


CommandHandler = Callable[[CommandRouter, dict], Awaitable[Any]]


async def _get_status(router: CommandRouter, params: dict) -> Any:
    return _to_jsonable(router.require_player().get_status())


async def _get_shows(router: CommandRouter, params: dict) -> Any:
    return router.require_player().get_shows()


async def _load_show(router: CommandRouter, params: dict) -> Any:
    name = params.get("name")
    if not name:
        raise CommandError("LOAD_SHOW requires 'name'")
    player = router.require_player()
    player.load_show(name)
    return _to_jsonable(player.get_status())


async def _play(router: CommandRouter, params: dict) -> Any:
    player = router.require_player()
    await player.play()
    return _to_jsonable(player.get_status())


async def _pause(router: CommandRouter, params: dict) -> Any:
    player = router.require_player()
    player.pause()
    return _to_jsonable(player.get_status())


async def _stop(router: CommandRouter, params: dict) -> Any:
    player = router.require_player()
    await player.stop()
    return _to_jsonable(player.get_status())


async def _seek(router: CommandRouter, params: dict) -> Any:
    if "seconds" not in params:
        raise CommandError("SEEK requires 'seconds'")
    player = router.require_player()
    try:
        seconds = float(params["seconds"])
    except (TypeError, ValueError) as exc:
        raise CommandError("SEEK's 'seconds' must be a number") from exc
    player.seek_seconds(seconds)
    return _to_jsonable(player.get_status())


async def _next(router: CommandRouter, params: dict) -> Any:
    player = router.require_player()
    await player.next_show()
    return _to_jsonable(player.get_status())


async def _previous(router: CommandRouter, params: dict) -> Any:
    player = router.require_player()
    await player.previous_show()
    return _to_jsonable(player.get_status())


async def _record_start(router: CommandRouter, params: dict) -> Any:
    filename = params.get("filename")
    if not filename:
        raise CommandError("RECORD_START requires 'filename'")
    recorder = router.require_recorder()
    recorder.record_start(filename)
    return _to_jsonable(recorder.get_status())


async def _record_stop(router: CommandRouter, params: dict) -> Any:
    recorder = router.require_recorder()
    recorder.record_stop()
    return _to_jsonable(recorder.get_status())


async def _get_config(router: CommandRouter, params: dict) -> Any:
    player = router.require_player()
    config = player.get_config()
    config.update(player.get_network_status())
    return config


async def _set_config(router: CommandRouter, params: dict) -> Any:
    """Covers both playback settings (loop/speed/fps) and output/network
    settings (protocol/interface/destination/port/priority -- the brief's
    "configure Art-Net"/"configure sACN"/"configure network interface"/
    "configure destination IP") in one command, since both are naturally
    "configuration" from a client's point of view. Output is only
    (re)applied when 'protocol' is explicitly given -- never inferred from
    partial params, which would risk silently reapplying a stale value."""
    player = router.require_player()
    if "protocol" in params:
        player.set_output(
            params["protocol"],
            interface_ip=params.get("interface_ip", "0.0.0.0"),
            destination_ip=params.get("destination_ip"),
            port=params.get("port"),
            priority=params.get("priority", 100),
        )
    if any(k in params for k in ("loop", "speed", "fps")):
        player.set_config(loop=params.get("loop"), speed=params.get("speed"), fps=params.get("fps"))
    config = player.get_config()
    config.update(player.get_network_status())
    return config


async def _get_network_status(router: CommandRouter, params: dict) -> Any:
    return router.require_player().get_network_status()


_HANDLERS: dict[str, CommandHandler] = {
    "GET_STATUS": _get_status,
    "GET_SHOWS": _get_shows,
    "LOAD_SHOW": _load_show,
    "PLAY": _play,
    "PAUSE": _pause,
    "STOP": _stop,
    "SEEK": _seek,
    "NEXT": _next,
    "PREVIOUS": _previous,
    "RECORD_START": _record_start,
    "RECORD_STOP": _record_stop,
    "GET_CONFIG": _get_config,
    "SET_CONFIG": _set_config,
    "GET_NETWORK_STATUS": _get_network_status,
}

#: Exposed for docs/tests that want to enumerate the supported command set
#: without reaching into the private handler table.
COMMANDS: tuple[str, ...] = tuple(_HANDLERS.keys())
