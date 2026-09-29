// Module: encode_lossless. Exercises 8-bit / 12-bit / 16-bit single-component
// lossless encoding and asserts on the JPEG-LS wire-format EOI marker plus the
// round-trip pixel-identity contract. SOF55 field-layout assertions live in
// test_wire_format.cpp (strict superset of the earlier presence check).
//
// Tests:
//   EncodeLossless.Gray8x32EncodeThenDecodeIsBitExact
//   EncodeLossless.Gray12BitRoundtrip
//   EncodeLossless.Gray16BitRoundtrip
//   EncodeLossless.StreamEndsWithEoi
//   EncodeLossless.BytesWrittenLessThanOrEqualEstimated
//
// Portability rule: enum values passed to C API functions (charls_jpegls_*)
// use the C-macro constants (CHARLS_INTERLEAVE_MODE_NONE etc.) so the tests
// compile regardless of whether the agent's C++ enum implicitly converts to
// the C enum (upstream-style distinct C/C++ enums require the C constant).

#include "charls_fixture.h"

#include <charls/charls.h>
#include <gtest/gtest.h>

#include <cstdint>
#include <vector>

using charls_test_helpers::encode_decode_roundtrip_c;
using charls_test_helpers::make_gray16_gradient;
using charls_test_helpers::make_gray8_gradient;


TEST(EncodeLossless, Gray8x32EncodeThenDecodeIsBitExact) {
    // 32 x 32 grayscale 8-bit gradient encoded lossless. After roundtrip the
    // decoded pixels must equal the original byte-for-byte.
    const uint32_t W = 32, H = 32;
    const auto src = make_gray8_gradient(W, H);
    const charls_frame_info fi{W, H, 8, 1};

    const auto r = encode_decode_roundtrip_c(src, fi, CHARLS_INTERLEAVE_MODE_NONE, 0);

    // Decoder must report the original frame_info.
    EXPECT_EQ(r.decoded_frame_info.width, W);
    EXPECT_EQ(r.decoded_frame_info.height, H);
    EXPECT_EQ(r.decoded_frame_info.bits_per_sample, 8);
    EXPECT_EQ(r.decoded_frame_info.component_count, 1);

    // Decoder must report lossless (NEAR = 0).
    EXPECT_EQ(r.decoded_near_lossless, 0);

    // Round-trip bit-exact for lossless.
    ASSERT_EQ(r.decoded.size(), src.size());
    for (size_t i = 0; i < src.size(); ++i) {
        ASSERT_EQ(r.decoded[i], src[i]) << "differ at byte " << i;
    }
}


TEST(EncodeLossless, Gray12BitRoundtrip) {
    // 12-bit grayscale requires 2 bytes per sample. Values are limited to
    // [0, 4095]. The encoded stream must record bits_per_sample = 12.
    const uint32_t W = 24, H = 24;
    const auto src = make_gray16_gradient(W, H, 12);
    const charls_frame_info fi{W, H, 12, 1};

    const auto r = encode_decode_roundtrip_c(src, fi, CHARLS_INTERLEAVE_MODE_NONE, 0);
    EXPECT_EQ(r.decoded_frame_info.bits_per_sample, 12);

    // Bit-exact round-trip.
    ASSERT_EQ(r.decoded.size(), src.size());
    for (size_t i = 0; i < src.size(); ++i) {
        ASSERT_EQ(r.decoded[i], src[i]) << "differ at byte " << i;
    }
}


TEST(EncodeLossless, Gray16BitRoundtrip) {
    // 16-bit grayscale, full dynamic range [0, 65535]. Two bytes per sample.
    const uint32_t W = 16, H = 16;
    const auto src = make_gray16_gradient(W, H, 16);
    const charls_frame_info fi{W, H, 16, 1};

    const auto r = encode_decode_roundtrip_c(src, fi, CHARLS_INTERLEAVE_MODE_NONE, 0);
    EXPECT_EQ(r.decoded_frame_info.bits_per_sample, 16);

    ASSERT_EQ(r.decoded.size(), src.size());
    for (size_t i = 0; i < src.size(); ++i) {
        ASSERT_EQ(r.decoded[i], src[i]) << "differ at byte " << i;
    }
}


TEST(EncodeLossless, StreamEndsWithEoi) {
    // The encoded byte stream must end with the EOI marker (FF D9). This is
    // the canonical JPEG stream terminator.
    const uint32_t W = 8, H = 8;
    const auto src = make_gray8_gradient(W, H);
    const charls_frame_info fi{W, H, 8, 1};

    const auto r = encode_decode_roundtrip_c(src, fi, CHARLS_INTERLEAVE_MODE_NONE, 0);
    ASSERT_GE(r.encoded.size(), 2u);
    EXPECT_EQ(r.encoded[r.encoded.size() - 2], 0xFF);
    EXPECT_EQ(r.encoded[r.encoded.size() - 1], 0xD9);  // EOI
}


TEST(EncodeLossless, BytesWrittenLessThanOrEqualEstimated) {
    // get_estimated_destination_size returns an upper bound. After encoding,
    // get_bytes_written must return a value <= that estimate. This validates
    // both the estimate correctness and the write-tracking bookkeeping.
    const uint32_t W = 16, H = 16;
    const auto src = make_gray8_gradient(W, H);

    charls_jpegls_encoder* enc = charls_jpegls_encoder_create();
    ASSERT_NE(enc, nullptr);

    charls_frame_info fi{W, H, 8, 1};
    ASSERT_EQ(charls_jpegls_encoder_set_frame_info(enc, &fi), CHARLS_JPEGLS_ERRC_SUCCESS);

    size_t estimated = 0;
    ASSERT_EQ(charls_jpegls_encoder_get_estimated_destination_size(enc, &estimated),
              CHARLS_JPEGLS_ERRC_SUCCESS);
    ASSERT_GT(estimated, 0u);

    std::vector<uint8_t> dst(estimated);
    ASSERT_EQ(charls_jpegls_encoder_set_destination_buffer(enc, dst.data(), dst.size()),
              CHARLS_JPEGLS_ERRC_SUCCESS);
    ASSERT_EQ(charls_jpegls_encoder_encode_from_buffer(enc, src.data(), src.size(), 0),
              CHARLS_JPEGLS_ERRC_SUCCESS);

    size_t written = 0;
    ASSERT_EQ(charls_jpegls_encoder_get_bytes_written(enc, &written),
              CHARLS_JPEGLS_ERRC_SUCCESS);

    EXPECT_GT(written, 0u);
    EXPECT_LE(written, estimated);

    charls_jpegls_encoder_destroy(enc);
}
