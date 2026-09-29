// Module: spiff. Exercises SPIFF header emission (write_standard_spiff_header,
// write_spiff_header), the byte-level SPIFF APP8 segment layout, decoder
// read-back via read_spiff_header, and the charls_validate_spiff_header entry
// point.
//
// Tests:
//   Spiff.WriteStandardSpiffHeaderEmitsAPP8SPIFF
//   Spiff.SpiffHeaderFieldsAreBigEndian
//   Spiff.DecoderReadsBackWrittenSpiffHeader
//   Spiff.ValidateSpiffHeaderMatchesFrameInfo
//   Spiff.ValidateSpiffHeaderRejectsMismatchedBitsPerSample
//
// Portability rule: C API args + comparisons with charls_* types use the
// CHARLS_* C-macro constants. The spiff_header struct fields are typed as
// charls_* in the C ABI struct, so the constants must be used when reading
// them back too.

#include "charls_fixture.h"

#include <charls/charls.h>
#include <gtest/gtest.h>

#include <cstdint>
#include <cstring>
#include <vector>

using charls_test_helpers::make_gray8_gradient;
using charls_test_helpers::read_uint16_be;
using charls_test_helpers::read_uint32_be;


TEST(Spiff, WriteStandardSpiffHeaderEmitsAPP8SPIFF) {
    // Encode a small grayscale image with a standard SPIFF header. Verify the
    // encoded stream starts with:
    //   SOI (FF D8)                              -- 2 bytes
    //   APP8 marker (FF E8) + length (00 20 = 32) -- 4 bytes
    //   "SPIFF\0" identifier                     -- 6 bytes
    //   major = 02, minor = 00                   -- 2 bytes
    // = 14 bytes total before any per-field data.
    const uint32_t W = 16, H = 16;
    const auto src = make_gray8_gradient(W, H);

    charls_jpegls_encoder* enc = charls_jpegls_encoder_create();
    charls_frame_info fi{W, H, 8, 1};
    ASSERT_EQ(charls_jpegls_encoder_set_frame_info(enc, &fi), CHARLS_JPEGLS_ERRC_SUCCESS);

    size_t est = 0;
    charls_jpegls_encoder_get_estimated_destination_size(enc, &est);
    std::vector<uint8_t> dst(est);
    charls_jpegls_encoder_set_destination_buffer(enc, dst.data(), dst.size());

    ASSERT_EQ(charls_jpegls_encoder_write_standard_spiff_header(
                  enc, CHARLS_SPIFF_COLOR_SPACE_GRAYSCALE,
                  CHARLS_SPIFF_RESOLUTION_UNITS_ASPECT_RATIO, 1, 1),
              CHARLS_JPEGLS_ERRC_SUCCESS);
    ASSERT_EQ(charls_jpegls_encoder_encode_from_buffer(enc, src.data(), src.size(), 0),
              CHARLS_JPEGLS_ERRC_SUCCESS);

    size_t bytes_written = 0;
    charls_jpegls_encoder_get_bytes_written(enc, &bytes_written);
    dst.resize(bytes_written);
    charls_jpegls_encoder_destroy(enc);

    // Check the header bytes.
    ASSERT_GE(dst.size(), 14u);
    EXPECT_EQ(dst[0], 0xFF);
    EXPECT_EQ(dst[1], 0xD8);        // SOI
    EXPECT_EQ(dst[2], 0xFF);
    EXPECT_EQ(dst[3], 0xE8);        // APP8
    // Segment length = 2 (length bytes) + 30 (data bytes) = 32 (0x0020).
    EXPECT_EQ(dst[4], 0x00);
    EXPECT_EQ(dst[5], 0x20);
    // SPIFF magic identifier "SPIFF\0".
    EXPECT_EQ(dst[6], 'S');
    EXPECT_EQ(dst[7], 'P');
    EXPECT_EQ(dst[8], 'I');
    EXPECT_EQ(dst[9], 'F');
    EXPECT_EQ(dst[10], 'F');
    EXPECT_EQ(dst[11], 0x00);
    // SPIFF version = 2.0.
    EXPECT_EQ(dst[12], 0x02);
    EXPECT_EQ(dst[13], 0x00);
}


