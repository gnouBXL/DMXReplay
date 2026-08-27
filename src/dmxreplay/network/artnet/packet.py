"""Art-Net `OpDmx` packet parsing and building. See docs/ARTNET.md §3-§4, §6."""
from __future__ import annotations

import struct
from dataclasses import dataclass

ARTNET_ID = b"Art-Net\x00"
ARTNET_PORT = 6454
OP_DMX = 0x5000
MIN_PROTOCOL_VERSION = 14
MAX_DMX_LENGTH = 512


class MalformedArtNetPacketError(ValueError):
    """Raised when a received datagram fails ArtDmxPacket validation
    (docs/ARTNET.md §4, docs/SPECIFICATION.md §15/§18). The caller MUST drop
    and log the packet, never forward it to the DMX engine."""


@dataclass(frozen=True, slots=True)
class ArtDmxPacket:
    """A parsed/to-be-sent Art-Net `OpDmx` packet. Byte layout: docs/ARTNET.md §4."""

    sequence: int  # 0-255; 0 = sequencing disabled by sender
    physical: int  # 0-255, informational only
    net: int  # 0-127
    subnet: int  # 0-15
    universe: int  # 0-15 (raw Art-Net Universe field -- see docs/ARTNET.md §1.1)
    data: bytes  # DMX channel values, len in [2, 512], even length

    def __post_init__(self) -> None:
        if not (0 <= self.sequence <= 255):
            raise ValueError(f"sequence must be in [0, 255], got {self.sequence}")
        if not (0 <= self.physical <= 255):
            raise ValueError(f"physical must be in [0, 255], got {self.physical}")
        if not (0 <= self.net <= 127):
            raise ValueError(f"net must be in [0, 127], got {self.net}")
        if not (0 <= self.subnet <= 15):
            raise ValueError(f"subnet must be in [0, 15], got {self.subnet}")
        if not (0 <= self.universe <= 15):
            raise ValueError(f"universe must be in [0, 15], got {self.universe}")
        if not (2 <= len(self.data) <= MAX_DMX_LENGTH):
            raise ValueError(f"data length must be in [2, {MAX_DMX_LENGTH}], got {len(self.data)}")
        if len(self.data) % 2 != 0:
            raise ValueError(f"data length must be even, got {len(self.data)}")

    def port_address(self) -> int:
        return (self.net << 8) | (self.subnet << 4) | self.universe

    def to_bytes(self) -> bytes:
        sub_uni = (self.subnet << 4) | self.universe
        header = ARTNET_ID
        header += struct.pack("<H", OP_DMX)  # OpCode: little-endian
        header += struct.pack(">H", MIN_PROTOCOL_VERSION)  # ProtVer: big-endian
        header += bytes([self.sequence, self.physical, sub_uni, self.net])
        header += struct.pack(">H", len(self.data))  # Length: big-endian
        return header + self.data

    @classmethod
    def parse(cls, raw: bytes) -> "ArtDmxPacket":
        """Parse and fully validate a received datagram. Raises
        MalformedArtNetPacketError (never a bare exception type) on any
        validation failure, per docs/ARTNET.md §4 / docs/SPECIFICATION.md §18."""
        if len(raw) < 18:
            raise MalformedArtNetPacketError(f"packet too short ({len(raw)} bytes)")
        if raw[0:8] != ARTNET_ID:
            raise MalformedArtNetPacketError("bad Art-Net ID header")

        opcode = struct.unpack_from("<H", raw, 8)[0]
        if opcode != OP_DMX:
            raise MalformedArtNetPacketError(f"unsupported OpCode 0x{opcode:04X}")

        proto_ver = struct.unpack_from(">H", raw, 10)[0]
        if proto_ver < MIN_PROTOCOL_VERSION:
            raise MalformedArtNetPacketError(f"protocol version {proto_ver} too old")

        sequence = raw[12]
        physical = raw[13]
        sub_uni = raw[14]
        net = raw[15]
        if net > 127:
            raise MalformedArtNetPacketError(f"net {net} out of range [0, 127]")

        length = struct.unpack_from(">H", raw, 16)[0]
        if not (2 <= length <= MAX_DMX_LENGTH) or length % 2 != 0:
            raise MalformedArtNetPacketError(f"invalid declared length {length}")
        payload = raw[18:]
        if len(payload) != length:
            raise MalformedArtNetPacketError(
                f"declared length {length} does not match actual payload {len(payload)}"
            )

        return cls(
            sequence=sequence,
            physical=physical,
            net=net,
            subnet=(sub_uni >> 4) & 0x0F,
            universe=sub_uni & 0x0F,
            data=payload,
        )
