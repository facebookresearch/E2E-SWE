// Shared test-side helpers for the charls gtest suite.
//
// Fairness rule: this fixture must not shadow public library types. All
// references to charls:: types below are either fully qualified or brought in
// via `using namespace charls;` inside the private helpers namespace so agents
// that place all public identifiers in `namespace charls` (canonical) and
// agents that expose them at global scope (fallback) both compile against
// this header.

#pragma once

#include <charls/charls.h>

#include <cstdint>
#include <cstring>
#include <fstream>
#include <string>
#include <vector>

// ----------------------------------------------------------------------------
// Enum-bridge shims. Agents may implement the public types header in one of
// two conforming styles:
//   (a) alias-style: `using charls_jpegls_errc = charls::jpegls_errc;` — the
//       C-facing name is an alias for the C++ scoped enum. The CHARLS_*
//       C-macro constants are then only defined in C compilation (guarded by
//       `#ifdef __cplusplus`).
//   (b) distinct-C-enum style (upstream layout): the C-facing name is a
//       separate `enum charls_jpegls_errc` with `CHARLS_*` enumerators, and a
//       separate `enum class charls::jpegls_errc` for C++. The two types
//       intentionally do not implicitly convert.
//
// The tests want to write portable code that works against both. We define
// each CHARLS_* constant as a preprocessor macro that expands to a
// `static_cast<charls_c_type>(::charls::cpp_type::value)` bridge:
//   - For (a): static_cast between identical types is a no-op — works.
//   - For (b): static_cast bridges the C++ scoped enum through int to the
//     C enum — works.
// `#ifndef` triggers when the agent's header did not define the constant as
// a macro. In style (b) the constants exist as enum enumerators, not macros,
// so our shim still overrides them; the resulting behaviour is identical for
// the read-only uses in the test suite (comparisons and C API argument
// forwarding).
// ----------------------------------------------------------------------------

#ifndef CHARLS_JPEGLS_ERRC_SUCCESS
#define CHARLS_JPEGLS_ERRC_SUCCESS \
    static_cast<charls_jpegls_errc>(::charls::jpegls_errc::success)
#define CHARLS_JPEGLS_ERRC_INVALID_ARGUMENT \
    static_cast<charls_jpegls_errc>(::charls::jpegls_errc::invalid_argument)
#define CHARLS_JPEGLS_ERRC_PARAMETER_VALUE_NOT_SUPPORTED \
    static_cast<charls_jpegls_errc>(::charls::jpegls_errc::parameter_value_not_supported)
#define CHARLS_JPEGLS_ERRC_DESTINATION_BUFFER_TOO_SMALL \
    static_cast<charls_jpegls_errc>(::charls::jpegls_errc::destination_buffer_too_small)
#define CHARLS_JPEGLS_ERRC_SOURCE_BUFFER_TOO_SMALL \
    static_cast<charls_jpegls_errc>(::charls::jpegls_errc::source_buffer_too_small)
#define CHARLS_JPEGLS_ERRC_INVALID_ENCODED_DATA \
    static_cast<charls_jpegls_errc>(::charls::jpegls_errc::invalid_encoded_data)
#define CHARLS_JPEGLS_ERRC_TOO_MUCH_ENCODED_DATA \
    static_cast<charls_jpegls_errc>(::charls::jpegls_errc::too_much_encoded_data)
#define CHARLS_JPEGLS_ERRC_INVALID_OPERATION \
    static_cast<charls_jpegls_errc>(::charls::jpegls_errc::invalid_operation)
#define CHARLS_JPEGLS_ERRC_BIT_DEPTH_FOR_TRANSFORM_NOT_SUPPORTED \
    static_cast<charls_jpegls_errc>(::charls::jpegls_errc::bit_depth_for_transform_not_supported)
#define CHARLS_JPEGLS_ERRC_COLOR_TRANSFORM_NOT_SUPPORTED \
    static_cast<charls_jpegls_errc>(::charls::jpegls_errc::color_transform_not_supported)
#define CHARLS_JPEGLS_ERRC_ENCODING_NOT_SUPPORTED \
    static_cast<charls_jpegls_errc>(::charls::jpegls_errc::encoding_not_supported)
#define CHARLS_JPEGLS_ERRC_UNKNOWN_JPEG_MARKER_FOUND \
    static_cast<charls_jpegls_errc>(::charls::jpegls_errc::unknown_jpeg_marker_found)
#define CHARLS_JPEGLS_ERRC_JPEG_MARKER_START_BYTE_NOT_FOUND \
    static_cast<charls_jpegls_errc>(::charls::jpegls_errc::jpeg_marker_start_byte_not_found)