TEST(Spiff, SpiffHeaderFieldsAreBigEndian) {
    // The SPIFF header's height, width, and resolution fields are stored as
    // big-endian uint32. Verify by encoding a stream with distinct known
    // dimensions and cross-checking the raw bytes.
    const uint32_t W = 300, H = 200;
    const uint32_t VRES = 96, HRES = 72;
    const auto src = make_gray8_gradient(W, H);

    charls_jpegls_encoder* enc = charls_jpegls_encoder_create();
    charls_frame_info fi{W, H, 8, 1};
    charls_jpegls_encoder_set_frame_info(enc, &fi);
    size_t est = 0;
    charls_jpegls_encoder_get_estimated_destination_size(enc, &est);
    std::vector<uint8_t> dst(est);
    charls_jpegls_encoder_set_destination_buffer(enc, dst.data(), dst.size());
    charls_jpegls_encoder_write_standard_spiff_header(
        enc, CHARLS_SPIFF_COLOR_SPACE_GRAYSCALE,
        CHARLS_SPIFF_RESOLUTION_UNITS_DOTS_PER_INCH, VRES, HRES);
    charls_jpegls_encoder_encode_from_buffer(enc, src.data(), src.size(), 0);
    size_t bytes_written = 0;
    charls_jpegls_encoder_get_bytes_written(enc, &bytes_written);
    dst.resize(bytes_written);
    charls_jpegls_encoder_destroy(enc);

    // SPIFF header layout (offsets relative to start of encoded stream):
    //   [0..1]   SOI (FF D8)
    //   [2..3]   APP8 marker (FF E8)
    //   [4..5]   segment length (00 20 = 32)
    //   [6..11]  "SPIFF\0" magic
    //   [12]     major revision (2)
    //   [13]     minor revision (0)
    //   [14]     profile_id
    //   [15]     component_count
    //   [16..19] height (uint32 BE)
    //   [20..23] width  (uint32 BE)
    //   [24]     color_space
    //   [25]     bits_per_sample
    //   [26]     compression_type
    //   [27]     resolution_units
    //   [28..31] vertical_resolution   (uint32 BE)
    //   [32..35] horizontal_resolution (uint32 BE)
    ASSERT_GE(dst.size(), 36u);
    EXPECT_EQ(read_uint32_be(dst, 16), H) << "SPIFF height mismatch";
    EXPECT_EQ(read_uint32_be(dst, 20), W) << "SPIFF width mismatch";
    EXPECT_EQ(dst[24], static_cast<uint8_t>(CHARLS_SPIFF_COLOR_SPACE_GRAYSCALE));
    EXPECT_EQ(dst[25], 8u);
    EXPECT_EQ(dst[26], static_cast<uint8_t>(CHARLS_SPIFF_COMPRESSION_TYPE_JPEG_LS));
    EXPECT_EQ(dst[27], static_cast<uint8_t>(CHARLS_SPIFF_RESOLUTION_UNITS_DOTS_PER_INCH));
    EXPECT_EQ(read_uint32_be(dst, 28), VRES);
    EXPECT_EQ(read_uint32_be(dst, 32), HRES);
}


