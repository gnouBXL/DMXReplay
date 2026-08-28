"""Shared PyInstaller configuration for the DMXReplay desktop GUI apps.
Imported by player_gui.spec and recorder_gui.spec so both stay consistent
rather than duplicating pathex/hiddenimports by hand. See
docs/BUILD_AND_DISTRIBUTION.md for the full build process.
"""
import os

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(THIS_DIR))
SRC_DIR = os.path.join(REPO_ROOT, "src")

# av (PyAV) is bundled automatically via pyinstaller-hooks-contrib's own
# hook-av.py (`pip install pyinstaller-hooks-contrib`, listed in
# packaging/pyinstaller/requirements.txt) -- no manual binaries/datas
# collection needed for it here. Tkinter's own Tcl/Tk runtime is collected
# by PyInstaller's built-in tkinter hook, also automatic.
HIDDEN_IMPORTS = [
    # sounddevice is an optional dependency (dmxreplay.audio.
    # SoundDeviceAudioSink, docs/API.md) -- PyInstaller's static import
    # analysis won't always see it if the code path that imports it isn't
    # reached while building, so it's listed explicitly to make sure a
    # packaged build can still offer real hardware audio output when
    # PortAudio is present on the target machine. Harmless to include even
    # if a given user never uses it.
    "sounddevice",
]
