# RaptorQ — a Fountain Code (RFC 6330) Library for Rust

Build `raptorq`, a Rust library that implements the RaptorQ forward-error-correction code defined in
[RFC 6330](https://www.rfc-editor.org/rfc/rfc6330). RaptorQ is a *fountain code*: from an object of
`K` source symbols an encoder can generate a practically unlimited stream of *encoding symbols*
(the `K` source symbols themselves plus arbitrarily many *repair* symbols), and a decoder can
reconstruct the original object from **any** sufficiently large subset of those symbols — typically
just `K` symbols, with the recovery probability after receiving `K + h` symbols being
`1 - 1/256^(h+1)`. This makes it ideal for reliable transport over lossy/erasure channels.

The library must implement the full RaptorQ scheme as specified in RFC 6330 (and its errata), which
is the normative reference for all internal algorithms, constants, and generator functions. This
document specifies only the **public API contract and the on-the-wire formats** your implementation
must conform to — the algorithm itself is yours to derive from the RFC.

## Dependencies

- **None.** The library is implemented entirely with the Rust standard library — no third-party
  crates. The environment is offline; do not attempt to add or download dependencies.

## Build Environment

- Rust toolchain (edition 2021 or later), fully offline (no crate downloads).
- Crate name / library name: `raptorq` (a `lib` crate). The integration tests depend on it as an
  external crate via `use raptorq::{...};`, so the public items below must be exported from the
  crate root.
- The crate must build with its **default** features and no extra Cargo features enabled. Internal
  module organization under `src/` is entirely up to you; only the crate-root re-exports matter.

Your `setup.sh` must build the project offline. Example:

```bash
#!/bin/bash
export CARGO_NET_OFFLINE=true
export CARGO_HOME="${CARGO_HOME:-/usr/local/cargo}"
export CARGO_TARGET_DIR="${CARGO_TARGET_DIR:-/tmp/target}"
cargo build --offline --lib || return 1
```

## Package Structure

```
/app/
  Cargo.toml          # package "raptorq", [lib], zero dependencies
  setup.sh
  src/
    lib.rs            # re-exports the public API below; internal modules as you see fit
    ...
```

## Public API Reference

All of the following items must be importable from the crate root (`raptorq::Item`).

### `PayloadId`

Identifies an encoding symbol within an object: a source block number and an encoding symbol ID
(ESI). The ESI is a **24-bit** unsigned integer (must be `< 2^24`).

```rust
impl PayloadId {
    pub fn new(source_block_number: u8, encoding_symbol_id: u32) -> PayloadId; // asserts esi < 2^24
    pub fn deserialize(data: &[u8; 4]) -> PayloadId;
    pub fn serialize(&self) -> [u8; 4];
    pub fn source_block_number(&self) -> u8;
    pub fn encoding_symbol_id(&self) -> u32;
}
```

**Wire format (4 bytes), RFC 6330 §3.2:** byte 0 is the source block number; bytes 1–3 are the
encoding symbol ID as a 24-bit **big-endian** integer.

`PayloadId` must support equality comparison (`PartialEq`/`Eq`) and `Clone`.

### `EncodingPacket`

A transmittable unit: a `PayloadId` plus the symbol's payload bytes.

```rust
impl EncodingPacket {
    pub fn new(payload_id: PayloadId, data: Vec<u8>) -> EncodingPacket;
    pub fn deserialize(data: &[u8]) -> EncodingPacket;
    pub fn serialize(&self) -> Vec<u8>;
    pub fn payload_id(&self) -> &PayloadId;
    pub fn data(&self) -> &[u8];
    pub fn split(self) -> (PayloadId, Vec<u8>);
}
```

**Wire format:** the 4-byte serialized `PayloadId` followed verbatim by the payload bytes.
`deserialize` reads the first 4 bytes as the `PayloadId` and the remainder as the payload.
`EncodingPacket` must support `PartialEq`/`Eq` and `Clone`.

### `ObjectTransmissionInformation`

The configuration shared between encoder and decoder (the "Common FEC Object Transmission
Information"). Fields: transfer length `F` (a 40-bit value, i.e. `<= 942574504275`), symbol size `T`,
number of source blocks `Z`, number of sub-blocks `N`, and symbol alignment `Al`.

```rust
impl ObjectTransmissionInformation {
    pub fn new(transfer_length: u64, symbol_size: u16, source_blocks: u8,
               sub_blocks: u16, alignment: u8) -> ObjectTransmissionInformation;
    pub fn with_defaults(transfer_length: u64, max_packet_size: u16) -> ObjectTransmissionInformation;
    pub fn deserialize(data: &[u8; 12]) -> ObjectTransmissionInformation;
    pub fn serialize(&self) -> [u8; 12];
    pub fn transfer_length(&self) -> u64;
    pub fn symbol_size(&self) -> u16;
    pub fn source_blocks(&self) -> u8;
    pub fn sub_blocks(&self) -> u16;
    pub fn symbol_alignment(&self) -> u8;
}
```

- `new` constructs the configuration directly from the given RFC parameters.
- `with_defaults` derives `T`, `Z`, `N`, `Al` from the transfer length and a maximum packet
  (symbol) size using the RFC 6330 §4.3 parameter-derivation procedure, using a default decoder
  memory requirement (`WS`) of `10 * 1024 * 1024` bytes (10 MiB) and a default symbol alignment
  `Al` of `8` when `max_packet_size >= 64`, else `1`; the derived `symbol_size` must be
  `<= max_packet_size` and a multiple of the chosen alignment, and `source_blocks >= 1`.
- **Wire format (12 bytes), RFC 6330 §3.3.3:** bytes 0–4 = `F` as a 40-bit **big-endian** integer;
  byte 5 = reserved (`0`); bytes 6–7 = `T` (big-endian `u16`); byte 8 = `Z`; bytes 9–10 = `N`
  (big-endian `u16`); byte 11 = `Al`.
- Must support `Copy`/`Clone` and `PartialEq`/`Eq`.

### `Encoder`

```rust
impl Encoder {
    pub fn new(data: &[u8], config: ObjectTransmissionInformation) -> Encoder;
    pub fn with_defaults(data: &[u8], maximum_transmission_unit: u16) -> Encoder;
    pub fn get_config(&self) -> ObjectTransmissionInformation;
    pub fn get_encoded_packets(&self, repair_packets_per_block: u32) -> Vec<EncodingPacket>;
}
```

- `new` builds an encoder for `data` using an explicit configuration. The object is split into `Z`
  source blocks (zero-padded as needed) per the RFC; `data.len()` must equal `config.transfer_length()`.
- `with_defaults` is `Encoder::new(data, ObjectTransmissionInformation::with_defaults(data.len(), mtu))`.
- `get_config` returns the configuration the decoder must be constructed with.
- `get_encoded_packets(r)` returns, **for each source block in order**, that block's `K` *source*
  packets followed by `r` *repair* packets. Encoding-symbol numbering is **systematic**: within a
  block the source symbols have ESIs `0..K`, and repair symbols are numbered consecutively starting
  at `K'` (the extended source-block symbol count — see `extended_source_block_symbols`). Each
  packet's source block number identifies its block. A source packet's payload is the corresponding
  source symbol's bytes; concatenating a single block's source-packet payloads in ESI order
  reproduces that block's (padded) data.

### `Decoder`

```rust
impl Decoder {
    pub fn new(config: ObjectTransmissionInformation) -> Decoder;
    pub fn decode(&mut self, packet: EncodingPacket) -> Option<Vec<u8>>;
}
```

- `new` constructs a decoder from the encoder's `ObjectTransmissionInformation`.
- `decode` ingests one encoding packet and returns `Some(object)` once the **entire** object has
  been recovered (all source blocks decoded), or `None` if more packets are needed. The returned
  `Vec<u8>` is exactly the original object: length `transfer_length()`, with any encoder padding
  removed. Feeding fewer than `K` symbols for a block can never recover it. Order of ingestion does
  not matter, and the object is recoverable from source symbols, repair symbols, or any mixture.

### Free functions

```rust
pub fn partition(i: u32, j: u32) -> (u32, u32, u32, u32);
pub fn extended_source_block_symbols(source_block_symbols: u32) -> u32;
```

- `partition(I, J)` is the RFC 6330 §4.4.1.2 `Partition[I, J]` function. It returns
  `(IL, IS, JL, JS)` where `IL = ceil(I / J)`, `IS = floor(I / J)`, `JL = I - IS * J`, and
  `JS = J - JL`. (It accepts any integer types convertible into `u32`; the tests call it with `u32`
  arguments.)
- `extended_source_block_symbols(K)` returns `K'`, the smallest value in the RFC 6330 systematic
  index table that is `>= K` (RFC §5.3.1). It is non-decreasing and idempotent: `K' >= K` and
  `extended_source_block_symbols(K') == K'`.
