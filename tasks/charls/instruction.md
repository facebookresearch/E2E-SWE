# CharLS - JPEG-LS lossless / near-lossless image codec

Your task is to build a C++17 shared library called **`libcharls`** that implements the JPEG-LS image compression standard (ISO/IEC 14495-1:1999, also published as ITU-T T.87). The library exposes a stable **C ABI** (so it can be called from C, C++, Python, .NET, JavaScript, and other language bindings) plus a header-only **C++ wrapper** that layers a native C++ interface on top of the C entry points.

---

## 1. Background: what JPEG-LS is

JPEG-LS is a low-complexity image compression standard for continuous-tone still images. It compresses a rectangular pixel grid of 8-bit or 16-bit samples (with 2 to 16 useful bits per sample) into a compact byte stream. It supports both **lossless** compression (the decoded pixels are bit-identical to the input) and **near-lossless** compression (each decoded pixel is within a bounded error `NEAR` of the input, chosen by the encoder).

The core algorithm is HP's **LOCO-I** (LOw COmplexity LOssless Image compression): for each pixel `x`, predict its value from three already-decoded neighbours `a` (west), `b` (north), and `c` (northwest) using an edge-detecting predictor; classify the local gradient context into one of 365 buckets by quantizing the three gradients `(d - b, b - c, c - a)`, where `d` is the north-east neighbour (this matches the `(D1, D2, D3)` triple in section 5); then encode the prediction residual with a Golomb-Rice code whose parameter is adaptively estimated from the running statistics of the current context. A separate "run mode" kicks in when a flat region is detected. Read ISO/IEC 14495-1 (freely available from ITU as T.87) for the full algorithm; you are expected to derive the encoder / decoder from the standard.

Multi-component (typically 3-channel RGB) images can be encoded either **planar** (each channel stored independently as its own scan), **line-interleaved** (a full line of each channel encoded in turn), or **sample-interleaved** (RGB triplets encoded together). An optional HP color transformation (HP1, HP2, or HP3) can be applied before encoding a 3-component image to improve compression ratio; these transforms are reversible and lossless.

The byte-stream format is JPEG-like: a Start-of-Image (SOI) marker `FF D8`, an optional SPIFF (Still Picture Interchange File Format) header segment (APP8, `FF E8`), a JPEG-LS Start-of-Frame (SOF55, `FF F7`) marker segment, one or more Scan-Data (SOS, `FF DA`) segments, and an End-of-Image (EOI) marker `FF D9`.

CharLS explicitly does NOT support: restart markers on encode (decode-only), sub-sampled scans, mapping tables (palette), the DNL height marker, point transform, or JPEG-LS Part 2 extensions.

---

## 2. Build contract

The build environment provides `g++`, `cmake`, and `make` at standard locations. Your `setup.sh` script (at the repo root) will be run to build and install the library. After `setup.sh` runs successfully, the following must be true:

- The shared library `libcharls.so` is installed at `/usr/local/lib/libcharls.so`.
- The public headers are installed at `/usr/local/include/charls/`:
  - `/usr/local/include/charls/charls.h` (umbrella header - includes all others)
  - `/usr/local/include/charls/charls_jpegls_encoder.h`
  - `/usr/local/include/charls/charls_jpegls_decoder.h`
  - `/usr/local/include/charls/public_types.h`
  - `/usr/local/include/charls/jpegls_error.h`
  - `/usr/local/include/charls/validate_spiff_header.h`
  - `/usr/local/include/charls/version.h`
  - `/usr/local/include/charls/api_abi.h`
  - `/usr/local/include/charls/annotations.h`
- `ldconfig` has been run so the dynamic linker resolves `-lcharls`.

Downstream consumers compile against the installed headers and link with `-lcharls` (no `-I` flags, no `-L` flags - only the standard `/usr/local` include and lib paths). The typical command line for a consumer of your library looks like:

```
g++ -std=c++17 client.cpp -lcharls -o client
```

Consumers use only the public headers listed above; they do not `#include` internal implementation headers.

---

## 3. Public API surface

Every function, struct, and enum below must be defined in the public headers and exported by `libcharls.so`. All names must match exactly - the C ABI is the primary contract and cannot be renamed.

### 3.1 Common preprocessor / annotation macros

The file `annotations.h` defines a small set of empty-or-attribute macros that the other public headers use to mark function parameters and return values. You may implement them as no-ops on non-MSVC compilers. Names used in the API declarations below:

- `CHARLS_API_IMPORT_EXPORT` - visibility / import/export marker for shared library entry points.
- `CHARLS_API_CALLING_CONVENTION` - calling convention marker (empty on GCC/Linux).
- `CHARLS_NOEXCEPT` - `noexcept` on C++, empty on C.
- `CHARLS_CHECK_RETURN` - `[[nodiscard]]` on C++17.
- `CHARLS_ATTRIBUTE`, `CHARLS_ATTRIBUTE_ACCESS` - GCC attributes; safe to define as empty.
- `CHARLS_IN`, `CHARLS_IN_OPT`, `CHARLS_IN_Z`, `CHARLS_IN_READS_BYTES(_)`, `CHARLS_OUT`, `CHARLS_OUT_OPT`, `CHARLS_OUT_WRITES_BYTES(_)`, `CHARLS_OUT_WRITES_Z(_)`, `CHARLS_RETURN_TYPE_SUCCESS(_)` - SAL-style parameter annotation macros; safe to define as empty.
- `CHARLS_FINAL`, `CHARLS_NO_DISCARD`, `CHARLS_C_VOID`, `CHARLS_DEPRECATED`, `CHARLS_CONSTEXPR`, `CHARLS_CONSTEXPR_INLINE`, `CHARLS_RET_MAY_BE_NULL` - other markers; empty is fine.

The consuming code is standard C++17 and does not rely on any macro's specific expansion.

### 3.2 Version (`version.h`)

Three preprocessor defines expose the compile-time version numbers:

```c
#define CHARLS_VERSION_MAJOR 2
#define CHARLS_VERSION_MINOR 4
#define CHARLS_VERSION_PATCH 4
```

Two C entry points expose the runtime version:

```c
const char* charls_get_version_string(void);
void charls_get_version_number(int32_t* major, int32_t* minor, int32_t* patch);
```

- `charls_get_version_string()` returns a pointer to a static null-terminated string in the semver form `"2.4.4"` (major.minor.patch). Never returns NULL.
- `charls_get_version_number(major, minor, patch)` writes the version components through the pointers. Any of the three pointers may be NULL, in which case that component is skipped.

