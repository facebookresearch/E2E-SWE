# `j1939` — SAE J1939 protocol stack for Python

A Python package **`j1939`** implementing the SAE J1939 application layer on top of [`python-can`](https://python-can.readthedocs.io/).
Top-level exports (importable as `j1939.<Name>`): `ElectronicControlUnit`, `ControllerApplication`, `Name`, `MessageId`, `ParameterGroupNumber`,
`Dm1`, `Dm11`, `Dm22`, `DTC`, `DtcLamp`, `Dm14Query`. Runtime deps: **`python-can`**, **`numpy`**. Internal module layout is your choice.

> **Dependencies & environment.** The runtime dependencies (`python-can`, `numpy`) are **already installed** and the
> environment is **fully offline — do not install anything** (there is no network and no package index). Your project is
> installed by a `setup.sh` that runs offline (`pip install -e . --no-build-isolation`), so just provide the package
> source and a standard `setup.py`/`pyproject.toml`; the build backend (setuptools) is pre-installed. Do not attempt to
> add new third-party dependencies — only `python-can`, `numpy`, and the Python standard library are available.

---

## 1. Wire formats (SAE J1939, deterministic)

### 1.1 CAN identifier layout (J1939-21, 29-bit extended)

```
bit  28           26 25                          8 7              0
    [ Priority(3) ][ Parameter Group Number(18)  ][ Source Addr(8) ]

can_id = (priority << 26) | (pgn << 8) | source_address
```

The PGN's 18 bits are themselves three sub-fields:

```
bit 17 16 15                 8 7                 0
   [R][DP][   PDU Format (8)  ][  PDU Specific (8)]
```

Top "Reserved" bit (J1939-21 EDP) is always 0. **PF `0..239`** → **PDU1** peer-to-peer, PS = destination (255 = GLOBAL, 254 = NULL); PDU1 "wire PGN" strips PS to 0, i.e. `pgn_value & 0x1FF00`. **PF `240..255`** → **PDU2** broadcast, PS = Group Extension and part of the PGN.

### 1.2 NAME (8-byte, J1939-81)

64-bit little-endian value, bit fields (LSB→MSB):

| Bits | Width | Field |
|---|---|---|
| 0..20 | 21 | identity_number |
| 21..31 | 11 | manufacturer_code |
| 32..34 | 3 | ecu_instance |
| 35..39 | 5 | function_instance |
| 40..47 | 8 | function |
| 48 | 1 | reserved (always 0) |
| 49..55 | 7 | vehicle_system |
| 56..59 | 4 | vehicle_system_instance |
| 60..62 | 3 | industry_group |
| 63 | 1 | arbitrary_address_capable |

### 1.3 Predefined PGNs and addresses

| PGN | Hex | Meaning |
|---|---|---|
| 59904 | `EA00` | Request |
| 60160 | `EB00` | TP.DT (transport protocol data transfer) |
| 60416 | `EC00` | TP.CM (transport protocol connection management) |
| 60928 | `EE00` | Address Claim |
| 55552 | `D900` | DM14 (memory-access request) |
| 55296 | `D800` | DM15 (memory-access response) |
| 55040 | `D700` | DM16 (binary data transfer) |
| 65226 | `FECA` | DM1 (active DTCs) |
| 65235 | `FED3` | DM11 (clear active DTCs) |
| 49920 | `C300` | DM22 (clear specific DTC) |

Reserved addresses: `254` = NULL ("cannot claim"), `255` = GLOBAL.

### 1.4 J1939-21 transport protocol (TP)

Used for PGN payloads > 8 bytes. **TP.CM** (PGN 60416, 8 bytes); transported PGN is three little-endian bytes at the end:

```
[ control_byte, b1, b2, b3, b4, pgn_lo, pgn_mid, pgn_hi ]
```

| Value | Name | Direction | b1..b4 |
|---|---|---|---|
| 16 | RTS | originator → responder | total_size_lo, total_size_hi, num_packets, max_pkts_per_cts |
| 17 | CTS | responder → originator | num_pkts_to_send, next_pkt_seq, 0xFF, 0xFF |
| 19 | EndOfMsgACK | responder → originator | total_size_lo, total_size_hi, num_packets, 0xFF |
| 32 | BAM | originator → broadcast | total_size_lo, total_size_hi, num_packets, 0xFF |
| 255 | Abort | either | abort_reason, 0xFF, 0xFF, 0xFF |

**TP.DT** (PGN 60160, 8 bytes):

```
[ sequence_number (1..N), 7 payload bytes — last frame pads unused bytes with 0xFF ]
```

Destination for TP.CM/TP.DT goes in the CAN-ID's PS (BAM uses PS = GLOBAL). Initial RTS/BAM carries the caller-supplied priority; all responder TP.CM and every TP.DT use priority **7**. Reassembly: receiver concatenates TP.DT bodies in sequence order, truncates to announced total_size, delivers one PDU under the announced PGN; peer-to-peer ends with EndOfMsgACK, BAM does not. **REQUEST PDU** (PGN 59904): the stack **emits** it as **exactly 3 bytes** — `[pgn & 0xFF, (pgn >> 8) & 0xFF, (pgn >> 16) & 0xFF]` — with no 0xFF padding (per §2.4, a sub-8-byte frame goes on the wire un-padded, DLC == payload length). On **receive**, however, an inbound Request may arrive right-padded with trailing `0xFF` to a full 8-byte CAN frame (a common bus DLC): the requested PGN must be parsed from the **first 3 payload bytes** and the frame must be honoured regardless of its length (accept any `len(data) >= 3` — do **not** reject a padded inbound Request). **Abort-while-busy**: RTS for an (originator, responder) pair with an open receive session → ABORT (255) with `abort_reason = 1` (BUSY); existing session untouched. Reasons: `1`=BUSY, `2`=RESOURCES, `3`=TIMEOUT. **CTS pause**: a CTS with `num_pkts_to_send == 0` pauses the originator until a later CTS with `num_pkts_to_send > 0`. **Stray CTS/EndOfMsgACK** (no matching send session) → ABORT (255) with `abort_reason = 2` (RESOURCES). **CTS windowing**: each CTS grants up to `max_cmdt_packets` segments and sets `next_pkt_seq` to the next not-yet-received sequence; the receiver re-issues CTS until all segments arrive, then sends EndOfMsgACK with the announced size and packet count. When **originating** an RTS, the stack advertises its own configured `max_cmdt_packets` in the RTS `max_pkts_per_cts` field (`b4`), capped at the message's `num_packets` (i.e. `min(max_cmdt_packets, num_packets)`).

### 1.5 Memory-access DM14 / DM15 / DM16 (J1939-73)

DM14 (host, PGN 55552) and DM15 (responder, PGN 55296) share this 8-byte layout:

```
[ object_count, ((direct & 0xF)<<4) | ((command & 7)<<1) | 1,
  addr_b0, addr_b1, addr_b2, addr_b3,
  key_or_status_lo, key_or_status_hi ]
```

`addr_b0..addr_b3` = 32-bit pointer, little-endian. Trailing SAE-reserved bit always `1`. Commands:

| Code | Command |
|---|---|
| 1 | READ |
| 2 | WRITE |
| 4 | OPERATION_COMPLETED |

In DM15, bytes 6-7 carry a seed (non-`0xFFFF`) or `0xFFFF` (proceed unauthenticated); status nibble `OPERATION_COMPLETED` signals completion. A responder's DM15 (and DM16) frames are **not** guaranteed to echo the initiating DM14's 32-bit address — those `addr_b0..addr_b3` bytes may be `0xFF` filler (address `0xFFFFFFFF`) — so the host must correlate an inbound DM15/DM16 to its outstanding query by the responder's **source address** (equal to the query's destination) and **PGN** only, keyed on the status/seed in bytes 6-7 (and length); it must **not** filter received DM15/DM16 on the address field. DM16 (PGN 55040) carries the binary payload:

