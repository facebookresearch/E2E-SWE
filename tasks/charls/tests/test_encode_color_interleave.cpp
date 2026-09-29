// Module: encode_color_interleave. Exercises 3-component (RGB) lossless
// encoding at each of the three interleave modes (NONE, LINE, SAMPLE) and
// verifies the round-trip pixel identity plus the decoder's interleave-mode
// read-back.
//
// Tests:
//   ColorInterleave.RgbSampleInterleavedRoundtrip
//   ColorInterleave.RgbLineInterleavedRoundtrip
//   ColorInterleave.RgbPlanarNoneRoundtrip
//   ColorInterleave.EncoderReportsSameFrameInfoBackOn3Component
//
// Portability rule: C API args + comparisons against `charls_*` types use the
// CHARLS_* C-macro constants (works for both alias-style and distinct-C-enum
// agent impls).

#include "charls_fixture.h"

#include <charls/charls.h>
#include <gtest/gtest.h>

#include <cstdint>
#include <vector>

using charls_test_helpers::encode_decode_roundtrip_c;
using charls_test_helpers::make_rgb8_gradient;
using charls_test_helpers::triplet_to_planar_rgb8;


TEST(ColorInterleave, RgbSampleInterleavedRoundtrip) {
    // sample-interleaved: pixel-interleaved RGB triples (RGBRGB...).
    const uint32_t W = 24, H = 24;
    const auto src = make_rgb8_gradient(W, H);
    const charls_frame_info fi{W, H, 8, 3};

    const auto r = encode_decode_roundtrip_c(src, fi, CHARLS_INTERLEAVE_MODE_SAMPLE, 0);
    EXPECT_EQ(r.decoded_interleave_mode, CHARLS_INTERLEAVE_MODE_SAMPLE);
    EXPECT_EQ(r.decoded_frame_info.component_count, 3);
    ASSERT_EQ(r.decoded.size(), src.size());
    for (size_t i = 0; i < src.size(); ++i) {
        ASSERT_EQ(r.decoded[i], src[i]) << "differ at byte " << i;
    }
}


TEST(ColorInterleave, RgbLineInterleavedRoundtrip) {
    // line-interleaved: the encoder still consumes pixel-interleaved input
    // (RGBRGB...) but internally reorganizes on a per-line basis.
    const uint32_t W = 24, H = 24;
    const auto src = make_rgb8_gradient(W, H);
    const charls_frame_info fi{W, H, 8, 3};

    const auto r = encode_decode_roundtrip_c(src, fi, CHARLS_INTERLEAVE_MODE_LINE, 0);
    EXPECT_EQ(r.decoded_interleave_mode, CHARLS_INTERLEAVE_MODE_LINE);
    ASSERT_EQ(r.decoded.size(), src.size());
    for (size_t i = 0; i < src.size(); ++i) {
        ASSERT_EQ(r.decoded[i], src[i]) << "differ at byte " << i;
    }
}


TEST(ColorInterleave, RgbPlanarNoneRoundtrip) {
    // interleave_mode::none == planar layout: input is RRR...GGG...BBB.
    // Encoder emits 3 separate scans; decoder produces planar output too.
    const uint32_t W = 24, H = 24;
    const auto pixel_rgb = make_rgb8_gradient(W, H);
    const auto planar = triplet_to_planar_rgb8(pixel_rgb, W, H);
    const charls_frame_info fi{W, H, 8, 3};

    const auto r = encode_decode_roundtrip_c(planar, fi, CHARLS_INTERLEAVE_MODE_NONE, 0);
    EXPECT_EQ(r.decoded_interleave_mode, CHARLS_INTERLEAVE_MODE_NONE);
    ASSERT_EQ(r.decoded.size(), planar.size());
    for (size_t i = 0; i < planar.size(); ++i) {
        ASSERT_EQ(r.decoded[i], planar[i]) << "differ at byte " << i;
    }
}


TEST(ColorInterleave, EncoderReportsSameFrameInfoBackOn3Component) {
    // The SOF55 marker must record width, height, bits_per_sample, and
    // component_count exactly; decoder.get_frame_info reads them back.
    // Asymmetric dimensions (W != H) so a width/height swap in the SOF55
    // encode/parse path is caught (square-dimension round-trips cannot).
    const uint32_t W = 40, H = 24;
    const auto src = make_rgb8_gradient(W, H);
    const charls_frame_info fi{W, H, 8, 3};

    const auto r = encode_decode_roundtrip_c(src, fi, CHARLS_INTERLEAVE_MODE_SAMPLE, 0);
    EXPECT_EQ(r.decoded_frame_info.width, W);
    EXPECT_EQ(r.decoded_frame_info.height, H);
    EXPECT_EQ(r.decoded_frame_info.bits_per_sample, 8);
    EXPECT_EQ(r.decoded_frame_info.component_count, 3);
}
