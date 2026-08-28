# RASPBERRY_PI_INSTALL.md — headless appliance installation

Companion to [RASPBERRY_PI.md](RASPBERRY_PI.md) (the compatibility analysis and
architecture), [ARCHITECTURE.md](ARCHITECTURE.md) (Phases B/C/D/E), and
[NETWORKING.md](NETWORKING.md) (ports/discovery detail). This document is the
practical install walkthrough: turning a Raspberry Pi running Raspberry Pi OS (or any
systemd-based Debian/Ubuntu-family Linux) into a headless DMXReplay appliance — no
monitor, keyboard, or mouse required after setup.

## Two services, pick one

The installer sets up **both** systemd units; enable exactly one:

| | `dmxreplay-server` (recommended) | `dmxreplay-player` |
|---|---|---|
| Purpose | Full appliance: Control API + local web UI + mDNS, matches `docs/ARCHITECTURE.md`'s target architecture (smartphone as primary interface) | Simple play-straight-through, no remote control at all |
| Remote control | Yes — HTTP/WebSocket (`docs/MOBILE_API.md`), smartphone (Phase F once it exists) | No |
| Stays running after a show ends | Yes (it's a server) | No (exits cleanly, unless `loop = true`) |
| Extra dependencies | `aiohttp`, `zeroconf` (`[control]` extra) | None beyond `[codec,audio]` |

If you don't yet need remote control and just want a Pi that plays one show
automatically on boot, `dmxreplay-player` is simpler. Everything below defaults to
`dmxreplay-server`; substitute the unit name for `dmxreplay-player` where noted.

## What's verified here, and what isn't

| | Status |
|---|---|
| `dmxreplay.config.PlayerConfig` TOML loader | Real, unit-tested (`tests/test_config_loader.py`) |
| `dmxreplay-play --config` / `dmxreplay-server --config` | Real, tested end-to-end over real Art-Net (`tests/test_cli.py`, `tests/test_cli_server.py`) |
| `packaging/systemd/dmxreplay-{player,server}.service` syntax | **Verified for real** via `systemd-analyze verify` against an actual install at the path each unit expects (`tests/test_packaging.py` re-runs this check on every test run) |
| `packaging/raspberrypi/install.sh` shell syntax + full run | Verified (`bash -n` in `tests/test_packaging.py`; the script itself was also run for real end-to-end in this project's own environment — venv creation, `pip install -e '.[codec,audio,control]'`, config/directory creation, unit file installation all completed successfully) |
| `systemctl daemon-reload` specifically | **Not verified** — this project's development environment is a container with no systemd running as PID 1 (`daemon-reload` fails with "Host is down" there); this is expected on any real systemd-based Linux, including Raspberry Pi OS, and only fails to run in this particular sandboxed environment |
| Running on an actual Raspberry Pi (4 or 5, Raspberry Pi OS) | **Not verified** — no physical Pi in this environment. See `docs/RASPBERRY_PI.md` §0/§10 and `docs/ARCHITECTURE.md` §6/§8's hardware validation checklist. |
| `av`/`aiohttp`/`zeroconf` installing from a wheel on Raspberry Pi OS's ARM64 Python | Confirmed compatible wheels *exist* on PyPI (`docs/ARCHITECTURE.md` §1) — not confirmed to actually install/import on real Pi hardware |
| mDNS advertise + discover | **Verified for real** in this project's own environment (`tests/test_discovery.py`) — but multicast behavior can differ on real network hardware/APs, see `docs/NETWORKING.md` §3's "what can go wrong" |

## 1. Install

```bash
git clone https://github.com/gnouBXL/dmxreplay /tmp/dmxreplay
sudo /tmp/dmxreplay/packaging/raspberrypi/install.sh /tmp/dmxreplay
```

This script (run as root — it creates a system user and installs systemd units):

1. Creates a `dmxreplay` system user/group.
2. Creates a Python venv at `/opt/dmxreplay/.venv` and installs DMXReplay into it with
   the `codec`, `audio`, and `control` extras
   (`pip install -e '.[codec,audio,control]'`).
3. Creates `/etc/dmxreplay/` and `/var/lib/dmxreplay/shows/`, and writes a starter
   config to `/etc/dmxreplay/player.toml` if one doesn't already exist
   (from `packaging/raspberrypi/player.toml.example`).
4. Installs **both** `packaging/systemd/dmxreplay-server.service` and
   `dmxreplay-player.service` to `/etc/systemd/system/` and runs `systemctl
   daemon-reload`.

It does **not** enable or start either service — that's a deliberate separate step,
so you can edit the config and choose which service you want first.

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
terminal for a systemd-managed service. **Both** services load this same file
(`dmxreplay-server --config /etc/dmxreplay/player.toml`, the unit's own `ExecStart`) —
one config file regardless of which one you enable.

Copy your `.dmxr` (and optional external video) into `/var/lib/dmxreplay/shows/`:

```bash
sudo cp MyShow.dmxr MyShow.mp4 /var/lib/dmxreplay/shows/
sudo chown dmxreplay:dmxreplay /var/lib/dmxreplay/shows/*
```

(File transfer directly from a phone or desktop, without manual `scp`, is
`docs/ARCHITECTURE.md` Phase G — not implemented yet.)

## 3. Enable and start

```bash
sudo systemctl enable --now dmxreplay-server   # AUTOSTART=true equivalent
journalctl -u dmxreplay-server -f              # live status/logs
```

`dmxreplay-server` prints its pairing token to the journal on first run (also
persisted at `/etc/dmxreplay/api-token`, per the unit's `--token-file`) — this is
what you enter into the mobile app (`docs/MOBILE_API.md` §4) or paste as
`?token=...` to reach `http://<pi-ip>:8080/config` from a browser (`docs/API.md`
§10's local web config UI, for first-time/no-app setup).

Expected boot sequence, matching `docs/ARCHITECTURE.md`'s brief §6:

```
Power ON → Linux boot → network-online.target reached → dmxreplay-server.service starts
→ dmxreplay-server parses /etc/dmxreplay/player.toml → loads the show → configures
output → advertises via mDNS → serves the Control API → plays (or idles, if
autoplay = false) → READY
```

To disable autostart (`AUTOSTART=false` equivalent): `sudo systemctl disable
dmxreplay-server` (this stops it from starting on the *next* boot; it keeps running
until you also `systemctl stop` it, or reboot).

## 4. Automatic restart after failure

Both units set `Restart=on-failure` with a 2-second backoff and a cap of 5 restarts
per 60 seconds (`StartLimitBurst`/`StartLimitIntervalSec`, in each unit's `[Unit]`
section — a real mistake `dmxreplay-player.service`'s own first draft made by putting
them in `[Service]` instead, caught immediately by `systemd-analyze verify`, not by a
review months later). A clean exit does **not** trigger a restart:

- **`dmxreplay-player`**: a non-looping show finishing, or a deliberate `systemctl
  stop`.
- **`dmxreplay-server`**: only a deliberate `systemctl stop`, or the local web config
  UI's "Safe shutdown" button (`docs/API.md` §10) — the server itself doesn't exit
  when a show ends, it just goes idle and keeps serving the Control API.

The local web config UI's "Restart service" button (`POST /config/restart`) works by
having the process exit with a **non-zero** status deliberately, so this same
`Restart=on-failure` policy brings it back — it never calls `systemctl` itself
(`docs/API.md` §10 explains why: the process shouldn't assume it has permission to).

If a service hits its restart limit, `systemctl status dmxreplay-server` shows
`start-limit-hit`; check `journalctl -u dmxreplay-server` for why it's actually
failing (a missing show file and a bad network interface name are the two most
likely causes) before re-enabling it.

## 5. Updating

```bash
cd /tmp/dmxreplay && git pull
sudo /opt/dmxreplay/.venv/bin/pip install -e '.[codec,audio,control]'
sudo systemctl restart dmxreplay-server
```

There is no live-reload of `player.toml` on process start — a config change needs a
restart to take effect (though `SET_CONFIG` over the Control API, or the local web
config UI, applies playback/output changes live without one, docs/MOBILE_API.md §5).

## 6. Uninstalling

```bash
sudo systemctl disable --now dmxreplay-server dmxreplay-player
sudo rm /etc/systemd/system/dmxreplay-server.service /etc/systemd/system/dmxreplay-player.service
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
      install`ing `av`/`aiohttp`/`zeroconf` from wheels (not source — a source build
      would be a strong signal something about the target's Python/OS combination
      wasn't anticipated), and `systemctl daemon-reload` actually succeeds (unlike in
      this project's own sandboxed development environment, which has no systemd
      PID 1 at all).
- [ ] `systemctl enable --now dmxreplay-server` reaches a playing state and actually
      outputs correct, real-time Art-Net/sACN to the target lighting network.
- [ ] A phone on the same LAN discovers `DMXReplay-<name>` via mDNS
      (`docs/NETWORKING.md` §3) and can reach the Control API/local web config UI.
- [ ] A `sudo reboot` results in the service auto-starting and resuming playback
      (or idling, per `autoplay`) with no manual intervention — no monitor, keyboard,
      or mouse attached.
- [ ] Killing the process (`sudo pkill -9 -f dmxreplay-server`) triggers the
      `Restart=on-failure` behavior and playback resumes within a few seconds.
- [ ] The local web config UI's "Restart service"/"Safe shutdown" buttons produce the
      expected systemd behavior for real (restart brings it back; shutdown does not).
- [ ] `docs/ARCHITECTURE.md` Phase H's full performance matrix (1/10/50/128 universes ×
      DMX/+audio/+video/+audio+video @ 30fps) — CPU, RAM, network throughput, DMX
      timing accuracy, latency, packet loss, dropped frames, sync drift, boot time,
      and failure-recovery time, on both Pi 4 and Pi 5.
- [ ] Confirm actual boot-to-READY time is reasonable for a lighting appliance (no
      hard number promised anywhere yet — this is where one gets measured for real).
- [ ] Confirm mDNS actually reaches the phone across whatever real Wi-Fi AP/router is
      in use — `docs/NETWORKING.md` §3 lists known real-world multicast pitfalls
      (AP isolation, VLANs) that this project's own sandboxed network can't reproduce.
