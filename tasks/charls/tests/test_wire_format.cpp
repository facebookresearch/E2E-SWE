// Module: wire_format. Exercises the ISO/IEC 14495-1 § D.2 wire-format
// contracts for the SOF55 (JPEG-LS start-of-frame) and SOS (start-of-scan)
// marker segments. Every conforming JPEG-LS encoder MUST emit these markers
// with these field layouts and values regardless of internal implementation
// choices (predictor, Golomb-Rice mapping, run-length state, etc.). This
// module deliberately does NOT assert on entropy-coded scan bytes -- those
// depend on legitimate implementation choices and are exercised by round-trip
// tests elsewhere.
//
// Tests:
//   WireFormat.SOF55SegmentHasCorrectFieldLayout
//   WireFormat.SOSSegmentHasCorrectFieldLayout
//   WireFormat.SOSNEARByteMatchesSetNearLossless
//   WireFormat.SOSILVByteMatchesSetInterleaveMode
//
// Portability rule: enum values passed to C API functions (charls_jpegls_*)
// use the CHARLS_* C-macro constants (works for both alias-style and distinct-
// C-enum agent impls). See charls_fixture.h for the enum-bridge macro layer.
//
// Fairness note: only ISO-mandated field values are asserted (Lf, Ls, Nf, Ns,
// P, Hi_Vi=0x11, Tqi=0, Tdi_Tai=0, Al_Ah=0, NEAR, ILV, Y, X). The component
// identifier byte (Ci / Csi) is deliberately NOT asserted -- the JPEG spec
// permits any 8-bit value there, so pinning a specific number would penalize
// spec-compliant encoders that choose a different (but internally consistent)
// numbering.

#include "charls_fixture.h"

#include <charls/charls.h>
#include <gtest/gtest.h>

#include <algorithm>
#include <cstdint>
#include <optional>
#include <vector>

using charls_test_helpers::encode_decode_roundtrip_c;
using charls_test_helpers::make_gray8_gradient;
using charls_test_helpers::make_rgb8_gradient;
using charls_test_helpers::read_uint16_be;


namespace {

// Linear scan for a 2-byte marker (0xFF <marker>) starting at `start`. Returns
// the offset of the first byte (the 0xFF), or std::nullopt if not found.
//
// JPEG-LS scan data is byte-stuffed: any 0xFF in the entropy-coded payload is
// immediately followed by a stuffed 0x00. So real segment markers (which are
// 0xFF followed by a non-zero byte) cannot be confused with intra-scan 0xFF
// bytes even when scanning past the scan-data region. A linear search is safe.
std::optional<size_t> find_marker(const std::vector<uint8_t>& buf,
                                  const uint8_t marker,
                                  const size_t start = 0)
{
    for (size_t i = start; i + 1 < buf.size(); ++i) {
        if (buf[i] == 0xFF && buf[i + 1] == marker) {
            return i;
        }
    }
    return std::nullopt;
}

}  // namespace


