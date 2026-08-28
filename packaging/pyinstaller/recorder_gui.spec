# -*- mode: python ; coding: utf-8 -*-
# Build: pyinstaller packaging/pyinstaller/recorder_gui.spec
# Output: dist/DMXReplay Recorder/ (onedir).
import sys

sys.path.insert(0, SPECPATH)  # noqa: F821
from _common import HIDDEN_IMPORTS, SRC_DIR  # noqa: E402

block_cipher = None

a = Analysis(  # noqa: F821
    ["launch_recorder_gui.py"],
    pathex=[SRC_DIR],
    binaries=[],
    datas=[],
    hiddenimports=HIDDEN_IMPORTS,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DMXReplay Recorder",
    debug=False,
    strip=False,
    upx=False,
    console=False,
)
coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="DMXReplay Recorder",
)

if sys.platform == "darwin":
    # See player_gui.spec's identical note -- unverified here, no macOS
    # machine in this sandbox.
    app = BUNDLE(  # noqa: F821
        coll,
        name="DMXReplay Recorder.app",
        icon=None,
        bundle_identifier="org.dmxreplay.recorder",
    )
