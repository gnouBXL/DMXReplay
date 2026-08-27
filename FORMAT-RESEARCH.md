# FORMAT-RESEARCH.md — DMXReplay Phase 0 Format Research & Benchmark

**Status:** Phase 0 complete for V1. This document records the *actual measurements*
behind the container/codec/pixel-packing recommendation in
[`docs/SPECIFICATION.md`](docs/SPECIFICATION.md) and [`docs/CONTAINER.md`](docs/CONTAINER.md).

All numbers in this document come from real `ffmpeg`/`ffprobe` invocations, run by
[`benchmark/format_benchmark.py`](benchmark/format_benchmark.py) on this development
machine (Linux x86_64, ffmpeg 6.1.1, 4 vCPU, ext4). They are not simulated or estimated.
Raw results: [`benchmark/results.json`](benchmark/results.json). Absolute timings will
differ on other hardware; the pass/fail and relative findings below should not.

## 1. What was tested, and how

`benchmark/format_benchmark.py` generates synthetic DMX-shaped frame sequences
(grayscale `512×N` or RGB-packed `171×N`, per §6/§7 of the spec) using three patterns:

- **ramp** — every channel changes every frame (`(frame + channel) % 256`); worst case
  for intra-frame delta prediction, representative of a moving-head show with
  continuously changing pan/tilt/color.
- **alternating** — the whole frame flips between `0x00` and `0xFF`; best case, highly
  redundant.
- **random** — deterministic pseudo-random bytes; stresses entropy coding.

Each case is encoded to a container/codec combination, decoded back to raw, and
compared **byte-for-byte** against the original input. `losslessness` below means an
exact match; anything else is a failure regardless of file size or speed.

## 2. Container × codec support and losslessness

10 universes, 150 frames (5 s @ 30 fps), grayscale, ramp pattern:

| Container | Codec | Encode OK | Lossless | File size | Notes |
|---|---|---|---|---|---|
| mkv | FFV1 | ✅ | ✅ | 112,417 B | |
| mkv | Ut Video | ✅ | ✅ | 218,320 B | |
| mkv | HuffYUV | ✅ | ✅ | 582,455 B | |
| mkv | rawvideo | ✅ | ✅ | 774,827 B | uncompressed baseline |
| mov | FFV1 | ✅ | ✅ | 111,727 B | |
| mov | Ut Video | ✅ | ✅ | 214,310 B | |
| mov | HuffYUV | ✅ | ✅ | 577,440 B | |
| mov | rawvideo | ✅ | **❌** | 768,726 B | **round-trip corrupted, see 2.1** |
| mp4 | FFV1 | **❌** | — | — | muxer rejects codec, see 2.2 |
| mp4 | Ut Video | **❌** | — | — | muxer rejects codec |
| mp4 | HuffYUV | **❌** | — | — | muxer rejects codec |
| mp4 | rawvideo | **❌** | — | — | muxer rejects codec |

### 2.1 MOV + rawvideo is not lossless (unexpected)

`mov` muxed with the *uncompressed* `rawvideo` codec failed the byte-for-byte check
(first divergence at byte offset 4 of the decoded stream). `mov` + FFV1 and `mov` +
Ut Video/HuffYUV round-tripped correctly. This is exactly the kind of assumption the
spec (§3) told us not to make going in — a "trivially lossless" raw codec is not
automatically lossless once a specific container's muxing/remuxing logic is involved.
It reinforces using a real lossless *codec* (FFV1) rather than relying on "no codec" as
the losslessness guarantee, regardless of container choice.

### 2.2 MP4 cannot carry any of the candidate lossless codecs

With this ffmpeg build, the `mp4` muxer refuses FFV1, Ut Video, HuffYUV, and even
`rawvideo` outright:

```
Could not find tag for codec ffv1 in stream #0, codec not currently supported in container
```

This is not a benchmark nuance to weigh against file size — it is a hard compatibility
wall in mainstream tooling. **MP4 is disqualified for DMXReplay V1.**

### 2.3 Matroska vs. MOV

Both carried FFV1/Ut Video/HuffYUV losslessly, with near-identical file sizes (Matroska
was ~0.6% larger than MOV for the same content — noise-level). Matroska is preferred
over MOV as the primary container because:

