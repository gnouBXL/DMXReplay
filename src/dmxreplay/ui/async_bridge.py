"""Bridges dmxreplay's asyncio-based core (Player/Recorder) to a synchronous
GUI mainloop (Tkinter's, in this phase; the class itself has no Tkinter
import, so it is reusable by any future GUI toolkit).

Player/Recorder are asyncio-native (docs/API.md §4/§5) because the core
engine's real-time loop has to be -- see docs/TIMING.md. A desktop GUI
mainloop is not asyncio-native, and must never be blocked waiting for a
network/DMX operation (that would freeze the window). The standard bridge
for this is one persistent asyncio event loop running on a background
thread for the life of the GUI process; the GUI thread submits coroutines
to it and gets results back via a thread-safe callback, never by blocking.
"""
from __future__ import annotations

import asyncio
import threading
from typing import Any, Awaitable, Callable, Optional, TypeVar

T = TypeVar("T")

DoneCallback = Callable[[Optional[T], Optional[BaseException]], None]


class AsyncLoopThread:
    """One asyncio event loop, running forever on a background thread.

    submit() is the only way callers should interact with it: fire a
    coroutine, optionally get notified of its (result, exception) back on
    the calling ("GUI") thread via `marshal` -- e.g. `tk_root.after`. Never
    call asyncio APIs (including Player/Recorder's async methods) directly
    from the GUI thread; always go through submit().
    """

    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="dmxreplay-ui-asyncio")
        self._thread.start()
        self._ready.wait()

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        self._loop.run_forever()

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        return self._loop

    def submit(
        self,
        coro: Awaitable[T],
        on_done: DoneCallback | None = None,
        marshal: Callable[[Callable[[], None]], Any] | None = None,
    ) -> None:
        """Run `coro` on the background loop; fire-and-forget unless
        `on_done` is given. `marshal` (typically `tk_root.after`, called
        with a zero-arg callable) is how the result gets back onto the
        caller's own thread -- if omitted, `on_done` runs directly on the
        asyncio thread, which is only safe for non-GUI callers (tests)."""
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        if on_done is None:
            return

        def _future_done(f: "asyncio.Future[T]") -> None:
            try:
                result: T | None = f.result()
                exc: BaseException | None = None
            except BaseException as e:  # noqa: BLE001 -- handed to on_done, never swallowed
                result = None
                exc = e
            if marshal is not None:
                marshal(lambda: on_done(result, exc))
            else:
                on_done(result, exc)

        future.add_done_callback(_future_done)

    def call_soon(self, fn: Callable[[], None]) -> None:
        """Schedule a plain (non-coroutine) callable on the background
        loop's thread -- e.g. for sync Player/Recorder calls that must not
        race with an in-flight coroutine (both run on the same loop
        thread, so this serializes them correctly)."""
        self._loop.call_soon_threadsafe(fn)

    def stop(self) -> None:
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=2.0)
