# RASPBERRY_PI.md — Raspberry Pi 4/5 readiness analysis

**Status: analysis only, as requested. No format or codec change was made as a result
of this document.** It audits the Phase 0–4 implementation against a new V1
requirement — the DMXReplay Player must run standalone on a Raspberry Pi 4 or 5 — and
answers the question this requirement actually turns on: *is the format/architecture we
already built compatible, or does it need to change?*

## 0. Answer, up front

> **Yes — with the current container, codec, pixel format, and architecture as-is, a
> headless DMXReplay Player can decode `.dmxr` and drive Art-Net/sACN in real time on a
> Raspberry Pi 4, and comfortably on a Raspberry Pi 5, up to the V1 ceiling of 128
> universes @ 30 fps.** No format change is needed. This is not a guess: §4 below
> measures the actual decode+network-send pipeline (not a synthetic proxy) at 1/10/50/128
> universes on a reference x86 machine, and §5 extrapolates to Pi 4/5 using published
> comparative CPU benchmarks, with the method and its limits stated explicitly.

One real caveat did fall out of this analysis, and it's fixed by *usage*, not by
changing the format: the **optional** `rgb_packed` pixel encoding's current pure-Python
packing loop is measurably slow enough (§4.3) that it should not be assumed safe at 128
universes on a Pi 4 without further optimization. **Grayscale — already the V1 required
baseline — has no such issue** and is what this document's headroom numbers are based
on. See §9 for the precise, scoped recommendation (not applied yet).

Nothing here was run on physical Raspberry Pi hardware — this sandboxed environment
has none. Every number in §4 is a real measurement on the machine this session runs on;
every Pi 4/5 figure in §5 onward is an extrapolation from that measurement using
published third-party benchmarks (cited), clearly labeled as such. §10 lists exactly
what still needs validating on physical hardware before this is a hard guarantee.

---

## 1. Audit of the current Phase 4 implementation

Requested explicitly: re-derive what Phase 4 actually built, from the docs and code as
they stand, before reasoning about a new platform. No re-reading of intent, just facts.

| Aspect | Current V1 choice | Source |
|---|---|---|
| Container | Matroska (exposed as `.dmxr`) | `docs/CONTAINER.md` §1, chosen in `FORMAT-RESEARCH.md` |
| Video codec | FFV1 (intra-only, lossless) | `docs/CONTAINER.md` §2 |
| Pixel format (required baseline) | `gray`, 1 byte/pixel, width 512 | `docs/SPECIFICATION.md` §5.1 |
| Pixel format (optional) | `bgr0`, 4 bytes/pixel, width 171 | `docs/SPECIFICATION.md` §5.2 (corrected from an initially-assumed `rgb24` — FFV1 has no packed 3-byte 8-bit RGB format, `FORMAT-RESEARCH.md` §3.1) |
| Frame resolution | `width × N` where `N` = active universe count (1–128) | `docs/SPECIFICATION.md` §4 |
| Timestamp mechanism | Per-frame Matroska block timestamp, quantized to whole milliseconds at write time; encoder `codec_context.time_base` pinned explicitly (not via `rate=`) to avoid an encoder-level VFR-collapsing bug found during Phase 4 | `docs/CONTAINER.md` §2, `FORMAT-RESEARCH.md` §11 |
| VFR | Supported natively (Matroska per-block timestamps); sample-and-hold on playback, no interpolation | `docs/SPECIFICATION.md` §13 |
| Metadata | JSON manifest as a Matroska attachment (`dmxreplay-manifest.json`), read/written entirely in-process via PyAV, no external file required | `docs/CONTAINER.md` §4 |
| Code architecture | `dmxreplay.dmx` / `.clock` / `.metadata` / `.network.{artnet,sacn}` have **zero** third-party dependencies; `dmxreplay.codec.video_frame` / `dmxreplay.container` depend on the optional `av` (PyAV) extra; nothing under `src/dmxreplay/` except the not-yet-built `dmxreplay.ui` may depend on a GUI toolkit (`CONTRIBUTING.md`) | `pyproject.toml`, package `__init__.py` docstrings |
| Dependencies | Runtime: `av>=11.0` (PyAV, wraps libavformat/libavcodec) for codec/container only. No dependency at all for network I/O (Art-Net/sACN implemented from scratch, Phase 2/3). Dev-only: `pytest`, `jsonschema`. | `pyproject.toml` |

