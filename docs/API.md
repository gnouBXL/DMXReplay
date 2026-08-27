# API.md — DMXReplay core engine API

Companion to brief §50–§53. The core engine (`src/dmxreplay/`) MUST NOT depend on any
GUI toolkit (see [CONTRIBUTING.md](../CONTRIBUTING.md)) — GUIs (Phase 5/6) and the CLI
(Phase 11, `dmxreplay-record`/`-play`/`-info`/`-convert`) are consumers of this API, not
the other way around. This keeps TouchDesigner or any other future host able to embed
the engine directly (brief §52).

Status: **§1–§3.6 below are implemented now (Phases 1–4)**. **§4–§6 are the target
interface for Phases 5–8** — documented here so downstream code (CLI, GUI, TD
integration) can be designed against a stable contract as those phases land, but the
`Recorder`/`Player` classes themselves do not exist in `src/` yet (they will be built
*on top of* the already-implemented §3.5/§3.6 network and codec/container layers);
treat §4–§6 as a specification, not a changelog entry.

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

## 4. `dmxreplay.recorder` — target interface (Phase 5)

```python
class Recorder:
    def add_source(self, protocol: Literal["Art-Net", "sACN"], interface: str) -> None: ...
    def start(self, output_path: str) -> None: ...
    def stop(self) -> None: ...
    def get_universes(self) -> list[UniverseStatus]: ...   # live status, brief §13/§28
    def get_status(self) -> RecorderStatus: ...            # duration, packet rate, dropped packets, file size, brief §28
```

`Recorder` is the sole owner of the write path: network listener(s) → DMX engine →
encoder → container writer. A GUI or CLI only ever calls these methods and reads
`RecorderStatus`; it never touches the network or encoder directly.

## 5. `dmxreplay.player` — target interface (Phase 6–9)

(Basic load/play/pause/seek/output can build directly on §3.6's `DMXReplayReader` plus
§3.5's `ArtNetSender`/`SACNSender` once a `Timeline`-driven loop wraps them; the
harder parts of this phase are audio/external-video sync, Phases 7–8.)

```python
class Player:
    def load(self, dmxr_path: str, external_video_path: str | None = None) -> None: ...
    def play(self) -> None: ...
    def pause(self) -> None: ...
    def stop(self) -> None: ...
    def seek(self, position_ns: int) -> None: ...
    def set_speed(self, speed: float) -> None: ...          # e.g. 1.0, -1.0 for reverse
    def set_fps(self, fps: float) -> None: ...              # playback sampling rate, TIMING.md §5
    def set_loop(self, enabled: bool) -> None: ...
    def set_output(self, protocol: Literal["Art-Net", "sACN"], **kwargs) -> None: ...
    def set_universe_mapping(self, mapping: dict[int, int]) -> None: ...  # output remap, brief §34, never mutates the loaded file
    def set_preview_mode(self, mode: Literal["raw", "rgb_led"]) -> None: ...  # brief §36, visualization only
```

`Player` reads a `Manifest` + decodes the video track via the engine's `dmxreplay.codec`
+ `dmxreplay.container` modules, drives everything from one `Timeline` (§2), and pushes
output through `dmxreplay.network.artnet` / `dmxreplay.network.sacn` (ARTNET.md,
SACN.md). External video playback goes through `dmxreplay.video`; audio through
`dmxreplay.audio`. Both are driven by the same `Timeline`, never their own clock
(TIMING.md §1).

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

## 7. CLI surface (target, Phase 11)

Thin wrappers over §4/§5, per brief §51:

```
dmxreplay-record --input artnet --interface eth0 --fps 30 --output show.dmxr
dmxreplay-play --input show.dmxr --output artnet --destination 192.168.1.100
dmxreplay-info show.dmxr
dmxreplay-convert <options>
```

`dmxreplay-info` prints the parsed manifest (§3) plus container-level facts (duration,
track codecs, file size) — useful standalone for debugging even before the recorder/
player exist, since it depends only on §1–§3.6 (already implemented: it can be built
directly on `DMXReplayReader.manifest`, §3.6).
