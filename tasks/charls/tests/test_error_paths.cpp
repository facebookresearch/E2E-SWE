// Module: error_paths. Exercises the encoder / decoder error-return contracts
// for common misuses: too-small destination buffer, decoding malformed input,
// decoder accessors called before read_header, etc.
//
// Tests:
//   ErrorPaths.EncodeIntoTooSmallBufferReturnsDestinationTooSmall
//   ErrorPaths.DecodeEmptyStreamReturnsStreamError
//   ErrorPaths.DecodeGarbageReturnsSpecificError
//   ErrorPaths.DecoderAccessorsBeforeReadHeaderReturnInvalidOperation
//   ErrorPaths.EncodeWithoutFrameInfoReturnsInvalidOperation
//
// Portability rule: C API args + return-code comparisons use the CHARLS_*
// C-macro constants.

#include "charls_fixture.h"

#include <charls/charls.h>
#include <gtest/gtest.h>

#include <cstdint>
#include <vector>

using charls_test_helpers::make_gray8_gradient;


TEST(ErrorPaths, EncodeIntoTooSmallBufferReturnsDestinationTooSmall) {
    // Provide a destination buffer that is far too small to hold even the
    // JPEG header + SOF segment. The encode must return
    // destination_buffer_too_small (not crash, not silently succeed).
    const uint32_t W = 32, H = 32;
    const auto src = make_gray8_gradient(W, H);

    charls_jpegls_encoder* enc = charls_jpegls_encoder_create();
    charls_frame_info fi{W, H, 8, 1};
    ASSERT_EQ(charls_jpegls_encoder_set_frame_info(enc, &fi), CHARLS_JPEGLS_ERRC_SUCCESS);

    std::vector<uint8_t> tiny_dst(4);  // 4 bytes -- can barely hold the SOI marker.
    ASSERT_EQ(charls_jpegls_encoder_set_destination_buffer(enc, tiny_dst.data(), tiny_dst.size()),
              CHARLS_JPEGLS_ERRC_SUCCESS);

    const auto rc = charls_jpegls_encoder_encode_from_buffer(enc, src.data(), src.size(), 0);
    EXPECT_EQ(rc, CHARLS_JPEGLS_ERRC_DESTINATION_BUFFER_TOO_SMALL);

    charls_jpegls_encoder_destroy(enc);
}


TEST(ErrorPaths, DecodeEmptyStreamReturnsStreamError) {
    // Feeding a decoder a 0-length or too-short source buffer must not crash
    // and must return one of the structural-error codes on read_header.
    // Which specific code depends on internal parsing order (a decoder that
    // checks buffer-size first may return SOURCE_BUFFER_TOO_SMALL, one that
    // goes straight to the marker scan may return
    // JPEG_MARKER_START_BYTE_NOT_FOUND / START_OF_IMAGE_MARKER_NOT_FOUND).
    charls_jpegls_decoder* dec = charls_jpegls_decoder_create();

    // Empty buffer.
    const uint8_t nothing[1] = {0};
    ASSERT_EQ(charls_jpegls_decoder_set_source_buffer(dec, nothing, 0),
              CHARLS_JPEGLS_ERRC_SUCCESS);
    const auto rc = charls_jpegls_decoder_read_header(dec);
    EXPECT_TRUE(rc == CHARLS_JPEGLS_ERRC_SOURCE_BUFFER_TOO_SMALL ||
                rc == CHARLS_JPEGLS_ERRC_JPEG_MARKER_START_BYTE_NOT_FOUND ||
                rc == CHARLS_JPEGLS_ERRC_START_OF_IMAGE_MARKER_NOT_FOUND ||
                rc == CHARLS_JPEGLS_ERRC_INVALID_ENCODED_DATA ||
                rc == CHARLS_JPEGLS_ERRC_INVALID_MARKER_SEGMENT_SIZE ||
                rc == CHARLS_JPEGLS_ERRC_INVALID_OPERATION)
        << "expected a structural-error code on 0-byte stream, got " << static_cast<int>(rc);

    charls_jpegls_decoder_destroy(dec);
}


