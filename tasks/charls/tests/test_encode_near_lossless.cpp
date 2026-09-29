// Module: encode_near_lossless. Exercises near-lossless encoding at
// several NEAR values and verifies (a) the max-error bound holds on every
// decoded pixel, (b) the decoder reads back the same NEAR value.
//
// Tests:
//   EncodeNearLossless.NearBoundsErrorAtSeveralValues
//
// Portability rule: C API args use CHARLS_* C-macro constants (works for both
// alias-style and distinct-C-enum agent impls).

#include "charls_fixture.h"

#include <charls/charls.h>
#include <gtest/gtest.h>

#include <cstdint>
#include <cstdlib>
#include <vector>

using charls_test_helpers::encode_decode_roundtrip_c;
using charls_test_helpers::make_gray8_gradient;


namespace {

// Verify that every decoded pixel is within NEAR of the source pixel (8-bit
// grayscale scalar comparison).
void check_max_error_bound(const std::vector<uint8_t>& src,
                           const std::vector<uint8_t>& dec,
                           const int32_t near_lossless) {
    ASSERT_EQ(src.size(), dec.size());
    int32_t max_err = 0;
    for (size_t i = 0; i < src.size(); ++i) {
        const int32_t diff =
            std::abs(static_cast<int32_t>(src[i]) - static_cast<int32_t>(dec[i]));
        if (diff > max_err) {
            max_err = diff;
        }
        ASSERT_LE(diff, near_lossless)
            << "pixel " << i << ": src=" << static_cast<int>(src[i])
            << " dec=" << static_cast<int>(dec[i]) << " (NEAR=" << near_lossless << ")";
    }
    (void)max_err;
}

}  // namespace


TEST(EncodeNearLossless, NearBoundsErrorAtSeveralValues) {
    // For each of several NEAR values, encode a gradient and verify (a) the
    // decoder reads back the same NEAR value (the NEAR byte written into the
    // SOS scan header round-trips through get_near_lossless unchanged), and
    // (b) every decoded pixel is within NEAR of the source. Bundled across
    // NEAR ∈ {0, 1, 2, 5, 7, 10, 30} (0 == lossless, so the bound is exact) so
    // an agent with a broken quantizer that trips at any value fails one slot.
    const uint32_t W = 32, H = 32;
    const auto src = make_gray8_gradient(W, H);
    const charls_frame_info fi{W, H, 8, 1};

    for (const int32_t near : {0, 1, 2, 5, 7, 10, 30}) {
        const auto r = encode_decode_roundtrip_c(src, fi, CHARLS_INTERLEAVE_MODE_NONE, near);
        EXPECT_EQ(r.decoded_near_lossless, near) << "NEAR=" << near;
        check_max_error_bound(src, r.decoded, near);
    }
}
