"""Player core engine. See docs/API.md §5, docs/TIMING.md, brief §30-§33.

GUI-independent (CONTRIBUTING.md): a CLI or GUI only ever calls the methods
below; the playback loop, master timeline, and network output all live here,
enabling `dmxreplay-play --headless` without dmxreplay.ui
(docs/RASPBERRY_PI.md §12/§13).

Scope of this pass: DMX playback and output (Art-Net/sACN), audio playback
(Phase 7), and external video (Phase 8), all driven by one Timeline
(docs/TIMING.md §1-§2), with seek/play/pause/stop/loop/speed/fps. Preview
modes (Phase 9) are not implemented here -- API.md documents them as a
later-phase addition to this same class, not a reason to stub them now.

Audio playback is deliberately simple: on play()/seek(), the whole
already-decoded PCM buffer (from `DMXReplayReader.read_audio_pcm()`) is
handed to an `AudioSink` from the point matching the current Timeline
position; the sink's own hardware clock then paces actual sound output.
Timeline is not disciplined against that hardware clock afterward -- see
dmxreplay.audio's module docstring for why that's an accepted V1 limitation
rather than an oversight.

External video is never embedded in the .dmxr file (docs/CONTAINER.md §7)
-- `load_external_video()` opens a separate file via `ExternalVideoReader`
and, on every playback tick, presents the frame at the current Timeline
position (sample-and-hold, same semantics as DMX) to a `VideoSink`,
whenever it's a different frame than last tick.
"""
from __future__ import annotations

import asyncio
import bisect
from typing import Literal

