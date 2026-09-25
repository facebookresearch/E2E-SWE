// End-to-end coverage of the fixed layout: FixedMessage readers + the FixedMessage
// serializer path, nested inside a flat container, and as elements of an inline-offset
// array. Each test builds a real buffer with the low-level Serializer and reads every
// contract back.
#include "doctest.h"
#include "yaff_test_meta.h"

#include <yaff/serializer.h>
#include <yaff/message.h>
#include <yaff/array.h>

using namespace yaffmeta;

TEST_CASE("fixed message - scalars presence defaults and nesting in a flat box") {
    yaff::Serializer ys;

    // A FixedPair with id1 set (0xFF) and id2 left at the default 0.
    ys.StartFixedMessage<FixedPair>();
    ys.AddField<uint64_t>(2, 0x0, 0x0);
    ys.AddField<uint64_t>(1, 0xFF, 0x0);
    const auto pair = ys.FinishFixedMessage();

    // Embed it (by offset) in a flat box and finish the buffer.
    ys.StartFlatMessage<FlatBox>();
    ys.AddField(1, yaff::InternalOffset<void>(pair));
    ys.Finish(yaff::InternalOffset<void>(ys.FinishFlatMessage()));

    const auto* buf = ys.Data();
    const auto& box = yaff::ReadMessage<yaff::DynamicMessage<FlatBox>>(buf);

    const auto& read = *box.ReadLayout<yaff::FixedMessage<FixedPair>>(1, &yaff::FixedMessage<FixedPair>::Default());
    CHECK(read.ReadValue<uint64_t>(1, 0x0) == 0xFFULL);
    CHECK(read.ReadValue<uint64_t>(2, 0x0) == 0x0ULL);
    // Fixed scalar presence == stored value is non-zero (xor with default).
    CHECK(read.ReadPresence<uint64_t>(1) == true);
    CHECK(read.ReadPresence<uint64_t>(2) == false);

    // An absent box field falls back to the supplied default message (all-zero).
    const auto& def = *box.ReadLayout<yaff::FixedMessage<FixedPair>>(2, &yaff::FixedMessage<FixedPair>::Default());
    CHECK(def.ReadValue<uint64_t>(1, 0x0) == 0x0ULL);
    CHECK(def.ReadPresence<uint64_t>(1) == false);
}

TEST_CASE("fixed message - array of inline fixed messages preserves order and values") {
    yaff::Serializer ys;
    // Write-side element type == the type the array is read back as (see ArrT below).
    using Elem = yaff::InlineOffset<yaff::FixedMessage<FixedPair>>;

    // 10 fixed pairs: element i holds (id1 = 2*i, id2 = i). SerializeArray's producer
    // emits in order; the reader sees them reversed (yaff stores arrays back-to-front).
    const auto arrayOffset = ys.SerializeArray<Elem>([&](size_t i) {
        ys.StartFixedMessage<FixedPair>();
        ys.AddField<uint64_t>(2, i, 0x0);
        ys.AddField<uint64_t>(1, 2 * i, 0x0);
        return std::make_pair(Elem(ys.FinishFixedMessage()), i + 1 < 10);
    });

    ys.StartFlatMessage<FlatBox>();
    ys.AddField(1, arrayOffset);
    ys.Finish(yaff::InternalOffset<void>(ys.FinishFlatMessage()));

    const auto* buf = ys.Data();
    const auto& box = yaff::ReadMessage<yaff::DynamicMessage<FlatBox>>(buf);

    using ArrT = yaff::Array<yaff::InlineOffset<yaff::FixedMessage<FixedPair>>>;
    const auto& arr = *box.ReadLayout<ArrT>(1, &ArrT::Default());
    REQUIRE(arr.Size() == 10U);
    for (size_t i = 0; i < arr.Size(); ++i) {
        const auto& e = arr.Get(i);
        const uint64_t orig = arr.Size() - i - 1;  // stored reversed
        CHECK(e.ReadValue<uint64_t>(1, 0x0) == 2 * orig);
        CHECK(e.ReadValue<uint64_t>(2, 0x0) == orig);
    }
    // operator[] agrees with Get.
    CHECK(arr[0].ReadValue<uint64_t>(2, 0x0) == 9ULL);
}

TEST_CASE("fixed message - Default() is an all-zero instance") {
    const auto& def = yaff::FixedMessage<FixedPair>::Default();
    CHECK(def.ReadValue<uint64_t>(1, 0x0) == 0x0ULL);
    CHECK(def.ReadValue<uint64_t>(2, 0x7) == 0x7ULL);  // xor with default 0x7 -> 0x7
    CHECK(def.ReadPresence<uint64_t>(1) == false);
}
