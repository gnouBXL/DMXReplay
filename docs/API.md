# API.md — DMXReplay core engine API

Companion to brief §50–§53. The core engine (`src/dmxreplay/`) MUST NOT depend on any
GUI toolkit (see [CONTRIBUTING.md](../CONTRIBUTING.md)) — GUIs (still planned) and the
CLI (`dmxreplay-record`/`-play`/`-info`, implemented; `-convert`, stubbed) are
consumers of this API, not the other way around. This is what makes `dmxreplay-play
--headless` on a Raspberry Pi possible without `dmxreplay.ui`
([docs/RASPBERRY_PI.md](RASPBERRY_PI.md) §12), and keeps TouchDesigner or any other
future host able to embed the engine directly (brief §52).

Status: **§1–§7 below are all implemented (Phases 1–7)**, except `dmxreplay.ui` (no
GUI yet — the engine and CLI don't need it). External video (Phase 8) and preview
modes (Phase 9) are the remaining engine work, layered onto `Player` without
changing anything documented here.

## 1. `dmxreplay.dmx` — DMX data model (implemented)

```python
Channel = int  # 0-255; validated at construction sites, not a wrapper class (hot path)

@dataclass(frozen=True)
class Universe:
    channels: tuple[int, ...]  # length always == 512, each 0-255

@dataclass(frozen=True)
class DMXFrame:
    timestamp_ns: int          # capture-timeline timestamp, SPECIFICATION.md §11
    universes: tuple[Universe, ...]   # index == row (SPECIFICATION.md §7); row->source mapping lives in metadata, not here
```

`DMXFrame` intentionally carries no protocol/addressing information — that association
is the job of the metadata layer (`dmxreplay.metadata`), keeping the DMX model usable
independent of which protocol produced it (Art-Net, sACN, or a synthetic test vector).

## 2. `dmxreplay.clock` — master timeline (implemented)

```python
class MasterClock:
    def now_ns(self) -> int: ...          # monotonic capture-side timestamp source (TIMING.md §3)

class Timeline:
    """Playback-side position tracker; separate from MasterClock, which is
    specifically the capture-side monotonic source. See TIMING.md §2."""
    def position_ns(self) -> int: ...
    def seek(self, position_ns: int) -> None: ...
    def play(self, speed: float = 1.0) -> None: ...
    def pause(self) -> None: ...
```

## 3. `dmxreplay.metadata` — manifest model (implemented)

```python
@dataclass
class UniverseMapping:
    row: int
    protocol: Literal["Art-Net", "sACN"]
    universe: int
    net: int | None = None          # Art-Net only
    subnet: int | None = None       # Art-Net only
    source_ip: str | None = None

@dataclass
class Manifest:
    format: Literal["DMXReplay"]
    version: str
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
    audio: dict | None = None
    external_video_ref: str | None = None
    show_name: str | None = None
    description: str | None = None
    container_version: str | None = None

    def to_json(self) -> str: ...
    @classmethod
    def from_json(cls, data: str) -> "Manifest": ...   # ignores unknown fields, SPECIFICATION.md §10.4
```

Validated against [`schema.json`](../src/dmxreplay/metadata/schema.json) (JSON Schema).

## 3.5 `dmxreplay.network` — Art-Net / sACN I/O (implemented, Phase 2–3)

```python
# dmxreplay.network.artnet
class ArtDmxPacket:                 # parse()/to_bytes(), full validation -- ARTNET.md §4
    ...
class ArtNetListener:
    async def start(self, interface_ip: str, port: int = ARTNET_PORT) -> None: ...
    def stop(self) -> None: ...
    def get_universes(self) -> list[UniverseStatus]: ...
class ArtNetSender:
    async def start(self, interface_ip: str) -> None: ...
    def send(self, net: int, subnet: int, universe: int, data: bytes,
              destination_ip: str) -> ArtDmxPacket: ...

# dmxreplay.network.sacn
class E131DataPacket:               # parse()/to_bytes(), full root/framing/DMP -- SACN.md §2
    ...
class SACNListener:
    async def start(self, interface_ip: str, multicast_universes: list[int] | None = None) -> None: ...
class SACNSender:
    def send(self, universe: int, dmx_data: bytes, destination_ip: str | None = None) -> E131DataPacket: ...
```

Both listeners take an `on_packet` callback and expose `get_universes()` (live
per-universe status: packet rate, source IP, channel count — brief §13/§28), matching
what `Recorder` (§4) will aggregate across protocols. See [ARTNET.md](ARTNET.md) and
[SACN.md](SACN.md) for wire format and validation detail.

## 3.6 `dmxreplay.codec` / `dmxreplay.container` — DMX ⇄ file (implemented, Phase 4)

```python
# dmxreplay.codec (pure Python: pixels.py, frame_codec.py; PyAV-dependent: video_frame.py)
def dmxframe_to_pixel_rows(frame: DMXFrame, encoding: Literal["grayscale", "rgb_packed"]) -> list[bytes]: ...
def pixel_rows_to_dmxframe(rows: list[bytes], timestamp_ns: int, encoding: str) -> DMXFrame: ...

# dmxreplay.container (requires the optional `av` / PyAV dependency)
class DMXReplayWriter:
    def __init__(self, path: str, manifest: Manifest) -> None: ...   # manifest fully known up front -- see CONTAINER.md
    def write_frame(self, frame: DMXFrame) -> None: ...
    def close(self) -> None: ...

class DMXReplayReader:
    def __init__(self, path: str) -> None: ...   # raises NotADMXReplayFileError if no manifest attachment
    manifest: Manifest
    def read_frames(self) -> Iterator[DMXFrame]: ...
    def close(self) -> None: ...
```

Both are context managers (`with DMXReplayWriter(...) as w:`). `Recorder.start()` (§4)
will construct a `DMXReplayWriter` once universe discovery has fixed the manifest;
`Player.load()` (§5) will construct a `DMXReplayReader`. Round-trip losslessness (every
official test vector, both encodings) is verified in `tests/test_container_roundtrip.py`
against the real Matroska+FFV1 container chosen in FORMAT-RESEARCH.md — not mocked.

## 4. `dmxreplay.recorder` — implemented (Phase 5)

```python
class Recorder:
    def __init__(self, clock: MasterClock | None = None) -> None: ...
    async def add_source(
        self, protocol: Literal["Art-Net", "sACN"], interface_ip: str,
        port: int | None = None, multicast_universes: list[int] | None = None,
    ) -> None: ...
    def get_universes(self) -> list[RowInfo]: ...          # live discovery status, brief §13/§28
    def start(self, output_path: str, *, encoding: Encoding = "grayscale", fps: float = 30.0) -> None: ...
    def stop(self) -> None: ...
    def get_status(self) -> RecorderStatus: ...            # duration, packet counts, dropped/malformed, file size
    async def close(self) -> None: ...                      # stops recording (if active) and every listener
```

`Recorder` is the sole owner of the write path: one or more `ArtNetListener`/
`SACNListener` (§3.5) feed a `DMXEngine` (`dmxreplay.dmx.DMXEngine` — the "DMX Engine"
box in the brief's architecture diagram, brief §49), which `start()` freezes into a
`Manifest` and `DMXReplayWriter` (§3.6) once universe discovery is done. A CLI or GUI
only ever calls these methods and reads `RowInfo`/`RecorderStatus`; it never touches
the network or encoder directly. `dmxreplay-record` (§7) is a thin wrapper over this.

## 5. `dmxreplay.player` — implemented (Phase 6-7: DMX + audio)

```python
class Player:
    def __init__(self, clock_provider: ClockProvider | None = None) -> None: ...
    def load(self, dmxr_path: str) -> None: ...
    def set_output(
        self, protocol: Literal["Art-Net", "sACN"], interface_ip: str = "0.0.0.0",
        destination_ip: str | None = None, port: int | None = None, priority: int = 100,
    ) -> None: ...
    def set_universe_mapping(self, mapping: dict[int, int] | None) -> None: ...  # output remap, brief §34, never mutates the loaded file
    def set_audio_sink(self, sink: AudioSink | None) -> None: ...  # None -> NullAudioSink (default)
    async def play(self, speed: float | None = None) -> None: ...
    def pause(self) -> None: ...
    async def stop(self) -> None: ...
    def seek(self, position_ns: int) -> None: ...
    def set_speed(self, speed: float) -> None: ...          # e.g. 1.0, -1.0 for reverse
    def set_fps(self, fps: float) -> None: ...              # playback sampling rate, TIMING.md §5
    def set_loop(self, enabled: bool) -> None: ...
    manifest: Manifest | None                                # property
    duration_ns: int                                          # property
    position_ns: int                                           # property
    has_audio: bool                                             # property
```

`Player` decodes every frame via `DMXReplayReader` (§3.6) at `load()` time, drives an
internal `Timeline` (§2), and on every tick (rate = `set_fps()`, default the file's own
nominal `fps`) emits the sample-and-hold-current frame (SPECIFICATION.md §13) via
`ArtNetSender`/`SACNSender` (§3.5) if it has changed since the last tick. Loading
decodes the whole file (DMX **and** audio, if present) into memory up front (simple and
correct; a future streaming/seek-on-demand mode is a documented candidate optimization,
not yet needed at V1 scale — see `docs/RASPBERRY_PI.md` §9). Audio playback
(`play()`/`seek()`/`set_speed()`) re-cues the configured `AudioSink` (below) to match
the `Timeline`'s position — one master timeline drives both, never an independent audio
clock (`docs/TIMING.md` §1, `SPECIFICATION.md` §14). `AudioSink` is forward-only, so
non-1.0 speeds (including reverse) stop audio rather than play it incorrectly.
`set_preview_mode()` (brief §36) and `external_video_path` (brief §19, Phase 8) are
**not yet implemented** — left off this class until their phases land rather than
stubbed. `dmxreplay-play` (§7) is a thin wrapper over this.

### `dmxreplay.audio` — implemented (Phase 7)

```python
class AudioSink(Protocol):
    def load(self, pcm_data: bytes, sample_rate: int, channels: int, sample_width: int) -> None: ...
    def play(self, start_sample: int = 0) -> None: ...
    def stop(self) -> None: ...

class NullAudioSink(AudioSink): ...          # default; always available, does nothing
class WavFileAudioSink(AudioSink): ...       # writes decoded PCM to a .wav file; for headless verification/tests
class SoundDeviceAudioSink(AudioSink): ...   # real hardware output via the optional `sounddevice` dependency
```

`SoundDeviceAudioSink.play()` raises `AudioDeviceUnavailableError` up front if no
output device is present, rather than failing deep inside PortAudio. **Not exercised
against real audio hardware in this project's own development environment** — see
`docs/RASPBERRY_PI.md`'s audio note; the sync *trigger logic* (Player calling
load/play/stop at the right times with the right sample offsets) is real-tested against
this protocol via a recording test double, which is a meaningfully different claim from
"verified to produce correct sound," and this document doesn't conflate the two.

## 6. `dmxreplay.clock.ClockProvider` — future timecode sources (documented, not implemented)

```python
class ClockProvider(Protocol):
    def position_ns(self) -> int: ...

class InternalClockProvider(ClockProvider): ...   # V1's only implementation
# Future: LTCClockProvider, MTCClockProvider, ArtNetTimeCodeClockProvider (TIMING.md §7)
```

`Timeline` (§2) is constructed with a `ClockProvider`; V1 always uses
`InternalClockProvider`. This is the seam brief §40 asks for — adding a new provider
later should not require changing `Player`, `Recorder`, or the DMX/audio/video output
paths, only supplying a different `ClockProvider` to `Timeline`.

## 7. CLI surface — implemented (Phases 5-7)

Thin wrappers over §4/§5, per brief §51 (`src/dmxreplay/cli/{record,play,info,convert}.py`):

```
dmxreplay-record --input artnet --interface 0.0.0.0 --fps 30 --output show.dmxr
dmxreplay-play show.dmxr --output artnet --destination 192.168.1.100 --loop
dmxreplay-info show.dmxr [--frames]
dmxreplay-convert show.dmxr show_with_audio.dmxr --add-audio song.wav
```

`dmxreplay-convert` implements exactly one operation, `--add-audio` (`docs/CONTAINER.md`
§3 explains why: an audio track can only be muxed in from a complete source file, at
container-construction time, so "attach audio after the fact" is naturally a convert
operation rather than something `Recorder` can do mid-recording). Other conversions
brief §51 gestures at (re-encoding, universe remapping into a new file, fps change)
remain unimplemented — never specified, so not guessed at.

`dmxreplay-record` runs a discovery phase (`--discovery-seconds`, default 3s) before
freezing the universe set and starting to write, matching the brief §28 recorder GUI's
discover-then-checkbox-then-record flow; stops on Ctrl+C/SIGTERM.
`dmxreplay-play` accepts `--headless` (accepted for compatibility with the auto-start
config shape in `docs/RASPBERRY_PI.md` §14 — this CLI never imports a GUI toolkit, so
behavior doesn't actually change with or without the flag) plus `--loop`/`--speed`/
`--seek`/`--fps`; it plays straight through until the file ends (non-looping) or it's
interrupted (looping). Interactive transport control while running (pause/seek from
outside the process) is not implemented yet — `docs/RASPBERRY_PI.md` §13 explains why
that's deferred rather than guessed at now. `dmxreplay-info` prints the parsed
manifest as JSON; `--frames` additionally lists every frame's timestamp to stderr.