C++ callers also see three `constexpr int32_t` constants in namespace `charls`: `version_major`, `version_minor`, `version_patch`, matching the macro values.

### 3.3 Error codes (`public_types.h` + `jpegls_error.h`)

Every operation returns a status code. The C-visible enum is `charls_jpegls_errc`; the C++ typed enum in `namespace charls` is `jpegls_errc` with the same integer values.

The following enumerators MUST exist with the exact integer values shown (consumers rely on these values being stable across releases):

| C constant | C++ enumerator | Value |
|---|---|---|
| `CHARLS_JPEGLS_ERRC_SUCCESS` | `jpegls_errc::success` | 0 |
| `CHARLS_JPEGLS_ERRC_INVALID_ARGUMENT` | `jpegls_errc::invalid_argument` | 1 |
| `CHARLS_JPEGLS_ERRC_DESTINATION_BUFFER_TOO_SMALL` | `jpegls_errc::destination_buffer_too_small` | 3 |
| `CHARLS_JPEGLS_ERRC_SOURCE_BUFFER_TOO_SMALL` | `jpegls_errc::source_buffer_too_small` | 4 |
| `CHARLS_JPEGLS_ERRC_INVALID_ENCODED_DATA` | `jpegls_errc::invalid_encoded_data` | 5 |
| `CHARLS_JPEGLS_ERRC_INVALID_OPERATION` | `jpegls_errc::invalid_operation` | 7 |
| `CHARLS_JPEGLS_ERRC_UNKNOWN_JPEG_MARKER_FOUND` | `jpegls_errc::unknown_jpeg_marker_found` | 11 |
| `CHARLS_JPEGLS_ERRC_JPEG_MARKER_START_BYTE_NOT_FOUND` | `jpegls_errc::jpeg_marker_start_byte_not_found` | 12 |
| `CHARLS_JPEGLS_ERRC_NOT_ENOUGH_MEMORY` | `jpegls_errc::not_enough_memory` | 13 |
| `CHARLS_JPEGLS_ERRC_START_OF_IMAGE_MARKER_NOT_FOUND` | `jpegls_errc::start_of_image_marker_not_found` | 15 |
| `CHARLS_JPEGLS_ERRC_UNEXPECTED_MARKER_FOUND` | `jpegls_errc::unexpected_marker_found` | 16 |
| `CHARLS_JPEGLS_ERRC_INVALID_MARKER_SEGMENT_SIZE` | `jpegls_errc::invalid_marker_segment_size` | 17 |
| `CHARLS_JPEGLS_ERRC_INVALID_SPIFF_HEADER` | `jpegls_errc::invalid_spiff_header` | 29 |
| `CHARLS_JPEGLS_ERRC_INVALID_ARGUMENT_WIDTH` | `jpegls_errc::invalid_argument_width` | 100 |
| `CHARLS_JPEGLS_ERRC_INVALID_ARGUMENT_HEIGHT` | `jpegls_errc::invalid_argument_height` | 101 |
| `CHARLS_JPEGLS_ERRC_INVALID_ARGUMENT_COMPONENT_COUNT` | `jpegls_errc::invalid_argument_component_count` | 102 |
| `CHARLS_JPEGLS_ERRC_INVALID_ARGUMENT_BITS_PER_SAMPLE` | `jpegls_errc::invalid_argument_bits_per_sample` | 103 |
| `CHARLS_JPEGLS_ERRC_INVALID_ARGUMENT_INTERLEAVE_MODE` | `jpegls_errc::invalid_argument_interleave_mode` | 104 |
| `CHARLS_JPEGLS_ERRC_INVALID_ARGUMENT_NEAR_LOSSLESS` | `jpegls_errc::invalid_argument_near_lossless` | 105 |
| `CHARLS_JPEGLS_ERRC_INVALID_ARGUMENT_SIZE` | `jpegls_errc::invalid_argument_size` | 110 |
| `CHARLS_JPEGLS_ERRC_INVALID_ARGUMENT_COLOR_TRANSFORMATION` | `jpegls_errc::invalid_argument_color_transformation` | 111 |
| `CHARLS_JPEGLS_ERRC_INVALID_ARGUMENT_STRIDE` | `jpegls_errc::invalid_argument_stride` | 112 |
| `CHARLS_JPEGLS_ERRC_INVALID_PARAMETER_WIDTH` | `jpegls_errc::invalid_parameter_width` | 200 |
| `CHARLS_JPEGLS_ERRC_INVALID_PARAMETER_JPEGLS_PRESET_PARAMETERS` | `jpegls_errc::invalid_parameter_jpegls_preset_parameters` | 206 |

Additional enumerators may be present in the full ISO C ABI (the numeric ranges `1..29`, `100..113`, `200..206` are reserved for stream errors, argument errors, and stream-parameter errors respectively). An implementation MAY define extra codes within those ranges to name specific internal failure modes; callers treat any non-zero value as failure. The gaps in the value column above (e.g. 2, 6, 8-10, 14, 18-28, 106-109) are those reserved slots.

The C++ enum in `namespace charls` is declared:

```cpp
namespace charls {
enum class jpegls_errc { /* enumerators as above */ };
}
```

The C header aliases the same identifiers via `enum charls_jpegls_errc { ... }` at file scope, with `typedef` for C compatibility.

**Error semantics groups** (for your reference; the numeric ranges are stable):
- `0`: success.
- `1..29`: general operation / stream errors.
- `100..113`: invalid argument passed to a setter or public entry (the caller made a mistake).
- `200..206`: the encoded stream itself contains an invalid parameter value (the source data is bad).

`jpegls_error.h` additionally provides:

```c
const char* charls_get_error_message(charls_jpegls_errc error_value);
```

Returns a pointer to a static human-readable ASCII description of the error code. Never returns NULL, even for unknown values (return a sensible default such as `""` or `"unknown"` in that case).

For C++, `jpegls_error.h` also provides:
- `namespace charls { const std::error_category& jpegls_category() noexcept; }` - returns the singleton error category. The category's `name()` returns a stable non-empty identifier string (any stable identifier such as `"charls::jpegls"` is fine).
- `namespace charls { std::error_code make_error_code(jpegls_errc) noexcept; }` - constructs a `std::error_code` from a `jpegls_errc`.
- `namespace charls { class jpegls_error final : public std::system_error { ... }; }` - the exception type the C++ wrapper throws on error.
- `template<> struct std::is_error_code_enum<charls::jpegls_errc> : std::true_type {};` - specialization that lets `jpegls_errc` participate in `std::error_code` construction.

The C entry point `charls_get_jpegls_category` returns the same category pointer (used internally by the C++ inline wrapper).

