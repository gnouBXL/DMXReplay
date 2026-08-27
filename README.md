# DMXReplay

DMXReplay is an open, documented format and toolset for treating **DMX lighting data as
time-based media**: recorded from a live Art-Net or sACN stream, stored losslessly inside
a standard video container, and replayed later with accurate timing — synchronized with
audio, with an external video file, and eventually with external timecode sources.

> **Status:** early development (V1, Phase 0/1 of the roadmap below). The format is not
> yet stable. See [CHANGELOG.md](CHANGELOG.md) and [docs/SPECIFICATION.md](docs/SPECIFICATION.md).

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
│   └── API.md             Core engine API (Recorder / Player / Clock)
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
| 5 | Recorder GUI | planned |
| 6 | Player GUI (load/play/pause/seek/loop/speed) | planned |
| 7 | Audio synchronization | planned |
| 8 | External video synchronization | planned |
| 9 | Preview modes (raw DMX / RGB LED) | planned |
| 10 | Conformance test suite | planned |

## Getting started (development)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## License

MIT — see [LICENSE](LICENSE).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).
