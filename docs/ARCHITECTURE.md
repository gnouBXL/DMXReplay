# ARCHITECTURE.md — Cross-platform / Raspberry Pi / Smartphone audit

Companion to [SPECIFICATION.md](SPECIFICATION.md) (the file format) and
[API.md](API.md) (the core engine's Python API). This document is the audit and phased
plan requested for extending completed DMXReplay V1 (desktop-only, Phases 0–10, all
done — see `README.md`'s roadmap and `CHANGELOG.md`) into a cross-platform ecosystem:
Windows, macOS, Raspberry Pi 4/5, and smartphone control (with standalone mobile
record/playback evaluated, not assumed).

Per the extension brief's own instruction (§32): **this is the audit and the plan, not
the implementation.** Nothing under `src/dmxreplay/` changes in this pass. Phased
implementation starts only once a phase is chosen to begin.

## Contents

1. [What already works](#1-what-already-works)
2. [What can be reused as-is](#2-what-can-be-reused-as-is)
3. [What needs to change](#3-what-needs-to-change)
4. [What should not change](#4-what-should-not-change)
5. [What is platform-specific](#5-what-is-platform-specific)
6. [What is impossible or risky](#6-what-is-impossible-or-risky)
7. [Proposed phased plan](#7-proposed-phased-plan)
8. [Open questions before starting](#8-open-questions-before-starting)

---

## 1. What already works

Verified by inspection and by the existing test suite (167 passed, 1 skipped as of
Phase 10), not assumed:

- **The `.dmxr` format is already platform-independent by construction.** It's
  Matroska + FFV1 + a JSON manifest attachment (`docs/CONTAINER.md`), decoded via PyAV
  (`av`), which wraps ffmpeg — none of that is OS-specific. A file written on this
  Linux sandbox will decode identically on Windows/macOS/Pi; nothing in the format
  encodes host paths, endianness assumptions, or OS-specific metadata.
- **The core engine (`src/dmxreplay/`) has exactly one non-stdlib runtime dependency
  with native code: `av` (PyAV).** Checked just now against the real PyPI file index
  for the current release (18.1.0): prebuilt wheels exist for `win_amd64`, `win_arm64`,
  `macosx_x86_64`, `macosx_arm64` (Apple Silicon), and `manylinux_aarch64` /
  `musllinux_aarch64` (64-bit Raspberry Pi OS, both glibc and musl). This is the single
  most important fact behind Phase A/B being low-risk: the packaging problem is not
  "does our one C-extension dependency exist on these platforms" — it already does.
  `sounddevice` (optional, `[audio]` extra) similarly ships wheels for Windows/macOS and
  works on Linux against the system `libportaudio2` (already documented in
  `pyproject.toml`).
- **Everything else in the core has zero third-party dependencies** —
  `dmxreplay.dmx`, `.clock`, `.metadata`, `.network` (Art-Net and sACN are both
  hand-rolled from the wire spec, `docs/ARTNET.md`/`docs/SACN.md`), `.recorder`,
  `.player`, `.preview` are pure Python + `asyncio` + `socket`. Checked the actual
  socket calls used: `ArtNetListener`/`ArtNetSender` use only
  `asyncio.create_datagram_endpoint(..., allow_broadcast=True)`, which is portable.
  `SACNListener` uses `SO_REUSEADDR`/`IP_ADD_MEMBERSHIP` (both portable) and already
  guards `SO_REUSEPORT` behind `hasattr(socket, "SO_REUSEPORT")` — i.e. someone already
  wrote this defensively for a platform where that constant doesn't exist (it's absent
  on Windows), even though nobody explicitly targeted Windows before now.
- **The master clock is already portable and already correct for the "smartphone
  must not become the master clock" requirement (§14/§30 of the extension brief).**
  `InternalClockProvider` is `time.monotonic_ns()` — CLOCK_MONOTONIC on POSIX,
  QueryPerformanceCounter-derived on Windows, explicitly chosen over wall-clock time
  specifically because wall-clock can step backward (`docs/TIMING.md` §3). `Player`
  already has exactly one `Timeline` per instance, driving DMX/audio/video from a
  single `position_ns()` read per tick (`_run_loop()` in `player.py`) — this *is*
  already "one master clock on the device doing real-time output," which is precisely
  what §30's "correct" architecture diagram requires. A remote controller was never
  part of this loop; there's nothing to remove.
- **Headless operation already exists and was already designed with this exact
  extension in mind.** `dmxreplay-play --headless` (`src/dmxreplay/cli/play.py`) never
  imports a GUI toolkit — confirmed: `src/dmxreplay/ui/` exists only as an empty
  placeholder package (one 157-byte `__init__.py`, no code). `docs/RASPBERRY_PI.md` §13
  already identifies, in its own words, *exactly* the gap this extension brief calls
  Phase D: "interactive control (seek/pause/stop while a headless process is already
  running) needs some control surface... that surface is still not built." §14 already
  sketches a config-file shape (`AUTOSTART`/`DEFAULT_SHOW`/`OUTPUT`/etc. — almost
  identical field names to the extension brief's §6 example) and a systemd unit,
  explicitly marked "proposed shape, not implemented." This audit is not discovering a
  new requirement here; it's confirming a two-phases-ago analysis was accurate and
  picking up exactly where it said to stop.
- **Discovery of what's currently missing is itself already fully covered by tests
  that will catch any regression while building the extension**: 167 tests across
  format round-trips, Art-Net/sACN wire parsing, recorder/player conformance
  (`tests/test_conformance.py`, Phase 10), and end-to-end pipelines. Any refactor done
  to support this extension has an existing safety net.

## 2. What can be reused as-is

Everything in `src/dmxreplay/` except the CLI entry points (§3 below) is the
"DMXReplay Core" the extension brief's §2 architecture diagram calls for — one
authoritative implementation of DMX decoding/encoding, the timeline, sync, `.dmxr`,
Art-Net, and sACN, already satisfying "do not create three independent
implementations":

| Module | Reused unchanged for |
|---|---|
| `dmxreplay.dmx` | Every platform (data model) |
| `dmxreplay.clock` | Every platform (Timeline/MasterClock/ClockProvider) |
| `dmxreplay.metadata` | Every platform (`.dmxr` manifest schema) |
| `dmxreplay.network.artnet`/`.sacn` | Desktop + Raspberry Pi (wire protocols) |
| `dmxreplay.codec`, `dmxreplay.container` | Desktop + Raspberry Pi (`.dmxr` I/O) |
| `dmxreplay.recorder` | Desktop + Raspberry Pi (capture engine) |
| `dmxreplay.player` | Desktop + Raspberry Pi (playback engine) |
| `dmxreplay.audio`, `dmxreplay.video` | Desktop + Raspberry Pi (sinks/readers) |
| `dmxreplay.preview` | Anywhere a row's DMX state needs visualizing |

For Windows/macOS/Raspberry Pi, the plan is literally "run this same Python package" —
not a rewrite, not a reimplementation, not a second engine. The only genuinely new
*engine-adjacent* code needed on the Pi side is the **control surface** §1 already
flagged as missing (a long-running process that a network API can send commands to
instead of `dmxreplay-play` running once to completion) — that's new code, but it's a
thin layer calling the exact same `Player` methods the CLI already calls, not new DMX
logic.

Smartphone reuse is fundamentally different — see §6.

## 3. What needs to change

Concrete gaps, each traced to a specific requirement in the extension brief:

1. **No long-running, commandable Player process exists.** `dmxreplay-play` loads,
   configures output, and plays straight through to completion or Ctrl+C
   (`play.py`'s own docstring says this explicitly). The extension brief's §7/§8
   (smartphone play/pause/seek/next/previous over a network API) requires a process
   that stays alive after `play()` returns and accepts new commands — `Player`'s
   Python API already supports this (`pause()`, `seek()`, `frame_step()`,
   `set_loop()`, etc. can all be called at any time while a `_run_loop()` task is
   running), the CLI just never exposed a way to call them from outside the process.
2. **No network Control API.** Nothing under `src/dmxreplay/` speaks HTTP or
   WebSocket today. This is new: a thin service layer (§7's Phase D) wrapping
   `Recorder`/`Player` — GET_STATUS, GET_SHOWS, LOAD_SHOW, PLAY/PAUSE/STOP/SEEK,
   NEXT/PREVIOUS, RECORD_START/STOP, GET_CONFIG/SET_CONFIG, GET_NETWORK_STATUS per the
   brief's §8 command list, with a `docs/API.md`-style formal spec at
   `docs/MOBILE_API.md` (brief §9).
3. **No show library / "next/previous show" concept.** `Player.load()` takes a single
   path; there's no directory-of-shows abstraction, no `NEXT`/`PREVIOUS` semantics
   across shows (only within one file's frames, via `frame_step()`). Needed for §21
   (show browsing) and §8's `NEXT`/`PREVIOUS` commands.
4. **No config-file loader.** `docs/RASPBERRY_PI.md` §14's TOML shape was proposed but
   never parsed by any code — `AUTOSTART`/`DEFAULT_SHOW`/`OUTPUT`/etc. need an actual
   loader feeding `dmxreplay-play`'s existing arguments.
5. **No systemd unit, no packaging for any platform.** No PyInstaller/briefcase spec
   for Windows `.exe`/macOS `.app`, no Debian/ARM64 package for the Pi, no
   `docs/BUILD_AND_DISTRIBUTION.md`.
6. **No discovery mechanism** (mDNS/Zeroconf/UDP broadcast) — needed for §19 so a
   phone can find `DMXReplay-LivingRoom` on the LAN without a typed-in IP.
7. **No authentication/pairing on the (currently nonexistent) control API** — §20
   requires this be designed in from the start, not bolted on.
8. **No file-transfer mechanism** (§22) — uploading a `.dmxr`/video pair from a phone
   or desktop to a Pi's show library.
9. **No mobile application in any form** — a from-scratch build (§10–§13).
10. **`docs/ARCHITECTURE.md` (this file), `docs/RASPBERRY_PI_INSTALL.md`,
    `docs/MOBILE.md`, `docs/MOBILE_API.md`, `docs/BUILD_AND_DISTRIBUTION.md`,
    `docs/NETWORKING.md`** don't exist yet (brief §29); `docs/API.md` and
    `docs/RASPBERRY_PI.md` need extending, not replacing.
11. **Hardware-accelerated video decode on the Pi is unexplored** (brief §16) —
    `ExternalVideoReader` decodes in software only today; `docs/RASPBERRY_PI.md` §8
    already flags this as a documented open item, not new information.

None of these require touching `dmxreplay.dmx`, `.clock`, `.metadata`, `.codec`,
`.container`, or the `.dmxr` format itself.

## 4. What should not change

Stated explicitly because the extension brief repeatedly warns against exactly these
mistakes, and the audit confirms the current design already avoids them:

- **The `.dmxr` format** (`docs/SPECIFICATION.md`, `docs/CONTAINER.md`). Cross-platform
  portability was a V1 design goal from Phase 0 (`FORMAT-RESEARCH.md`), not an
  afterthought — no version bump or field addition is implied by anything in §1–§3.
- **One master `Timeline` per playing process, reading position once per tick for
  every track (DMX/audio/video).** This is `Player._run_loop()` today and must stay
  true on the Pi with a remote controller attached — the controller sends *commands*
  (`PLAY`/`SEEK`/...), never frame-by-frame timing, exactly matching brief §14/§30's
  "correct" diagram. A phone `SEEK` call becomes one `Player.seek()` call; there is no
  path from the network API to the timeline's tick loop.
- **GUI-independence of the core** (`CONTRIBUTING.md`'s rule, `src/dmxreplay/ui`
  staying empty of real code until a real GUI phase). A future HTTP/WebSocket service
  layer is a *consumer* of `Player`/`Recorder`, same relationship the CLI already has
  — it does not get special access the CLI doesn't have, and it lives in its own
  module (proposed: `dmxreplay.control`), not inside `player.py`/`recorder.py`.
- **Sample-and-hold semantics, VFR storage, byte-exact DMX preservation** — none of
  this is platform behavior; changing it for one platform would make `.dmxr` files
  platform-dependent, which is the one thing brief §3/§33 forbids outright.
- **The recorder-side commit policy** ("one stored frame per received valid packet,"
  `recorder.py`) and the conformance suite's guarantees about it — the mobile Recorder
  (if built at all, see §6 below) must produce files satisfying the same
  `tests/test_conformance.py` Reader/Recorder conformance checks, not a parallel set of
  rules.

## 5. What is platform-specific

Genuinely different per target, and where the plan should isolate the difference
rather than let it leak into the core:

| Concern | Windows | macOS | Raspberry Pi | Smartphone |
|---|---|---|---|---|
| Process packaging | PyInstaller `.exe` | PyInstaller/`py2app` `.app`, likely needs notarization for distribution outside dev use | pip install / `.deb`, no bundling needed (Python ships with Raspberry Pi OS) | Native app package (`.ipa`/`.apk`), separate toolchain entirely (§6) |
| Autostart/service | Task Scheduler or a Windows service wrapper (not systemd) | `launchd` `.plist` (not systemd) — desktop use case is unlikely to need this at all | systemd unit (already sketched, `RASPBERRY_PI.md` §14) | App lifecycle, OS-managed, not comparable to a service |
| Signal handling | `asyncio.loop.add_signal_handler` raises `NotImplementedError` on Windows for `SIGTERM` (already caught gracefully in `play.py`'s existing `try/except`) — Ctrl+C still works via the default `KeyboardInterrupt` path, but a clean remote "stop the whole process" story on Windows needs its own mechanism, not `SIGTERM` | Same as Linux (POSIX) | Same as Linux (POSIX) | N/A |
| Broadcast/multicast networking | `allow_broadcast=True` datagram sockets and `IP_ADD_MEMBERSHIP` both work on Windows; `SO_REUSEPORT` doesn't exist there (already guarded) — needs an actual Windows run to confirm sACN multicast join behaves the same, not just "should work" | POSIX, same as Linux | POSIX, same as Linux, plus this is the *target* network (the actual lighting rig's Art-Net/sACN segment) | Mobile OS background networking restrictions — this is the big one, see §6 |
| Hardware video decode | Available via ffmpeg's platform decoders (DXVA2/D3D11) if PyAV's build exposes them — unverified, not yet needed at V1's video scale | VideoToolbox, similarly unverified/unneeded so far | No hardware FFV1 decode on either Pi 4/5 (`RASPBERRY_PI.md` §5 already established this isn't needed for DMX decode at V1 universe counts); external-video hardware decode is the open item this extension's §16 revives | Fully OS-managed if the mobile app plays video at all (unlikely in remote-controller mode — the Pi/desktop does the playback, not the phone) |
| GPIO / physical controls | N/A | N/A | Real, but brief §17 explicitly says don't build around it — a hardware abstraction layer, not core logic | N/A |
| Local web config UI (brief §18) | Not needed (desktop already has a full OS UI) | Not needed | Directly applicable — the headless-with-no-screen case | The *client* of that UI, or of the native app |

## 6. What is impossible or risky

The extension brief asks for this explicitly (§10/§12: "the feasibility of standalone
mode must be evaluated separately for iOS and Android," §32: "do not implement Mobile
Standalone before validating the network and `.dmxr` architecture"). Being direct about
this now, before any mobile code exists, is cheaper than discovering it mid-build:

- **Real-time Art-Net/sACN reception on a phone, in the background, is fundamentally
  at odds with both major mobile OSes' power-management models.** iOS suspends
  background UDP socket activity aggressively outside a small set of app categories
  (VoIP, specific Bluetooth/location use cases — "lighting control" isn't one of
  them); a `.dmxr` recorder needs to keep receiving and timestamping packets
  continuously while the app may not be foregrounded. Android is less strict but has
  moved the same direction for years (Doze mode, background service limits since
  Android 8+) and would need a persistent foreground service (a visible, ongoing
  notification) to have any chance of staying alive — which is a legitimate option,
  but user-visible and still not guaranteed by the OS the way a desktop or Pi process
  is. **This is a real reliability risk, not a solvable engineering detail** — the
  brief's own §12 instruction ("do not sacrifice timing reliability simply to support
  standalone mobile output") points at the same conclusion this audit reaches
  independently.
- **PyAV/ffmpeg (the one native dependency the whole "single authoritative Core"
  claim in §2 leans on) has no realistic path onto iOS**, and no official prebuilt
  wheel story for Android either (§1's wheel-availability table stops at
  win/mac/linux+aarch64 — mobile OSes are absent from that list because PyPI wheels
  target CPython on those platforms, not iOS/Android app runtimes). This means the
  "one authoritative Core" principle (brief §2) **cannot literally extend to a native
  mobile app** without either (a) treating the Pi/desktop as the only place the real
  Core ever runs, and the phone as a thin remote-control client (no `.dmxr`
  decode/encode on-device at all), or (b) a second, mobile-native reimplementation of
  DMX decode/encode — which is exactly the "three independent implementations" the
  brief says not to create. **(a) is the only option consistent with the brief's own
  stated principles**, and is what §7's phase plan below assumes: mobile standalone
  record/playback is evaluated, and very likely scoped down to "not attempted for V1
  of this extension," rather than built and then found unreliable.
- **A Flutter/React-Native-style cross-platform mobile framework does not give you
  DMX-grade real-time UDP the way a desktop Python process does.** Both frameworks can
  do UDP sockets and even multicast joins, but neither promises anything about timing
  precision under OS scheduling pressure, and neither runs FFV1/Matroska decode
  without a native plugin (which reopens the PyAV-on-mobile problem in a different
  form). This reinforces "controller by default," not "controller because it was
  easier" — it's the technically correct call, independently arrived at.
- **`docs/RASPBERRY_PI.md` §0 already flags that nothing in this whole project has run
  on physical Raspberry Pi hardware** — every Pi number so far is measured on the x86
  sandbox this session runs in and extrapolated using published comparative CPU
  benchmarks, explicitly labeled as such. Brief §25's performance-testing requirement
  (1/10/50/128 universes × DMX/DMX+audio/DMX+video/DMX+audio+video, boot time,
  recovery after failure) genuinely cannot be completed in this sandboxed environment
  — it requires physical Pi 4 and Pi 5 units. This should be flagged to whoever owns
  physical hardware access rather than silently reported as "done" from extrapolation
  a second time.
- **Windows-specific network behavior (multicast join semantics, firewall prompts on
  first Art-Net/sACN bind, `SIGTERM` handling) is unverified** — the code is written
  defensively (§1), but "should work based on the socket API being portable" is not
  the same claim as "measured working on a Windows machine," and this project's own
  standing rule is not to conflate the two.
- **App store distribution (iOS App Store review, Google Play policies) for an app
  whose stated purpose includes "controls DMX lighting fixtures" is a real-world,
  non-technical risk** — not this audit's call to resolve, but worth surfacing before
  investing in native app builds: distribution as a sideloaded/enterprise/TestFlight
  build may be the realistic V1 target rather than public store listing.

## 7. Proposed phased plan

**Approved and in progress.** The user confirmed this order (with Phase A widened to
include the desktop GUI apps themselves, not just their packaging — see §7's Phase A
row) and gave the go-ahead to implement. Status is tracked here as each phase lands;
this table is a living document, updated in place rather than rewritten each time
(same convention as `docs/RASPBERRY_PI.md`'s "Update, Phase N:" annotations).

| Phase | Scope | Status |
|---|---|---|
| **A** | Cross-platform packaging + desktop GUIs: `dmxreplay.ui` (Tkinter) Player/Recorder GUI apps per the desktop GUI spec, wired to `Player`/`Recorder` via toolkit-independent view-models; PyInstaller specs; `docs/BUILD_AND_DISTRIBUTION.md` | ✅ **Done.** GUI apps built and unit/widget-tested (`tests/test_ui_*.py`, `tests_gui/`). Linux onedir packaging built and run for real (`packaging/build_linux.sh`, verified — see `docs/BUILD_AND_DISTRIBUTION.md` §3, including one real bug found and fixed: a Tkinter/Python-version mismatch that silently produced a broken package). Windows/macOS build scripts written, mirroring the verified Linux command exactly, but **not run on real hardware** — no Windows/macOS machine in this environment. Installer (`.msi`)/`.dmg`+signing are explicitly not done yet (§4/§5 there). |
| **B** | Raspberry Pi ARM64/headless foundation: config-file loader for `RASPBERRY_PI.md` §14's proposed TOML shape, a real systemd unit, install script | Next |
| **C** | Long-running commandable Player/Recorder service: the control surface `RASPBERRY_PI.md` §13 already identified as missing — a persistent process wrapping `Player`/`Recorder` that stays alive and accepts new commands after `play()` returns | Planned |
| **D** | Control API (HTTP + WebSocket) over Phase C's service; `docs/MOBILE_API.md`; must never contain the real-time DMX loop itself | Planned |
| **E** | Raspberry Pi configuration + discovery: mDNS/Zeroconf advertisement, a lightweight local web config UI (network/Art-Net/sACN/playback/system settings) | Planned |
| **F** | Mobile remote controller: cross-platform app (Flutter recommended, §6) talking only to Phase D's API — browse/select/play/pause/seek/next/previous/record/status, never on-device DMX decode | Planned |
| **G** | Show management + file transfer: show-library abstraction, browse/select/delete/info via the Control API, upload from client to Pi | Planned |
| **H** | Performance / hardware validation: the full matrix (1/10/50/128 universes × DMX/+audio/+video/+audio+video) on real Pi 4/5 where possible; a hardware validation checklist where it isn't | Planned |
| **I** | Final packaging + documentation pass across all new docs (`ARCHITECTURE.md`, `API.md`, `RASPBERRY_PI.md`, `RASPBERRY_PI_INSTALL.md`, `MOBILE.md`, `MOBILE_API.md`, `NETWORKING.md`, `BUILD_AND_DISTRIBUTION.md`) | Planned |

**Mobile standalone record/playback** (§6's evaluation) is deliberately *not* one of
these nine lettered phases — the user confirmed it stays a documented future/
experimental capability, evaluated but not built for this extension's V1 unless a
reliably implementation becomes apparent, consistent with §6's own conclusion. It will
be revisited, if at all, after Phase F, in `docs/MOBILE.md`.

`docs/NETWORKING.md` and this file are living documents updated across Phases B–E
rather than written once at the end.

## 8. Open questions — resolved

The four questions raised when this audit was first written (§8, prior revision) have
been answered by the user directly:

1. **Physical hardware access**: none available in this environment. Confirmed:
   proceed with everything *except* what genuinely requires physical Pi/Windows/macOS
   hardware, mark those items clearly rather than blocking on them (§18 of the
   extension brief), and produce a hardware validation checklist (Phase H) for later.
2. **Mobile framework for Phase F**: proceed with this audit's Flutter recommendation
   (§6) — not explicitly overridden.
3. **Mobile standalone risk tolerance**: confirmed — stays future/experimental, not a
   blocking V1 requirement, architecture kept open for it (§6 above).
4. **Distribution channel for the mobile app** (App Store/Play Store vs.
   sideload/TestFlight/enterprise) — still genuinely open, not addressed by the user's
   reply; revisit before Phase F work goes far enough that it matters (affects how much
   is worth investing relative to review/policy risk, §6).

This document should be updated as each phase actually lands, the same way
`docs/RASPBERRY_PI.md` was updated with "Update, Phase N:" annotations rather than
rewritten from scratch each time.
