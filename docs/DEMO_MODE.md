# DEMO_MODE.md — exploring DMXReplay without a lighting rig

DMXReplay's desktop GUIs can be explored end-to-end without any Art-Net/sACN
hardware, a real `.dmxr` file, or a network connection. This document covers what
"demo mode" actually is, and what it deliberately is not.

## 1. Why this exists

Before this, using the Player GUI required already having a `.dmxr` file, and using
the Recorder GUI required a real Art-Net/sACN source on the network — both a real
barrier to just seeing what the interface looks like and how it behaves. Demo mode
removes that barrier for exploration and UI testing, without touching how real
recording/playback works in any way.

## 2. Player: the bundled demo show

**File → Open Demo Show** loads a small, synthetic `.dmxr` file
(`dmxreplay.demo.demo_show_path()`) — generated once on first use and cached under the
platform's per-user cache directory (`~/.cache/dmxreplay/` on Linux, `~/Library/
Caches/dmxreplay/` on macOS, `%LOCALAPPDATA%\dmxreplay\` on Windows), not regenerated
on every launch. It contains:

- 4 universes of a deterministic, clearly-moving "chase" pattern (`dmxreplay.dmx.DemoDMXSource`)
- ~8 seconds, 30 fps
- a short synthesized audio tone (so "Audio: present" has something to show)

This is a completely ordinary `.dmxr` file — nothing about the Player's playback
path treats it specially. Its manifest carries `show_name: "DMXReplay Demo Show"`
and a `description` explicitly saying it's synthetic, so it's never mistaken for a
real recording if inspected (`dmxreplay-info`) or shared.

The Output panel's Destination field defaults to `127.0.0.1` (loopback) — pressing
Play works immediately with no lighting rig on the network, since the Art-Net/sACN
packets simply go nowhere real. A real destination IP replaces this the moment the
user has a real console/node to type in.

## 3. Recorder: the "Demo (no hardware needed)" input

Selecting **Demo (no hardware needed)** and pressing **Listen** starts
`Recorder.add_demo_source()` instead of a real `ArtNetListener`/`SACNListener`: a
real, ticking `asyncio` task feeds the identical `DMXEngine.update_artnet()` code
path a real listener's packet callback would, at a real cadence, on the same
`DemoDMXSource` pattern the Player's demo show uses. Everything downstream —
"Detected universes," packet counts, recording, the resulting `.dmxr` file — behaves
exactly as it would for a real source, because it *is* the same engine/writer path;
only the origin of the DMX values differs.

## 4. The universe monitor

Both windows now include a live "Universe monitor (row 0, RGB preview)" panel — a
grid of colored squares reconstructed via `dmxreplay.preview.rgb_led_pixels()`
(Phase 9, previously implemented but never wired into either GUI). This is purely a
visualization: it never affects what's stored, sent, or received, and works
identically whether the underlying data is real Art-Net/sACN or the demo source.

## 5. What demo mode is *not*

- **Not a substitute for real hardware validation.** A demo show or demo source
  proves the GUI's wiring and the engine's code paths run correctly; it says nothing
  about real network behavior, real lighting console compatibility, or real-world
  timing under load (`docs/PERFORMANCE.md`/`docs/RASPBERRY_PI_INSTALL.md` §7 remain
  the record of what still needs real hardware).
- **Not a "simulator" of any specific fixture, console, or protocol quirk.** The
  chase pattern is deliberately generic and visually obvious, not a model of real
  lighting behavior.
- **Never silently substituted for real data.** Demo mode is always an explicit user
  choice (a menu item, a radio button) — nothing falls back to it automatically, and
  the Recorder GUI's status text says "Demo source active... no network involved"
  specifically so it's never confused with a real listening state.

## 6. Launching without the command line

`dmxreplay-gui` (new) opens a small "Welcome to DMXReplay" chooser —
Player / Recorder / Configure — instead of requiring already knowing that
`dmxreplay-player-gui` and `dmxreplay-recorder-gui` are separate commands. This is
what a packaged app's icon runs (`docs/BUILD_AND_DISTRIBUTION.md`).
