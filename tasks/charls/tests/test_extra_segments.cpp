// Module: extra_segments. Exercises the auxiliary encoder segments:
// preset coding parameters (LSE segment), COM (comment) segment, and
// APPn (application data) segment. Plus the decoder callback plumbing
// (at_comment).
//
// Tests:
//   ExtraSegments.CustomPresetCodingParametersRoundtrip
//   ExtraSegments.WriteCommentThenEncodeDecodesCorrectly
//   ExtraSegments.CommentCallbackFiresWithExactBytes
//   ExtraSegments.ApplicationDataIdRangeCheck
//   ExtraSegments.RewindAllowsSecondEncode
//
// Portability rule: C API args + return-code comparisons use the CHARLS_*
// C-macro constants.

#include "charls_fixture.h"

#include <charls/charls.h>
#include <gtest/gtest.h>

#include <cstdint>
#include <cstring>
#include <string>
#include <vector>

using charls_test_helpers::make_gray8_gradient;


TEST(ExtraSegments, CustomPresetCodingParametersRoundtrip) {
    // Set explicit non-default preset coding parameters. Encoder emits an LSE
    // segment; decoder reads them back via get_preset_coding_parameters.
    const uint32_t W = 32, H = 32;
    const auto src = make_gray8_gradient(W, H);

    // For 8-bit images the default parameters are T1=3, T2=7, T3=21, RESET=64,
    // MAXVAL=255. Pick a distinctly non-default set that's still valid per
    // ISO/IEC 14495-1 C.2.4.1.1.
    charls_jpegls_pc_parameters custom{};
    custom.maximum_sample_value = 255;
    custom.threshold1           = 5;
    custom.threshold2           = 10;
    custom.threshold3           = 30;
    custom.reset_value          = 40;

    charls_jpegls_encoder* enc = charls_jpegls_encoder_create();
    charls_frame_info fi{W, H, 8, 1};
    ASSERT_EQ(charls_jpegls_encoder_set_frame_info(enc, &fi), CHARLS_JPEGLS_ERRC_SUCCESS);
    ASSERT_EQ(charls_jpegls_encoder_set_preset_coding_parameters(enc, &custom),
              CHARLS_JPEGLS_ERRC_SUCCESS);

    size_t est = 0;
    charls_jpegls_encoder_get_estimated_destination_size(enc, &est);
    std::vector<uint8_t> dst(est);
    charls_jpegls_encoder_set_destination_buffer(enc, dst.data(), dst.size());
    ASSERT_EQ(charls_jpegls_encoder_encode_from_buffer(enc, src.data(), src.size(), 0),
              CHARLS_JPEGLS_ERRC_SUCCESS);
    size_t written = 0;
    charls_jpegls_encoder_get_bytes_written(enc, &written);
    dst.resize(written);
    charls_jpegls_encoder_destroy(enc);

    // Decode.
    charls_jpegls_decoder* dec = charls_jpegls_decoder_create();
    charls_jpegls_decoder_set_source_buffer(dec, dst.data(), dst.size());
    ASSERT_EQ(charls_jpegls_decoder_read_header(dec), CHARLS_JPEGLS_ERRC_SUCCESS);

    charls_jpegls_pc_parameters read_back{};
    ASSERT_EQ(charls_jpegls_decoder_get_preset_coding_parameters(dec, 0, &read_back),
              CHARLS_JPEGLS_ERRC_SUCCESS);
    EXPECT_EQ(read_back.maximum_sample_value, 255);
    EXPECT_EQ(read_back.threshold1, 5);
    EXPECT_EQ(read_back.threshold2, 10);
    EXPECT_EQ(read_back.threshold3, 30);
    EXPECT_EQ(read_back.reset_value, 40);

    charls_jpegls_decoder_destroy(dec);
}


