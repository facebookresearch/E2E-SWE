// maki WRG task — gtest suite, module: composite.
// Module tests (Tier 2 — composite states + orthogonal regions):
//   MakiComposite.InnerStateReachableViaMachineState
//   MakiComposite.ReEnterResetsInnerToInitial
//   MakiOrthogonal.RegionsAreIndependent

#include <gtest/gtest.h>
#include <maki.hpp>

#include <string>


namespace composite_ns {
    struct context { std::string log; };
    struct power{};
    struct next{};

    inline constexpr auto off = maki::state_mold{}
        .entry_action_c([](context& c){ c.log += "off.entry;"; })
        .exit_action_c ([](context& c){ c.log += "off.exit;";  })
    ;

    inline constexpr auto red   = maki::state_mold{};
    inline constexpr auto green = maki::state_mold{};
    inline constexpr auto blue  = maki::state_mold{};

    inline constexpr auto on_table = maki::transition_table{}
        (maki::ini, red)
        (red,   green, maki::event<next>)
        (green, blue,  maki::event<next>)
        (blue,  red,   maki::event<next>)
    ;

    inline constexpr auto on = maki::state_mold{}
        .transition_tables(on_table)
        .entry_action_c([](context& c){ c.log += "on.entry;"; })
        .exit_action_c ([](context& c){ c.log += "on.exit;";  })
    ;

    inline constexpr auto table = maki::transition_table{}
        (maki::ini, off)
        (off, on,  maki::event<power>)
        (on,  off, maki::event<power>)
    ;

    struct conf {
        static constexpr auto value = maki::machine_conf{}
            .transition_tables(table)
            .context_a<context>()
        ;
    };

    using machine_t = maki::machine<conf>;
}

TEST(MakiComposite, InnerStateReachableViaMachineState) {
    using namespace composite_ns;

    auto m = machine_t{};
    EXPECT_TRUE(m.is<off>());
    EXPECT_EQ(m.context().log, "off.entry;");

    m.context().log.clear();
    m.process_event(power{});
    EXPECT_TRUE(m.is<on>());

    const auto& on_state = m.state<on>();
    EXPECT_TRUE(on_state.is<red>());

    m.process_event(next{});
    EXPECT_TRUE(m.is<on>());
    EXPECT_TRUE(on_state.is<green>());

    m.process_event(next{});
    EXPECT_TRUE(on_state.is<blue>());

    m.context().log.clear();
    m.process_event(power{});
    EXPECT_TRUE(m.is<off>());
    EXPECT_EQ(m.context().log, "on.exit;off.entry;");
}


TEST(MakiComposite, ReEnterResetsInnerToInitial) {
    using namespace composite_ns;

    auto m = machine_t{};

    m.process_event(power{});
    m.process_event(next{});
    m.process_event(next{});
    m.process_event(power{});
    m.process_event(power{});

    const auto& on_state = m.state<on>();
    EXPECT_TRUE(m.is<on>());
    EXPECT_TRUE(on_state.is<red>());
    EXPECT_FALSE(on_state.is<blue>());
}


// ============================================================================
// MakiOrthogonal
// ============================================================================

namespace orth_ns {
    struct context { std::string log; };
    struct e_a{};
    struct e_b{};

    inline constexpr auto a_off = maki::state_mold{};
    inline constexpr auto a_on  = maki::state_mold{}
        .entry_action_c([](context& c){ c.log += "a_on;"; })
    ;
    inline constexpr auto b_off = maki::state_mold{};
    inline constexpr auto b_on  = maki::state_mold{}
        .entry_action_c([](context& c){ c.log += "b_on;"; })
    ;

    inline constexpr auto t_a = maki::transition_table{}
        (maki::ini, a_off)
        (a_off, a_on, maki::event<e_a>)
    ;
    inline constexpr auto t_b = maki::transition_table{}
        (maki::ini, b_off)
        (b_off, b_on, maki::event<e_b>)
    ;

    struct conf {
        static constexpr auto value = maki::machine_conf{}
            .transition_tables(t_a, t_b)
            .context_a<context>()
        ;
    };

    using machine_t = maki::machine<conf>;
}

TEST(MakiOrthogonal, RegionsAreIndependent) {
    using namespace orth_ns;

    auto m = machine_t{};
    EXPECT_EQ(m.context().log, "");

    m.process_event(e_a{});
    EXPECT_EQ(m.context().log, "a_on;");

    m.process_event(e_b{});
    EXPECT_EQ(m.context().log, "a_on;b_on;");

    m.process_event(e_a{});
    EXPECT_EQ(m.context().log, "a_on;b_on;");
}