#define CHARLS_JPEGLS_ERRC_NOT_ENOUGH_MEMORY \
    static_cast<charls_jpegls_errc>(::charls::jpegls_errc::not_enough_memory)
#define CHARLS_JPEGLS_ERRC_UNEXPECTED_FAILURE \
    static_cast<charls_jpegls_errc>(::charls::jpegls_errc::unexpected_failure)
#define CHARLS_JPEGLS_ERRC_START_OF_IMAGE_MARKER_NOT_FOUND \
    static_cast<charls_jpegls_errc>(::charls::jpegls_errc::start_of_image_marker_not_found)
#define CHARLS_JPEGLS_ERRC_UNEXPECTED_MARKER_FOUND \
    static_cast<charls_jpegls_errc>(::charls::jpegls_errc::unexpected_marker_found)
#define CHARLS_JPEGLS_ERRC_INVALID_MARKER_SEGMENT_SIZE \
    static_cast<charls_jpegls_errc>(::charls::jpegls_errc::invalid_marker_segment_size)
#define CHARLS_JPEGLS_ERRC_INVALID_SPIFF_HEADER \
    static_cast<charls_jpegls_errc>(::charls::jpegls_errc::invalid_spiff_header)
#define CHARLS_JPEGLS_ERRC_INVALID_ARGUMENT_WIDTH \
    static_cast<charls_jpegls_errc>(::charls::jpegls_errc::invalid_argument_width)
#define CHARLS_JPEGLS_ERRC_INVALID_ARGUMENT_HEIGHT \
    static_cast<charls_jpegls_errc>(::charls::jpegls_errc::invalid_argument_height)
#define CHARLS_JPEGLS_ERRC_INVALID_ARGUMENT_COMPONENT_COUNT \
    static_cast<charls_jpegls_errc>(::charls::jpegls_errc::invalid_argument_component_count)
#define CHARLS_JPEGLS_ERRC_INVALID_ARGUMENT_BITS_PER_SAMPLE \
    static_cast<charls_jpegls_errc>(::charls::jpegls_errc::invalid_argument_bits_per_sample)
#define CHARLS_JPEGLS_ERRC_INVALID_ARGUMENT_INTERLEAVE_MODE \
    static_cast<charls_jpegls_errc>(::charls::jpegls_errc::invalid_argument_interleave_mode)
#define CHARLS_JPEGLS_ERRC_INVALID_ARGUMENT_NEAR_LOSSLESS \
    static_cast<charls_jpegls_errc>(::charls::jpegls_errc::invalid_argument_near_lossless)
#define CHARLS_JPEGLS_ERRC_INVALID_ARGUMENT_COLOR_TRANSFORMATION \
    static_cast<charls_jpegls_errc>(::charls::jpegls_errc::invalid_argument_color_transformation)
#define CHARLS_JPEGLS_ERRC_INVALID_ARGUMENT_STRIDE \
    static_cast<charls_jpegls_errc>(::charls::jpegls_errc::invalid_argument_stride)
#define CHARLS_JPEGLS_ERRC_INVALID_ARGUMENT_SIZE \
    static_cast<charls_jpegls_errc>(::charls::jpegls_errc::invalid_argument_size)
#define CHARLS_JPEGLS_ERRC_INVALID_PARAMETER_WIDTH \
    static_cast<charls_jpegls_errc>(::charls::jpegls_errc::invalid_parameter_width)
#define CHARLS_JPEGLS_ERRC_INVALID_PARAMETER_JPEGLS_PRESET_PARAMETERS \
    static_cast<charls_jpegls_errc>(::charls::jpegls_errc::invalid_parameter_jpegls_preset_parameters)
#endif

#ifndef CHARLS_INTERLEAVE_MODE_NONE
#define CHARLS_INTERLEAVE_MODE_NONE \
    static_cast<charls_interleave_mode>(::charls::interleave_mode::none)
#define CHARLS_INTERLEAVE_MODE_LINE \
    static_cast<charls_interleave_mode>(::charls::interleave_mode::line)
#define CHARLS_INTERLEAVE_MODE_SAMPLE \
    static_cast<charls_interleave_mode>(::charls::interleave_mode::sample)
#endif

#ifndef CHARLS_COLOR_TRANSFORMATION_NONE
#define CHARLS_COLOR_TRANSFORMATION_NONE \
    static_cast<charls_color_transformation>(::charls::color_transformation::none)
#define CHARLS_COLOR_TRANSFORMATION_HP1 \
    static_cast<charls_color_transformation>(::charls::color_transformation::hp1)
#define CHARLS_COLOR_TRANSFORMATION_HP2 \
    static_cast<charls_color_transformation>(::charls::color_transformation::hp2)
