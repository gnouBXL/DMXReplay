# BUILD_AND_DISTRIBUTION.md — packaging DMXReplay's desktop apps

Companion to [ARCHITECTURE.md](ARCHITECTURE.md) (Phase A). Covers building the
`DMXReplay Player`/`DMXReplay Recorder` desktop GUI apps (`src/dmxreplay/ui`) into
distributable packages for Windows, macOS, and Linux, without the user needing Python
installed.

## 1. What this covers, and what it doesn't yet

| | Status |
|---|---|
| PyInstaller specs (`packaging/pyinstaller/*.spec`) | Implemented |
| Linux onedir build | **Built and run for real** in this project's own development environment (see §3) |
| Windows build script | Written, mirrors the verified Linux build, **not run on a real Windows machine** (none available in this environment) |
| macOS build script + `.app` bundling | Written, mirrors the verified Linux build, **not run on a real Mac** (none available in this environment) |
| Windows installer (`.msi`/Inno Setup) | Not implemented |
| macOS `.dmg`, code signing, notarization | Not implemented |
| Raspberry Pi / ARM64 packaging | Separate: [RASPBERRY_PI_INSTALL.md](RASPBERRY_PI_INSTALL.md) |

Every claim below is labeled per this table — this document does not present the
Windows/macOS paths as verified when they aren't.

## 2. Why PyInstaller, why Tkinter

- **PyInstaller** was chosen because it needs no separate "spec language" investment
  beyond the two `.spec` files already in `packaging/pyinstaller/`, has first-class,
  actively maintained hooks for PyAV specifically
  (`pyinstaller-hooks-contrib`'s `hook-av.py`, confirmed present and used in the build
  in §3 — it's what collects PyAV's bundled ffmpeg shared libraries into the package),
  and produces plain onedir/`.app`/`.exe` output with no runtime installed-agent
  requirement on the target machine (unlike some alternatives).
- **Tkinter**, for the GUI itself (`src/dmxreplay/ui`), was chosen over a third-party
  cross-platform GUI framework because it's Python's own standard-library toolkit:
  the official python.org installers bundle it on Windows and macOS, and it's a
  one-line `apt install python3-tk` on Debian/Raspberry Pi OS — zero new pip
  dependencies, and no separate "which GUI framework" decision to make for the
  desktop apps. See `docs/ARCHITECTURE.md` §1 for the equivalent reasoning already
  applied to `av` (PyAV).

## 3. Linux build — verified

Run in this project's own development environment (an x86_64 Linux container), with
these real, measured results:

```bash
packaging/build_linux.sh /usr/bin/python3.12   # or whichever python3.X has Tkinter
```

- Both `dist/DMXReplay Player/` and `dist/DMXReplay Recorder/` onedir bundles were
  produced successfully by PyInstaller 6.22.2 (with `pyinstaller-hooks-contrib`
  2026.7 installed for the `av` hook).
- Each resulting executable was launched for real under Xvfb (`xvfb-run -a timeout 5
  ./"DMXReplay Player"`) and ran to the timeout with **no output at all** — i.e. it
  started, initialized Tkinter, entered its event loop, and sat there exactly as a
  working GUI app should, with no missing-module traceback or crash.
- Measured package size: **~141MB** for the Player onedir bundle (dominated by
  PyAV's bundled ffmpeg shared libraries, not DMXReplay's own code, which is a few
  hundred KB of pure Python).

**A real bug was found and fixed while producing this, not found by inspection**:
this machine has four Python versions installed (3.10–3.13), and Tkinter bindings
(`apt install python3-tk`) had only been installed for 3.12 — the *default* `python3`
on this machine resolves to 3.11, which has no Tkinter at all. The first version of
`build_linux.sh` used bare `python3` and **built successfully with no error or
warning**, producing a package that failed at *run time* with `ModuleNotFoundError:
No module named 'tkinter'` — PyInstaller does not hard-fail at build time when a
directly-imported module can't be resolved for a hidden import; it just silently
omits it. `build_linux.sh` now runs `python -c "import tkinter"` as a preflight check
and refuses to build if it fails, with a clear error message, rather than shipping a
broken package. The same preflight check was added to `build_windows.ps1` and
`build_macos.sh` for the same reason, even though it hasn't (yet) been proven to
trigger on those platforms — the failure mode it guards against is generic to any
machine with multiple Python installs, not Linux-specific.

