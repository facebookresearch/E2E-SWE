// Module: decode_reference. Exercises the decoder against a real JPEG-LS
// stream produced by the HP reference encoder (tulips-gray-8bit-512-512).
// This is a cross-implementation conformance check: any conformant JPEG-LS
// decoder must reproduce the exact same pixels from this reference stream.
// One test also checks decode determinism on a stream the library itself
// produced (no foreign-stream dependency).
//
// Tests:
//   DecodeReference.TulipsHeaderReportsCorrectFrameInfo
//   DecodeReference.TulipsHeaderReportsLosslessNoneInterleave
//   DecodeReference.TulipsDecodesToExpectedSize
//   DecodeReference.EncodedStreamDecodeIsDeterministic
//
// Portability rule: C API args + return-code comparisons use the CHARLS_*
// C-macro constants.

#include "charls_fixture.h"

#include <charls/charls.h>
#include <gtest/gtest.h>

#include <cstdint>
#include <string>
#include <vector>

using charls_test_helpers::encode_decode_roundtrip_c;
using charls_test_helpers::make_gray8_gradient;
using charls_test_helpers::read_file_bytes;


namespace {

// Path where the grader uploads test fixture data. The tulips reference file is
// shipped alongside this file under tests/data/ and uploaded to /tests/data/.
constexpr const char* kTulipsPath =
    "/tests/data/tulips-gray-8bit-512-512-hp-encoder.jls";

// Bit-exact expected decode of the tulips stream: the 262144 raw grayscale
// pixels (the payload of the canonical tulips-gray-8bit-512-512 reference
// image), shipped under tests/data/ and uploaded to /tests/data/. Any
// ISO/IEC 14495-1 conformant decoder must reproduce exactly these bytes.
constexpr const char* kTulipsReferencePixelsPath =
    "/tests/data/tulips-gray-8bit-512-512.raw";

// Load and sanity-check the fixture. Returns an empty vector on failure so the
// test can EXPECT_FALSE(empty).
std::vector<uint8_t> load_tulips_or_fail() {
    auto data = read_file_bytes(kTulipsPath);
    if (data.empty()) {
        ADD_FAILURE() << "failed to open tulips fixture at " << kTulipsPath;
    }
    return data;
}

}  // namespace


TEST(DecodeReference, TulipsHeaderReportsCorrectFrameInfo) {
    // Decode header only. The tulips reference file is a 512 x 512 8-bit
    // grayscale image encoded losslessly by the HP reference encoder.
    const auto encoded = load_tulips_or_fail();
    ASSERT_FALSE(encoded.empty());

    charls_jpegls_decoder* dec = charls_jpegls_decoder_create();
    ASSERT_NE(dec, nullptr);

    ASSERT_EQ(charls_jpegls_decoder_set_source_buffer(dec, encoded.data(), encoded.size()),
              CHARLS_JPEGLS_ERRC_SUCCESS);
    ASSERT_EQ(charls_jpegls_decoder_read_header(dec), CHARLS_JPEGLS_ERRC_SUCCESS);

    charls_frame_info fi{};
    ASSERT_EQ(charls_jpegls_decoder_get_frame_info(dec, &fi), CHARLS_JPEGLS_ERRC_SUCCESS);
    EXPECT_EQ(fi.width, 512u);
    EXPECT_EQ(fi.height, 512u);
    EXPECT_EQ(fi.bits_per_sample, 8);
    EXPECT_EQ(fi.component_count, 1);

    charls_jpegls_decoder_destroy(dec);
}


TEST(DecodeReference, TulipsHeaderReportsLosslessNoneInterleave) {
    // A single-component grayscale stream is encoded with interleave_mode::none
    // and NEAR = 0 (lossless). Verify the decoder reads those back.
    const auto encoded = load_tulips_or_fail();
    ASSERT_FALSE(encoded.empty());

    charls_jpegls_decoder* dec = charls_jpegls_decoder_create();
    ASSERT_NE(dec, nullptr);

    ASSERT_EQ(charls_jpegls_decoder_set_source_buffer(dec, encoded.data(), encoded.size()),
              CHARLS_JPEGLS_ERRC_SUCCESS);
    ASSERT_EQ(charls_jpegls_decoder_read_header(dec), CHARLS_JPEGLS_ERRC_SUCCESS);

    charls_interleave_mode ilv;
    ASSERT_EQ(charls_jpegls_decoder_get_interleave_mode(dec, &ilv), CHARLS_JPEGLS_ERRC_SUCCESS);
    EXPECT_EQ(ilv, CHARLS_INTERLEAVE_MODE_NONE);

    int32_t near = -1;
    ASSERT_EQ(charls_jpegls_decoder_get_near_lossless(dec, 0, &near), CHARLS_JPEGLS_ERRC_SUCCESS);
    EXPECT_EQ(near, 0);

    charls_jpegls_decoder_destroy(dec);
}