```
[ byte_count_or_0xFF, payload_bytes... ]
```

Write: host emits DM16 immediately after the responder grants (key-accepted or no-seed-key DM15). Both Read and Write then complete the same way: after the responder's final `OPERATION_COMPLETED` DM15, the host sends a closing DM14 with `OPERATION_COMPLETED` and `key_or_status = 0xFFFF` (Read sends it after receiving DM16; Write sends it after the DM16 it emitted is acknowledged).

---

## 2. Public API

### 2.1 `j1939.Name`

```python
Name(**fields)        # all integer fields (see §1.2); ValueError if out of range
Name(value=int)       # build from a 64-bit value
Name(bytes=[8 ints])  # build from a little-endian 8-byte sequence
name.value            # int — the 64-bit value
name.bytes            # list[int] — 8 little-endian bytes
name.<field>          # readable + writable for every field in §1.2
Name.IndustryGroup    # nested: Global=0, OnHighway=1, AgriculturalAndForestry=2, Construction=3, Marine=4, Industrial=5
```

Construction from explicit fields must raise `ValueError` if any field exceeds its bit width (e.g. `industry_group=8`, `vehicle_system=128`, `function=256`, `manufacturer_code=2048`, `identity_number=(1<<21)`).

### 2.2 `j1939.MessageId`

