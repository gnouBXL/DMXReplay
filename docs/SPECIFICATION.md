# DMXReplay Specification 1.0 (Draft)

Status: **Draft** — implemented against by the reference recorder/player in this
repository, but not yet frozen. Backward-incompatible changes are still possible before
a `1.0` format version is declared stable (see §16 Versioning).

This document defines the DMXReplay **logical format**: what a compliant file means,
independent of how its bytes are physically stored. The physical storage layer
(container/codec choice, and the exact benchmark data behind it) is specified
separately in [CONTAINER.md](CONTAINER.md) and [FORMAT-RESEARCH.md](../FORMAT-RESEARCH.md),
so that a future physical encoding could in principle be added without changing this
document. Protocol-specific detail for Art-Net and sACN lives in
[ARTNET.md](ARTNET.md) and [SACN.md](SACN.md); timing/clock detail lives in
[TIMING.md](TIMING.md); the programmatic API lives in [API.md](API.md).

A third-party developer should be able to implement a compatible DMXReplay reader,
recorder, or player from this set of documents alone.

## Contents

1. [Terminology](#1-terminology)
2. [File identification](#2-file-identification)
3. [Container requirements](#3-container-requirements)
4. [Video representation](#4-video-representation)
5. [Pixel encoding](#5-pixel-encoding)
6. [DMX channel mapping](#6-dmx-channel-mapping)
7. [Universe mapping](#7-universe-mapping)
8. [Art-Net mapping](#8-art-net-mapping)
9. [sACN mapping](#9-sacn-mapping)
10. [Metadata](#10-metadata)
11. [Timestamp format](#11-timestamp-format)
12. [Frame timing](#12-frame-timing)
13. [VFR behavior](#13-vfr-behavior)
14. [Audio synchronization](#14-audio-synchronization)
15. [Error handling](#15-error-handling)
16. [Versioning](#16-versioning)
17. [Compatibility](#17-compatibility)
18. [Security considerations](#18-security-considerations)
19. [Test vectors](#19-test-vectors)
20. [Conformance requirements](#20-conformance-requirements)

---

## 1. Terminology

| Term | Meaning |
|---|---|
| **Channel** | One DMX data slot: an unsigned 8-bit value, `0`–`255`. |
| **Universe** | An ordered sequence of exactly 512 channels (channels 1–512). |
| **DMX frame** | A snapshot of the values of every active channel, across every active universe, at one instant on the capture timeline. |
| **Active universe** | A universe for which at least one DMX packet was actually received/is present during the recording; see §7. |
| **Row** | The physical video row (or row-group, for RGB packing) that a given active universe is stored in. Row index is **not** the same thing as universe number — see §7. |
| **DMXReplay file** | A physical media file (Matroska container, see [CONTAINER.md](CONTAINER.md)) conforming to this specification, conventionally named with the `.dmxr` extension. |
| **Manifest** | The versioned, structured metadata block embedded in a DMXReplay file (§10). |
| **Master timeline** | The single authoritative clock a DMXReplay player uses to drive DMX output, audio, and external video in lock-step (§14, [TIMING.md](TIMING.md)). |
| **Capture timeline** | The sequence of high-resolution timestamps at which DMX packets were actually received during recording (§12). |
| **Playback timeline** | The sequence of timestamps at which DMX states are reproduced during playback; may run at a different nominal rate than the capture timeline (§12). |
| **Port-Address** | The Art-Net 4 `Net`/`Sub-Net`/`Universe` addressing triple; see [ARTNET.md](ARTNET.md). |
| **Reader / Recorder / Player** | The three conformance roles defined in §20. |

Key words "MUST", "MUST NOT", "SHOULD", "SHOULD NOT", and "MAY" are used as in RFC 2119.

## 2. File identification

- The conventional file extension is **`.dmxr`**.
- The physical container is Matroska (see [CONTAINER.md](CONTAINER.md)); a DMXReplay
  file is a valid Matroska file and can be opened by any Matroska-aware tool, though
  such a tool will not know how to interpret the DMX manifest.
- The extension alone MUST NOT be relied upon for format identification (files get
  renamed). A reader MUST identify a DMXReplay file by:
  1. Confirming the outer container is valid Matroska (EBML header present), **and**
  2. Locating an attachment (see [CONTAINER.md](CONTAINER.md) §"Manifest storage")
     whose filename is `dmxreplay-manifest.json` and whose content parses as a valid
     DMXReplay manifest (§10) with a recognized `"format": "DMXReplay"` field.
- A file missing a valid manifest attachment is not a DMXReplay file, even if it
  happens to contain a video track shaped like one — this rules out treating an
  arbitrary grayscale video as a DMX recording by accident.

## 3. Container requirements

Full detail and the benchmark behind this choice: [CONTAINER.md](CONTAINER.md) and
[FORMAT-RESEARCH.md](../FORMAT-RESEARCH.md). Summary of the normative requirements:

- The container MUST be Matroska.
- The container MUST contain exactly one DMX video track, encoded losslessly per §4/§5.
- The container MAY contain exactly one audio track (§14). If present, it MUST be
  synchronized to the same timeline as the DMX video track (same start, same rate of
  time passing — no independent clocks).
- The container MUST contain exactly one attachment carrying the manifest (§10).
- The container MUST NOT contain any other video track. (Conventional/preview video is
  always an *external* file in V1 — see §14 and brief §24; embedding it is future work.)
- The DMX video track's codec MUST be a codec verified lossless for 8-bit sample data
  under round-trip byte comparison. V1 REQUIRES FFV1 (`fourcc/codec ID FFV1`, tagged
  `V_MS/VFW/FOURCC` or Matroska-native `V_FFV1` per the muxer used) as the baseline
  codec every DMXReplay writer and reader MUST support. A file MAY use a different
  verified-lossless codec if declared in the manifest (`video.codec`), but readers are
  only REQUIRED to decode FFV1.

## 4. Video representation

The DMX video track's frames are not intended to be watched. **One video sample
represents one DMX state at one point on the capture timeline** (see §12 for the
VFR/CFR distinction). No gamma correction, no color management, no chroma subsampling,
and no interpolation may be applied anywhere between capture and the stored pixel
value: the stored 8-bit sample **is** the DMX byte.

Frame height is dynamic and MUST equal the number of **active** universes actually
present in the recording (see §7) — a recording with 10 active universes MUST produce a
10-row-tall (or 10-row-group-tall, for RGB packing) video, never a fixed 128-row
allocation. Frame width is fixed by the pixel encoding in use (§5).

## 5. Pixel encoding

Two pixel encodings are defined. A file declares which one it uses via the manifest's
`encoding` field (§10). See [FORMAT-RESEARCH.md §3](../FORMAT-RESEARCH.md#3-pixel-packing-grayscale-vs-rgb-packed)
for the measured size/complexity trade-off behind the recommendation below.

### 5.1 Grayscale (`"encoding": "grayscale"`) — REQUIRED baseline

- Frame width = **512** pixels (one pixel per DMX channel).
- Frame height = number of active universes, `N`.
- Pixel format: single 8-bit grayscale sample per pixel (ffmpeg `pix_fmt=gray`).
- Mapping: `pixel(x, row) = channel (x + 1) of the universe stored at that row` for
  `x` in `0..511`.
- This is the V1 default and the encoding every conformant writer MUST be able to
  produce; every conformant reader MUST be able to decode it.

### 5.2 RGB-packed (`"encoding": "rgb_packed"`) — OPTIONAL, storage-optimized

- Frame width = **171** pixels (`ceil(512 / 3)`) — 3 DMX channels per pixel.
- Frame height = number of active universes, `N`.
- Pixel format: **`bgr0`, 4 bytes per pixel** (byte order Blue, Green, Red, pad;
  ffmpeg/libavcodec `pix_fmt=bgr0`). **Not** a tightly-packed 3-byte `rgb24`: FFV1 (the
  V1 baseline codec, §3) has no 8-bit packed 3-byte RGB pixel format at all — only
  4-byte formats (`bgr0`, `bgra`) among its 8-bit RGB-likes (confirmed by querying
  `av.codec.Codec("ffv1", "w").video_formats`; see FORMAT-RESEARCH.md §3.1 for how this
  was discovered). The **logical** channel-to-component mapping below is unaffected;
  only the physical byte order and the extra always-zero 4th byte differ from a
  hypothetical tight `rgb24`.
- Mapping, for pixel `p` in `0..170`: DMX channel `3p+1` (1-based) → this pixel's
  **R** component, `3p+2` → **G**, `3p+3` → **B**. Physically, within the pixel's 4
  bytes, these are written in **`bgr0`** order: byte 0 = B, byte 1 = G, byte 2 = R,
  byte 3 = pad (always `0`, MUST be ignored on read — it never carries a channel
  value, regardless of `p`). Separately, for `p = 170`, channel indices `3p+1..3p+3`
  (0-based `510..512`) run past the last valid channel (0-based index `511`); any
  component whose channel index is `≥ 512` (i.e. `p=170`'s B component) is **unused
  and MUST be written as `0`**, and MUST be ignored (not interpreted as a channel
  value) on read — this is in addition to, and independent of, the format's own pad
  byte.
- Measured ~42% smaller than grayscale for representative content (FORMAT-RESEARCH.md
  §3); RECOMMENDED for long-duration or high-universe-count recordings.
- A conformant writer MAY support this encoding; a conformant reader SHOULD support it
  (REQUIRED for the "Player" conformance role, see §20).

### 5.3 What packing never means

Neither encoding implies anything about fixture color. RGB-packed storage is a *byte
packing strategy*, not a color space. See §"Preview mode" note below and brief §8: a
player MAY offer a separate, clearly-labeled "RGB/LED preview" *visualization* that
reinterprets three consecutive channels as R/G/B for on-screen display — that
visualization layer is purely cosmetic, operates only on decoded DMX values (regardless
of which of the two encodings above the file actually uses), and MUST NOT alter,
gamma-correct, or persist anything back into the DMX data.

## 6. DMX channel mapping

Each channel is an **unsigned 8-bit integer, `0`–`255`, with no semantic
interpretation** (brief §5). DMXReplay never encodes what a channel *means* (dimmer,
pan, red, etc.) — only its raw value and its position (universe, channel-within-universe,
timestamp). This is what makes the format fixture-agnostic and future-proof: a decoder
written against this spec alone can correctly reproduce any recorded channel value
without knowing anything about the lighting rig that produced it.

## 7. Universe mapping

- A DMXReplay file stores only universes that were actually active (received at least
  one packet) during recording — never a fixed pre-allocated block (brief §9).
- The row a universe is stored at (its **row index**, `0..N-1`) carries **no**
  implied relationship to that universe's original network address. Row 0 is not
  necessarily "universe 1" — it is whatever the recorder assigned first (typically
  discovery/arrival order).
- The mapping from row index → original source addressing (Art-Net Net/Sub-Net/Universe,
  or sACN universe) MUST be stored in the manifest's `universes[]` array (§10), keyed by
  `row`.
- A reader MUST use the manifest mapping to determine which original universe a given
  row represents; a reader MUST NOT assume `row == universe number - 1` or any other
  implicit formula.
- No empty/placeholder rows are permitted between active universes' rows — rows are
  packed contiguously `0..N-1` regardless of how sparse the original addressing was
  (e.g. source universes `{1, 5, 17}` become rows `{0, 1, 2}`, in the order the manifest
  declares — see brief §10 and the "Sparse universes" test vector, §19).

## 8. Art-Net mapping

Full detail: [ARTNET.md](ARTNET.md). Summary: Art-Net 4's addressing is a 15-bit
**Port-Address**, composed of `Net` (7 bits), `Sub-Net` (4 bits), `Universe` (4 bits):

```
Port-Address (15 bits) = Net(7) | Sub-Net(4) | Universe(4)
```

DMXReplay's manifest stores `net`, `subnet`, and `universe` as separate integer fields
per row (never collapsed into a single opaque index), so the original Port-Address is
always exactly recoverable: `port_address = (net << 8) | (subnet << 4) | universe`, and
conversely `net = (port_address >> 8) & 0x7F`, `subnet = (port_address >> 4) & 0x0F`,
`universe = port_address & 0x0F`. See [ARTNET.md](ARTNET.md) for packet parsing rules,
sequence-number handling, and the V1 subset of Art-Net 4 that is implemented (vs.
documented for future work, per brief §11/§41).

## 9. sACN mapping

Full detail: [SACN.md](SACN.md). Summary: sACN / ANSI E1.31 addresses a universe with a
16-bit **Universe** number (`1`–`63999`). The manifest stores this directly as the
row's `universe` field with `protocol: "sACN"` (no net/subnet — those are Art-Net-only
concepts). [SACN.md](SACN.md) documents exactly which E1.31 features V1 implements
(basic streaming: root layer, framing layer, DMP layer, sequence number passthrough)
and which are explicitly deferred (priority merging, synchronization packets, universe
discovery, stream termination semantics) per brief §12.

## 10. Metadata

The manifest is a single JSON document, embedded as a named Matroska attachment (see
[CONTAINER.md](CONTAINER.md)), never a mandatory *external* file. The formal schema is
[`schema/manifest.schema.json`](../src/dmxreplay/metadata/schema.json)
(JSON Schema, Draft 2020-12); this section is the normative prose description.

### 10.1 Required top-level fields

| Field | Type | Meaning |
|---|---|---|
| `format` | string, constant `"DMXReplay"` | Format identifier, used for file identification (§2). |
| `version` | string, semver-like `"MAJOR.MINOR"` | Manifest schema version (§16). |
| `encoding` | `"grayscale"` \| `"rgb_packed"` | Pixel encoding in use (§5). |
| `fps` | number | Nominal frame rate (§12). |
| `vfr` | boolean | Whether the video track uses variable frame timing (§13). |
| `timestamp_resolution_ns` | integer | Resolution of stored timestamps, in nanoseconds (§11). |
| `width`, `height` | integer | Video frame dimensions, redundant with the container's own track headers but required here so a manifest-only parse (no video decode) can still validate shape. |
| `universes` | array of objects (see 10.2) | Row → source-address mapping (§7). |
| `created_at` | string, RFC 3339 UTC timestamp | Recording creation time. |
| `duration_seconds` | number | Total recording duration. For a file produced by a live/streaming recorder, this MAY be a best-effort estimate rather than exact (the true duration is only known once recording stops, but the manifest attachment is written once, at container-header time — see `docs/CONTAINER.md` §4 — before that). The **authoritative** duration is always derivable by any reader from the video track's own last-frame timestamp; a reader MUST NOT treat `duration_seconds` as more precise than that. |
| `recorder` | object `{name, version}` | Producing software identification. |

### 10.2 `universes[]` entry fields

| Field | Type | Meaning |
|---|---|---|
| `row` | integer | Row index (§7), `0`-based. |
| `protocol` | `"Art-Net"` \| `"sACN"` | Source protocol for this universe. |
| `net`, `subnet`, `universe` | integer | Art-Net Port-Address components (§8). Present only when `protocol == "Art-Net"`. |
| `universe` | integer | sACN universe number (§9). Present (alone) when `protocol == "sACN"`. |
| `source_ip` | string, optional | Source IP address, when known. |

### 10.3 Optional fields

`audio` (object: codec, sample rate, channels — present iff an audio track exists, §14),
`external_video_ref` (string, optional filename hint for the companion video file, §14),
`show_name`, `description` (free-text, optional), `container_version` (string, physical
container/muxer version info for diagnostics).

### 10.4 Versioning and forward compatibility

- The manifest MUST include `version`. A reader encountering a manifest `version` whose
  **major** component it does not recognize MUST refuse to decode DMX data from the
  file (fail closed) rather than guess. A reader encountering a newer **minor** version
  within a major version it understands MUST proceed, ignoring any unrecognized field
  (§16, §17).
- Fields not listed above MAY be present and MUST be preserved by any tool that
  round-trips (reads and rewrites) a manifest, even if that tool doesn't understand
  them.

## 11. Timestamp format

- All timestamps are stored as **integer nanoseconds** since an arbitrary
  recording-local epoch (`t=0` at the start of capture) — never wall-clock/calendar
  time for the per-frame timing itself (calendar time, if wanted, lives only in the
  manifest's `created_at`, once, as metadata).
- The capture-side clock MUST be a **monotonic, high-resolution** clock (e.g.
  `clock_gettime(CLOCK_MONOTONIC)` / `time.monotonic_ns()`), never wall-clock time
  (which can jump backward/forward under NTP adjustment) and never a fixed-tick counter
  derived only from an assumed frame rate. See [TIMING.md](TIMING.md) for the full
  rationale and the measured hazard in FORMAT-RESEARCH.md §6 (implicit frame-rate
  reconciliation silently duplicating a frame).
- `timestamp_resolution_ns` in the manifest documents the *effective, as-stored*
  precision — i.e. the granularity a reader can actually rely on, not the raw
  capture-side clock's precision. These are **not the same thing**, and conflating them
  was an earlier draft error corrected once real storage was implemented (Phase 4):
  the in-memory capture clock (§3 above) is OS-dependent and typically low-microsecond
  or better, but the **physical container/codec toolchain currently in use quantizes
  timestamps to whole milliseconds** on write (Matroska's muxer has a fixed 1 ms
  `TimecodeScale` in this toolchain, and the video encoder's own time base must be
  pinned to match it explicitly or timing is silently lost even earlier — both measured
  in FORMAT-RESEARCH.md §11). `docs/CONTAINER.md`'s `STORAGE_TIMESTAMP_RESOLUTION_NS`
  (`1,000,000`, i.e. 1 ms) is therefore what `timestamp_resolution_ns` is set to for V1
  files produced by the reference writer. A reader MUST use the manifest's declared
  value, not assume any particular resolution.

## 12. Frame timing

DMXReplay distinguishes two timelines (brief §16):

- **Capture timeline** — the precise timestamps at which DMX packets actually arrived
  during recording. This is never discarded, even though V1's nominal rate is 30 fps.
- **Playback timeline** — the timestamps at which DMX states are reproduced during
  playback, which a user MAY run at a different rate (brief §17: 15/20/25/30/50/60 fps
  or custom).

The nominal DMXReplay rate is **30 fps**, but every DMX video frame carries its own
timestamp (§11); a reader/player MUST use the per-frame timestamp, not a `frame_index /
fps` computation, to determine when that frame's DMX state is valid. Changing playback
FPS changes *how often the player samples the timeline*, never the recorded DMX values
themselves (§13).

## 13. VFR behavior

- The video track MAY use Variable Frame Rate: consecutive frames MAY have unequal
  timestamp deltas, reflecting genuine irregularity in when DMX packets were received
  (manifest `vfr: true`).
- Matroska natively supports per-block timestamps, which is what makes VFR storage
  possible without inventing a side-channel timing format (see
  [FORMAT-RESEARCH.md](../FORMAT-RESEARCH.md) for why Matroska was chosen partly for
  this reason).
- **Playback rate changes never interpolate DMX values unless explicitly requested.**
  When the player's playback rate differs from the capture rate (or from `fps`), the
  DMX state at playback time `T` is the value held by the **most recent frame whose
  timestamp is ≤ T** (sample-and-hold / zero-order hold). Linear or other interpolation
  between frames is explicitly out of scope for V1 and MUST NOT happen implicitly —
  brief §17 is explicit that reducing 30→15 fps must not interpolate.
- Reducing playback rate below the capture rate means some captured frames are skipped
  (not blended); increasing it beyond the capture rate means some captured frames are
  held for more than one displayed tick. Both are sample-and-hold; neither smooths.

## 14. Audio synchronization

- If present, the audio track (AAC, recommended — brief §18) and the DMX video track
  share **one master timeline** (see [TIMING.md](TIMING.md), [API.md](API.md)'s
  `Clock` interface). There is no independent audio clock: `Player` starts/stops/
  re-cues audio playback (via an `AudioSink`, [API.md](API.md) §Audio) at the same
  `Timeline` position it drives DMX output from, whenever play/seek/speed changes it.
  Once playback is running, the audio sink's own hardware clock is what actually paces
  sound output — V1 does not discipline `Timeline` against that hardware clock
  afterward (a documented limitation, not an independent second clock: both still
  *start* from the one master timeline's position, they just aren't continuously
  re-synced against each other during playback).
- An external, conventional video file (e.g. `Show.mp4`, alongside `Show.dmxr`) is
  **not** part of the DMXReplay container in V1 (brief §24/§39) — it is synchronized by
  the player against the same master timeline as a third track, driven purely by
  timestamp, not embedded. Container embedding of conventional video is documented as
  V2+ future work (§17).
- Seeking (brief §21), reverse playback (§22), and looping (§23) all operate by moving
  the **master timeline's** position; DMX/audio/external-video subsystems each answer
  "what should I be doing at time T" independently when asked, but T itself has exactly
  one source of truth. See [TIMING.md](TIMING.md) for the full master-clock design and
  the `ClockProvider` abstraction that leaves room for future external timecode sources
  (SMPTE/LTC, MTC, Art-Net TimeCode — brief §40–§42) without changing this interface.

## 15. Error handling

A reader/player MUST distinguish, and MUST NOT silently mask, at least these conditions
(brief §57–§58): malformed manifest JSON, manifest `version` major mismatch, missing
required manifest field, video/audio codec mismatch against manifest declaration,
video dimensions inconsistent with `universes[]` count, decode error mid-file, and (for
recorders) network-side conditions — malformed packet, invalid universe/Port-Address,
unexpected packet length, unsupported protocol version, and excessive packet rate. A
DMXReplay implementation MUST NOT respond to any of these by silently substituting,
truncating, or corrupting DMX output; the required behavior in each case is specified
per-module in [API.md](API.md) and [ARTNET.md](ARTNET.md)/[SACN.md](SACN.md).

## 16. Versioning

- This document is versioned independently as **DMXReplay Specification 1.0 (Draft)**.
- The manifest schema version (`version` field, §10.4) tracks the *on-disk format*,
  which is what actually needs compatibility guarantees; the specification document
  version and the manifest schema version are expected to move together but are
  formally distinct.
- Format version numbers are `MAJOR.MINOR`. A MINOR bump MUST be purely additive
  (new optional fields, new optional encodings/codecs) — anything an old reader can
  safely ignore. A MAJOR bump MAY change the meaning of existing fields and MAY break
  old readers; readers MUST refuse (not guess) when they don't recognize a file's major
  version (§10.4).

## 17. Compatibility

- Backward compatibility target: a reader implementing this specification version MUST
  be able to read every file produced by a writer implementing the same MAJOR version,
  regardless of MINOR version, ignoring fields it doesn't recognize.
- Forward compatibility is explicitly NOT promised across MAJOR versions.
- Documented, not-yet-implemented future extensions (do not implement speculatively —
  brief §56): embedded conventional video, multiple audio/video tracks, external
  timecode sources (SMPTE/LTC, MTC, Art-Net TimeCode, sACN sync, Ableton Link), RDM,
  >128 universes, 16-bit fixture values, channel/fixture metadata, multiple concurrent
  Art-Net sources with priority merging, redundant network paths.

## 18. Security considerations

Art-Net and sACN are UDP-based and unauthenticated; a recorder MUST treat all inbound
network data as untrusted (brief §57): validate packet length before indexing into it,
validate protocol/version identifiers before dispatch, validate universe/Port-Address
range before using it as an array/row index, and bound per-source packet rate to avoid
unbounded memory growth from a misbehaving or malicious sender. A malformed or
adversarial packet MUST be dropped and logged (§15), never allowed to crash the
recorder or corrupt already-recorded data. On the read side, a manifest is untrusted
input from a file that may have been transferred or edited: a reader MUST validate it
against the schema before using any of its values (e.g. `width`/`height`/`universes`
count) to size buffers or index arrays, to avoid out-of-bounds access driven by a
crafted file.

## 19. Test vectors

Official test vectors (generated by
[`test-vectors/generate_test_vectors.py`](../test-vectors/generate_test_vectors.py),
see that directory's README for exact byte layouts):

1. **Ramp** — channel values cycle `0..255` over time.
2. **Alternating** — all channels alternate `0`/`255` every frame.
3. **Random** — deterministic pseudo-random values across all 512 channels.
4. **Multiple universes** — at least 128 active universes.
5. **Sparse universes** — a small, non-contiguous set of source universes (e.g. Art-Net
   universes 1, 5, 17, 42), verifying row-packing per §7.
6. **High packet rate** — stress test at realistic maximum Art-Net/sACN packet rates
   (implemented as a recorder-side test, not a static file — see `tests/`).
7. **Timing irregularity** — packets arriving at intentionally variable intervals,
   exercising VFR (§13).
8. **Seek** — play → seek forward → seek backward → verify exact DMX state at each stop.
9. **Synchronization** — DMX + audio + external video, a per-second visible counter
   compared against the DMX channel value at the same instant, within a documented
   tolerance (measured, not assumed — see [TIMING.md](TIMING.md) §8: ~0.18ms DMX↔video
   pairing skew in this project's own environment, well under the ±1-video-frame
   staleness bound each track is individually subject to).
10. **Loop** — verify seamless timeline restart (DMX, audio, and external video all
    resume at their respective `t=0` on the same master-timeline tick).

All 10 test vectors are implemented. Tests 1–5 at the `dmxreplay.dmx` data-model level
(`tests/test_dmx_model.py`) and round-tripped through the real container
(`tests/test_container_roundtrip.py`); tests 6–9 in
[`tests/test_conformance.py`](../tests/test_conformance.py) (Phase 10); test 8 (seek)
and test 10 (loop) in `tests/test_player.py`, exercised again against `frame_step()` in
`test_conformance.py`. See §20 below and `test_conformance.py`'s module docstring for
the full test↔requirement mapping.

## 20. Conformance requirements

Three independent conformance roles (an implementation MAY claim one, two, or all
three):

### Reader
MUST: open a valid DMXReplay file; identify it per §2; parse and validate the manifest
per §10 and §16.4's version-refusal rule; decode the DMX video track (at least
grayscale, §5.1); reconstruct per-universe channel values using the manifest's row
mapping (§7); reproduce each frame's timestamp (§11) without alteration.

### Recorder
MUST: capture at least one of Art-Net ([ARTNET.md](ARTNET.md)) or sACN
([SACN.md](SACN.md)); timestamp every received DMX frame with a monotonic
high-resolution clock (§11); produce a valid DMXReplay file (passes Reader
requirements above on its own output); store only actually-active universes (§7);
preserve DMX values exactly (byte-for-byte) and preserve capture timing within the
tolerance documented in [TIMING.md](TIMING.md).

### Player
MUST: everything required of a Reader; output decoded DMX as Art-Net and as sACN
([ARTNET.md](ARTNET.md), [SACN.md](SACN.md)); maintain audio/video/DMX synchronization
against one master timeline (§14, [TIMING.md](TIMING.md)); support seek, play, pause,
frame-step, and loop (§13, brief §21–§23) with correct DMX state immediately after any
of those operations.