TEST(DecodeReference, TulipsDecodesToExpectedSize) {
    // 512 x 512 x 1 component x 1 byte-per-sample = 262144 bytes uncompressed.
    // The decoder must (a) report that as its destination_size and (b) decode
    // into a buffer of that size without any error return.
    const auto encoded = load_tulips_or_fail();
    ASSERT_FALSE(encoded.empty());

    charls_jpegls_decoder* dec = charls_jpegls_decoder_create();
    ASSERT_NE(dec, nullptr);
    ASSERT_EQ(charls_jpegls_decoder_set_source_buffer(dec, encoded.data(), encoded.size()),
              CHARLS_JPEGLS_ERRC_SUCCESS);
    ASSERT_EQ(charls_jpegls_decoder_read_header(dec), CHARLS_JPEGLS_ERRC_SUCCESS);

    size_t dest_size = 0;
    ASSERT_EQ(charls_jpegls_decoder_get_destination_size(dec, 0, &dest_size),
              CHARLS_JPEGLS_ERRC_SUCCESS);
    EXPECT_EQ(dest_size, 512u * 512u);  // 262144 bytes.

    std::vector<uint8_t> decoded(dest_size);
    EXPECT_EQ(charls_jpegls_decoder_decode_to_buffer(dec, decoded.data(), decoded.size(), 0),
              CHARLS_JPEGLS_ERRC_SUCCESS);

    // Cross-implementation conformance: the decoded pixels must bit-exactly match
    // the known reference image. Decoding is fully deterministic under ISO/IEC
    // 14495-1, so a self-consistent but non-conformant entropy/predictor/run-mode
    // implementation (one that round-trips only its OWN streams) is rejected here.
    const auto expected = read_file_bytes(kTulipsReferencePixelsPath);
    ASSERT_EQ(expected.size(), 512u * 512u)
        << "reference pixel file missing or wrong size at " << kTulipsReferencePixelsPath;
    ASSERT_EQ(decoded.size(), expected.size());
    for (size_t i = 0; i < expected.size(); ++i) {
        ASSERT_EQ(decoded[i], expected[i]) << "decoded pixel differs from reference at byte " << i;
    }

    charls_jpegls_decoder_destroy(dec);
}


TEST(DecodeReference, EncodedStreamDecodeIsDeterministic) {
    // Decode determinism, checked on a stream the library itself produced (so it
    // does not depend on ISO-exact decode of a foreign reference stream): encode
    // a synthetic image, then decode that stream twice through two independent
    // decoder instances and require byte-identical output. This guards against a
    // decoder that leaks mutable state across invocations. JPEG-LS decode is
    // fully deterministic, so the two passes must match exactly.
    const uint32_t W = 48, H = 32;
    const auto src = make_gray8_gradient(W, H);
    const charls_frame_info fi{W, H, 8, 1};

    // encode_decode_roundtrip_c returns the library's own encoded stream in
    // r.encoded and its first decode in r.decoded.
    const auto r = encode_decode_roundtrip_c(src, fi, CHARLS_INTERLEAVE_MODE_NONE, 0);
    ASSERT_FALSE(r.encoded.empty());
    ASSERT_FALSE(r.decoded.empty());

    // Second, independent decode of the exact same stream.
    charls_jpegls_decoder* dec = charls_jpegls_decoder_create();
    ASSERT_NE(dec, nullptr);
    ASSERT_EQ(charls_jpegls_decoder_set_source_buffer(dec, r.encoded.data(), r.encoded.size()),
              CHARLS_JPEGLS_ERRC_SUCCESS);
    ASSERT_EQ(charls_jpegls_decoder_read_header(dec), CHARLS_JPEGLS_ERRC_SUCCESS);

    size_t sz = 0;
    ASSERT_EQ(charls_jpegls_decoder_get_destination_size(dec, 0, &sz),
              CHARLS_JPEGLS_ERRC_SUCCESS);
    std::vector<uint8_t> pass2(sz);
    ASSERT_EQ(charls_jpegls_decoder_decode_to_buffer(dec, pass2.data(), pass2.size(), 0),
              CHARLS_JPEGLS_ERRC_SUCCESS);
    charls_jpegls_decoder_destroy(dec);

    ASSERT_EQ(r.decoded.size(), pass2.size());
    for (size_t i = 0; i < pass2.size(); ++i) {
        ASSERT_EQ(r.decoded[i], pass2[i]) << "differ at byte " << i;
    }
}
