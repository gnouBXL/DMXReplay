# Build the DMXReplay Player and Recorder Windows GUI apps.
# Run from a Windows machine with Python 3.10+ installed from python.org
# (which bundles Tkinter -- no separate install needed).
#
# UNVERIFIED IN CI/dev sandbox: this script has not been run on a real
# Windows machine (no Windows available in the environment that wrote it --
# see docs/BUILD_AND_DISTRIBUTION.md). The equivalent Linux onedir build
# (packaging/build_linux.sh) has been run and its output executed
# successfully; this script mirrors that same PyInstaller invocation for
# Windows and should be validated on real hardware/CI before being trusted
# for a release.
#
# Usage: powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot

# See packaging/build_linux.sh's comment on why this check exists: a
# packaged build with no working Tkinter fails silently at build time and
# loudly (but only) when a user runs it. python.org's Windows installer
# bundles Tkinter by default, but a custom/embeddable install may not.
python -c "import tkinter" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Error "python has no working Tkinter (needed by dmxreplay.ui). Use the standard python.org installer, which bundles it, or repair/reinstall Python with the 'tcl/tk' optional feature enabled."
    exit 1
}

python -m venv "$RepoRoot\.venv-build"
& "$RepoRoot\.venv-build\Scripts\pip.exe" install -e "$RepoRoot[dev]"
& "$RepoRoot\.venv-build\Scripts\pip.exe" install -r "$RepoRoot\packaging\pyinstaller\requirements.txt"

& "$RepoRoot\.venv-build\Scripts\pyinstaller.exe" `
    "$RepoRoot\packaging\pyinstaller\player_gui.spec" `
    --noconfirm --distpath "$RepoRoot\dist" --workpath "$RepoRoot\build"

& "$RepoRoot\.venv-build\Scripts\pyinstaller.exe" `
    "$RepoRoot\packaging\pyinstaller\recorder_gui.spec" `
    --noconfirm --distpath "$RepoRoot\dist" --workpath "$RepoRoot\build"

Write-Host "Built: dist\DMXReplay Player\DMXReplay Player.exe"
Write-Host "Built: dist\DMXReplay Recorder\DMXReplay Recorder.exe"
Write-Host ""
Write-Host "These are onedir builds (a folder, not a single .exe) -- see"
Write-Host "docs/BUILD_AND_DISTRIBUTION.md for why, and for the still-open"
Write-Host "installer (.msi/Inno Setup) packaging step this script does not"
Write-Host "perform yet."
