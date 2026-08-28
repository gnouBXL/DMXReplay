# NETWORKING.md — ports, interfaces, and discovery

Companion to [ARTNET.md](ARTNET.md)/[SACN.md](SACN.md) (the DMX wire protocols),
[MOBILE_API.md](MOBILE_API.md) (the Control API's own protocol), and
[ARCHITECTURE.md](ARCHITECTURE.md) (Phase E). This document is the network-topology
reference: what ports DMXReplay uses, how to pick an interface, and how mDNS
discovery works end to end.

## 1. Ports

| Port | Protocol | Direction | Used by |
|---|---|---|---|
| UDP 6454 | Art-Net | in (Recorder) / out (Player) | `dmxreplay.network.artnet` — [ARTNET.md](ARTNET.md) |
| UDP 5568 | sACN / E1.31 | in (Recorder) / out (Player) | `dmxreplay.network.sacn` — [SACN.md](SACN.md) |
| TCP 8080 (default, `--port`) | HTTP + WebSocket | in | `dmxreplay-server` — [MOBILE_API.md](MOBILE_API.md) |
| UDP 5353 | mDNS | in + out (multicast, `224.0.0.251`) | `dmxreplay.control.discovery` — §3 below |

The Control API port is the only one you would ever consider putting behind a
firewall rule limiting *which* LAN clients can reach it (the mobile app, a desktop
tool) — Art-Net/sACN are inherently broadcast/multicast-oriented protocols meant to
reach the whole lighting network segment, and mDNS is link-local by design (it never
routes off the local subnet, by the mDNS/RFC 6762 spec itself, not a DMXReplay
choice).

## 2. Choosing an interface

Every DMXReplay component that sends or listens for DMX (`ArtNetListener`/`Sender`,
`SACNListener`/`Sender`, and therefore `Recorder`/`Player`/`PlayerService`/
`RecorderService`) takes an explicit `interface_ip` — never "just picks one." On a
Raspberry Pi with both Ethernet and Wi-Fi active, this matters: DMX traffic and the
Control API do not have to share an interface.

A common, deliberate topology:

```
eth0  (wired)  -- Art-Net/sACN to the lighting network (low, consistent latency)
wlan0 (Wi-Fi)  -- Control API (8080) for the smartphone remote controller
```

`dmxreplay-server`'s `--host` binds the Control API's listening address (`0.0.0.0` —
the default — listens on every interface; a specific IP restricts it to one).
`PlayerService.set_output()`/the `player.toml` config's `interface` field
(`docs/RASPBERRY_PI.md` §14) independently controls which interface DMX itself goes
out on. Find an interface's IP with `ip addr` (Linux) — DMXReplay never guesses
Ethernet vs. Wi-Fi for you.

## 3. mDNS discovery

`dmxreplay-server` advertises itself (unless started with `--no-mdns`) as:

```
DMXReplay-<device-name>._dmxreplay._tcp.local.
```

`<device-name>` defaults to the machine's hostname, or `--device-name` if given. TXT
record properties:

```
api_version    -- e.g. "1.0" (docs/MOBILE_API.md §3)
auth_required  -- "true" or "false"
```

The SRV record's port is whatever `--port` the server bound (default `8080`); the A
record is this project's own best-effort "what's my LAN IP" detection (opens a UDP
socket toward a public IP purely to ask the OS which local route/address it would
use — no packet is actually sent, and no external service is contacted). On a
multi-homed device, prefer the interface actually used for the Control API when this
guess is wrong — override with the `ip=` parameter to `DeviceAdvertiser` if
embedding the API directly (not exposed as a CLI flag today; open a request if you
need it).

A client discovers devices by browsing `_dmxreplay._tcp.local.` — `dmxreplay.control.
discover_devices()` is a reference implementation (`src/dmxreplay/control/
discovery.py`) using the same `zeroconf` library the server uses to advertise. The
mobile app (Phase F, `mobile/lib/discovery/device_discovery_service.dart`) instead uses
the Flutter team's own `multicast_dns` package — a cross-platform mDNS client rather
than each platform's separate native API (`NSNetService`/Bonjour on iOS, `NsdManager`
on Android), avoiding two separate platform-channel implementations for one app — but
the wire format — standard mDNS/DNS-SD — is identical either way, and the same
`api_version`/`auth_required` TXT record shape this document specifies is what both
sides parse.

**Discovery is never required.** Every DMXReplay Control API client can connect
directly by IP:port with no mDNS involved at all (`docs/MOBILE_API.md` §1) — this is
a convenience layer, not a dependency, consistent with `docs/ARCHITECTURE.md` §5's
rule that discovery must never gate the underlying API.

### What can go wrong

- **mDNS doesn't cross subnets or VLANs.** A phone on a guest Wi-Fi network with
  client isolation, or a separate VLAN from the Pi's Ethernet segment, will not see
  the advertisement even though both can technically route to each other — this is
  inherent to link-local multicast, not a DMXReplay bug. Connect by IP instead.
- **Some routers/APs block multicast** (common on consumer Wi-Fi "AP isolation" or
  "guest network" features, and some corporate/venue networks) — same symptom, same
  fix.
- `dmxreplay-server` never lets an mDNS failure stop DMX output from working: if
  advertisement registration raises (e.g. no multicast route available), it logs a
  warning and continues running the actual Control API and DMX output normally
  (`src/dmxreplay/cli/server.py`) — verified in this project's own environment,
  where mDNS advertise+discover was confirmed to work end-to-end
  (`tests/test_discovery.py`), the same way `tests/test_sacn_network.py`'s multicast
  test is written to skip gracefully rather than fail hard if a given environment's
  multicast support differs.

## 4. What's not covered here

- The DMX wire protocols themselves (packet formats, universe addressing,
  multicast groups for sACN specifically) — [ARTNET.md](ARTNET.md)/[SACN.md](SACN.md).
- The Control API's own request/response protocol — [MOBILE_API.md](MOBILE_API.md).
- Physical network topology recommendations for a real lighting rig (switch choice,
  cable runs, PoE, etc.) — outside DMXReplay's scope; it works over any network that
  correctly delivers UDP broadcast/multicast and TCP.