## 4. Windows build — written, not yet verified on real hardware

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1
```

Mirrors the verified Linux build command-for-command (venv, `pip install -e`, the two
`pyinstaller` invocations). The only Windows-specific choices already made:

- `EXE(..., console=False, ...)` in both `.spec` files, so the packaged `.exe` doesn't
  open a console window alongside the GUI (the same setting is a harmless no-op on
  Linux/macOS, which is why one `.spec` file works for all three).
- `[project.gui-scripts]` (not `[project.scripts]`) in `pyproject.toml` for the
  `pip install`-based entry points, for the same reason.

**Not yet done**: an actual installer. The output is a folder
(`dist\DMXReplay Player\DMXReplay Player.exe` plus its `_internal\` dependencies), not
a single installable file. Turning that into a real Windows installer is future work —
Inno Setup or the WiX Toolset are the standard options, neither wired up here, and
should be validated on a real Windows machine or CI runner before being trusted for a
release, exactly like the base build itself.

## 5. macOS build — written, not yet verified on real hardware

```bash
packaging/build_macos.sh
```

Mirrors the Linux build, with one macOS-specific addition already present in both
`.spec` files: a `BUNDLE(...)` step guarded by `if sys.platform == "darwin":`, which is
PyInstaller's documented mechanism for producing a real `.app` bundle instead of a bare
folder. This branch has **not executed** anywhere this document's claims come from
(no macOS machine in this environment) — it is written correctly per PyInstaller's
documentation, not verified by running it.

**Not yet done, and non-trivial when it is**:

- **`.dmg` packaging** (`hdiutil` or a tool like `create-dmg`) — not implemented.
- **Code signing and notarization.** Apple's Gatekeeper will warn or outright refuse
  to run an unsigned/unnotarized app downloaded from the internet. This requires an
  active Apple Developer Program membership and a real macOS machine (or macOS CI
  runner) to do at all — it cannot be prepared in advance without one. Until this is
  done, a macOS build should be described to users as "for local development / manual
  Gatekeeper override," not as a normal double-click-to-install app.

One Python-specific note carried over from the general Tkinter caveat in §2:
**python.org's macOS installer bundles Tkinter; Homebrew's `python3` does not by
default** (`brew install python-tk` is a separate step). `build_macos.sh`'s own
preflight check (§3) will refuse to proceed rather than silently produce a broken
package if this is missed, but it's worth knowing in advance.

## 6. Rebuilding after a core change

Nothing in this packaging pipeline needs to change when `src/dmxreplay/` changes,
*unless* a new third-party import is added somewhere reachable from
`dmxreplay.ui.player_app`/`recorder_app`'s import graph — in which case, add it to
`HIDDEN_IMPORTS` in `packaging/pyinstaller/_common.py` if PyInstaller's static analysis
doesn't find it on its own (it will warn in `build/*/warn-*.txt` if something's
missing; that warning is the signal to check, not something to ignore). The `.spec`
files never need touching for a plain code change in the core engine or the GUI
widgets themselves.

## 7. Distribution scope note

Per `docs/ARCHITECTURE.md` §5's platform-specific table: **only Windows and macOS are
in scope for this packaging pipeline.** Raspberry Pi is `pip install` from a wheel/
`.deb` (Python already ships on Raspberry Pi OS — no bundling needed, see
`docs/RASPBERRY_PI_INSTALL.md`), and desktop Linux was only built here as this
project's own development-environment verification target for the shared `.spec`
files, not as a fourth deliverable platform.
