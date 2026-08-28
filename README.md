# DMXReplay

DMXReplay is an open, documented format and toolset for treating **DMX lighting data as
time-based media**: recorded from a live Art-Net or sACN stream, stored losslessly inside
a standard video container, and replayed later with accurate timing — synchronized with
audio, with an external video file, and eventually with external timecode sources.

> **Status:** early development (V1, Phase 0–10 done: the core engine is
> feature-complete). Now extending into a cross-platform ecosystem (Windows/macOS
> desktop GUIs, Raspberry Pi appliance, smartphone remote control) — see
> [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the plan and current phase status.
> The format is not yet stable. See [CHANGELOG.md](CHANGELOG.md) and
> [docs/SPECIFICATION.md](docs/SPECIFICATION.md).

## Platform targets

V1 targets desktop Linux/macOS/Windows **and standalone operation on a Raspberry Pi 4
or 5** (headless, no GUI required) — see [docs/RASPBERRY_PI.md](docs/RASPBERRY_PI.md)
for the compatibility analysis and real (not simulated) decode/network throughput
measurements behind that claim.

## Why

Lighting shows are usually locked inside a specific console's proprietary show file.
DMXReplay instead represents the DMX state over time as a lossless, timestamped media
stream, using well-understood, widely supported media technology (a standard video
container + a lossless codec) as the storage layer. Any third-party developer should be
able to implement a compatible reader or writer from the public specification alone,
without needing this repository's source code.

## Core idea

```
                 DMX / Art-Net / sACN
                         │
                         ▼
                  DMXReplay Recorder
                         │
                         ▼
                 Lossless DMX Video (.dmxr)
                         │
                  +------+------+
                  │             │
                DMX           Audio
                  │
                  ▼
             DMXReplay Player
                  │
          ┌───────┴────────┐
          ▼                ▼
       Art-Net            sACN
          │                │
          └───────┬────────┘
                  ▼
             Lighting rig
```

One video sample = one DMX state at a precise point in time. The image is not meant to be
watched — it's a machine-readable, lossless encoding of DMX channel values, stored using
standard container/codec technology so existing tools (ffmpeg, VLC, TouchDesigner, etc.)
can inspect the file even before a dedicated DMXReplay tool exists.

The **logical format** (universes, channels, timestamps, metadata) is specified
independently from the **physical media encoding** (which container/codec actually store
the bytes) — see [docs/SPECIFICATION.md](docs/SPECIFICATION.md) and
[FORMAT-RESEARCH.md](FORMAT-RESEARCH.md) for the benchmark behind that choice.

## Repository layout

```
/DMXReplay
├── src/dmxreplay/     Core Python engine (network, codec, container, clock, metadata, ...)
├── tests/             Unit and round-trip tests
├── test-vectors/      Official, generated test files (see docs/SPECIFICATION.md §19)
├── benchmark/         Format research benchmark harness (Phase 0)
├── docs/
│   ├── SPECIFICATION.md   Formal DMXReplay format specification
│   ├── ARTNET.md          Art-Net 4 addressing and mapping notes
│   ├── SACN.md            sACN / ANSI E1.31 notes
│   ├── TIMING.md          Timestamps, VFR, master timeline
│   ├── CONTAINER.md       Physical container/codec details
│   ├── API.md             Core engine API (Recorder / Player / Clock)
│   └── RASPBERRY_PI.md    Raspberry Pi 4/5 compatibility analysis and benchmarks
├── FORMAT-RESEARCH.md     Phase 0 benchmark results and recommendation
├── CHANGELOG.md
├── CONTRIBUTING.md
└── LICENSE (MIT)
```

## Development roadmap

DMXReplay is built in phases (tracked in [CHANGELOG.md](CHANGELOG.md)):

| Phase | Scope | Status |
|---|---|---|
| 0 | Format research & benchmark (container/codec choice) | ✅ |
| 1 | DMX core: data model, master clock, metadata schema | ✅ |
| 2 | Art-Net input/output | ✅ |
| 3 | sACN / E1.31 input/output | ✅ |
| 4 | DMXReplay encoder (DMX → video → lossless container) | ✅ |
| 5 | Recorder core engine + `dmxreplay-record` CLI (headless) | ✅ |
| 6 | Player core engine + `dmxreplay-play` CLI (load/play/pause/seek/loop/speed, headless) | ✅ |
| 7 | Audio synchronization | ✅ |
| 8 | External video synchronization | ✅ |
| 9 | Preview modes (raw DMX / RGB LED) | ✅ |
| 10 | Conformance test suite | ✅ |

With Phase 10 done, the core engine (Reader, Recorder, Player, and the full V1.0 file
format) is feature-complete and has an explicit conformance test suite
(`tests/test_conformance.py`, [`docs/SPECIFICATION.md`](docs/SPECIFICATION.md) §19–§20)
validating all three conformance roles and all 10 official test vectors.

### Post-V1: cross-platform extension

DMXReplay is being extended into a cross-platform ecosystem — Windows/macOS desktop
GUIs, a Raspberry Pi headless appliance, and smartphone remote control — on top of this
same core engine and `.dmxr` format, unchanged. See
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the audit and phased plan.

| Phase | Scope | Status |
|---|---|---|
| A | Desktop GUIs (`dmxreplay.ui`, Tkinter) + Windows/macOS packaging | ✅ GUI + Linux-verified packaging; Windows/macOS build scripts written, unverified on real hardware |
| B | Raspberry Pi ARM64/headless foundation | ✅ config loader + systemd unit verified; real Pi hardware unverified |
| C | Long-running commandable Player/Recorder service | ✅ |
| D | Control API (HTTP + WebSocket) | ✅ |
| E | Raspberry Pi configuration + discovery | planned |
| F | Mobile remote controller | planned |
| G | Show management + file transfer | planned |
| H | Performance/hardware validation | planned |
| I | Final packaging + documentation | planned |

`dmxreplay.ui` provides `DMXReplay Player`/`DMXReplay Recorder` desktop GUI apps
(`dmxreplay-player-gui`/`dmxreplay-recorder-gui`), built on Tkinter (Python's own
standard-library GUI toolkit — no new pip dependency) with all DMX/network logic kept
in toolkit-independent view-models per [CONTRIBUTING.md](CONTRIBUTING.md)'s
GUI-independence rule. See [docs/BUILD_AND_DISTRIBUTION.md](docs/BUILD_AND_DISTRIBUTION.md)
for packaging status per platform.

## Getting started (development)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## Command-line usage

```bash
# Record a live Art-Net stream (discovers universes for 3s, then records until Ctrl+C)
dmxreplay-record --input artnet --interface 0.0.0.0 --fps 30 --output show.dmxr

# Play it back over Art-Net, looping, to a specific console/node
dmxreplay-play show.dmxr --output artnet --destination 192.168.1.100 --loop

# Inspect a file's manifest without playing it
dmxreplay-info show.dmxr

# Headless appliance mode: everything from a config file (docs/RASPBERRY_PI_INSTALL.md)
dmxreplay-play --headless --config /etc/dmxreplay/player.toml
```

All three run headless — no GUI dependency (`dmxreplay-play --headless` is accepted
for config-file/auto-start compatibility, see
[docs/RASPBERRY_PI.md](docs/RASPBERRY_PI.md) §13-§14; the CLI never imports a GUI
toolkit either way).

## Desktop GUI apps

```bash
dmxreplay-player-gui      # DMXReplay Player
dmxreplay-recorder-gui    # DMXReplay Recorder
```

See [docs/API.md](docs/API.md) §8 for what they cover and
[docs/BUILD_AND_DISTRIBUTION.md](docs/BUILD_AND_DISTRIBUTION.md) for packaging them
into standalone Windows/macOS apps that don't need Python installed.

## Network Control API

```bash
dmxreplay-server --shows-dir /var/lib/dmxreplay/shows --enable-recorder
```

Runs an HTTP + WebSocket API for remote control (play/pause/seek/next/previous/record/
status) — the foundation the smartphone remote controller (Phase F) talks to. The
device's own master timeline always drives real-time playback; a connected client
never becomes part of that loop, and playback continues unaffected if it disconnects.
See [docs/API.md](docs/API.md) §10 for the Python side and
[docs/MOBILE_API.md](docs/MOBILE_API.md) for the full wire protocol.

## License

MIT — see [LICENSE](LICENSE).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).
