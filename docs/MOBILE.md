# MOBILE.md — DMXReplay mobile remote controller (Phase F)

A touch-first Flutter app (`mobile/`) that remote-controls a DMXReplay Raspberry Pi
appliance over the Control API ([MOBILE_API.md](MOBILE_API.md)). This document covers
the mobile project's architecture, screens, platform requirements, and — because this
project was built in an environment with no Flutter SDK available — exactly what has
and has not been validated, and how a developer with Flutter installed should validate
it next.

## 1. The one rule this app is built around

**The smartphone is never part of the real-time DMX timing loop.** The Raspberry Pi's
own `Player._run_loop()` is the sole master clock; this app only ever sends one-shot
control commands (`PLAY`/`PAUSE`/`SEEK`/`LOAD_SHOW`/`RECORD_START`/...,
[MOBILE_API.md](MOBILE_API.md) §5) and displays whatever status the device reports back.
It never sends a DMX frame, never paces output, and is never required to be connected
for playback to continue — see [ARCHITECTURE.md](ARCHITECTURE.md) §4's disconnect
acceptance test and [MOBILE_API.md](MOBILE_API.md) §2/§8. Every controller class in
`mobile/lib/state/` repeats this in its own doc comment deliberately, so the rule is
visible at every call site, not just here.

## 2. Project layout

```
mobile/
  pubspec.yaml            Real, pinned dependencies (see §5)
  analysis_options.yaml   flutter_lints + a few extra rules
  lib/
    main.dart              Entry point
    app.dart                MaterialApp + connected/not-connected routing
    api/
      models.dart                    PlayerStatus / RecorderStatus / DeviceConfig / DeviceEndpoint
      dmxreplay_exception.dart       Typed exception hierarchy
      dmxreplay_rest_client.dart     HTTP half of the Control API
      dmxreplay_websocket_client.dart WebSocket half (status broadcast, receive-only)
    discovery/
      device_discovery_service.dart  mDNS browse (docs/NETWORKING.md §3)
    state/
      connection_controller.dart     Owns the paired device + both clients
      player_controller.dart         Player status/commands
      recorder_controller.dart       Recorder status/commands
    screens/
      discovery_screen.dart          Find/pick/pair a device
      player_screen.dart             Timeline, transport, loop, output status
      shows_screen.dart              Show library browse/select
      recorder_screen.dart           Record start/stop + live stats
      settings_screen.dart           Art-Net/sACN output configuration
    widgets/
      connection_status_banner.dart
      transport_controls.dart
      timeline_slider.dart
      network_status_card.dart
      error_banner.dart
  test/                     Dart unit + widget tests (see §7)
```

This project is deliberately **independent of the Python `dmxreplay` package** — no
shared build, no path dependency — so it can be developed, compiled, and tested on any
machine with the Flutter SDK, entirely separately from the core library's Python
toolchain.

## 3. Screens

| Screen | Covers (brief requirement) |
|---|---|
| `DiscoveryScreen` | Raspberry Pi discovery (mDNS); manual IP connection; pairing token entry |
| `PlayerScreen` | Device connection/status; Player: play/pause/stop/seek/next/previous; loop; Art-Net/sACN output status |
| `ShowsScreen` | Show library; show selection; per-show info and delete (Phase G) |
| `RecorderScreen` | Recording: record start/stop; live duration/frame/packet stats |
| `SettingsScreen` | Basic Raspberry Pi configuration (protocol/interface/destination/port/priority); network status; forget device |

`ErrorBanner` (used on every screen) and `ConnectionStatusBanner` (used on every
connected screen) together cover the brief's "error/status messages" requirement as one
consistent, reusable pattern rather than each screen inventing its own.

## 4. Architecture notes

- **REST for commands, WebSocket for status only.** [MOBILE_API.md](MOBILE_API.md) §5
  documents that commands work over either transport, but the WebSocket protocol has no
  request-id/correlation field. Routing every command through HTTP (which already
  correlates request/response for free) and reserving the WebSocket connection for the
  ~1/s `PlayerStatus` broadcast keeps both halves simple and correct instead of adding
  client-side sequencing to work around a server-protocol gap. See the doc comment on
  `DmxReplayWebSocketClient` for the fuller reasoning.
- **`ChangeNotifier` + `ListenableBuilder`, no state-management package.** The app's
  state graph is small (one connection, one player, one recorder) and Flutter's own
  SDK-provided reactive primitives are sufficient — adding `provider`/`riverpod`/`bloc`
  for this scope would be an unjustified dependency, not a simplification.
  `DmxReplayApp` (`lib/app.dart`) owns the single `ConnectionController` for the app's
  lifetime and (re)creates `PlayerController`/`RecorderController` exactly when the
  connected device changes.
