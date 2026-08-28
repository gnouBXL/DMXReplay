"""Recorder core engine. See docs/API.md §4, brief §13/§28-§29.

GUI-independent (CONTRIBUTING.md): a CLI or GUI only ever calls the methods
below and reads RecorderStatus/RowInfo; neither touches the network or the
encoder directly. This is what makes `dmxreplay-record --headless` possible
without dmxreplay.ui (docs/RASPBERRY_PI.md §12/§13).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from ..clock import MasterClock
from ..codec import ENCODINGS, Encoding
from ..container import STORAGE_TIMESTAMP_RESOLUTION_NS, DMXReplayWriter
from ..dmx import DemoDMXSource, DMXEngine, RowInfo
from ..metadata import Manifest, UniverseMapping
from ..network.artnet import ARTNET_PORT, ArtNetListener
from ..network.sacn import SACN_PORT, SACNListener
from ..preview import PreviewMode, compute_preview
from .status import RecorderStatus

RECORDER_NAME = "dmxreplay-recorder"
RECORDER_VERSION = "0.1.0-dev"


class Recorder:
    """Owns the write path: network listener(s) -> DMXEngine -> DMXReplayWriter.

    Usage:
        recorder = Recorder()
        await recorder.add_source("Art-Net", interface_ip="eth0-ip")
        # ... wait for discovery, inspect recorder.get_universes() ...
        recorder.start("show.dmxr")
        # ... recording happens via the listener callbacks ...
        recorder.stop()
        await recorder.close()
    """

    def __init__(self, clock: MasterClock | None = None) -> None:
        self._clock = clock or MasterClock()
        self._engine = DMXEngine()
        self._artnet_listeners: list[ArtNetListener] = []
        self._sacn_listeners: list[SACNListener] = []
        self._writer: DMXReplayWriter | None = None
        self._output_path: str | None = None
        self._recording = False
        self._frame_count = 0
        self._start_ns: int | None = None
        self._demo_task: asyncio.Task | None = None

    async def add_source(
        self,
        protocol: Literal["Art-Net", "sACN"],
        interface_ip: str,
        port: int | None = None,
        multicast_universes: list[int] | None = None,
    ) -> None:
        """Start listening on one interface. MAY be called multiple times for
        multiple sources/protocols (brief §14); each gets its own listener,
        all feeding the same DMXEngine and sharing this Recorder's MasterClock
        so every committed frame is on one consistent capture timeline."""
        if protocol == "Art-Net":
            listener = ArtNetListener(on_packet=self._on_artnet_packet, clock=self._clock)
            await listener.start(
                interface_ip=interface_ip, port=port if port is not None else ARTNET_PORT
            )
            self._artnet_listeners.append(listener)
        elif protocol == "sACN":
            listener = SACNListener(on_packet=self._on_sacn_packet, clock=self._clock)
            await listener.start(
                interface_ip=interface_ip, port=port if port is not None else SACN_PORT,
                multicast_universes=multicast_universes,
            )
            self._sacn_listeners.append(listener)
        else:
            raise ValueError(f"Unknown protocol {protocol!r}")

    def add_demo_source(self, universe_count: int = 4, fps: float = 30.0) -> None:
        """A synthetic, no-network DMX source (`DemoDMXSource`) for
        exploring the Recorder without real Art-Net/sACN hardware
        connected. Feeds `DMXEngine.update_artnet()` directly from a real,
        ticking `asyncio` task at a real cadence -- the identical engine
        code path a real `ArtNetListener` callback would exercise, just
        without a socket underneath, so `get_universes()`/recording/preview
        all behave exactly as they would for a real source. At most one
        demo source at a time; calling this again while one is already
        running is a no-op (matching `add_source()`'s "call multiple times
        for multiple real sources" being additive, not this -- one
        synthetic source is enough to demonstrate the pipeline)."""
        if self._demo_task is not None:
            return
        source = DemoDMXSource(universe_count)

        async def _run() -> None:
            period = 1.0 / fps
            try:
                while True:
                    for row, universe in enumerate(source.tick()):
                        frame = self._engine.update_artnet(
                            net=0, subnet=0, universe=row, data=universe.to_bytes(),
                            timestamp_ns=self._clock.now_ns(), source_ip="demo",
                        )
                        self._maybe_commit(frame)
                    await asyncio.sleep(period)
            except asyncio.CancelledError:
                pass

        self._demo_task = asyncio.ensure_future(_run())

    def remove_demo_source(self) -> None:
        if self._demo_task is not None:
            self._demo_task.cancel()
            self._demo_task = None

    @property
    def has_demo_source(self) -> bool:
        return self._demo_task is not None

    def current_preview(self, row: int, mode: PreviewMode = "raw"):
        """The current DMX state at `row` (real or demo source alike),
        transformed per `mode` (`dmxreplay.preview`) -- for a live
        "universe monitor" UI. Returns None if `row` isn't active yet.
        Purely cosmetic, like `Player.current_preview()`: never affects
        what's stored or (for a real source) received."""
        frame = self._engine.current_frame(self._clock.now_ns())
        if row >= len(frame.universes):
            return None
        return compute_preview(frame.universes[row], mode)

    def _on_artnet_packet(self, packet, source_ip: str, timestamp_ns: int) -> None:
        frame = self._engine.update_artnet(
            net=packet.net, subnet=packet.subnet, universe=packet.universe,
            data=packet.data, timestamp_ns=timestamp_ns, source_ip=source_ip,
        )
        self._maybe_commit(frame)

    def _on_sacn_packet(self, packet, source_ip: str, timestamp_ns: int) -> None:
        if not packet.is_dmx_data:
            return  # non-DMX start code (e.g. RDM) -- docs/SACN.md §3
        frame = self._engine.update_sacn(
            universe=packet.universe, data=packet.dmx_data,
            timestamp_ns=timestamp_ns, source_ip=source_ip,
        )
        self._maybe_commit(frame)

    def _maybe_commit(self, frame) -> None:
        # One stored frame per received (valid) packet while recording --
        # docs/TIMING.md §4.1's commit policy. No explicit rate limiting:
        # near-duplicate consecutive frames compress extremely well under
        # FFV1 (FORMAT-RESEARCH.md §4), so this stays correct and simple
        # rather than adding an unproven rate limiter pre-emptively.
        if self._recording and self._writer is not None:
            self._writer.write_frame(frame)
            self._frame_count += 1

    def get_universes(self) -> list[RowInfo]:
        """Universes discovered so far, for a 'detected universes' UI
        (brief §13/§28) to checkbox before calling start()."""
        return self._engine.get_row_infos()

    def start(self, output_path: str, *, encoding: Encoding = "grayscale", fps: float = 30.0) -> None:
        """Freeze the currently-discovered universe set into a manifest and
        begin writing. Universes first seen *after* this call are not added
        to the recording -- the video track's dimensions are fixed at
        container-header time (docs/CONTAINER.md), matching the brief §28
        recorder GUI flow (discover, checkbox, then RECORD)."""
        if self._recording:
            raise RuntimeError("already recording")
        rows = self._engine.get_row_infos()
        if not rows:
            raise RuntimeError(
                "no universes discovered yet -- call add_source() and wait for "
                "at least one packet before start()"
            )

        mapping = [
            UniverseMapping(
                row=r.row, protocol=r.protocol, universe=r.universe,
                net=r.net, subnet=r.subnet, source_ip=r.source_ip,
            )
            for r in rows
        ]
        manifest = Manifest(
            encoding=encoding,
            fps=fps,
            vfr=True,
            timestamp_resolution_ns=STORAGE_TIMESTAMP_RESOLUTION_NS,
            width=ENCODINGS[encoding]["width"],
            height=len(rows),
            universes=mapping,
            created_at=datetime.now(timezone.utc).isoformat(),
            # Best-effort placeholder -- the true duration isn't known until
            # stop(); see SPECIFICATION.md §10.1's duration_seconds note.
            duration_seconds=0.0,
            recorder={"name": RECORDER_NAME, "version": RECORDER_VERSION},
        )

        self._writer = DMXReplayWriter(output_path, manifest)
        self._output_path = output_path
        self._start_ns = self._clock.now_ns()
        self._recording = True
        self._frame_count = 0
        # Write an initial frame capturing current state immediately, so
        # playback has correct DMX from t=0 even if the next real packet is
        # still a full frame-period away.
        self._writer.write_frame(self._engine.current_frame(self._start_ns))
        self._frame_count = 1

    def stop(self) -> None:
        if not self._recording:
            return
        self._recording = False
        if self._writer is not None:
            self._writer.close()
            self._writer = None

    def get_status(self) -> RecorderStatus:
        duration = 0.0
        if self._start_ns is not None:
            duration = (self._clock.now_ns() - self._start_ns) / 1_000_000_000
        file_size = None
        if self._output_path is not None and Path(self._output_path).exists():
            file_size = Path(self._output_path).stat().st_size
        total_packets = sum(r.packet_count for r in self._engine.get_row_infos())
        malformed = sum(l.malformed_packet_count for l in self._artnet_listeners)
        malformed += sum(l.malformed_packet_count for l in self._sacn_listeners)
        return RecorderStatus(
            recording=self._recording,
            duration_seconds=duration,
            universe_count=self._engine.active_row_count,
            frame_count=self._frame_count,
            total_packets=total_packets,
            malformed_packets=malformed,
            file_size_bytes=file_size,
        )

    async def close(self) -> None:
        """Stop recording (if active) and close every network listener (and
        the demo source's task, if one is running)."""
        self.stop()
        self.remove_demo_source()
        for listener in self._artnet_listeners:
            listener.stop()
        for listener in self._sacn_listeners:
            listener.stop()
