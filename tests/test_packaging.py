"""Static checks on the packaging/ artifacts that don't need a real
Windows/macOS/Raspberry Pi machine to run for real: shell script syntax,
and the systemd unit file's own syntax (via `systemd-analyze verify`,
which DOES exist and run for real wherever this suite runs, unlike an
actual Raspberry Pi -- docs/BUILD_AND_DISTRIBUTION.md/
docs/RASPBERRY_PI_INSTALL.md are explicit about what's genuinely
unverified vs. what a check like this one actually confirms)."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

PACKAGING_DIR = Path(__file__).resolve().parent.parent / "packaging"


@pytest.mark.parametrize("script", [
    "build_linux.sh",
    "build_macos.sh",
    "raspberrypi/install.sh",
])
def test_shell_script_syntax_is_valid(script):
    path = PACKAGING_DIR / script
    assert path.exists(), f"{path} missing"
    result = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_systemd_unit_syntax_is_valid():
    """systemd-analyze verify legitimately fails in any environment that
    doesn't have DMXReplay actually installed at /opt/dmxreplay (the
    ExecStart binary doesn't exist there) -- that failure is expected and
    NOT what this test checks. What it checks is that this is the *only*
    thing verify complains about: no misplaced directive (this file's own
    first draft put StartLimit* in the wrong section and
    `systemd-analyze verify` caught it immediately, see the unit file's
    own comment), no unknown key, no syntax error."""
    if shutil.which("systemd-analyze") is None:
        pytest.skip("systemd-analyze not available in this environment")

    unit_path = PACKAGING_DIR / "systemd" / "dmxreplay-player.service"
    result = subprocess.run(
        ["systemd-analyze", "verify", str(unit_path)],
        capture_output=True, text=True,
    )
    problems = [
        line for line in result.stderr.splitlines()
        if line.strip() and "is not executable" not in line
    ]
    assert problems == [], f"unexpected systemd-analyze verify complaints: {problems}"