### 3.4 Other enums (`public_types.h`)

```c
enum charls_interleave_mode {
    CHARLS_INTERLEAVE_MODE_NONE   = 0,   /* planar (RRR...GGG...BBB) */
    CHARLS_INTERLEAVE_MODE_LINE   = 1,   /* line interleaved */
    CHARLS_INTERLEAVE_MODE_SAMPLE = 2    /* pixel interleaved (RGBRGB) */
};

enum charls_encoding_options {
    CHARLS_ENCODING_OPTIONS_NONE                        = 0,
    CHARLS_ENCODING_OPTIONS_EVEN_DESTINATION_SIZE       = 1,
    CHARLS_ENCODING_OPTIONS_INCLUDE_VERSION_NUMBER      = 2,
    CHARLS_ENCODING_OPTIONS_INCLUDE_PC_PARAMETERS_JAI   = 4
};

enum charls_color_transformation {
    CHARLS_COLOR_TRANSFORMATION_NONE = 0,
    CHARLS_COLOR_TRANSFORMATION_HP1  = 1,
    CHARLS_COLOR_TRANSFORMATION_HP2  = 2,
    CHARLS_COLOR_TRANSFORMATION_HP3  = 3
};
```

Corresponding C++ scoped enums in `namespace charls`: `interleave_mode`, `encoding_options`, `color_transformation`, with lower-case member names (`none`, `line`, `sample`, `hp1`, `hp2`, `hp3`, etc.). Values match the C constants exactly. `encoding_options` supports bitwise OR / OR-assign so a caller can combine flags.

SPIFF-related enums (also in `public_types.h`). The enum definitions are per ISO/IEC 10918-3 Annex F; the essential values used by `write_standard_spiff_header` and returned via `read_spiff_header` are:

```c
enum charls_spiff_profile_id {
    CHARLS_SPIFF_PROFILE_ID_NONE = 0
    /* Additional profile-id values per ISO/IEC 10918-3 F.2.1 are also permitted. */
};

enum charls_spiff_color_space {
    CHARLS_SPIFF_COLOR_SPACE_GRAYSCALE = 8
    /* Additional color-space values per ISO/IEC 10918-3 F.2.1 (BI_LEVEL_BLACK=0,
     * YCBCR_*, RGB=10, CMY=11, CMYK=12, YCCK=13, CIE_LAB=14, BI_LEVEL_WHITE=15,
     * PHOTO_YCC=9, NONE=2) are also permitted. */
};

enum charls_spiff_compression_type {
    CHARLS_SPIFF_COMPRESSION_TYPE_JPEG_LS = 6
    /* Additional compression-type values per ISO/IEC 10918-3 F.2.1 (UNCOMPRESSED=0,
     * MODIFIED_HUFFMAN=1, MODIFIED_READ=2, MODIFIED_MODIFIED_READ=3, JBIG=4, JPEG=5)
     * are also permitted. `write_standard_spiff_header` always emits JPEG_LS. */
};

enum charls_spiff_resolution_units {
    CHARLS_SPIFF_RESOLUTION_UNITS_ASPECT_RATIO          = 0,
    CHARLS_SPIFF_RESOLUTION_UNITS_DOTS_PER_INCH         = 1,
    CHARLS_SPIFF_RESOLUTION_UNITS_DOTS_PER_CENTIMETER   = 2
};
```

Corresponding C++ scoped enums `charls::spiff_profile_id`, `charls::spiff_color_space`, `charls::spiff_compression_type`, `charls::spiff_resolution_units` (with lower-case members, e.g. `charls::spiff_color_space::grayscale`). Values match the C constants.

### 3.5 Structs (`public_types.h`)

```c
struct charls_frame_info {
    uint32_t width;             /* [1, 65535] on encode, [1, 100000] loosely allowed */
    uint32_t height;            /* [1, 65535] on encode */
    int32_t  bits_per_sample;   /* [2, 16] */
    int32_t  component_count;   /* [1, 255] */
};

struct charls_jpegls_pc_parameters {
    int32_t maximum_sample_value;   /* upper bound for sample values */
    int32_t threshold1;             /* T1 quantization threshold */
    int32_t threshold2;             /* T2 quantization threshold */
    int32_t threshold3;             /* T3 quantization threshold */
    int32_t reset_value;            /* counter reset threshold */
};

struct charls_spiff_header {
    charls_spiff_profile_id     profile_id;
    int32_t                     component_count;
    uint32_t                    height;
    uint32_t                    width;
    charls_spiff_color_space    color_space;
    int32_t                     bits_per_sample;
    charls_spiff_compression_type compression_type;
    charls_spiff_resolution_units resolution_units;
    uint32_t                    vertical_resolution;
    uint32_t                    horizontal_resolution;
};
```

For C++, these structs must be aliased inside `namespace charls`:

```cpp
namespace charls {
    using spiff_header        = charls_spiff_header;
    using frame_info          = charls_frame_info;
    using jpegls_pc_parameters = charls_jpegls_pc_parameters;
}
```

The struct layouts are required to satisfy:
- `sizeof(charls::spiff_header) == 40`
- `sizeof(charls::frame_info) == 16`
- `sizeof(charls::jpegls_pc_parameters) == 20`

(These are asserted with `static_assert` in the public header.)

### 3.6 Encoder C API (`charls_jpegls_encoder.h`)

An opaque handle:

```c
typedef struct charls_jpegls_encoder charls_jpegls_encoder;
```

Every C entry point returns `charls_jpegls_errc` (except the create/destroy pair). The function set:

```c
charls_jpegls_encoder* charls_jpegls_encoder_create(void);
void                   charls_jpegls_encoder_destroy(const charls_jpegls_encoder* encoder);

charls_jpegls_errc charls_jpegls_encoder_set_frame_info(
    charls_jpegls_encoder* encoder,
    const charls_frame_info* frame_info);

charls_jpegls_errc charls_jpegls_encoder_set_near_lossless(
    charls_jpegls_encoder* encoder,
    int32_t near_lossless);

charls_jpegls_errc charls_jpegls_encoder_set_encoding_options(
    charls_jpegls_encoder* encoder,
    charls_encoding_options encoding_options);

charls_jpegls_errc charls_jpegls_encoder_set_interleave_mode(
    charls_jpegls_encoder* encoder,
    charls_interleave_mode interleave_mode);

charls_jpegls_errc charls_jpegls_encoder_set_preset_coding_parameters(
    charls_jpegls_encoder* encoder,
    const charls_jpegls_pc_parameters* preset_coding_parameters);

charls_jpegls_errc charls_jpegls_encoder_set_color_transformation(
    charls_jpegls_encoder* encoder,
    charls_color_transformation color_transformation);

charls_jpegls_errc charls_jpegls_encoder_get_estimated_destination_size(
    const charls_jpegls_encoder* encoder,
    size_t* size_in_bytes);

charls_jpegls_errc charls_jpegls_encoder_set_destination_buffer(
    charls_jpegls_encoder* encoder,
    void* destination_buffer,
    size_t destination_size_bytes);

charls_jpegls_errc charls_jpegls_encoder_write_standard_spiff_header(
    charls_jpegls_encoder* encoder,
    charls_spiff_color_space color_space,
    charls_spiff_resolution_units resolution_units,
    uint32_t vertical_resolution,
    uint32_t horizontal_resolution);

charls_jpegls_errc charls_jpegls_encoder_write_spiff_header(
    charls_jpegls_encoder* encoder,
    const charls_spiff_header* spiff_header);

charls_jpegls_errc charls_jpegls_encoder_write_spiff_entry(
    charls_jpegls_encoder* encoder,
    uint32_t entry_tag,
    const void* entry_data,
    size_t entry_data_size_bytes);

charls_jpegls_errc charls_jpegls_encoder_write_spiff_end_of_directory_entry(
    charls_jpegls_encoder* encoder);

charls_jpegls_errc charls_jpegls_encoder_write_comment(
    charls_jpegls_encoder* encoder,
    const void* comment,
    size_t comment_size_bytes);

charls_jpegls_errc charls_jpegls_encoder_write_application_data(
    charls_jpegls_encoder* encoder,
    int32_t application_data_id,
    const void* application_data,
    size_t application_data_size_bytes);

charls_jpegls_errc charls_jpegls_encoder_encode_from_buffer(
    charls_jpegls_encoder* encoder,
    const void* source_buffer,
    size_t source_size_bytes,
    uint32_t stride);

charls_jpegls_errc charls_jpegls_encoder_get_bytes_written(
    const charls_jpegls_encoder* encoder,
    size_t* bytes_written);

charls_jpegls_errc charls_jpegls_encoder_rewind(charls_jpegls_encoder* encoder);
```

**Semantic contracts:**

- `..._create()` returns a heap-allocated opaque encoder, or NULL if allocation fails.
- `..._destroy(NULL)` is a no-op.
- `set_frame_info` validates the struct: width and height in `[1, 65535]`, bits_per_sample in `[2, 16]`, component_count in `[1, 255]`. Return `invalid_argument_width` / `invalid_argument_height` / `invalid_argument_bits_per_sample` / `invalid_argument_component_count` respectively for out-of-range values. `success` otherwise.
- `set_near_lossless` validates `near_lossless` in `[0, 255]`. Return `invalid_argument_near_lossless` otherwise. `success` for 0 (lossless, the default).
- `set_encoding_options` validates that only known flag bits are set. Return a suitable `invalid_argument` code if any unknown bit is set. Default value is `include_pc_parameters_jai` (i.e. that option is applied when the caller does not explicitly configure encoding options).
- `set_interleave_mode` validates value in `[0, 2]`. Return `invalid_argument_interleave_mode` otherwise. Additional cross-validation with component_count may be deferred to `encode_from_buffer`.
- `set_preset_coding_parameters` validates the pc_parameters against the current frame_info's bits_per_sample: `maximum_sample_value` must be in `[1, (2^bits_per_sample) - 1]`, threshold values and reset_value must satisfy the constraints from ISO/IEC 14495-1 C.2.4.1.1 Table C.1. Return a suitable `invalid_argument` code otherwise.
- `set_color_transformation` validates value in `[0, 3]`. Return `invalid_argument_color_transformation` otherwise. Additional cross-validation (color transforms require component_count == 3) may be deferred to `encode_from_buffer`.
- `get_estimated_destination_size` returns a size (in bytes) that is guaranteed to fit the eventual encoded output for the currently-configured frame_info, near_lossless, and interleave_mode, before any SPIFF header or extra segments. The returned value is a conservative upper bound, not necessarily the exact encoded size. Callable after `set_frame_info` succeeds; returns `invalid_operation` otherwise.
- `set_destination_buffer` records the caller-owned output buffer. Callable at any time; the buffer must remain valid until encoding completes.
- `write_standard_spiff_header` emits SOI + a SPIFF APP8 segment based on the current frame_info plus the given `color_space` / `resolution_units` / `vertical_resolution` / `horizontal_resolution`. The remaining SPIFF fields (profile_id, component_count, height, width, bits_per_sample) are filled from `frame_info_`; `compression_type` is set to `jpeg_ls`. Callable after `set_frame_info` and `set_destination_buffer` succeed. Must be called before `encode_from_buffer`. Returns `invalid_operation` if called out of order.
- `write_spiff_header` emits SOI + a caller-supplied SPIFF APP8 segment. Similar ordering constraints to `write_standard_spiff_header`.
- `write_spiff_entry` emits an APP8 directory-entry segment. Callable between `write_spiff_header` (or `write_standard_spiff_header`) and `encode_from_buffer`. `entry_data_size_bytes` must fit in the APP8 segment length; return `invalid_argument_size` if `entry_data_size_bytes` exceeds the segment size limit (65528 bytes).
- `write_spiff_end_of_directory_entry` emits the SPIFF end-of-directory APP8 marker. The encoder normally emits this automatically before writing the SOF segment, but this entry point is public so a caller can wrap an existing JPEG-LS byte stream.
- `write_comment` writes an APP-agnostic JPEG comment (COM) segment (`FF FE`). Must be called before `encode_from_buffer`. `comment_size_bytes` must be `<= 65533`.
- `write_application_data` writes an APPn segment (`FF E0 + id`) where `application_data_id` is in `[0, 15]`. Return `invalid_argument` otherwise. `application_data_size_bytes` must be `<= 65533`.
- `encode_from_buffer` encodes the pixel data from `source_buffer` into the previously-configured destination buffer. `stride` may be 0, in which case the encoder computes the natural per-line byte count from frame_info (`width * bits_per_sample / 8` for planar / line-interleaved, `width * component_count * bytes_per_sample` for sample-interleaved, adjusted for 16-bit samples). If the destination buffer is too small return `destination_buffer_too_small`. If the source buffer size disagrees with the frame_info return `invalid_argument_size`. `source_size_bytes` is validated: it must be `>= stride * height` (or the equivalent for stride == 0).
- In the uncompressed pixel buffers — the `source_buffer` read by `encode_from_buffer` and the buffer filled by `decode_to_buffer` — a sample with `bits_per_sample > 8` occupies two bytes in native host (little-endian) order. The big-endian rule of section 4 applies only to JPEG marker-segment fields, never to these buffers.
- `get_bytes_written` returns the total bytes written to the destination buffer since the encoder was created or last rewound. Callable at any time.
- `rewind` resets the write position to the start of the destination buffer so a new encode can reuse the same output buffer. Does not release the destination pointer, does not reset frame_info / interleave_mode / near_lossless / preset_coding_parameters / color_transformation / encoding_options.

