#!/usr/bin/env bash
# Build the DMXReplay Player and Recorder macOS .app bundles.
#
# UNVERIFIED IN CI/dev sandbox: this script has not been run on a real Mac
# (no macOS available in the environment that wrote it -- see
# docs/BUILD_AND_DISTRIBUTION.md). It mirrors packaging/build_linux.sh,
# which HAS been run and verified end-to-end; the only macOS-specific
# addition is the BUNDLE() step already present in both .spec files
# (guarded by `sys.platform == "darwin"`, PyInstaller's documented way to
# produce a .app). Needs validation on real hardware/CI, and the
# .dmg-creation step and code-signing/notarization (required for
# distribution outside local dev use, per Apple's Gatekeeper) are not
# implemented here at all -- see docs/BUILD_AND_DISTRIBUTION.md's open
# items.
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
    "$REPO_ROOT/packaging/pyinstaller/player_gui.spec" \
    --noconfirm --distpath "$REPO_ROOT/dist" --workpath "$REPO_ROOT/build"

"$REPO_ROOT/.venv-build/bin/pyinstaller" \
    "$REPO_ROOT/packaging/pyinstaller/recorder_gui.spec" \
    --noconfirm --distpath "$REPO_ROOT/dist" --workpath "$REPO_ROOT/build"

echo "Built: dist/DMXReplay Player.app"
echo "Built: dist/DMXReplay Recorder.app"
echo ""
echo "NOT done by this script (see docs/BUILD_AND_DISTRIBUTION.md):"
echo "  - .dmg packaging (e.g. via hdiutil or create-dmg)"
echo "  - code signing / notarization (required for distribution outside"
echo "    local development use, per Apple Gatekeeper)"