```python
MessageId(can_id=int)                       # parse a 29-bit CAN-ID
MessageId(priority=, parameter_group_number=, source_address=)
mid.priority                                # 3-bit
mid.parameter_group_number                  # 18-bit (raw PGN bits, includes PS)
mid.source_address                          # 8-bit
mid.can_id                                  # composes per §1.1
```

`send_pgn`'s `frame_format` argument: int `2 = FBFF`, `3 = FEFF` (default); affects only J1939-22.

### 2.3 `j1939.ParameterGroupNumber`

```python
ParameterGroupNumber(data_page=0, pdu_format=0, pdu_specific=0)
pgn.data_page, pgn.pdu_format, pgn.pdu_specific
pgn.value                                   # (DP<<16)|(PF<<8)|PS
pgn.is_pdu1_format                          # True iff 0   <= PF <= 239
pgn.is_pdu2_format                          # True iff 240 <= PF <= 255
pgn.from_message_id(mid)                    # fill DP/PF/PS from a MessageId

ParameterGroupNumber.PGN  # nested: REQUEST=59904, ADDRESSCLAIM=60928, TP_CM=60416, DATATRANSFER=60160,
                          #         DM01=65226, DM11=65235, DM14=55552, DM15=55296, DM16=55040, DM22=49920, etc.
ParameterGroupNumber.Address.NULL    = 254
ParameterGroupNumber.Address.GLOBAL  = 255
```

### 2.4 `j1939.ElectronicControlUnit` (ECU)

```python
ElectronicControlUnit(
    data_link_layer='j1939-21',         # or 'j1939-22'
    max_cmdt_packets=1,                 # max segments per CTS round; <= 0xFF
    minimum_tp_rts_cts_dt_interval=None,
    minimum_tp_bam_dt_interval=None,
    send_message=None,                  # optional: override the raw-CAN sender
)
```

