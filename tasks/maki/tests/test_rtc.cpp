// maki WRG task — gtest suite, module: rtc.
// Single-test module: MakiRunToCompletion.RecursiveDispatchIsQueued
// Split to per-file so an unrelated test failure elsewhere doesn't compile-sink
// this test.

#include <gtest/gtest.h>
#include <maki.hpp>

#include <string>


namespace rtc_ns {
    struct context { std::string log; };
    struct outer{};
    struct inner{};

    inline constexpr auto s0 = maki::state_mold{}
        .internal_action_cm<outer>(
            [](context& c, auto& mach){
                c.log += "outer_start;";
                mach.process_event(inner{});
                c.log += "outer_end;";
            }
        )
    ;
    inline constexpr auto s1 = maki::state_mold{}
        .entry_action_c([](context& c){ c.log += "s1.entry;"; })
    ;

    inline constexpr auto table = maki::transition_table{}
        (maki::ini, s0)
        (s0, s1, maki::event<inner>)
    ;

    struct conf {
        static constexpr auto value = maki::machine_conf{}
            .transition_tables(table)
            .context_a<context>()
        ;
    };

    using machine_t = maki::machine<conf>;
}

TEST(MakiRunToCompletion, RecursiveDispatchIsQueued) {
    using namespace rtc_ns;

    auto m = machine_t{};
    EXPECT_TRUE(m.is<s0>());

    m.process_event(outer{});

    EXPECT_TRUE(m.is<s1>());
    EXPECT_EQ(m.context().log, "outer_start;outer_end;s1.entry;");
}
