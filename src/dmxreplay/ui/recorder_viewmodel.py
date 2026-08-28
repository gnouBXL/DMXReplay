"""Recorder GUI view-model -- the Recorder-side counterpart to
player_viewmodel.py. Same rules: no GUI-toolkit import, all DMX/network
logic stays inside `dmxreplay.recorder.Recorder` (docs/API.md §4); this
class only sequences calls to it.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Callable

from ..dmx import RowInfo
from ..recorder import Recorder
from ..recorder.status import RecorderStatus
from .async_bridge import AsyncLoopThread


@dataclass
class RecorderSnapshot:
    universes: list[RowInfo]
    status: RecorderStatus
    output_path: str | None
    status_text: str
    error_text: str | None
    has_demo_source: bool


class RecorderViewModel:
    def __init__(self, loop_thread: AsyncLoopThread | None = None) -> None:
        self._loop_thread = loop_thread or AsyncLoopThread()
        self._recorder = Recorder()
        self._output_path: str | None = None
        self._status_text = "Idle -- add a source to begin discovery."
        self._error_text: str | None = None
        self._on_change: Callable[[], None] | None = None

    def set_on_change(self, callback: Callable[[], None] | None) -> None:
        self._on_change = callback

    def _notify(self) -> None:
        if self._on_change is not None:
            self._on_change()

    def _marshal(self, fn: Callable[[], None]) -> None:
        fn()  # overridden by the Tk view; see PlayerViewModel._marshal

    # --- Input configuration ------------------------------------------------

    def add_source(self, protocol: str, interface_ip: str, port: int | None = None) -> None:
        def _done(_result, exc) -> None:
            if exc is not None:
                self._error_text = f"Could not start listening: {exc}"
            else:
                self._error_text = None
                self._status_text = f"Listening for {protocol} on {interface_ip} -- discovering universes..."
            self._notify()

        self._loop_thread.submit(
            self._recorder.add_source(protocol, interface_ip=interface_ip, port=port),
            on_done=_done, marshal=self._marshal,
        )

    def refresh_universes(self) -> list[RowInfo]:
        return self._recorder.get_universes()

    def add_demo_source(self, universe_count: int = 4, fps: float = 30.0) -> None:
        """A synthetic, no-hardware-needed input (`Recorder.add_demo_source()`)
        -- lets a user explore/record with the Recorder GUI without a real
        Art-Net/sACN source connected. Dispatched via `call_soon`, not
        called directly: `Recorder.add_demo_source()` starts an `asyncio`
        task internally (`asyncio.ensure_future`), which needs the
        background loop thread as its current running loop -- calling it
        straight from the GUI thread (which has no running loop at all)
        would raise, exactly the class of bug `AsyncLoopThread`'s own
        docstring warns never to do."""
        self._loop_thread.call_soon(lambda: self._recorder.add_demo_source(universe_count, fps))
        self._status_text = f"Demo source active -- {universe_count} simulated universe(s)"
        self._notify()

    def remove_demo_source(self) -> None:
        self._loop_thread.call_soon(self._recorder.remove_demo_source)
        self._status_text = "Demo source stopped."
        self._notify()

    def current_preview(self, row: int, mode: str = "raw"):
        """The current DMX state at `row` (real or demo source), for a live
        "universe monitor" widget -- purely cosmetic, mirrors
        `Recorder.current_preview()`; never affects recording."""
        return self._recorder.current_preview(row, mode)

    # --- Recording control ---------------------------------------------------

    def start(self, output_path: str) -> None:
        try:
            self._recorder.start(output_path)
        except Exception as exc:  # noqa: BLE001
            self._error_text = f"Could not start recording: {exc}"
        else:
            self._error_text = None
            self._output_path = output_path
            self._status_text = f"Recording -> {output_path}"
        self._notify()

    def stop(self) -> None:
        self._recorder.stop()
        self._status_text = "Stopped."
        self._notify()

    # --- Status ----------------------------------------------------------

    def snapshot(self) -> RecorderSnapshot:
        return RecorderSnapshot(
            universes=self._recorder.get_universes(),
            status=self._recorder.get_status(),
            output_path=self._output_path,
            status_text=self._status_text,
            error_text=self._error_text,
            has_demo_source=self._recorder.has_demo_source,
        )

    def shutdown(self) -> None:
        """Blocks (briefly) for close() to actually finish before halting
        the loop thread -- see PlayerViewModel.shutdown()'s note on why
        fire-and-forget is wrong for shutdown specifically."""
        if self._recorder.get_status().recording:
            self._recorder.stop()
        future = asyncio.run_coroutine_threadsafe(self._recorder.close(), self._loop_thread.loop)
        try:
            future.result(timeout=2.0)
        except Exception:  # noqa: BLE001 -- best-effort on shutdown
            pass
        self._loop_thread.stop()
