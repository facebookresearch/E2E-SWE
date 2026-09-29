// Module: version. Exercises the compile-time version macros and the runtime
// charls_get_version_string / charls_get_version_number entry points.
//
// Tests:
//   Version.ReportsVersionAndAcceptsNullOutPointers

#include "charls_fixture.h"

#include <charls/charls.h>
#include <gtest/gtest.h>

#include <cstring>
#include <string>


// The version identity (semver "2.4.4" / macros 2.4.4) is inherently a
// compile-time constant, so it occupies a single slot; the only non-trivial
// contract exercised here is charls_get_version_number tolerating NULL for any
// subset of its three out-pointers.
TEST(Version, ReportsVersionAndAcceptsNullOutPointers) {
    // Runtime version string, semver form "major.minor.patch".
    const char* v = charls_get_version_string();
    ASSERT_NE(v, nullptr);
    // Must start with "2.4.4" (may have a trailing "-<prerelease>" suffix but
    // for v2.4.4 tag there is none).
    const std::string s{v};
    EXPECT_EQ(s.substr(0, 5), "2.4.4") << "got: " << s;

    // Compile-time version identity: the macros and the mirrored C++
    // namespace-scoped constexpr constants must all be 2.4.4.
    EXPECT_EQ(CHARLS_VERSION_MAJOR, 2);
    EXPECT_EQ(CHARLS_VERSION_MINOR, 4);
    EXPECT_EQ(CHARLS_VERSION_PATCH, 4);
    EXPECT_EQ(charls::version_major, 2);
    EXPECT_EQ(charls::version_minor, 4);
    EXPECT_EQ(charls::version_patch, 4);

    // Full population: all three pointers non-NULL.
    int32_t major = -1, minor = -1, patch = -1;
    charls_get_version_number(&major, &minor, &patch);
    EXPECT_EQ(major, 2);
    EXPECT_EQ(minor, 4);
    EXPECT_EQ(patch, 4);

    // Any subset of pointers may be NULL. Verify the API tolerates each combo
    // (must not crash, must populate only the non-NULL ones).
    major = -1;
    charls_get_version_number(&major, nullptr, nullptr);
    EXPECT_EQ(major, 2);

    minor = -1;
    charls_get_version_number(nullptr, &minor, nullptr);
    EXPECT_EQ(minor, 4);

    patch = -1;
    charls_get_version_number(nullptr, nullptr, &patch);
    EXPECT_EQ(patch, 4);

    // All-NULL is legal too.
    charls_get_version_number(nullptr, nullptr, nullptr);
}