TEST(ExtraSegments, WriteCommentThenEncodeDecodesCorrectly) {
    // Writing a COM (comment) segment before encoding must not break the
    // subsequent decode. The decoded pixels must still match the input, and
    // the COM segment must be present in the encoded stream (searchable via
    // the byte pattern 0xFF 0xFE).
    const uint32_t W = 16, H = 16;
    const auto src = make_gray8_gradient(W, H);

    const std::string comment = "test-comment";
    charls_jpegls_encoder* enc = charls_jpegls_encoder_create();
    charls_frame_info fi{W, H, 8, 1};
    charls_jpegls_encoder_set_frame_info(enc, &fi);
    size_t est = 0;
    charls_jpegls_encoder_get_estimated_destination_size(enc, &est);
    std::vector<uint8_t> dst(est);
    charls_jpegls_encoder_set_destination_buffer(enc, dst.data(), dst.size());

    ASSERT_EQ(charls_jpegls_encoder_write_comment(enc, comment.data(), comment.size()),
              CHARLS_JPEGLS_ERRC_SUCCESS);
    ASSERT_EQ(charls_jpegls_encoder_encode_from_buffer(enc, src.data(), src.size(), 0),
              CHARLS_JPEGLS_ERRC_SUCCESS);
    size_t written = 0;
    charls_jpegls_encoder_get_bytes_written(enc, &written);
    dst.resize(written);
    charls_jpegls_encoder_destroy(enc);

    // Search for the COM marker (FF FE) in the encoded stream.
    bool found_com = false;
    for (size_t i = 0; i + 1 < dst.size(); ++i) {
        if (dst[i] == 0xFF && dst[i + 1] == 0xFE) {
            found_com = true;
            break;
        }
    }
    EXPECT_TRUE(found_com) << "COM marker (FF FE) not found in encoded stream";

    // Decode must still work and give back the original pixels.
    charls_jpegls_decoder* dec = charls_jpegls_decoder_create();
    charls_jpegls_decoder_set_source_buffer(dec, dst.data(), dst.size());
    ASSERT_EQ(charls_jpegls_decoder_read_header(dec), CHARLS_JPEGLS_ERRC_SUCCESS);
    size_t dest_size = 0;
    charls_jpegls_decoder_get_destination_size(dec, 0, &dest_size);
    std::vector<uint8_t> decoded(dest_size);
    ASSERT_EQ(charls_jpegls_decoder_decode_to_buffer(dec, decoded.data(), decoded.size(), 0),
              CHARLS_JPEGLS_ERRC_SUCCESS);
    ASSERT_EQ(decoded.size(), src.size());
    for (size_t i = 0; i < src.size(); ++i) {
        ASSERT_EQ(decoded[i], src[i]) << "differ at byte " << i;
    }
    charls_jpegls_decoder_destroy(dec);
}


namespace {

struct comment_capture {
    std::string captured;
};

int32_t on_comment(const void* data, size_t size, void* ctx) noexcept {
    auto* c = static_cast<comment_capture*>(ctx);
    c->captured.assign(static_cast<const char*>(data), size);
    return 0;  // signal success -- decoding proceeds.
}

}  // namespace


TEST(ExtraSegments, CommentCallbackFiresWithExactBytes) {
    // Register an at_comment callback; encode a stream with a specific COM
    // payload; decode and verify the callback saw exactly those bytes.
    const uint32_t W = 8, H = 8;
    const auto src = make_gray8_gradient(W, H);
    const std::string payload = "hello-jpegls";

    charls_jpegls_encoder* enc = charls_jpegls_encoder_create();
    charls_frame_info fi{W, H, 8, 1};
    charls_jpegls_encoder_set_frame_info(enc, &fi);
    size_t est = 0;
    charls_jpegls_encoder_get_estimated_destination_size(enc, &est);
    std::vector<uint8_t> dst(est);
    charls_jpegls_encoder_set_destination_buffer(enc, dst.data(), dst.size());
    charls_jpegls_encoder_write_comment(enc, payload.data(), payload.size());
    charls_jpegls_encoder_encode_from_buffer(enc, src.data(), src.size(), 0);
    size_t written = 0;
    charls_jpegls_encoder_get_bytes_written(enc, &written);
    dst.resize(written);
    charls_jpegls_encoder_destroy(enc);

    // Decode with an installed comment callback.
    comment_capture cap;
    charls_jpegls_decoder* dec = charls_jpegls_decoder_create();
    charls_jpegls_decoder_set_source_buffer(dec, dst.data(), dst.size());
    ASSERT_EQ(charls_jpegls_decoder_at_comment(dec, &on_comment, &cap),
              CHARLS_JPEGLS_ERRC_SUCCESS);
    ASSERT_EQ(charls_jpegls_decoder_read_header(dec), CHARLS_JPEGLS_ERRC_SUCCESS);

    EXPECT_EQ(cap.captured, payload) << "callback did not receive expected COM bytes";

    charls_jpegls_decoder_destroy(dec);
}


