# Changelog

All notable changes to this project are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). DMXReplay is pre-1.0; the file
format and API may still change between entries.

## [Unreleased]

### Added — Phase 9: Preview modes (raw DMX / RGB LED)
- `src/dmxreplay/preview`: `raw_channel_grid(universe)` (identity — the 512 raw
  channel values, unchanged), `rgb_led_pixels(universe)` (groups channels 3-at-a-time
  into `(R, G, B)` pixels, reusing the same grouping as the RGB-packed encoding in
  `SPECIFICATION.md` §5.2; 512 isn't divisible by 3, so the final pixel's missing
  component(s) are zero-padded rather than wrapping into the next universe or reading
  out of bounds — covered by a dedicated test), `rgb_hex(pixel)` (`"#RRGGBB"` from raw
  byte values — brief §37 explicitly forbids a gamma/dimming curve here, and the test
  suite checks that literal values map 1:1), and `compute_preview(universe, mode)` to
  dispatch between them. Every function is pure and read-only: none can mutate a
  `Universe` or influence what's stored/output (brief §8's "MUST NOT modify stored DMX
  values"), verified with a real record→decode round trip that computes both preview
  modes on a decoded frame and asserts it's byte-identical to what was written.
- `Player` gained `set_preview_mode(mode)` and `current_preview(row)`, which read
  whichever `Universe` is currently active at the given row under the existing
  sample-and-hold playback state and hand it to `compute_preview()` — purely a read
  path, never feeding back into playback, network output, or recording (asserted by a
  test that calls it repeatedly and checks playback position is unaffected).
- No GUI renders these values yet — that's `dmxreplay.ui`, out of scope for this
  headless environment; `current_preview()` is usable today from a script or a future
  GUI layer alike.
- `docs/API.md` updated with a new `dmxreplay.preview` subsection.

### Added — Phase 8: External video synchronization
- `src/dmxreplay/video`: `ExternalVideoReader` (opens a separate conventional video
  file via PyAV -- MP4/MOV/MKV etc., never embedded in `.dmxr`, `docs/CONTAINER.md`
  §7) with `frame_at(position_ns)` serving the sample-and-hold-current frame for any
  timeline position, seeking efficiently (only re-seeks on backward jumps; forward
  requests just keep decoding). `VideoSink` protocol, `NullVideoSink` (default),
  `PPMFileVideoSink` (writes each presented frame as a real, headless-verifiable
  image -- no display or extra dependency needed).
- `Player` gained `load_external_video()`, `set_video_sink()`, and
  `has_external_video`; the playback loop now presents the current external-video
  frame on every tick whenever it changes, driven by the same `Timeline` as DMX and
  audio (`docs/TIMING.md` §1) -- confirmed by real tests using an actual encoded
  H.264/MP4 test video, not a synthetic proxy.
- **One real bug found and fixed by this phase's tests, not by inspection**: libav
  reuses/overwrites its internal decoded-frame buffers across successive `decode()`
  calls. `ExternalVideoReader.frame_at()`'s forward-scanning loop was holding a live
  `av.VideoFrame` reference across multiple `next()` calls while looking for the
  right frame, so the final "selected" frame's pixel data had often already been
  silently overwritten by a *later* frame decoded during the same scan by the time it
  was converted -- while its *timestamp* (read earlier) stayed correct, making the
  bug easy to miss without asserting on actual pixel content. Fixed by converting
  every candidate frame to an owned buffer immediately upon decoding it.
- No on-screen/display video sink is implemented — this project's environment is
  headless with no display attached, so one can't be built *or verified* here;
  `docs/RASPBERRY_PI.md` §8 also notes `ExternalVideoReader` currently decodes in
  software only (hardware-accelerated decode on a real Pi is an open follow-up, not
  a DMXReplay format/API change either way).
- `docs/API.md`, `docs/RASPBERRY_PI.md` §8/§10 updated to match.

