// maki WRG task — gtest suite, module: basic.
// One TEST per behavioral contract; per-module split so per-file compile
// failures do not sink the entire suite.
//
// Module tests (Tier 1 — basic FSM shape + machine control):
//   MakiBasic.SimpleTwoStateTransition
//   MakiBasic.AutoStartFalseThenExplicitStart
//   MakiBasic.DispatchByEventType
//   MakiBasic.StartWithCustomEventPassesToEntryAction

#include <gtest/gtest.h>
#include <maki.hpp>


namespace basic_ns {
    struct context {};

    struct press{};
    struct release{};

    inline constexpr auto off = maki::state_mold{};
    inline constexpr auto on  = maki::state_mold{};

    inline constexpr auto table = maki::transition_table{}
        (maki::ini, off)
        (off,       on,  maki::event<press>)
        (on,        off, maki::event<release>)
    ;

    struct conf {
        static constexpr auto value = maki::machine_conf{}
            .transition_tables(table)
            .context_a<context>()
        ;
    };

    using machine_t = maki::machine<conf>;
}

TEST(MakiBasic, SimpleTwoStateTransition) {
    using namespace basic_ns;

    auto m = machine_t{};

    // Auto-started, initial state is `off` (target of the ini transition).
    EXPECT_TRUE(m.running());
    EXPECT_TRUE(m.is<off>());
    EXPECT_FALSE(m.is<on>());

    m.process_event(press{});
    EXPECT_TRUE(m.is<on>());
    EXPECT_FALSE(m.is<off>());

    m.process_event(release{});
    EXPECT_TRUE(m.is<off>());
    EXPECT_FALSE(m.is<on>());
}


namespace manual_start_ns {
    struct context {};
    struct press{};

    inline constexpr auto off = maki::state_mold{};
    inline constexpr auto on  = maki::state_mold{};

    inline constexpr auto table = maki::transition_table{}
        (maki::ini, off)
        (off,       on,  maki::event<press>)
    ;

    struct conf {
        static constexpr auto value = maki::machine_conf{}
            .transition_tables(table)
            .context_a<context>()
            .auto_start(false)
        ;
    };

    using machine_t = maki::machine<conf>;
}

TEST(MakiBasic, AutoStartFalseThenExplicitStart) {
    using namespace manual_start_ns;

    auto m = machine_t{};

    // With auto_start(false), the machine is NOT running after construction.
    EXPECT_FALSE(m.running());

    // Events dispatched to a stopped machine do nothing.
    m.process_event(press{});
    EXPECT_FALSE(m.running());

    // Now start it: initial state becomes active, machine is running.
    m.start();
    EXPECT_TRUE(m.running());
    EXPECT_TRUE(m.is<off>());

    m.process_event(press{});
    EXPECT_TRUE(m.is<on>());

    // stop() halts the machine.
    m.stop();
    EXPECT_FALSE(m.running());
}


namespace multi_event_ns {
    struct context {};

    struct ev_a{};
    struct ev_b{};
    struct ev_c{};

    inline constexpr auto s0 = maki::state_mold{};
    inline constexpr auto s1 = maki::state_mold{};
    inline constexpr auto s2 = maki::state_mold{};
    inline constexpr auto s3 = maki::state_mold{};

    inline constexpr auto table = maki::transition_table{}
        (maki::ini, s0)
        (s0, s1, maki::event<ev_a>)
        (s1, s2, maki::event<ev_b>)
        (s2, s3, maki::event<ev_c>)
    ;

    struct conf {
        static constexpr auto value = maki::machine_conf{}
            .transition_tables(table)
            .context_a<context>()
        ;
    };

    using machine_t = maki::machine<conf>;
}

TEST(MakiBasic, DispatchByEventType) {
    using namespace multi_event_ns;

    auto m = machine_t{};
    EXPECT_TRUE(m.is<s0>());

    // Wrong event type -> no transition.
    m.process_event(ev_b{});
    EXPECT_TRUE(m.is<s0>());

    m.process_event(ev_a{});
    EXPECT_TRUE(m.is<s1>());

    // ev_a from s1 -> no matching transition, no state change.
    m.process_event(ev_a{});
    EXPECT_TRUE(m.is<s1>());

    m.process_event(ev_b{});
    EXPECT_TRUE(m.is<s2>());

    m.process_event(ev_c{});
    EXPECT_TRUE(m.is<s3>());
}


namespace start_event_ns {
    struct context { int payload = 0; };

    struct init_evt { int n = 0; };

    inline constexpr auto s0 = maki::state_mold{}
        .entry_action_ce<init_evt>(
            [](context& ctx, const init_evt& e) {
                ctx.payload = e.n;
            }
        )
    ;

    inline constexpr auto table = maki::transition_table{}
        (maki::ini, s0)
    ;

    struct conf {
        static constexpr auto value = maki::machine_conf{}
            .transition_tables(table)
            .context_a<context>()
            .auto_start(false)
        ;
    };

    using machine_t = maki::machine<conf>;
}

TEST(MakiBasic, StartWithCustomEventPassesToEntryAction) {
    using namespace start_event_ns;

    auto m = machine_t{};
    EXPECT_EQ(m.context().payload, 0);

    m.start(init_evt{42});
    EXPECT_TRUE(m.is<s0>());
    EXPECT_EQ(m.context().payload, 42);
}
