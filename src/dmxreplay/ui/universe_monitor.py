"""A small live "universe monitor" widget: a grid of colored squares
showing one universe's current DMX state, via `dmxreplay.preview`'s
RGB-LED reconstruction (Phase 9) -- purely a visualization, exactly like
`Player.current_preview()`/`Recorder.current_preview()`, which this widget
is the one and only consumer of in the GUI so far.

Shared by both `player_app.py` and `recorder_app.py` rather than each
building its own -- one widget, one place that knows how to lay out 171
LED-preview pixels on a Tk Canvas.
"""
from __future__ import annotations

import tkinter as tk

from ..preview import rgb_hex

COLUMNS = 19  # ceil(sqrt(171)) -- a roughly square grid for 171 pixels
CELL_SIZE = 12
CELL_GAP = 2
IDLE_COLOR = "#202020"  # dark gray, not black -- visibly "off but present"


class UniverseMonitor(tk.Frame):
    """`update_pixels(pixels)` with a `tuple[tuple[int, int, int], ...]`
    from `dmxreplay.preview.rgb_led_pixels()` (or None to show "idle")
    repaints the grid. Named `update_pixels`, not `update`, because
    `tk.Widget` already defines `update()` (process pending Tk events) --
    shadowing it would be a real bug, not just a naming clash. Construction
    only allocates the canvas items once; every subsequent
    `update_pixels()` call just recolors them (`itemconfig`), not rebuilds
    them, so this is cheap enough to call on every GUI poll tick."""

    def __init__(self, parent: tk.Widget, pixel_count: int, *, title: str = "Universe monitor") -> None:
        super().__init__(parent)
        self._label = tk.Label(self, text=title)
        self._label.pack(anchor="w")
        rows = -(-pixel_count // COLUMNS)  # ceil
        width = COLUMNS * (CELL_SIZE + CELL_GAP) + CELL_GAP
        height = rows * (CELL_SIZE + CELL_GAP) + CELL_GAP
        self._canvas = tk.Canvas(self, width=width, height=height, background="#101010", highlightthickness=0)
        self._canvas.pack()
        self._cells: list[int] = []
        for i in range(pixel_count):
            col, row = i % COLUMNS, i // COLUMNS
            x0 = CELL_GAP + col * (CELL_SIZE + CELL_GAP)
            y0 = CELL_GAP + row * (CELL_SIZE + CELL_GAP)
            cell = self._canvas.create_rectangle(
                x0, y0, x0 + CELL_SIZE, y0 + CELL_SIZE, fill=IDLE_COLOR, outline=""
            )
            self._cells.append(cell)

    def update_pixels(self, pixels) -> None:
        """`pixels`: a `tuple[tuple[int, int, int], ...]` matching this
        widget's `pixel_count` (from `rgb_led_pixels()`), or `None` to show
        every cell as idle (no active universe at the current position)."""
        if pixels is None:
            for cell in self._cells:
                self._canvas.itemconfig(cell, fill=IDLE_COLOR)
            return
        for cell, pixel in zip(self._cells, pixels):
            self._canvas.itemconfig(cell, fill=rgb_hex(pixel))
