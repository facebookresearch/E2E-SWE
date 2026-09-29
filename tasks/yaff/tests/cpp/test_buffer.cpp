// The dual-ended growth buffer (yaff/buffer.h): the left side grows up from the start, the
// right side grows down from the end, reallocation must preserve both, and detaching yields
// the serialized right segment. Tested as two full lifecycles rather than per-method probes.
#include "doctest.h"
#include <yaff/buffer.h>
#include <yaff/base.h>

#include <cstdint>

TEST_CASE("dual buffer - interleaved left/right lifecycle survives reallocation") {
    yaff::DualBuffer b(4);  // tiny initial size forces several reallocations

    // Push 32 words on each side, interleaved, crossing several growth events.
    for (uint32_t i = 0; i < 32; ++i) {
        b.LeftPushSmall<uint32_t>(i);
        b.RightPushSmall<uint32_t>(1000u + i);
    }
    CHECK(b.LeftSize() == 128u);
    CHECK(b.RightSize() == 128u);

    // Left side keeps insertion order from the start; addressing by absolute offset works.
    for (uint32_t i = 0; i < 32; ++i) {
        CHECK(yaff::ReadValue<uint32_t>(b.LeftDataAt(i * 4)) == i);
    }
    // OffsetAt is the inverse of DataAt on the left side.
    CHECK(b.LeftOffsetAt(b.LeftDataAt(40)) == 40u);

    // Right side: the most recent push sits at the lowest address (RightData()).
    CHECK(yaff::ReadValue<uint32_t>(b.RightData()) == 1031u);

    // Fill + pop adjust the left cursor without disturbing existing data.
    b.LeftFill(8);
    CHECK(b.LeftSize() == 136u);
    CHECK(yaff::ReadValue<uint32_t>(b.LeftDataAt(128)) == 0u);  // filled zero
    b.LeftPop(8);
    CHECK(b.LeftSize() == 128u);
    CHECK(yaff::ReadValue<uint32_t>(b.LeftDataAt(124)) == 31u);  // earlier data intact
}

TEST_CASE("dual buffer - RightDetach hands off the serialized right segment") {
    yaff::DualBuffer b(8);
    b.RightPushSmall<uint32_t>(0x0000000A);  // pushed first -> higher address
    b.RightPushSmall<uint32_t>(0x12345678);  // pushed last  -> RightData()
    CHECK(b.RightSize() == 8u);

    auto seg = b.RightDetach();
    CHECK(seg.Size() == 8u);
    CHECK(yaff::ReadValue<uint32_t>(seg.Data()) == 0x12345678u);
    CHECK(yaff::ReadValue<uint32_t>(seg.Data() + 4) == 0x0000000Au);
    // The buffer is emptied after a detach and can be reused.
    CHECK(b.RightSize() == 0u);
    b.RightPushSmall<uint16_t>(0xBEEF);
    CHECK(b.RightSize() == 2u);
}
