"""Long-running, commandable Recorder service (Phase C) -- the Recorder-
side counterpart to player_service.py. Same relationship to
dmxreplay.recorder.Recorder that PlayerService has to Player: a thin,
asyncio-native wrapper adding a show-library-aware output path, with all
DMX/network logic staying inside Recorder itself.
"""
from __future__ import annotations

import os

from ..dmx import RowInfo
from ..recorder import Recorder
from ..recorder.status import RecorderStatus
from .show_library import ShowLibrary

__all__ = ["RecorderService"]


class RecorderService:
    def __init__(self, shows_directory: str | None = None) -> None:
        self._recorder = Recorder()
        self._library = ShowLibrary(shows_directory) if shows_directory else None
        self._output_filename: str | None = None

    async def add_source(self, protocol: str, interface_ip: str, port: int | None = None) -> None:
        await self._recorder.add_source(protocol, interface_ip=interface_ip, port=port)

    def get_universes(self) -> list[RowInfo]:
        return self._recorder.get_universes()

    def record_start(self, filename: str) -> None:
        """`filename` is a bare name written into the show library
        directory (if configured) or a full path otherwise -- resolved
        via ShowLibrary.resolve(must_exist=False), since the file doesn't
        exist yet at record_start() time (Recorder.start() creates it)."""
        if self._library is not None:
            path = self._library.resolve(filename, must_exist=False)
        else:
            path = filename
        self._recorder.start(path)
        self._output_filename = os.path.basename(path)

    def record_stop(self) -> None:
        self._recorder.stop()

    def get_status(self) -> RecorderStatus:
        return self._recorder.get_status()

    @property
    def output_filename(self) -> str | None:
        return self._output_filename

    async def shutdown(self) -> None:
        if self._recorder.get_status().recording:
            self._recorder.stop()
        await self._recorder.close()