TEST(ErrorPaths, DecodeGarbageReturnsSpecificError) {
    // Feed the decoder a couple of bytes that don't form any valid JPEG marker
    // pattern. The decoder must return one of the structural-error codes
    // (which specific code fires depends on parsing order within the decoder
    // and is not a user-observable contract). Reject only success.
    charls_jpegls_decoder* dec = charls_jpegls_decoder_create();
    const uint8_t garbage[2] = {0x33, 0x33};  // no 0xFF marker start anywhere.
    ASSERT_EQ(charls_jpegls_decoder_set_source_buffer(dec, garbage, sizeof(garbage)),
              CHARLS_JPEGLS_ERRC_SUCCESS);

    const auto rc = charls_jpegls_decoder_read_header(dec);
    EXPECT_TRUE(rc == CHARLS_JPEGLS_ERRC_JPEG_MARKER_START_BYTE_NOT_FOUND ||
                rc == CHARLS_JPEGLS_ERRC_INVALID_MARKER_SEGMENT_SIZE ||
                rc == CHARLS_JPEGLS_ERRC_START_OF_IMAGE_MARKER_NOT_FOUND ||
                rc == CHARLS_JPEGLS_ERRC_UNKNOWN_JPEG_MARKER_FOUND ||
                rc == CHARLS_JPEGLS_ERRC_UNEXPECTED_MARKER_FOUND ||
                rc == CHARLS_JPEGLS_ERRC_INVALID_ENCODED_DATA)
        << "expected a structural-error code on garbage input, got " << static_cast<int>(rc);

    charls_jpegls_decoder_destroy(dec);
}


TEST(ErrorPaths, DecoderAccessorsBeforeReadHeaderReturnInvalidOperation) {
    // Calling get_frame_info / get_near_lossless / get_interleave_mode before
    // read_header succeeds is illegal state -- must return invalid_operation.
    charls_jpegls_decoder* dec = charls_jpegls_decoder_create();
    // Note: don't set source, don't read header.

    charls_frame_info fi{};
    EXPECT_EQ(charls_jpegls_decoder_get_frame_info(dec, &fi),
              CHARLS_JPEGLS_ERRC_INVALID_OPERATION);

    int32_t near = 0;
    EXPECT_EQ(charls_jpegls_decoder_get_near_lossless(dec, 0, &near),
              CHARLS_JPEGLS_ERRC_INVALID_OPERATION);

    charls_interleave_mode ilv;
    EXPECT_EQ(charls_jpegls_decoder_get_interleave_mode(dec, &ilv),
              CHARLS_JPEGLS_ERRC_INVALID_OPERATION);

    charls_jpegls_decoder_destroy(dec);
}


TEST(ErrorPaths, EncodeWithoutFrameInfoReturnsInvalidOperation) {
    // Calling encode without first setting frame_info is an illegal state.
    // The C ABI must return invalid_operation, not crash.
    const uint32_t W = 8, H = 8;
    const auto src = make_gray8_gradient(W, H);

    charls_jpegls_encoder* enc = charls_jpegls_encoder_create();
    // No set_frame_info call.

    std::vector<uint8_t> dst(1024);
    ASSERT_EQ(charls_jpegls_encoder_set_destination_buffer(enc, dst.data(), dst.size()),
              CHARLS_JPEGLS_ERRC_SUCCESS);

    const auto rc = charls_jpegls_encoder_encode_from_buffer(enc, src.data(), src.size(), 0);
    EXPECT_EQ(rc, CHARLS_JPEGLS_ERRC_INVALID_OPERATION);

    // get_estimated_destination_size before frame_info is also invalid.
    size_t est = 0;
    const auto rc2 = charls_jpegls_encoder_get_estimated_destination_size(enc, &est);
    EXPECT_EQ(rc2, CHARLS_JPEGLS_ERRC_INVALID_OPERATION);

    charls_jpegls_encoder_destroy(enc);
}
