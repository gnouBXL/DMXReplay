"""DMX universe/channel data model. See docs/SPECIFICATION.md §5-§6."""
from __future__ import annotations

from dataclasses import dataclass

CHANNELS_PER_UNIVERSE = 512
MIN_CHANNEL_VALUE = 0
MAX_CHANNEL_VALUE = 255


@dataclass(frozen=True, slots=True)
class Universe:
    """One DMX universe: exactly 512 unsigned 8-bit channel values.

    Channels carry no semantic meaning (SPECIFICATION.md §6) -- this class only
    stores and validates raw bytes. `channels` is 0-indexed internally;
    `get_channel`/`with_channel` use DMX's conventional 1-based channel numbering
    to match the terminology in SPECIFICATION.md §1.
    """

    channels: tuple[int, ...]

    def __post_init__(self) -> None:
        if len(self.channels) != CHANNELS_PER_UNIVERSE:
            raise ValueError(
                f"Universe must have exactly {CHANNELS_PER_UNIVERSE} channels, "
                f"got {len(self.channels)}"
            )
        for value in self.channels:
            if not (MIN_CHANNEL_VALUE <= value <= MAX_CHANNEL_VALUE):
                raise ValueError(
                    f"Channel value {value} out of range "
                    f"[{MIN_CHANNEL_VALUE}, {MAX_CHANNEL_VALUE}]"
                )

    @classmethod
    def blank(cls) -> "Universe":
        """A universe with every channel at 0."""
        return cls(channels=(0,) * CHANNELS_PER_UNIVERSE)

    @classmethod
    def from_bytes(cls, data: bytes) -> "Universe":
        if len(data) != CHANNELS_PER_UNIVERSE:
            raise ValueError(
                f"Expected {CHANNELS_PER_UNIVERSE} bytes, got {len(data)}"
            )
        return cls(channels=tuple(data))

    def to_bytes(self) -> bytes:
        return bytes(self.channels)

    def get_channel(self, channel_number: int) -> int:
        """1-based channel access (channel_number in 1..512), per DMX convention."""
        if not (1 <= channel_number <= CHANNELS_PER_UNIVERSE):
            raise ValueError(
                f"channel_number must be in [1, {CHANNELS_PER_UNIVERSE}], "
                f"got {channel_number}"
            )
        return self.channels[channel_number - 1]

    def with_channel(self, channel_number: int, value: int) -> "Universe":
        """Return a new Universe with one 1-based channel replaced (immutable update)."""
        if not (1 <= channel_number <= CHANNELS_PER_UNIVERSE):
            raise ValueError(
                f"channel_number must be in [1, {CHANNELS_PER_UNIVERSE}], "
                f"got {channel_number}"
            )
        if not (MIN_CHANNEL_VALUE <= value <= MAX_CHANNEL_VALUE):
            raise ValueError(
                f"Channel value {value} out of range "
                f"[{MIN_CHANNEL_VALUE}, {MAX_CHANNEL_VALUE}]"
            )
        new_channels = list(self.channels)
        new_channels[channel_number - 1] = value
        return Universe(channels=tuple(new_channels))
