#!/usr/bin/env bash
# Build DMXReplay.app (the single, user-facing launcher app -- "Welcome to
# DMXReplay", opens Player/Recorder itself) plus the separate DMXReplay
# Player.app/DMXReplay Recorder.app for anyone who wants one directly, and
# package DMXReplay.app into DMXReplay.dmg for distribution: drag to
# Applications, double-click, done -- no Python/terminal/CLI required by
# the end user (docs/DEMO_MODE.md §6).
#
# UNVERIFIED IN CI/dev sandbox: this script has not been run on a real Mac
# (no macOS available in the environment that wrote it -- see
# docs/BUILD_AND_DISTRIBUTION.md). It mirrors packaging/build_linux.sh,
# which HAS been run and verified end-to-end; the only macOS-specific
# additions are the BUNDLE() step already present in every .spec file
# (guarded by `sys.platform == "darwin"`, PyInstaller's documented way to
# produce a .app) and this script's own `hdiutil` .dmg step below. Needs
# validation on real hardware/CI; code signing/notarization (required for
# distribution outside local dev use, per Apple's Gatekeeper) is still not
# implemented here -- see docs/BUILD_AND_DISTRIBUTION.md's open items.
#
# python.org's official macOS installers bundle Tkinter; Homebrew's
# `python3` does NOT by default (needs `brew install python-tk`) --
# confirm which Python this runs against before relying on Tkinter being
# present.
#
# Usage: packaging/build_macos.sh

set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${1:-python3}"

# See packaging/build_linux.sh's comment on why this check exists: a
# packaged build with no working Tkinter fails silently at build time and
# loudly (but only) when a user runs it.
if ! "$PYTHON" -c "import tkinter" 2>/dev/null; then
    echo "ERROR: '$PYTHON' has no working Tkinter (needed by dmxreplay.ui)." >&2
    echo "The python.org macOS installer bundles it; Homebrew's python3 does" >&2
    echo "NOT by default ('brew install python-tk'). Pass a working" >&2
    echo "interpreter explicitly if needed: packaging/build_macos.sh /path/to/python3" >&2
    exit 1
fi

"$PYTHON" -m venv "$REPO_ROOT/.venv-build"
"$REPO_ROOT/.venv-build/bin/pip" install -e "$REPO_ROOT[dev]"
"$REPO_ROOT/.venv-build/bin/pip" install -r "$REPO_ROOT/packaging/pyinstaller/requirements.txt"

"$REPO_ROOT/.venv-build/bin/pyinstaller" \
    "$REPO_ROOT/packaging/pyinstaller/dmxreplay_gui.spec" \
    --noconfirm --distpath "$REPO_ROOT/dist" --workpath "$REPO_ROOT/build"

"$REPO_ROOT/.venv-build/bin/pyinstaller" \
    "$REPO_ROOT/packaging/pyinstaller/player_gui.spec" \
    --noconfirm --distpath "$REPO_ROOT/dist" --workpath "$REPO_ROOT/build"

"$REPO_ROOT/.venv-build/bin/pyinstaller" \
    "$REPO_ROOT/packaging/pyinstaller/recorder_gui.spec" \
    --noconfirm --distpath "$REPO_ROOT/dist" --workpath "$REPO_ROOT/build"

echo "Built: dist/DMXReplay.app (the one users should actually run)"
echo "Built: dist/DMXReplay Player.app"
echo "Built: dist/DMXReplay Recorder.app"

# --- .dmg packaging (DMXReplay.app only -- the single user-facing app) ---
if [[ "$(uname -s)" == "Darwin" ]]; then
    DMG_STAGING="$REPO_ROOT/build/dmg-staging"
    rm -rf "$DMG_STAGING"
    mkdir -p "$DMG_STAGING"
    cp -R "$REPO_ROOT/dist/DMXReplay.app" "$DMG_STAGING/"
    ln -s /Applications "$DMG_STAGING/Applications"
    rm -f "$REPO_ROOT/dist/DMXReplay.dmg"
    hdiutil create -volname "DMXReplay" -srcfolder "$DMG_STAGING" \
        -ov -format UDZO "$REPO_ROOT/dist/DMXReplay.dmg"
    echo "Built: dist/DMXReplay.dmg"
else
    echo "Skipping .dmg step -- hdiutil is macOS-only and this isn't macOS" \
         "(uname: $(uname -s)); the .app bundles above were still built by" \
         "PyInstaller itself, which doesn't need hdiutil." >&2
fi

echo ""
echo "NOT done by this script (see docs/BUILD_AND_DISTRIBUTION.md):"
echo "  - code signing / notarization (required for distribution outside"
echo "    local development use, per Apple Gatekeeper -- an unsigned"
echo "    DMXReplay.dmg will trigger a Gatekeeper warning on another Mac)"
