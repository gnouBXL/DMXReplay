"""Local machine configuration for headless/autostart operation
(docs/RASPBERRY_PI.md §14) -- distinct from dmxreplay.metadata, which is
the portable .dmxr manifest schema (docs/SPECIFICATION.md §10). Nothing
here is ever written into or read from a .dmxr file.
"""
from .loader import InvalidPlayerConfigError, PlayerConfig

__all__ = ["PlayerConfig", "InvalidPlayerConfigError"]
