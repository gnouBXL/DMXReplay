"""PyInstaller entry-point script for the DMXReplay launcher (the
"Welcome to DMXReplay" chooser -- Player / Recorder / Configure). This is
what a packaged DMXReplay.app/DMXReplay.exe's icon actually runs -- see
packaging/pyinstaller/dmxreplay_gui.spec and docs/DEMO_MODE.md §6.
"""
from dmxreplay.ui.launcher import main

if __name__ == "__main__":
    main()
