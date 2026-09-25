// End-to-end Serializer mechanics: cross-layout nesting (fixed inside flat), producer-based
// array building (including early termination), object/string deduplication, and the
// Release/Reset buffer lifecycle. Uses hand-written meta traits so no codegen is involved.
#include "doctest.h"
#include "yaff_test_meta.h"

#include <yaff/serializer.h>
#include <yaff/message.h>
#include <yaff/array.h>

#include <utility>
#include <stdexcept>

using namespace yaffmeta;

TEST_CASE("serializer - Finish rejects a null root offset") {
    // The root object handed to Finish must be non-null; a zero/null offset is rejected.
    yaff::Serializer ys;
    CHECK_THROWS_AS(ys.Finish(yaff::InternalOffset<void>(0)), std::runtime_error);
}

TEST_CASE("serializer - early-terminating producer builds a shorter array of inline fixed messages") {
    // The producer returns "continue = false" after the 3rd element, so the array holds exactly
    // the produced count (not any larger natural bound). Element i holds (id1 = 100 + i,
    // id2 = 7 * i); producer/deferred arrays are stored in the reverse of production order.
    yaff::Serializer ys;
    // Write-side element type == the type the array is read back as (see ArrT below).
    using Elem = yaff::InlineOffset<yaff::FixedMessage<FixedPair>>;
    const auto arrayOffset = ys.SerializeArray<Elem>([&](size_t i) {
        ys.StartFixedMessage<FixedPair>();
        ys.AddField<uint64_t>(2, 7 * i, 0x0);
        ys.AddField<uint64_t>(1, 100 + i, 0x0);
        return std::make_pair(Elem(ys.FinishFixedMessage()), i + 1 < 3);
    });
    ys.StartFlatMessage<FlatBox>();
    ys.AddField(1, arrayOffset);
    ys.Finish(yaff::InternalOffset<void>(ys.FinishFlatMessage()));

    using ArrT = yaff::Array<yaff::InlineOffset<yaff::FixedMessage<FixedPair>>>;
    const auto& arr = *yaff::ReadMessage<yaff::DynamicMessage<FlatBox>>(ys.Data()).ReadLayout<ArrT>(1, &ArrT::Default());
    REQUIRE(arr.Size() == 3U);
    for (size_t i = 0; i < arr.Size(); ++i) {
        const uint64_t orig = arr.Size() - i - 1;  // stored reversed
        CHECK(arr.Get(i).ReadValue<uint64_t>(1, 0x0) == 100 + orig);
        CHECK(arr.Get(i).ReadValue<uint64_t>(2, 0x0) == 7 * orig);
    }
}

TEST_CASE("serializer - identical strings are deduplicated but distinct content is not") {
    yaff::Serializer ys;
    const auto a = ys.SerializeString(std::string("shared-token"));
    const auto b = ys.SerializeString(std::string("shared-token"));
    const auto c = ys.SerializeString(std::string("other-token"));
    CHECK(a.O == b.O);
    CHECK(a.O != c.O);

    // The deduplicated offset still resolves to the correct content.
    ys.StartFlatMessage<FlatBox>();
    ys.AddField(1, b);
    ys.Finish(yaff::InternalOffset<void>(ys.FinishFlatMessage()));
    const auto& s = *yaff::ReadMessage<yaff::DynamicMessage<FlatBox>>(ys.Data())
                         .ReadLayout<yaff::String>(1, &yaff::String::Default());
    CHECK(s == std::string("shared-token"));
}

TEST_CASE("serializer - Release detaches the buffer and Reset enables reuse") {
    yaff::Serializer ys;

    // First message: a fixed pair wrapped in a box, then Release the finished buffer.
    ys.StartFixedMessage<FixedPair>();
    ys.AddField<uint64_t>(2, 2, 0);
    ys.AddField<uint64_t>(1, 1, 0);
    const auto first = ys.FinishFixedMessage();
    ys.StartFlatMessage<FlatBox>();
    ys.AddField(1, yaff::InternalOffset<void>(first));
    ys.Finish(yaff::InternalOffset<void>(ys.FinishFlatMessage()));
    const auto seg = ys.Release();

    const auto& box1 = yaff::ReadMessage<yaff::DynamicMessage<FlatBox>>(seg.Data());
    const auto& p1 = *box1.ReadLayout<yaff::FixedMessage<FixedPair>>(1, &yaff::FixedMessage<FixedPair>::Default());
    CHECK(p1.ReadValue<uint64_t>(1, 0) == 1ULL);
    CHECK(p1.ReadValue<uint64_t>(2, 0) == 2ULL);

    // The same serializer can build a fresh, independent message after Release/Reset.
    ys.StartFixedMessage<FixedPair>();
    ys.AddField<uint64_t>(2, 20, 0);
    ys.AddField<uint64_t>(1, 10, 0);
    const auto second = ys.FinishFixedMessage();
    ys.StartFlatMessage<FlatBox>();
    ys.AddField(1, yaff::InternalOffset<void>(second));
    ys.Finish(yaff::InternalOffset<void>(ys.FinishFlatMessage()));

    const auto& box2 = yaff::ReadMessage<yaff::DynamicMessage<FlatBox>>(ys.Data());
    const auto& p2 = *box2.ReadLayout<yaff::FixedMessage<FixedPair>>(1, &yaff::FixedMessage<FixedPair>::Default());
    CHECK(p2.ReadValue<uint64_t>(1, 0) == 10ULL);
    CHECK(p2.ReadValue<uint64_t>(2, 0) == 20ULL);
    // The earlier detached segment is unaffected by the reuse.
    CHECK(p1.ReadValue<uint64_t>(1, 0) == 1ULL);
}
