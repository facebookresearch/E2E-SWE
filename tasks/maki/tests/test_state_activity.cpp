// maki WRG task — gtest suite, module: state_activity.
// Single-test module: MakiStateData.StateActivityLifetimeResetsOnReEntry
// (state_activity lifetime — context() returns an optional-like handle).

#include <gtest/gtest.h>
#include <maki.hpp>


namespace state_data_activity_ns {
    struct context {};

    struct on_data {
        int counter = 0;
    };

    struct press{};
    struct tick { int n = 0; };

    inline constexpr auto off = maki::state_mold{};

    inline constexpr auto on = maki::state_mold{}
        .context_v<on_data>()
        .context_lifetime(maki::state_context_lifetime::state_activity)
        .internal_action_ce<tick>(
            [](on_data& d, const tick& e){ d.counter += e.n; }
        )
    ;

    inline constexpr auto table = maki::transition_table{}
        (maki::ini, off)
        (off, on,  maki::event<press>)
        (on,  off, maki::event<press>)
    ;

    struct conf {
        static constexpr auto value = maki::machine_conf{}
            .transition_tables(table)
            .context_a<context>()
        ;
    };

    using machine_t = maki::machine<conf>;
}

TEST(MakiStateData, StateActivityLifetimeResetsOnReEntry) {
    using namespace state_data_activity_ns;

    auto m = machine_t{};
    const auto& on_state = m.state<on>();

    EXPECT_FALSE(on_state.context().has_value());

    m.process_event(press{});
    ASSERT_TRUE(on_state.context().has_value());
    m.process_event(tick{5});
    EXPECT_EQ(on_state.context()->counter, 5);

    m.process_event(press{});
    EXPECT_FALSE(on_state.context().has_value());

    m.process_event(press{});
    ASSERT_TRUE(on_state.context().has_value());
    EXPECT_EQ(on_state.context()->counter, 0);

    m.process_event(tick{9});
    EXPECT_EQ(on_state.context()->counter, 9);
}