TEST(ExtraSegments, ApplicationDataIdRangeCheck) {
    // application_data_id is in [0, 15]. 16 is out of range; -1 is out of range.
    // Encoder needs frame_info + destination buffer to be in the right state.
    charls_jpegls_encoder* enc = charls_jpegls_encoder_create();
    charls_frame_info fi{16, 16, 8, 1};
    charls_jpegls_encoder_set_frame_info(enc, &fi);
    size_t est = 0;
    charls_jpegls_encoder_get_estimated_destination_size(enc, &est);
    std::vector<uint8_t> dst(est);
    charls_jpegls_encoder_set_destination_buffer(enc, dst.data(), dst.size());

    const uint8_t data[4] = {0xDE, 0xAD, 0xBE, 0xEF};

    // id = 16 is out of range. Conformant impls return one of the two
    // "invalid argument" codes documented in instruction.md for this API.
    const auto rc_high = charls_jpegls_encoder_write_application_data(enc, 16, data, sizeof(data));
    EXPECT_TRUE(rc_high == CHARLS_JPEGLS_ERRC_INVALID_ARGUMENT ||
                rc_high == CHARLS_JPEGLS_ERRC_INVALID_ARGUMENT_SIZE)
        << "application_data_id=16 must be rejected with invalid_argument or invalid_argument_size, got "
        << static_cast<int>(rc_high);

    // id = -1 is out of range.
    const auto rc_low = charls_jpegls_encoder_write_application_data(enc, -1, data, sizeof(data));
    EXPECT_TRUE(rc_low == CHARLS_JPEGLS_ERRC_INVALID_ARGUMENT ||
                rc_low == CHARLS_JPEGLS_ERRC_INVALID_ARGUMENT_SIZE)
        << "application_data_id=-1 must be rejected with invalid_argument or invalid_argument_size, got "
        << static_cast<int>(rc_low);

    // id = 5 is legal.
    const auto rc_ok = charls_jpegls_encoder_write_application_data(enc, 5, data, sizeof(data));
    EXPECT_EQ(rc_ok, CHARLS_JPEGLS_ERRC_SUCCESS);

    charls_jpegls_encoder_destroy(enc);
}


TEST(ExtraSegments, RewindAllowsSecondEncode) {
    // After a full encode, rewind() resets the write position so the same
    // destination buffer can be reused for a second encode without recreating
    // the encoder. frame_info / interleave_mode etc. must survive the rewind.
    const uint32_t W = 16, H = 16;
    const auto src = make_gray8_gradient(W, H);

    charls_jpegls_encoder* enc = charls_jpegls_encoder_create();
    charls_frame_info fi{W, H, 8, 1};
    charls_jpegls_encoder_set_frame_info(enc, &fi);
    size_t est = 0;
    charls_jpegls_encoder_get_estimated_destination_size(enc, &est);
    std::vector<uint8_t> dst(est);
    charls_jpegls_encoder_set_destination_buffer(enc, dst.data(), dst.size());

    ASSERT_EQ(charls_jpegls_encoder_encode_from_buffer(enc, src.data(), src.size(), 0),
              CHARLS_JPEGLS_ERRC_SUCCESS);
    size_t first_written = 0;
    charls_jpegls_encoder_get_bytes_written(enc, &first_written);
    EXPECT_GT(first_written, 0u);

    // Rewind and encode again -- the second encode must produce the same
    // byte-count as the first (identical input, identical settings).
    ASSERT_EQ(charls_jpegls_encoder_rewind(enc), CHARLS_JPEGLS_ERRC_SUCCESS);
    ASSERT_EQ(charls_jpegls_encoder_encode_from_buffer(enc, src.data(), src.size(), 0),
              CHARLS_JPEGLS_ERRC_SUCCESS);
    size_t second_written = 0;
    charls_jpegls_encoder_get_bytes_written(enc, &second_written);
    EXPECT_EQ(second_written, first_written);

    charls_jpegls_encoder_destroy(enc);
}
