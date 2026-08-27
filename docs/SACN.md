# SACN.md — sACN / ANSI E1.31 mapping for DMXReplay

Normative for how DMXReplay ingests/emits sACN. Companion to
[SPECIFICATION.md §9](SPECIFICATION.md#9-sacn-mapping). Based on ANSI E1.31 (Streaming
ACN) layered on ANSI E1.17 (ACN).

## 1. Addressing

sACN addresses a **universe** directly with a 16-bit number, `1`–`63999` (0 and values
above 63999 are reserved/invalid per E1.31). Unlike Art-Net, there is no
Net/Sub-Net split. DMXReplay's manifest stores this as the row's `universe` field with
`protocol: "sACN"` (no `net`/`subnet` fields — see SPECIFICATION.md §10.2).

```
row  →  manifest.universes[row] = {protocol: "sACN", universe}
universe  →  row : reverse lookup over manifest.universes[]
```

## 2. Packet layers consumed (V1)

Exact byte layout for a full 512-slot packet (matches
`src/dmxreplay/network/sacn/packet.py`; total size 638 bytes: `38` root + `77`
framing + `10` DMP header + `1` start code + `512` DMX data):

| Offset | Size | Layer | Field |
|---|---|---|---|
| 0–1 | 2 | Root | Preamble Size (`0x0010`) |
| 2–3 | 2 | Root | Post-amble Size (`0x0000`) |
| 4–15 | 12 | Root | ACN Packet Identifier (`"ASC-E1.17\0\0\0"`) |
| 16–17 | 2 | Root | Flags (top 4 bits `0x7`) & Length |
| 18–21 | 4 | Root | Vector = `VECTOR_ROOT_E131_DATA` (`0x00000004`) |
| 22–37 | 16 | Root | CID (sender's UUID) |
| 38–39 | 2 | Framing | Flags & Length |
| 40–43 | 4 | Framing | Vector = `VECTOR_E131_DATA_PACKET` (`0x00000002`) |
| 44–107 | 64 | Framing | Source Name (UTF-8, null-padded) |
| 108 | 1 | Framing | Priority (`0`–`200`) |
| 109–110 | 2 | Framing | Synchronization Address |
| 111 | 1 | Framing | Sequence Number |
| 112 | 1 | Framing | Options (bit7 Preview_Data, bit6 Stream_Terminated, bit5 Force_Sync) |
| 113–114 | 2 | Framing | Universe |
| 115–116 | 2 | DMP | Flags & Length |
| 117 | 1 | DMP | Vector = `VECTOR_DMP_SET_PROPERTY` (`0x02`) |
| 118 | 1 | DMP | Address Type & Data Type (`0xA1`) |
| 119–120 | 2 | DMP | First Property Address (`0x0000`) |
| 121–122 | 2 | DMP | Address Increment (`0x0001`) |
| 123–124 | 2 | DMP | Property Value Count (`1 + slot count`) |
| 125 | 1 | DMP | Start Code (`0x00` for DMX — see §3) |
| 126… | ≤512 | DMP | DMX data slots |

V1 parses only what it needs to extract DMX data, validating each layer's declared
length against the actual UDP payload before trusting any offset derived from it
(SPECIFICATION.md §18):

1. **Root Layer** (ACN) — validates the 12-byte ACN packet identifier, and that the
   vector identifies an E1.31 data packet (`VECTOR_ROOT_E131_DATA`,
   `0x00000004`). CID (component identifier) is read for diagnostics/source
   identification but not required for correctness.
2. **Framing Layer** — validates vector `VECTOR_E131_DATA_PACKET` (`0x00000002`),
   reads `Universe` (the addressing field, §1), `Sequence Number`, `Options` (only the
   `Preview_Data` and `Stream_Terminated` bits are inspected — see §4), and `Priority`
   (read but not acted on in V1, see §5).
3. **DMP Layer** — validates vector `VECTOR_DMP_SET_PROPERTY` (`0x02`), address type/
   data type byte `0xA1`, and reads the property values starting at the first data
   octet, which is **DMX slot 0** (the E1.31 "start code" slot — see §3) followed by
   up to 512 DMX data slots.

## 3. DMX start code

E1.31 always transmits slot 0 as a start code before the 512 data slots. V1 only stores
frames where the start code is `0x00` (standard "null start code" DMX data) — the
common case for lighting. Packets with a non-zero start code (e.g. `0xCC` RDM,
alternate START codes) are **not DMX data** in the DMXReplay sense; V1 drops them at
the recorder with a `DEBUG`-level log entry rather than an error (documented as future
scope, not a malformed-packet condition — see SPECIFICATION.md §17 future extensions,
RDM).

## 4. Options bits handled in V1

| Bit | Meaning | V1 behavior |
|---|---|---|
| `Preview_Data` | Sender marks this stream as "visualizer preview, not live" | Recorder MAY surface this in the source list UI; does not affect whether the universe is recorded (left to the user) |
| `Stream_Terminated` | Sender is explicitly ending this universe's stream | Recorder MUST stop expecting further packets for that universe and MAY mark it inactive in the live status UI; does not truncate already-recorded data |
| `Force_Synchronization` | Requests synchronized application of a prior sync-addressed packet | Not implemented in V1 — see §6 |

## 5. Priority and merging — deferred

E1.31 defines per-source priority (0–200) so multiple consoles can send to the same
universe with deterministic arbitration (highest priority wins; equal priority = HTP
merge per-channel). **V1 records from a single active source per universe** and does
not implement priority-based merging of multiple simultaneous sources. `Priority` is
read and logged for diagnostics. Multi-source priority merging is documented future
scope (brief §12/§56), architecturally accommodated by keeping per-source packet
handling separate from the "committed DMX frame" step in the engine ([API.md](API.md))
so a merge stage can be inserted later without restructuring the network layer.

## 6. Universe synchronization (`E131_Universe_Sync`) — deferred

E1.31 defines a companion sync-packet mechanism (vector `VECTOR_E131_EXTENDED_SYNCHRONIZATION`,
universe number `0` reserved for the sync layer) that lets a sender hold multiple
universes' worth of updates and apply them atomically on a sync packet. V1 does not
implement sending or honoring sync packets — every received data packet is timestamped
and applied to the DMX engine as soon as it arrives (see [TIMING.md](TIMING.md)).
Documented as future scope.

## 7. Discovery (`E131_Universe_Discovery`) — deferred

E1.31 defines a periodic universe-discovery broadcast (`VECTOR_ROOT_E131_EXTENDED`,
`VECTOR_E131_DISCOVERY_UNIVERSE`) that lets a receiver learn what universes are on the
network without waiting for data. V1's recorder relies on passive observation of actual
data packets to populate its "detected universes" UI (brief §13) rather than sending
or parsing discovery packets. Documented future scope.

## 8. Output (player side)

The player MUST generate well-formed E1.31 data packets: correct root/framing/DMP
layers, an incrementing (wrapping 0–255) per-universe sequence number, the correct
`Universe` field from the row's manifest addressing (§1), start code `0x00`, and the
exact stored channel count. A configurable `Priority` (default 100, the E1.31 default)
is sent per brief §31. Unicast (to a configured destination) is the V1 default; sACN's
standard is multicast to the universe's designated multicast address
(`239.255.<universe-high-byte>.<universe-low-byte>`) — V1 supports selecting either
mode, with the network interface always explicit (SPECIFICATION.md/brief §48).

## 9. Multiple sources

As with Art-Net (see [ARTNET.md](ARTNET.md) §8), the network layer is structured to
allow multiple simultaneous listeners; V1's merging behavior is the single-source
model described in §5.
