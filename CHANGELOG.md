# Changelog

All notable changes to this project are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). DMXReplay is pre-1.0; the file
format and API may still change between entries.

## [Unreleased]

### Added — Phase 0: Format research
- `benchmark/format_benchmark.py`: real benchmark harness (not simulated) comparing
  Matroska / MOV / MP4 containers with FFV1 / Ut Video / HuffYUV / rawvideo, and
  grayscale vs. RGB-packed pixel representations, on synthetic DMX-shaped test patterns.
- `FORMAT-RESEARCH.md`: measured results and the justified container/codec
  recommendation for V1 (see document for numbers).

### Added — Phase 1: DMX core
- `src/dmxreplay/dmx`: DMX data model — `Channel` (uint8, 0-255), `Universe` (512
  channels), `DMXFrame` (a full snapshot across active universes at one timestamp).
- `src/dmxreplay/clock`: `MasterClock`, a monotonic high-resolution clock abstraction
  that is the single source of truth for "what time is it" across DMX/audio/video
  subsystems (per spec §20/§62); capture-timeline vs. playback-timeline distinction.
- `src/dmxreplay/metadata`: versioned metadata model (dataclasses) + JSON Schema
  (`schema.json`) for the embedded DMXReplay manifest, with forward-compatible
  "unknown fields are ignored" semantics.
- `test-vectors/generate_test_vectors.py`: generators for the Ramp, Alternating,
  Random, Multiple-universes and Sparse-universes test vectors (spec §19, tests 1-5).
- Unit tests for the DMX model, clock and metadata round-trip.

### Added — Documentation
- `docs/SPECIFICATION.md`: DMXReplay Specification 1.0 (draft) — terminology, container
  requirements, video representation, pixel encoding, DMX/universe/Art-Net/sACN mapping,
  metadata schema, timestamp format, VFR behavior, audio sync, error handling,
  versioning, security considerations, test vectors, conformance levels.
- `docs/ARTNET.md`, `docs/SACN.md`, `docs/TIMING.md`, `docs/CONTAINER.md`, `docs/API.md`.
- `README.md`, `CONTRIBUTING.md`, `LICENSE` (MIT).

### Not yet implemented
Everything from Phase 2 onward (Art-Net/sACN network I/O, the actual DMXReplay
encoder/decoder, Recorder/Player GUIs, audio and external-video synchronization, preview
modes, CLI binaries, conformance suite). Tracked in `README.md`'s roadmap table.