Getters called with NULL out-pointers return `invalid_argument`.

### 3.7 Decoder C API (`charls_jpegls_decoder.h`)

An opaque handle:

```c
typedef struct charls_jpegls_decoder charls_jpegls_decoder;
```

Function set:

```c
charls_jpegls_decoder* charls_jpegls_decoder_create(void);
void                   charls_jpegls_decoder_destroy(const charls_jpegls_decoder* decoder);

charls_jpegls_errc charls_jpegls_decoder_set_source_buffer(
    charls_jpegls_decoder* decoder,
    const void* source_buffer,
    size_t source_size_bytes);

charls_jpegls_errc charls_jpegls_decoder_read_spiff_header(
    charls_jpegls_decoder* decoder,
    charls_spiff_header* spiff_header,
    int32_t* header_found);

charls_jpegls_errc charls_jpegls_decoder_read_header(charls_jpegls_decoder* decoder);

charls_jpegls_errc charls_jpegls_decoder_get_frame_info(
    const charls_jpegls_decoder* decoder,
    charls_frame_info* frame_info);

charls_jpegls_errc charls_jpegls_decoder_get_near_lossless(
    const charls_jpegls_decoder* decoder,
    int32_t component,
    int32_t* near_lossless);

charls_jpegls_errc charls_jpegls_decoder_get_interleave_mode(
    const charls_jpegls_decoder* decoder,
    charls_interleave_mode* interleave_mode);

charls_jpegls_errc charls_jpegls_decoder_get_preset_coding_parameters(
    const charls_jpegls_decoder* decoder,
    int32_t reserved,
    charls_jpegls_pc_parameters* preset_coding_parameters);

charls_jpegls_errc charls_jpegls_decoder_get_color_transformation(
    const charls_jpegls_decoder* decoder,
    charls_color_transformation* color_transformation);

charls_jpegls_errc charls_jpegls_decoder_get_destination_size(
    const charls_jpegls_decoder* decoder,
    uint32_t stride,
    size_t* destination_size_bytes);

charls_jpegls_errc charls_jpegls_decoder_decode_to_buffer(
    charls_jpegls_decoder* decoder,
    void* destination_buffer,
    size_t destination_size_bytes,
    uint32_t stride);

charls_jpegls_errc charls_jpegls_decoder_at_comment(
    charls_jpegls_decoder* decoder,
    charls_at_comment_handler handler,
    void* user_context);

charls_jpegls_errc charls_jpegls_decoder_at_application_data(
    charls_jpegls_decoder* decoder,
    charls_at_application_data_handler handler,
    void* user_context);
```

Where:

```c
typedef int32_t (*charls_at_comment_handler)(
    const void* data, size_t size, void* user_context);
typedef int32_t (*charls_at_application_data_handler)(
    int32_t application_data_id, const void* data, size_t size, void* user_context);
```

**Semantic contracts:**

- `..._create()` returns a heap-allocated opaque decoder, or NULL if allocation fails.
- `..._destroy(NULL)` is a no-op.
- `set_source_buffer` records the caller-owned encoded byte stream. The buffer must remain valid until decoding completes.
- `read_spiff_header` scans the byte stream for a SPIFF APP8 segment right after SOI. On success sets `*header_found` to 1 and populates `*spiff_header` from the stream; on absence sets `*header_found` to 0 (return `success`). Returns `invalid_spiff_header` if a SPIFF-looking segment is present but malformed. Must be called before `read_header` if the caller wants SPIFF info.
- `read_header` scans the byte stream from the current position (either the start or just after the SPIFF segment) to the Start-of-Scan (SOS) marker, populating internal state with frame_info, near_lossless, interleave_mode, preset_coding_parameters, and color_transformation. Returns `start_of_image_marker_not_found` if the stream doesn't start with SOI (accounting for a preceding SPIFF header). Returns `jpeg_marker_start_byte_not_found`, `unknown_jpeg_marker_found`, `encoding_not_supported`, `invalid_marker_segment_size`, etc. per the actual failure.
- `get_frame_info`, `get_near_lossless`, `get_interleave_mode`, `get_preset_coding_parameters`, `get_color_transformation` may only be called after `read_header` returns `success`. Return `invalid_operation` if called earlier.
- `get_destination_size` returns the required byte size for the decoded pixel buffer. `stride == 0` means "use the natural per-line byte count computed from frame_info and interleave_mode". `stride > 0` must be `>= natural_line_size`; return `invalid_argument_stride` otherwise.
- `decode_to_buffer` decodes into the destination buffer. `destination_size_bytes` must be `>= get_destination_size(stride)`. Return `destination_buffer_too_small` otherwise. `stride == 0` means "use natural per-line byte count".
- `at_comment` installs a callback invoked once per COM segment encountered during `read_header` (and also during `decode_to_buffer` if COM segments appear inline). Passing NULL uninstalls the callback. If the callback returns non-zero, decoding aborts with a suitable non-success `jpegls_errc`. Return `invalid_argument` if the decoder pointer is NULL.
- `at_application_data` is the APPn analogue of `at_comment`. `application_data_id` in the callback ranges over `[0, 15]`.

### 3.8 SPIFF validation (`validate_spiff_header.h`)

```c
charls_jpegls_errc charls_validate_spiff_header(
    const charls_spiff_header* spiff_header,
    const charls_frame_info* frame_info);
```

Returns `success` if the SPIFF header is internally consistent AND matches the frame_info in width, height, bits_per_sample, and component_count. Returns `invalid_spiff_header` otherwise. Both pointers must be non-NULL; return `invalid_argument` if either is NULL. This entry point is used by the decoder's C++ wrapper `read_header()` to validate a SPIFF header that was previously read by `read_spiff_header()`.

### 3.9 C++ wrapper classes (`charls_jpegls_encoder.h`, `charls_jpegls_decoder.h`)

Two header-only classes in `namespace charls` sit on top of the C ABI and translate error codes into `charls::jpegls_error` exceptions:

```cpp
namespace charls {

class jpegls_encoder final {
public:
    jpegls_encoder();
    ~jpegls_encoder() = default;

    // Configuration - returns *this for chaining.
    jpegls_encoder& frame_info(const frame_info& info);
    jpegls_encoder& near_lossless(int32_t value);
    jpegls_encoder& interleave_mode(interleave_mode mode);
    jpegls_encoder& encoding_options(encoding_options options);
    jpegls_encoder& preset_coding_parameters(const jpegls_pc_parameters& params);
    jpegls_encoder& color_transformation(color_transformation transform);

    // Sizing / destination.
    size_t estimated_destination_size() const;

    jpegls_encoder& destination(void* buffer, size_t size);
    template<typename Container> jpegls_encoder& destination(Container& c);

    // SPIFF.
    jpegls_encoder& write_standard_spiff_header(
        spiff_color_space color_space,
        spiff_resolution_units resolution_units = spiff_resolution_units::aspect_ratio,
        uint32_t vertical_resolution = 1,
        uint32_t horizontal_resolution = 1);
    jpegls_encoder& write_spiff_header(const spiff_header& header);
    template<typename IntType>
    jpegls_encoder& write_spiff_entry(IntType tag, const void* data, size_t size);
    jpegls_encoder& write_spiff_end_of_directory_entry();

    // Extra segments.
    jpegls_encoder& write_comment(const char* comment);              // null-terminated
    jpegls_encoder& write_comment(const void* comment, size_t size);
    jpegls_encoder& write_application_data(int32_t id, const void* data, size_t size);

    // Encode + status.
    size_t encode(const void* buffer, size_t size, uint32_t stride = 0) const;
    template<typename Container> size_t encode(const Container& c, uint32_t stride = 0) const;
    size_t bytes_written() const;
    void rewind() const;

    // One-shot convenience.
    template<typename Container>
    static Container encode(const Container& source,
                            const charls::frame_info& frame,
                            interleave_mode mode = interleave_mode::none,
                            encoding_options options = encoding_options::none);
};

class jpegls_decoder final {
public:
    jpegls_decoder();
    template<typename Container>
    jpegls_decoder(const Container& source, bool parse_header);
    jpegls_decoder(const void* buffer, size_t size, bool parse_header = true);

    // Source input.
    jpegls_decoder& source(const void* buffer, size_t size);
    template<typename Container> jpegls_decoder& source(const Container& c);

    // Header parsing.
    bool read_spiff_header();
    bool read_spiff_header(std::error_code& ec) noexcept;
    jpegls_decoder& read_header();
    jpegls_decoder& read_header(std::error_code& ec) noexcept;

    // Read-only accessors (post-read_header).
    bool spiff_header_has_value() const noexcept;
    const spiff_header& spiff_header() const& noexcept;
    charls::spiff_header spiff_header() const&& noexcept;
    const charls::frame_info& frame_info() const& noexcept;
    charls::frame_info frame_info() const&& noexcept;
    int32_t near_lossless(int32_t component = 0) const;
    charls::interleave_mode interleave_mode() const;
    jpegls_pc_parameters preset_coding_parameters() const;
    charls::color_transformation color_transformation() const;

    // Sizing / decode.
    size_t destination_size(uint32_t stride = 0) const;
    void decode(void* buffer, size_t size, uint32_t stride = 0) const;
    template<typename Container> void decode(Container& c, uint32_t stride = 0) const;
    template<typename Container> Container decode(uint32_t stride = 0) const;

    // Callbacks.
    jpegls_decoder& at_comment(std::function<void(const void*, size_t)> handler);
    jpegls_decoder& at_application_data(
        std::function<void(int32_t, const void*, size_t)> handler);

    // One-shot convenience.
    template<typename SourceContainer, typename DestContainer>
    static std::pair<charls::frame_info, charls::interleave_mode>
    decode(const SourceContainer& source, DestContainer& destination,
           size_t maximum_size_in_bytes = size_t{7680} * 4320 * 3);
};

}  // namespace charls
```

Both classes use `std::unique_ptr<charls_jpegls_..., void(*)(const charls_jpegls_...*)>` internally to own the C handle. All member functions that would return a C error code convert `!= success` into a thrown `charls::jpegls_error`. The `noexcept std::error_code&`-taking overloads return the error via the out parameter instead.

---

## 4. Wire format

The encoder must emit a byte stream that a conformant JPEG-LS decoder (upstream CharLS, or any other ISO/IEC 14495-1-conformant decoder) can decode back into the original pixels. The stream structure for a typical encode is:

```
[SOI]                             FF D8
[optional APP8 SPIFF header]      FF E8 <len> "SPIFF\0" 02 00 <fields...>
[optional APP8 SPIFF EOD]         FF E8 00 08 00 00 00 01 FF D8
[optional COM segments]           FF FE <len> <bytes>
[optional APPn segments]          FF E0..EF <len> <bytes>
[optional LSE preset params seg]  FF F8 <len> 01 <maxval:u16> <t1:u16> <t2:u16> <t3:u16> <reset:u16>
[SOF55]                           FF F7 <len> <P> <Y:u16> <X:u16> <Nf> [Ci Hi/Vi Tqi]*Nf
[optional COM segments]           FF FE <len> <bytes>
[SOS + scan bytes]                FF DA <len> ... encoded entropy bytes ...
[EOI]                             FF D9
```

All multi-byte integer fields in JPEG segments are big-endian. Segment lengths include the two length bytes themselves.

### 4.1 SPIFF header segment (APP8)

Follows ISO/IEC 10918-3 Annex F. The `write_spiff_header_segment` layout at the byte level, starting right after the SOI marker:

| Offset from SPIFF APP8 start | Size | Field |
|---|---|---|
| 0 | 1 | `0xFF` (marker start) |
| 1 | 1 | `0xE8` (APP8) |
| 2 | 2 | segment length (big-endian, `= 32`) |
| 4 | 6 | identifier `"SPIFF\0"` |
| 10 | 1 | major revision (`2`) |
| 11 | 1 | minor revision (`0`) |
| 12 | 1 | profile_id |
| 13 | 1 | component_count |
| 14 | 4 | height (big-endian) |
| 18 | 4 | width (big-endian) |
| 22 | 1 | color_space |
| 23 | 1 | bits_per_sample |
| 24 | 1 | compression_type |
| 25 | 1 | resolution_units |
| 26 | 4 | vertical_resolution (big-endian) |
| 30 | 4 | horizontal_resolution (big-endian) |

The whole SPIFF APP8 segment is 34 bytes on the wire (2 bytes marker + 2 bytes length + 30 bytes payload starting with "SPIFF\0").

