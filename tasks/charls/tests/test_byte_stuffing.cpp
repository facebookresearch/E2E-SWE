// Module: byte_stuffing. Exercises the ISO/IEC 14495-1 § A.1 byte-stuffing rule
// in the entropy-coded scan region.
//
// The JPEG-LS byte-stuffing invariant is:
//   Within the entropy-coded scan region, every 0xFF byte MUST be followed by
//   a byte whose most-significant bit is 0 (i.e., the follower byte is in
//   [0x00, 0x7F]).
//
// This is the CharLS-reference-decoder rule (see decoder_strategy.h): a 0xFF
// byte in the scan region is treated as a marker start iff the following byte
// has bit 7 set. Conforming JPEG-LS encoders either (a) insert an inline "0"
// bit after every 0xFF byte written from the bit buffer -- the JPEG-LS bit-
// stuffing style used by upstream CharLS, which naturally leaves any value in
// [0x00, 0x7F] as the follower -- or (b) insert a literal 0x00 stuffing byte
// after every 0xFF -- the JPEG (T.81) byte-stuffing style, which trivially
// satisfies the same invariant (0x00 has bit 7 = 0). Both stuffing styles
// satisfy the bit-7-clear invariant, so a test asserting bit-7-clear is fair
// to either implementation choice. Implementations that skip stuffing entirely
// (emit 0xFF followed by an arbitrary byte, e.g. a data byte with bit 7 = 1)
// break both invariants and produce streams that any conforming decoder mis-
// parses as containing a marker in the middle of scan data.
//
// Tests:
//   ByteStuffing.EveryFFInScanIsFollowedByBit7Clear -- byte-level assertion
//     that the scan region between SOS-payload-start and EOI-marker-start
//     contains at least one 0xFF byte (sanity precondition on the pathological
//     input) AND that every such 0xFF is followed by a byte with bit 7 = 0
//     (except when the 0xFF is the LAST byte of the scan region, in which case
//     the next byte in the stream is the EOI marker's own 0xFF and JPEG "FF FF
//     = fill byte" semantics apply).
//   ByteStuffing.RoundtripPreservesFFPayload -- self-roundtrip on the same
//     high-entropy input. Encoder and decoder must agree on stuffing/unstuffing
//     for pixels to survive the roundtrip when the scan region contains 0xFF
//     bytes.
//
// Fairness rail: only the invariant explicitly required by the ISO spec is
// asserted. The assertion (bit 7 clear) is the weakest invariant that both
// stuffing styles satisfy and any conformant decoder relies on. No assertion
// depends on how many 0xFF bytes appear beyond "at least one".
//
// Buffer-sizing note: high-entropy inputs can expand under Golomb-Rice coding
// (each residual is ~12 bits per pixel worst case). Rather than trust the
// library's `estimated_destination_size` (which is a conservative upper bound
// but not always calibrated for pathological entropy), we allocate a buffer
// sized as `4 * width * height + 4096` -- guaranteed to hold even worst-case
// expansion plus all header bytes and byte-stuffing overhead. We also assert
// the encoder's return code and require bytes_written >= 27 (minimum valid
// stream: 2 SOI + 13 SOF55 + 10 SOS + 2 EOI = 27), so a silent under-write is
// caught immediately with a clear message.
//
// Portability rule: C API args + return-code comparisons use the CHARLS_*
// C-macro constants from charls_fixture.h.

#include "charls_fixture.h"

#include <charls/charls.h>
#include <gtest/gtest.h>

#include <cstdint>
#include <optional>
#include <vector>

using charls_test_helpers::read_uint16_be;


