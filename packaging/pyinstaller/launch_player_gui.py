"""PyInstaller entry-point script for the DMXReplay Player GUI.

PyInstaller bundles a *script*, not a `package:function` reference (unlike
`pyproject.toml`'s `[project.gui-scripts]`, which pip/setuptools turns into
a tiny wrapper script itself) -- this file is that wrapper for the
packaged build. See packaging/pyinstaller/player_gui.spec.
"""
from dmxreplay.ui.player_app import main

if __name__ == "__main__":
    main()
