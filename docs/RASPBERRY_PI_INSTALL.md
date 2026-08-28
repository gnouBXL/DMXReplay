# RASPBERRY_PI_INSTALL.md — headless appliance installation

Companion to [RASPBERRY_PI.md](RASPBERRY_PI.md) (the compatibility analysis and
architecture) and [ARCHITECTURE.md](ARCHITECTURE.md) (Phase B). This document is the
practical install walkthrough: turning a Raspberry Pi running Raspberry Pi OS (or any
systemd-based Debian/Ubuntu-family Linux) into a headless DMXReplay Player appliance —
no monitor, keyboard, or mouse required after setup.

## What's verified here, and what isn't

| | Status |
|---|---|
| `dmxreplay.config.PlayerConfig` TOML loader | Real, unit-tested (`tests/test_config_loader.py`) |
| `dmxreplay-play --config` | Real, tested end-to-end over real Art-Net (`tests/test_cli.py`) |
| `packaging/systemd/dmxreplay-player.service` syntax | **Verified for real** via `systemd-analyze verify` against an actual install at the path this unit expects (`tests/test_packaging.py` re-runs this check on every test run) |
| `packaging/raspberrypi/install.sh` shell syntax | Verified (`bash -n`, `tests/test_packaging.py`) |
| Running on an actual Raspberry Pi (4 or 5, Raspberry Pi OS) | **Not verified** — no physical Pi in this environment. See `docs/RASPBERRY_PI.md` §0/§10 and `docs/ARCHITECTURE.md` §6/§8's hardware validation checklist. |
| `av` (PyAV) installing from a wheel on Raspberry Pi OS's ARM64 Python | Confirmed a compatible wheel *exists* on PyPI (`docs/ARCHITECTURE.md` §1) — not confirmed to actually install/import on real Pi hardware |

## 1. Install

```bash
git clone https://github.com/gnouBXL/dmxreplay /tmp/dmxreplay
sudo /tmp/dmxreplay/packaging/raspberrypi/install.sh /tmp/dmxreplay
```

This script (run as root — it creates a system user and installs a systemd unit):

1. Creates a `dmxreplay` system user/group.
2. Creates a Python venv at `/opt/dmxreplay/.venv` and installs DMXReplay into it with
   the `codec` and `audio` extras (`pip install -e '.[codec,audio]'`).
3. Creates `/etc/dmxreplay/` and `/var/lib/dmxreplay/shows/`, and writes a starter
   config to `/etc/dmxreplay/player.toml` if one doesn't already exist
   (from `packaging/raspberrypi/player.toml.example`).
4. Installs `packaging/systemd/dmxreplay-player.service` to
   `/etc/systemd/system/` and runs `systemctl daemon-reload`.

It does **not** enable or start the service — that's a deliberate separate step, so you
can edit the config first.

## 2. Configure

Edit `/etc/dmxreplay/player.toml`. At minimum:

```toml
show = "/var/lib/dmxreplay/shows/MyShow.dmxr"
interface = "eth0"              # or a specific IP
destination = "192.168.1.100"   # your Art-Net/sACN node's IP, or omit for broadcast/multicast
```

See `packaging/raspberrypi/player.toml.example` for every field DMXReplay understands
(all optional except `show`) — `dmxreplay.config.PlayerConfig`
(`src/dmxreplay/config/loader.py`) rejects unknown keys and malformed TOML with a clear
error rather than silently ignoring a typo, since nobody is watching an interactive
terminal for a systemd-managed service.

Copy your `.dmxr` (and optional external video) into `/var/lib/dmxreplay/shows/`:

```bash
sudo cp MyShow.dmxr MyShow.mp4 /var/lib/dmxreplay/shows/
sudo chown dmxreplay:dmxreplay /var/lib/dmxreplay/shows/*
```

(File transfer directly from a phone or desktop, without manual `scp`, is
`docs/ARCHITECTURE.md` Phase G — not implemented yet.)

