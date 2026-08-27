"""Player core engine. See docs/API.md §5, docs/TIMING.md, brief §30-§33.

GUI-independent (CONTRIBUTING.md): a CLI or GUI only ever calls the methods
below; the playback loop, master timeline, and network output all live here,
enabling `dmxreplay-play --headless` without dmxreplay.ui
(docs/RASPBERRY_PI.md §12/§13).

Scope of this pass: DMX playback and output (Art-Net/sACN), driven by one
Timeline (docs/TIMING.md §1-§2), with seek/play/pause/stop/loop/speed/fps.
Audio sync (Phase 7), external video sync (Phase 8), and preview modes
(Phase 9) are not implemented here -- API.md documents them as later-phase
additions to this same class, not a reason to stub them now.
"""
from __future__ import annotations

import asyncio
import bisect
from typing import Literal

from ..clock import ClockProvider, Timeline
from ..container import DMXReplayReader
from ..dmx import DMXFrame
from ..metadata import Manifest, artnet_port_address_to_fields
from ..network.artnet import ARTNET_PORT, ArtNetSender
from ..network.sacn import SACN_PORT, SACNSender

OutputProtocol = Literal["Art-Net", "sACN"]


class Player:
    def __init__(self, clock_provider: ClockProvider | None = None) -> None:
        self._timeline = Timeline(provider=clock_provider)
        self._manifest: Manifest | None = None
        self._frames: list[DMXFrame] = []
        self._timestamps: list[int] = []
        self._duration_ns = 0
        self._loop = False
        self._speed = 1.0
        self._fps = 30.0

        self._output_protocol: OutputProtocol | None = None
        self._output_interface_ip = "0.0.0.0"
        self._output_destination_ip: str | None = None
        self._output_port: int | None = None
        self._output_priority = 100
        self._universe_mapping: dict[int, int] | None = None  # row -> destination Port-Address/universe, brief §34

        self._sender: ArtNetSender | SACNSender | None = None
        self._task: asyncio.Task | None = None
        self._last_sent_index: int | None = None

    # --- Loading -------------------------------------------------------- #

    def load(self, dmxr_path: str) -> None:
        with DMXReplayReader(dmxr_path) as reader:
            self._manifest = reader.manifest
            self._frames = list(reader.read_frames())
        self._timestamps = [f.timestamp_ns for f in self._frames]
        self._duration_ns = self._timestamps[-1] if self._timestamps else 0
        self._fps = self._manifest.fps
        self._timeline.seek(0)
        self._last_sent_index = None

    @property
    def manifest(self) -> Manifest | None:
        return self._manifest

    @property
    def duration_ns(self) -> int:
        return self._duration_ns

    # --- Output configuration -------------------------------------------- #

    def set_output(
        self,
        protocol: OutputProtocol,
        interface_ip: str = "0.0.0.0",
        destination_ip: str | None = None,
        port: int | None = None,
        priority: int = 100,
    ) -> None:
        """Configure where decoded DMX is sent. destination_ip=None means
        broadcast for Art-Net, or the standard per-universe multicast group
        for sACN (docs/ARTNET.md §6, docs/SACN.md §8)."""
        self._output_protocol = protocol
        self._output_interface_ip = interface_ip
        self._output_destination_ip = destination_ip
        self._output_port = port
        self._output_priority = priority

    def set_universe_mapping(self, mapping: dict[int, int] | None) -> None:
        """Remap row -> destination universe for output only (brief §34).
        For Art-Net, values are flattened Port-Addresses (docs/ARTNET.md
        §1.1); for sACN, plain universe numbers. Never modifies the loaded
        file. Pass None to reset to the manifest's own recorded addressing."""
        self._universe_mapping = mapping

    # --- Transport -------------------------------------------------------- #

    async def play(self, speed: float | None = None) -> None:
        if self._output_protocol is None:
            raise RuntimeError("call set_output() before play()")
        if speed is not None:
            self._speed = speed
        if self._sender is None:
            await self._open_output()
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run_loop())
        self._timeline.play(speed=self._speed)

    def pause(self) -> None:
        self._timeline.pause()

    async def stop(self) -> None:
        self._timeline.pause()
        self._timeline.seek(0)
        self._last_sent_index = None
        if self._task is not None:
            self._task.cancel()
            self._task = None
        if self._sender is not None:
            self._sender.stop()
            self._sender = None

    def seek(self, position_ns: int) -> None:
        position_ns = max(0, min(position_ns, self._duration_ns))
        self._timeline.seek(position_ns)
        self._last_sent_index = None  # force re-emit at the new position

    def set_speed(self, speed: float) -> None:
        self._speed = speed
        if self._timeline.playing:
            self._timeline.play(speed=speed)

    def set_fps(self, fps: float) -> None:
        """Playback sampling rate (docs/TIMING.md §5) -- never alters stored
        DMX values, only how often the player re-checks the timeline."""
        if fps <= 0:
            raise ValueError(f"fps must be > 0, got {fps}")
        self._fps = fps

    def set_loop(self, enabled: bool) -> None:
        self._loop = enabled

    @property
    def playing(self) -> bool:
        return self._timeline.playing

    @property
    def position_ns(self) -> int:
        return self._timeline.position_ns()

    # --- Internals -------------------------------------------------------- #

    def active_frame_index(self, position_ns: int) -> int | None:
        """Sample-and-hold (docs/SPECIFICATION.md §13): the most recent
        frame with timestamp <= position_ns."""
        if not self._timestamps:
            return None
        idx = bisect.bisect_right(self._timestamps, position_ns) - 1
        if idx < 0:
            idx = 0
        return idx

    async def _open_output(self) -> None:
        if self._output_protocol == "Art-Net":
            sender = ArtNetSender()
            await sender.start(interface_ip=self._output_interface_ip)
        elif self._output_protocol == "sACN":
            sender = SACNSender()
            await sender.start(interface_ip=self._output_interface_ip)
        else:
            raise ValueError(f"Unknown output protocol {self._output_protocol!r}")
        self._sender = sender

    def _destination_for_row(self, row: int) -> int:
        if self._universe_mapping is not None and row in self._universe_mapping:
            return self._universe_mapping[row]
        mapping = self._manifest.universes[row]
        if mapping.protocol == "Art-Net":
            return mapping.port_address()
        return mapping.universe

    async def _emit(self, frame: DMXFrame) -> None:
        assert self._sender is not None
        for row, universe in enumerate(frame.universes):
            dest = self._destination_for_row(row)
            data = universe.to_bytes()
            if self._output_protocol == "Art-Net":
                net, subnet, u = artnet_port_address_to_fields(dest)
                self._sender.send(
                    net=net, subnet=subnet, universe=u, data=data,
                    destination_ip=self._output_destination_ip or "255.255.255.255",
                    port=self._output_port or ARTNET_PORT,
                )
            else:
                self._sender.send(
                    universe=dest, dmx_data=data,
                    destination_ip=self._output_destination_ip,
                    priority=self._output_priority,
                    port=self._output_port or SACN_PORT,
                )

    async def _run_loop(self) -> None:
        while True:
            tick_interval = 1.0 / self._fps
            position = self._timeline.position_ns()
            reverse = self._timeline.speed < 0

            at_end = (not reverse and self._duration_ns > 0 and position >= self._duration_ns)
            at_start = (reverse and position <= 0)

            if at_end or at_start:
                boundary_ns = self._duration_ns if at_end else 0
                if self._loop:
                    # Reverse playback loops back to the end; forward loops
                    # back to the start (brief §22/§23). Emit the frame at
                    # the restart position immediately (continue, not sleep
                    # first) -- otherwise the first frame after every loop
                    # restart is silently skipped for one whole tick.
                    self._timeline.seek(0 if at_end else self._duration_ns)
                    self._last_sent_index = None
                    continue
                else:
                    idx = self.active_frame_index(boundary_ns)
                    if idx is not None and idx != self._last_sent_index:
                        await self._emit(self._frames[idx])
                    self._timeline.pause()
                    self._timeline.seek(boundary_ns)
                    return
            else:
                idx = self.active_frame_index(position)
                if idx is not None and idx != self._last_sent_index:
                    await self._emit(self._frames[idx])
                    self._last_sent_index = idx

            await asyncio.sleep(tick_interval)
