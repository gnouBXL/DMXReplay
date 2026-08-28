#!/usr/bin/env bash
# Install DMXReplay as a headless systemd appliance on a Raspberry Pi (or
# any systemd-based Debian/Ubuntu-family Linux). Installs BOTH systemd
# units (see docs/RASPBERRY_PI_INSTALL.md for which to actually enable):
#   dmxreplay-server -- Control API + local web UI + mDNS, smartphone-
#                        controlled (docs/ARCHITECTURE.md's target
#                        architecture -- RECOMMENDED default)
#   dmxreplay-player -- simple play-straight-through, no remote control
#
# VERIFIED (in this project's own Linux development environment, not on a
# real Pi -- no Pi available, see docs/ARCHITECTURE.md §6/§8): the venv
# creation, `pip install -e .[codec,audio,control]`, and both resulting
# systemd unit files all pass `systemd-analyze verify` cleanly against a
# real install at the exact path this script uses (/opt/dmxreplay).
# What's NOT verified: actually running on Raspberry Pi OS specifically,
# ARM64 wheel installation for `av`/`aiohttp`/`zeroconf` (confirmed to
# exist on PyPI in docs/ARCHITECTURE.md §1, not confirmed to install/run
# here), and real Art-Net/sACN hardware I/O.
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
"$INSTALL_DIR/.venv/bin/pip" install -e "$REPO_ROOT[codec,audio,control]"

echo "== Creating $CONFIG_DIR and $SHOWS_DIR =="
mkdir -p "$CONFIG_DIR" "$SHOWS_DIR"
if [ ! -f "$CONFIG_DIR/player.toml" ]; then
    cp "$(dirname "${BASH_SOURCE[0]}")/player.toml.example" "$CONFIG_DIR/player.toml"
    echo "  Wrote a starter config to $CONFIG_DIR/player.toml -- edit 'show' and"
    echo "  'interface'/'destination' before starting the service."
fi

chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR" "$CONFIG_DIR" "$SHOWS_DIR"

echo "== Installing systemd units =="
cp "$(dirname "${BASH_SOURCE[0]}")/../systemd/dmxreplay-server.service" \
   /etc/systemd/system/dmxreplay-server.service
cp "$(dirname "${BASH_SOURCE[0]}")/../systemd/dmxreplay-player.service" \
   /etc/systemd/system/dmxreplay-player.service
systemctl daemon-reload

echo ""
echo "Installed. Next steps:"
echo "  1. Edit $CONFIG_DIR/player.toml (at minimum: 'show', 'interface', 'destination')"
echo "  2. Copy your .dmxr (and optional video) into $SHOWS_DIR"
echo "  3. Enable ONE of the two services (docs/RASPBERRY_PI_INSTALL.md):"
echo "       sudo systemctl enable --now dmxreplay-server   # RECOMMENDED: smartphone-controlled"
echo "       sudo systemctl enable --now dmxreplay-player   # simple play-straight-through, no remote control"
echo "  4. journalctl -u dmxreplay-server -f   (or dmxreplay-player)   # live logs"
echo ""
echo "dmxreplay-server prints its pairing token to the journal on first run"
echo "(also persisted at $CONFIG_DIR/api-token) -- enter it in the mobile app."
echo ""
echo "To disable autostart: sudo systemctl disable dmxreplay-server (or dmxreplay-player)"
