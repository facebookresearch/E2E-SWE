// End-to-end coverage of Array<T>: scalar / bool / message element kinds, ordering,
// iterator protocol (range-for, random access, reverse, std algorithms), sorted-vector
// lookups (find/contains/equal_range), the empty/Default array, deduplication of identical
// arrays, and the generator overload. Arrays are wrapped in a flat box and read back.
#include "doctest.h"
#include "yaff_test_meta.h"

#include <yaff/serializer.h>
#include <yaff/message.h>
#include <yaff/array.h>

#include <algorithm>
#include <cstddef>
#include <numeric>
#include <vector>
using namespace yaffmeta;

namespace {
// Serialize a single array offset into a flat box and finish the buffer.
template <typename Off>
const std::byte* FinishInBox(yaff::Serializer& ys, Off arrayOffset) {
    ys.StartFlatMessage<FlatBox>();
    ys.AddField(1, arrayOffset);
    ys.Finish(yaff::InternalOffset<void>(ys.FinishFlatMessage()));
    return ys.Data();
}
}  // namespace

TEST_CASE("array - scalar uint64 vector order iteration random access and find") {
    std::vector<uint64_t> vec{10, 20, 30, 40, 50};
    yaff::Serializer ys;
    const auto* buf = FinishInBox(ys, ys.SerializeArray(vec));

    const auto& box = yaff::ReadMessage<yaff::DynamicMessage<FlatBox>>(buf);
    using ArrT = yaff::Array<uint64_t>;
    const auto& arr = *box.ReadLayout<ArrT>(1, &ArrT::Default());

    REQUIRE(arr.Size() == 5U);
    CHECK_FALSE(arr.Empty());
    for (uint32_t i = 0; i < arr.Size(); ++i) {
        CHECK(arr.Get(i) == (i + 1) * 10ULL);
        CHECK(arr[i] == (i + 1) * 10ULL);
    }
    // Range-for + std algorithms over the iterator.
    CHECK(std::accumulate(arr.begin(), arr.end(), uint64_t{0}) == 150ULL);
    CHECK(std::equal(arr.begin(), arr.end(), vec.begin()));
    CHECK(std::find(arr.begin(), arr.end(), 30ULL) != arr.end());
    CHECK(std::find(arr.begin(), arr.end(), 999ULL) == arr.end());
    // Reverse iteration via random-access arithmetic.
    CHECK(*(arr.end() - 1) == 50ULL);
    CHECK(arr.begin()[2] == 30ULL);
}

TEST_CASE("array - bool and double vectors round-trip element-wise") {
    std::vector<bool> flags;
    std::vector<double> reals;
    for (int i = 0; i < 8; ++i) {
        flags.push_back((i % 3) == 0);
        reals.push_back(i * 0.5);
    }

    yaff::Serializer ys1;
    const auto& barr =
        *yaff::ReadMessage<yaff::DynamicMessage<FlatBox>>(FinishInBox(ys1, ys1.SerializeArray(flags)))
             .ReadLayout<yaff::Array<bool>>(1, &yaff::Array<bool>::Default());
    REQUIRE(barr.Size() == 8U);
    for (uint32_t i = 0; i < barr.Size(); ++i) {
        CHECK(barr.Get(i) == ((i % 3) == 0));
    }

    yaff::Serializer ys2;
    const auto& darr =
        *yaff::ReadMessage<yaff::DynamicMessage<FlatBox>>(FinishInBox(ys2, ys2.SerializeArray(reals)))
             .ReadLayout<yaff::Array<double>>(1, &yaff::Array<double>::Default());
    REQUIRE(darr.Size() == 8U);
    for (uint32_t i = 0; i < darr.Size(); ++i) {
        CHECK(darr.Get(i) == doctest::Approx(i * 0.5));
    }
}