- **Reconnection.** `DmxReplayWebSocketClient` reconnects on its own with capped
  exponential backoff (1s → 2s → 5s → 10s → 20s → 30s, retrying indefinitely at the
  cap) and re-runs the auth handshake on every attempt, since a fresh WebSocket
  connection always starts unauthenticated. `ConnectionStatusBanner` surfaces
  `WsConnectionState.reconnecting` distinctly so the user knows they're looking at
  possibly-stale data — and, per §1, the device itself is completely unaffected by any
  of this the whole time.
- **A real API gap found and fixed while building this client:** the Control API had
  no way to poll live recorder status without calling `RECORD_START` again (which
  restarts the recording). Rather than ship a client-side workaround, `GET_RECORDER_STATUS`
  was added to `dmxreplay.control.CommandRouter` in this same phase, with its own tests
  (`tests/test_control_router.py`) and documentation
  ([MOBILE_API.md](MOBILE_API.md) §5). `RecorderController`'s polling timer uses it.
- **Show management (Phase G).** `DmxReplayRestClient.getShowInfo()`/`deleteShow()`
  wrap the `GET_SHOW_INFO`/`DELETE_SHOW` commands; `ShowsScreen` exposes both via a
  per-show menu (info dialog, delete with a confirmation dialog). `uploadShowBytes()`
  wraps the new `PUT /api/v1/shows/{name}` endpoint and is fully implemented/tested,
  but **has no UI wired up in this pass** — letting the user pick a file from the
  phone's own storage needs a file-picker plugin (e.g. `file_picker` or
  `file_selector`, both real, commonly-used Flutter packages), which isn't currently a
  dependency of this project. Adding one is a small, well-scoped follow-up once this
  app is being compiled/tested for real (§8) — deliberately not added speculatively
  here without the ability to verify it against a real Flutter toolchain.

## 5. Dependencies

