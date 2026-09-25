// Hidden grading suite for the RaptorQ (RFC 6330) reimplementation task.
//
// These are black-box integration tests: they exercise the crate ONLY through its public API,
// asserting observable behaviour (wire formats, the partition function, and encode/decode recovery
// under packet loss). They never reach into private internals, so any faithful RFC 6330
// implementation passes regardless of how it is structured.
//
// Self-contained and std-only (a tiny deterministic LCG stands in for `rand`), so the suite builds
// and runs fully offline. One `#[test] fn` == one graded CTRF entry.

use raptorq::{
    Decoder, Encoder, EncodingPacket, ObjectTransmissionInformation, PayloadId,
    extended_source_block_symbols, partition,
};

// ----------------------------------------------------------------------------------------------
// Deterministic helpers (not #[test], so they are not graded)
// ----------------------------------------------------------------------------------------------

/// A small SplitMix64-style generator: deterministic, seedable, no external crates.
struct Lcg(u64);

impl Lcg {
    fn new(seed: u64) -> Self {
        Lcg(seed)
    }

    fn next_u64(&mut self) -> u64 {
        // SplitMix64
        self.0 = self.0.wrapping_add(0x9E3779B97F4A7C15);
        let mut z = self.0;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58476D1CE4E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D049BB133111EB);
        z ^ (z >> 31)
    }

    fn bytes(&mut self, len: usize) -> Vec<u8> {
        (0..len).map(|_| (self.next_u64() & 0xFF) as u8).collect()
    }

    fn below(&mut self, bound: usize) -> usize {
        (self.next_u64() % bound as u64) as usize
    }
}

/// Feed packets to a fresh decoder one at a time; return the first successful reconstruction.
fn decode_all(config: ObjectTransmissionInformation, packets: Vec<EncodingPacket>) -> Option<Vec<u8>> {
    let mut decoder = Decoder::new(config);
    let mut result = None;
    for packet in packets {
        result = decoder.decode(packet);
        if result.is_some() {
            break;
        }
    }
    result
}

/// Single source block, single sub-block, alignment 1 — the simplest configuration, giving exact
/// control over symbol layout for white-box-free byte assertions.
fn simple_config(transfer_length: u64, symbol_size: u16) -> ObjectTransmissionInformation {
    ObjectTransmissionInformation::new(transfer_length, symbol_size, 1, 1, 1)
}

// ----------------------------------------------------------------------------------------------
// Wire format — PayloadId / EncodingPacket / ObjectTransmissionInformation (RFC 6330 §3)
// ----------------------------------------------------------------------------------------------

#[test]
fn payload_id_roundtrip_and_bytes() {
    let id = PayloadId::new(5, 0x010203);
    assert_eq!(id.source_block_number(), 5);
    assert_eq!(id.encoding_symbol_id(), 0x010203);
    // 1 byte SBN followed by a 24-bit big-endian Encoding Symbol ID.
    assert_eq!(id.serialize(), [5, 0x01, 0x02, 0x03]);
    assert_eq!(PayloadId::deserialize(&id.serialize()), id);
}

#[test]
fn payload_id_esi_is_24_bit_big_endian() {
    let max = PayloadId::new(0xAB, 0xFFFFFF);
    assert_eq!(max.serialize(), [0xAB, 0xFF, 0xFF, 0xFF]);
    let mixed = PayloadId::new(0, 0x00ABCD);
    assert_eq!(mixed.serialize(), [0x00, 0x00, 0xAB, 0xCD]);
    assert_eq!(PayloadId::deserialize(&[0x07, 0x12, 0x34, 0x56]).encoding_symbol_id(), 0x123456);
}

#[test]
fn encoding_packet_roundtrip_and_layout() {
    let id = PayloadId::new(3, 42);
    let payload = vec![9u8, 8, 7, 6, 5];
    let packet = EncodingPacket::new(id.clone(), payload.clone());
    let wire = packet.serialize();
    // Serialized form is the 4-byte PayloadId followed verbatim by the payload.
    assert_eq!(&wire[0..4], &id.serialize());
    assert_eq!(&wire[4..], payload.as_slice());
    let back = EncodingPacket::deserialize(&wire);
    assert_eq!(back, packet);
    assert_eq!(back.payload_id(), &id);
    assert_eq!(back.data(), payload.as_slice());
    let (split_id, split_data) = back.split();
    assert_eq!(split_id, id);
    assert_eq!(split_data, payload);
}