Methods:
- `add_ca(controller_application=ca) -> ca` — register a pre-built CA.
- `add_ca(name=, device_address=None) -> ca` — build and register a CA.
- `remove_ca(device_address) -> bool` — remove by preferred device address; `True` on success. Once removed, that CA no longer participates in message delivery: any subscription bound to it via `ControllerApplication.subscribe` stops receiving, and a peer-to-peer PDU addressed to its former device address is no longer accepted through it (per §4 it is dropped unless some other CA or subscriber accepts that destination). Broadcasts and PDUs to any still-registered CA are unaffected.
- `subscribe(callback, device_address=None)` — listener `cb(priority, pgn, source_address, timestamp, data)`; delivered `pgn` is the wire PGN (§1.1: PDU1 strips PS, PDU2 keeps GE), same for reassembled TP payloads. `device_address`: `None` (receive all), 8-bit address, or callable `dest -> bool`.
- `unsubscribe(callback)`
- `send_pgn(data_page, pdu_format, pdu_specific, priority, src_address, data, time_limit=0, frame_format=3)` — if `len(data) <= 8` emit one CAN frame; else fragment via J1939-21 TP (BAM if PDU2 or `pdu_specific == GLOBAL`, RTS/CTS otherwise). A single sub-8-byte frame is emitted with a DLC equal to its payload length — the data bytes are sent as-is, **not** padded out to 8 bytes with `0xFF` (e.g. a 6-byte payload goes on the wire as 6 bytes). The `pdu_specific` argument is reduced to its low 8 bits (`pdu_specific & 0xFF`) rather than being validated/rejected, so a caller may pass a full PGN value whose low byte is the intended PS / group extension. `send_pgn` does **not** wait for the peer: it returns as soon as the message has been handed to the stack — for a TP-fragmented message, once the initial RTS/BAM is on the wire — leaving the originator's send session open, and the remaining TP.CM/TP.DT exchange is driven by the stack from frames delivered later through `notify` (so a caller may inject the peer's replies on the same thread that called `send_pgn`). `time_limit` is not a wait on the caller.
- `notify(can_id, data, timestamp)` — inject a received CAN frame.
- `stop()` — stop the ECU and release background resources.

The stack drives delayed/timed transmissions itself; mechanism is your choice. `send_message=callable` (signature `(can_id, extended_id, data, fd_format=False)`) replaces the outgoing-frame sink. All CAN-IDs are 29-bit; `extended_id` is `True` for J1939-21.

### 2.5 `j1939.ControllerApplication` (CA)

```python
ControllerApplication(name=None, device_address_preferred=None, bypass_address_claim=False)
```

`name` accepts a `Name` (or an int value) **or `None`**. `name=None` constructs a CA with no J1939
NAME (equivalent to an all-zero NAME, value `0`); construction must not eagerly require a non-`None`
NAME. A nameless CA cannot drive the address-claim state machine (which needs a real NAME), so it is
used as a plain addressed endpoint together with `bypass_address_claim=True` and a preferred device
address; it still participates in message delivery / `message_acceptable` exactly like a named CA.

`bypass_address_claim=True` with a preferred address is in the `NORMAL` state **immediately upon construction** (and stays `NORMAL` once registered via `add_ca`) — it does **not** require a `start()` call to become usable: `device_address` returns the preferred address right away, `send_pgn` / `send_request` work, `message_acceptable` applies the `NORMAL`-state rules, and the CA auto-responds to an inbound Address-Claim Request — all without ever calling `start()`. Without `bypass_address_claim` (or with no preferred address) the CA starts in `NONE` and only runs the claim state machine when `start()` is called. (The "go directly to `NORMAL`" wording in the Address-claim paragraph below refers to skipping the `WAIT_VETO` step *during a `start()`-driven claim*, which is a separate path from this construction-time bypass.) Methods:
- `start()` / `stop()` — drive the claim state machine.
- `subscribe(callback)` / `unsubscribe(callback)` — bound subscription filtered through `self.message_acceptable(dest_address)`.
- `send_pgn(data_page, pdu_format, pdu_specific, priority, data, time_limit=0, frame_format=3)` — delegates to the ECU with the CA's current address as source; `RuntimeError` if called before claim completes.
- `send_request(data_page, pgn, destination)` — emit a Request PDU (PGN 59904); permitted before `NORMAL` only for the Address-Claim PGN (source = `NULL`).
- `message_acceptable(dest_address)` — override hook. Default: accept GLOBAL plus this CA's claimed address; `False` before `NORMAL`.

