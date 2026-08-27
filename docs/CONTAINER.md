# CONTAINER.md — Physical media encoding

Companion to [SPECIFICATION.md §3](SPECIFICATION.md#3-container-requirements). This
document is the **physical encoding** layer: exactly how the logical format
(SPECIFICATION.md) is laid out as real bytes in a real container. The logical format is
defined independent of this document by design (brief §3) — a future revision could in
principle replace this document with a different physical mapping without touching
SPECIFICATION.md's semantics.

The choices below are justified by measurement in
[FORMAT-RESEARCH.md](../FORMAT-RESEARCH.md); this document states the resulting
normative encoding rules.

## 1. Container: Matroska

- File extension exposed to users: **`.dmxr`**.
- Underlying container: **Matroska** (EBML-based), the same container family as
  `.mkv`/`.webm`. A `.dmxr` file is byte-for-byte a valid Matroska file — any
  Matroska-aware tool (ffmpeg, VLC, mkvtoolnix, ffprobe) can open, inspect, and remux it
  without any DMXReplay-specific code; it just won't understand the manifest.
- Rationale, with measured data: [FORMAT-RESEARCH.md §2.3](../FORMAT-RESEARCH.md#23-matroska-vs-mov).

## 2. Video track

| Property | Value |
|---|---|
| Codec | **FFV1** (FFmpeg codec ID `ffv1`), version 3 (the version emitted by current FFmpeg `-c:v ffv1` with default `-level`) |
| Pixel format | `gray` (grayscale encoding, SPECIFICATION.md §5.1) or `rgb24` (RGB-packed encoding, §5.2), matching the manifest's `encoding` field |
| Slicing/threading | Left at encoder defaults for V1 (FFV1 supports slice-based parallelism; not tuned/pinned in V1 — revisit if Phase 10 benchmarks show it matters at 128 universes) |
| Frame rate (container-level) | Set to the manifest's nominal `fps`; **actual per-frame timestamps govern playback** (SPECIFICATION.md §13) — the container-level rate is advisory/nominal only, consistent with VFR usage |
| GOP structure | Intra-only (every frame is a keyframe) — this is inherent to FFV1 and is required for good seek granularity (every frame is independently decodable) |

FFV1 was selected over Ut Video, HuffYUV, and uncompressed `rawvideo` because it
measured the best compression ratio of the lossless candidates while remaining fully
byte-for-byte lossless in every tested configuration — see
[FORMAT-RESEARCH.md §2](../FORMAT-RESEARCH.md#2-container--codec-support-and-losslessness)
and [§4](../FORMAT-RESEARCH.md#4-pattern--compressibility-spread).

## 3. Audio track (optional)

| Property | Value |
|---|---|
| Codec | AAC (FFmpeg `aac` encoder, or a bitstream-compatible encoder) |
| Presence | Optional — a DMXReplay file MAY have zero or one audio track |
| Sync | Must share the master timeline with the video track (SPECIFICATION.md §14); MUST be muxed with explicit frame/sample accounting — **MUST NOT** rely on a transcoder's default frame-rate reconciliation behavior between tracks, per the measured hazard in [FORMAT-RESEARCH.md §6](../FORMAT-RESEARCH.md#6-audio-in-the-same-container) (ffmpeg's default `vsync`/`fps_mode auto` silently duplicated a video frame when an audio track was present; `fps_mode passthrough` with an explicit frame count fixed it). Any DMXReplay writer MUST use the equivalent of explicit/passthrough frame handling, never a tool's "auto" stream-sync default. |

## 4. Manifest storage (attachment)

- The manifest (SPECIFICATION.md §10) is stored as a **Matroska Attachment**
  (`AttachedFile` element), not as a side-channel track or a required external file.
- Attachment filename: **`dmxreplay-manifest.json`** (fixed, used for identification —
  SPECIFICATION.md §2).
- Attachment MIME type: `application/json`.
- Content: UTF-8 encoded JSON, matching
  [`../src/dmxreplay/metadata/schema.json`](../src/dmxreplay/metadata/schema.json).
- Rationale for an attachment over Matroska's `Tags` element: `Tags` is designed for
  flat key/value metadata (title, artist, etc.) and is a poor fit for a structured,
  nested, versioned document like the `universes[]` mapping; an attachment lets the
  manifest be a normal, independently-parseable JSON document, and tools that don't
  understand DMXReplay still see a normal (if opaque) attached file rather than
  malformed tags.

## 5. Track/attachment ordering

Not semantically significant — a reader MUST locate the video track by codec (`ffv1` or
the manifest-declared alternative), the audio track (if any) by track type `audio`, and
the manifest by attachment filename (§4), never by fixed track/attachment index.

## 6. What was explicitly rejected, and why

See [FORMAT-RESEARCH.md](../FORMAT-RESEARCH.md) for full data. Summary:

- **MP4**: hard-disqualified — the muxer refuses FFV1/Ut Video/HuffYUV/even rawvideo
  outright (not a size/quality trade-off; a compatibility wall in mainstream tooling).
- **MOV**: viable for FFV1 (lossless, size within ~1% of Matroska), but a
  lossless-in-theory codec (`rawvideo`) round-tripped **incorrectly** in MOV on the
  tested ffmpeg build — a concrete instance of "don't assume, benchmark," and a reason
  to prefer Matroska's cleaner track record across every tested codec.
- **Uncompressed (`rawvideo`)**: rejected as the codec choice on file-size grounds alone
  (no compression: ~0.99–1.0× ratio vs. FFV1's 6.8–11.9× on the same content) — see
  [FORMAT-RESEARCH.md §2](../FORMAT-RESEARCH.md#2-container--codec-support-and-losslessness).
- **HuffYUV / Ut Video**: both fully lossless and viable fallbacks, but FFV1 compressed
  noticeably better in every tested pattern — see
  [FORMAT-RESEARCH.md §2](../FORMAT-RESEARCH.md#2-container--codec-support-and-losslessness).
  A DMXReplay reader MAY still decode files declaring one of these as an alternative
  codec (SPECIFICATION.md §3 permits a declared alternative), but a writer is not
  required to ever produce one.

## 7. Embedding conventional video — not in V1

Per brief §24/§39 and SPECIFICATION.md §14/§17, conventional (visually-meaningful)
video stays an **external** file in V1 (`Show.dmxr` + `Show.mp4`, synchronized by
timestamp at playback time, never embedded in the same container). Investigating
embedding is explicitly future work — doing so now would mean carrying a second,
*lossy*, differently-timed video track inside a container designed around one
intra-only lossless track, which is a materially different engineering problem
(container-level multi-video-track semantics, lossy codec selection, etc.) than V1's
scope.
