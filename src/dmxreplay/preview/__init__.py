"""Raw DMX / RGB-LED visualization preview (Phase 9). See
docs/SPECIFICATION.md §5.3, brief §8/§36-§37. Purely cosmetic -- every
function here is a pure, read-only transform of already-decoded DMX values
and MUST NEVER alter stored or output DMX values."""
from typing import Literal, Union

from ..dmx import Universe
from .raw import raw_channel_grid
from .rgb_led import LED_PIXELS_PER_UNIVERSE, rgb_hex, rgb_led_pixels

PreviewMode = Literal["raw", "rgb_led"]

__all__ = [
    "PreviewMode",
    "raw_channel_grid",
    "rgb_led_pixels",
    "rgb_hex",
    "LED_PIXELS_PER_UNIVERSE",
    "compute_preview",
]


def compute_preview(
    universe: Universe, mode: PreviewMode
) -> Union[tuple[int, ...], tuple[tuple[int, int, int], ...]]:
    """Dispatch to the requested preview mode (brief §36). Never mutates
    `universe`, never affects DMX output -- visualization only."""
    if mode == "raw":
        return raw_channel_grid(universe)
    if mode == "rgb_led":
        return rgb_led_pixels(universe)
    raise ValueError(f"Unknown preview mode {mode!r}")
