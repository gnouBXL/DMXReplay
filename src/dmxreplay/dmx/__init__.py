"""DMX data model (Phase 1). See docs/SPECIFICATION.md §5-§7."""
from .frame import DMXFrame
from .universe import CHANNELS_PER_UNIVERSE, MAX_CHANNEL_VALUE, MIN_CHANNEL_VALUE, Universe

__all__ = [
    "Universe",
    "DMXFrame",
    "CHANNELS_PER_UNIVERSE",
    "MIN_CHANNEL_VALUE",
    "MAX_CHANNEL_VALUE",
]
