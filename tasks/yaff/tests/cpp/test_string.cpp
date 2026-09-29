// End-to-end coverage of String: serialize/read, string_view conversion, equality and
// ordering, indexing + iteration, the empty string, arrays of strings, and sorted lookups.
#include "doctest.h"
#include "yaff_test_meta.h"

#include <yaff/serializer.h>
#include <yaff/message.h>
#include <yaff/array.h>

#include <cstring>
#include <string>
#include <vector>
using namespace yaffmeta;

TEST_CASE("string - content view equality ordering indexing and iteration") {
    const std::string text = "hello yaff";
    yaff::Serializer ys;
    const auto strOff = ys.SerializeString(text);
    ys.StartFlatMessage<FlatBox>();
    ys.AddField(1, strOff);
    ys.Finish(yaff::InternalOffset<void>(ys.FinishFlatMessage()));

    const auto& box = yaff::ReadMessage<yaff::DynamicMessage<FlatBox>>(ys.Data());
    const auto& s = *box.ReadLayout<yaff::String>(1, &yaff::String::Default());

    REQUIRE(s.Size() == text.size());
    CHECK(s.AsStringView() == text);
    CHECK(s == std::string("hello yaff"));   // operator==
    CHECK((s <=> std::string_view("hello yaff")) == std::strong_ordering::equal);
    CHECK((s <=> std::string_view("hello z")) == std::strong_ordering::less);
    CHECK((s <=> std::string_view("hello a")) == std::strong_ordering::greater);
    CHECK(s.Get(0) == 'h');
    CHECK(s[4] == 'o');
    // Iterate char-by-char and rebuild the string.
    std::string rebuilt;
    for (char c : s) {
        rebuilt.push_back(c);
    }
    CHECK(rebuilt == text);
    CHECK(std::memcmp(s.Data(), text.data(), s.Size()) == 0);
}

TEST_CASE("string - empty string round-trips as a zero-length String") {
    yaff::Serializer ys;
    const auto strOff = ys.SerializeString(std::string{});
    CHECK_FALSE(strOff.IsNull());  // an explicitly-serialized empty string is still present
    ys.StartFlatMessage<FlatBox>();
    ys.AddField(1, strOff);
    ys.Finish(yaff::InternalOffset<void>(ys.FinishFlatMessage()));

    const auto& s = *yaff::ReadMessage<yaff::DynamicMessage<FlatBox>>(ys.Data())
                         .ReadLayout<yaff::String>(1, &yaff::String::Default());
    CHECK(s.Size() == 0U);
    CHECK(s.Empty());
    CHECK(s.AsStringView() == "");
}

TEST_CASE("string - array of strings preserves order and content per element") {
    yaff::Serializer ys;
    std::vector<std::string> expected;
    std::vector<yaff::InternalOffset<yaff::String>> offsets;
    for (uint64_t n = 1; n <= 6; ++n) {
        std::string str(n, static_cast<char>('a' + n - 1));  // "a", "bb", "ccc", ...
        expected.push_back(str);
        offsets.emplace_back(ys.SerializeString(str));
    }

    const auto arrOff = ys.SerializeArray(offsets);  // must finish before opening the box
    ys.StartFlatMessage<FlatBox>();
    ys.AddField(1, arrOff);
    ys.Finish(yaff::InternalOffset<void>(ys.FinishFlatMessage()));

    using ArrT = yaff::Array<yaff::InternalOffset<yaff::String>>;
    const auto& arr = *yaff::ReadMessage<yaff::DynamicMessage<FlatBox>>(ys.Data())
                           .ReadLayout<ArrT>(1, &ArrT::Default());
    REQUIRE(arr.Size() == expected.size());
    for (uint32_t i = 0; i < arr.Size(); ++i) {
        const auto& s = arr.Get(i);
        CHECK(s == expected[i]);
        CHECK(s.Size() == expected[i].size());
        for (uint32_t j = 0; j < s.Size(); ++j) {
            CHECK(s[j] == expected[i][j]);
        }
    }
}

