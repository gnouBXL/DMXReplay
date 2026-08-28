"""Recorder/Player desktop GUIs (Phase A of the cross-platform extension,
docs/ARCHITECTURE.md). The only package under src/dmxreplay allowed to
depend on a GUI toolkit -- see CONTRIBUTING.md.

Built with Tkinter (Python's own standard-library GUI toolkit): ships with
the official python.org installers on Windows/macOS and is a one-line
`apt install python3-tk` on Debian/Raspberry Pi OS, so it adds zero new
pip dependencies and needs no separate cross-platform GUI framework
decision for the desktop apps.

Deliberately NOT re-exported here: importing this package (`import
dmxreplay.ui`) must not require Tkinter to be installed, since
`player_viewmodel`/`recorder_viewmodel`/`async_bridge` (below) have their
own real test coverage that runs in the normal project venv, which has no
Tkinter dependency at all -- eagerly importing the Tk-based app modules in
this `__init__.py` would break that. Import what you need directly:
`from dmxreplay.ui.player_app import PlayerWindow`, etc.

Structure, per module:
- `async_bridge.py`  -- bridges the asyncio-based core to a synchronous
  GUI mainloop; no Tkinter import, reusable by any future toolkit.
- `player_viewmodel.py` / `recorder_viewmodel.py` -- all state/command
  logic, no Tkinter import either; independently unit-tested
  (tests/test_ui_player_viewmodel.py, tests/test_ui_recorder_viewmodel.py)
  without a display.
- `player_app.py` / `recorder_app.py` -- the only files that import
  `tkinter`; pure presentation, wired to the view-models above.
"""