## 3. Enable and start

```bash
sudo systemctl enable --now dmxreplay-player   # AUTOSTART=true equivalent
journalctl -u dmxreplay-player -f              # live status/logs
```

Expected boot sequence, matching `docs/ARCHITECTURE.md`'s brief §6:

```
Power ON → Linux boot → network-online.target reached → dmxreplay-player.service starts
→ dmxreplay-play parses /etc/dmxreplay/player.toml → loads the show → configures output
→ plays (or idles, if autoplay = false) → READY
```

To disable autostart (`AUTOSTART=false` equivalent): `sudo systemctl disable
dmxreplay-player` (this stops it from starting on the *next* boot; it keeps running
until you also `systemctl stop` it, or reboot).

## 4. Automatic restart after failure

`packaging/systemd/dmxreplay-player.service` sets `Restart=on-failure` with a 2-second
backoff and a cap of 5 restarts per 60 seconds (`StartLimitBurst`/
`StartLimitIntervalSec`, in the unit's `[Unit]` section — a real mistake this file's own
first draft made by putting them in `[Service]` instead, caught immediately by
`systemd-analyze verify`, not by a review months later). A clean exit (a non-looping
show finishing, or a deliberate `systemctl stop`) does **not** trigger a restart — only
a crash or non-zero exit does. If the service hits its restart limit,
`systemctl status dmxreplay-player` shows `start-limit-hit`; check `journalctl -u
dmxreplay-player` for why it's actually failing (a missing show file and a bad network
interface name are the two most likely causes) before re-enabling it.

## 5. Updating

```bash
cd /tmp/dmxreplay && git pull
sudo /opt/dmxreplay/.venv/bin/pip install -e '.[codec,audio]'
sudo systemctl restart dmxreplay-player
```

There is no live-reload of `player.toml` — a config change needs
`systemctl restart dmxreplay-player` to take effect.

## 6. Uninstalling

```bash
sudo systemctl disable --now dmxreplay-player
sudo rm /etc/systemd/system/dmxreplay-player.service
sudo systemctl daemon-reload
sudo rm -rf /opt/dmxreplay /etc/dmxreplay
# /var/lib/dmxreplay/shows is left in place deliberately -- remove it
# yourself if you also want your recorded/transferred shows gone:
#   sudo rm -rf /var/lib/dmxreplay
sudo userdel dmxreplay
```

## 7. Hardware validation checklist

Everything above has been verified in this project's own (non-Pi) Linux development
environment, per the table at the top of this document. Before trusting this as a
production appliance on real hardware, confirm on an actual **Raspberry Pi 4** and
**Raspberry Pi 5** (Raspberry Pi OS, 64-bit):

- [ ] `sudo packaging/raspberrypi/install.sh` completes without error, including `pip
      install`ing `av` from a wheel (not source — a source build would be a strong
      signal something about the target's Python/OS combination wasn't anticipated).
- [ ] `systemctl enable --now dmxreplay-player` reaches a playing state and actually
      outputs correct, real-time Art-Net/sACN to the target lighting network.
- [ ] A `sudo reboot` results in the service auto-starting and resuming playback
      (or idling, per `autoplay`) with no manual intervention — no monitor, keyboard,
      or mouse attached.
- [ ] Killing the process (`sudo pkill -9 -f dmxreplay-play`) triggers the
      `Restart=on-failure` behavior and playback resumes within a few seconds.
- [ ] `docs/ARCHITECTURE.md` Phase H's full performance matrix (1/10/50/128 universes ×
      DMX/+audio/+video/+audio+video @ 30fps) — CPU, RAM, network throughput, DMX
      timing accuracy, latency, packet loss, dropped frames, sync drift, boot time,
      and failure-recovery time, on both Pi 4 and Pi 5.
- [ ] Confirm actual boot-to-READY time is reasonable for a lighting appliance (no
      hard number promised anywhere yet — this is where one gets measured for real).
