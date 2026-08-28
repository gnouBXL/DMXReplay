# GUI smoke tests

Real Tkinter widget-construction tests for `dmxreplay.ui` (`player_app.py`/
`recorder_app.py`). Kept **out** of `tests/` deliberately: the main project venv
(`.venv`, `pyproject.toml`'s `testpaths = ["tests"]`) has no Tkinter dependency by
design (`dmxreplay.ui.player_viewmodel`/`recorder_viewmodel`/`async_bridge` are fully
covered there, with zero Tkinter import — see their own docstrings), and Tkinter isn't
a pip package, so it can't just be added as a normal test dependency.

These tests build the real `tk.Tk()` root, construct `PlayerWindow`/`RecorderWindow`,
call `root.update()` to process pending Tk events (never `mainloop()`, which blocks),
assert on real widget state, then destroy the root — genuine construction/wiring
verification, not a mock.

## Running

Requires Tkinter (`python3-tk` on Debian/Ubuntu/Raspberry Pi OS; bundled with the
python.org installers on Windows/macOS) and a display or a virtual one (`Xvfb`):

```bash
# one-time setup: a second venv with system Tkinter bindings visible
python3.12 -m venv --system-site-packages .venv-gui
.venv-gui/bin/pip install -e ".[dev]"

# run (xvfb-run provides a throwaway virtual display; omit it if you have a real one)
xvfb-run -a .venv-gui/bin/pytest tests_gui/
```

Not run as part of `pytest` (no args) or CI's default test command — that only ever
exercises `tests/`, matching the "no GUI toolkit needed for the core/CLI" guarantee
CONTRIBUTING.md makes. Run this directory explicitly when touching `dmxreplay.ui`.