Properties: `state` ∈ `ControllerApplication.State.{NONE, WAIT_VETO, NORMAL, CANNOT_CLAIM}`; `device_address` returns `NULL` (254) whenever `state != NORMAL`.

**Address-claim**: on `start()`, after ~0.5 s, (1) emit Address Claimed — PGN 60928, 8-byte NAME payload, priority **6**, source = address being claimed, PS = GLOBAL; (2) preferred addresses `128..247` enter `WAIT_VETO` for ~250 ms; `0..127` and `248..253` go directly to `NORMAL`; (3) if no contender arrives, transition to `NORMAL`. On a contender's Address Claimed for the same address: if our NAME value is **greater**, we lose — with `arbitrary_address_capable == 0` go `CANNOT_CLAIM` and emit a final Address Claimed with source `NULL` (254); with `arbitrary_address_capable == 1` try `announced + 1`, emit Address Claimed for it, re-enter `WAIT_VETO`. Otherwise keep our address and re-announce. **Request handling**: a Request (PGN 59904) to us (or GLOBAL) while in `NORMAL` → re-emit Address Claimed if requested PGN is the Address-Claim PGN; otherwise dispatch is implementation-private. The inbound Request is parsed by its first 3 bytes and honoured even when the frame is 0xFF-padded to 8 bytes (see §1.4 receive note).

### 2.6 Diagnostic messages

```python
DTC(dtc=None, spn=None, fmi=None, oc=0)
# Build from a packed 32-bit DTC value, or from the (spn, fmi, oc) triple. Packing:
#   dtc = (spn & 0xFFFF) | ((spn & 0x70000) << 5) | ((fmi & 0x1F) << 16) | ((oc & 0x7F) << 24)
# Properties: .spn, .fmi, .oc, .cm (always 0 for new objects), .dtc
DtcLamp                     # status constants used as dict values: .OFF=0, .ON=1
                            # (ON_SLOW_FLASH=2, ON_FAST_FLASH=3, NA=4 also exist for completeness)
Dm1(ca)                     # active DTCs (PGN 65226)
   .subscribe(cb)           # cb(src_address, lamp_status_dict, dtc_list, timestamp)
   .start_send(cb, cycletime=1)  # cb() must return (lamp_status_dict, dtc_list)
   .stop_send(cb)           # cancel start_send; pass the same callback object
Dm11(ca)                    # request to clear active DTCs (PGN 65235)
   .request_clear_all(destination)
Dm22(ca)                    # clear a specific DTC (PGN 49920)
   .request_clear_act_dtc(dest, spn, fmi)
   .request_clear_pa_dtc(dest, spn, fmi)
```

`dtc_list`: `list` of dicts `{'spn': int, 'fmi': int, 'oc': int}` (produced by `start_send` callback, delivered to `subscribe`). DM22 wire
format (8 bytes, priority 6): byte 0 = `17` for `request_clear_act_dtc` / `1` for `request_clear_pa_dtc`; bytes 1..4 = `0xFF`; byte 5 =
`spn & 0xFF`; byte 6 = `(spn >> 8) & 0xFF`; byte 7 = `((spn >> 22) & 0xE0) | (fmi & 0x1F)`.

**DM01 emission priority**: when the DM01 payload (2 lamp bytes + 4 bytes per DTC) fits in 8 bytes, `Dm1` emits a single
frame at priority **6**; when it exceeds 8 bytes it is sent via the transport protocol with the caller priority fixed at
**7** (so the BAM/RTS TP.CM and every TP.DT go out at priority 7, per §1.4).

