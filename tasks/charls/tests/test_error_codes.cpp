// Module: error_codes. Exercises the charls_jpegls_errc enum values, the
// charls_get_error_message entry point, and the C++ std::error_code integration
// (jpegls_category, make_error_code, is_error_code_enum, jpegls_error).
//
// Tests:
//   ErrorCodes.KeyNumericValuesAreStable
//   ErrorCodes.GetErrorMessageReturnsNonEmptyForKnownCodes
//   ErrorCodes.CppCategoryHasStableName
//   ErrorCodes.MakeErrorCodeRoundTrips
//   ErrorCodes.JpeglsErrorCarriesTheCode
//
// Portability rule: values passed to the C API (charls_get_error_message takes
// `charls_jpegls_errc`) use the CHARLS_* C-macro constants; values passed to
// the C++ API (charls::make_error_code, charls::jpegls_error) use the scoped
// C++ enum (charls::jpegls_errc::foo).

#include "charls_fixture.h"

#include <charls/charls.h>
#include <gtest/gtest.h>

#include <cstring>
#include <system_error>


TEST(ErrorCodes, KeyNumericValuesAreStable) {
    // The success constant must be integer 0 so callers can idiom
    // `if (charls_jpegls_encoder_set_...) { /* error */ }` cleanly.
    EXPECT_EQ(static_cast<int>(CHARLS_JPEGLS_ERRC_SUCCESS), 0);
    EXPECT_EQ(static_cast<int>(charls::jpegls_errc::success), 0);

    // A representative sample from each of the three numeric ranges (stream
    // errors [1..29], argument-error [100..113], stream-parameter-error
    // [200..206]). Wire protocol / language bindings depend on these staying
    // stable across releases.
    EXPECT_EQ(static_cast<int>(CHARLS_JPEGLS_ERRC_INVALID_ARGUMENT), 1);
    EXPECT_EQ(static_cast<int>(CHARLS_JPEGLS_ERRC_DESTINATION_BUFFER_TOO_SMALL), 3);
    EXPECT_EQ(static_cast<int>(CHARLS_JPEGLS_ERRC_INVALID_ENCODED_DATA), 5);
    EXPECT_EQ(static_cast<int>(CHARLS_JPEGLS_ERRC_INVALID_OPERATION), 7);
    EXPECT_EQ(static_cast<int>(CHARLS_JPEGLS_ERRC_UNKNOWN_JPEG_MARKER_FOUND), 11);
    EXPECT_EQ(static_cast<int>(CHARLS_JPEGLS_ERRC_JPEG_MARKER_START_BYTE_NOT_FOUND), 12);
    EXPECT_EQ(static_cast<int>(CHARLS_JPEGLS_ERRC_INVALID_SPIFF_HEADER), 29);
    EXPECT_EQ(static_cast<int>(CHARLS_JPEGLS_ERRC_INVALID_ARGUMENT_WIDTH), 100);
    EXPECT_EQ(static_cast<int>(CHARLS_JPEGLS_ERRC_INVALID_ARGUMENT_NEAR_LOSSLESS), 105);
    EXPECT_EQ(static_cast<int>(CHARLS_JPEGLS_ERRC_INVALID_ARGUMENT_COLOR_TRANSFORMATION), 111);
    EXPECT_EQ(static_cast<int>(CHARLS_JPEGLS_ERRC_INVALID_ARGUMENT_STRIDE), 112);
    EXPECT_EQ(static_cast<int>(CHARLS_JPEGLS_ERRC_INVALID_PARAMETER_WIDTH), 200);
    EXPECT_EQ(static_cast<int>(CHARLS_JPEGLS_ERRC_INVALID_PARAMETER_JPEGLS_PRESET_PARAMETERS), 206);

    // C++ enum values must line up with C constants.
    EXPECT_EQ(static_cast<int>(charls::jpegls_errc::invalid_argument), 1);
    EXPECT_EQ(static_cast<int>(charls::jpegls_errc::destination_buffer_too_small), 3);
    EXPECT_EQ(static_cast<int>(charls::jpegls_errc::invalid_argument_width), 100);
    EXPECT_EQ(static_cast<int>(charls::jpegls_errc::invalid_parameter_width), 200);
}


