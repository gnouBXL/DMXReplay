# -*- mode: python ; coding: utf-8 -*-
# Build: pyinstaller packaging/pyinstaller/player_gui.spec
# Output: dist/DMXReplay Player/ (onedir -- see docs/BUILD_AND_DISTRIBUTION.md
# for why onedir, not onefile, is the default here).
import sys

sys.path.insert(0, SPECPATH)  # noqa: F821 -- SPECPATH is injected by PyInstaller at spec exec time
from _common import HIDDEN_IMPORTS, SRC_DIR  # noqa: E402

block_cipher = None

a = Analysis(  # noqa: F821 -- Analysis/PYZ/EXE/COLLECT are injected by PyInstaller
    ["launch_player_gui.py"],
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
    name="DMXReplay Player",
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
    name="DMXReplay Player",
)

if sys.platform == "darwin":
    # macOS wants a real .app bundle, not a bare onedir folder --
    # BUNDLE() is a PyInstaller macOS-only construct (unverified here: no
    # macOS machine in this sandbox, see docs/BUILD_AND_DISTRIBUTION.md).
    app = BUNDLE(  # noqa: F821
        coll,
        name="DMXReplay Player.app",
        icon=None,
        bundle_identifier="org.dmxreplay.player",
    )
