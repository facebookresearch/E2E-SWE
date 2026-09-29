# Implement the `xknx` KNX protocol codec

## Background (read first if you have never seen KNX)

**KNX** is an international standard for home and building automation. Devices (light
switches, thermostats, blinds, sensors) talk to each other over a shared **KNX bus**.
**KNXnet/IP** is the variant of the same protocol that carries those messages over an
ordinary IP network (so a PC or gateway can join the bus over Ethernet/Wi-Fi). Both are
binary protocols: every message is a precisely-defined sequence of bytes ("the wire
format").

A handful of KNX terms used throughout this document, defined here once:

- **Datapoint Type (DPT)** — the rule for converting one logical value (a temperature,
  a percentage, an on/off flag, a colour) to/from its byte representation. Each DPT has
  a `main.sub` number (e.g. temperature is DPT `9.001`).
- **Group address** — a *logical* destination like `"1/2/3"` that one or more devices
  subscribe to (e.g. "all kitchen lights"). 16 bits on the wire.
- **Individual address** — a *physical* device address like `"1.1.5"` (area.line.device).
  Also 16 bits on the wire.
- **Telegram** — one application-level message: a destination address plus a payload.
- **APCI** (Application-layer Protocol Control Information) — the few bits that say what
  kind of application action a telegram performs (read a value, write a value, respond).
- **TPCI** (Transport-layer Protocol Control Information) — one control octet that
  describes the transport relationship (connectionless vs a numbered point-to-point
  connection, connect/disconnect/ack).
- **cEMI** (common External Message Interface) — the standard container format that
  wraps a telegram (addresses + TPCI + APCI + payload) into a self-describing frame.
- **KNXnet/IP frame** — the outermost container that carries a cEMI frame (or a
  discovery/connection message) over IP, with a 6-byte header.
- **NPDU** — the bytes of the telegram that follow the addresses inside a cEMI frame
  (the TPCI octet plus the APCI/payload). The cEMI frame stores a one-byte length for it,
  but that length octet is **`len(NPDU) - 1`**: it counts only the APCI/payload octets and
  excludes the first/TPCI octet (the APCI high bits share that first octet).

The byte/bit layouts in this document are part of the published KNX standard and are
restated here so your implementation matches the wire format exactly.

## Goal

Build a Python library named **`xknx`** that encodes and decodes the wire formats of
the KNX / KNXnet/IP protocol. The library is a **pure-Python codec**: it converts
between high-level Python values and the exact bytes that travel on a KNX bus or a
KNXnet/IP network. There is no networking, no I/O, no async — only value ⟷ bytes.

This task implements **only the codec layer**. You do **not** implement the
networking/transport layer (UDP/TCP/routing sockets, asyncio, device discovery),
the device/abstraction layer, the management/application client, or KNX Data Secure
(cryptography). Those subsystems are out of scope; the package must import and run
without them being exercised.

The package is organised into four subpackages, importable as shown:

- `xknx.dpt` — Datapoint Types (value ⟷ bytes conversion)
- `xknx.telegram` — addresses, the telegram model, APCI and TPCI
- `xknx.cemi` — cEMI frame layer
- `xknx.knxip` — KNXnet/IP frame layer
- `xknx.exceptions` — the codec exception types `ConversionError`,
  `CouldNotParseTelegram`, and `CouldNotParseKNXIP` (importable as
  `from xknx.exceptions import ...`)

KNX is a published standard; the bit/byte layouts below are part of that standard and
are specified here so your implementation matches the wire format exactly.

---

## Dependencies

The environment is **offline** — there is no network and you must **not** install anything.
Everything needed at runtime is already installed. The project is installed by a `setup.sh`
that runs **offline** in this environment (for Python, a `pyproject.toml` / `setup.py` that
`pip install -e . --no-build-isolation` can build against the pre-installed setuptools backend).

The following Python packages are pre-installed and may be used:

- `cryptography` — pre-installed (declared dependency of the package; not needed by the codec
  subset itself, but available if your package layout imports it).
- `ifaddr` — pre-installed (declared dependency of the package; not needed by the codec subset
  itself, but available).
- `async_timeout`, `typing_extensions` — pre-installed (declared dependencies for Python < 3.11).

No system services are required. The codec is **pure Python** and can be implemented with the
standard library alone (e.g. `struct`, `enum`, `dataclasses`) — the codec layer you build does
not require the packages above.

---

## API usage examples (calling conventions)

These snippets show **how the public API is called** — the calling convention and the
shapes of arguments/return values. They are illustrative: the values used here are
placeholders, not a lookup table of expected outputs (the exact byte encodings for each
DPT, the cEMI/TPCI octet packing, and the DPT19 validity bits are specified in the
sections below and are what your implementation must get right). Use these to anchor the
class names, method names, and how the layers compose.

```python
# --- Payload wrappers (xknx.dpt) -----------------------------------------
from xknx.dpt import DPTArray, DPTBinary

multi_byte = DPTArray((0xAB, 0xCD))          # one-or-more whole bytes
multi_byte == DPTArray(b"\xab\xcd")          # True — equal by value
tiny = DPTBinary(1)                          # <= 6 bits, rides in the APCI octet

# --- A DPT transcoder: value <-> KNX payload (xknx.dpt) ------------------
from xknx.dpt import DPTBase, DPTScaling

# Each DPT is a class with two classmethods. to_knx() returns a wrapper,
# from_knx() takes a wrapper and returns the Python value. (Exact bytes per
# DPT are defined in the sections below; shapes shown here.)
payload = DPTScaling.to_knx(25)              # -> DPTArray(...)   (a percentage)
percent = DPTScaling.from_knx(payload)       # -> int
DPTScaling.dpt_main_number, DPTScaling.dpt_sub_number, DPTScaling.value_type

# Registry lookup by value-type string or by {"main": m, "sub": s}:
cls = DPTBase.parse_transcoder("scaling")    # -> the DPTScaling class (or None)
cls = DPTBase.parse_transcoder({"main": 5, "sub": 1})

# --- Addresses (xknx.telegram.address) ----------------------------------
from xknx.telegram.address import GroupAddress, IndividualAddress

ga = GroupAddress("0/0/1")                   # 3-level string or a raw int
ga.raw                                        # -> 16-bit int
ga.to_knx()                                   # -> 2 big-endian bytes
str(ga)                                        # -> "0/0/1"
ia = IndividualAddress("1.1.1")              # area.line.device

# --- APCI service primitives (xknx.telegram.apci) -----------------------
from xknx.telegram.apci import APCI, GroupValueWrite, GroupValueRead

apci = GroupValueWrite(DPTArray((0xAB, 0xCD)))
octets = apci.to_knx()                        # -> bytes  (APCI header + payload)
service = APCI.from_knx(octets)               # -> the matching APCI instance
service.value                                 # -> the decoded payload wrapper

# --- TPCI transport control (xknx.telegram.tpci) ------------------------
from xknx.telegram.tpci import TPCI, TConnect, TDataConnected

TConnect().to_knx()                           # -> a single octet (int)
TDataConnected(sequence_number=1).to_knx()    # -> a single octet (int)
inst = TPCI.resolve(octet, dst_is_group_address=True, dst_is_zero=False)

# --- Telegram (xknx.telegram) -------------------------------------------
from xknx.telegram import Telegram

telegram = Telegram(
    destination_address=ga,
    payload=GroupValueWrite(DPTArray((0xAB, 0xCD))),
    tpci=None,                                # optional; defaults per the rules below
)

# --- cEMI frame (xknx.cemi) ---------------------------------------------
from xknx.cemi import CEMIFrame, CEMILData, CEMIMessageCode

ldata = CEMILData.init_from_telegram(telegram, src_addr=ia)
frame = CEMIFrame(code=CEMIMessageCode.L_DATA_IND, data=ldata)
cemi_bytes = frame.to_knx()                   # -> bytes
back = CEMIFrame.from_knx(cemi_bytes)         # parse; raises on unknown code
back.data.telegram()                          # -> recovered Telegram

# --- KNXnet/IP frame (xknx.knxip) ---------------------------------------
from xknx.knxip import KNXIPFrame, RoutingIndication

ip_frame = KNXIPFrame.init_from_body(RoutingIndication(raw_cemi=cemi_bytes))
wire = ip_frame.to_knx()                       # -> bytes  (6-byte header + body)
parsed, remainder = KNXIPFrame.from_knx(wire)  # dispatch on service type
parsed.body                                    # -> the body object
```

The round-trip contract is uniform across every layer: `to_knx(value) -> bytes/wrapper`
and the corresponding `from_knx(...) -> value` are inverses, and the wire bytes must
match the KNX standard exactly as specified below.

---

## Payload wrapper types (`xknx.dpt`)

Two wrapper classes carry a raw KNX payload:

- `DPTBinary(value: int)` — a payload of **at most 6 bits** that rides inside the APCI
  octet (used by 1-bit and other tiny datapoints).
- `DPTArray(data)` — a payload of one or more whole bytes. `data` may be an `int`,
  a `bytes`/`bytearray`, or an iterable of ints. `DPTArray((0x0C, 0x1A))` and
  `DPTArray(b"\x0c\x1a")` are equal.

Both support equality by value. Encoders return one of these wrappers; decoders accept
one of these wrappers.

## Datapoint Types — the DPT framework (`xknx.dpt`)

Each Datapoint Type (DPT) is a class providing two class methods:

- `to_knx(value) -> DPTArray | DPTBinary` — encode a Python value to a KNX payload.
- `from_knx(payload) -> value` — decode a KNX payload back to a Python value.

Every DPT class exposes these class attributes:

- `dpt_main_number: int` and `dpt_sub_number: int` — the KNX `main.sub` numbering
  (e.g. temperature is DPT 9.001, so `dpt_main_number == 9`, `dpt_sub_number == 1`).
- `value_type: str` — a unique snake_case identifier (e.g. `"temperature"`).
- `payload_type` — the wrapper class this DPT uses (`DPTArray` or `DPTBinary`).

A base class `DPTBase` provides a registry/lookup classmethod
`parse_transcoder(identifier)` that returns the matching DPT **class** (or `None`):

- by `value_type` string, e.g. `parse_transcoder("temperature")`;
- by `{"main": m, "sub": s}` mapping, e.g. `parse_transcoder({"main": 9, "sub": 1})`.

`from_knx` raises `CouldNotParseTelegram` when the payload has the wrong length.
`to_knx` raises `ConversionError` when the value is out of the DPT's valid range or
otherwise not serialisable.

### DPT categories you must implement

The exact value ⟷ byte mappings (standard KNX):

- **DPT 1 — 1-bit boolean.** `DPTBinary` payload. Encodes a boolean to `DPTBinary(1)`
  / `DPTBinary(0)`. `DPTSwitch` decodes to a `Switch` enum (`Switch.ON` / `Switch.OFF`).
- **DPT 5 — 8-bit unsigned.** `DPTValue1ByteUnsigned` maps the byte directly (0..255).
  `DPTScaling` maps a percentage `0..100` linearly onto the byte `0x00..0xFF`. Both
  directions **round to the nearest integer** (no truncation): `to_knx(v)` returns
  `round(v / 100 * 255)` (so 50% → `0x80`, 100% → `0xFF`) and `from_knx` returns
  `round(raw / 255 * 100)` as an `int` (so `0x80` → `50`, `0xFF` → `100`).
  Out-of-range input raises `ConversionError`.
- **DPT 7 — 2-byte unsigned** (`DPT2ByteUnsigned`), big-endian.
- **DPT 8 — 2-byte signed** (`DPTValue2Count`), two's-complement big-endian.
- **DPT 9 — 2-byte KNX float** (`DPT2ByteFloat`, the generic base transcoder for this
  category). 16 bits as `MEEEEMMM MMMMMMMM`: sign bit, a 4-bit exponent `E`, and an
  11-bit two's-complement mantissa `M`; the encoded value is `0.01 * M * 2**E`. The base
  `DPT2ByteFloat` is not range-clamped: it covers the full range representable by that
  encoding, and a value outside it raises `ConversionError`. `DPTTemperature` is the
  DPT 9.001 subclass (a temperature-clamped specialisation of `DPT2ByteFloat`).
- **DPT 13 — 4-byte signed** (`DPT4ByteSigned`), two's-complement big-endian.
- **DPT 14 — 4-byte float** (`DPT4ByteFloat`), IEEE-754 single precision big-endian.
- **DPT 10 — time of day** (`DPTTime`): 3 bytes. The high 3 bits of byte 0 are the
  day-of-week (0 = no day, 1 = Monday … 7 = Sunday); the low 5 bits are the hour.
  Byte 1 is minutes, byte 2 is seconds. `to_knx` accepts a mapping with keys
  `hour`, `minutes`, `seconds`, and optional `day`; `day` may be given as the
  integer code or as the lowercase weekday name (e.g. `1` or `"monday"`,
  `0`/`"no_day"` for none). `from_knx` returns an object exposing `.hour`,
  `.minutes`, `.seconds` (ints) and `.day` (the day-of-week as an enum-like
  member exposing a numeric `.value` day code, Monday = 1 … Sunday = 7).
- **DPT 11 — date** (`DPTDate`): 3 bytes — day, month, year-within-century (years
  90..99 → 1990s, 0..89 → 2000s). `to_knx` accepts a mapping with keys `year`,
  `month`, `day`; `from_knx` returns an object exposing `.year`, `.month`, `.day`
  as ints (with `.year` the full four-digit year).
- **DPT 19 — date+time** (`DPTDateTime`): 8 bytes. Byte 0 is the year offset from
  1900; byte 1 is the month; byte 2 is the day; byte 3 packs the day-of-week in its
  high 3 bits and the hour in its low 5 bits; byte 4 is minutes; byte 5 is seconds.
  Bytes 6 and 7 are the status/validity field. Byte 6 (MSB→LSB): bit 7 `fault`,
  bit 6 `working_day`, bit 5 `working_day_invalid` (set when working-day is not
  given), bit 4 `year_invalid` (year not given), bit 3 `date_invalid` (month/day
  not given), bit 2 `weekday_invalid` (day-of-week not given), bit 1 `time_invalid`
  (hour/minutes/seconds not given), bit 0 `dst`. Byte 7: bit 7 `external_sync`,
  bit 6 `source_reliable`, remaining bits zero. Any field not supplied is encoded
  as 0 with its corresponding `*_invalid` bit set. `to_knx` accepts a mapping with
  optional keys `year`, `month`, `day`, `hour`, `minutes`, `seconds`, `day_of_week`
  (and booleans `fault`, `working_day`, `dst`, `external_sync`, `source_reliable`);
  `from_knx` returns an object exposing `.year`, `.month`, `.day`, `.hour`,
  `.minutes`, `.seconds`, `.day_of_week`, and the boolean flags above. On decode, a
  field whose `*_invalid` bit is set is returned as `None` rather than the stored 0
  (so `.hour`, `.minutes`, `.seconds` are `None` when `time_invalid` is set; `.year`
  is `None` when `year_invalid` is set; `.month`/`.day` are `None` when `date_invalid`
  is set; `.day_of_week` is `None` when `weekday_invalid` is set; `.working_day` is
  `None` when `working_day_invalid` is set), otherwise the decoded integer. The
  `.day_of_week` is an enum-like member exposing a numeric `.value` day code
  (Monday = 1 … Sunday = 7).
- **DPT 16 — string** (`DPTString`): a fixed 14-byte ASCII field, right-padded with
  `0x00`.
- **DPT 232 — RGB colour** (`DPTColorRGB`): 3 bytes `red`, `green`, `blue`. Accepts a
  mapping with keys `red`, `green`, `blue`; decodes to an object with `.red`,
  `.green`, `.blue` attributes.

## Telegram model (`xknx.telegram`)

### Addresses (`xknx.telegram.address`)

- `GroupAddress` — a 16-bit KNX group address. Constructible from the 3-level string
  `"main/middle/sub"` (5/3/8 bits: `main<<11 | middle<<8 | sub`) or from a raw int.
  `.raw` is the 16-bit integer; `.to_knx()` returns 2 big-endian bytes; `str()` returns
  the `"main/middle/sub"` form.
- `IndividualAddress` — a 16-bit physical address `"area.line.device"` (4/4/8 bits:
  `area<<12 | line<<8 | device`). Same `.raw` / `.to_knx()` / `str()` contract.

### APCI (`xknx.telegram.apci`)

Application-layer service primitives. Each is a class with `to_knx() -> bytes` and a
base `APCI.from_knx(raw: bytes)` that resolves the service from its APCI code and
returns the matching instance. Implement at least:

- `GroupValueRead()` — APCI code `0x000`.
- `GroupValueWrite(value)` — APCI code `0x080`. The value is a `DPTArray` or
  `DPTBinary`. A `DPTBinary` (≤ 6 bits) is packed into the low bits of the second APCI
  octet (so `GroupValueWrite(DPTBinary(1))` encodes as `00 81`); a `DPTArray` follows
  the 2-octet APCI header (so `GroupValueWrite(DPTArray((0x0C, 0x1A)))` encodes as
  `00 80 0C 1A`). `GroupValueRead()` encodes as `00 00`.
- `GroupValueResponse(value)` — APCI code `0x040`. Encodes its payload exactly like
  `GroupValueWrite` but against code `0x040` (so a `DPTBinary(1)` packs into the second
  octet as `00 41`, and a `DPTArray((0x0C, 0x1A))` follows the header as `00 40 0C 1A`).

`GroupValueWrite` and `GroupValueResponse` expose the decoded payload as `.value`.

### TPCI (`xknx.telegram.tpci`)

Transport-layer control. Each TPCI class has `to_knx() -> int` (the TPCI octet value)
and the base provides `TPCI.resolve(raw_octet, *, dst_is_group_address, dst_is_zero)`
returning the matching instance. The standard control codes:

- `TDataGroup` / `TDataBroadcast` / `TDataTagGroup` — data primitives selected by
  whether the destination is a group address and whether it is the zero (broadcast)
  address.
- `TDataIndividual` — point-to-point connectionless data.
- `TConnect()` → `0x80`, `TDisconnect()` → `0x81`.
- `TDataConnected(sequence_number)` and `TAck(sequence_number)` / `TNak(sequence_number)`
  carry a 4-bit sequence number in the standard bit positions (e.g.
  `TDataConnected(7).to_knx() == 0b01011100`, `TAck(10).to_knx() == 0b11101010`).
  `TNak` shares the `TAck` base but with the low (negative-acknowledge) control bit set —
  i.e. the Nak base is the Ack base `| 1`.

### Telegram (`xknx.telegram`)

`Telegram(destination_address, payload=None, tpci=None, source_address=...)` is the
high-level message object combining a destination address, an APCI payload, and a TPCI.
Telegrams compare equal by value.

## cEMI frame layer (`xknx.cemi`)

`CEMIFrame(code, data)` represents a cEMI message:

- `code` is a `CEMIMessageCode` enum (e.g. `L_DATA_IND = 0x29`, `L_DATA_REQ = 0x11`).
- `data` is a cEMI payload object. `CEMILData` is the L_Data payload; build one from a
  telegram with `CEMILData.init_from_telegram(telegram, src_addr=...)` and recover the
  telegram with `.telegram()`. When `src_addr` is omitted the source individual address
  defaults to `0.0.0` (encoded as the two bytes `0x00 0x00`).

`CEMIFrame.to_knx() -> bytes` serialises the message code, the additional-info length
(0), the two control fields, source and destination addresses, the one-byte NPDU length
(`len(NPDU) - 1`, as defined above), the TPCI octet, and the APCI/payload.
`CEMIFrame.from_knx(raw)` parses it back and raises on an unknown message code or
malformed input.

The two control octets default to standard frame / do-not-repeat / no-ack /
hop-count-6, with the second octet selecting the **destination address type and
priority**: a group-address destination sets the address-type bit and low priority
(control byte 2 `0xE0`, giving the common `… BC E0 …` prefix), while an
individual-address destination clears the address-type bit and uses system priority
(control byte 2 `0x60`, giving `… B0 60 …`). A **control TPDU** (`TConnect`,
`TDisconnect`, `TAck`, `TNak`) carries the 8-bit TPCI octet with **no APCI payload**
and an NPDU length of 0; a **data TPDU** carries the APCI/payload and the TPCI's low
bits are OR-ed into the first APCI octet. `TDataConnected` is a **numbered (connected)
data TPDU**, not a control TPDU: when its telegram carries an APCI payload the payload
is retained (it is encoded exactly like any other data TPDU) — its TPCI octet's low
bits are OR-ed into the first APCI octet and the NPDU length reflects the payload.
Only a bare `TDataConnected` with no payload behaves like a control TPDU (TPCI octet
only, NPDU length 0).

## KNXnet/IP frame layer (`xknx.knxip`)

Every KNXnet/IP frame starts with a 6-byte header: header length `0x06`, protocol
version `0x10`, a 2-byte big-endian **service type identifier**, and the 2-byte
big-endian **total frame length** (header + body).

`KNXIPFrame` is the container:

- `KNXIPFrame.init_from_body(body)` builds a frame around a body object (filling the
  header automatically).
- `KNXIPFrame.to_knx() -> bytes` serialises header + body.
- `KNXIPFrame.from_knx(raw) -> (frame, remainder)` parses a frame, dispatching on the
  service type, and returns the frame plus any unparsed trailing bytes. Malformed
  frames raise `CouldNotParseKNXIP`.
- `frame.body` is the parsed body object.

Implement at least these bodies (service type identifiers in parentheses):

- `SearchRequest` (`0x0201`) — carries a discovery `HPAI`, exposed as the constructor
  keyword / attribute `discovery_endpoint` (i.e.
  `SearchRequest(discovery_endpoint: HPAI)` / `frame.body.discovery_endpoint`).
- `ConnectRequest` (`0x0205`) — a control `HPAI` (constructor keyword / attribute
  `control_endpoint`), a data `HPAI` (keyword / attribute `data_endpoint`), and a
  `ConnectRequestInformation` (`cri`) selecting `connection_type`
  (`ConnectRequestType.TUNNEL_CONNECTION` / `DEVICE_MGMT_CONNECTION`), `knx_layer`
  (a `TunnellingLayer` enum with members `DATA_LINK_LAYER` = `0x02`,
  `RAW_LAYER` = `0x04`, `BUSMONITOR_LAYER` = `0x80`), and an optional individual
  address. The CRI is serialised as a leading length byte followed by a
  `connection_type` byte (`DEVICE_MGMT_CONNECTION` = `0x03`,
  `TUNNEL_CONNECTION` = `0x04`). A `DEVICE_MGMT_CONNECTION` CRI carries nothing
  more (length byte `0x02`, two bytes total). A `TUNNEL_CONNECTION` CRI additionally
  carries the `knx_layer` byte followed by a reserved `0x00` byte (length byte `0x04`,
  four bytes total) — so a `DATA_LINK_LAYER` tunnel CRI with no individual address is
  `04 04 02 00`.
- `TunnellingRequest` (`0x0420`) — a `communication_channel_id`, an 8-bit
  `sequence_counter`, and a raw cEMI byte string `raw_cemi`. Its body begins with a
  4-byte connection header — a structure-length byte (`0x04`), the
  `communication_channel_id` byte, the `sequence_counter` byte, and a reserved `0x00`
  byte — immediately followed by the raw cEMI bytes.
- `RoutingIndication` (`0x0530`) — a raw cEMI byte string `raw_cemi`.

`HPAI(ip_addr=..., port=..., protocol=...)` is the Host Protocol Address Information
structure: a length byte, a protocol byte (default UDP/IPv4 = `0x01`; IPv4/TCP =
`0x02`), 4 IPv4 bytes, and a 2-byte big-endian port. It compares equal by value.

---

## Deliverable

Provide an installable package `xknx` exposing the four subpackages and the public
classes/functions named above, importable exactly as written in this document. The
codec must produce and consume bytes exactly matching the KNX wire format described
here. Provide a `setup.sh` script that installs the package into the current
environment **offline** (e.g. `pip install -e . --no-build-isolation`, using the
pre-installed setuptools build backend — do not fetch anything from the network).