TEST(Spiff, DecoderReadsBackWrittenSpiffHeader) {
    // Round-trip a SPIFF header through the encoder + decoder. The decoder's
    // read_spiff_header must set header_found=1 and populate the struct with
    // the same field values that were written.
    const uint32_t W = 64, H = 48;
    const auto src = make_gray8_gradient(W, H);

    charls_jpegls_encoder* enc = charls_jpegls_encoder_create();
    charls_frame_info fi{W, H, 8, 1};
    charls_jpegls_encoder_set_frame_info(enc, &fi);
    size_t est = 0;
    charls_jpegls_encoder_get_estimated_destination_size(enc, &est);
    std::vector<uint8_t> dst(est);
    charls_jpegls_encoder_set_destination_buffer(enc, dst.data(), dst.size());
    charls_jpegls_encoder_write_standard_spiff_header(
        enc, CHARLS_SPIFF_COLOR_SPACE_GRAYSCALE,
        CHARLS_SPIFF_RESOLUTION_UNITS_DOTS_PER_CENTIMETER, 100, 100);
    charls_jpegls_encoder_encode_from_buffer(enc, src.data(), src.size(), 0);
    size_t bytes_written = 0;
    charls_jpegls_encoder_get_bytes_written(enc, &bytes_written);
    dst.resize(bytes_written);
    charls_jpegls_encoder_destroy(enc);

    // Now decode.
    charls_jpegls_decoder* dec = charls_jpegls_decoder_create();
    ASSERT_EQ(charls_jpegls_decoder_set_source_buffer(dec, dst.data(), dst.size()),
              CHARLS_JPEGLS_ERRC_SUCCESS);

    charls_spiff_header sh{};
    int32_t found = 0;
    ASSERT_EQ(charls_jpegls_decoder_read_spiff_header(dec, &sh, &found), CHARLS_JPEGLS_ERRC_SUCCESS);
    EXPECT_EQ(found, 1);
    EXPECT_EQ(sh.height, H);
    EXPECT_EQ(sh.width, W);
    EXPECT_EQ(sh.bits_per_sample, 8);
    EXPECT_EQ(sh.component_count, 1);
    EXPECT_EQ(sh.color_space, CHARLS_SPIFF_COLOR_SPACE_GRAYSCALE);
    EXPECT_EQ(sh.compression_type, CHARLS_SPIFF_COMPRESSION_TYPE_JPEG_LS);
    EXPECT_EQ(sh.resolution_units, CHARLS_SPIFF_RESOLUTION_UNITS_DOTS_PER_CENTIMETER);
    EXPECT_EQ(sh.vertical_resolution, 100u);
    EXPECT_EQ(sh.horizontal_resolution, 100u);

    charls_jpegls_decoder_destroy(dec);
}


TEST(Spiff, ValidateSpiffHeaderMatchesFrameInfo) {
    // charls_validate_spiff_header returns success when the SPIFF header
    // and the frame_info agree on the four cross-checked fields
    // (width, height, bits_per_sample, component_count).
    charls_spiff_header sh{};
    sh.profile_id           = CHARLS_SPIFF_PROFILE_ID_NONE;
    sh.component_count      = 1;
    sh.height               = 100;
    sh.width                = 200;
    sh.color_space          = CHARLS_SPIFF_COLOR_SPACE_GRAYSCALE;
    sh.bits_per_sample      = 8;
    sh.compression_type     = CHARLS_SPIFF_COMPRESSION_TYPE_JPEG_LS;
    sh.resolution_units     = CHARLS_SPIFF_RESOLUTION_UNITS_ASPECT_RATIO;
    sh.vertical_resolution  = 1;
    sh.horizontal_resolution = 1;

    charls_frame_info fi{200, 100, 8, 1};
    EXPECT_EQ(charls_validate_spiff_header(&sh, &fi), CHARLS_JPEGLS_ERRC_SUCCESS);
}


TEST(Spiff, ValidateSpiffHeaderRejectsMismatchedBitsPerSample) {
    // If the SPIFF header reports 8 bits per sample but the JPEG-LS frame
    // reports 12, validate_spiff_header must return invalid_spiff_header.
    charls_spiff_header sh{};
    sh.profile_id           = CHARLS_SPIFF_PROFILE_ID_NONE;
    sh.component_count      = 1;
    sh.height               = 32;
    sh.width                = 32;
    sh.color_space          = CHARLS_SPIFF_COLOR_SPACE_GRAYSCALE;
    sh.bits_per_sample      = 8;  // mismatch
    sh.compression_type     = CHARLS_SPIFF_COMPRESSION_TYPE_JPEG_LS;
    sh.resolution_units     = CHARLS_SPIFF_RESOLUTION_UNITS_ASPECT_RATIO;
    sh.vertical_resolution  = 1;
    sh.horizontal_resolution = 1;

    charls_frame_info fi{32, 32, 12, 1};  // <-- 12 bits, disagrees with SPIFF.
    EXPECT_EQ(charls_validate_spiff_header(&sh, &fi), CHARLS_JPEGLS_ERRC_INVALID_SPIFF_HEADER);

    // Mismatched height also fails.
    charls_frame_info fi_bad_h{32, 64, 8, 1};
    EXPECT_EQ(charls_validate_spiff_header(&sh, &fi_bad_h), CHARLS_JPEGLS_ERRC_INVALID_SPIFF_HEADER);
}
