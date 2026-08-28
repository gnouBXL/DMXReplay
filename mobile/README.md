# DMXReplay Remote Controller (mobile/)

A touch-first Flutter app that remote-controls a DMXReplay Raspberry Pi appliance over
its Control API. It never generates or sends DMX itself — the Raspberry Pi's own
`Player._run_loop()` is the sole real-time master clock; this app only issues one-shot
control commands and displays whatever status the device reports back.

Full architecture, screen-by-screen coverage, platform setup, and test notes:
[`../docs/MOBILE.md`](../docs/MOBILE.md). Wire protocol this app is built against:
[`../docs/MOBILE_API.md`](../docs/MOBILE_API.md).

## Flutter validation status

This app was written in an environment with no Flutter SDK installed.

- Flutter SDK available: **NO**
- Compilation performed: **NO**
- Runtime test performed: **NO**
- Source code generated: **YES**
- API integration implemented: **YES**
- Remaining validation steps: see [`../docs/MOBILE.md`](../docs/MOBILE.md) §8/§9 for the
  full explanation and the exact commands to run
  (`flutter create`, `flutter pub get`, `flutter analyze`, `flutter test`, `flutter run`).

## Quick start (once you have the Flutter SDK)

```bash
cd mobile
flutter create --platforms=android,ios .
flutter pub get
flutter analyze
flutter test
flutter run
```

See [`../docs/MOBILE.md`](../docs/MOBILE.md) §6 for the Android/iOS manifest permissions
this needs before discovery/networking will work on-device.