- It is an explicitly open, unencumbered format (EBML-based) with the most permissive
  extensibility model for the custom metadata this spec needs (§25) — see
  [`docs/CONTAINER.md`](docs/CONTAINER.md).
- It has first-class, native support for arbitrary/irregular per-block timestamps,
  which VFR (§16) fundamentally requires.
- It is FFmpeg's most "no surprises" muxer for arbitrary lossless codecs (as 2.1 shows,
  even MOV has codec-specific edge cases).
- Native attachment support (arbitrary embedded files with a MIME type) gives a clean,
  standard place to embed the versioned manifest from §25, without inventing a custom
  chunk format.

**Decision: Matroska (`.mkv`, exposed to users as `.dmxr`) is the DMXReplay V1
container. FFV1 is the DMXReplay V1 video codec.**

## 3. Pixel packing: grayscale vs. RGB-packed

Same content (10 universes, 150 frames, ramp pattern), FFV1/Matroska:

| Packing | Width | Raw size | Encoded size | Compression ratio |
|---|---|---|---|---|
| Grayscale (1 channel/pixel) | 512 | 768,000 B | 112,417 B | 6.83× |
| RGB-packed (3 channels/pixel) | 171 | 769,500 B | 64,586 B | 11.91× |

RGB packing produced a file **~42% smaller** for identical DMX content. This is
consistent with FFV1's per-plane prediction handling 3-byte-interleaved pixels more
efficiently than single-channel rows in this configuration, on top of the 3× reduction
in pixel *count* (raw byte count is nearly identical; the win is in how well FFV1
compresses the result).

**Decision:** both encodings are part of the V1 spec (§6/§7) and are declared per-file
via the `encoding` metadata field, exactly as illustrated in the brief's example
manifest. **Grayscale is the V1 default/required baseline** — the direct
`pixel(channel, universe) = 1:1` mapping is the simplest possible for a third-party
implementer to get right without a reference implementation (a stated project goal,
see spec §1), and a grayscale frame can be opened in any image viewer as an
immediately-legible "channel × universe" heatmap for debugging.
**RGB-packed is an optional, storage-optimized encoding**, recommended for
long-duration or high-universe-count recordings where the ~40% size reduction matters.
A conformant reader must support both; a conformant writer must support at least
grayscale.

## 4. Pattern / compressibility spread

10 universes, 150 frames, grayscale, FFV1/Matroska:

| Pattern | File size | Compression ratio |
|---|---|---|
| alternating | 7,698 B | 99.77× |
| ramp | 112,417 B | 6.83× |
| random | 170,916 B | 4.49× |

Real lighting shows sit far closer to "ramp" than "random" (fixture values change
smoothly/held between cues, not uniformly at random every frame), so the ramp numbers
above are a reasonable pessimistic planning baseline; random is the worst realistic
case and still compresses 4.5×.

## 5. Scale: 1 / 10 / 50 / 128 universes

Ramp pattern, grayscale, FFV1/Matroska, 150 frames (5 s of show @ 30 fps):

| Universes | Encode time | Decode time | File size | Compression |
|---|---|---|---|---|
| 1 | 79 ms | 96 ms | 25,859 B | 2.97× |
| 10 | 89 ms | 83 ms | 112,417 B | 6.83× |
| 50 | 146 ms | 117 ms | 496,436 B | 7.74× |
| 128 | 240 ms | 198 ms | 1,245,237 B | 7.89× |

At the V1 ceiling (128 universes), 5 seconds of show data encodes in 0.24 s and decodes
in 0.20 s on ordinary CPU hardware — roughly **20–25× faster than real time**, using a
single ffmpeg process with no GPU acceleration. This gives substantial headroom for
V1's real-time capture/playback requirement (§47), and room for the CPU budget to also
cover network I/O, audio, and (for playback) a second video decode for external video.

## 6. Audio in the same container

FFV1 video (grayscale, 150 frames) muxed with AAC audio (128 kbps, same 5 s duration)
into one Matroska file: mux succeeded, both streams decode, and the video stream
remained byte-for-byte lossless after the mux — **conditionally**. The first attempt
(letting ffmpeg pick its default `-vsync auto`/`fps_mode auto` behavior when a second
stream is present) silently duplicated one video frame at decode time (150 frames in →
151 decoded), even though the encoded file itself held exactly 150 frames
(`ffprobe -count_frames` confirmed this). Forcing `-fps_mode passthrough` (no implicit
frame retiming/duplication) on both encode and decode reproduced the input exactly.