#[test]
fn oti_serialize_layout_and_reserved_byte() {
    // transfer_length is a 40-bit field; check the byte packing explicitly. A large symbol size and
    // max source-block count keep symbols-per-block within the RFC limit while still letting the
    // upper transfer-length bytes be non-zero.
    let oti = ObjectTransmissionInformation::new(0x01_02_03_04_05, 65535, 255, 1, 1);
    let bytes = oti.serialize();
    assert_eq!(bytes.len(), 12);
    assert_eq!(&bytes[0..5], &[0x01, 0x02, 0x03, 0x04, 0x05]); // F (40-bit, big-endian)
    assert_eq!(bytes[5], 0); // reserved
    assert_eq!(&bytes[6..8], &[0xFF, 0xFF]); // symbol size = 65535
    assert_eq!(bytes[8], 255); // num source blocks
    assert_eq!(&bytes[9..11], &[0, 1]); // num sub-blocks
    assert_eq!(bytes[11], 1); // alignment
}

#[test]
fn oti_roundtrips_and_accessors() {
    let oti = ObjectTransmissionInformation::new(70000, 1280, 4, 3, 8);
    let back = ObjectTransmissionInformation::deserialize(&oti.serialize());
    assert_eq!(back, oti);
    assert_eq!(back.transfer_length(), 70000);
    assert_eq!(back.symbol_size(), 1280);
    assert_eq!(back.source_blocks(), 4);
    assert_eq!(back.sub_blocks(), 3);
    assert_eq!(back.symbol_alignment(), 8);
}

// ----------------------------------------------------------------------------------------------
// partition() and configuration derivation (RFC 6330 §4.4.1.2)
// ----------------------------------------------------------------------------------------------

#[test]
fn partition_function_values() {
    // partition(I, J) = (ceil(I/J), floor(I/J), I - floor(I/J)*J, J - (I - floor(I/J)*J))
    assert_eq!(partition(10u32, 3u32), (4, 3, 1, 2));
    assert_eq!(partition(10u32, 2u32), (5, 5, 0, 2));
    assert_eq!(partition(7u32, 3u32), (3, 2, 1, 2));
    assert_eq!(partition(4u32, 4u32), (1, 1, 0, 4));
    // J == 1 (a single part): every element goes to the "long" partition.
    assert_eq!(partition(5u32, 1u32), (5, 5, 0, 1));
    assert_eq!(partition(1u32, 1u32), (1, 1, 0, 1));
}

#[test]
fn with_defaults_config_invariants() {
    for &(len, mtu) in &[(10_000u64, 1400u16), (1u64, 64u16), (250_000u64, 512u16)] {
        let cfg = Encoder::with_defaults(&vec![0u8; len as usize], mtu).get_config();
        assert_eq!(cfg.transfer_length(), len);
        assert!(cfg.symbol_size() > 0);
        assert!(cfg.symbol_size() <= mtu);
        assert_eq!(cfg.symbol_size() % cfg.symbol_alignment() as u16, 0);
        assert!(cfg.source_blocks() >= 1);
    }
}

#[test]
fn extended_source_block_symbols_is_non_shrinking() {
    // K' >= K, and rounding an already-extended value is a fixed point.
    for k in [1u32, 2, 10, 26, 100, 500] {
        let kprime = extended_source_block_symbols(k);
        assert!(kprime >= k, "K'={kprime} must be >= K={k}");
        assert_eq!(extended_source_block_symbols(kprime), kprime);
    }
    // K' is the SMALLEST RFC 6330 systematic-index (§5.6 Table 2) value >= K, not the identity:
    // pin the exact table lookups, including inputs (11, 27, 100, 500) that are not themselves table
    // entries and so must round strictly UP — this rejects an identity / no-round implementation.
    assert_eq!(extended_source_block_symbols(1), 10);
    assert_eq!(extended_source_block_symbols(2), 10);
    assert_eq!(extended_source_block_symbols(10), 10);
    assert_eq!(extended_source_block_symbols(11), 12);
    assert_eq!(extended_source_block_symbols(26), 26);
    assert_eq!(extended_source_block_symbols(27), 30);
    assert_eq!(extended_source_block_symbols(100), 101);
    assert_eq!(extended_source_block_symbols(500), 511);
}