The end-of-directory entry (emitted automatically before the SOF segment when a SPIFF header was written) is an APP8 segment with 6 data bytes: `00 00 00 01 FF D8`.

### 4.2 SOF55 (Start of Frame, JPEG-LS)

| Field | Size | Meaning |
|---|---|---|
| Marker | 2 | `FF F7` |
| Segment length | 2 | `= 8 + component_count * 3` (big-endian) |
| P | 1 | sample precision (bits_per_sample, `[2, 16]`) |
| Y | 2 | height (big-endian, or 0 for over-size) |
| X | 2 | width (big-endian, or 0 for over-size) |
| Nf | 1 | component_count |
| Per component: Ci, HV, Tqi | 3 | component id (1-indexed), packed 0x11 (horizontal + vertical sampling factor = 1), quantization table selector (must be 0 for JPEG-LS) |

### 4.3 SOS (Start of Scan)

| Field | Size | Meaning |
|---|---|---|
| Marker | 2 | `FF DA` |
| Segment length | 2 | `= 6 + 2 * Ns` |
| Ns | 1 | number of components in this scan |
| Per scan component: Ci, mapping table selector | 2 | component id (1-indexed) and 0 (no table) |
| NEAR | 1 | near-lossless parameter |
| ILV | 1 | interleave mode (0, 1, or 2) |
| point transform | 1 | must be 0 |

### 4.4 LSE (JPEG-LS extension marker)

Used to encode non-default preset coding parameters. Only emitted when the caller explicitly configured non-default values via `set_preset_coding_parameters`.

| Field | Size | Meaning |
|---|---|---|
| Marker | 2 | `FF F8` |
| Segment length | 2 | `= 13` |
| type | 1 | `= 1` (preset coding parameters) |
| MAXVAL | 2 | maximum_sample_value (big-endian) |
| T1 | 2 | threshold1 (big-endian) |
| T2 | 2 | threshold2 (big-endian) |
| T3 | 2 | threshold3 (big-endian) |
| RESET | 2 | reset_value (big-endian) |

### 4.5 Encoded scan bytes

The scan bytes carry the entropy-coded prediction residuals. The encoder uses the LOCO-I predictor, adaptive Golomb-Rice coding, and the stuffing rule of section 4.6 (which keeps encoded data distinguishable from marker starts). The details are in ISO/IEC 14495-1 clauses A.2 through A.7 for the regular mode and A.7 for run mode. The observable contract at the public API level is: an encode-then-decode round-trip in lossless mode reproduces the original pixels bit-for-bit; in near-lossless mode each reconstructed pixel is within `NEAR` of the original; the frame_info, interleave_mode, near_lossless, and color_transformation read back from the decoder match the values used to encode. The exact byte sequences in the entropy-coded region are not part of the public contract - different conforming encoders can produce different scan bytes for the same input.

### 4.6 Stuffing rule in the entropy-coded scan

Within the entropy-coded scan, JPEG-LS uses the bit-stuffing rule of ISO/IEC 14495-1 A.1, not the JPEG (T.81) `FF 00` byte-stuffing rule: whenever a byte equal to `0xFF` is written, a single `0` bit is inserted at the most-significant bit position of the next byte, so that byte carries only 7 bits of coded data and always has bit 7 clear. Decoding reverses this: the byte following a `0xFF` supplies 7 bits of coded data, and a `0xFF` whose following byte has bit 7 set is the start of a marker rather than coded data. The unstuffing obligation applies to every conformant stream your decoder is handed (section 7), not only to streams your own encoder produced.

---

## 5. LOCO-I algorithm sketch

For each pixel `x` being encoded (in raster order, per component / per scan depending on interleave mode):

1. **Gather context:** read the three already-encoded neighbours `Ra` (west), `Rb` (north), `Rc` (northwest). At the top row `Rb = Rc = 0`; at the leftmost column `Ra = Rb-of-previous-line` (with special-case handling for the top-left corner).

2. **Compute the local gradient triple** `(D1, D2, D3) = (Rd - Rb, Rb - Rc, Rc - Ra)` where `Rd` is the north-east neighbour.

3. **Quantize each gradient** into `{-4, -3, -2, -1, 0, +1, +2, +3, +4}` using the thresholds `T1`, `T2`, `T3` (default values depend on bits-per-sample and maximum-sample-value; see ISO/IEC 14495-1 Annex A.3.3 for the formula). The default thresholds for 8-bit lossless are `T1=3, T2=7, T3=21, RESET=64, MAXVAL=255`. Extended to any `MAXVAL`, the standard defines them in table C.1.

4. **If all three quantized gradients are zero**, switch to **run mode**. Read consecutive pixels along the current row that equal `Ra` (within the near-lossless tolerance `NEAR`); encode the run length using a modified Golomb-Rice code and the special run-mode escape when the run ends at a pixel with a different value.

5. **Otherwise (regular mode):**
   - Determine the sign and canonical form of the context. Two contexts with symmetric gradients (e.g. `(1, 0, -1)` and `(-1, 0, 1)`) share the same state but predictions are sign-swapped. This gives 365 canonical contexts for the regular mode.
   - **Fix the predictor** using edge detection: `Px = min(Ra, Rb) if Rc >= max(Ra, Rb); max(Ra, Rb) if Rc <= min(Ra, Rb); Ra + Rb - Rc otherwise`.
   - **Correction:** apply the context's running `C[q]` correction value to `Px`, then clip into `[0, MAXVAL]`. The context correction is updated after each pixel using the running average of past errors.
   - **Compute the residual** `Errval = x - Px`. Reduce to the range `[-(MAXVAL+1)/2, MAXVAL/2]` (modulo-MAXVAL folding).
   - **Estimate the Golomb parameter `k`** for the current context from the running sums `A[q]` and `N[q]`. `k = ceil(log2(A[q] / N[q]))` (implemented as a loop over bit positions to keep it branch-friendly).
   - **Map the signed residual to an unsigned magnitude** using the standard folding: `MErrval = 2*Errval` if `Errval >= 0`, else `-2*Errval - 1`. Emit the Golomb-Rice code with parameter `k`.
   - **Update the context state:** `A[q] += |Errval|; B[q] += Errval; N[q] += 1;` and when `N[q] == RESET`, halve `A[q]`, `B[q]`, `N[q]`. The context correction value `C[q]` is updated based on the accumulator sign.

6. **After the last pixel**, flush any remaining bits in the entropy encoder to byte alignment, apply the section 4.6 stuffing rule, and emit the EOI marker.

