"""PyInstaller entry-point script for the DMXReplay Recorder GUI. See
launch_player_gui.py's docstring and packaging/pyinstaller/recorder_gui.spec.
"""
from dmxreplay.ui.recorder_app import main

if __name__ == "__main__":
    main()
