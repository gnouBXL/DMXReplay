"""DMXReplay launcher (Tkinter): the first-run "Welcome to DMXReplay"
screen -- pick Player, Recorder, or a pointer to advanced/network options,
rather than needing to already know `dmxreplay-player-gui` vs
`dmxreplay-recorder-gui` exist as separate commands. This is what
`dmxreplay-gui` (the single, no-argument entry point meant for a user who
just double-clicked the app) opens.

Same rule as player_app.py/recorder_app.py: no DMX/network logic lives
here, only window management -- opening a `PlayerWindow`/`RecorderWindow`
in a new `Toplevel` each time a button is pressed.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from .player_app import PlayerWindow
from .recorder_app import RecorderWindow

_ADVANCED_OPTIONS_TEXT = (
    "Player and Recorder windows configure Art-Net/sACN and network settings "
    "for that session directly (their own Output/Input panels).\n\n"
    "For a Raspberry Pi appliance controlled by a smartphone, or a persistent "
    "background service instead of these desktop windows, see the "
    "dmxreplay-server command-line tool and its local web configuration page "
    "(docs/RASPBERRY_PI_INSTALL.md, docs/MOBILE.md) -- advanced/developer "
    "options, not needed for everyday Player/Recorder use."
)


class LauncherWindow:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("DMXReplay")
        # Holds the PlayerWindow/RecorderWindow instances themselves (not
        # just their Toplevels), so anything that needs to clean them up
        # properly (tests; a future "close all" action) can call
        # window.vm.shutdown() -- the same call each window's own
        # WM_DELETE_WINDOW handler already makes, just reachable from here
        # too instead of only via the window manager close button.
        self._open_windows: list[PlayerWindow | RecorderWindow] = []
        self._build_widgets()

    def _build_widgets(self) -> None:
        root = self.root
        frame = ttk.Frame(root, padding=24)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Welcome to DMXReplay", font=("TkDefaultFont", 16, "bold")).pack(pady=(0, 4))
        ttk.Label(
            frame,
            text="DMX lighting data as time-based media -- record, replay, and\nsynchronize Art-Net/sACN shows.",
            justify="center",
        ).pack(pady=(0, 20))

        button_frame = ttk.Frame(frame)
        button_frame.pack()
        ttk.Button(button_frame, text="Player", width=16, command=self._open_player).grid(row=0, column=0, padx=6, pady=4)
        ttk.Button(button_frame, text="Recorder", width=16, command=self._open_recorder).grid(row=0, column=1, padx=6, pady=4)
        ttk.Button(button_frame, text="Configure...", width=16, command=self._show_configure).grid(row=1, column=0, columnspan=2, padx=6, pady=4)

        ttk.Label(
            frame,
            text="New to DMXReplay? Open Player, then File → Open Demo Show — no lighting rig needed.",
            foreground="#555555",
        ).pack(pady=(20, 0))

    def _open_player(self) -> None:
        top = tk.Toplevel(self.root)
        window = PlayerWindow(top)
        self._open_windows.append(window)

    def _open_recorder(self) -> None:
        top = tk.Toplevel(self.root)
        window = RecorderWindow(top)
        self._open_windows.append(window)

    def _show_configure(self) -> None:
        messagebox.showinfo("Advanced / network options", _ADVANCED_OPTIONS_TEXT, parent=self.root)


def main() -> None:
    root = tk.Tk()
    LauncherWindow(root)
    root.mainloop()


if __name__ == "__main__":
    main()
