// Module: preset_params_lse. Exercises the JPEG-LS extension marker (LSE,
// 0xFF 0xF8) segment carrying custom preset coding parameters, per ISO/IEC
// 14495-1 § D.3 and the task spec § 4.4:
//
//   FF F8 <Ls:u16 BE = 13> <type:u8 = 1>
//     <MAXVAL:u16 BE> <T1:u16 BE> <T2:u16 BE> <T3:u16 BE> <RESET:u16 BE>
//
// Only the "type = 1 (preset coding parameters)" extension is exercised here;
// upstream CharLS emits this segment iff the caller explicitly configures
// non-default values via charls_jpegls_encoder_set_preset_coding_parameters.
//
// Tests:
//   PresetParamsLSE.EncoderEmitsLSESegmentForCustomThresholds -- byte-level
//     assertion on the wire format of the LSE segment (marker, Ls, type byte,
//     and the 5 big-endian 16-bit fields).
//   PresetParamsLSE.CustomThresholdsFullRoundtripPixelsMatch -- full pixel
//     roundtrip (encode + decode + compare) with custom thresholds set. A
//     decoder that ignores LSE and uses default thresholds classifies gradient
//     contexts differently, drifting the adaptive Golomb-Rice state and
//     producing wrong pixels -- caught by bit-exact pixel comparison.
//
// The existing ExtraSegments.CustomPresetCodingParametersRoundtrip covers the
// read-header path (get_preset_coding_parameters returns matching values); it
// does NOT run decode_to_buffer, so it does not catch a decoder that reads LSE
// values into the getter but decodes pixels with defaults. This module fills
// that gap and also asserts the wire-format layout of the LSE segment itself.
//
// Fairness rail: threshold values chosen (T1=5, T2=10, T3=30, RESET=40,
// MAXVAL=255) satisfy the ISO/IEC 14495-1 C.2.4.1.1 constraint
// 1 <= T1 <= T2 <= T3 <= MAXVAL and 3 <= RESET <= 255. They are also visibly
// non-default (defaults for 8-bit are T1=3, T2=7, T3=21, RESET=64) so a
// decoder that silently uses defaults produces detectable pixel drift.
//
// Portability rule: C API args + return-code comparisons use the CHARLS_*
// C-macro constants from charls_fixture.h.

#include "charls_fixture.h"

#include <charls/charls.h>
#include <gtest/gtest.h>

#include <cstdint>
#include <optional>
#include <vector>

using charls_test_helpers::make_gray8_gradient;
using charls_test_helpers::read_uint16_be;


namespace {

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


// Encode a gray-8 image with the given non-default preset coding parameters
// and return the raw encoded byte stream. Assertions on ordering violations
// bail with an error status. Caller frees the encoded buffer.
std::vector<uint8_t> encode_with_preset_params(const std::vector<uint8_t>& src,
                                               const uint32_t width, const uint32_t height,
                                               const charls_jpegls_pc_parameters& params,
                                               charls_jpegls_errc* out_rc)
{
    *out_rc = CHARLS_JPEGLS_ERRC_SUCCESS;
    charls_jpegls_encoder* enc = charls_jpegls_encoder_create();
    charls_frame_info fi{width, height, 8, 1};
    *out_rc = charls_jpegls_encoder_set_frame_info(enc, &fi);
    if (*out_rc != CHARLS_JPEGLS_ERRC_SUCCESS)
    {
        charls_jpegls_encoder_destroy(enc);
        return {};
    }
    *out_rc = charls_jpegls_encoder_set_preset_coding_parameters(enc, &params);
    if (*out_rc != CHARLS_JPEGLS_ERRC_SUCCESS)
    {
        charls_jpegls_encoder_destroy(enc);
        return {};
    }
    size_t est = 0;
    charls_jpegls_encoder_get_estimated_destination_size(enc, &est);
    std::vector<uint8_t> dst(est);
    charls_jpegls_encoder_set_destination_buffer(enc, dst.data(), dst.size());
    *out_rc = charls_jpegls_encoder_encode_from_buffer(enc, src.data(), src.size(), 0);
    if (*out_rc != CHARLS_JPEGLS_ERRC_SUCCESS)
    {
        charls_jpegls_encoder_destroy(enc);
        return {};
    }
    size_t written = 0;
    charls_jpegls_encoder_get_bytes_written(enc, &written);
    dst.resize(written);
    charls_jpegls_encoder_destroy(enc);
    return dst;
}

}  // namespace