This is a concrete, measured instance of the exact failure mode §16/§18/§62 of the spec
warn about in the abstract: **default, "convenience" frame-rate reconciliation between
multiple streams is not safe for DMX data.** The DMXReplay encoder/player must always
write and read frames using explicit frame counts / explicit timestamps and must never
rely on a generic transcoder's default stream-synchronization heuristics. This is now a
hard requirement in [`docs/TIMING.md`](docs/TIMING.md), not just a design preference.

## 7. Seeking

Measured as: process-spawn `ffmpeg -ss <t> -i file -frames:v 1 ...` wall time, at ~60%
into a 5 s file, across several of the cases above: consistently **60–105 ms**. This
number is dominated by ffmpeg *process startup* overhead in this CLI-driven harness
(a few dozen ms baseline per invocation seen even on trivial cases), not by Matroska/FFV1
seek cost itself — the real DMXReplay player will decode in-process (e.g. via PyAV),
where seeking to a keyframe-aligned position in an intra-only codec like FFV1 is
expected to be materially faster. **This number should be re-measured against the
actual player implementation in Phase 6/10, not treated as final.**

## 8. Not independently verified in this environment

This sandboxed Linux container has no display/GPU and cannot run TouchDesigner, VLC, or
Windows/macOS builds of anything. The following are carried over from the DMXReplay
container choice being deliberately unexotic (documented upstream facts, not this
project's own measurement) and **must be spot-checked on real target machines before
V1 ships**:

- **VLC compatibility** — VLC bundles its own libavcodec/libavformat (typically a
  recent FFmpeg release), so Matroska+FFV1 playback is expected to work out of the box;
  not independently confirmed here.
- **TouchDesigner compatibility** — TD's Movie File In TOP is FFmpeg-backed on
  Windows/macOS; Matroska+FFV1 is expected to be readable, but TD is not installed in
  this environment. Needs verification on a real TD install (tracked as a Phase 9/10
  follow-up).
- **macOS / Windows support** — FFmpeg, Matroska, and FFV1 are all cross-platform and
  widely packaged (Homebrew, the official ffmpeg.org Windows builds, etc.); no
  platform-specific blockers are known, but this repo's CI (once set up) should build
  and test on all three OSes rather than relying on this note.

## 9. Recommendation (final for V1)

| Decision | Choice | Justification |
|---|---|---|
| Container | **Matroska** (files exposed as `.dmxr`) | Only container tested that accepted every lossless codec candidate cleanly; native VFR timestamp support; native attachments for the metadata manifest; MP4 is hard-disqualified (§2.2), MOV has a codec-specific lossless bug on this build (§2.1). |
| Video codec | **FFV1** | Best compression of the lossless codecs tested (6.8×–11.9× vs. 1.3×–3.5× for HuffYUV/Ut Video), intra-frame (good seek granularity), and it round-tripped losslessly in every configuration tested. |
| Audio codec | **AAC** | As recommended in the brief; muxes cleanly alongside FFV1 in Matroska (§6), ubiquitous decoder support. |
| Pixel packing | **Grayscale required (V1 default)**, **RGB-packed optional** | Grayscale: simplest 1:1 mapping, easiest third-party re-implementation, human-inspectable. RGB-packed: ~42% smaller measured (§3), recommended for large/long recordings. Both declared via the `encoding` metadata field. |

This confirms the brief's proposed starting point (Matroska + FFV1 + AAC) as correct,
while replacing the "strong candidate" language with numbers, and adds two findings the
brief didn't anticipate: MP4 is not viable at all, and generic transcoder frame-sync
defaults are an active hazard the real implementation must avoid by construction (§6).

See [`docs/CONTAINER.md`](docs/CONTAINER.md) for the resulting physical-encoding
specification, and [`docs/SPECIFICATION.md`](docs/SPECIFICATION.md) §3–§7 for how this
maps onto the logical format.

## 10. Reproducing this benchmark

```bash
python3 benchmark/format_benchmark.py
```

Requires `ffmpeg`/`ffprobe` on `PATH`; uses GNU `time -v` when available for RSS/CPU
figures (falls back to wall-clock-only otherwise). Writes `benchmark/results.json` and
cleans up its own temporary encoded files.
