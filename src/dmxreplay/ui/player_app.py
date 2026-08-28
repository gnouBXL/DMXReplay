"""DMXReplay Player desktop GUI (Tkinter). Functional, not styled -- the
user explicitly asked for a clean and understandable GUI first, visual
polish later. This module is the *only* place that imports `tkinter`;
every DMX/network/timing decision is delegated to `PlayerViewModel`
(player_viewmodel.py), which has no knowledge Tkinter exists.

Functional areas covered (per the desktop Player spec): open .dmxr, play,
pause, stop, seek, rewind, fast-forward, loop, timeline with current/total
time, DMX output status, Art-Net/sACN selection, network interface,
destination IP, universe information, audio status, video status,
synchronization status.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, ttk

from .player_viewmodel import PlayerSnapshot, PlayerViewModel

POLL_INTERVAL_MS = 150


def _format_hms(ns: int) -> str:
    total_s = max(0, ns) // 1_000_000_000
    h, rem = divmod(total_s, 3600)
    m, s = divmod(rem, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


class PlayerWindow:
    def __init__(self, root: tk.Tk | tk.Toplevel, viewmodel: PlayerViewModel | None = None) -> None:
        self.root = root
        self.vm = viewmodel or PlayerViewModel()
        self._scrubbing = False
        root.title("DMXReplay Player")
        self._build_widgets()
        self.vm.set_on_change(self._refresh)  # marshaled onto the Tk thread by the vm's own _marshal override
        self.vm._marshal = lambda fn: self.root.after(0, fn)  # noqa: SLF001 -- intentional, see player_viewmodel.py's note
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._poll()

    # --- Widget construction ---------------------------------------------

    def _build_widgets(self) -> None:
        root = self.root
        menubar = tk.Menu(root)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Open .dmxr...", command=self._on_open)
        file_menu.add_command(label="Load external video...", command=self._on_open_video)
        file_menu.add_separator()
        file_menu.add_command(label="Quit", command=self._on_close)
        menubar.add_cascade(label="File", menu=file_menu)
        root.config(menu=menubar)

        self.filename_label = ttk.Label(root, text="No file loaded.")
        self.filename_label.pack(fill="x", padx=8, pady=(8, 0))

        # --- Timeline ---
        timeline_frame = ttk.Frame(root)
        timeline_frame.pack(fill="x", padx=8, pady=4)
        self.time_label = ttk.Label(timeline_frame, text="00:00 / 00:00", width=14)
        self.time_label.pack(side="left")
        self.timeline = ttk.Scale(timeline_frame, from_=0, to=1000, orient="horizontal")
        self.timeline.pack(side="left", fill="x", expand=True, padx=8)
        self.timeline.bind("<ButtonPress-1>", lambda _e: setattr(self, "_scrubbing", True))
        self.timeline.bind("<ButtonRelease-1>", self._on_scrub_release)

        # --- Transport ---
        transport_frame = ttk.Frame(root)
        transport_frame.pack(pady=4)
        ttk.Button(transport_frame, text="◄◄", width=4, command=lambda: self.vm.skip(-1)).pack(side="left", padx=2)
        self.play_pause_button = ttk.Button(transport_frame, text="▶", width=4, command=self._on_play_pause)
        self.play_pause_button.pack(side="left", padx=2)
        ttk.Button(transport_frame, text="■", width=4, command=self.vm.stop).pack(side="left", padx=2)
        ttk.Button(transport_frame, text="▶▶", width=4, command=lambda: self.vm.skip(1)).pack(side="left", padx=2)
        self.loop_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(transport_frame, text="Loop", variable=self.loop_var, command=self._on_loop_toggle).pack(side="left", padx=8)

        # --- Output configuration ---
        output_frame = ttk.LabelFrame(root, text="Output")
        output_frame.pack(fill="x", padx=8, pady=4)
        self.protocol_var = tk.StringVar(value="Art-Net")
        ttk.Radiobutton(output_frame, text="Art-Net", variable=self.protocol_var, value="Art-Net").grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(output_frame, text="sACN", variable=self.protocol_var, value="sACN").grid(row=0, column=1, sticky="w")
        ttk.Label(output_frame, text="Interface:").grid(row=1, column=0, sticky="e")
        self.interface_entry = ttk.Entry(output_frame, width=16)
        self.interface_entry.insert(0, "0.0.0.0")
        self.interface_entry.grid(row=1, column=1, sticky="w")
        ttk.Label(output_frame, text="Destination:").grid(row=1, column=2, sticky="e")
        self.destination_entry = ttk.Entry(output_frame, width=16)
        self.destination_entry.grid(row=1, column=3, sticky="w")
        ttk.Button(output_frame, text="Apply", command=self._on_apply_output).grid(row=1, column=4, padx=8)

        # --- Status ---
        status_frame = ttk.LabelFrame(root, text="Status")
        status_frame.pack(fill="x", padx=8, pady=4)
        self.universe_label = ttk.Label(status_frame, text="Universes: -")
        self.universe_label.pack(anchor="w")
        self.output_status_label = ttk.Label(status_frame, text="DMX output: not configured")
        self.output_status_label.pack(anchor="w")
        self.audio_status_label = ttk.Label(status_frame, text="Audio: none")
        self.audio_status_label.pack(anchor="w")
        self.video_status_label = ttk.Label(status_frame, text="Video: none")
        self.video_status_label.pack(anchor="w")
        self.sync_status_label = ttk.Label(status_frame, text="Synchronization: n/a")
        self.sync_status_label.pack(anchor="w")
        self.error_label = ttk.Label(status_frame, text="", foreground="red")
        self.error_label.pack(anchor="w")

    # --- Actions -----------------------------------------------------------

    def _on_open(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("DMXReplay show", "*.dmxr"), ("All files", "*.*")])
        if path:
            self.vm.open_file(path)

    def _on_open_video(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("Video", "*.mp4 *.mov *.mkv"), ("All files", "*.*")])
        if path:
            self.vm.load_external_video(path)

    def _on_apply_output(self) -> None:
        self.vm.configure_output(
            self.protocol_var.get(),
            self.interface_entry.get() or "0.0.0.0",
            self.destination_entry.get() or None,
            None,
        )

    def _on_play_pause(self) -> None:
        if self.vm.snapshot().playing:
            self.vm.pause()
        else:
            self.vm.play()

    def _on_loop_toggle(self) -> None:
        self.vm.set_loop(self.loop_var.get())

    def _on_scrub_release(self, _event) -> None:
        self._scrubbing = False
        duration_s = self.vm.snapshot().duration_ns / 1e9
        fraction = self.timeline.get() / 1000.0
        self.vm.seek_seconds(fraction * duration_s)

    def _on_close(self) -> None:
        self.vm.shutdown()
        self.root.destroy()

    # --- Refresh -----------------------------------------------------------

    def _poll(self) -> None:
        self._refresh()
        self.root.after(POLL_INTERVAL_MS, self._poll)

    def _refresh(self) -> None:
        snap = self.vm.snapshot()
        self._render(snap)

    def _render(self, snap: PlayerSnapshot) -> None:
        self.filename_label.config(text=snap.filename or "No file loaded.")
        self.time_label.config(text=f"{_format_hms(snap.position_ns)} / {_format_hms(snap.duration_ns)}")
        if not self._scrubbing and snap.duration_ns > 0:
            self.timeline.set(1000.0 * snap.position_ns / snap.duration_ns)
        self.play_pause_button.config(text="⏸" if snap.playing else "▶")
        self.universe_label.config(text=f"Universes: {snap.universe_count}" if snap.loaded else "Universes: -")
        self.output_status_label.config(
            text="DMX output: configured" if snap.output_configured else "DMX output: not configured"
        )
        self.audio_status_label.config(text=f"Audio: {'present' if snap.has_audio else 'none'}")
        self.video_status_label.config(text=f"Video: {'present' if snap.has_external_video else 'none'}")
        self.sync_status_label.config(
            text=f"Synchronization: {'playing' if snap.playing else 'stopped'} (master timeline on this device)"
        )
        self.error_label.config(text=snap.error_text or "")


def main() -> None:
    root = tk.Tk()
    PlayerWindow(root)
    root.mainloop()


if __name__ == "__main__":
    main()
