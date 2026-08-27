# Changelog

All notable changes to this project are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). DMXReplay is pre-1.0; the file
format and API may still change between entries.

## [Unreleased]

### Added — Phase 4: DMXReplay encoder/decoder (real Matroska + FFV1 container I/O)
- `src/dmxreplay/codec/pixels.py`: DMX universe <-> pixel row packing for both
  encodings (pure Python, no extra dependency): grayscale (1:1, 512 bytes/row) and
  rgb_packed (bgr0, 4 bytes/pixel -- see correction below).
- `src/dmxreplay/codec/frame_codec.py`: `DMXFrame` <-> list of pixel rows.
- `src/dmxreplay/codec/video_frame.py`: pixel rows <-> `av.VideoFrame`, handling
  libav plane stride/padding explicitly (queried at runtime, never assumed --
  confirmed empirically that both rgb24-shaped and bgr0 frames have non-trivial
  row padding that differs by width/format).
- `src/dmxreplay/container/writer.py` (`DMXReplayWriter`) and `reader.py`
  (`DMXReplayReader`): the real Matroska + FFV1 + manifest-attachment file I/O
  chosen in FORMAT-RESEARCH.md, via the optional `av` (PyAV) dependency. Manifest
  is embedded as a Matroska attachment (`add_attachment`/`stream.data`), fully
  in-process -- no `ffmpeg` subprocess needed for either reading or writing.
- Round-trip verified byte-for-byte lossless for every Phase 1 test vector (ramp,
  alternating, random, 128 universes, sparse), in both encodings, including exact
  reproduction of irregular (VFR) per-frame timestamps and correct handling of two
  source frames landing on the same output millisecond.
- **Two more measured findings, corrected before they became bugs:**
  1. FFV1 has no 8-bit packed 3-byte RGB pixel format -- only 4-byte `bgr0`/`bgra`.
     The Phase 0 benchmark's "RGB-packed" result was real (ffmpeg silently
     converted `rgb24`→`bgr0` under the hood) but the spec described the wrong
     on-disk byte layout; corrected in `SPECIFICATION.md` §5.2, `CONTAINER.md` §2,
     `FORMAT-RESEARCH.md` §3.1, and `pixels.py`.
  2. Passing `rate=` to `add_stream()` pins the video codec context's own internal
     `time_base` to `1/rate`, silently truncating finer per-frame timestamps onto
     that grid *inside the encoder* (deeper than the Phase 0 muxer-level frame-sync
     hazard) -- two frames 22ms apart at "30fps" collapsed onto the same output
     tick. Fixed by setting `stream.codec_context.time_base` directly instead;
     documented in `FORMAT-RESEARCH.md` §11, `TIMING.md` §3, `CONTAINER.md` §2.
- `pyproject.toml`: `av` moved into its own `codec` extra pulled in by `dev`
  (previously-listed `network` extra removed -- Art-Net/sACN are implemented from
  scratch, no third-party `sacn` package is used).

### Added — Phase 3: sACN / ANSI E1.31 network I/O
- `src/dmxreplay/network/sacn/packet.py`: `E131DataPacket` -- full root/framing/DMP
  layer parse and build (byte-exact, 638 bytes for a full 512-slot universe),
  start-code handling (`is_dmx_data`, non-null start codes preserved but not
  treated as DMX per SACN.md §3), Options bits (Preview_Data, Stream_Terminated,
  Force_Sync).
- `src/dmxreplay/network/sacn/listener.py`: `SACNListener` -- asyncio UDP listener,
  optional multicast group join per universe (`multicast_group_for_universe`,
  `239.255.hi.lo`), drops/logs malformed packets, tracks live per-universe
  `UniverseStatus` (packet rate, non-DMX count, source name/priority).
- `src/dmxreplay/network/sacn/sender.py`: `SACNSender` -- unicast or multicast
  output, per-universe wrapping sequence numbers.
- Tests: packet round-trip/malformed-rejection, and real UDP-loopback
  send/receive between an actual `SACNSender` and `SACNListener` (multicast
  loopback test skips gracefully if the sandbox has no multicast routing).

### Added — Phase 2: Art-Net 4 network I/O
- `src/dmxreplay/network/artnet/packet.py`: `ArtDmxPacket` -- byte-exact `OpDmx`
  parse and build (docs/ARTNET.md §4), with full validation (ID, OpCode, protocol
  version, Net range, declared-vs-actual length) raising
  `MalformedArtNetPacketError` rather than crashing on bad input.
- `src/dmxreplay/network/artnet/listener.py`: `ArtNetListener` -- asyncio UDP
  listener, drops/logs malformed packets, tracks live per-universe
  `UniverseStatus` (packet rate, source IP, channel count, last-packet time)
  for the recorder UI (brief §13/§28).
- `src/dmxreplay/network/artnet/sender.py`: `ArtNetSender` -- unicast/broadcast
  output with per-destination-universe wrapping sequence numbers (docs/ARTNET.md §6).
- Tests: packet round-trip/malformed-rejection (every validation rule exercised
  individually), and real UDP-loopback send/receive between an actual
  `ArtNetSender` and `ArtNetListener` (not mocked).
- Fixed two byte-offset documentation bugs found while implementing against
  `docs/ARTNET.md`/`docs/SACN.md`: Art-Net's `Physical` field is at byte 13, not
  12 (12 is `Sequence`); the sACN ACN Packet Identifier is 12 bytes, not 16.
  Also added a worked clarification (`docs/ARTNET.md` §1.1) that a
  console-displayed "Universe 17" is the flattened Port-Address, not the raw
  4-bit `Universe` field -- caught by the test suite's own sparse-universe
  vector during Phase 1 (`net=0, subnet=1, universe=1`, not `universe=17`).

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
Everything from Phase 5 onward (Recorder/Player GUIs, audio and external-video
synchronization, preview modes, CLI binaries, conformance suite). Tracked in
`README.md`'s roadmap table.
