"""Long-running, commandable Player service (cross-platform extension
Phase C, docs/ARCHITECTURE.md). Wraps dmxreplay.player.Player so a caller
-- today: tests, and any future CLI; Phase D: the network Control API --
can issue commands (load/play/pause/seek/next/previous show/...) to an
already-running process, instead of Player only ever running once to
completion the way dmxreplay-play's CLI does today.

Deliberately NOT a network service itself -- the extension brief's own
instruction ("The API must not contain the real-time DMX playback loop")
is honored one layer earlier than the API layer: this class doesn't talk
to a network at all, it's a plain asyncio-native Python object with no
Tkinter/HTTP/WebSocket dependency (contrast with dmxreplay.ui's
PlayerViewModel, which needs a thread bridge specifically because
Tkinter's mainloop is not asyncio-native -- a future Phase D HTTP/
WebSocket handler runs on the same asyncio event loop as this service and
Player._run_loop() itself, so no bridge is needed here at all). Commands
just call the same Player methods the CLI already calls; the real-time
tick loop stays inside Player._run_loop(), never duplicated or
reimplemented here.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from ..clock import ClockProvider
from ..player import Player
from .show_library import ShowLibrary, ShowNotFoundError

__all__ = ["PlayerService", "PlayerStatus", "ShowNotFoundError"]


@dataclass
class PlayerStatus:
    loaded: bool
    show_name: str | None
    universe_count: int
    duration_ns: int
    position_ns: int
    playing: bool
    loop: bool
    speed: float
    fps: float | None
    has_audio: bool
    has_external_video: bool
    output_configured: bool


class PlayerService:
    def __init__(self, shows_directory: str | None = None, clock_provider: ClockProvider | None = None) -> None:
        self._player = Player(clock_provider)
        self._library = ShowLibrary(shows_directory) if shows_directory else None
        self._show_name: str | None = None
        # Player exposes set_loop()/set_speed()/set_fps() but no getters
        # (docs/API.md §5) -- tracked here, the same pattern
        # dmxreplay.ui.player_viewmodel.PlayerViewModel already uses, so
        # GET_CONFIG (below) has something to report.
        self._loop = False
        self._speed = 1.0
        self._fps: float | None = None
        self._output_protocol: str | None = None
        self._output_kwargs: dict = {}

    # --- Show library ------------------------------------------------------

    def get_shows(self) -> list[str]:
        return self._library.list_shows() if self._library is not None else []

    def load_show(self, name_or_path: str) -> None:
        path = self._library.resolve(name_or_path) if self._library is not None else name_or_path
        self._player.load(path)
        self._show_name = os.path.basename(path)

    def load_external_video(self, name_or_path: str) -> None:
        path = self._library.resolve(name_or_path) if self._library is not None else name_or_path
        self._player.load_external_video(path)

    async def next_show(self) -> None:
        await self._step_show(1)

    async def previous_show(self) -> None:
        await self._step_show(-1)

    async def _step_show(self, direction: int) -> None:
        shows = self.get_shows()
        if not shows:
            raise ShowNotFoundError("no show library configured, or no .dmxr files found in it")
        if self._show_name in shows:
            idx = shows.index(self._show_name) + direction
        else:
            idx = 0 if direction > 0 else len(shows) - 1
        idx = max(0, min(idx, len(shows) - 1))
        # Player.load() deliberately leaves output configuration (set_output())
        # untouched across calls (src/dmxreplay/player/player.py) -- verified
        # by tests/test_service_player.py's own next/previous test, not
        # re-applied here, so switching shows never needs to reopen the
        # sender or re-validate output settings.
        was_playing = self._player.playing
        await self._player.stop()
        self.load_show(shows[idx])
        if was_playing:
            await self.play()

    # --- Output configuration -----------------------------------------------

    def set_output(
        self, protocol: str, interface_ip: str = "0.0.0.0",
        destination_ip: str | None = None, port: int | None = None, priority: int = 100,
    ) -> None:
        self._player.set_output(
            protocol, interface_ip=interface_ip, destination_ip=destination_ip,
            port=port, priority=priority,
        )
        self._output_protocol = protocol
        self._output_kwargs = {
            "interface_ip": interface_ip, "destination_ip": destination_ip,
            "port": port, "priority": priority,
        }

    def set_universe_mapping(self, mapping: dict[int, int] | None) -> None:
        self._player.set_universe_mapping(mapping)

    # --- Transport -----------------------------------------------------------

    async def play(self) -> None:
        await self._player.play(speed=self._speed)

    def pause(self) -> None:
        self._player.pause()

    async def stop(self) -> None:
        await self._player.stop()

    def seek_seconds(self, seconds: float) -> None:
        self._player.seek(max(0, int(seconds * 1_000_000_000)))

    async def frame_step(self, direction: int = 1) -> None:
        await self._player.frame_step(direction)

    def set_loop(self, enabled: bool) -> None:
        self._player.set_loop(enabled)
        self._loop = enabled

    def set_speed(self, speed: float) -> None:
        self._player.set_speed(speed)
        self._speed = speed

    def set_fps(self, fps: float) -> None:
        self._player.set_fps(fps)
        self._fps = fps

    # --- Status / config ------------------------------------------------------

    def get_status(self) -> PlayerStatus:
        manifest = self._player.manifest
        return PlayerStatus(
            loaded=manifest is not None,
            show_name=self._show_name,
            universe_count=manifest.height if manifest is not None else 0,
            duration_ns=self._player.duration_ns,
            position_ns=self._player.position_ns,
            playing=self._player.playing,
            loop=self._loop,
            speed=self._speed,
            fps=self._fps,
            has_audio=self._player.has_audio,
            has_external_video=self._player.has_external_video,
            output_configured=self._output_protocol is not None,
        )

    def get_config(self) -> dict:
        return {"loop": self._loop, "speed": self._speed, "fps": self._fps}

    def set_config(self, *, loop: bool | None = None, speed: float | None = None, fps: float | None = None) -> None:
        if loop is not None:
            self.set_loop(loop)
        if speed is not None:
            self.set_speed(speed)
        if fps is not None:
            self.set_fps(fps)

    def get_network_status(self) -> dict:
        return {"output_protocol": self._output_protocol, **self._output_kwargs}

    async def shutdown(self) -> None:
        await self._player.stop()
