"""Raw DMX preview. See brief §36 ("Preview: [ Raw DMX ] [ RGB Pixels ]").

The "Raw DMX" mode is the channel grid itself -- no reconstruction needed,
unlike RGB/LED preview (rgb_led.py). This module exists mainly so both
preview modes have the same shape of entry point (see __init__.py's
compute_preview()), for whatever future UI binds to either.
"""
from __future__ import annotations

from ..dmx import Universe


def raw_channel_grid(universe: Universe) -> tuple[int, ...]:
    """The 512 channel values, unmodified -- what "Raw DMX" preview shows."""
    return universe.channels
