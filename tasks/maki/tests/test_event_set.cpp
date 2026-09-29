// maki WRG task — gtest suite, module: event_set.
// Single-test module: MakiEventSet.SetAlgebraContainsAndOperators

#include <gtest/gtest.h>
#include <maki.hpp>


TEST(MakiEventSet, SetAlgebraContainsAndOperators) {
    {
        constexpr auto s = maki::event<int> || maki::event<double>;
        EXPECT_TRUE (s.template contains<int>());
        EXPECT_TRUE (s.template contains<double>());
        EXPECT_FALSE(s.template contains<char>());
    }
    {
        constexpr auto s = !maki::event<int>;
        EXPECT_FALSE(s.template contains<int>());
        EXPECT_TRUE (s.template contains<double>());
    }
    {
        constexpr auto s = (maki::event<int> || maki::event<char>) &&
                           (maki::event<int> || maki::event<double>);
        EXPECT_TRUE (s.template contains<int>());
        EXPECT_FALSE(s.template contains<char>());
        EXPECT_FALSE(s.template contains<double>());
    }
    {
        EXPECT_TRUE (maki::all_events.template contains<int>());
        EXPECT_TRUE (maki::all_events.template contains<double>());
        EXPECT_FALSE(maki::no_event.template contains<int>());
    }
}