The decoder reverses the process, reading the same context sequence and adaptive Golomb parameter, decoding the residual, and reconstructing each pixel.

**Near-lossless mode (`NEAR > 0`):** quantize the residual by `NEAR`, so the reconstructed pixel is within `NEAR` of the original. The regular-mode predictor works on the quantized residual; the run-mode threshold uses `NEAR` when deciding whether the next pixel is close enough to continue the run.

**HP color transformations:** applied losslessly before encoding for 3-component images to decorrelate the channels and improve the compression ratio. HP1 is `(R-G, G, B-G)` and HP2 is `(R-G, G, B-(R+G)/2)`; HP3 is a further decorrelating transform in the same family. The transformed triple is stored as 8-bit samples in place of the original, and the selected transform id is recorded in the JPEG-LS stream (via a private APP marker) so the decoder can undo it. The exact per-channel arithmetic of each transform is left to the implementation; the binding contract is only that (a) every transform is **losslessly reversible** — encoding a 3-component image with the transform and decoding it back through the library reproduces the original RGB pixels bit-for-bit (section 4.5) — and (b) the decoder reports the applied transform via `get_color_transformation`. Because the transformed channels are only 8-bit, a transform is valid only if the original triple is exactly recoverable from those stored 8-bit channels. Color transforms may only be applied when component_count == 3 and bits_per_sample <= 8; return a suitable `not_supported` / `invalid_argument_color_transformation` code for 16-bit images or if component_count != 3.

---

## 6. Usage example

A typical encode-then-decode round-trip using the C++ wrapper:

```cpp
#include <charls/charls.h>
#include <vector>

std::vector<uint8_t> encode_gray_8bit_lossless(
    const std::vector<uint8_t>& pixels, uint32_t width, uint32_t height)
{
    charls::jpegls_encoder encoder;
    encoder.frame_info({width, height, 8, 1})
           .interleave_mode(charls::interleave_mode::none);

    std::vector<uint8_t> encoded(encoder.estimated_destination_size());
    encoder.destination(encoded);

    const size_t bytes_written = encoder.encode(pixels);
    encoded.resize(bytes_written);
    return encoded;
}

std::vector<uint8_t> decode_gray_8bit(const std::vector<uint8_t>& encoded)
{
    charls::jpegls_decoder decoder;
    decoder.source(encoded).read_header();

    std::vector<uint8_t> decoded(decoder.destination_size());
    decoder.decode(decoded);
    return decoded;
}
```

Using only the C ABI:

```c
#include <charls/charls.h>
#include <stdlib.h>

/* Encode an 8-bit grayscale image and write to *out_bytes. */
charls_jpegls_errc encode_gray_8bit(
    const uint8_t* pixels, uint32_t width, uint32_t height,
    uint8_t** out_bytes, size_t* out_size)
{
    charls_jpegls_encoder* enc = charls_jpegls_encoder_create();
    if (!enc) return CHARLS_JPEGLS_ERRC_NOT_ENOUGH_MEMORY;

    charls_frame_info fi = {width, height, 8, 1};
    charls_jpegls_errc rc = charls_jpegls_encoder_set_frame_info(enc, &fi);
    if (rc != CHARLS_JPEGLS_ERRC_SUCCESS) { charls_jpegls_encoder_destroy(enc); return rc; }

    size_t estimated = 0;
    charls_jpegls_encoder_get_estimated_destination_size(enc, &estimated);
    uint8_t* buffer = (uint8_t*)malloc(estimated);
    charls_jpegls_encoder_set_destination_buffer(enc, buffer, estimated);

    rc = charls_jpegls_encoder_encode_from_buffer(
        enc, pixels, (size_t)width * height, 0);
    if (rc != CHARLS_JPEGLS_ERRC_SUCCESS) {
        free(buffer); charls_jpegls_encoder_destroy(enc); return rc;
    }

    charls_jpegls_encoder_get_bytes_written(enc, out_size);
    *out_bytes = buffer;
    charls_jpegls_encoder_destroy(enc);
    return CHARLS_JPEGLS_ERRC_SUCCESS;
}
```

---

## 7. Conformance expectation

The ISO/IEC 14495-1 standard is deterministic on the decoder side: any conformant JPEG-LS decoder, when given a well-formed .jls stream, must produce the exact same pixel array as any other conformant decoder. Interoperability with existing JPEG-LS files (produced by the HP reference implementation, upstream CharLS, etc.) is a first-order correctness property: your decoder must correctly read frames encoded by any conformant encoder, and your encoder must produce frames that any conformant decoder can read.

---

## 8. Constraints on valid inputs

Enforce the following at the C ABI boundary:

- Encoder `frame_info`: `width in [1, 65535]`, `height in [1, 65535]`, `bits_per_sample in [2, 16]`, `component_count in [1, 255]`.
- `near_lossless in [0, 255]`. `near_lossless == 0` is lossless.
- `interleave_mode`: `none` (0), `line` (1), `sample` (2). `line` and `sample` require `component_count > 1`.
- `color_transformation`: `none` (0), `hp1`, `hp2`, `hp3` (1..3). `hp1/hp2/hp3` require `component_count == 3` AND `bits_per_sample <= 8`.
- `encoding_options`: valid combinations of `even_destination_size`, `include_version_number`, `include_pc_parameters_jai`.
- `preset_coding_parameters`: `maximum_sample_value in [1, (2^bits_per_sample) - 1]`. Threshold and reset values per ISO/IEC 14495-1 C.2.4.1.1 Table C.1.
- `application_data_id in [0, 15]`.
- `write_comment` / `write_application_data`: max data size `65533` bytes.
- `write_spiff_entry`: max entry data size `65528` bytes.

Return the corresponding `invalid_argument_*` code (see the table in section 3.3) when a caller passes an out-of-range value.

---

## 9. Threading and lifetime notes

- Encoder / decoder instances are not thread-safe. A single encoder / decoder should be used from one thread at a time. Multiple encoders / decoders in different threads are fine.
- The source / destination buffers passed to `set_source_buffer` / `set_destination_buffer` must remain valid until decoding / encoding completes. The library does not copy them.
- Callback functions installed via `at_comment` / `at_application_data` must be safe to call from the decoder thread.
- The C entry points are `noexcept` - all errors are returned as `charls_jpegls_errc`. The C++ wrapper translates non-success codes into `charls::jpegls_error` exceptions except on the explicitly `noexcept` overloads that take `std::error_code&`.

---

Everything the library exposes is documented above. Anything not documented is unspecified; you may implement it as you see fit or omit it entirely.
