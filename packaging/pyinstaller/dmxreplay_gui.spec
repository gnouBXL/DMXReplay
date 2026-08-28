# -*- mode: python ; coding: utf-8 -*-
# Build: pyinstaller packaging/pyinstaller/dmxreplay_gui.spec
# Output: dist/DMXReplay/ (onedir) and, on macOS, dist/DMXReplay.app --
# the single app a packaged build's icon runs (docs/DEMO_MODE.md §6,
# docs/BUILD_AND_DISTRIBUTION.md): a "Welcome to DMXReplay" chooser that
# opens Player/Recorder windows itself, not a separate app per window.
import sys

sys.path.insert(0, SPECPATH)  # noqa: F821 -- SPECPATH is injected by PyInstaller at spec exec time
from _common import HIDDEN_IMPORTS, SRC_DIR  # noqa: E402

block_cipher = None

a = Analysis(  # noqa: F821 -- Analysis/PYZ/EXE/COLLECT/BUNDLE are injected by PyInstaller
    ["launch_dmxreplay_gui.py"],
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
    name="DMXReplay",
    debug=False,
    strip=False,
    upx=False,
    console=False,  # GUI app -- no console window (docs/BUILD_AND_DISTRIBUTION.md)
)
coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="DMXReplay",
)

if sys.platform == "darwin":
    # macOS wants a real .app bundle, not a bare onedir folder -- BUNDLE()
    # is a PyInstaller macOS-only construct (unverified here: no macOS
    # machine in this sandbox, see docs/BUILD_AND_DISTRIBUTION.md).
    app = BUNDLE(  # noqa: F821
        coll,
        name="DMXReplay.app",
        icon=None,
        bundle_identifier="org.dmxreplay.app",
        info_plist={
            "CFBundleName": "DMXReplay",
            "CFBundleDisplayName": "DMXReplay",
            "CFBundleShortVersionString": "0.1.0",
            "NSHighResolutionCapable": True,
        },
    )
