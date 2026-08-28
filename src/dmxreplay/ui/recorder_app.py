"""DMXReplay Recorder desktop GUI (Tkinter). Same rules as player_app.py:
this is the only place that imports `tkinter`; all DMX/network logic lives
in `RecorderViewModel` (recorder_viewmodel.py).

Functional areas covered (per the desktop Recorder spec): select Art-Net/
sACN input, select network interface, detect received universes, show
active universes, record, stop, recording duration, output filename,
recording status, network status.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, ttk

from ..preview import LED_PIXELS_PER_UNIVERSE
from .recorder_viewmodel import RecorderSnapshot, RecorderViewModel
from .universe_monitor import UniverseMonitor

POLL_INTERVAL_MS = 250


class RecorderWindow:
    def __init__(self, root: tk.Tk | tk.Toplevel, viewmodel: RecorderViewModel | None = None) -> None:
        self.root = root
        self.vm = viewmodel or RecorderViewModel()
        root.title("DMXReplay Recorder")
        self._build_widgets()
        self.vm.set_on_change(self._refresh)
        self.vm._marshal = lambda fn: self.root.after(0, fn)  # noqa: SLF001 -- see player_app.py's identical note
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._poll()

    def _build_widgets(self) -> None:
        root = self.root

        input_frame = ttk.LabelFrame(root, text="Input")
        input_frame.pack(fill="x", padx=8, pady=4)
        self.protocol_var = tk.StringVar(value="Art-Net")
        ttk.Radiobutton(input_frame, text="Art-Net", variable=self.protocol_var, value="Art-Net").grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(input_frame, text="sACN", variable=self.protocol_var, value="sACN").grid(row=0, column=1, sticky="w")
        ttk.Radiobutton(
            input_frame, text="Demo (no hardware needed)", variable=self.protocol_var, value="Demo",
        ).grid(row=0, column=2, sticky="w")
        ttk.Label(input_frame, text="Interface:").grid(row=1, column=0, sticky="e")
        self.interface_entry = ttk.Entry(input_frame, width=16)
        self.interface_entry.insert(0, "0.0.0.0")
        self.interface_entry.grid(row=1, column=1, sticky="w")
        ttk.Button(input_frame, text="Listen", command=self._on_add_source).grid(row=1, column=2, padx=8)

        universes_frame = ttk.LabelFrame(root, text="Detected universes")
        universes_frame.pack(fill="both", expand=True, padx=8, pady=4)
        self.universes_list = tk.Listbox(universes_frame, height=6)
        self.universes_list.pack(fill="both", expand=True)

        record_frame = ttk.LabelFrame(root, text="Recording")
        record_frame.pack(fill="x", padx=8, pady=4)
        ttk.Label(record_frame, text="Output file:").grid(row=0, column=0, sticky="e")
        self.output_entry = ttk.Entry(record_frame, width=32)
        self.output_entry.grid(row=0, column=1, sticky="w")
        ttk.Button(record_frame, text="Browse...", command=self._on_browse_output).grid(row=0, column=2, padx=4)
        self.record_button = ttk.Button(record_frame, text="● REC", command=self._on_record)
        self.record_button.grid(row=1, column=0, pady=4)
        ttk.Button(record_frame, text="■ Stop", command=self._on_stop).grid(row=1, column=1, pady=4)

        status_frame = ttk.LabelFrame(root, text="Status")
        status_frame.pack(fill="x", padx=8, pady=4)
        self.status_label = ttk.Label(status_frame, text="Idle.")
        self.status_label.pack(anchor="w")
        self.duration_label = ttk.Label(status_frame, text="Duration: 0.0s")
        self.duration_label.pack(anchor="w")
        self.packets_label = ttk.Label(status_frame, text="Packets: 0 (0 malformed)")
        self.packets_label.pack(anchor="w")
        self.network_status_label = ttk.Label(status_frame, text="Network: not listening")
        self.network_status_label.pack(anchor="w")
        self.error_label = ttk.Label(status_frame, text="", foreground="red")
        self.error_label.pack(anchor="w")

        # --- Universe monitor (Phase 9 preview, wired into the GUI here) ---
        self.universe_monitor = UniverseMonitor(
            root, LED_PIXELS_PER_UNIVERSE, title="Universe monitor (row 0, RGB preview)"
        )
        self.universe_monitor.pack(padx=8, pady=(4, 8))

    # --- Actions -----------------------------------------------------------

    def _on_add_source(self) -> None:
        protocol = self.protocol_var.get()
        if protocol == "Demo":
            self.vm.add_demo_source()
        else:
            self.vm.add_source(protocol, self.interface_entry.get() or "0.0.0.0")

    def _on_browse_output(self) -> None:
        path = filedialog.asksaveasfilename(defaultextension=".dmxr", filetypes=[("DMXReplay show", "*.dmxr")])
        if path:
            self.output_entry.delete(0, tk.END)
            self.output_entry.insert(0, path)

    def _on_record(self) -> None:
        path = self.output_entry.get()
        if path:
            self.vm.start(path)

    def _on_stop(self) -> None:
        self.vm.stop()

    def _on_close(self) -> None:
        self.vm.shutdown()
        self.root.destroy()

    # --- Refresh -----------------------------------------------------------

    def _poll(self) -> None:
        self._refresh()
        self.root.after(POLL_INTERVAL_MS, self._poll)

    def _refresh(self) -> None:
        self._render(self.vm.snapshot())

    def _render(self, snap: RecorderSnapshot) -> None:
        self.universes_list.delete(0, tk.END)
        for row in snap.universes:
            label = f"Row {row.row}: {row.protocol} universe {row.universe}"
            if row.source_ip:
                label += f" from {row.source_ip}"
            label += f" ({row.packet_count} packets)"
            self.universes_list.insert(tk.END, label)

        self.status_label.config(text=snap.status_text)
        self.duration_label.config(text=f"Duration: {snap.status.duration_seconds:.1f}s")
        self.packets_label.config(text=f"Packets: {snap.status.total_packets} ({snap.status.malformed_packets} malformed)")
        if snap.has_demo_source:
            network_text = f"Demo source active, {snap.status.universe_count} simulated universe(s) -- no network involved"
        elif snap.universes:
            network_text = f"Network: listening, {snap.status.universe_count} universe(s) seen"
        else:
            network_text = "Network: not listening"
        self.network_status_label.config(text=network_text)
        self.record_button.config(state="disabled" if snap.status.recording else "normal")
        self.error_label.config(text=snap.error_text or "")
        pixels = self.vm.current_preview(0, "rgb_led") if snap.universes else None
        self.universe_monitor.update_pixels(pixels)


def main() -> None:
    root = tk.Tk()
    RecorderWindow(root)
    root.mainloop()


if __name__ == "__main__":
    main()
