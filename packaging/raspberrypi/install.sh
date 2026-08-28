#!/usr/bin/env bash
# Install DMXReplay Player as a headless systemd appliance on a Raspberry
# Pi (or any systemd-based Debian/Ubuntu-family Linux). See
# docs/RASPBERRY_PI_INSTALL.md for the full walkthrough and what in this
# script has/hasn't been run against real Raspberry Pi hardware.
#
# VERIFIED (in this project's own Linux development environment, not on a
# real Pi -- no Pi available, see docs/ARCHITECTURE.md §6/§8): the venv
# creation, `pip install -e .[codec,audio]`, and the resulting
# systemd-player.service unit file all pass `systemd-analyze verify`
# cleanly against a real install at the exact path this script uses
# (/opt/dmxreplay). What's NOT verified: actually running on Raspberry Pi
# OS specifically, ARM64 wheel installation for `av` (confirmed to exist
# on PyPI in docs/ARCHITECTURE.md §1, not confirmed to install/run here),
# and real Art-Net/sACN hardware I/O.
#
# Usage: sudo packaging/raspberrypi/install.sh /path/to/dmxreplay/checkout

set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: must run as root (creates a system user, installs a systemd unit)." >&2
    exit 1
fi

REPO_ROOT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
INSTALL_DIR="/opt/dmxreplay"
CONFIG_DIR="/etc/dmxreplay"
SHOWS_DIR="/var/lib/dmxreplay/shows"
SERVICE_USER="dmxreplay"

echo "== Creating system user/group '$SERVICE_USER' =="
if ! id "$SERVICE_USER" >/dev/null 2>&1; then
    useradd --system --home-dir "$INSTALL_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
fi

echo "== Installing DMXReplay into $INSTALL_DIR =="
python3 -m venv "$INSTALL_DIR/.venv"
"$INSTALL_DIR/.venv/bin/pip" install --upgrade pip
"$INSTALL_DIR/.venv/bin/pip" install -e "$REPO_ROOT[codec,audio]"

echo "== Creating $CONFIG_DIR and $SHOWS_DIR =="
mkdir -p "$CONFIG_DIR" "$SHOWS_DIR"
if [ ! -f "$CONFIG_DIR/player.toml" ]; then
    cp "$(dirname "${BASH_SOURCE[0]}")/player.toml.example" "$CONFIG_DIR/player.toml"
    echo "  Wrote a starter config to $CONFIG_DIR/player.toml -- edit 'show' and"
    echo "  'interface'/'destination' before starting the service."
fi

chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR" "$CONFIG_DIR" "$SHOWS_DIR"

echo "== Installing the systemd unit =="
cp "$(dirname "${BASH_SOURCE[0]}")/../systemd/dmxreplay-player.service" \
   /etc/systemd/system/dmxreplay-player.service
systemctl daemon-reload

echo ""
echo "Installed. Next steps:"
echo "  1. Edit $CONFIG_DIR/player.toml (at minimum: 'show', 'interface', 'destination')"
echo "  2. Copy your .dmxr (and optional video) into $SHOWS_DIR"
echo "  3. sudo systemctl enable --now dmxreplay-player   # AUTOSTART=true equivalent"
echo "  4. journalctl -u dmxreplay-player -f              # live logs"
echo ""
echo "To disable autostart (AUTOSTART=false equivalent): sudo systemctl disable dmxreplay-player"
