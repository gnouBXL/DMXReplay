"""Headless Player config-file loader. Implements the shape proposed (but
never parsed by any code) in docs/RASPBERRY_PI.md §14 -- lets
`dmxreplay-play --headless --config <path>` or a systemd unit start
without every option on the command line. See docs/RASPBERRY_PI.md §14 and
docs/RASPBERRY_PI_INSTALL.md.

Not a `.dmxr` format concern: this is local machine configuration (what
show to play, which network interface, whether to autoplay), never
embedded in or read from a .dmxr file, and has nothing to do with
SPECIFICATION.md's manifest schema.
"""
from __future__ import annotations

import dataclasses
import sys
from dataclasses import dataclass
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore[no-redef]


class InvalidPlayerConfigError(ValueError):
    """Raised for a config file DMXReplay can parse as TOML but not
    understand -- fail closed (missing required key, unknown key -- almost
    always a typo in a systemd-managed file nobody will be watching stderr
    for interactively) rather than silently ignoring or guessing."""


@dataclass
class PlayerConfig:
    show: str
    video: str | None = None
    output: str = "artnet"  # "artnet" | "sacn"
    interface: str = "0.0.0.0"
    destination: str | None = None
    port: int | None = None
    priority: int = 100  # sACN sender priority, docs/SACN.md
    loop: bool = False
    autoplay: bool = True
    fps: float | None = None
    speed: float = 1.0

    def __post_init__(self) -> None:
        if self.output not in ("artnet", "sacn"):
            raise InvalidPlayerConfigError(
                f"output must be 'artnet' or 'sacn', got {self.output!r}"
            )

    @classmethod
    def from_toml_file(cls, path: str) -> "PlayerConfig":
        with open(path, "rb") as f:
            try:
                data = tomllib.load(f)
            except tomllib.TOMLDecodeError as exc:
                raise InvalidPlayerConfigError(f"{path}: malformed TOML: {exc}") from exc
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PlayerConfig":
        if "show" not in data:
            raise InvalidPlayerConfigError("config must set 'show' (path to the .dmxr file to play)")
        known = {f.name for f in dataclasses.fields(cls)}
        unknown = sorted(set(data) - known)
        if unknown:
            raise InvalidPlayerConfigError(
                f"unknown config key(s) {unknown} -- known keys are {sorted(known)} "
                "(likely a typo; DMXReplay fails closed on config rather than "
                "silently ignoring a misspelled key in an unattended service)"
            )
        try:
            return cls(**data)
        except TypeError as exc:
            raise InvalidPlayerConfigError(f"invalid config: {exc}") from exc