Lamp-status dicts use keys `'pl'`, `'awl'`, `'rsl'`, `'mil'` → `DtcLamp` values; missing keys default to `OFF`. DM1 encodes each lamp as 2 bits in byte 0 (lamp) + 2 bits in byte 1 (flash), packed **least-significant-first** in `pl/awl/rsl/mil` order: lamp `k` (k = 0,1,2,3 for `pl`, `awl`, `rsl`, `mil`) occupies bits `2k..2k+1` of both bytes — `pl` → bits 0-1, `awl` → bits 2-3, `rsl` → bits 4-5, `mil` → bits 6-7. Equivalently `byte0 |= lamp_bits << (2*k)` and `byte1 |= flash_bits << (2*k)`. (Example: `mil`=ON with the other three OFF gives byte0 = `0x40`, byte1 = `0xFF`.)

| Status | (lamp_bits, flash_bits) |
|---|---|
| `OFF` | `(0, 3)` |
| `ON` | `(1, 3)` |
| `ON_SLOW_FLASH` | `(1, 0)` |
| `ON_FAST_FLASH` | `(1, 1)` |
| `NA` | `(3, 3)` |

### 2.7 Memory access

```python
Dm14Query(ca)
   .set_seed_key_algorithm(fn)         # fn: seed:int -> key:int
   .read(dest_address, direct, address, object_count,
         object_byte_size=1, signed=False, return_raw_bytes=False)
   .write(dest_address, direct, address, values, object_byte_size=1)
```

`address`: 32-bit pointer (LE in DM14 payload, §1.5). `direct`: 4-bit nibble in the high nibble of DM14 byte 1. `read(...)` blocks (~1 s) and returns raw bytes (`return_raw_bytes=True`) or a list of `object_byte_size`-wide LE ints with `signed`. `write(...)` encodes each value LE to `object_byte_size` bytes; after the responder's `OPERATION_COMPLETED` DM15 ack it emits the closing `OPERATION_COMPLETED` DM14 (below) and returns (or times out silently). Seed/key dance is responder-driven: first DM15 with non-`0xFFFF` bytes 6-7 is a seed → host re-sends DM14 with `algorithm(seed)` as key; first DM15 with `0xFFFF` and matching length → proceed unauthenticated. DM14 bytes 6-7 by phase: **initial** = `0x0007` (SAE "user level 7", LE `0x07 0x00`); **post-seed** = 16-bit `key`; **final** `OPERATION_COMPLETED` = `0xFFFF`. The final `OPERATION_COMPLETED` DM14 repeats the initiating read/write call's `direct` nibble and 32-bit `address` (bytes 1-5 unchanged from the request), forcing only `object_count = 1` (byte 0) — regardless of the `object_count` used to initiate the read — and `key_or_status = 0xFFFF` (bytes 6-7).

---

## 3. J1939-22 (CAN-FD) — separate, secondary

`data_link_layer='j1939-22'` activates a parallel data-link layer with the same `add_ca` / `send_pgn` / `notify` API. PGN constants: `FEFF_MULTI_PG = 0x2500` (9472), `FD_TP_CM = 0x4D00` (19712), `FD_TP_DT = 0x4E00` (19968). Up to 4 concurrent BAM sessions per originator and 8 concurrent RTS/CTS sessions per originator+responder pair, distinguished by the `session` nibble in `data[0]`. The `session` value belongs to the transfer, not to a side: a receiving RTS/CTS responder MUST **echo** the originator's session number — the high nibble of the incoming RTS's `data[0]` — in every TP.CM (CTS, EOM_STATUS, EOM_ACK) and TP.DT frame it emits for that transfer, so the originator can correlate the response to its outgoing session; receive-side sessions are keyed by `(source_address, session)`.

**FD TP.CM** (12 bytes):

```
data[0]    = (control & 0xF) | ((session & 0xF) << 4)
data[1..3] = message_size, 24-bit little-endian
data[4..6] = num_segments OR next_packet (per control type), 24-bit LE
data[7]    = role depends on control (max_segments / size_of_assurance_data / 0xFF)
data[8]    = role depends on control (assurance data type / request_code / 0xFF)
data[9..11]= pgn, 24-bit little-endian (with PS=0 for PDU1)
```