// ----------------------------------------------------------------------------------------------
// Encode/decode recovery — the core RaptorQ contract
// ----------------------------------------------------------------------------------------------

#[test]
fn roundtrip_no_loss_single_block() {
    let symbol_size = 64u16;
    let k = 16usize;
    let data = Lcg::new(1).bytes(k * symbol_size as usize);
    let config = simple_config(data.len() as u64, symbol_size);
    let encoder = Encoder::new(&data, config);
    let packets = encoder.get_encoded_packets(0); // source symbols only
    assert_eq!(decode_all(config, packets), Some(data));
}

#[test]
fn source_packets_are_systematic_in_order() {
    // For a single block / single sub-block / alignment 1 with no padding, the source packets'
    // payloads, concatenated in encoding-symbol-id order, reproduce the original object exactly.
    let symbol_size = 32u16;
    let k = 20usize;
    let data = Lcg::new(2).bytes(k * symbol_size as usize);
    let config = simple_config(data.len() as u64, symbol_size);
    let encoder = Encoder::new(&data, config);
    let mut source: Vec<EncodingPacket> = encoder.get_encoded_packets(0);
    source.sort_by_key(|p| p.payload_id().encoding_symbol_id());
    let reassembled: Vec<u8> = source.iter().flat_map(|p| p.data().to_vec()).collect();
    assert_eq!(reassembled, data);
}

#[test]
fn roundtrip_with_defaults_no_loss() {
    let data = Lcg::new(3).bytes(10_000);
    let encoder = Encoder::with_defaults(&data, 1400);
    let config = encoder.get_config();
    let packets = encoder.get_encoded_packets(15);
    assert_eq!(decode_all(config, packets), Some(data));
}

#[test]
fn roundtrip_recovers_with_random_erasures() {
    let data = Lcg::new(4).bytes(10_000);
    let encoder = Encoder::with_defaults(&data, 1400);
    let config = encoder.get_config();
    let mut packets = encoder.get_encoded_packets(20);
    // Erase 12 packets at random positions (fewer than the 20 repair symbols per block).
    let mut rng = Lcg::new(99);
    for _ in 0..12 {
        if packets.is_empty() {
            break;
        }
        let idx = rng.below(packets.len());
        packets.remove(idx);
    }
    assert_eq!(decode_all(config, packets), Some(data));
}

#[test]
fn roundtrip_repair_only() {
    // Drop EVERY source packet and recover purely from repair symbols (the fountain property).
    let symbol_size = 64u16;
    let k = 10usize;
    let data = Lcg::new(5).bytes(k * symbol_size as usize);
    let config = simple_config(data.len() as u64, symbol_size);
    let encoder = Encoder::new(&data, config);
    let all = encoder.get_encoded_packets(k as u32 + 10); // generous overhead
    let repair_only: Vec<EncodingPacket> = all
        .into_iter()
        .filter(|p| p.payload_id().encoding_symbol_id() >= k as u32)
        .collect();
    assert_eq!(decode_all(config, repair_only), Some(data));
}

#[test]
fn decode_returns_none_until_enough_packets() {
    let symbol_size = 64u16;
    let k = 16usize;
    let data = Lcg::new(6).bytes(k * symbol_size as usize);
    let config = simple_config(data.len() as u64, symbol_size);
    let encoder = Encoder::new(&data, config);
    let mut packets = encoder.get_encoded_packets(0);
    packets.truncate(k - 1); // strictly fewer than K symbols can never decode
    let mut decoder = Decoder::new(config);
    for packet in packets {
        assert_eq!(decoder.decode(packet), None);
    }
}

#[test]
fn roundtrip_non_multiple_symbol_size() {
    // Object length not a multiple of the symbol size exercises the zero-padding path; the decoder
    // must still return exactly the original (un-padded) bytes.
    let data = Lcg::new(7).bytes(10_000 + 37);
    let encoder = Encoder::with_defaults(&data, 1400);
    let config = encoder.get_config();
    let recovered = decode_all(config, encoder.get_encoded_packets(15)).expect("decode");
    assert_eq!(recovered.len(), data.len());
    assert_eq!(recovered, data);
}