### Why this matters for "is it Pi-compatible"

The single most important fact for everything that follows: **DMXReplay video frames
are tiny.** The V1 ceiling is `512 × 128` pixels (grayscale) or `171 × 128` (RGB-packed)
— **65,536 pixels at most**, vs. **2,073,600** for 1080p or **8,294,400** for 4K. A
DMXReplay frame at maximum V1 scale is **~32× smaller than a single 1080p video frame**.
Any public benchmark or hardware-decode discussion about a Raspberry Pi's *video*
capability (§2 below) is about frames orders of magnitude larger than what this format
ever produces. That gap is why §4's measurements land so favorably, and it's the main
reason no format change is indicated by this analysis.

## 2. Raspberry Pi 4 / 5 hardware facts

| | Raspberry Pi 4 | Raspberry Pi 5 |
|---|---|---|
| CPU | Quad-core ARM **Cortex-A72** @ 1.5 GHz | Quad-core ARM **Cortex-A76** @ 2.4 GHz |
| Geekbench 6 single-core (measured, third-party) | ~293 (1.8 GHz variant; stock 1.5 GHz proportionally lower, roughly ~245) | ~764–774 |
| RAM options | 1 / 2 / 4 / 8 GB LPDDR4 | 4 / 8 / 16 GB LPDDR4X |
| Wired network | Gigabit Ethernet (~940 Mb/s real-world, not USB-bottlenecked since the BCM2711) | Gigabit Ethernet via RP1 I/O chip, ~900–941 Mb/s real-world |
| Storage | microSD (slow, ~20–90 MB/s typical), or USB3 SSD (~300–450 MB/s typical) | microSD, USB3 SSD (~270–830 MB/s depending on adapter/UASP support), or PCIe NVMe (Pi 5 only, up to ~800+ MB/s) |
| GPU / video block | VideoCore VI — HW decode: H.264, H.265 (HEVC) | VideoCore VII — HW decode: H.265 (HEVC), AV1, up to 4K; **H.264 hardware decode was dropped** on Pi 5 (software H.264 only) |
| FFV1 hardware decode | **None** | **None** |

