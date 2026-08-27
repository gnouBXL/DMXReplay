"""sACN / ANSI E1.31 data packet parsing and building. See docs/SACN.md §2-§4."""
from __future__ import annotations

import struct
import uuid
from dataclasses import dataclass, field

SACN_PORT = 5568
ACN_PACKET_IDENTIFIER = b"ASC-E1.17\x00\x00\x00"
VECTOR_ROOT_E131_DATA = 0x00000004
VECTOR_E131_DATA_PACKET = 0x00000002
VECTOR_DMP_SET_PROPERTY = 0x02
DMP_ADDRESS_DATA_TYPE = 0xA1
DMP_FIRST_PROPERTY_ADDRESS = 0x0000
DMP_ADDRESS_INCREMENT = 0x0001
MAX_DMX_SLOTS = 512
DEFAULT_START_CODE = 0x00

# Byte offsets, per docs/SACN.md §2 (also documented inline below for readers
# without that doc open).
_OFFSET_PREAMBLE = 0
_OFFSET_ACN_ID = 4
_OFFSET_ROOT_FLAGS_LENGTH = 16
_OFFSET_ROOT_VECTOR = 18
_OFFSET_CID = 22
_OFFSET_FRAMING = 38
_OFFSET_FRAMING_VECTOR = 40
_OFFSET_SOURCE_NAME = 44
_OFFSET_PRIORITY = 108
_OFFSET_SYNC_ADDRESS = 109
_OFFSET_SEQUENCE = 111
_OFFSET_OPTIONS = 112
_OFFSET_UNIVERSE = 113
_OFFSET_DMP = 115
_OFFSET_DMP_VECTOR = 117
_OFFSET_DMP_ADDR_TYPE = 118
_OFFSET_DMP_FIRST_PROP_ADDR = 119
_OFFSET_DMP_ADDR_INCREMENT = 121
_OFFSET_DMP_PROP_VALUE_COUNT = 123
_OFFSET_PROPERTY_VALUES = 125  # start code + DMX data

_OPTION_PREVIEW_DATA = 0x80
_OPTION_STREAM_TERMINATED = 0x40
_OPTION_FORCE_SYNC = 0x20


class MalformedE131PacketError(ValueError):
    """Raised when a received datagram fails E1.31 structural validation
    (docs/SACN.md §2, docs/SPECIFICATION.md §15/§18). The caller MUST drop and
    log the packet, never forward it to the DMX engine.

    NOTE: a non-zero DMX start code (docs/SACN.md §3) is *not* malformed --
    it's valid E1.31 carrying non-DMX data (e.g. RDM). Check
    E131DataPacket.is_dmx_data instead of expecting parse() to raise for it.
    """


def _pdu_flags_and_length(length: int) -> int:
    if not (0 <= length <= 0x0FFF):
        raise ValueError(f"PDU length {length} exceeds 12-bit field")
    return (0x7 << 12) | length