#[test]
fn roundtrip_multiple_source_blocks() {
    // Force two source blocks; verify both source-block-numbers appear and the object recovers.
    let symbol_size = 64u16;
    let kt = 40usize; // total symbols across both blocks
    let data = Lcg::new(8).bytes(kt * symbol_size as usize);
    let config = ObjectTransmissionInformation::new(data.len() as u64, symbol_size, 2, 1, 1);
    let encoder = Encoder::new(&data, config);
    let packets = encoder.get_encoded_packets(10);
    let mut sbns: Vec<u8> = packets.iter().map(|p| p.payload_id().source_block_number()).collect();
    sbns.sort_unstable();
    sbns.dedup();
    assert_eq!(sbns, vec![0, 1]);
    assert_eq!(decode_all(config, packets), Some(data));
}

#[test]
fn roundtrip_with_sub_blocks() {
    // sub_blocks > 1 interleaves sub-symbols; recovery must be unaffected.
    let symbol_size = 64u16; // divisible by alignment(8) * something
    let k = 12usize;
    let data = Lcg::new(9).bytes(k * symbol_size as usize);
    let config = ObjectTransmissionInformation::new(data.len() as u64, symbol_size, 1, 2, 8);
    let encoder = Encoder::new(&data, config);
    assert_eq!(decode_all(config, encoder.get_encoded_packets(8)), Some(data));
}

#[test]
fn roundtrip_single_symbol() {
    let symbol_size = 128u16;
    let data = Lcg::new(10).bytes(symbol_size as usize);
    let config = simple_config(data.len() as u64, symbol_size);
    let encoder = Encoder::new(&data, config);
    assert_eq!(decode_all(config, encoder.get_encoded_packets(4)), Some(data));
}

#[test]
fn roundtrip_object_smaller_than_symbol() {
    // One partial symbol (data shorter than the symbol size): padded to a full symbol, recovered
    // back to the original short length.
    let symbol_size = 256u16;
    let data = Lcg::new(11).bytes(100);
    let config = simple_config(data.len() as u64, symbol_size);
    let encoder = Encoder::new(&data, config);
    let recovered = decode_all(config, encoder.get_encoded_packets(4)).expect("decode");
    assert_eq!(recovered, data);
}

// ----------------------------------------------------------------------------------------------
// Packet structure
// ----------------------------------------------------------------------------------------------

#[test]
fn source_packet_count_matches_symbol_count() {
    let symbol_size = 64u16;
    let k = 25usize;
    let data = Lcg::new(12).bytes(k * symbol_size as usize);
    let config = simple_config(data.len() as u64, symbol_size);
    let encoder = Encoder::new(&data, config);
    // No repair: exactly K source packets. With R repair: K + R.
    assert_eq!(encoder.get_encoded_packets(0).len(), k);
    assert_eq!(encoder.get_encoded_packets(7).len(), k + 7);
}

#[test]
fn repair_packet_ids_follow_extended_source_symbols() {
    let symbol_size = 64u16;
    let k = 18usize;
    let data = Lcg::new(13).bytes(k * symbol_size as usize);
    let config = simple_config(data.len() as u64, symbol_size);
    let encoder = Encoder::new(&data, config);
    let packets = encoder.get_encoded_packets(5);
    let kprime = extended_source_block_symbols(k as u32);
    let mut repair_ids: Vec<u32> = packets
        .iter()
        .map(|p| p.payload_id().encoding_symbol_id())
        .filter(|&esi| esi >= kprime)
        .collect();
    repair_ids.sort_unstable();
    // Repair symbols are numbered consecutively starting at K'.
    assert_eq!(repair_ids, (kprime..kprime + 5).collect::<Vec<u32>>());
}

