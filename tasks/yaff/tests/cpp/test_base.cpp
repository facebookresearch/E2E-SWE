// Wire-format primitives in yaff/base.h, exercised through a hand-built record rather than
// as isolated one-liners: values are written and read back, an offset is resolved to a
// sub-region, the default-xor encoding is shown self-inverse, and the checked-offset guards
// enforce their bounds.
#include "doctest.h"
#include <yaff/base.h>

#include <cstddef>
#include <cstdint>
#include <stdexcept>

TEST_CASE("wire primitives - a hand-built record reads back through base.h accessors") {
    // Lay out: [0..7] uint64 (xor-encoded vs default), [8..11] uint32, [12..15] Offset to a
    // sub-region at byte 32, [16..19] a null Offset, [32..39] the sub-region payload.
    std::byte buf[64] = {};
    yaff::WriteValue<uint64_t>(buf + 0, yaff::XorDef<uint64_t>(0x1122334455667788ULL, 0x00000000000000FFULL));
    yaff::WriteValue<uint32_t>(buf + 8, 0xCAFEBABEU);
    yaff::WriteValue<yaff::Offset>(buf + 12, 32);
    yaff::WriteValue<yaff::Offset>(buf + 16, 0);
    yaff::WriteValue<uint64_t>(buf + 32, 0x00ABCDEF00ABCDEFULL);

    // Scalar with default-xor decoding restores the original value.
    CHECK(yaff::XorDef<uint64_t>(yaff::ReadValue<uint64_t>(buf + 0), 0x00000000000000FFULL) ==
          0x1122334455667788ULL);
    // Plain scalar + advancing read.
    const void* next = nullptr;
    CHECK(yaff::ReadValue<uint32_t>(buf + 8, &next) == 0xCAFEBABEU);
    CHECK(next == static_cast<const void*>(buf + 12));

    // A non-zero offset resolves into the buffer; a zero offset falls back to the default.
    const auto* sub = yaff::ResolveOffset<uint64_t>(buf, yaff::ReadValue<yaff::Offset>(buf + 12));
    CHECK(yaff::ReadValue<uint64_t>(sub) == 0x00ABCDEF00ABCDEFULL);
    uint64_t fallback = 0x9999;
    CHECK(yaff::ResolveNullableOffset<uint64_t>(buf, yaff::ReadValue<yaff::Offset>(buf + 16), &fallback) == &fallback);
    CHECK(yaff::ResolveNullableOffset<uint64_t>(buf, 32, &fallback) == sub);

    // XorDef is self-inverse for integral and float payloads; IsEqual is type-aware.
    CHECK(yaff::XorDef<int32_t>(yaff::XorDef<int32_t>(0x1234, 0x00FF), 0x00FF) == 0x1234);
    const float enc = yaff::XorDef<float>(3.5f, 1.25f);
    CHECK(yaff::XorDef<float>(enc, 1.25f) == doctest::Approx(3.5f));
    CHECK(yaff::IsEqual<double>(2.0, 2.0));
    CHECK_FALSE(yaff::IsEqual<int32_t>(2, 3));
}

TEST_CASE("wire primitives - checked offsets enforce 31-bit and signed 32-bit bounds") {
    CHECK(yaff::ToCheckedOffset(0) == 0u);
    CHECK(yaff::ToCheckedOffset((1ULL << 31) - 1) == static_cast<yaff::Offset>((1ULL << 31) - 1));
    CHECK_THROWS_AS(yaff::ToCheckedOffset(1ULL << 31), std::runtime_error);

    CHECK(yaff::ToCheckedSignedOffset(-5) == -5);
    CHECK(yaff::ToCheckedSignedOffset(2147483647LL) == 2147483647);
    CHECK_THROWS_AS(yaff::ToCheckedSignedOffset(1LL << 32), std::runtime_error);
    CHECK_THROWS_AS(yaff::ToCheckedSignedOffset(-(1LL << 32)), std::runtime_error);
}
