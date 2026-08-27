"""Live, protocol-agnostic DMX state aggregator.

Addresses the "DMX Engine" box in the brief's architecture diagram (brief
§49; noted as not yet built in docs/RASPBERRY_PI.md §12): Art-Net and sACN
listeners feed raw universe updates in here; this class turns them into
row-indexed live state and, on each update, a committed DMXFrame snapshot
covering every row's current value -- the commit policy described in
docs/TIMING.md §4.1 ("one stored frame per committed DMX engine update").

Row assignment is first-seen order across *both* protocols combined
(SPECIFICATION.md §7): the first universe DMXEngine ever sees, from either
Art-Net or sACN, becomes row 0, and so on. This is exactly the ordering
Recorder needs when it freezes the manifest's universes[] mapping.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .frame import DMXFrame
from .universe import CHANNELS_PER_UNIVERSE, Universe

RowKey = tuple  # ("Art-Net", net, subnet, universe) or ("sACN", universe)


@dataclass
class RowInfo:
    """Source addressing for one row, mirroring
    dmxreplay.metadata.UniverseMapping's fields (kept separate from that
    class: DMXEngine is metadata-format-agnostic, Recorder is what converts
    RowInfo -> UniverseMapping when it freezes a manifest)."""

    row: int
    protocol: Literal["Art-Net", "sACN"]
    universe: int
    net: int | None = None
    subnet: int | None = None
    source_ip: str | None = None
    packet_count: int = 0


class DMXEngine:
    """Aggregates live per-universe DMX state from any number of Art-Net/sACN
    sources into one row-indexed timeline. Not tied to any specific
    listener class -- callers push updates via update_artnet()/update_sacn().
    """

    def __init__(self) -> None:
        self._rows: dict[RowKey, RowInfo] = {}
        self._row_order: list[RowKey] = []
        self._universes: list[Universe] = []  # parallel to _row_order

    def update_artnet(
        self, net: int, subnet: int, universe: int, data: bytes,
        timestamp_ns: int, source_ip: str | None = None,
    ) -> DMXFrame:
        key = ("Art-Net", net, subnet, universe)
        return self._update(
            key, data, timestamp_ns,
            protocol="Art-Net", net=net, subnet=subnet, universe=universe, source_ip=source_ip,
        )

    def update_sacn(
        self, universe: int, data: bytes, timestamp_ns: int, source_ip: str | None = None,
    ) -> DMXFrame:
        key = ("sACN", universe)
        return self._update(
            key, data, timestamp_ns,
            protocol="sACN", net=None, subnet=None, universe=universe, source_ip=source_ip,
        )

    def _update(self, key: RowKey, data: bytes, timestamp_ns: int, **addr) -> DMXFrame:
        if len(data) > CHANNELS_PER_UNIVERSE:
            raise ValueError(f"DMX data length {len(data)} exceeds {CHANNELS_PER_UNIVERSE}")

        row_info = self._rows.get(key)
        if row_info is None:
            row = len(self._row_order)
            row_info = RowInfo(row=row, **addr)
            self._rows[key] = row_info
            self._row_order.append(key)
            self._universes.append(Universe.blank())
        else:
            row = row_info.row
            row_info.source_ip = addr.get("source_ip") or row_info.source_ip

        row_info.packet_count += 1

        # A packet shorter than 512 channels updates only the channels it
        # declares; channels beyond that keep their previous value (matches
        # real Art-Net/sACN sender behavior -- most fixtures/consoles only
        # send the channels actually patched).
        if len(data) < CHANNELS_PER_UNIVERSE:
            channels = list(self._universes[row].channels)
            channels[: len(data)] = data
            self._universes[row] = Universe(channels=tuple(channels))
        else:
            self._universes[row] = Universe.from_bytes(data)

        return DMXFrame(timestamp_ns=timestamp_ns, universes=tuple(self._universes))

    def get_row_infos(self) -> list[RowInfo]:
        """Snapshot of every row discovered so far, in row order."""
        return [self._rows[k] for k in self._row_order]

    def current_frame(self, timestamp_ns: int) -> DMXFrame:
        """The current state of every row, without requiring a new update
        (used by Recorder.start() to capture the state at the moment
        recording begins, and by tests)."""
        return DMXFrame(timestamp_ns=timestamp_ns, universes=tuple(self._universes))

    @property
    def active_row_count(self) -> int:
        return len(self._row_order)