TEST(WireFormat, SOF55SegmentHasCorrectFieldLayout) {
    // Per ISO/IEC 14495-1 § D.2.2, the SOF55 marker segment for a single-
    // component 8-bit image has this exact layout (offsets relative to the
    // 0xFF byte of the marker):
    //   [0..1] FF F7                     -- SOF55 marker
    //   [2..3] Lf (uint16 BE) = 8 + 3*Nf -- for Nf=1, Lf = 11 (0x000B)
    //   [4]    P                         -- sample precision (bits per sample)
    //   [5..6] Y  (uint16 BE)            -- number of lines (height)
    //   [7..8] X  (uint16 BE)            -- samples per line (width)
    //   [9]    Nf                        -- number of components
    //   for i in [0, Nf):
    //     [10 + 3*i]     Ci              -- component identifier (spec-open value)
    //     [10 + 3*i + 1] Hi_Vi = 0x11    -- 1x1 sampling (JPEG-LS is always 1x1)
    //     [10 + 3*i + 2] Tqi = 0         -- quantization table (always 0 in JPEG-LS)
    // Use asymmetric W (64) x H (32) so any BE/LE mistake or Y/X field swap surfaces.
    const uint32_t W = 64, H = 32;
    const auto src = make_gray8_gradient(W, H);
    const charls_frame_info fi{W, H, 8, 1};

    const auto r = encode_decode_roundtrip_c(src, fi, CHARLS_INTERLEAVE_MODE_NONE, 0);
    ASSERT_GT(r.encoded.size(), 20u);

    const auto sof_pos = find_marker(r.encoded, 0xF7, 2);
    ASSERT_TRUE(sof_pos.has_value()) << "SOF55 (FF F7) marker not found";
    const size_t p = *sof_pos;
    ASSERT_LE(p + 13u, r.encoded.size()) << "SOF55 segment truncated";

    // Marker bytes.
    EXPECT_EQ(r.encoded[p], 0xFF);
    EXPECT_EQ(r.encoded[p + 1], 0xF7);
    // Lf = 8 + 3*1 = 11 (0x000B), big-endian.
    EXPECT_EQ(read_uint16_be(r.encoded, p + 2), 11u) << "SOF55 Lf incorrect";
    // P = 8 (matches frame_info.bits_per_sample).
    EXPECT_EQ(r.encoded[p + 4], 8u) << "SOF55 P (bits per sample) incorrect";
    // Y and X are big-endian uint16 (asymmetric dims catch BE/LE swaps).
    EXPECT_EQ(read_uint16_be(r.encoded, p + 5), H) << "SOF55 Y (height) not BE " << H;
    EXPECT_EQ(read_uint16_be(r.encoded, p + 7), W) << "SOF55 X (width) not BE " << W;
    // Nf = 1.
    EXPECT_EQ(r.encoded[p + 9], 1u) << "SOF55 Nf (component count) incorrect";
    // Hi_Vi = 0x11 (1x1 sampling factors). JPEG-LS is ALWAYS 1x1 -- ISO-mandated.
    EXPECT_EQ(r.encoded[p + 11], 0x11u) << "SOF55 Hi_Vi should be 0x11 (1x1)";
    // Tqi = 0. JPEG-LS uses no quantization tables -- ISO-mandated.
    EXPECT_EQ(r.encoded[p + 12], 0u) << "SOF55 Tqi should be 0 in JPEG-LS";
}


TEST(WireFormat, SOSSegmentHasCorrectFieldLayout) {
    // Per ISO/IEC 14495-1 § D.2.3, the SOS marker segment for a single-
    // component lossless scan has this exact layout (offsets relative to the
    // 0xFF byte of the marker):
    //   [0..1] FF DA                     -- SOS marker
    //   [2..3] Ls (uint16 BE) = 6 + 2*Ns -- for Ns=1, Ls = 8 (0x0008)
    //   [4]    Ns                        -- number of components in scan
    //   for j in [0, Ns):
    //     [5 + 2*j]     Csj              -- component selector (spec-open value)
    //     [5 + 2*j + 1] Tdj_Taj = 0      -- table selectors (always 0 in JPEG-LS)
    //   [5 + 2*Ns]     NEAR              -- near-lossless parameter (0 = lossless)
    //   [5 + 2*Ns + 1] ILV               -- interleave mode (0=NONE, 1=LINE, 2=SAMPLE)
    //   [5 + 2*Ns + 2] Al_Ah = 0         -- successive approximation (unused in JPEG-LS)
    const uint32_t W = 16, H = 16;
    const auto src = make_gray8_gradient(W, H);
    const charls_frame_info fi{W, H, 8, 1};

    const auto r = encode_decode_roundtrip_c(src, fi, CHARLS_INTERLEAVE_MODE_NONE, 0);
    ASSERT_GT(r.encoded.size(), 20u);

    const auto sos_pos = find_marker(r.encoded, 0xDA, 2);
    ASSERT_TRUE(sos_pos.has_value()) << "SOS (FF DA) marker not found";
    const size_t p = *sos_pos;
    ASSERT_LE(p + 9u, r.encoded.size()) << "SOS segment truncated";

    // Marker bytes.
    EXPECT_EQ(r.encoded[p], 0xFF);
    EXPECT_EQ(r.encoded[p + 1], 0xDA);
    // Ls = 6 + 2*1 = 8 (0x0008), big-endian.
    EXPECT_EQ(read_uint16_be(r.encoded, p + 2), 8u) << "SOS Ls incorrect";
    // Ns = 1.
    EXPECT_EQ(r.encoded[p + 4], 1u) << "SOS Ns (components in scan) incorrect";
    // Tdj_Taj = 0. Always 0 in JPEG-LS -- ISO-mandated.
    EXPECT_EQ(r.encoded[p + 6], 0x00u) << "SOS Tdi_Tai should be 0 in JPEG-LS";
    // NEAR = 0 (this test uses lossless).
    EXPECT_EQ(r.encoded[p + 7], 0u) << "SOS NEAR should be 0 for lossless";
    // ILV = 0 (this test uses NONE / planar for a single-component image).
    EXPECT_EQ(r.encoded[p + 8], 0u) << "SOS ILV should be 0 (NONE) for interleave_mode::none";
    // Al_Ah = 0. Always 0 in JPEG-LS -- ISO-mandated.
    EXPECT_EQ(r.encoded[p + 9], 0x00u) << "SOS Al_Ah should be 0 in JPEG-LS";
}