from ..audio import AudioSink, NullAudioSink
from ..clock import ClockProvider, Timeline
from ..container import DMXReplayReader
from ..dmx import DMXFrame
from ..metadata import Manifest, artnet_port_address_to_fields
from ..network.artnet import ARTNET_PORT, ArtNetSender
from ..network.sacn import SACN_PORT, SACNSender
from ..preview import PreviewMode, compute_preview
from ..video import ExternalVideoReader, NullVideoSink, VideoSink

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

        self._audio_sink: AudioSink = NullAudioSink()
        self._audio_pcm: bytes | None = None
        self._audio_sample_rate = 0
        self._audio_channels = 0
        self._audio_sample_width = 2
        self._audio_loaded_into_sink = False

        self._video_sink: VideoSink = NullVideoSink()
        self._video_reader: ExternalVideoReader | None = None
        self._last_presented_video_ns: int | None = None

        self._preview_mode: PreviewMode = "raw"

    # --- Loading -------------------------------------------------------- #

    def load(self, dmxr_path: str) -> None:
        with DMXReplayReader(dmxr_path) as reader:
            self._manifest = reader.manifest
            self._frames = list(reader.read_frames())
            if reader.has_audio:
                self._audio_pcm, self._audio_sample_rate, self._audio_channels, \
                    self._audio_sample_width = reader.read_audio_pcm()
            else:
                self._audio_pcm = None
        self._timestamps = [f.timestamp_ns for f in self._frames]
        self._duration_ns = self._timestamps[-1] if self._timestamps else 0
        self._fps = self._manifest.fps
        self._timeline.seek(0)
        self._last_sent_index = None
        self._audio_loaded_into_sink = False
        if self._video_reader is not None:
            self._video_reader.close()
            self._video_reader = None
        self._last_presented_video_ns = None

    def load_external_video(self, video_path: str) -> None:
        """Load a conventional video file to play alongside the DMX show,
        synchronized against the same Timeline (docs/CONTAINER.md §7: never
        embedded in the .dmxr; a completely separate file). Call after
        load(). The external video's own duration does not have to match
        the DMX show's -- SPECIFICATION.md doesn't require it, and
        `_present_video_if_due()` simply has nothing left to show once its
        reader runs out of frames for the current position."""
        if self._video_reader is not None:
            self._video_reader.close()
        self._video_reader = ExternalVideoReader(video_path)
        self._last_presented_video_ns = None

    @property
    def has_external_video(self) -> bool:
        return self._video_reader is not None

    def set_video_sink(self, sink: VideoSink | None) -> None:
        """Configure where decoded external video frames are presented.
        None resets to NullVideoSink (the default -- safe/no-op)."""
        self._video_sink = sink if sink is not None else NullVideoSink()

    def set_preview_mode(self, mode: PreviewMode) -> None:
        """Select how current_preview() reconstructs a row for visualization
        (brief §36: "Raw DMX" or "RGB Pixels"). Purely cosmetic -- never
        affects what's stored or sent to Art-Net/sACN output
        (docs/SPECIFICATION.md §5.3)."""
        self._preview_mode = mode

    def current_preview(self, row: int):
        """The current DMX state at `row`, transformed per the configured
        preview mode (dmxreplay.preview). Returns None if nothing is loaded
        or `row` isn't active at the current position."""
        idx = self.active_frame_index(self._timeline.position_ns())
        if idx is None:
            return None
        universe = self._frames[idx].universes[row]
        return compute_preview(universe, self._preview_mode)

    @property
    def manifest(self) -> Manifest | None:
        return self._manifest

    @property
    def duration_ns(self) -> int:
        return self._duration_ns

    @property
    def has_audio(self) -> bool:
        return self._audio_pcm is not None

    def set_audio_sink(self, sink: AudioSink | None) -> None:
        """Configure where decoded audio is played. None resets to
        NullAudioSink (the default -- safe/no-op, used automatically for
        files with no audio track or when nothing else is configured)."""
        self._audio_sink = sink if sink is not None else NullAudioSink()
        self._audio_loaded_into_sink = False

    def _ensure_audio_loaded(self) -> None:
        if self._audio_pcm is not None and not self._audio_loaded_into_sink:
            self._audio_sink.load(
                self._audio_pcm, self._audio_sample_rate,
                self._audio_channels, self._audio_sample_width,
            )
            self._audio_loaded_into_sink = True

    def _start_audio_at(self, position_ns: int) -> None:
        if self._audio_pcm is None:
            return
        self._ensure_audio_loaded()
        start_sample = max(0, int(position_ns * self._audio_sample_rate / 1_000_000_000))
        self._audio_sink.play(start_sample)

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
        self._sync_audio_to_playback_state()

    def pause(self) -> None:
        self._timeline.pause()
        self._audio_sink.stop()

    async def stop(self) -> None:
        self._timeline.pause()
        self._timeline.seek(0)
        self._last_sent_index = None
        self._last_presented_video_ns = None
        self._audio_sink.stop()
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
        self._last_presented_video_ns = None  # force re-present, same reason
        self._sync_audio_to_playback_state()

    def set_speed(self, speed: float) -> None:
        self._speed = speed
        if self._timeline.playing:
            self._timeline.play(speed=speed)
        self._sync_audio_to_playback_state()

    def _sync_audio_to_playback_state(self) -> None:
        """Re-cue the audio sink to match the current Timeline position
        whenever play/seek/speed changes it -- one master timeline drives
        both (docs/TIMING.md §1). AudioSink's contract is forward-only
        real-time playback (see dmxreplay.audio), so audio only actually
        plays at speed == 1.0; any other speed (including reverse) stops it
        rather than producing incorrect/garbled sound -- a documented V1
        limitation, not an oversight."""
        if self._audio_pcm is None:
            return
        if self._timeline.playing and self._speed == 1.0:
            self._start_audio_at(self._timeline.position_ns())
        else:
            self._audio_sink.stop()

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

    def _present_video_if_due(self, position_ns: int) -> None:
        if self._video_reader is None:
            return
        frame = self._video_reader.frame_at(position_ns)
        if frame is not None and frame.timestamp_ns != self._last_presented_video_ns:
            self._video_sink.present(frame)
            self._last_presented_video_ns = frame.timestamp_ns

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
                    self._last_presented_video_ns = None
                    continue
                else:
                    idx = self.active_frame_index(boundary_ns)
                    if idx is not None and idx != self._last_sent_index:
                        await self._emit(self._frames[idx])
                    self._present_video_if_due(boundary_ns)
                    self._timeline.pause()
                    self._timeline.seek(boundary_ns)
                    return
            else:
                idx = self.active_frame_index(position)
                if idx is not None and idx != self._last_sent_index:
                    await self._emit(self._frames[idx])
                    self._last_sent_index = idx
                self._present_video_if_due(position)

            await asyncio.sleep(tick_interval)