#[test]
fn source_packets_have_block_local_ids() {
    let symbol_size = 64u16;
    let k = 14usize;
    let data = Lcg::new(14).bytes(k * symbol_size as usize);
    let config = simple_config(data.len() as u64, symbol_size);
    let encoder = Encoder::new(&data, config);
    let source = encoder.get_encoded_packets(0);
    let mut ids: Vec<u32> = source.iter().map(|p| p.payload_id().encoding_symbol_id()).collect();
    ids.sort_unstable();
    assert_eq!(ids, (0..k as u32).collect::<Vec<u32>>());
    assert!(source.iter().all(|p| p.payload_id().source_block_number() == 0));
}

// ----------------------------------------------------------------------------------------------
// Hard regimes — large K (sparse decode path), minimal overhead, and scale under loss. These
// stress the full intermediate-symbol solver well beyond the small-K cases above, where naive or
// incomplete RFC implementations tend to break. Still strictly behaviour-only.
// ----------------------------------------------------------------------------------------------

#[test]
fn roundtrip_large_block_sparse_path_no_loss() {
    // A single block with many symbols (well past the dense/sparse decode-path cutoff). Source-only.
    let symbol_size = 64u16;
    let k = 300usize;
    let data = Lcg::new(20).bytes(k * symbol_size as usize);
    let config = simple_config(data.len() as u64, symbol_size);
    let encoder = Encoder::new(&data, config);
    assert_eq!(decode_all(config, encoder.get_encoded_packets(0)), Some(data));
}

#[test]
fn roundtrip_large_block_with_erasures() {
    // Large single block, recover after losing a sizeable fraction of a mixed source+repair stream.
    let symbol_size = 64u16;
    let k = 300usize;
    let data = Lcg::new(21).bytes(k * symbol_size as usize);
    let config = simple_config(data.len() as u64, symbol_size);
    let encoder = Encoder::new(&data, config);
    let mut packets = encoder.get_encoded_packets(80); // 380 total
    let mut rng = Lcg::new(2121);
    for _ in 0..60 {
        let idx = rng.below(packets.len());
        packets.remove(idx);
    }
    assert_eq!(decode_all(config, packets), Some(data));
}

#[test]
fn roundtrip_repair_only_minimal_overhead() {
    // Drop every source symbol and recover from a repair-only stream with only a small overhead
    // above K. This is the tight end of the recovery guarantee and exercises the solver hardest.
    let symbol_size = 64u16;
    let k = 40usize;
    let data = Lcg::new(22).bytes(k * symbol_size as usize);
    let config = simple_config(data.len() as u64, symbol_size);
    let encoder = Encoder::new(&data, config);
    let all = encoder.get_encoded_packets(k as u32 + 2);
    let repair_only: Vec<EncodingPacket> = all
        .into_iter()
        .filter(|p| p.payload_id().encoding_symbol_id() >= k as u32)
        .take(k + 2) // K + 2 symbols only
        .collect();
    assert_eq!(decode_all(config, repair_only), Some(data));
}

#[test]
fn roundtrip_large_multi_block_sparse_with_loss() {
    // Two large source blocks (each past the sparse cutoff), recovered together after loss.
    let symbol_size = 64u16;
    let per_block = 300usize;
    let kt = 2 * per_block;
    let data = Lcg::new(23).bytes(kt * symbol_size as usize);
    let config = ObjectTransmissionInformation::new(data.len() as u64, symbol_size, 2, 1, 1);
    let encoder = Encoder::new(&data, config);
    let mut packets = encoder.get_encoded_packets(60); // 60 repair per block
    let mut rng = Lcg::new(2323);
    for _ in 0..70 {
        let idx = rng.below(packets.len());
        packets.remove(idx);
    }
    assert_eq!(decode_all(config, packets), Some(data));
}

#[test]
fn roundtrip_multi_block_sub_block_with_erasures() {
    // Multiple source blocks AND sub-block interleaving together, under packet loss.
    let symbol_size = 64u16;
    let kt = 64usize;
    let data = Lcg::new(24).bytes(kt * symbol_size as usize);
    let config = ObjectTransmissionInformation::new(data.len() as u64, symbol_size, 2, 4, 8);
    let encoder = Encoder::new(&data, config);
    let mut packets = encoder.get_encoded_packets(30);
    let mut rng = Lcg::new(2424);
    for _ in 0..20 {
        let idx = rng.below(packets.len());
        packets.remove(idx);
    }
    assert_eq!(decode_all(config, packets), Some(data));
}
