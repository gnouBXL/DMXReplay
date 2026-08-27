# ARTNET.md — Art-Net mapping for DMXReplay

Normative for how DMXReplay ingests/emits Art-Net. Companion to
[SPECIFICATION.md §8](SPECIFICATION.md#8-art-net-mapping). Based on the Art-Net 4
protocol as published by Artistic Licence.

## 1. Port-Address addressing

Art-Net 4 addresses a universe with a 15-bit **Port-Address**, split into three fields:

```
 bit: 14............8 7......4 3......0
      Net (7 bits)    SubNet   Universe
                       (4 bits) (4 bits)

Port-Address = (Net << 8) | (SubNet << 4) | Universe
```

- `Net`: 0–127
- `Sub-Net`: 0–15
- `Universe`: 0–15 (this is the *Art-Net* universe field, distinct from "a DMXReplay
  universe" or "an sACN universe" — all three are different numbering systems that
  happen to share the word "universe")

DMXReplay stores `net`, `subnet`, and `universe` as three separate integers per row in
the manifest (`SPECIFICATION.md` §10.2) — **never** a single collapsed index — so the
original Port-Address is always exactly recoverable in both directions:

```
port_address = (net << 8) | (subnet << 4) | universe
net       = (port_address >> 8) & 0x7F
subnet    = (port_address >> 4) & 0x0F
universe  =  port_address       & 0x0F
```

## 1.1 A note on "Universe 17": flattened numbering vs. the raw field

Most consoles and lighting software show the user a single "universe number"
(e.g. "Universe 17") rather than three separate Net/Sub-Net/Universe fields. That
displayed number is, in effect, **the flattened Port-Address** (§1), *not* the raw
4-bit `Universe` field DMXReplay's manifest stores. `Port-Address 17` decomposes to
`Net=0, Sub-Net=1, Universe=1` (`17 = 0×256 + 1×16 + 1`), **not** `Universe=17`, which
would be out of the field's `0–15` range. Implementers converting from a
console-displayed universe number to DMXReplay's stored `net`/`subnet`/`universe`
fields MUST go through the Port-Address decomposition in §1 — never treat the
displayed number as the raw `Universe` field directly. DMXReplay's reference
implementation provides this both ways:
`UniverseMapping.from_artnet_port_address(row, port_address)` and
`UniverseMapping.port_address()` (`src/dmxreplay/metadata/schema.py`).

## 2. DMXReplay row index vs. Art-Net addressing

A DMXReplay row index (§SPECIFICATION.md §7) is an internal storage detail — the
Nth active universe encountered, packed contiguously starting at 0. It carries **no**
implicit relationship to `Net`/`Sub-Net`/`Universe`. The conversion in both directions
always goes through the manifest:

```
row  →  manifest.universes[row] = {protocol: "Art-Net", net, subnet, universe}
{net, subnet, universe}  →  row : reverse lookup over manifest.universes[]
```

## 3. Packets handled in V1

| ArtNet OpCode | Direction | V1 support |
|---|---|---|
| `OpPoll` (0x2000) | recorder → network | SHOULD send periodically while listening, to encourage `OpPollReply` discovery |
| `OpPollReply` (0x2100) | network → recorder | Used for auto-detection of available sources/universes (UI display only — not required to receive DMX) |
| `OpDmx` (0x5000) | both | REQUIRED — this is the actual DMX data packet |
| `OpOutput`/legacy DMX opcodes from Art-Net 1–3 | network → recorder | SHOULD be accepted where the payload shape matches `OpDmx` (backward compatibility, brief §11), version field permitting |
| `OpTimeCode` (0x9700) | — | Documented only (§5), not implemented as a sync source in V1 |
| Everything else | — | MUST be ignored (not treated as an error) if well-formed but unrecognized; MUST be logged and dropped if malformed (SPECIFICATION.md §15/§18) |

## 4. `OpDmx` packet layout and validation (recorder side)

Exact byte layout (matches `src/dmxreplay/network/artnet/packet.py`):

| Offset | Size | Field | Notes |
|---|---|---|---|
| 0–7 | 8 | `ID` | ASCII `"Art-Net"` + `0x00` |
| 8–9 | 2 | `OpCode` | uint16, **little-endian** (low byte first) — `0x5000` for `OpDmx` |
| 10–11 | 2 | `ProtVerHi`, `ProtVerLo` | uint16, **big-endian** (high byte first) |
| 12 | 1 | `Sequence` | `0` = sequencing disabled by sender; else wraps `1–255` (§5) |
| 13 | 1 | `Physical` | Informational input-port index; not used for addressing |
| 14 | 1 | `SubUni` | `(Sub-Net << 4) \| Universe` |
| 15 | 1 | `Net` | `0–127` (top bit reserved, must be `0`) |
| 16–17 | 2 | `LengthHi`, `LengthLo` | uint16, **big-endian**, DMX data length |
| 18… | `Length` | `Data` | DMX channel values |

Before use, a recorder MUST validate, in order:

1. Packet is UDP, destination port `6454`.
2. First 8 bytes equal the Art-Net ID string `"Art-Net\0"`.
3. OpCode (bytes 8–9, little-endian) `== 0x5000`.
4. Protocol version (bytes 10–11, big-endian) `>= 14` (Art-Net 3/4-era protocol
   revisions used in practice; a lower/garbage value is rejected as malformed rather
   than guessed at).
5. Declared DMX data length (bytes 16–17, big-endian) is even, `>= 2`, `<= 512`, and
   matches the actual remaining payload length (protects against a short/truncated UDP
   datagram being read out of bounds).
6. `Net` (byte 15) `<= 127`.

A packet failing any check is dropped and logged at `WARN` (SPECIFICATION.md §18); it
MUST NOT be forwarded to the DMX engine or allowed to affect any active universe's
state.

## 5. Sequence numbers

`OpDmx` byte 12 is the sequence number (`0` = sequencing disabled by sender; `1–255`
wrapping). V1 recorder behavior: sequence numbers are logged for diagnostics
(out-of-order/dropped-packet detection) but are **not** used to reorder packets before
storage — the recorder timestamps and stores packets in arrival order (see
[TIMING.md](TIMING.md)); out-of-order arrival is rare on a LAN and reordering is left as
a documented future refinement rather than V1 scope creep.

## 6. Output (player side)

The player MUST generate well-formed `OpDmx` packets: correct `Art-Net\0` header,
OpCode, protocol version, an incrementing (wrapping 1–255) sequence number per
destination universe, correct `Physical`/`SubUni`/`Net` fields derived from the row's
manifest addressing (§2), and the exact stored channel count as `Length`. The player
MUST NOT send packets for universes not present in the loaded file, and MUST NOT send
malformed or filler packets to "pad" unused universes.

Both unicast (to a configured destination IP) and broadcast (to the interface's
broadcast address) are supported; the network interface used MUST be explicitly
selected by the user (SPECIFICATION.md/brief §48), never silently auto-chosen on a
multi-interface machine.

## 7. Art-Net TimeCode (`OpTimeCode`) — documented, not implemented in V1

Art-Net 4 defines `OpTimeCode` (opcode `0x9700`) for distributing SMPTE-style
hours:minutes:seconds:frames timecode over the network. V1 does not consume or emit it.
The architecture's `ClockProvider` abstraction ([TIMING.md](TIMING.md)) is designed so
a future version can add `OpTimeCode` as an external clock source (network → DMXReplay
master timeline) and/or an output sync target (DMXReplay master timeline → network)
without changing the master-timeline interface itself (brief §41).

## 8. Multiple sources

The network layer (`src/dmxreplay/network/artnet`) is structured to allow binding
multiple listeners (e.g. per-interface, or per-multicast-group) feeding one DMX engine
(brief §14). V1's recorder GUI may expose only one active source/interface at a time;
the underlying engine API ([API.md](API.md)) does not assume single-source.