TEST(ErrorCodes, GetErrorMessageReturnsNonEmptyForKnownCodes) {
    // For non-success codes, each documented code must map to a non-empty
    // message AND distinct codes must return distinct message strings (an
    // implementation returning the literal "x" for every code passes non-empty
    // but is not useful; distinctness catches that).
    const char* msg_success = charls_get_error_message(CHARLS_JPEGLS_ERRC_SUCCESS);
    ASSERT_NE(msg_success, nullptr);

    const char* msg_bad_width = charls_get_error_message(CHARLS_JPEGLS_ERRC_INVALID_ARGUMENT_WIDTH);
    ASSERT_NE(msg_bad_width, nullptr);
    EXPECT_GT(std::strlen(msg_bad_width), 0u);

    const char* msg_bad_bps = charls_get_error_message(CHARLS_JPEGLS_ERRC_INVALID_ARGUMENT_BITS_PER_SAMPLE);
    ASSERT_NE(msg_bad_bps, nullptr);
    EXPECT_GT(std::strlen(msg_bad_bps), 0u);

    const char* msg_bad_stream = charls_get_error_message(CHARLS_JPEGLS_ERRC_INVALID_ENCODED_DATA);
    ASSERT_NE(msg_bad_stream, nullptr);
    EXPECT_GT(std::strlen(msg_bad_stream), 0u);

    // Distinctness: distinct error codes MUST produce distinct message strings.
    // Also distinct from the SUCCESS message. A conformant implementation
    // returns a per-code human-readable description; a lookup-table that keys
    // on the error value trivially satisfies this.
    EXPECT_STRNE(msg_bad_width, msg_bad_bps)
        << "invalid_argument_width and invalid_argument_bits_per_sample must map to distinct messages";
    EXPECT_STRNE(msg_bad_width, msg_bad_stream)
        << "invalid_argument_width and invalid_encoded_data must map to distinct messages";
    EXPECT_STRNE(msg_bad_bps, msg_bad_stream)
        << "invalid_argument_bits_per_sample and invalid_encoded_data must map to distinct messages";
    EXPECT_STRNE(msg_bad_width, msg_success)
        << "invalid_argument_width and success must map to distinct messages";
}


TEST(ErrorCodes, CppCategoryHasStableName) {
    const std::error_category& cat = charls::jpegls_category();
    const char* name = cat.name();
    ASSERT_NE(name, nullptr);
    EXPECT_GT(std::strlen(name), 0u);

    // The name must identify this category as a charls/jpegls one (any
    // conformant impl includes "charls" or "jpegls" somewhere in the name --
    // this catches an impl that returns a generic name like "unknown" that
    // wouldn't disambiguate from other error categories in a user's system).
    const std::string s{name};
    EXPECT_TRUE(s.find("charls") != std::string::npos ||
                s.find("jpegls") != std::string::npos ||
                s.find("JPEG-LS") != std::string::npos ||
                s.find("CharLS") != std::string::npos)
        << "category name should identify itself as charls/jpegls; got: " << s;

    // Category singleton: repeated calls return the same object.
    const std::error_category& cat2 = charls::jpegls_category();
    EXPECT_EQ(&cat, &cat2);
}


TEST(ErrorCodes, MakeErrorCodeRoundTrips) {
    // make_error_code converts a jpegls_errc into a std::error_code whose value
    // matches the enum's integer value and whose category is jpegls_category.
    const std::error_code ec = charls::make_error_code(charls::jpegls_errc::invalid_argument_width);
    EXPECT_EQ(ec.value(), 100);
    EXPECT_EQ(&ec.category(), &charls::jpegls_category());

    // is_error_code_enum specialization: implicit conversion from enum to error_code.
    const std::error_code ec2 = charls::jpegls_errc::destination_buffer_too_small;
    EXPECT_EQ(ec2.value(), 3);
    EXPECT_EQ(&ec2.category(), &charls::jpegls_category());

    // Non-success error_code evaluates to true in bool context.
    EXPECT_TRUE(static_cast<bool>(ec2));

    // success error_code evaluates to false.
    const std::error_code ok = charls::jpegls_errc::success;
    EXPECT_FALSE(static_cast<bool>(ok));
}


TEST(ErrorCodes, JpeglsErrorCarriesTheCode) {
    // The exception type stores the error code and reports it via .code().
    try {
        throw charls::jpegls_error{charls::jpegls_errc::invalid_argument_bits_per_sample};
    } catch (const charls::jpegls_error& e) {
        EXPECT_EQ(e.code().value(), 103);
        EXPECT_EQ(&e.code().category(), &charls::jpegls_category());
    } catch (...) {
        FAIL() << "expected charls::jpegls_error, got a different exception";
    }
}