#define CHARLS_COLOR_TRANSFORMATION_HP3 \
    static_cast<charls_color_transformation>(::charls::color_transformation::hp3)
#endif

#ifndef CHARLS_SPIFF_PROFILE_ID_NONE
#define CHARLS_SPIFF_PROFILE_ID_NONE \
    static_cast<charls_spiff_profile_id>(::charls::spiff_profile_id::none)
#endif

#ifndef CHARLS_SPIFF_COLOR_SPACE_GRAYSCALE
#define CHARLS_SPIFF_COLOR_SPACE_GRAYSCALE \
    static_cast<charls_spiff_color_space>(::charls::spiff_color_space::grayscale)
#endif

#ifndef CHARLS_SPIFF_COMPRESSION_TYPE_JPEG_LS
#define CHARLS_SPIFF_COMPRESSION_TYPE_JPEG_LS \
    static_cast<charls_spiff_compression_type>(::charls::spiff_compression_type::jpeg_ls)
#endif

#ifndef CHARLS_SPIFF_RESOLUTION_UNITS_ASPECT_RATIO
#define CHARLS_SPIFF_RESOLUTION_UNITS_ASPECT_RATIO \
    static_cast<charls_spiff_resolution_units>(::charls::spiff_resolution_units::aspect_ratio)
#define CHARLS_SPIFF_RESOLUTION_UNITS_DOTS_PER_INCH \
    static_cast<charls_spiff_resolution_units>(::charls::spiff_resolution_units::dots_per_inch)
#define CHARLS_SPIFF_RESOLUTION_UNITS_DOTS_PER_CENTIMETER \
    static_cast<charls_spiff_resolution_units>(::charls::spiff_resolution_units::dots_per_centimeter)
#endif