namespace {

// Build a high-entropy pseudo-random 8-bit grayscale image. The xor-shift
// sequence has well-mixed low bits so residuals after LOCO-I prediction span
// the full Golomb-Rice output range -- at 128x128 this reliably produces
// multiple 0xFF payload bytes in the encoded scan.
std::vector<uint8_t> make_high_entropy_gray8(const uint32_t width, const uint32_t height,
                                             const uint32_t seed = 42)
{
    std::vector<uint8_t> pixels(static_cast<size_t>(width) * height);
    uint32_t s = seed;
    for (size_t i = 0; i < pixels.size(); ++i)
    {
        s ^= s << 13;
        s ^= s >> 17;
        s ^= s << 5;
        pixels[i] = static_cast<uint8_t>(s & 0xFF);
    }
    return pixels;
}


// Linear scan for a 2-byte marker (0xFF <marker>) starting at `start`. Returns
// the offset of the first byte (the 0xFF), or std::nullopt if not found.
// Byte-stuffing means a 0xFF followed by 0x00 is never a marker.
std::optional<size_t> find_marker(const std::vector<uint8_t>& buf,
                                  const uint8_t marker,
                                  const size_t start = 0)
{
    for (size_t i = start; i + 1 < buf.size(); ++i)
    {
        if (buf[i] == 0xFF && buf[i + 1] == marker)
        {
            return i;
        }
    }
    return std::nullopt;
}


// Local encoder helper for byte-stuffing tests. Uses an oversized destination
// buffer (4x uncompressed + 4 KB header slack) so `estimated_destination_size`
// under-calibration cannot silently truncate the output. Every C-API return
// code is checked; on failure the returned vector is empty and out_rc holds
// the failing code (caller ASSERTs on both).
std::vector<uint8_t> encode_gray8_lossless_oversized(const std::vector<uint8_t>& src,
                                                     const uint32_t width, const uint32_t height,
                                                     charls_jpegls_errc* out_rc)
{
    *out_rc = CHARLS_JPEGLS_ERRC_SUCCESS;
    charls_jpegls_encoder* enc = charls_jpegls_encoder_create();
    if (!enc)
    {
        *out_rc = CHARLS_JPEGLS_ERRC_NOT_ENOUGH_MEMORY;
        return {};
    }

    charls_frame_info fi{width, height, 8, 1};
    *out_rc = charls_jpegls_encoder_set_frame_info(enc, &fi);
    if (*out_rc != CHARLS_JPEGLS_ERRC_SUCCESS)
    {
        charls_jpegls_encoder_destroy(enc);
        return {};
    }
    *out_rc = charls_jpegls_encoder_set_interleave_mode(enc, CHARLS_INTERLEAVE_MODE_NONE);
    if (*out_rc != CHARLS_JPEGLS_ERRC_SUCCESS)
    {
        charls_jpegls_encoder_destroy(enc);
        return {};
    }
    *out_rc = charls_jpegls_encoder_set_near_lossless(enc, 0);
    if (*out_rc != CHARLS_JPEGLS_ERRC_SUCCESS)
    {
        charls_jpegls_encoder_destroy(enc);
        return {};
    }

    // Oversize aggressively: 4 x uncompressed + 4 KB header slack. High-entropy
    // input expands (~12 bits/pixel Golomb-Rice worst case = 1.5x); byte-
    // stuffing doubles some bytes; 4x is comfortably above any conformant
    // encoder's actual output. Do NOT trust get_estimated_destination_size
    // as the ONLY sizing signal -- take the max.
    size_t est = 0;
    (void)charls_jpegls_encoder_get_estimated_destination_size(enc, &est);
    const size_t hard_min = 4u * static_cast<size_t>(width) * height + 4096u;
    const size_t buf_size = est > hard_min ? est : hard_min;
    std::vector<uint8_t> dst(buf_size);

    *out_rc = charls_jpegls_encoder_set_destination_buffer(enc, dst.data(), dst.size());
    if (*out_rc != CHARLS_JPEGLS_ERRC_SUCCESS)
    {
        charls_jpegls_encoder_destroy(enc);
        return {};
    }
    *out_rc = charls_jpegls_encoder_encode_from_buffer(enc, src.data(), src.size(), 0);
    if (*out_rc != CHARLS_JPEGLS_ERRC_SUCCESS)
    {
        charls_jpegls_encoder_destroy(enc);
        return {};
    }
    size_t written = 0;
    *out_rc = charls_jpegls_encoder_get_bytes_written(enc, &written);
    charls_jpegls_encoder_destroy(enc);
    if (*out_rc != CHARLS_JPEGLS_ERRC_SUCCESS)
    {
        return {};
    }
    dst.resize(written);
    return dst;
}


std::vector<uint8_t> decode_gray8_lossless(const std::vector<uint8_t>& encoded,
                                           charls_jpegls_errc* out_rc)
{
    *out_rc = CHARLS_JPEGLS_ERRC_SUCCESS;
    charls_jpegls_decoder* dec = charls_jpegls_decoder_create();
    if (!dec)
    {
        *out_rc = CHARLS_JPEGLS_ERRC_NOT_ENOUGH_MEMORY;
        return {};
    }
    *out_rc = charls_jpegls_decoder_set_source_buffer(dec, encoded.data(), encoded.size());
    if (*out_rc != CHARLS_JPEGLS_ERRC_SUCCESS)
    {
        charls_jpegls_decoder_destroy(dec);
        return {};
    }
    *out_rc = charls_jpegls_decoder_read_header(dec);
    if (*out_rc != CHARLS_JPEGLS_ERRC_SUCCESS)
    {
        charls_jpegls_decoder_destroy(dec);
        return {};
    }
    size_t dest_size = 0;
    *out_rc = charls_jpegls_decoder_get_destination_size(dec, 0, &dest_size);
    if (*out_rc != CHARLS_JPEGLS_ERRC_SUCCESS)
    {
        charls_jpegls_decoder_destroy(dec);
        return {};
    }
    std::vector<uint8_t> decoded(dest_size);
    *out_rc = charls_jpegls_decoder_decode_to_buffer(dec, decoded.data(), decoded.size(), 0);
    charls_jpegls_decoder_destroy(dec);
    if (*out_rc != CHARLS_JPEGLS_ERRC_SUCCESS)
    {
        return {};
    }
    return decoded;
}

}  // namespace


