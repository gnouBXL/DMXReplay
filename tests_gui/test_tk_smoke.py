"""Real Tkinter construction/wiring tests for PlayerWindow/RecorderWindow.
See README.md in this directory for why these live outside tests/ and how
to run them (requires Tkinter + a display or Xvfb)."""
from __future__ import annotations

import tkinter as tk

import pytest

from dmxreplay.codec import ENCODINGS
from dmxreplay.container import DMXReplayWriter
from dmxreplay.dmx import CHANNELS_PER_UNIVERSE, DMXFrame, Universe
from dmxreplay.metadata import Manifest, UniverseMapping
from dmxreplay.ui.player_app import PlayerWindow, _format_hms
from dmxreplay.ui.player_viewmodel import PlayerViewModel
from dmxreplay.ui.recorder_app import RecorderWindow
from dmxreplay.ui.recorder_viewmodel import RecorderViewModel


@pytest.fixture
def tk_root():
    root = tk.Tk()
    yield root
    try:
        root.destroy()
    except tk.TclError:
        pass  # already destroyed by the test (e.g. via window close)


def _make_dmxr(path: str, frame_count: int = 5) -> None:
    mapping = [UniverseMapping.from_artnet_port_address(row=0, port_address=1)]
    manifest = Manifest(
        encoding="grayscale", fps=30.0, vfr=False, timestamp_resolution_ns=1_000_000,
        width=ENCODINGS["grayscale"]["width"], height=1,
        universes=mapping, created_at="2026-08-27T00:00:00Z",
        duration_seconds=frame_count / 30.0,
        recorder={"name": "dmxreplay-tests", "version": "0.1.0-dev"},
    )
    with DMXReplayWriter(path, manifest) as w:
        for t in range(frame_count):
            w.write_frame(DMXFrame(timestamp_ns=int(t * 1e9 / 30), universes=(Universe.blank(),)))


def test_format_hms():
    assert _format_hms(0) == "00:00"
    assert _format_hms(65 * 1_000_000_000) == "01:05"
    assert _format_hms(3665 * 1_000_000_000) == "1:01:05"


def test_player_window_constructs_and_renders_initial_state(tk_root):
    window = PlayerWindow(tk_root)
    tk_root.update()
    try:
        assert window.filename_label.cget("text") == "No file loaded."
        assert window.time_label.cget("text") == "00:00 / 00:00"
        assert window.play_pause_button.cget("text") == "▶"
    finally:
        window.vm.shutdown()


def test_player_window_reflects_a_loaded_file(tmp_path, tk_root):
    path = str(tmp_path / "s.dmxr")
    _make_dmxr(path)
    window = PlayerWindow(tk_root)
    try:
        window.vm.open_file(path)
        window._refresh()
        tk_root.update()
        assert window.filename_label.cget("text") == path
        assert "Universes: 1" in window.universe_label.cget("text")
    finally:
        window.vm.shutdown()


def test_player_window_close_shuts_down_cleanly(tmp_path, tk_root):
    path = str(tmp_path / "s.dmxr")
    _make_dmxr(path)
    window = PlayerWindow(tk_root)
    window.vm.open_file(path)
    tk_root.update()
    window._on_close()  # simulates the window-close button; destroys tk_root itself
    # The real assertion: the destroyed root's Tcl interpreter is gone --
    # proves _on_close() actually tore the window down, not just called
    # shutdown() on the view-model. (winfo_exists() itself raises once the
    # interpreter is destroyed, rather than returning 0 -- that's the
    # actual, verified Tkinter behavior, not documentation guesswork.)
    with pytest.raises(tk.TclError):
        tk_root.winfo_exists()


def test_recorder_window_constructs_and_renders_initial_state(tk_root):
    window = RecorderWindow(tk_root)
    tk_root.update()
    try:
        assert window.status_label.cget("text") == "Idle -- add a source to begin discovery."
        assert window.universes_list.size() == 0
    finally:
        window.vm.shutdown()
