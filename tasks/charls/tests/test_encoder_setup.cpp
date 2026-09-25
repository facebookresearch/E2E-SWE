// Module: encoder_setup. Exercises the encoder lifecycle (create/destroy) and
// the setter validation contracts for frame_info, near_lossless,
// interleave_mode, color_transformation, encoding_options, and
// preset_coding_parameters.
//
// Tests:
//   EncoderSetup.CreateDestroyAndNullDestroyContract
//   EncoderSetup.FrameInfoRejectsZeroWidth
//   EncoderSetup.FrameInfoRejectsBadBitsPerSample
//   EncoderSetup.NearLosslessRangeCheck
//   EncoderSetup.InterleaveModeRangeCheck
//   EncoderSetup.ColorTransformationRangeCheck
//   EncoderSetup.EstimatedDestinationSizeGrowsWithImage
//
// Portability rule: C API args + comparisons against `charls_*` return types
// use the CHARLS_* C-macro constants (works for both alias-style and
// distinct-C-enum agent impls).

#include "charls_fixture.h"

#include <charls/charls.h>
#include <gtest/gtest.h>


TEST(EncoderSetup, CreateDestroyAndNullDestroyContract) {
    // Basic lifecycle: create returns a non-null handle, destroy of that
    // handle succeeds, and destroy of NULL is a documented no-op.
    charls_jpegls_encoder* enc = charls_jpegls_encoder_create();
    ASSERT_NE(enc, nullptr);
    charls_jpegls_encoder_destroy(enc);

    // Passing NULL to destroy must be a no-op (documented C ABI contract).
    charls_jpegls_encoder_destroy(nullptr);
    SUCCEED();
}


TEST(EncoderSetup, FrameInfoRejectsZeroWidth) {
    charls_jpegls_encoder* enc = charls_jpegls_encoder_create();
    ASSERT_NE(enc, nullptr);

    charls_frame_info bad_width{0, 32, 8, 1};
    const auto rc = charls_jpegls_encoder_set_frame_info(enc, &bad_width);
    EXPECT_EQ(rc, CHARLS_JPEGLS_ERRC_INVALID_ARGUMENT_WIDTH);

    charls_frame_info bad_height{32, 0, 8, 1};
    const auto rc2 = charls_jpegls_encoder_set_frame_info(enc, &bad_height);
    EXPECT_EQ(rc2, CHARLS_JPEGLS_ERRC_INVALID_ARGUMENT_HEIGHT);

    // Valid frame info: 32x32 grayscale 8-bit.
    charls_frame_info ok{32, 32, 8, 1};
    const auto rc3 = charls_jpegls_encoder_set_frame_info(enc, &ok);
    EXPECT_EQ(rc3, CHARLS_JPEGLS_ERRC_SUCCESS);

    charls_jpegls_encoder_destroy(enc);
}


TEST(EncoderSetup, FrameInfoRejectsBadBitsPerSample) {
    charls_jpegls_encoder* enc = charls_jpegls_encoder_create();
    ASSERT_NE(enc, nullptr);

    // bits_per_sample < 2 is out of range.
    charls_frame_info too_low{32, 32, 1, 1};
    EXPECT_EQ(charls_jpegls_encoder_set_frame_info(enc, &too_low),
              CHARLS_JPEGLS_ERRC_INVALID_ARGUMENT_BITS_PER_SAMPLE);

    // bits_per_sample > 16 is out of range.
    charls_frame_info too_high{32, 32, 17, 1};
    EXPECT_EQ(charls_jpegls_encoder_set_frame_info(enc, &too_high),
              CHARLS_JPEGLS_ERRC_INVALID_ARGUMENT_BITS_PER_SAMPLE);

    // component_count == 0 is out of range.
    charls_frame_info zero_comp{32, 32, 8, 0};
    EXPECT_EQ(charls_jpegls_encoder_set_frame_info(enc, &zero_comp),
              CHARLS_JPEGLS_ERRC_INVALID_ARGUMENT_COMPONENT_COUNT);

    // All valid.
    charls_frame_info ok{32, 32, 12, 3};
    EXPECT_EQ(charls_jpegls_encoder_set_frame_info(enc, &ok),
              CHARLS_JPEGLS_ERRC_SUCCESS);

    charls_jpegls_encoder_destroy(enc);
}


TEST(EncoderSetup, NearLosslessRangeCheck) {
    charls_jpegls_encoder* enc = charls_jpegls_encoder_create();
    ASSERT_NE(enc, nullptr);

    // Negative near-lossless is out of range.
    EXPECT_EQ(charls_jpegls_encoder_set_near_lossless(enc, -1),
              CHARLS_JPEGLS_ERRC_INVALID_ARGUMENT_NEAR_LOSSLESS);

    // 256 is out of range (max is 255).
    EXPECT_EQ(charls_jpegls_encoder_set_near_lossless(enc, 256),
              CHARLS_JPEGLS_ERRC_INVALID_ARGUMENT_NEAR_LOSSLESS);

    // 0 is legal (lossless, the default).
    EXPECT_EQ(charls_jpegls_encoder_set_near_lossless(enc, 0),
              CHARLS_JPEGLS_ERRC_SUCCESS);

    // 10 is legal.
    EXPECT_EQ(charls_jpegls_encoder_set_near_lossless(enc, 10),
              CHARLS_JPEGLS_ERRC_SUCCESS);

    // 255 is legal (the maximum).
    EXPECT_EQ(charls_jpegls_encoder_set_near_lossless(enc, 255),
              CHARLS_JPEGLS_ERRC_SUCCESS);

    charls_jpegls_encoder_destroy(enc);
}