### Added — Phase 7: Audio synchronization
- `src/dmxreplay/audio`: `AudioSink` protocol, `NullAudioSink` (default, no-op),
  `WavFileAudioSink` (writes decoded PCM to a .wav -- for headless verification and
  tests, no hardware needed), `SoundDeviceAudioSink` (real output via the optional
  `sounddevice`/PortAudio dependency; raises `AudioDeviceUnavailableError` up front
  when no device is present rather than failing deep inside PortAudio). No audio
  hardware exists in this project's development environment, so `SoundDeviceAudioSink`
  is real code, real-tested for correct error behavior in that environment, but not
  verified against actual sound output -- documented as such rather than glossed over.
- `DMXReplayWriter` gained an optional `audio_path` constructor parameter: the whole
  source audio file is decoded, resampled, and re-encoded to AAC (48kHz, mono/stereo),
  and muxed in immediately. `DMXReplayReader` gained `has_audio` and
  `read_audio_pcm()`.
- `Player` gained `set_audio_sink()` and `has_audio`; `play()`/`seek()`/`set_speed()`
  now re-cue the configured sink to match the Timeline's position, so DMX and audio
  always start from the same instant (one master timeline, `docs/TIMING.md` §1).
  Non-1.0 speeds (including reverse) stop audio instead of playing it incorrectly,
  since `AudioSink` is forward-only by contract.
- `dmxreplay-convert --add-audio`: the one well-scoped conversion this CLI needed --
  attach an audio file to an already-recorded `.dmxr` (a live `Recorder` can't do this
  mid-recording, since an audio track can only be declared from a complete source file
  before the container header is written -- see `docs/CONTAINER.md` §3).
- **Two real bugs found by the new tests, not by inspection**, both in
  `DMXReplayWriter`/`DMXReplayReader`: (1) adding the manifest attachment *after*
  muxing the first audio packets corrupts the Matroska header and crashes the process
  (a native abort, not a catchable Python exception) later during encoder flush --
  fixed by always adding the attachment before any packet of any kind is muxed; (2)
  `DMXReplayReader` decoding the audio track first, through the same container object
  `read_frames()` uses, silently consumed the shared demuxer cursor all the way to
  EOF, so a subsequent `read_frames()` call found 0 frames instead of what was
  actually written -- fixed by decoding audio through a second, independent
  `av.open()` of the same file.
- `docs/CONTAINER.md`, `docs/SPECIFICATION.md` §14, and `docs/API.md` updated with
  the audio track's real constraints (attachment-ordering rule, AAC encoder priming
  delay, the "audio can only be attached from a complete file" timing constraint).

