#!/usr/bin/env bash
# Build the DMXReplay Player and Recorder GUI apps as Linux onedir bundles.
#
# VERIFIED: this exact sequence (venv with --system-site-packages for
# Tkinter, pip install -e, pip install the PyInstaller requirements,
# pyinstaller on both specs) was run for real in this project's own
# development environment and the resulting executables were launched
# under Xvfb and confirmed to start their Tk mainloop without error --
# see docs/BUILD_AND_DISTRIBUTION.md for the exact commands and output.
# Not yet packaged further (.deb/AppImage) -- that's Raspberry Pi
# packaging territory (docs/RASPBERRY_PI_INSTALL.md), and desktop Linux
# isn't one of the three required desktop targets (Windows/macOS) for
# this extension, so it's left as this onedir build for now.
#
# Requires system Tkinter bindings (Debian/Ubuntu: `apt install
# python3-tk` for whichever Python version PYTHON below resolves to) since
# Tkinter is not a pip package. A REAL bug this script's own first version
# hit and now guards against: a machine with multiple Python versions
# installed can have Tkinter bound to only ONE of them (e.g. `python3-tk`
# satisfies python3.12 but not python3.11's `python3` symlink) -- PyInstaller
# does not hard-fail when a hidden import like this is missing at build
# time, it just silently ships a package that dies with
# "ModuleNotFoundError: No module named 'tkinter'" the moment a user runs
# it. The preflight check below catches that before it ever reaches a
# release artifact, rather than after.
#
# Usage: packaging/build_linux.sh [python-executable]

set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${1:-python3}"

if ! "$PYTHON" -c "import tkinter" 2>/dev/null; then
    echo "ERROR: '$PYTHON' has no working Tkinter (needed by dmxreplay.ui)." >&2
    echo "Install it for this Python version (e.g. 'apt install python3-tk'" >&2
    echo "for whichever python3.X '$PYTHON' resolves to), or pass a working" >&2
    echo "interpreter explicitly: packaging/build_linux.sh /path/to/python3.X" >&2
    exit 1
fi

"$PYTHON" -m venv --system-site-packages "$REPO_ROOT/.venv-build"
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

echo "Built: dist/DMXReplay/DMXReplay (the Welcome launcher -- what a packaged"
echo "  macOS/Windows build's icon runs)"
echo "Built: dist/DMXReplay Player/DMXReplay Player"
echo "Built: dist/DMXReplay Recorder/DMXReplay Recorder"