TEST(WireFormat, SOSNEARByteMatchesSetNearLossless) {
    // The SOS NEAR byte (offset 5 + 2*Ns from the SOS marker start) MUST equal
    // the value passed to charls_jpegls_encoder_set_near_lossless. Verify at a
    // non-baseline NEAR = 3 to distinguish from the lossless-default test.
    const int32_t NEAR = 3;
    const uint32_t W = 16, H = 16;
    const auto src = make_gray8_gradient(W, H);
    const charls_frame_info fi{W, H, 8, 1};

    const auto r = encode_decode_roundtrip_c(src, fi, CHARLS_INTERLEAVE_MODE_NONE, NEAR);
    ASSERT_GT(r.encoded.size(), 20u);

    const auto sos_pos = find_marker(r.encoded, 0xDA, 2);
    ASSERT_TRUE(sos_pos.has_value()) << "SOS (FF DA) marker not found";
    const size_t p = *sos_pos;
    ASSERT_LE(p + 9u, r.encoded.size()) << "SOS segment truncated";

    const uint8_t ns = r.encoded[p + 4];
    ASSERT_EQ(ns, 1u) << "SOS Ns should be 1 for single-component NONE-interleaved";
    // NEAR byte is at offset 5 + 2*Ns from the marker start.
    const size_t near_off = p + 5u + 2u * ns;
    EXPECT_EQ(r.encoded[near_off], static_cast<uint8_t>(NEAR))
        << "SOS NEAR byte should equal set_near_lossless value " << NEAR;
}


TEST(WireFormat, SOSILVByteMatchesSetInterleaveMode) {
    // The SOS ILV byte (offset 5 + 2*Ns + 1 from the SOS marker start) MUST
    // equal the integer value of the interleave_mode passed to
    // charls_jpegls_encoder_set_interleave_mode (0=NONE, 1=LINE, 2=SAMPLE).
    // Verify with SAMPLE (2) on a 3-component RGB image. This also exercises
    // the multi-component SOS layout (Ns=3, Ls=12) as a side effect.
    const uint32_t W = 16, H = 16;
    const auto src = make_rgb8_gradient(W, H);
    const charls_frame_info fi{W, H, 8, 3};

    const auto r = encode_decode_roundtrip_c(src, fi, CHARLS_INTERLEAVE_MODE_SAMPLE, 0);
    ASSERT_GT(r.encoded.size(), 20u);

    const auto sos_pos = find_marker(r.encoded, 0xDA, 2);
    ASSERT_TRUE(sos_pos.has_value()) << "SOS (FF DA) marker not found";
    const size_t p = *sos_pos;
    ASSERT_LE(p + 13u, r.encoded.size()) << "3-component SOS segment truncated";

    // For SAMPLE / LINE interleave modes on a 3-component image, one SOS with
    // Ns=3 is emitted (single scan covering all components).
    const uint8_t ns = r.encoded[p + 4];
    ASSERT_EQ(ns, 3u) << "SOS Ns should be 3 for SAMPLE-interleaved 3-component";
    // Ls = 6 + 2*3 = 12.
    EXPECT_EQ(read_uint16_be(r.encoded, p + 2), 12u) << "SOS Ls should be 12 for Ns=3";
    // ILV byte is at offset 5 + 2*Ns + 1 from the marker start.
    const size_t ilv_off = p + 5u + 2u * ns + 1u;
    EXPECT_EQ(r.encoded[ilv_off], 2u)
        << "SOS ILV byte should be 2 (SAMPLE) for interleave_mode::sample";
}
