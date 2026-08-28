"""Player GUI view-model: all the state and command logic a Player window
needs, with zero GUI-toolkit imports (CONTRIBUTING.md's GUI-independence
rule applies here too -- `dmxreplay.ui` is allowed to depend on a toolkit,
but this module deliberately doesn't, so it stays testable headlessly and
reusable by a future non-Tkinter GUI). Every DMX/timing decision still
happens inside `dmxreplay.player.Player` (docs/API.md §5) -- this class
only sequences calls to it and holds display-only state (status text,
last error) that has no effect on playback.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Callable

from ..player import Player
from .async_bridge import AsyncLoopThread

#: "Rewind"/"fast-forward" (brief §12/§13) are implemented as a relative
#: seek by this many seconds, the common media-player convention (skip
#: back/forward), rather than a sustained high-speed transport -- simpler,
#: and Player.seek() already exists and is exact; a held-down "scan"
#: control can reuse the same seek() call at a UI-timer cadence later
#: without any Player-level change.
SKIP_SECONDS = 5.0


@dataclass
class PlayerSnapshot:
    """Everything a view needs to redraw itself, read in one call so the
    view never reads Player fields directly (keeps all Player access
    funneled through this view-model, and behind the async bridge)."""

    loaded: bool
    filename: str | None
    universe_count: int
    duration_ns: int
    position_ns: int
    playing: bool
    loop: bool
    speed: float
    has_audio: bool
    has_external_video: bool
    output_configured: bool
    status_text: str
    error_text: str | None


class PlayerViewModel:
    def __init__(self, loop_thread: AsyncLoopThread | None = None) -> None:
        self._loop_thread = loop_thread or AsyncLoopThread()
        self._player = Player()
        self._filename: str | None = None
        self._loop = False
        self._speed = 1.0
        self._status_text = "No file loaded."
        self._error_text: str | None = None
        self._output_configured = False
        self._on_change: Callable[[], None] | None = None

    def set_on_change(self, callback: Callable[[], None] | None) -> None:
        """Called (on whatever thread triggered the change -- the view is
        expected to marshal this itself, e.g. via a periodic `after()`
        poll rather than treating this as a push notification) whenever
        state that affects `snapshot()` might have changed."""
        self._on_change = callback

    def _notify(self) -> None:
        if self._on_change is not None:
            self._on_change()

    # --- Loading ---------------------------------------------------------

    def open_file(self, path: str) -> None:
        try:
            self._player.load(path)
        except Exception as exc:  # noqa: BLE001 -- surfaced to the UI as text, not raised into Tk callbacks
            self._error_text = f"Could not open {path!r}: {exc}"
            self._notify()
            return
        self._filename = path
        self._error_text = None
        self._status_text = f"Loaded {path}"
        self._notify()

    def open_demo_show(self) -> None:
        """Loads the bundled demo show (`dmxreplay.demo.demo_show_path()`),
        generating it once and caching it, so "try DMXReplay" never
        requires the user to already have a `.dmxr` file or a lighting rig
        to make one with (docs/DEMO_MODE.md)."""
        from ..demo import demo_show_path

        self.open_file(demo_show_path())

    def load_external_video(self, path: str) -> None:
        try:
            self._player.load_external_video(path)
        except Exception as exc:  # noqa: BLE001
            self._error_text = f"Could not load video {path!r}: {exc}"
        else:
            self._error_text = None
            self._status_text = f"External video: {path}"
        self._notify()

    # --- Output configuration --------------------------------------------

    def configure_output(
        self,
        protocol: str,
        interface_ip: str,
        destination_ip: str | None,
        port: int | None,
        priority: int = 100,
    ) -> None:
        try:
            self._player.set_output(
                protocol, interface_ip=interface_ip, destination_ip=destination_ip,
                port=port, priority=priority,
            )
        except Exception as exc:  # noqa: BLE001
            self._error_text = f"Output configuration failed: {exc}"
            self._output_configured = False
        else:
            self._error_text = None
            self._output_configured = True
            self._status_text = f"Output: {protocol} via {interface_ip}"
        self._notify()

    # --- Transport ---------------------------------------------------------

    def play(self) -> None:
        if not self._output_configured:
            self._error_text = "Configure an output before playing."
            self._notify()
            return

        def _done(_result, exc) -> None:
            if exc is not None:
                self._error_text = f"Play failed: {exc}"
            else:
                self._error_text = None
            self._notify()

        self._status_text = "Playing"
        self._notify()
        self._loop_thread.submit(self._player.play(speed=self._speed), on_done=_done, marshal=self._marshal)

    def pause(self) -> None:
        self._loop_thread.call_soon(self._player.pause)
        self._status_text = "Paused"
        self._notify()

    def stop(self) -> None:
        def _done(_result, exc) -> None:
            if exc is not None:
                self._error_text = f"Stop failed: {exc}"
            self._notify()

        self._status_text = "Stopped"
        self._notify()
        self._loop_thread.submit(self._player.stop(), on_done=_done, marshal=self._marshal)

    def seek_seconds(self, seconds: float) -> None:
        position_ns = max(0, int(seconds * 1_000_000_000))
        self._loop_thread.call_soon(lambda: self._player.seek(position_ns))
        self._notify()

    def skip(self, direction: int) -> None:
        """Rewind (direction=-1) / fast-forward (direction=1) by
        SKIP_SECONDS -- see the module docstring's note on why this is a
        relative seek, not a sustained scan speed."""
        current_s = self._player.position_ns / 1e9
        self.seek_seconds(current_s + direction * SKIP_SECONDS)

    def set_loop(self, enabled: bool) -> None:
        self._loop = enabled
        self._loop_thread.call_soon(lambda: self._player.set_loop(enabled))
        self._notify()

    def set_speed(self, speed: float) -> None:
        self._speed = speed
        self._loop_thread.call_soon(lambda: self._player.set_speed(speed))
        self._notify()

    # --- Preview (universe monitor) -----------------------------------------

    def set_preview_mode(self, mode) -> None:  # mode: dmxreplay.preview.PreviewMode
        self._player.set_preview_mode(mode)

    def current_preview(self, row: int):
        """The current DMX state at `row`, for a live "universe monitor"
        widget -- purely cosmetic, mirrors `Player.current_preview()`
        exactly (see that method's docstring); never affects playback."""
        return self._player.current_preview(row)

    def _marshal(self, fn: Callable[[], None]) -> None:
        # Overridden by the Tk view to marshal onto the Tk thread via
        # `root.after(0, fn)`; the default just runs inline, which is only
        # correct for non-GUI callers (tests) that don't have a Tk thread
        # to protect in the first place.
        fn()

    # --- Status ------------------------------------------------------------

    def snapshot(self) -> PlayerSnapshot:
        # Reads Player's own properties directly from the GUI thread rather
        # than round-tripping through the asyncio loop thread. These are
        # single scalar reads (int/bool/float), safe under the GIL and
        # consistent with Player.position_ns being designed to be pollable
        # (docs/TIMING.md) -- only *commands* (play/pause/seek/stop) are
        # required to go through the loop thread, to stay ordered with the
        # tick loop; a read of "what is it right now" doesn't need to.
        manifest = self._player.manifest
        return PlayerSnapshot(
            loaded=manifest is not None,
            filename=self._filename,
            universe_count=manifest.height if manifest is not None else 0,
            duration_ns=self._player.duration_ns,
            position_ns=self._player.position_ns,
            playing=self._player.playing,
            loop=self._loop,
            speed=self._speed,
            has_audio=self._player.has_audio,
            has_external_video=self._player.has_external_video,
            output_configured=self._output_configured,
            status_text=self._status_text,
            error_text=self._error_text,
        )

    def shutdown(self) -> None:
        """Call once, on GUI-window close, to stop playback and tear down
        the background asyncio loop cleanly. Blocks (briefly) for the stop
        to actually finish before halting the loop -- submit()'s
        fire-and-forget shape is wrong here: stopping the loop thread
        while player.stop() is still pending would abandon that task
        mid-flight, not run it."""
        future = asyncio.run_coroutine_threadsafe(self._player.stop(), self._loop_thread.loop)
        try:
            future.result(timeout=2.0)
        except Exception:  # noqa: BLE001 -- best-effort on shutdown, never block the window from closing
            pass
        self._loop_thread.stop()