Per-control byte_7 / byte_8: `RTS (0)` byte_7 = max segments per CTS window, byte_8 = assurance data type (0 = none); `CTS (1)` `message_size = 0xFFFFFF`, `num_segments` slot carries **next_packet**, byte_7 = segments granted, byte_8 = request_code (0); `EOM_STATUS (2)` byte_7 = size_of_assurance_data (0), byte_8 = assurance data type (0); `EOM_ACK (3)` byte_7 = `0xFF`, byte_8 = `0xFF`; `BAM (4)` byte_7 = `0xFF`, byte_8 = `0`; `ABORT (15)` `message_size = num_segments = 0xFFFFFF`, byte_7 = `0xFF`, byte_8 = reason code.

**FD TP.DT**:

```
data[0]    = (dtfi & 0xF) | ((session & 0xF) << 4)   # dtfi = 0 for "no assurance data"
data[1..3] = segment_number, 24-bit little-endian (1-based)
data[4..]  = up to 60 payload bytes
```

**Multi-PG carrier**: every J1939-22 application PDU with payload ≤ 60 bytes is transmitted inside a multi-PG carrier frame — never as a raw direct CAN frame. Carrier CAN-id PGN = `FEFF_MULTI_PG | (dst & 0xFF)` (= `0x2500 | dst`). Payload concatenates one or more c-pgs, each a 4-byte header + contained PDU:

```
byte 0 = (tos << 5) | (tf << 2) | ((cpgn >> 16) & 0x3)
byte 1 = (cpgn >> 8) & 0xFF
byte 2 =  cpgn       & 0xFF
byte 3 =  data_length (contained PDU's byte count, 0..60)
bytes 4..(3+data_length) = contained PDU bytes
```

Use `tos = 2`, `tf = 0`. `cpgn = pgn.value` for PDU2; `cpgn = pgn.value & 0xFFF00` for PDU1 (dst travels in the carrier CAN-id). After all c-pgs are concatenated, pad to the next valid CAN-FD length: first up to three pad bytes = `0x00`, remainder = `0xAA`. Valid lengths: `0..8, 12, 16, 20, 24, 32, 48, 64`.

**FD BAM completion**: originator sends an explicit `EOM_STATUS` (control `2`) TP.CM after the last TP.DT, confirming `message_size` and `num_segments`. Receivers MUST defer notifying subscribers until `EOM_STATUS` arrives. No `EOM_ACK` for broadcast.

---

## 4. Behavioral notes

PDU2 frames deliver to every subscriber as broadcast (destination = GLOBAL); PDU1 frames deliver only if some subscriber or CA accepts the destination (GLOBAL always accepted). This destination-acceptance check gates the **entire** peer-to-peer (PDU1) receive path — not just final delivery: a peer-to-peer frame whose destination is not accepted is dropped without any further processing. For a single-frame (≤ 8-byte) PDU1 the destination is **accepted** — and the frame is delivered to matching subscribers — if it is GLOBAL, OR any registered CA accepts it (per `message_acceptable`), OR any bare ECU-level subscriber (one registered via `ElectronicControlUnit.subscribe` with no controller application) was given a matching `device_address` (its 8-bit address equals the destination, or its callable `dest -> bool` returns True). The transport-protocol responder is gated more narrowly: the stack engages it (opens a receive session and answers an RTS with a CTS, or accepts a BAM) **only** when the transfer's destination is GLOBAL or an accepted CA address — a bare subscriber's `device_address` does **not** by itself make the stack a TP responder, so an RTS addressed to an address no local CA accepts is ignored — no CTS, no receive session, no abort. So on a shared bus that carries every frame to all nodes, a peer-to-peer RTS is answered only by its addressed responder, and concurrent peer-to-peer transfers reach only their intended destinations. TP.CM, TP.DT, Address-Claim, and Request frames (when accepted) are intercepted by the stack, not forwarded raw. Concurrent TP transfers between different (source, destination) address pairs must not interfere — each reassembles and delivers its own payload independently.