TEST(PresetParamsLSE, EncoderEmitsLSESegmentForCustomThresholds) {
    // Set custom preset coding parameters that are non-default but valid.
    // Encoder MUST emit an LSE segment (FF F8) with:
    //   Ls    = 13 (uint16 BE)  -- 1 type byte + 5 * 2-byte fields = 11, plus 2 bytes for Ls itself.
    //   type  = 1  (u8)         -- preset coding parameters extension
    //   MAXVAL, T1, T2, T3, RESET as big-endian uint16, in that order.
    const uint32_t W = 32, H = 32;
    const auto src = make_gray8_gradient(W, H);

    charls_jpegls_pc_parameters custom{};
    custom.maximum_sample_value = 255;
    custom.threshold1           = 5;
    custom.threshold2           = 10;
    custom.threshold3           = 30;
    custom.reset_value          = 40;

    charls_jpegls_errc enc_rc = CHARLS_JPEGLS_ERRC_SUCCESS;
    const auto encoded = encode_with_preset_params(src, W, H, custom, &enc_rc);
    ASSERT_EQ(enc_rc, CHARLS_JPEGLS_ERRC_SUCCESS)
        << "encoder rejected valid custom preset coding parameters";
    ASSERT_GT(encoded.size(), 20u);

    const auto lse_pos = find_marker(encoded, 0xF8, 2);
    ASSERT_TRUE(lse_pos.has_value())
        << "LSE (FF F8) segment not found -- encoder skipped writing custom preset coding "
           "parameters even though the caller explicitly configured them";
    const size_t p = *lse_pos;
    ASSERT_LE(p + 15u, encoded.size()) << "LSE segment truncated";

    // Marker bytes.
    EXPECT_EQ(encoded[p], 0xFFu);
    EXPECT_EQ(encoded[p + 1], 0xF8u);
    // Ls = 13, big-endian.
    EXPECT_EQ(read_uint16_be(encoded, p + 2), 13u)
        << "LSE Ls should be 13 (1 type byte + 5 x 2-byte fields + 2 bytes for Ls itself)";
    // type = 1 (preset coding parameters extension).
    EXPECT_EQ(encoded[p + 4], 1u)
        << "LSE type byte should be 1 (preset coding parameters extension type)";
    // MAXVAL, T1, T2, T3, RESET in order, each big-endian uint16.
    EXPECT_EQ(read_uint16_be(encoded, p + 5), 255u) << "LSE MAXVAL field mismatch";
    EXPECT_EQ(read_uint16_be(encoded, p + 7), 5u)   << "LSE T1 field mismatch";
    EXPECT_EQ(read_uint16_be(encoded, p + 9), 10u)  << "LSE T2 field mismatch";
    EXPECT_EQ(read_uint16_be(encoded, p + 11), 30u) << "LSE T3 field mismatch";
    EXPECT_EQ(read_uint16_be(encoded, p + 13), 40u) << "LSE RESET field mismatch";
}


TEST(PresetParamsLSE, CustomThresholdsFullRoundtripPixelsMatch) {
    // Encode with custom thresholds, then decode with the same library. Custom
    // thresholds affect context classification in LOCO-I; a decoder that reads
    // LSE only into its metadata getter but decodes with default thresholds
    // will misclassify contexts, drift the adaptive Golomb-Rice state, and
    // produce wrong pixels. Bit-exact roundtrip confirms the decoder actually
    // USES the custom values throughout the decode.
    const uint32_t W = 32, H = 32;
    const auto src = make_gray8_gradient(W, H);

    charls_jpegls_pc_parameters custom{};
    custom.maximum_sample_value = 255;
    custom.threshold1           = 5;
    custom.threshold2           = 10;
    custom.threshold3           = 30;
    custom.reset_value          = 40;

    charls_jpegls_errc enc_rc = CHARLS_JPEGLS_ERRC_SUCCESS;
    const auto encoded = encode_with_preset_params(src, W, H, custom, &enc_rc);
    ASSERT_EQ(enc_rc, CHARLS_JPEGLS_ERRC_SUCCESS);
    ASSERT_GT(encoded.size(), 20u);

    charls_jpegls_decoder* dec = charls_jpegls_decoder_create();
    ASSERT_EQ(charls_jpegls_decoder_set_source_buffer(dec, encoded.data(), encoded.size()),
              CHARLS_JPEGLS_ERRC_SUCCESS);
    ASSERT_EQ(charls_jpegls_decoder_read_header(dec), CHARLS_JPEGLS_ERRC_SUCCESS);

    size_t dest_size = 0;
    ASSERT_EQ(charls_jpegls_decoder_get_destination_size(dec, 0, &dest_size),
              CHARLS_JPEGLS_ERRC_SUCCESS);
    std::vector<uint8_t> decoded(dest_size);
    ASSERT_EQ(charls_jpegls_decoder_decode_to_buffer(dec, decoded.data(), decoded.size(), 0),
              CHARLS_JPEGLS_ERRC_SUCCESS)
        << "decoder failed to decode LSE-stream with custom preset coding parameters";
    charls_jpegls_decoder_destroy(dec);

    ASSERT_EQ(decoded.size(), src.size()) << "decoded buffer size mismatch";
    for (size_t i = 0; i < src.size(); ++i)
    {
        ASSERT_EQ(decoded[i], src[i])
            << "pixel mismatch at byte " << i
            << " -- decoder likely ignored LSE segment and used default thresholds "
               "(decoded=0x" << std::hex << +decoded[i] << " src=0x" << +src[i] << ")";
    }
}