TEST(ByteStuffing, EveryFFInScanIsFollowedByBit7Clear) {
    // Encode a high-entropy image so the scan region reliably contains payload
    // 0xFF bytes. Verify (a) at least one payload 0xFF appears (sanity guard on
    // the input, catches an implementation that emits nothing) and (b) every
    // such 0xFF is followed by a byte with bit 7 = 0 (in [0x00, 0x7F]) -- the
    // ISO/IEC 14495-1 § A.1 invariant.
    const uint32_t W = 128, H = 128;
    const auto src = make_high_entropy_gray8(W, H);

    charls_jpegls_errc enc_rc = CHARLS_JPEGLS_ERRC_SUCCESS;
    const auto encoded = encode_gray8_lossless_oversized(src, W, H, &enc_rc);
    ASSERT_EQ(enc_rc, CHARLS_JPEGLS_ERRC_SUCCESS)
        << "encoder returned non-success on high-entropy 128x128 gray8 lossless input";
    // Minimum valid JPEG-LS stream: 2 (SOI) + 13 (SOF55 for Nf=1) + 10 (SOS for Ns=1) + 2 (EOI) = 27.
    ASSERT_GE(encoded.size(), 27u)
        << "encoded stream too small to be a valid JPEG-LS bitstream (bytes_written = "
        << encoded.size() << "; minimum 27)";

    // Locate SOS marker (FF DA). Scan data begins immediately after the SOS
    // segment header. For Ns=1 (single-component NONE-interleaved), the SOS
    // segment has Ls=8, so the payload starts at SOS_pos + 10 (2 marker + 8 Ls
    // value including its own 2 bytes).
    const auto sos_pos = find_marker(encoded, 0xDA, 2);
    ASSERT_TRUE(sos_pos.has_value()) << "SOS (FF DA) marker not found";
    const uint8_t ns = encoded[*sos_pos + 4];
    ASSERT_EQ(ns, 1u) << "SOS Ns should be 1 for single-component NONE";
    const size_t scan_start = *sos_pos + 10;  // = 2 (marker) + Ls (= 6 + 2*Ns = 8)
    ASSERT_LT(scan_start, encoded.size());

    // Locate EOI marker (FF D9). Because byte-stuffing guarantees any 0xFF
    // followed by 0x00 in the scan region is a payload byte, find_marker with
    // target 0xD9 skips those correctly. The EOI marker sits at the very end
    // of the stream (after the last scan byte).
    const auto eoi_pos = find_marker(encoded, 0xD9, scan_start);
    ASSERT_TRUE(eoi_pos.has_value()) << "EOI (FF D9) marker not found";
    const size_t scan_end = *eoi_pos;
    ASSERT_GT(scan_end, scan_start) << "scan region is empty";

    // Walk the scan region [scan_start, scan_end). Every 0xFF must be followed
    // by a byte with bit 7 clear. Exception: the LAST byte of the scan region
    // may itself be 0xFF (its "next byte" is the EOI marker's own 0xFF; JPEG
    // "FF FF = fill byte" semantics handle this case). Count occurrences of
    // any 0xFF; require at least 1.
    size_t ff_count = 0;
    for (size_t i = scan_start; i < scan_end; ++i)
    {
        if (encoded[i] != 0xFF)
        {
            continue;
        }
        ++ff_count;
        if (i + 1 == scan_end)
        {
            // FF at scan boundary: next stream byte is the EOI marker's FF.
            continue;
        }
        EXPECT_EQ(static_cast<unsigned>(encoded[i + 1] & 0x80u), 0u)
            << "0xFF in scan region followed by byte with bit 7 set at offset " << i
            << " (next byte = 0x" << std::hex << +encoded[i + 1] << std::dec << "); "
               "JPEG-LS requires the byte after any 0xFF in the entropy-coded scan "
               "region to have bit 7 clear (JPEG-LS bit-stuff or JPEG byte-stuff)";
    }

    // Precondition: the 128x128 xor-shift input at typical JPEG-LS compression
    // ratios produces many payload 0xFF bytes. Zero implies the encoder emitted
    // an empty or trivially-small scan region -- indicative of an encoder bug
    // rather than a fair "no FFs happened" scenario.
    EXPECT_GT(ff_count, 0u)
        << "no 0xFF payload bytes in scan region; either the encoder produced no "
           "output OR the pathological input coincidentally avoided 0xFF (extremely "
           "unlikely at 128x128 xor-shift entropy)";
}