All pinned to real, currently-published versions (verified against the pub.dev API and
each package's own source, not guessed):

| Package | Version | Why |
|---|---|---|
| `http` | ^1.6.0 | REST half of the Control API |
| `web_socket_channel` | ^3.0.3 | WebSocket half |
| `multicast_dns` | ^0.3.3 | mDNS discovery (Flutter team's own package) |
| `shared_preferences` | ^2.5.5 | Persists the paired device + token across restarts |
| `cupertino_icons` | ^1.0.9 | Standard Flutter template dependency |
| `flutter_lints` (dev) | ^6.0.0 | Standard Flutter lint set |

## 6. Platform-specific requirements

**Android (`android/`) is committed** — hand-authored (not `flutter create`-generated,
see §8), including a real Gradle wrapper, so `flutter pub get`/`flutter build apk` work
without running `flutter create` first. Its manifest
(`android/app/src/main/AndroidManifest.xml`) already declares:

```xml
<uses-permission android:name="android.permission.INTERNET" />
<uses-permission android:name="android.permission.CHANGE_WIFI_MULTICAST_STATE" />
<uses-permission android:name="android.permission.ACCESS_WIFI_STATE" />
```

mDNS browsing needs multicast, which is off by default on some Android devices/ROMs;
`CHANGE_WIFI_MULTICAST_STATE` is what lets the app acquire a multicast lock. If
discovery still doesn't find devices on a given phone, manual IP connection
(`DiscoveryScreen`'s bottom section) always works regardless (§1, [MOBILE_API.md](MOBILE_API.md) §1).

Cleartext HTTP is allowed globally (`android:usesCleartextTraffic="true"` on
`<application>`), not scoped to specific domains via a network security config: the
Control API has no TLS at all ([MOBILE_API.md](MOBILE_API.md) §1, a trusted-LAN
design), and the device address is whatever IP the user types or mDNS discovers, not a
fixed domain a per-domain config could usefully scope to. The launcher icon
(`android/app/src/main/res/mipmap-*/ic_launcher.png`) is a plain generated placeholder
(a white triangle on the app's Material seed color) — real branding art is a follow-up,
not a build blocker.

**iOS is not committed yet.** `ios/Runner/Info.plist` doesn't exist until you run
`flutter create --platforms=ios .` (mobile/README.md's quick start) — Xcode project
files (`.pbxproj`) are fragile enough hand-authored that doing so without being able to
open them in Xcode here would be a worse starting point than the standard generator,
unlike Android's plain-text Gradle/XML files. Once generated, add, iOS 14+:

```xml
<key>NSLocalNetworkUsageDescription</key>
<string>DMXReplay Remote discovers your DMXReplay Raspberry Pi on the local network.</string>
<key>NSBonjourServices</key>
<array>
  <string>_dmxreplay._tcp</string>
</array>
```

Without both keys, iOS silently blocks the mDNS query and `discover()` returns nothing
rather than erroring — the first thing to check if discovery is empty on iOS but the
device is confirmed reachable by manual IP. App Transport Security also needs relaxing
for local-network HTTP (`NSAllowsLocalNetworking`, or an `NSExceptionDomain` entry) —
not a blanket "allow all cleartext" change, same reasoning as Android's global flag
above doesn't quite apply on iOS since ATS's scoping mechanism works differently.

## 7. Tests

`mobile/test/` contains real Dart tests written against the actual API surface:

- `test/api/models_test.dart` — `fromJson` parsing for every model, including the exact
  JSON shapes documented in [MOBILE_API.md](MOBILE_API.md) §6.
- `test/api/dmxreplay_rest_client_test.dart` — every command's request shape (method,
  path, headers, body) and response handling (success, 401, 404, 409, malformed JSON),
  using `package:http/testing.dart`'s real `MockClient` (no server, no mocking
  framework beyond what the `http` package itself ships).
- `test/discovery/device_discovery_service_test.dart` — TXT record parsing
  (`parseDeviceTxtRecord`), including the newline-joined-substrings detail confirmed
  against `multicast_dns`'s own decoding behavior.
- `test/widgets/error_banner_test.dart`, `test/widgets/timeline_slider_test.dart` —
  widget tests for the two most logic-bearing shared widgets.

These tests are written to run under `flutter test` and are believed correct against
the real package APIs they use, but **have not been executed** — see §8's validation
status. `ConnectionController`/`PlayerController`/`RecorderController` are not yet unit
tested (they'd need a fake `SharedPreferencesAsync`/injectable HTTP client wired through
further than the current constructors expose) — a reasonable next step for whoever
picks up §8's validation, not done here to avoid guessing at test doubles for API
surfaces not yet confirmed to compile.

## 8. Flutter validation status

This app was written in an environment with **no Flutter SDK installed** and could not
be compiled, analyzed, or run here. Every file was written against real, verified
package APIs (pub.dev + each package's published source), and structured the same way
the rest of this repository's Python code is — but until someone runs the steps below
on a machine with Flutter installed, treat it as **implemented but not compiled or
tested**.

- Flutter SDK available: **NO**
- Compilation performed: **NO** (no `flutter`/Dart compiler, no Android SDK to link
  against — the app code and the `android/` project were both written and checked as
  far as this environment's tools allow, see below, but neither has gone through a
  real Flutter/Gradle build)
- Runtime test performed: **NO**
- Source code generated: **YES** (both `lib/`/`test/` and, new this phase, `android/`)
- API integration implemented: **YES** — built directly against the real, shipped
  `dmxreplay.control.CommandRouter`/`ControlServer` (Phase D) command set and JSON
  shapes, cross-referenced against [MOBILE_API.md](MOBILE_API.md) line by line; the one
  gap found (`GET_RECORDER_STATUS`) was fixed at the source in this same phase, not
  papered over client-side.
- Android project (`android/`): real Gradle wrapper (genuinely generated by a real
  Gradle 8.14.3 install, not a placeholder), every XML file verified well-formed
  (`xml.etree.ElementTree` caught and fixed several double-hyphen-in-comment errors
  before commit) — but the Groovy build scripts themselves were not evaluated by
  Gradle here (needs the real Flutter SDK for `dev.flutter.flutter-plugin-loader` plus
  a real Android SDK, neither present); see mobile/README.md's own validation section.
- Remaining validation steps: run §9 below; fix whatever `flutter analyze`/`flutter
  test`/a real device run surfaces (expect at least minor issues — unused-import lints,
  a missed null-check, a widget rebuild edge case, or an Android Gradle Plugin/Kotlin
  version needing a bump for whatever Flutter version you're on — none of which were
  possible to catch without a working toolchain); add the unit tests noted as missing
  in §7; run a real end-to-end pairing/play/record session against an actual
  `dmxreplay-server` instance on a Raspberry Pi or dev machine on the same network.

## 9. First-validation instructions

For a developer with the Flutter SDK installed (`flutter --version` working):

```bash
cd mobile

# 1. Fetch dependencies. android/ is already part of this checkout (§6) --
#    no `flutter create` needed for Android. For iOS, generate its platform
#    folder first: flutter create --platforms=ios .
flutter pub get

# 2. If you generated iOS in step 1, apply Info.plist's changes from §6.

# 3. Static analysis -- this is the fastest way to find anything this
#    environment could not catch (typos, API mismatches, lint violations,
#    or an Android Gradle Plugin/Kotlin version mismatch for your Flutter
#    version specifically).
flutter analyze

# 4. Run the test suite.
flutter test

# 5. Run against a real device/emulator, pointed at a real dmxreplay-server
#    instance (docs/RASPBERRY_PI_INSTALL.md, or `dmxreplay-server` run
#    locally on the dev machine for a first smoke test).
flutter run   # or: flutter build apk
```

If `flutter analyze` or `flutter test` finds issues, fix them in `mobile/lib`/`mobile/test`
directly — nothing about this app's structure is expected to need a redesign, only the
kind of small corrections that only surface once real `dart analyze`/`flutter test` runs
against the real SDK.
