// Module: encode_color_transform. Exercises the HP color transformations
// (HP1, HP2, HP3) applied to 3-component RGB images. Verifies (a) each
// transform round-trips losslessly, (b) the decoder reads back the applied
// transform, and (c) the NONE transform is reported as NONE.
//
// Tests:
//   ColorTransform.Hp1RgbRoundtripLossless
//   ColorTransform.Hp2RgbRoundtripLossless
//   ColorTransform.Hp3RgbRoundtripLossless
//   ColorTransform.DecoderReadsBackTransform
//   ColorTransform.NoneMeansNoTransformOnDecodedStream
//
// Portability rule: C API args + comparisons against `charls_*` types use the
// CHARLS_* C-macro constants.

#include "charls_fixture.h"

#include <charls/charls.h>
#include <gtest/gtest.h>

#include <cstdint>
#include <vector>

using charls_test_helpers::make_rgb8_gradient;


namespace {

// Encode with a specific color transformation, then decode. Returns the full
// encoded/decoded pair for further inspection. The source is pixel-interleaved
// RGB (RGBRGB layout); the encoder uses sample-interleaved mode.
struct color_transform_result {
    std::vector<uint8_t> encoded;
    std::vector<uint8_t> decoded;
    charls_color_transformation decoded_transform{};
    charls_frame_info decoded_frame_info{};
};

color_transform_result encode_decode_with_transform(
    const std::vector<uint8_t>& src, const uint32_t width, const uint32_t height,
    const charls_color_transformation transform)
{
    color_transform_result r{};

    charls_jpegls_encoder* enc = charls_jpegls_encoder_create();
    charls_frame_info fi{width, height, 8, 3};
    charls_jpegls_encoder_set_frame_info(enc, &fi);
    charls_jpegls_encoder_set_interleave_mode(enc, CHARLS_INTERLEAVE_MODE_SAMPLE);
    charls_jpegls_encoder_set_near_lossless(enc, 0);
    charls_jpegls_encoder_set_color_transformation(enc, transform);

    size_t est = 0;
    charls_jpegls_encoder_get_estimated_destination_size(enc, &est);
    r.encoded.resize(est);
    charls_jpegls_encoder_set_destination_buffer(enc, r.encoded.data(), r.encoded.size());
    charls_jpegls_encoder_encode_from_buffer(enc, src.data(), src.size(), 0);

    size_t bytes_written = 0;
    charls_jpegls_encoder_get_bytes_written(enc, &bytes_written);
    r.encoded.resize(bytes_written);
    charls_jpegls_encoder_destroy(enc);

    charls_jpegls_decoder* dec = charls_jpegls_decoder_create();
    charls_jpegls_decoder_set_source_buffer(dec, r.encoded.data(), r.encoded.size());
    charls_jpegls_decoder_read_header(dec);
    charls_jpegls_decoder_get_frame_info(dec, &r.decoded_frame_info);
    charls_jpegls_decoder_get_color_transformation(dec, &r.decoded_transform);

    size_t dest_size = 0;
    charls_jpegls_decoder_get_destination_size(dec, 0, &dest_size);
    r.decoded.resize(dest_size);
    charls_jpegls_decoder_decode_to_buffer(dec, r.decoded.data(), r.decoded.size(), 0);
    charls_jpegls_decoder_destroy(dec);

    return r;
}

}  // namespace


TEST(ColorTransform, Hp1RgbRoundtripLossless) {
    // HP1 = (R-G, G, B-G). Reversible transform, so lossless encode+decode
    // must reproduce the original RGB pixels bit-for-bit.
    const uint32_t W = 24, H = 24;
    const auto src = make_rgb8_gradient(W, H);
    const auto r = encode_decode_with_transform(src, W, H, CHARLS_COLOR_TRANSFORMATION_HP1);

    ASSERT_EQ(r.decoded.size(), src.size());
    for (size_t i = 0; i < src.size(); ++i) {
        ASSERT_EQ(r.decoded[i], src[i]) << "differ at byte " << i;
    }
}


TEST(ColorTransform, Hp2RgbRoundtripLossless) {
    // HP2 = (R-G, G, B-(R+G)/2). Reversible.
    const uint32_t W = 24, H = 24;
    const auto src = make_rgb8_gradient(W, H);
    const auto r = encode_decode_with_transform(src, W, H, CHARLS_COLOR_TRANSFORMATION_HP2);

    ASSERT_EQ(r.decoded.size(), src.size());
    for (size_t i = 0; i < src.size(); ++i) {
        ASSERT_EQ(r.decoded[i], src[i]) << "differ at byte " << i;
    }
}


TEST(ColorTransform, Hp3RgbRoundtripLossless) {
    // HP3 = (R-G, G+((R+B)/4), B-G). Reversible: after encode+decode through
    // the same library, decoded pixels must equal the source bit-for-bit.
    const uint32_t W = 24, H = 24;
    const auto src = make_rgb8_gradient(W, H);
    const auto r = encode_decode_with_transform(src, W, H, CHARLS_COLOR_TRANSFORMATION_HP3);

    ASSERT_EQ(r.decoded.size(), src.size());
    for (size_t i = 0; i < src.size(); ++i) {
        ASSERT_EQ(r.decoded[i], src[i]) << "differ at byte " << i;
    }
}


TEST(ColorTransform, DecoderReadsBackTransform) {
    // The color transform is stored in the encoded stream (via a private HP
    // APP segment) so the decoder can undo it. Verify each transform round-trips
    // through decoder.get_color_transformation.
    const uint32_t W = 16, H = 16;
    const auto src = make_rgb8_gradient(W, H);
    for (const charls_color_transformation t : {CHARLS_COLOR_TRANSFORMATION_HP1,
                                                CHARLS_COLOR_TRANSFORMATION_HP2,
                                                CHARLS_COLOR_TRANSFORMATION_HP3}) {
        const auto r = encode_decode_with_transform(src, W, H, t);
        EXPECT_EQ(r.decoded_transform, t)
            << "encoded with " << static_cast<int>(t)
            << " but decoder read back " << static_cast<int>(r.decoded_transform);
    }
}


TEST(ColorTransform, NoneMeansNoTransformOnDecodedStream) {
    // With color_transformation::none, the decoder must report NONE on read-back.
    const uint32_t W = 16, H = 16;
    const auto src = make_rgb8_gradient(W, H);
    const auto r = encode_decode_with_transform(src, W, H, CHARLS_COLOR_TRANSFORMATION_NONE);
    EXPECT_EQ(r.decoded_transform, CHARLS_COLOR_TRANSFORMATION_NONE);
}