TEST(EncoderSetup, InterleaveModeRangeCheck) {
    charls_jpegls_encoder* enc = charls_jpegls_encoder_create();
    ASSERT_NE(enc, nullptr);

    // Value 3 is out of range (0=none, 1=line, 2=sample).
    EXPECT_EQ(charls_jpegls_encoder_set_interleave_mode(
                  enc, static_cast<charls_interleave_mode>(3)),
              CHARLS_JPEGLS_ERRC_INVALID_ARGUMENT_INTERLEAVE_MODE);

    // Negative is out of range.
    EXPECT_EQ(charls_jpegls_encoder_set_interleave_mode(
                  enc, static_cast<charls_interleave_mode>(-1)),
              CHARLS_JPEGLS_ERRC_INVALID_ARGUMENT_INTERLEAVE_MODE);

    // All three legal values succeed.
    EXPECT_EQ(charls_jpegls_encoder_set_interleave_mode(enc, CHARLS_INTERLEAVE_MODE_NONE),
              CHARLS_JPEGLS_ERRC_SUCCESS);
    EXPECT_EQ(charls_jpegls_encoder_set_interleave_mode(enc, CHARLS_INTERLEAVE_MODE_LINE),
              CHARLS_JPEGLS_ERRC_SUCCESS);
    EXPECT_EQ(charls_jpegls_encoder_set_interleave_mode(enc, CHARLS_INTERLEAVE_MODE_SAMPLE),
              CHARLS_JPEGLS_ERRC_SUCCESS);

    charls_jpegls_encoder_destroy(enc);
}


TEST(EncoderSetup, ColorTransformationRangeCheck) {
    charls_jpegls_encoder* enc = charls_jpegls_encoder_create();
    ASSERT_NE(enc, nullptr);

    // Value 4 is out of range (0=none, 1=hp1, 2=hp2, 3=hp3).
    EXPECT_EQ(charls_jpegls_encoder_set_color_transformation(
                  enc, static_cast<charls_color_transformation>(4)),
              CHARLS_JPEGLS_ERRC_INVALID_ARGUMENT_COLOR_TRANSFORMATION);

    // Negative is out of range.
    EXPECT_EQ(charls_jpegls_encoder_set_color_transformation(
                  enc, static_cast<charls_color_transformation>(-1)),
              CHARLS_JPEGLS_ERRC_INVALID_ARGUMENT_COLOR_TRANSFORMATION);

    // All four legal values succeed at the setter (cross-checks with
    // component_count are deferred to encode).
    EXPECT_EQ(charls_jpegls_encoder_set_color_transformation(enc, CHARLS_COLOR_TRANSFORMATION_NONE),
              CHARLS_JPEGLS_ERRC_SUCCESS);
    EXPECT_EQ(charls_jpegls_encoder_set_color_transformation(enc, CHARLS_COLOR_TRANSFORMATION_HP1),
              CHARLS_JPEGLS_ERRC_SUCCESS);
    EXPECT_EQ(charls_jpegls_encoder_set_color_transformation(enc, CHARLS_COLOR_TRANSFORMATION_HP2),
              CHARLS_JPEGLS_ERRC_SUCCESS);
    EXPECT_EQ(charls_jpegls_encoder_set_color_transformation(enc, CHARLS_COLOR_TRANSFORMATION_HP3),
              CHARLS_JPEGLS_ERRC_SUCCESS);

    charls_jpegls_encoder_destroy(enc);
}


TEST(EncoderSetup, EstimatedDestinationSizeGrowsWithImage) {
    // estimated_destination_size must be at least large enough to hold the raw
    // uncompressed pixels + some header/preset overhead. Confirm it scales with
    // frame dimensions and returns a value large enough to hold the raw image.
    charls_jpegls_encoder* enc_small = charls_jpegls_encoder_create();
    charls_jpegls_encoder* enc_large = charls_jpegls_encoder_create();
    ASSERT_NE(enc_small, nullptr);
    ASSERT_NE(enc_large, nullptr);

    charls_frame_info small{32, 32, 8, 1};
    charls_frame_info large{128, 128, 8, 1};
    ASSERT_EQ(charls_jpegls_encoder_set_frame_info(enc_small, &small), CHARLS_JPEGLS_ERRC_SUCCESS);
    ASSERT_EQ(charls_jpegls_encoder_set_frame_info(enc_large, &large), CHARLS_JPEGLS_ERRC_SUCCESS);

    size_t est_small = 0, est_large = 0;
    EXPECT_EQ(charls_jpegls_encoder_get_estimated_destination_size(enc_small, &est_small),
              CHARLS_JPEGLS_ERRC_SUCCESS);
    EXPECT_EQ(charls_jpegls_encoder_get_estimated_destination_size(enc_large, &est_large),
              CHARLS_JPEGLS_ERRC_SUCCESS);

    // Small image needs at least (32*32*1) = 1024 raw bytes + overhead.
    EXPECT_GE(est_small, 32u * 32u * 1u);
    // Large image needs at least (128*128*1) = 16384 raw bytes + overhead.
    EXPECT_GE(est_large, 128u * 128u * 1u);
    // Larger image must estimate a larger buffer.
    EXPECT_GT(est_large, est_small);

    charls_jpegls_encoder_destroy(enc_small);
    charls_jpegls_encoder_destroy(enc_large);
}
