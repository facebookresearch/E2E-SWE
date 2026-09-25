// maki WRG task — gtest suite, module: exceptions.
// Module tests (Tier 2 — exception handling):
//   MakiExceptions.UncaughtExceptionLandsInUndefined
//   MakiExceptions.CatchMxInterceptsAndAllowsRecovery

#include <gtest/gtest.h>
#include <maki.hpp>

#include <exception>
#include <stdexcept>
#include <string>


namespace exc_default_ns {
    struct context {
        int always_zero = 0;
        std::string log;
    };
    struct trigger{};

    inline constexpr auto off = maki::state_mold{}
        .exit_action_c([](context& c){ c.log += "off.exit;"; })
    ;

    inline constexpr auto on = maki::state_mold{}
        .entry_action_c([](context& c){
            c.log += "on.entry;";
            if (c.always_zero == 0) {
                throw std::runtime_error{"boom"};
            }
        })
    ;

    inline constexpr auto table = maki::transition_table{}
        (maki::ini, off)
        (off, on, maki::event<trigger>)
    ;

    struct conf {
        static constexpr auto value = maki::machine_conf{}
            .transition_tables(table)
            .context_a<context>()
        ;
    };

    using machine_t = maki::machine<conf>;
}

TEST(MakiExceptions, UncaughtExceptionLandsInUndefined) {
    using namespace exc_default_ns;

    auto m = machine_t{};
    EXPECT_TRUE(m.is<off>());
    m.context().log.clear();

    EXPECT_THROW(m.process_event(trigger{}), std::runtime_error);
    EXPECT_TRUE(m.is<maki::undefined>());
    EXPECT_EQ(m.context().log, "off.exit;on.entry;");
}


namespace catch_mx_ns {
    struct context {
        int always_zero = 0;
        std::string log;
    };
    struct trigger{};
    struct rescue{};

    inline constexpr auto off = maki::state_mold{};
    inline constexpr auto on  = maki::state_mold{}
        .entry_action_c([](context& c){
            if (c.always_zero == 0) {
                throw std::runtime_error{"boom"};
            }
        })
    ;

    constexpr auto do_rescue = maki::action_c(
        [](context& c){ c.log += "rescued;"; });

    inline constexpr auto table = maki::transition_table{}
        (maki::ini, off)
        (off, on,  maki::event<trigger>)
        (maki::undefined, off, maki::event<rescue>, do_rescue)
    ;

    struct conf {
        static constexpr auto value = maki::machine_conf{}
            .transition_tables(table)
            .context_a<context>()
            .catch_mx(
                [](auto& mach, const std::exception_ptr& eptr) {
                    try {
                        std::rethrow_exception(eptr);
                    } catch (const std::exception& e) {
                        mach.context().log += std::string{"caught:"} + e.what() + ";";
                    }
                }
            )
        ;
    };

    using machine_t = maki::machine<conf>;
}

TEST(MakiExceptions, CatchMxInterceptsAndAllowsRecovery) {
    using namespace catch_mx_ns;

    auto m = machine_t{};
    EXPECT_TRUE(m.is<off>());

    m.process_event(trigger{});
    EXPECT_EQ(m.context().log, "caught:boom;");
    EXPECT_TRUE(m.is<maki::undefined>());

    m.process_event(rescue{});
    EXPECT_EQ(m.context().log, "caught:boom;rescued;");
    EXPECT_TRUE(m.is<off>());
}