namespace charls_test_helpers {

using namespace charls;  // bridges both namespaced and global-scope agent styles.

// Build a small synthetic 8-bit grayscale image: value(x, y) = (x + y) % 256.
inline std::vector<uint8_t> make_gray8_gradient(const uint32_t width, const uint32_t height)
{
    std::vector<uint8_t> pixels(static_cast<size_t>(width) * height);
    for (uint32_t y = 0; y < height; ++y)
    {
        for (uint32_t x = 0; x < width; ++x)
        {
            pixels[static_cast<size_t>(y) * width + x] = static_cast<uint8_t>((x + y) & 0xFF);
        }
    }
    return pixels;
}


// Build a synthetic 16-bit grayscale image at a given bit depth. Values are
// bounded by (1 << bits_per_sample) - 1. Stored as little-endian pairs.
inline std::vector<uint8_t> make_gray16_gradient(const uint32_t width, const uint32_t height,
                                                 const int32_t bits_per_sample)
{
    const uint16_t max_value = static_cast<uint16_t>((1u << bits_per_sample) - 1u);
    std::vector<uint8_t> pixels(static_cast<size_t>(width) * height * 2);
    for (uint32_t y = 0; y < height; ++y)
    {
        for (uint32_t x = 0; x < width; ++x)
        {
            const uint16_t v = static_cast<uint16_t>(((x * 7 + y * 3) & 0xFFFF) & max_value);
            const size_t off = (static_cast<size_t>(y) * width + x) * 2;
            pixels[off + 0] = static_cast<uint8_t>(v & 0xFF);
            pixels[off + 1] = static_cast<uint8_t>((v >> 8) & 0xFF);
        }
    }
    return pixels;
}


// Build a small 8-bit RGB image stored as pixel-interleaved triplets (BGRBGRBGR
// layout unrelated -- we produce RGBRGB byte order and let the caller pick the
// charls_interleave_mode).
inline std::vector<uint8_t> make_rgb8_gradient(const uint32_t width, const uint32_t height)
{
    std::vector<uint8_t> pixels(static_cast<size_t>(width) * height * 3);
    for (uint32_t y = 0; y < height; ++y)
    {
        for (uint32_t x = 0; x < width; ++x)
        {
            const size_t off = (static_cast<size_t>(y) * width + x) * 3;
            pixels[off + 0] = static_cast<uint8_t>((x * 5) & 0xFF);           // R
            pixels[off + 1] = static_cast<uint8_t>((y * 3) & 0xFF);           // G
            pixels[off + 2] = static_cast<uint8_t>(((x + y) * 2) & 0xFF);     // B
        }
    }
    return pixels;
}


// Convert RGBRGBRGB (pixel-interleaved) into RRR...GGG...BBB (planar layout)
// so it can be encoded with interleave_mode::none for a 3-component image.
inline std::vector<uint8_t> triplet_to_planar_rgb8(const std::vector<uint8_t>& rgb,
                                                   const uint32_t width, const uint32_t height)
{
    std::vector<uint8_t> planar(rgb.size());
    const size_t plane_bytes = static_cast<size_t>(width) * height;
    for (size_t i = 0; i < plane_bytes; ++i)
    {
        planar[i]                    = rgb[i * 3 + 0];
        planar[i + plane_bytes]      = rgb[i * 3 + 1];
        planar[i + 2 * plane_bytes]  = rgb[i * 3 + 2];
    }
    return planar;
}


// Full round-trip: encode `source` with the given parameters, decode it back,
// return the decoded bytes plus the observed frame_info + interleave mode.
struct roundtrip_result
{
    std::vector<uint8_t> encoded;
    std::vector<uint8_t> decoded;
    charls_frame_info decoded_frame_info{};
    charls_interleave_mode decoded_interleave_mode{};
    int32_t decoded_near_lossless{};
};

inline roundtrip_result encode_decode_roundtrip_c(const std::vector<uint8_t>& source,
                                                  const charls_frame_info& frame,
                                                  const charls_interleave_mode interleave,
                                                  const int32_t near_lossless,
                                                  const uint32_t stride = 0)
{
    roundtrip_result r{};

    // Callers of this helper skip per-call return-code checks by design (the
    // helper is used from tests that verify the observable outputs). Capture
    // return values into a discarded local to suppress `[[nodiscard]]`
    // (-Wunused-result) warnings from the charls C API.
    [[maybe_unused]] charls_jpegls_errc _rc{};

    charls_jpegls_encoder* enc = charls_jpegls_encoder_create();
    _rc = charls_jpegls_encoder_set_frame_info(enc, &frame);
    _rc = charls_jpegls_encoder_set_interleave_mode(enc, interleave);
    _rc = charls_jpegls_encoder_set_near_lossless(enc, near_lossless);

    size_t est = 0;
    _rc = charls_jpegls_encoder_get_estimated_destination_size(enc, &est);
    r.encoded.resize(est);
    _rc = charls_jpegls_encoder_set_destination_buffer(enc, r.encoded.data(), r.encoded.size());
    _rc = charls_jpegls_encoder_encode_from_buffer(enc, source.data(), source.size(), stride);

    size_t bytes_written = 0;
    _rc = charls_jpegls_encoder_get_bytes_written(enc, &bytes_written);
    r.encoded.resize(bytes_written);
    charls_jpegls_encoder_destroy(enc);

    charls_jpegls_decoder* dec = charls_jpegls_decoder_create();
    _rc = charls_jpegls_decoder_set_source_buffer(dec, r.encoded.data(), r.encoded.size());
    _rc = charls_jpegls_decoder_read_header(dec);
    _rc = charls_jpegls_decoder_get_frame_info(dec, &r.decoded_frame_info);
    _rc = charls_jpegls_decoder_get_interleave_mode(dec, &r.decoded_interleave_mode);
    _rc = charls_jpegls_decoder_get_near_lossless(dec, 0, &r.decoded_near_lossless);

    size_t dest_size = 0;
    _rc = charls_jpegls_decoder_get_destination_size(dec, 0, &dest_size);
    r.decoded.resize(dest_size);
    _rc = charls_jpegls_decoder_decode_to_buffer(dec, r.decoded.data(), r.decoded.size(), 0);
    charls_jpegls_decoder_destroy(dec);

    return r;
}


// Read a file into a byte vector. Used to load fixture .jls files bundled under
// /tests/data/ by the grader.
inline std::vector<uint8_t> read_file_bytes(const std::string& path)
{
    std::ifstream input(path, std::ios::binary | std::ios::ate);
    if (!input.good())
    {
        return {};
    }
    const auto size = static_cast<size_t>(input.tellg());
    input.seekg(0, std::ios::beg);
    std::vector<uint8_t> data(size);
    if (size > 0)
    {
        input.read(reinterpret_cast<char*>(data.data()), static_cast<std::streamsize>(size));
    }
    return data;
}


// Read a big-endian uint16 from a byte buffer at offset `off`.
inline uint16_t read_uint16_be(const std::vector<uint8_t>& buf, const size_t off)
{
    return static_cast<uint16_t>((static_cast<uint16_t>(buf[off]) << 8) | buf[off + 1]);
}


// Read a big-endian uint32 from a byte buffer at offset `off`.
inline uint32_t read_uint32_be(const std::vector<uint8_t>& buf, const size_t off)
{
    return (static_cast<uint32_t>(buf[off]) << 24) | (static_cast<uint32_t>(buf[off + 1]) << 16) |
           (static_cast<uint32_t>(buf[off + 2]) << 8) | static_cast<uint32_t>(buf[off + 3]);
}

}  // namespace charls_test_helpers