TEST(ByteStuffing, RoundtripPreservesFFPayload) {
    // Self-roundtrip on the same high-entropy input. The encoder emits payload
    // 0xFF bytes (guaranteed by the input entropy at 128x128); those bytes are
    // stuffed with 0x00 on encode and must be unstuffed on decode. If either
    // direction is broken independently, the decoded pixel stream diverges
    // from the original -- verified by bit-exact comparison.
    const uint32_t W = 128, H = 128;
    const auto src = make_high_entropy_gray8(W, H);

    charls_jpegls_errc enc_rc = CHARLS_JPEGLS_ERRC_SUCCESS;
    const auto encoded = encode_gray8_lossless_oversized(src, W, H, &enc_rc);
    ASSERT_EQ(enc_rc, CHARLS_JPEGLS_ERRC_SUCCESS)
        << "encoder returned non-success on high-entropy 128x128 gray8 lossless input";
    ASSERT_GE(encoded.size(), 27u);

    charls_jpegls_errc dec_rc = CHARLS_JPEGLS_ERRC_SUCCESS;
    const auto decoded = decode_gray8_lossless(encoded, &dec_rc);
    ASSERT_EQ(dec_rc, CHARLS_JPEGLS_ERRC_SUCCESS)
        << "decoder returned non-success on self-encoded high-entropy stream";
    ASSERT_EQ(decoded.size(), src.size()) << "decoded buffer size mismatch";
    for (size_t i = 0; i < src.size(); ++i)
    {
        ASSERT_EQ(decoded[i], src[i])
            << "high-entropy pixel mismatch at byte " << i
            << " (decoded=0x" << std::hex << +decoded[i]
            << " src=0x" << +src[i] << ")";
    }
}