TEST_CASE("array - of nested flat messages preserve order support iteration and lower_bound") {
    yaff::Serializer ys;
    using Msg = yaff::DynamicMessage<RecordV1>;

    std::vector<yaff::InternalOffset<Msg>> messages;
    for (uint64_t i = 0; i < 16; ++i) {
        ys.StartFlatMessage<RecordV1>(/*implicit*/ false, /*sized*/ true);
        ys.AddField<uint64_t>(1, i, 0);
        messages.emplace_back(yaff::InternalOffset<Msg>(ys.FinishFlatMessage()));
    }
    const auto* buf = FinishInBox(ys, ys.SerializeArray(messages));

    const auto& box = yaff::ReadMessage<yaff::DynamicMessage<FlatBox>>(buf);
    using ArrT = yaff::Array<yaff::InternalOffset<Msg>>;
    const auto& arr = *box.ReadLayout<ArrT>(1, &ArrT::Default());

    REQUIRE(arr.Size() == 16U);
    uint64_t expected = 0;
    for (const auto& m : arr) {
        CHECK(m.ReadValue<uint64_t>(1, 0) == expected);
        CHECK(m.ReadValue<uint64_t>(5, 0xEE) == 0xEEULL);  // unset tail field -> default
        ++expected;
    }
    // Sorted-by-id1, so a lower_bound keyed on field 1 finds the element.
    const auto it = std::lower_bound(arr.begin(), arr.end(), 10ULL,
                                     [](const Msg& m, uint64_t k) { return m.ReadValue<uint64_t>(1, 0) < k; });
    CHECK(it->ReadValue<uint64_t>(1, 0) == 10ULL);
}

TEST_CASE("array - sorted scalar vector supports find / contains / equal_range") {
    std::vector<uint32_t> vec{1, 3, 5, 7, 9};
    yaff::Serializer ys;
    const auto* buf = FinishInBox(ys, ys.SerializeArray(vec));
    using ArrT = yaff::Array<uint32_t>;
    const auto& arr = *yaff::ReadMessage<yaff::DynamicMessage<FlatBox>>(buf).ReadLayout<ArrT>(1, &ArrT::Default());

    CHECK(arr.find(5U) != arr.end());
    CHECK(*arr.find(7U) == 7U);
    CHECK(arr.find(4U) == arr.end());
    CHECK(arr.contains(9U));
    CHECK_FALSE(arr.contains(8U));
    CHECK(arr.count(1U) == 1U);
    const auto range = arr.equal_range(5U);
    CHECK(range.first != range.second);
    CHECK(*range.first == 5U);
}

TEST_CASE("array - empty vector produces a null offset and reads as the empty Default array") {
    yaff::Serializer ys;
    const auto off = ys.SerializeArray(std::vector<uint64_t>{});
    CHECK(off.IsNull());  // empty arrays serialize to the null offset

    // The box field is therefore absent and reads back as the empty default array.
    ys.StartFlatMessage<FlatBox>();
    ys.AddField(1, off);
    ys.Finish(yaff::InternalOffset<void>(ys.FinishFlatMessage()));

    using ArrT = yaff::Array<uint64_t>;
    const auto& arr = *yaff::ReadMessage<yaff::DynamicMessage<FlatBox>>(ys.Data())
                           .ReadLayout<ArrT>(1, &ArrT::Default());
    CHECK(arr.Size() == 0U);
    CHECK(arr.Empty());
    CHECK(arr.begin() == arr.end());
}

TEST_CASE("array - identical arrays are deduplicated to the same offset") {
    yaff::Serializer ys;
    const auto a = ys.SerializeArray(std::vector<uint64_t>{7, 8, 9});
    const auto b = ys.SerializeArray(std::vector<uint64_t>{7, 8, 9});  // identical bytes
    const auto c = ys.SerializeArray(std::vector<uint64_t>{7, 8, 0});  // differs
    CHECK(a.O == b.O);     // deduplicated
    CHECK(a.O != c.O);     // distinct content -> distinct offset
}

TEST_CASE("array - generator overload builds elements in index order") {
    yaff::Serializer ys;
    const auto off = ys.SerializeArray<uint64_t>(6, [](size_t i) { return static_cast<uint64_t>(i * i); });
    const auto* buf = FinishInBox(ys, off);
    using ArrT = yaff::Array<uint64_t>;
    const auto& arr = *yaff::ReadMessage<yaff::DynamicMessage<FlatBox>>(buf).ReadLayout<ArrT>(1, &ArrT::Default());

    REQUIRE(arr.Size() == 6U);
    for (uint32_t i = 0; i < arr.Size(); ++i) {
        CHECK(arr.Get(i) == static_cast<uint64_t>(i) * i);
    }
}
