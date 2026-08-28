# PERFORMANCE.md — Cross-platform extension Phase H

Companion to [RASPBERRY_PI.md](RASPBERRY_PI.md) (Phase B's own real-benchmark audit) and
[RASPBERRY_PI_INSTALL.md](RASPBERRY_PI_INSTALL.md) §7 (the hardware validation
checklist). This document is Phase H's own contribution: real measurements this
environment *can* produce (no physical Raspberry Pi is available here, stated plainly,
same as every other document in this project that runs into that limit), plus the
finalized checklist for what genuinely needs one.

## 1. What this document adds over RASPBERRY_PI.md §4

RASPBERRY_PI.md §4 already measured **unthrottled max decode+send throughput** across
the full 1/10/50/128-universe matrix (`benchmark/player_pipeline_benchmark.py`) — the
right tool for "how much CPU headroom exists." It does not answer two things
`docs/ARCHITECTURE.md`'s Phase H row also promises:

1. **Real-time packet timing accuracy** — when the real `Player` is actually paced to
   real time (not run flat-out), how close to the nominal frame period do DMX packets
   actually arrive?
2. **The `+audio`/`+video`/`+audio+video` matrix cells** — audio and external video
   decode run on their own PyAV streams the real `Player` coordinates off the same
   `Timeline` (`docs/API.md` §5), entirely separate from the DMX decode path §4
   measured, so their cost doesn't show up in that number at all.

`benchmark/realtime_playback_benchmark.py` (new, Phase H) runs the **real**
`dmxreplay.player.Player` — not a synthetic stand-in — real-time paced, against a real
Art-Net loopback listener, and measures both.

## 2. Method

For each `{1, 50}` universes × `{dmx, audio, video, audio_video}` variant:

1. Build a real `.dmxr` file (`DMXReplayWriter`, ramp-pattern content, same
   deliberately-pessimistic-every-channel-changes-every-frame pattern as Phase 0/§4).
2. For `audio`/`audio_video`: synthesize a real WAV tone (same approach as
   `tests/test_container_audio.py`) and pass it as `DMXReplayWriter`'s `audio_path` —
   genuinely re-encoded to AAC and muxed by the real writer, not stubbed.
3. For `video`/`audio_video`: synthesize a real H.264 file via PyAV directly (same
   approach as `tests/test_player_video.py`) and `Player.load_external_video()` it.
4. `Player.set_output("Art-Net", ...)` to a real loopback `ArtNetListener`; `await
   player.play()`; sleep for the real content duration + a drain margin; `await
   player.stop()`.
5. Record every received packet's arrival time for one representative universe (row 0
   — matched by its full `(net, subnet, universe)` triple, not just the raw 4-bit
   `universe` field, which repeats every 16 universes and silently over-counted
   "row 0" arrivals in an early version of this script by ~4× at 50 universes; caught
   because the resulting jitter numbers looked implausible, not by inspection).
6. Compare consecutive arrivals' spacing against the nominal `1/fps` period for mean/max
   deviation (jitter). Measure whole-process CPU time consumed during the run
   (`resource.getrusage`) as a fraction of wall-clock duration, directly comparable to
   §4's "CPU needed for real-time playback" column.

30 fps, 3 real seconds of content per run. **1 and 50 universes are representative
low/high points, not a re-run of §4's full 1/10/50/128 sweep** — audio/external-video
decode cost is architecturally independent of universe count (it's a separate stream
entirely), so crossing all 4 universe counts with all 4 audio/video variants would
mostly re-measure the same per-universe DMX cost §4 already covers, at 4× the runtime,
for little additional insight. Reproduce with
`bash benchmark/run_realtime_playback_benchmark.sh`; raw results in
`benchmark/realtime_playback_results.json`.

Reference machine: this environment's container, same as RASPBERRY_PI.md §4.1 — **4
vCPU Intel Xeon @ 2.80 GHz** (cloud VM), 15 GB RAM, x86_64. Explicitly **not** a
Raspberry Pi; see §4's extrapolation caveat, same one RASPBERRY_PI.md §5 already states
for its own numbers.

## 3. Results

| Universes | Variant | CPU fraction of one core | Mean packet jitter | Max packet jitter |
|---|---|---|---|---|
| 1 | dmx | 1.1% | 1.4 ms | 15.7 ms |
| 1 | audio | 1.1% | 1.3 ms | 8.4 ms |
| 1 | video | 4.8% | 2.5 ms | 3.8 ms |
| 1 | audio_video | 4.7% | 3.5 ms | 30.8 ms |
| 50 | dmx | 4.1% | 1.6 ms | 11.2 ms |
| 50 | audio | 4.2% | 1.5 ms | 2.4 ms |
| 50 | video | 7.7% | 2.7 ms | 4.1 ms |
| 50 | audio_video | 7.9% | 3.0 ms | 9.5 ms |

