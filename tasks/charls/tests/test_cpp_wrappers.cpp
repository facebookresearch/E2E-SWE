// Module: cpp_wrappers. Exercises the header-only C++ wrapper classes
// charls::jpegls_encoder and charls::jpegls_decoder. Verifies the fluent
// builder pattern, exception-based error reporting, and template-container
// convenience overloads (encode / decode taking a std::vector).
//
// Tests:
//   CppWrappers.EncoderChainedBuilderThenEncodeRoundtrip
//   CppWrappers.EncoderThrowsOnInvalidFrameInfo
//   CppWrappers.DecoderTwoArgConstructorReadsHeader
//   CppWrappers.DecoderNoexceptReadHeaderReportsErrorViaEc
//   CppWrappers.OneShotEncodeAndDecodeHelpers

#include "charls_fixture.h"

#include <charls/charls.h>
#include <gtest/gtest.h>

#include <cstdint>
#include <system_error>
#include <utility>
#include <vector>

using charls_test_helpers::make_gray8_gradient;
using charls_test_helpers::make_rgb8_gradient;


TEST(CppWrappers, EncoderChainedBuilderThenEncodeRoundtrip) {
    // Build an encoder via the fluent chained setters and verify the encoded
    // stream round-trips through a decoder to identical pixels.
    const uint32_t W = 24, H = 24;
    const auto src = make_gray8_gradient(W, H);

    charls::jpegls_encoder encoder;
    encoder.frame_info({W, H, 8, 1})
           .near_lossless(0)
           .interleave_mode(charls::interleave_mode::none);

    std::vector<uint8_t> encoded(encoder.estimated_destination_size());
    encoder.destination(encoded);

    const size_t written = encoder.encode(src);
    ASSERT_GT(written, 0u);
    encoded.resize(written);
    EXPECT_EQ(encoder.bytes_written(), written);

    // Decode.
    charls::jpegls_decoder decoder;
    decoder.source(encoded).read_header();

    const auto& fi = decoder.frame_info();
    EXPECT_EQ(fi.width, W);
    EXPECT_EQ(fi.height, H);
    EXPECT_EQ(fi.bits_per_sample, 8);
    EXPECT_EQ(fi.component_count, 1);

    std::vector<uint8_t> decoded(decoder.destination_size());
    decoder.decode(decoded);

    ASSERT_EQ(decoded.size(), src.size());
    for (size_t i = 0; i < src.size(); ++i) {
        ASSERT_EQ(decoded[i], src[i]) << "differ at byte " << i;
    }
}


TEST(CppWrappers, EncoderThrowsOnInvalidFrameInfo) {
    // Invalid frame_info (bits_per_sample = 1) must throw charls::jpegls_error
    // whose code() is invalid_argument_bits_per_sample.
    charls::jpegls_encoder encoder;
    try {
        encoder.frame_info({32, 32, 1, 1});
        FAIL() << "expected an exception, got none";
    } catch (const charls::jpegls_error& e) {
        EXPECT_EQ(e.code().value(),
                  static_cast<int>(charls::jpegls_errc::invalid_argument_bits_per_sample));
    } catch (...) {
        FAIL() << "expected charls::jpegls_error, got a different exception";
    }
}


TEST(CppWrappers, DecoderTwoArgConstructorReadsHeader) {
    // Prepare a real encoded stream first, then construct the decoder with
    // parse_header=true so the ctor internally invokes read_spiff_header +
    // read_header. Accessors like frame_info() must be usable immediately.
    const uint32_t W = 16, H = 16;
    const auto src = make_gray8_gradient(W, H);

    charls::jpegls_encoder enc;
    enc.frame_info({W, H, 8, 1}).interleave_mode(charls::interleave_mode::none);
    std::vector<uint8_t> encoded(enc.estimated_destination_size());
    enc.destination(encoded);
    encoded.resize(enc.encode(src));

    // Two-arg (buffer + size) constructor with parse_header=true.
    charls::jpegls_decoder decoder{encoded.data(), encoded.size(), true};
    EXPECT_EQ(decoder.frame_info().width, W);
    EXPECT_EQ(decoder.frame_info().height, H);
    EXPECT_EQ(decoder.frame_info().bits_per_sample, 8);
    EXPECT_EQ(decoder.frame_info().component_count, 1);
    EXPECT_EQ(decoder.near_lossless(), 0);
}


TEST(CppWrappers, DecoderNoexceptReadHeaderReportsErrorViaEc) {
    // The `noexcept` overload of read_header that takes std::error_code&
    // must never throw; instead it stores a structural-error jpegls_errc
    // into `ec`. Feed the decoder garbage (all-zeros -- no SOI marker
    // anywhere) and confirm ec is set to one of the structural error codes.
    const std::vector<uint8_t> garbage(64, 0x00);

    charls::jpegls_decoder decoder;
    decoder.source(garbage);

    std::error_code ec;
    decoder.read_header(ec);
    EXPECT_TRUE(static_cast<bool>(ec));
    EXPECT_EQ(&ec.category(), &charls::jpegls_category());
    // Structural failures on garbage input: JPEG marker not found, SOI not
    // found, invalid marker segment size, invalid encoded data, or unknown
    // marker. Which one fires depends on internal parsing order.
    const int v = ec.value();
    EXPECT_TRUE(v == static_cast<int>(charls::jpegls_errc::jpeg_marker_start_byte_not_found) ||
                v == static_cast<int>(charls::jpegls_errc::start_of_image_marker_not_found) ||
                v == static_cast<int>(charls::jpegls_errc::invalid_marker_segment_size) ||
                v == static_cast<int>(charls::jpegls_errc::invalid_encoded_data) ||
                v == static_cast<int>(charls::jpegls_errc::unknown_jpeg_marker_found) ||
                v == static_cast<int>(charls::jpegls_errc::unexpected_marker_found) ||
                v == static_cast<int>(charls::jpegls_errc::source_buffer_too_small))
        << "expected a structural-error jpegls_errc value, got " << v;
}


TEST(CppWrappers, OneShotEncodeAndDecodeHelpers) {
    // The static one-shot encode<Container>() and decode<>() helpers hide
    // the encoder/decoder object lifecycle behind a single call.
    const uint32_t W = 32, H = 32;
    const auto src = make_gray8_gradient(W, H);

    const std::vector<uint8_t> encoded =
        charls::jpegls_encoder::encode(src, charls::frame_info{W, H, 8, 1},
                                       charls::interleave_mode::none);
    ASSERT_GT(encoded.size(), 0u);

    std::vector<uint8_t> decoded;
    const std::pair<charls::frame_info, charls::interleave_mode> info =
        charls::jpegls_decoder::decode(encoded, decoded);

    EXPECT_EQ(info.first.width, W);
    EXPECT_EQ(info.first.height, H);
    EXPECT_EQ(info.first.bits_per_sample, 8);
    EXPECT_EQ(info.first.component_count, 1);
    EXPECT_EQ(info.second, charls::interleave_mode::none);

    ASSERT_EQ(decoded.size(), src.size());
    for (size_t i = 0; i < src.size(); ++i) {
        ASSERT_EQ(decoded[i], src[i]) << "differ at byte " << i;
    }
}
