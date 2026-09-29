// Sorted-lookup over an array of strings (find/contains on Array<InternalOffset<String>>).
// Isolated into its own component binary because it instantiates the sorted-vector lookup API
// on a reference array — an advanced corner whose absence should cost only this case, not the
// basic String round-trip tests in test_string.cpp.
#include "doctest.h"
#include "yaff_test_meta.h"

#include <yaff/serializer.h>
#include <yaff/message.h>
#include <yaff/array.h>

#include <string>
#include <string_view>
#include <vector>

using namespace yaffmeta;

TEST_CASE("string - sorted string array supports find and contains") {
    std::vector<yaff::InternalOffset<yaff::String>> offsets;
    yaff::Serializer ys;
    for (const char* w : {"alpha", "beta", "gamma", "omega"}) {
        offsets.emplace_back(ys.SerializeString(std::string(w)));
    }
    const auto arrOff = ys.SerializeArray(offsets);  // finish array before opening the box
    ys.StartFlatMessage<FlatBox>();
    ys.AddField(1, arrOff);
    ys.Finish(yaff::InternalOffset<void>(ys.FinishFlatMessage()));

    using ArrT = yaff::Array<yaff::InternalOffset<yaff::String>>;
    const auto& arr = *yaff::ReadMessage<yaff::DynamicMessage<FlatBox>>(ys.Data())
                           .ReadLayout<ArrT>(1, &ArrT::Default());
    REQUIRE(arr.Size() == 4U);
    auto it = arr.find(std::string_view("gamma"));
    CHECK(it != arr.end());
    CHECK(*it == std::string("gamma"));
    CHECK(arr.contains(std::string_view("alpha")));
    CHECK_FALSE(arr.contains(std::string_view("delta")));
}
