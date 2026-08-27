# TIMING.md — Clocks, timestamps, VFR, and the master timeline

Companion to [SPECIFICATION.md §11–§14](SPECIFICATION.md#11-timestamp-format). This
document is the detailed rationale and design for DMXReplay's timing model — the part
of the brief (§15–§23, §38, §40–§42, §62) that most determines whether the format
actually delivers reliable synchronization, so it gets its own document.

## 1. Guiding principle

> Every subsystem must be able to answer: **"What should I be doing at time T?"**

DMXReplay is built around one **master timeline**, not three independently-running
clocks that happen to start together. This is not a stylistic preference — it is the
only design that makes seeking, reverse playback, and looping behave correctly by
construction, and it is what the empirical finding in
[FORMAT-RESEARCH.md §6](../FORMAT-RESEARCH.md#6-audio-in-the-same-container) validated:
letting a generic tool's default stream-sync heuristics reconcile "video" and "audio"
independently silently duplicated a DMX frame. If DMX drives lighting hardware
(dimmers, movers, pyro), a silently duplicated or dropped frame is not a cosmetic bug.

```
                    MASTER CLOCK
                         │
          ┌──────────────┼──────────────┐
          │              │              │
         DMX           Audio          Video
          │              │              │
       Art-Net          DAC          Decoder
          │
       Lighting
```

## 2. Two clocks, two timelines

- **Capture timeline** (recording time): the actual, monotonic, high-resolution
  timestamp at which each DMX packet was received. Never derived from an assumed frame
  rate.
- **Playback timeline** (player time): the position on the master timeline that
  determines "what DMX state, what audio sample, what video frame is current right
  now." Playback timeline position advances at `speed × real time` while playing
  (brief §17's speed control), jumps discontinuously on seek (§21), and can run
  backward during reverse playback (§22).

A frame's stored timestamp (SPECIFICATION.md §11) always refers to the **capture**
timeline. The player's job is to map "current playback timeline position" to "which
stored frame is current" — via sample-and-hold (SPECIFICATION.md §13), never by
assuming a fixed frame index arithmetic.

## 3. Capture-side clock requirements

- MUST be monotonic (immune to NTP/wall-clock adjustment stepping backward).
- MUST be high-resolution at the **in-memory capture** stage — V1 targets
  microsecond-order effective resolution there (implementation- and OS-dependent).
  **This is not the same thing as what ends up on disk.** Once Phase 4's actual
  container/codec toolchain is in the loop, the *stored* precision is coarser: ~1 ms,
  a hard property of this toolchain's Matroska muxer (no finer `TimecodeScale` is
  exposed) and of the video encoder's own time base, which must be pinned to match it
  explicitly or timing is lost even earlier, inside the encoder (both measured, not
  assumed — see FORMAT-RESEARCH.md §11). `timestamp_resolution_ns` in the manifest
  records this *stored* precision (currently `1,000,000` ns for files from the
  reference writer) — do not hard-code an assumed value, and do not read it as a claim
  about the capture clock's own precision.
- Reference implementation: Python `time.monotonic_ns()` (POSIX
  `CLOCK_MONOTONIC`/`CLOCK_MONOTONIC_RAW`-backed on Linux/macOS,
  `QueryPerformanceCounter`-backed on Windows via the interpreter).
- The recorder timestamps a DMX frame at the moment it **finishes assembling** a
  complete, committed update for the DMX engine's current state (i.e., after applying
  an incoming packet to the relevant universe's buffer), not at UDP-socket-receive time
  alone, so that timestamp jitter reflects processing-relevant timing rather than raw
  kernel scheduling noise. (Both are close in practice; this is a documented choice, not
  an unstated assumption.)

## 4. Why VFR, and how it's stored

V1's *nominal* rate is 30 fps, but real Art-Net/sACN senders do not emit packets on a
perfectly regular 33.3ms grid — consoles, network stacks, and multiple senders all
introduce jitter, and some sources intentionally send at non-30fps rates. Silently
snapping every packet onto a fixed 30fps grid would **destroy real timing information**
(brief §16) — exactly the failure mode this spec exists to avoid.

DMXReplay therefore permits **Variable Frame Rate** storage: each video sample in the
container carries its own timestamp (Matroska block timestamps — see
[CONTAINER.md](CONTAINER.md) and [FORMAT-RESEARCH.md](../FORMAT-RESEARCH.md) for why
Matroska was chosen partly for this). The manifest's `fps` field remains meaningful as
the *nominal* rate (useful for UI display, rough duration estimates, and as the default
playback rate), while `vfr: true` tells a reader "do not assume the `fps` field implies
equal spacing — trust each frame's own timestamp."

### 4.1 Encoder strategy (capture → stored frames)

The encoder (Phase 4) writes one stored video frame per **committed DMX engine update**
— i.e., whenever the recorder decides a new frame is worth persisting (typically: any
received packet changes at least one active universe's state, rate-limited to avoid
pathological per-packet frame explosion under a very high packet rate source — see
brief Test 6, "High packet rate"). The exact commit policy (e.g. minimum inter-frame
spacing, coalescing multiple packets arriving within one scheduler tick) is an
implementation detail of the recorder and MUST be documented in its own release notes
if changed, since it affects the *storage* granularity — but it never affects the
*meaning* of a stored frame's timestamp, which is always "this DMX state was correct
starting at this timestamp until the next stored frame's timestamp."

## 5. Playback rate control and sample-and-hold

Changing playback FPS (brief §17) changes how often the player *asks* "what should DMX
be doing right now" — never the stored values. Given playback timeline position `T`:

```
active_frame(T) = the stored frame with the greatest timestamp <= T
DMX_state(T) = active_frame(T).channel_values
```

This is a pure zero-order hold. No interpolation between `active_frame(T)` and the next
frame is performed unless a future, explicitly-opt-in interpolation mode is added — it
is not part of V1 and must never happen implicitly (SPECIFICATION.md §13).

## 6. Seeking, reverse playback, and looping

- **Seek**: set playback timeline position `T` directly; recompute `active_frame(T)`
  for DMX, and instruct audio/video decoders to present their content at `T`. All three
  MUST reflect `T` before the player reports the seek complete.
- **Reverse playback**: playback timeline position decreases over real time instead of
  increasing. `active_frame(T)` is computed identically (same sample-and-hold formula —
  it is direction-agnostic by construction, since it only depends on the *value* of
  `T`, not the direction it's moving).
- **Loop**: on reaching the end of the timeline (or the configured loop out-point), `T`
  resets to the start (or in-point) on the same tick for every subsystem — implemented
  as a seek to `T=0`, reusing the same code path rather than a special case.

## 7. `ClockProvider` abstraction (future timecode sources)

V1 ships exactly one clock provider: the **internal clock**, a free-running
monotonic timer that advances the master timeline during playback. The `Clock` API
([API.md](API.md)) is deliberately provider-agnostic:

```
             Clock Provider
                  │
       ┌──────────┼──────────┐
       │          │          │
    Internal     LTC       MTC
       │
       ▼
  Master Timeline
       │
 ┌─────┼─────┐
 ▼     ▼     ▼
DMX   Audio Video
```

A future provider (SMPTE/LTC, MIDI Time Code, Art-Net TimeCode — see
[ARTNET.md](ARTNET.md) §7 — sACN sync, MIDI Clock, Ableton Link) would implement the
same `getPosition()`/timeline-driving contract as the internal clock, without any
DMX/audio/video subsystem needing to change: they always ask the *current provider*
"what time is it," never a specific provider directly. This is why `Clock` is specified
as an abstract interface in [API.md](API.md) rather than a concrete free-running timer
baked into `Player`.

The internal timeline is always **absolute time** (nanoseconds since recording start),
never BPM/musical-beat-relative (brief §42) — a future LTC/timecode mapping is a
straightforward absolute-time-to-absolute-time conversion, not a reinterpretation of
what the timeline fundamentally measures.

## 8. Synchronization tolerance

A numeric tolerance for "DMX/audio/video are considered in sync" is required by
SPECIFICATION.md's Test 9 (synchronization test) but cannot be honestly claimed until
it is measured against the real player (Phase 8/10) rather than asserted in advance.
Placeholder target, to be confirmed empirically and updated here once Phase 8 lands:
**±1 frame at the external video's own frame rate** (e.g. ±33ms at 30fps external
video) between the video track's presented frame and the DMX state considered "current"
at the same master-timeline position. This document will be updated with the measured
figure rather than left as an aspirational placeholder once that test exists.