@dataclass(frozen=True, slots=True)
class E131DataPacket:
    """A parsed/to-be-sent E1.31 (sACN) data packet. V1 implements the basic
    streaming subset only -- see docs/SACN.md §5-§7 for what's deferred."""

    universe: int  # 1-63999
    dmx_data: bytes  # 1-512 slots, NOT including the start code
    cid: bytes = field(default_factory=lambda: uuid.uuid4().bytes)  # 16 bytes
    source_name: str = "DMXReplay"
    priority: int = 100
    sequence_number: int = 0
    sync_address: int = 0
    start_code: int = DEFAULT_START_CODE
    preview_data: bool = False
    stream_terminated: bool = False
    force_sync: bool = False

    def __post_init__(self) -> None:
        if not (1 <= self.universe <= 63999):
            raise ValueError(f"universe must be in [1, 63999], got {self.universe}")
        if not (1 <= len(self.dmx_data) <= MAX_DMX_SLOTS):
            raise ValueError(f"dmx_data length must be in [1, {MAX_DMX_SLOTS}], got {len(self.dmx_data)}")
        if len(self.cid) != 16:
            raise ValueError(f"cid must be 16 bytes, got {len(self.cid)}")
        if not (0 <= self.priority <= 200):
            raise ValueError(f"priority must be in [0, 200], got {self.priority}")
        if not (0 <= self.sequence_number <= 255):
            raise ValueError(f"sequence_number must be in [0, 255], got {self.sequence_number}")
        if not (0 <= self.start_code <= 255):
            raise ValueError(f"start_code must be in [0, 255], got {self.start_code}")
        source_name_bytes = self.source_name.encode("utf-8")
        if len(source_name_bytes) > 63:
            raise ValueError("source_name must encode to at most 63 UTF-8 bytes")

    @property
    def is_dmx_data(self) -> bool:
        """True iff this packet carries standard null-start-code DMX data
        (docs/SACN.md §3). False for RDM/alternate-start-code payloads, which
        V1 does not interpret as DMX."""
        return self.start_code == DEFAULT_START_CODE

    def to_bytes(self) -> bytes:
        property_values = bytes([self.start_code]) + self.dmx_data
        dmp_prop_value_count = len(property_values)

        source_name_bytes = self.source_name.encode("utf-8").ljust(64, b"\x00")
        options = 0
        if self.preview_data:
            options |= _OPTION_PREVIEW_DATA
        if self.stream_terminated:
            options |= _OPTION_STREAM_TERMINATED
        if self.force_sync:
            options |= _OPTION_FORCE_SYNC

        dmp_layer = (
            struct.pack(">B", VECTOR_DMP_SET_PROPERTY)
            + struct.pack(">B", DMP_ADDRESS_DATA_TYPE)
            + struct.pack(">H", DMP_FIRST_PROPERTY_ADDRESS)
            + struct.pack(">H", DMP_ADDRESS_INCREMENT)
            + struct.pack(">H", dmp_prop_value_count)
            + property_values
        )
        dmp_pdu_length = 2 + len(dmp_layer)  # + its own flags&length field
        dmp_full = struct.pack(">H", _pdu_flags_and_length(dmp_pdu_length)) + dmp_layer

        framing_layer = (
            struct.pack(">I", VECTOR_E131_DATA_PACKET)
            + source_name_bytes
            + struct.pack(">B", self.priority)
            + struct.pack(">H", self.sync_address)
            + struct.pack(">B", self.sequence_number)
            + struct.pack(">B", options)
            + struct.pack(">H", self.universe)
            + dmp_full
        )
        framing_pdu_length = 2 + len(framing_layer)
        framing_full = struct.pack(">H", _pdu_flags_and_length(framing_pdu_length)) + framing_layer

        root_layer = struct.pack(">I", VECTOR_ROOT_E131_DATA) + self.cid + framing_full
        root_pdu_length = 2 + len(root_layer)

        return (
            struct.pack(">H", 0x0010)  # Preamble Size
            + struct.pack(">H", 0x0000)  # Post-amble Size
            + ACN_PACKET_IDENTIFIER
            + struct.pack(">H", _pdu_flags_and_length(root_pdu_length))
            + root_layer
        )

    @classmethod
    def parse(cls, raw: bytes) -> "E131DataPacket":
        if len(raw) < _OFFSET_PROPERTY_VALUES + 1:
            raise MalformedE131PacketError(f"packet too short ({len(raw)} bytes)")

        preamble = struct.unpack_from(">H", raw, _OFFSET_PREAMBLE)[0]
        if preamble != 0x0010:
            raise MalformedE131PacketError(f"bad preamble size 0x{preamble:04X}")
        if raw[_OFFSET_ACN_ID : _OFFSET_ACN_ID + 12] != ACN_PACKET_IDENTIFIER:
            raise MalformedE131PacketError("bad ACN packet identifier")

        root_vector = struct.unpack_from(">I", raw, _OFFSET_ROOT_VECTOR)[0]
        if root_vector != VECTOR_ROOT_E131_DATA:
            raise MalformedE131PacketError(f"unsupported root vector 0x{root_vector:08X}")
        cid = raw[_OFFSET_CID : _OFFSET_CID + 16]

        framing_vector = struct.unpack_from(">I", raw, _OFFSET_FRAMING_VECTOR)[0]
        if framing_vector != VECTOR_E131_DATA_PACKET:
            raise MalformedE131PacketError(f"unsupported framing vector 0x{framing_vector:08X}")

        source_name = raw[_OFFSET_SOURCE_NAME : _OFFSET_SOURCE_NAME + 64].split(b"\x00", 1)[0].decode(
            "utf-8", errors="replace"
        )
        priority = raw[_OFFSET_PRIORITY]
        sync_address = struct.unpack_from(">H", raw, _OFFSET_SYNC_ADDRESS)[0]
        sequence_number = raw[_OFFSET_SEQUENCE]
        options = raw[_OFFSET_OPTIONS]
        universe = struct.unpack_from(">H", raw, _OFFSET_UNIVERSE)[0]
        if not (1 <= universe <= 63999):
            raise MalformedE131PacketError(f"universe {universe} out of range [1, 63999]")

        dmp_vector = raw[_OFFSET_DMP_VECTOR]
        if dmp_vector != VECTOR_DMP_SET_PROPERTY:
            raise MalformedE131PacketError(f"unsupported DMP vector 0x{dmp_vector:02X}")
        addr_type = raw[_OFFSET_DMP_ADDR_TYPE]
        if addr_type != DMP_ADDRESS_DATA_TYPE:
            raise MalformedE131PacketError(f"unsupported DMP address/data type 0x{addr_type:02X}")
        first_prop_addr = struct.unpack_from(">H", raw, _OFFSET_DMP_FIRST_PROP_ADDR)[0]
        if first_prop_addr != DMP_FIRST_PROPERTY_ADDRESS:
            raise MalformedE131PacketError(f"unexpected first property address {first_prop_addr}")
        addr_increment = struct.unpack_from(">H", raw, _OFFSET_DMP_ADDR_INCREMENT)[0]
        if addr_increment != DMP_ADDRESS_INCREMENT:
            raise MalformedE131PacketError(f"unexpected address increment {addr_increment}")

        prop_value_count = struct.unpack_from(">H", raw, _OFFSET_DMP_PROP_VALUE_COUNT)[0]
        if not (2 <= prop_value_count <= MAX_DMX_SLOTS + 1):
            raise MalformedE131PacketError(f"invalid property value count {prop_value_count}")
        property_values = raw[_OFFSET_PROPERTY_VALUES : _OFFSET_PROPERTY_VALUES + prop_value_count]
        if len(property_values) != prop_value_count:
            raise MalformedE131PacketError(
                f"declared property value count {prop_value_count} does not match "
                f"actual payload {len(property_values)}"
            )

        return cls(
            universe=universe,
            dmx_data=property_values[1:],
            cid=cid,
            source_name=source_name,
            priority=priority,
            sequence_number=sequence_number,
            sync_address=sync_address,
            start_code=property_values[0],
            preview_data=bool(options & _OPTION_PREVIEW_DATA),
            stream_terminated=bool(options & _OPTION_STREAM_TERMINATED),
            force_sync=bool(options & _OPTION_FORCE_SYNC),
        )
