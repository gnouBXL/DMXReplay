"""RGB/LED preview reconstruction. See docs/SPECIFICATION.md §5.3, brief
§8/§36-§37.

Purely a visualization transform: every function here is a pure function of
already-decoded DMX values, has no side effects, and cannot influence what
gets stored in a `.dmxr` file or sent to Art-Net/sACN output. This is
intentionally independent of `dmxreplay.codec.pixels`' `rgb_packed`
encoding (which is a *physical storage* choice, `docs/CONTAINER.md` §2) --
preview mode is a player-side visualization option available regardless of
which encoding a given file was actually stored with (brief §8: "Preview:
[Raw DMX] / [RGB Pixels]" is offered independent of the loaded file).

Raw values only: no gamma correction, no DMX dimming curve, no color
management (brief §37) -- channel value 255 means RGB component 255,
always, exactly as decoded.
"""
from __future__ import annotations

from ..dmx import CHANNELS_PER_UNIVERSE, Universe

LED_PIXELS_PER_UNIVERSE = -(-CHANNELS_PER_UNIVERSE // 3)  # ceil(512/3) = 171


def rgb_led_pixels(universe: Universe) -> tuple[tuple[int, int, int], ...]:
    """Reconstruct up to 171 (R, G, B) pixels from a universe's 512
    channels: channel 3p+1 (1-based) -> R, 3p+2 -> G, 3p+3 -> B (brief §7/
    §36's mapping). The final pixel's components past channel 512 are 0."""
    channels = universe.channels  # 512 values, 0-based
    pixels = []
    for p in range(LED_PIXELS_PER_UNIVERSE):
        base = p * 3
        r = channels[base] if base < CHANNELS_PER_UNIVERSE else 0
        g = channels[base + 1] if base + 1 < CHANNELS_PER_UNIVERSE else 0
        b = channels[base + 2] if base + 2 < CHANNELS_PER_UNIVERSE else 0
        pixels.append((r, g, b))
    return tuple(pixels)


def rgb_hex(pixel: tuple[int, int, int]) -> str:
    """(255, 128, 64) -> "#FF8040" (brief §37's worked example), raw values,
    no gamma/dimming-curve adjustment."""
    r, g, b = pixel
    return f"#{r:02X}{g:02X}{b:02X}"
