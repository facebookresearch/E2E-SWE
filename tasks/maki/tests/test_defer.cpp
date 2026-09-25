// maki WRG task — gtest suite, module: defer.
// Single-test module: MakiDefer.DeferredEventProcessedAfterStateExit

#include <gtest/gtest.h>
#include <maki.hpp>


namespace defer_ns {
    struct context { int hits = 0; };
    struct init_done{};
    struct do_work{};

    inline constexpr auto initializing = maki::state_mold{}
        .defer<do_work>()
    ;

    inline constexpr auto ready = maki::state_mold{}
        .internal_action_c<do_work>(
            [](context& c){ ++c.hits; }
        )
    ;

    inline constexpr auto table = maki::transition_table{}
        (maki::ini,     initializing)
        (initializing,  ready, maki::event<init_done>)
    ;

    struct conf {
        static constexpr auto value = maki::machine_conf{}
            .transition_tables(table)
            .context_a<context>()
        ;
    };

    using machine_t = maki::machine<conf>;
}

TEST(MakiDefer, DeferredEventProcessedAfterStateExit) {
    using namespace defer_ns;

    auto m = machine_t{};
    EXPECT_TRUE(m.is<initializing>());

    m.process_event(do_work{});
    m.process_event(do_work{});
    EXPECT_EQ(m.context().hits, 0);

    m.process_event(init_done{});
    EXPECT_TRUE(m.is<ready>());
    EXPECT_EQ(m.context().hits, 2);
}
