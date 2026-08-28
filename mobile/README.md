# DMXReplay Remote Controller (mobile/)

A touch-first Flutter app that remote-controls a DMXReplay Raspberry Pi appliance over
its Control API. It never generates or sends DMX itself — the Raspberry Pi's own
`Player._run_loop()` is the sole real-time master clock; this app only issues one-shot
control commands and displays whatever status the device reports back.

Full architecture, screen-by-screen coverage, platform setup, and test notes:
[`../docs/MOBILE.md`](../docs/MOBILE.md). Wire protocol this app is built against:
[`../docs/MOBILE_API.md`](../docs/MOBILE_API.md).

## Flutter validation status

This app was written in an environment with no Flutter SDK and no Android SDK
installed.

- Flutter SDK available: **NO**
- Compilation performed: **NO** (no `flutter`/Dart compiler, no Android SDK to link
  against)
- Runtime test performed: **NO**
- Source code generated: **YES**
- API integration implemented: **YES**
- Android project (`android/`): hand-authored (not `flutter create`-generated),
  including a **real Gradle wrapper** (`gradle-wrapper.jar` genuinely produced by a
  real Gradle 8.14.3 install's own `wrapper` task targeting Gradle 8.4, not a
  guessed/placeholder binary) and real, well-formed XML (every manifest/resource file
  verified with `xml.etree.ElementTree`, which caught and fixed several
  double-hyphen-in-comment XML syntax errors before this was committed). The Groovy
  build scripts (`build.gradle`/`settings.gradle`/`app/build.gradle`) were **not**
  compiled/evaluated by Gradle here — that needs a real Flutter SDK (for the
  `dev.flutter.flutter-plugin-loader` include) and Android SDK, neither present.
- Remaining validation steps: see [`../docs/MOBILE.md`](../docs/MOBILE.md) §8/§9 for the
  full explanation and the exact commands to run
  (`flutter pub get`, `flutter analyze`, `flutter test`, `flutter run`/`flutter build apk`).

## Quick start (once you have the Flutter SDK)

`android/` is already part of this checkout (hand-authored, including a real Gradle
wrapper) — **no `flutter create` needed for Android**:

```bash
cd mobile
flutter pub get
flutter analyze
flutter test
flutter run   # or: flutter build apk
```

For iOS, generate the platform folder first (not committed here — see
[`../docs/MOBILE.md`](../docs/MOBILE.md) §6 for why):

```bash
flutter create --platforms=ios .
```

See [`../docs/MOBILE.md`](../docs/MOBILE.md) §6 for the Android/iOS permissions this
needs before discovery/networking will work on-device — Android's are already applied
in the committed `android/app/src/main/AndroidManifest.xml`; iOS's still need adding
to `Info.plist` after `flutter create --platforms=ios .` generates it.