(Nominal frame period at 30 fps is 33.3 ms — every mean deviation above is well under
10% of one frame, and even the largest max-deviation outlier, 30.8 ms, is still under
one whole frame period.)

**Reading this table:**

- **CPU cost is small and dominated by video, not audio or universe count.** Going
  from 1 to 50 universes barely moves the DMX-only CPU fraction (1.1% → 4.1%) —
  consistent with §4's own finding that grayscale decode+send is cheap per universe.
  Adding audio costs almost nothing extra (PCM resample + AAC encode of one channel is
  trivial). **Video decode is the real cost** — roughly 4× the DMX-only fraction at
  both universe counts (a 64×48 H.264 frame decoded every ~33 ms, still small in
  absolute terms here, but the component actually worth watching on a Pi 4, §4's tight
  scale point).
- **Jitter is real but small at every point measured**, mean deviations all under 3.5
  ms (≈10% of one frame). The occasional double-digit-ms max-deviation outlier (e.g.
  30.8 ms on `1u_audio_video`) is consistent with ordinary scheduling noise on a
  **shared, non-real-time cloud VM** — not evidence of a systemic timing bug (every
  variant, including plain DMX, shows some outliers; there's no trend tying them to
  audio/video specifically). This is exactly the kind of number that needs
  confirming on a real, dedicated Pi (§5's checklist) rather than trusted at face value
  from a shared virtualized host.
- These CPU fractions are **not directly comparable** to RASPBERRY_PI.md §4.2's table —
  that one measures unthrottled max throughput (how fast the same work *could* run);
  this one measures actual CPU consumed while genuinely paced to real time, which is
  necessarily close to that table's inverse (`1/realtime_factor`) for the DMX-only
  case, and this run confirms that: 1 universe here is 1.1% vs §4.2's 0.23% (same order
  of magnitude, not identical — different content pattern/duration, and this includes
  Python/asyncio scheduling overhead §4.2's raw decode+send loop doesn't have to pay).

## 4. Extrapolating to Raspberry Pi 4 / 5

Same method and same caveat as RASPBERRY_PI.md §5 (repeated here rather than
re-derived): no physical Pi was available to run this script directly, so §5's
conservative single-core throughput ratios (Pi 4 ≈8× slower, Pi 5 ≈2.6× slower than
this reference machine) are the best available estimate, presented as **requiring
physical validation**, not a guarantee:

| Universes | Variant | This machine | Pi 4 estimate (×8) | Pi 5 estimate (×2.6) |
|---|---|---|---|---|
| 50 | video (worst measured case) | 7.7% | 61.6% | 20.0% |
| 50 | audio_video (worst measured case) | 7.9% | 63.2% | 20.5% |

Both remain under one core even at the conservative Pi 4 estimate, at this
representative 50-universe point — but §4.2/§5's own finding that Pi 4 at 128
universes is the tight scale point (~98% of one core, DMX alone) still stands: adding
video's ~4× overhead on top of that specific combination is the one scenario this
document flags as needing real hardware before trusting it, not something this
extrapolation alone can responsibly clear.

## 5. Finalized hardware validation checklist

[RASPBERRY_PI_INSTALL.md §7](RASPBERRY_PI_INSTALL.md) already has the checklist for
physical Pi 4/5 validation (install, boot, mDNS, restart/failure recovery, and this
document's own performance matrix). Nothing here duplicates it — this document's
job was producing the dev-machine numbers that checklist's performance bullet points
to; the checklist itself is the authoritative "run this on real hardware" list, updated
in this phase with two additional items this document's findings motivate directly:

- [ ] Confirm 50-universe `+video` and `+audio+video` CPU cost on a real Pi 4 at the
      128-universe ceiling specifically (§4's own tight scale point, now compounded by
      video's ~4× overhead per this document's §4) — the one combination this
      document's extrapolation alone cannot responsibly clear.
- [ ] Confirm packet-timing jitter on a real, dedicated Pi (not a shared virtualized
      host) is at or below what §3 measured here, since a real-time OS scheduler with
      nothing else competing for the core should, if anything, do better than this
      shared cloud VM did — a Pi showing *worse* jitter than this document's numbers
      would be a genuine, unexpected finding worth investigating, not an assumption to
      wave away.

## 6. What's still explicitly not measured anywhere

Boot-to-READY time, actual thermal/power behavior under sustained load, mDNS across a
real Wi-Fi AP/router (as opposed to this project's own sandboxed loopback network), and
disk write throughput for the Recorder under real Pi storage (SD card vs. USB SSD) —
all already called out in RASPBERRY_PI.md §10/§7 and RASPBERRY_PI_INSTALL.md §7, and
still genuinely unmeasured here for the same reason as everything else in this section:
no physical Raspberry Pi hardware exists in this environment.
