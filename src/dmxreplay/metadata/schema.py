"""DMXReplay manifest model. See docs/SPECIFICATION.md §10 and the formal
JSON Schema in schema.json (the two must be kept in sync by hand for now --
tests/test_metadata.py validates instances against schema.json).
"""
from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from typing import Any, Literal

FORMAT_MARKER = "DMXReplay"
CURRENT_VERSION = "1.0"
SUPPORTED_MAJOR_VERSION = 1


class UnsupportedManifestVersionError(ValueError):
    """Raised when a manifest's major version isn't understood -- fail closed
    per docs/SPECIFICATION.md §10.4/§16, never guess."""


def artnet_fields_to_port_address(net: int, subnet: int, universe: int) -> int:
    """(Net, Sub-Net, Universe) -> the flattened 15-bit Port-Address most
    consoles/software display as a single "universe number". docs/ARTNET.md §1."""
    return (net << 8) | (subnet << 4) | universe


def artnet_port_address_to_fields(port_address: int) -> tuple[int, int, int]:
    """Reverse of artnet_fields_to_port_address: flattened Port-Address ->
    (Net, Sub-Net, Universe). docs/ARTNET.md §1-§2."""
    if not (0 <= port_address <= 0x7FFF):
        raise ValueError(f"port_address must be in [0, 32767], got {port_address}")
    net = (port_address >> 8) & 0x7F
    subnet = (port_address >> 4) & 0x0F
    universe = port_address & 0x0F
    return net, subnet, universe


@dataclass
class UniverseMapping:
    """One row -> source-address mapping entry. See docs/SPECIFICATION.md §7-§9."""

    row: int
    protocol: Literal["Art-Net", "sACN"]
    universe: int
    net: int | None = None
    subnet: int | None = None
    source_ip: str | None = None

    def __post_init__(self) -> None:
        if self.row < 0:
            raise ValueError(f"row must be >= 0, got {self.row}")
        if self.protocol == "Art-Net":
            if self.net is None or self.subnet is None:
                raise ValueError("Art-Net universes require both net and subnet")
            if not (0 <= self.net <= 127):
                raise ValueError(f"net must be in [0, 127], got {self.net}")
            if not (0 <= self.subnet <= 15):
                raise ValueError(f"subnet must be in [0, 15], got {self.subnet}")
            if not (0 <= self.universe <= 15):
                raise ValueError(
                    f"Art-Net universe field must be in [0, 15], got {self.universe}"
                )
        elif self.protocol == "sACN":
            if not (1 <= self.universe <= 63999):
                raise ValueError(
                    f"sACN universe must be in [1, 63999], got {self.universe}"
                )
        else:
            raise ValueError(f"Unknown protocol {self.protocol!r}")

    def port_address(self) -> int:
        """Art-Net Port-Address: (Net << 8) | (Sub-Net << 4) | Universe. See
        docs/ARTNET.md §1. Only meaningful for protocol == 'Art-Net'."""
        if self.protocol != "Art-Net":
            raise ValueError("port_address() is only defined for Art-Net universes")
        assert self.net is not None and self.subnet is not None
        return artnet_fields_to_port_address(self.net, self.subnet, self.universe)

    @classmethod
    def from_artnet_port_address(
        cls, row: int, port_address: int, source_ip: str | None = None
    ) -> "UniverseMapping":
        """Build a mapping from the flattened Port-Address numbering most
        consoles/software show users (e.g. "Universe 17") -- see docs/ARTNET.md
        §1-§2. Decomposes into the raw net/subnet/universe fields DMXReplay
        actually stores."""
        net, subnet, universe = artnet_port_address_to_fields(port_address)
        return cls(
            row=row, protocol="Art-Net", universe=universe, net=net, subnet=subnet,
            source_ip=source_ip,
        )

    def to_dict(self) -> dict[str, Any]:
        d = dataclasses.asdict(self)
        return {k: v for k, v in d.items() if v is not None}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UniverseMapping":
        known = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class Manifest:
    """The DMXReplay manifest (docs/SPECIFICATION.md §10). Embedded as a
    Matroska attachment named 'dmxreplay-manifest.json' (docs/CONTAINER.md §4).
    """

    encoding: Literal["grayscale", "rgb_packed"]
    fps: float
    vfr: bool
    timestamp_resolution_ns: int
    width: int
    height: int
    universes: list[UniverseMapping]
    created_at: str
    duration_seconds: float
    recorder: dict[str, str]
    format: str = FORMAT_MARKER
    version: str = CURRENT_VERSION
    audio: dict[str, Any] | None = None
    external_video_ref: str | None = None
    show_name: str | None = None
    description: str | None = None
    container_version: str | None = None
    # Unknown/future fields encountered on read are preserved here so a tool
    # that round-trips a manifest doesn't drop them (docs/SPECIFICATION.md §10.4).
    extra_fields: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.format != FORMAT_MARKER:
            raise ValueError(f"format must be {FORMAT_MARKER!r}, got {self.format!r}")
        major = _major_version(self.version)
        if major != SUPPORTED_MAJOR_VERSION:
            raise UnsupportedManifestVersionError(
                f"Unsupported manifest major version {major} "
                f"(this reader supports major version {SUPPORTED_MAJOR_VERSION})"
            )
        if self.height != len(self.universes):
            raise ValueError(
                f"height ({self.height}) must equal len(universes) "
                f"({len(self.universes)}) per SPECIFICATION.md §4/§7"
            )
        rows = [u.row for u in self.universes]
        if sorted(rows) != list(range(len(rows))):
            raise ValueError(
                "universes[].row must be a contiguous 0-based range with no gaps "
                "(SPECIFICATION.md §7)"
            )

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "format": self.format,
            "version": self.version,
            "encoding": self.encoding,
            "fps": self.fps,
            "vfr": self.vfr,
            "timestamp_resolution_ns": self.timestamp_resolution_ns,
            "width": self.width,
            "height": self.height,
            "universes": [u.to_dict() for u in self.universes],
            "created_at": self.created_at,
            "duration_seconds": self.duration_seconds,
            "recorder": self.recorder,
        }
        for key in (
            "audio",
            "external_video_ref",
            "show_name",
            "description",
            "container_version",
        ):
            value = getattr(self, key)
            if value is not None:
                d[key] = value
        d.update(self.extra_fields)
        return d

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Manifest":
        known = {f.name for f in dataclasses.fields(cls)} - {"extra_fields"}
        kwargs = {k: v for k, v in data.items() if k in known}
        kwargs["universes"] = [
            UniverseMapping.from_dict(u) for u in data.get("universes", [])
        ]
        extra = {k: v for k, v in data.items() if k not in known}
        return cls(**kwargs, extra_fields=extra)

    @classmethod
    def from_json(cls, data: str) -> "Manifest":
        return cls.from_dict(json.loads(data))


def _major_version(version: str) -> int:
    try:
        return int(version.split(".", 1)[0])
    except (ValueError, IndexError) as exc:
        raise ValueError(f"Malformed version string: {version!r}") from exc