### Added — Phase 5/6: Recorder and Player core engines + CLI (headless)
- `src/dmxreplay/dmx/engine.py` (`DMXEngine`): live, protocol-agnostic per-universe
  state aggregator -- the "DMX Engine" box in the brief's architecture diagram.
  Art-Net/sACN listeners feed it raw updates; it commits a full DMXFrame snapshot
  (every row's current state) on each one, per `docs/TIMING.md` §4.1's policy. Row
  assignment is first-seen order across both protocols combined.
- `src/dmxreplay/recorder/recorder.py` (`Recorder`): `add_source()` (Art-Net/sACN,
  multiple sources supported), `get_universes()` (live discovery status for a
  checkbox UI), `start()` (freezes the discovered universe set into a `Manifest` and
  opens a `DMXReplayWriter`), `stop()`, `get_status()` (duration, frame/packet counts,
  malformed-packet counts, file size). One shared `MasterClock` across all sources.
- `src/dmxreplay/player/player.py` (`Player`): `load()` (decodes the whole file via
  `DMXReplayReader`), `set_output()`/`set_universe_mapping()`, `play()`/`pause()`/
  `stop()`/`seek()`/`set_speed()`/`set_fps()`/`set_loop()`. A `Timeline`-driven
  playback loop samples the current DMX state (sample-and-hold, SPECIFICATION.md §13)
  and emits it over real Art-Net/sACN only when it changes. Supports forward and
  reverse playback and looping in both directions.
- `src/dmxreplay/cli/{record,play,info}.py`: real `dmxreplay-record`,
  `dmxreplay-play` (incl. `--headless`, accepted for config/auto-start compatibility
  per `docs/RASPBERRY_PI.md` §13-14 -- the CLI never depended on a GUI to begin
  with), and `dmxreplay-info`. `dmxreplay-convert` is a documented stub (brief §51
  never specified its scope).
- Two bugs found and fixed by the real tests exercising all of this end to end: (1)
  `Recorder.add_source(..., port=0)` was silently rebinding to the default Art-Net
  port because of a `port or DEFAULT` idiom that treats `0` as falsy; (2) `Player`'s
  loop-restart path called `seek(0)` and then slept a full tick before ever
  re-checking the timeline, silently skipping the first frame after every loop
  restart except the very first pass through the file.
- Tests: `test_dmx_engine.py`, `test_recorder.py` (real Art-Net traffic captured into
  a real `.dmxr`), `test_player.py` (real playback verified over real Art-Net:
  correct DMX, seek, pause, loop, reverse, output remapping), `test_cli.py` (drives
  the actual CLI coroutines end to end, plus a subprocess smoke test of the installed
  `dmxreplay-info` console script), and `test_end_to_end_recorder_player.py` (the
  full `Art-Net -> Recorder -> .dmxr -> Player -> Art-Net` validation, now through
  the real orchestration classes rather than the lower-level primitives
  `test_end_to_end_artnet_pipeline.py` used before these classes existed).
- `docs/API.md` and `docs/RASPBERRY_PI.md` updated to reflect what's actually
  implemented now (both were written against a target/proposed interface before this
  phase).

### Added — Raspberry Pi 4/5 readiness analysis (V1 platform requirement)
- `docs/RASPBERRY_PI.md`: full compatibility analysis of the Phase 0–4 format/
  architecture against a new V1 requirement (standalone Raspberry Pi 4/5 operation).
  **Verdict: no format or codec change needed** — DMXReplay frames are tiny (65,536
  pixels max at the V1 ceiling vs. 2,073,600 for 1080p), so FFV1's lack of hardware
  decode on either Pi SoC doesn't matter in practice. One scoped, non-blocking finding:
  the optional `rgb_packed` encoding's pure-Python pixel packer is measurably slow at
  128 universes and should be optimized before relying on it at that scale on a Pi 4;
  the required grayscale baseline has no such issue.
- `benchmark/player_pipeline_benchmark.py` + `run_player_pipeline_benchmark.sh`: real
  decode -> Art-Net/sACN-output pipeline benchmark (not synthetic) at 1/10/50/128
  universes @ 30fps, measuring CPU/RSS/realtime-factor via `/usr/bin/time -v`. Results
  in `benchmark/pi_readiness_results.json`. Pi 4/5 figures are extrapolated from these
  measurements using published Geekbench 6 comparisons, explicitly labeled as estimates
  pending physical-hardware validation (no Pi hardware available in this environment).
- `tests/test_end_to_end_artnet_pipeline.py`: validates the full
  `Art-Net -> DMXReplayWriter -> .dmxr -> DMXReplayReader -> Art-Net` data path
  byte-for-byte, using the real Phase 2/3 network I/O and Phase 4 codec/container
  (the dedicated Recorder/Player orchestration classes are Phase 5/6 work and don't
  exist yet, but the data path they'll wrap is fully exercised here).
- Confirmed by audit, not modified: the master clock design (`docs/TIMING.md`) and the
  GUI-independent package architecture (`CONTRIBUTING.md`) both already satisfy the
  Raspberry Pi / headless requirement as designed.
- Proposed (not yet implemented, tracked for Phase 5/6): a `--headless` flag for
  `dmxreplay-play` and a config-file shape for future boot-time auto-start.

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