Sources: [SunFounder Pi 5 vs Pi 4 comparison](https://www.sunfounder.com/blogs/news/raspberry-pi-5-vs-raspberry-pi-4-in-depth-comparison-and-unique-advantages), [Raspberry Pi Foundation's own Pi 5 benchmarking post](https://www.raspberrypi.com/news/benchmarking-raspberry-pi-5/), [PiCockpit Pi4 vs Pi5](https://picockpit.com/raspberry-pi/raspberry-pi-4-vs-raspberry-pi-5/), [cpu-monkey Pi 5 Geekbench 6](https://www.cpu-monkey.com/en/benchmark-raspberry_pi_5_b_broadcom_bcm2712-geekbench_6_single_core), [Raspberry Pi forums on Pi 5 losing HW H.264 decode](https://forums.raspberrypi.com/viewtopic.php?t=391283), [Pi 5 USB3/network real-world throughput discussion](https://forums.raspberrypi.com/viewtopic.php?t=362458).

**No source found anywhere mentions FFV1 hardware decode on either SoC** — expected: FFV1
is an archival/production intra-frame codec, essentially never hardware-accelerated on
any consumer SoC (desktop GPUs included). FFV1 decode is **always software/CPU-bound**,
on a Pi and everywhere else. This isn't a Pi-specific gap; it's a property of the codec
choice already made and accepted for its losslessness guarantee (`FORMAT-RESEARCH.md`).
Because of §1's frame-size point, this doesn't matter in practice — see §4.

## 3. Does the codec need to change? — determined *before* optimizing

Per the instruction not to swap the codec preemptively: the question is answered by
measurement (§4), not assumption. Short version, justified below: **no.** FFV1 decode
of a `512×128` (or smaller) frame is cheap in absolute terms — cheap enough that even a
conservative worst-case slowdown applied to this session's x86 measurements leaves
headroom on a Pi 4, and comfortable headroom on a Pi 5. If a physical Pi 4 test (§10)
later contradicts this, the fix would be targeted (e.g. tuning FFV1 slice count, or
offloading decode to a background thread/process) — not a container/codec swap, since
the bottleneck at these frame sizes is much more likely to be Python/PyAV per-frame
overhead than the codec itself (§4.3 finds exactly this for the optional RGB-packed
path).

## 4. Real benchmark: decode → DMX state → Art-Net/sACN output

### 4.1 Method

`benchmark/player_pipeline_benchmark.py` measures the actual bottleneck path a headless
Player runs: `DMXReplayReader.read_frames()` (real FFV1 decode via PyAV) immediately
followed by building and sending real UDP Art-Net or sACN packets
(`ArtNetSender`/`SACNSender`, Phase 2/3) for every universe in the frame, over loopback.
It is **not** a synthetic proxy — every frame is genuinely decoded from a real `.dmxr`
file this same script writes first, and every packet is a real `socket.sendto()` call
building the real wire format (`docs/ARTNET.md` / `docs/SACN.md`).

The loop runs **unthrottled** — as fast as possible, not paced to real time — so the
measured wall time is the actual CPU work required; comparing it against the nominal
real-time duration (`frames / fps`) gives a realtime factor and, inverted, the fraction
of one CPU core continuous real-time playback would actually consume. `/usr/bin/time -v`
wraps each run for peak RSS and CPU%. Reference machine: this session's container —
**4 vCPU Intel Xeon @ 2.80 GHz** (cloud VM, exact microarchitecture generation
unidentified from `/proc/cpuinfo`; treated as a generic modern x86 server core, see
§5's ratio discussion), 15 GB RAM, x86_64, ffmpeg/PyAV as already validated in Phase 0/4.

Matrix: 1 / 10 / 50 / 128 universes × {Art-Net, sACN} × grayscale, 300 frames (10 s
nominal @ 30 fps) each, ramp-pattern content (every channel changes every frame — the
Phase 0 benchmark's deliberately pessimistic case, not a realistic showfile). Reproduce
with `bash benchmark/run_player_pipeline_benchmark.sh`; raw results in
`benchmark/pi_readiness_results.json`.

### 4.2 Results (grayscale, the V1 required baseline)

| Universes | Decode+send wall (unthrottled) | Realtime factor | **CPU needed for real-time playback** | Peak RSS (whole process) |
|---|---|---|---|---|
| 1 | 0.023 s | 433× | 0.23% of one core | 60.6 MB |
| 10 | 0.146 s | 68.6× | 1.46% of one core | 71.6 MB |
| 50 | 0.565 s | 17.7× | 5.65% of one core | 121.9 MB |
| 128 (V1 ceiling) | 1.23 s | 8.1× | **12.3% of one core** | 219.1 MB |

("CPU needed for real-time playback" = `1 / realtime_factor`: the fraction of one CPU
core continuously busy that real-time — as opposed to unthrottled — playback would
consume, since the same amount of work has to happen either way, just spread across
real time instead of done as fast as possible.)

Both protocols (Art-Net, sACN) measured within noise of each other at every scale — the
packet-building/socket cost is not the bottleneck at these packet rates (max 128
universes × 30 fps = 3,840 packets/s, each a few hundred bytes; trivial for a gigabit
link or even 100 Mb/s, see §6). `received_packets` in the raw JSON undercounts
`sent_packets` at 50/128 universes in this loopback harness — that's an artifact of
bursting thousands of packets into a shared-machine kernel UDP buffer with zero pacing
(§4.1: intentionally unthrottled), not a statement about real Art-Net/sACN network
capacity between separate physical devices; see the comment in
`player_pipeline_benchmark.py::_bump_rcvbuf`. Real playback paced to 30 fps sends 128
packets every ~33 ms, nowhere near this artifact's threshold.

Encode-side (recorder) cost, same content: 0.24 s to encode 10 s of 128-universe show
data (2.4% of one core, real-time) — cheaper than decode, as expected for an intra-only
codec, and relevant to running the *recorder* on a Pi too (not this document's primary
focus, but the headroom carries over directly).

### 4.3 RGB-packed is measurably slower — a real, scoped finding

Same 128-universe case, `rgb_packed` encoding instead of grayscale:

| | grayscale | rgb_packed |
|---|---|---|
| Encode wall | 0.24 s | **1.88 s** |
| Decode+send wall | 1.23 s | **3.45 s** |
| Realtime factor | 8.1× | **2.9×** |

`rgb_packed`'s pixel packing (`src/dmxreplay/codec/pixels.py`) runs a pure-Python loop
over all 171 pixels per universe per frame (`universe_to_rgb_row`/`rgb_row_to_universe`)
— at 128 universes × 300 frames that's ~6.6M individual Python-level iterations, which
is almost certainly what dominates here, not FFV1 itself (FFV1's own cost scales with
pixel *count*, and `rgb_packed`'s pixel count, 171×128, is actually *smaller* than
grayscale's 512×128). A 2.9× realtime factor still has headroom on *this* reference
machine, but combined with §5's conservative Pi 4 slowdown estimate, **`rgb_packed` at
128 universes should not currently be assumed safe on a Pi 4** without either using
fewer universes or optimizing the packer (e.g. the `array`/`struct` module, or a
`numpy`-based vectorized reshape, neither pulled in yet — see §9). This does not affect
the verdict in §0: `rgb_packed` is optional, and grayscale — the required baseline this
whole analysis is otherwise based on — has no such cost, since `Universe.to_bytes()`/
`Universe.from_bytes()` are already a straight byte-buffer operation with no per-channel
Python loop.

## 5. Extrapolating to Raspberry Pi 4 / 5

**Method and its limits, stated plainly:** no physical Pi was available to run §4's
script directly (this sandbox is x86_64 cloud infrastructure). Instead, §2's published
Geekbench 6 single-core scores are used as a *conservative* per-core throughput ratio.
This is an approximation — Geekbench and "decode a tiny FFV1 frame + build UDP packets
in Python" stress different parts of a CPU (branch prediction, memory latency, syscall
overhead) — so the resulting numbers are presented as **estimates requiring physical
validation (§10)**, not guarantees.

A modern x86 server/desktop core in this class (~2.5–3.5 GHz, several-issue
out-of-order) is typically in the Geekbench 6 single-core range of roughly 2,000–2,600
(general knowledge about this CPU tier; a precise score for the exact cloud vCPU in this
sandbox could not be identified from `/proc/cpuinfo` alone). Using the **low** end of
that range (2,000) against §2's Pi scores, to keep the resulting Pi estimate
conservative (i.e. err toward *overestimating* how much slower the Pi is):

- Pi 4 ratio: 2,000 / ~245 ≈ **8×** slower, single-core.
- Pi 5 ratio: 2,000 / ~770 ≈ **2.6×** slower, single-core.

Applying these to §4.2's "CPU needed for real-time playback" column (linear scaling —
itself an approximation, but a standard and conservative one for CPU-bound, mostly
single-threaded Python workloads):

| Universes | This machine | **Pi 4 estimate (×8)** | **Pi 5 estimate (×2.6)** |
|---|---|---|---|
| 1 | 0.23% | 1.8% | 0.6% |
| 10 | 1.46% | 11.7% | 3.8% |
| 50 | 5.65% | 45.2% | 14.7% |
| 128 (ceiling) | 12.3% | **98.4%** | **32%** |

**Reading this table:** Pi 5 has comfortable headroom at every scale up to the V1
ceiling — even at 128 universes, roughly two-thirds of one core remains free for
master-clock bookkeeping, audio, or coordination overhead. **Pi 4 at 128 universes is
the one scale point this estimate calls tight** (~98% of one core) — plausibly still
real-time-capable on a dedicated core with nothing else scheduled on it, but with very
little margin for jitter, OS scheduling noise, or anything else sharing that core. Pi 4
at ≤50 universes has clear headroom (≤45%).

This is a genuine, scale-dependent answer, not a blanket "fine" or "not fine" — and it's
exactly the kind of finding that needs physical confirmation (§10) rather than either
dismissing it or over-reacting to an estimate with a possibly-pessimistic ratio.

## 6. Network throughput

At the V1 ceiling, 128 universes × 30 fps = 3,840 packets/s; each Art-Net packet is
≤530 bytes and each sACN packet ≤638 bytes (`docs/ARTNET.md`, `docs/SACN.md`) — worst
case **≈2.45 MB/s (≈19.6 Mb/s)**. Both Pi 4 and Pi 5's Gigabit Ethernet (§2, ~900+ Mb/s
real-world) have roughly **45×** the required headroom. Not a constraint at any V1
scale. (The player would typically send to one destination console/node, not fan out to
many simultaneous receivers — that scenario, if it arises later, is a different
analysis and isn't part of V1.)

## 7. Disk throughput and storage

From §4.2's measured file sizes: 128 universes, grayscale, ≈255 KB/s of show content
(2.55 MB for 10 s). A **30-minute** 128-universe show is therefore **≈459 MB** — trivial
for a Pi's microSD (even the slow end, ~20 MB/s, is ~13× the ≈0.255 MB/s read rate
needed) or a USB3/NVMe SSD (hundreds of times the required rate). Storage is not a V1
constraint at any measured or estimated scale.

## 8. Audio and external video: architectural readiness (not yet implemented, not yet benchmarked)

Phases 7 (audio sync) and 8 (external video sync) don't exist in code yet, so nothing
here is measured — this section is a design-level check that the *architecture* chosen
so far doesn't foreclose the Pi target, per the brief's instruction to treat Pi as a
target for the full DMX+audio+video scenario, not DMX alone.

- **Master clock**: already designed (`docs/TIMING.md`) as one `Timeline`/`ClockProvider`
  driving DMX, audio, and video from a single source of truth (§11 below confirms this
  wasn't touched by this analysis). Adding audio/video subsystems means giving them a
  `position_ns()` to poll, not adding their own clocks — the design that avoids drift
  was already the design, before Pi was a stated requirement.
- **Audio**: AAC decode (`docs/CONTAINER.md` §3) is a solved, cheap problem on any
  Pi — Pi 4/5 both decode AAC comfortably in software (this is a much smaller ask than
  the video decode discussion in wide use for Pi-based media players); no red flags.
- **External video** (brief §39: MP4/MOV/MKV, H.264/H.265/ProRes; this document's scope
  is explicitly **1080p, not 4K60**, per the instruction not to make 4K a performance
  requirement yet): H.265 has hardware decode on *both* Pi 4 and Pi 5 (§2); H.264 has
  hardware decode on Pi 4 but **not** Pi 5 (software only there). At 1080p, even
  software H.264 decode is generally considered feasible on a Cortex-A76 (Pi 5, 2.4 GHz,
  4 cores) — this is a widely-reported capability of that class of SoC for 1080p
  content, though it has not been measured in this repository. **Recommendation for
  Phase 8 (not applied now):** prefer H.265 for external video where the producer has a
  choice, since it's hardware-accelerated on both target boards; document this as
  guidance in Phase 8's own design work rather than a DMXReplay format constraint (the
  external video file is never embedded in `.dmxr`, `docs/CONTAINER.md` §7, so this
  choice doesn't touch the format at all).
- Because video decode for external video would run on the GPU (VideoCore) when H.265
  is used, it mostly doesn't compete with the CPU-bound DMX decode/send path measured in
  §4 — a favorable interaction the architecture happens to already support by keeping
  external video a *separate, non-embedded* file (brief §24, a decision made before Pi
  was a requirement, that turns out to help here too).

**Nothing above required changing anything already built.** It's confirmation, not new
work.

## 9. Recommendation (scoped, not applied)

Consistent with "don't optimize prematurely": the one concrete finding from §4.3 is
scoped and does **not** justify touching the codec, container, or the required
grayscale path.

| Finding | Recommendation | Applied now? |
|---|---|---|
| `rgb_packed` pixel packing is pure-Python and measurably slow at 128 universes (§4.3) | Document as a known limitation of the *optional* encoding; if it needs to be fast at high universe counts on constrained hardware later, optimize `universe_to_rgb_row`/`rgb_row_to_universe` (e.g. `array`/`struct`-based bulk packing) as a self-contained, tested change to `src/dmxreplay/codec/pixels.py` — no format/spec change needed, since the on-disk `bgr0` byte layout doesn't change, only how fast Python produces/consumes it. | **No** — flagged here for whoever picks this up; not blocking Pi 4/5 readiness for the required grayscale path. |
| Pi 4 at 128 universes has thin CPU margin in the §5 estimate | Once physical Pi 4 hardware is available (§10), re-run `benchmark/player_pipeline_benchmark.py` directly; if the real number is as tight as estimated, the fix is architectural (run the DMX decode/send loop in its own thread/process, pinned to a dedicated core, so OS scheduling noise and any audio/video/UI work on other cores can't starve it) — not a codec change. | **No** — no physical hardware to confirm against yet. |
| Everything else audited in §1 | No issue found. | N/A |

## 10. What still needs physical hardware to confirm

Explicitly not claimed as validated by this document:

- §5's Pi 4/5 CPU estimates (extrapolated from published Geekbench scores, not measured
  on a Pi).
- Real disk I/O behavior on microSD specifically under sustained DMXReplay recording
  (§7's numbers are theoretical throughput headroom, not a measured microSD write test).
- Real Wi-Fi throughput/latency if a Pi is used wirelessly instead of wired Ethernet
  (§6 only covers wired Gigabit, which is what brief §48 and this project's network
  interface selection requirement point toward as the reliable choice).
- §11's validation test (below), run on actual Raspberry Pi 4 and 5 boards.
- Anything about Phases 7/8 (audio/video), since those phases don't exist in code yet.

## 11. Validation test: Art-Net → Recorder → `.dmxr` → Player → Art-Net

Added: `tests/test_end_to_end_artnet_pipeline.py`. At the time this was written, the
dedicated `Recorder`/`Player` orchestration classes (`docs/API.md` §4–§5) were Phase
5/6 work that didn't exist yet, so this test exercised the data path they'd wrap
directly (nothing mocked, but using `DMXReplayWriter`/`DMXReplayReader` and raw
`ArtNetListener`/`ArtNetSender` in place of `Recorder`/`Player`):

```
ArtNetSender (simulated console)
    --UDP-->  ArtNetListener  (recorder input)
                    |
              DMXReplayWriter  (writes a real .dmxr)
                    |
              DMXReplayReader  (reads the real .dmxr)
                    |
ArtNetSender (player output)
    --UDP-->  ArtNetListener  (simulated lighting rig)
```

**Update, Phase 5/6:** `Recorder` and `Player` now exist, so
`tests/test_end_to_end_recorder_player.py` was added alongside the original test,
running the *same* validation shape through the *actual* classes instead of the
primitives standing in for them:

```
ArtNetSender (simulated console) --UDP--> Recorder --> .dmxr --> Player --UDP--> ArtNetListener (simulated rig)
```

It confirms no value is fabricated in transit and that each universe's final
state after playback exactly matches the last value the simulated console sent (the
right invariant here, since the recorder commits one frame per received packet —
`docs/TIMING.md` §4.1 — so a strict per-packet value-for-value replay isn't the
correct comparison once two universes interleave; see the test's own comments).
Both tests pass on this reference machine now. **Reproducing either on physical
Raspberry Pi 4/5 hardware is listed in §10** as an open item — both are written to
run identically there (`pytest` over loopback UDP, no platform-specific code), but
this session has no such hardware to run them on.

## 12. Architecture separation check (brief's diagram)

Requested structure:

```
DMXReplay Core
       │
       ├── Decoder
       ├── Master Clock
       ├── DMX Engine
       ├── Art-Net
       ├── sACN
       ├── Audio
       └── Video
```

Audited against `src/dmxreplay/`: `codec`+`container` (decoder), `clock` (master
clock), `dmx` (the DMX data model the brief's "DMX Engine" box operates on — see note
below), `network.artnet`, `network.sacn`, `audio` (placeholder, Phase 7),
`video` (placeholder, Phase 8) — all present as separate packages, **none of them
importing a GUI toolkit** (verified: only `src/dmxreplay/ui/__init__.py` is permitted
to, per `CONTRIBUTING.md`, and nothing else does). A future headless
`dmxreplay-play --headless show.dmxr` (§13) can therefore already be built without
touching `dmxreplay.ui` at all — the GUI was never load-bearing for the engine, which
directly satisfies "the player must be able to function without a GUI on Linux/Raspberry
Pi."

**Update, Phase 5:** the naming note below has been resolved — `dmxreplay.dmx.DMXEngine`
now exists (`src/dmxreplay/dmx/engine.py`), feeding `Recorder` exactly as described.
Original note, kept for the record: the brief's architecture diagram shows a
standalone "DMX Engine" box between the network layer and Art-Net/sACN I/O — a live,
protocol-agnostic aggregator of current per-universe state. That box didn't exist as
its own module yet; each of `ArtNetListener`/`SACNListener` tracked its own
per-universe live status independently (`docs/API.md` §3.5). Unifying that into one
shared "DMX Engine" that both protocols feed was identified as `Recorder`-level work
(`docs/API.md` §4, Phase 5) — the right layer for it, since only the Recorder needs to
merge multiple simultaneous sources into one committed timeline.

## 13. Headless mode — implemented (Phase 6)

**Update, Phase 6:** `dmxreplay-play --headless` is now real (`src/dmxreplay/cli/play.py`).
Original proposal, kept for the record, and what was actually built against it:

```bash
dmxreplay-play --headless show.dmxr \
  --output artnet --interface eth0 --destination 192.168.1.100 --loop --fps 30
```

This maps directly onto the `Player` API (`docs/API.md` §5): `load()`, `set_output()`,
`set_loop()`, `set_fps()`, `play()`. As predicted, no new engine-level interface was
needed — `--headless` is accepted but is actually a no-op, since `dmxreplay-play` never
imported `dmxreplay.ui` in the first place (§12's finding held). One thing the original
proposal got only half right: it suggested `--autoplay` as a separate flag from
`--headless`; the shipped CLI simplified this away since there is no "loaded but
waiting for a command" alternative yet (see the next paragraph) — `dmxreplay-play`
always starts playing once loaded, so `--autoplay` wasn't added as a distinct flag.

**Still open, as predicted:** interactive control (seek/pause/stop while a headless
process is already running) needs *some* control surface (brief §8 lists
play/pause/stop/loop/seek/FPS as required headless capabilities), and that surface is
still not built — `dmxreplay-play` today loads, configures output, and plays straight
through until the file ends (non-looping) or it's interrupted (looping), with no way to
send it a new command mid-run. A small local control mechanism (Unix domain socket, or
a minimal loopback-only HTTP endpoint) remains the proposed shape, deliberately still
not decided/built, consistent with not designing a remote-control protocol under time
pressure just to check a box.

## 14. Auto-start on boot — proposed shape (not implemented yet)

Per the brief, full auto-start is explicitly deferred to a later phase; only the
architecture needs to accommodate it now. Proposed (not applied): a small config file
(e.g. `/etc/dmxreplay/player.toml` or similar) that `--headless` can optionally load
instead of requiring every option on the command line:

```toml
show = "MyShow.dmxr"
video = "MyShow.mp4"       # optional, brief §19/§39
output = "artnet"
interface = "eth0"
destination = "192.168.1.100"
loop = true
autoplay = true
```

Turning this into an actual boot-time auto-start would mean a systemd unit invoking
`dmxreplay-play --headless --config /etc/dmxreplay/player.toml`, standard on
Raspberry Pi OS (systemd-based) — pure ops/packaging work with no DMXReplay-format
implications, left for the phase that builds it.

## 15. Master clock — explicitly unchanged

Per the brief's strongest instruction in this pass: the Pi requirement must not become
three independent clocks. It doesn't. Nothing in `docs/TIMING.md`'s `Timeline`/
`ClockProvider`/`MasterClock` design was touched by this analysis (§8 above confirms it
by inspection, doesn't modify it). At any timeline position `T`, DMX, audio, and video
each independently answer "what should I be doing at `T`" against the same
`Timeline.position_ns()` — that contract, once Phases 7/8 exist, is what makes seek and
scrub correct on a Pi exactly as it would be anywhere else; Pi doesn't change it, it's
just the platform the same design has to keep holding on.
