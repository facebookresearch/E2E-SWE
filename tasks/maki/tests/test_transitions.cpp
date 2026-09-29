// maki WRG task — gtest suite, module: transitions.
// Module tests (Tier 2 — actions, guards, internal/completion, state_set source):
//   MakiActions.EntryExitTransitionOrdering
//   MakiActions.SignatureVariantsAllCallable
//   MakiActions.EventTypedEntryActionFiresOnlyForMatchingEvent
//   MakiGuards.GuardBlocksAndAllows
//   MakiGuards.BooleanOperatorComposition
//   MakiGuards.SignatureVariantsAllInvocable
//   MakiInternal.InternalActionDoesNotReentryState
//   MakiInternal.NullTargetInTableIsInternalTransition
//   MakiCompletion.ChainedCompletionTransitions
//   MakiTable.SourceIsStateSet

#include <gtest/gtest.h>
#include <maki.hpp>

#include <string>


// ============================================================================
// MakiActions
// ============================================================================

namespace action_seq_ns {
    struct context { std::string log; };
    struct press{};

    inline constexpr auto off = maki::state_mold{}
        .entry_action_c([](context& c){ c.log += "off.entry;"; })
        .exit_action_c ([](context& c){ c.log += "off.exit;";  })
    ;

    inline constexpr auto on = maki::state_mold{}
        .entry_action_c([](context& c){ c.log += "on.entry;"; })
        .exit_action_c ([](context& c){ c.log += "on.exit;";  })
    ;

    constexpr auto trans_act = maki::action_c([](context& c){ c.log += "trans;"; });

    inline constexpr auto table = maki::transition_table{}
        (maki::ini, off)
        (off,       on,  maki::event<press>, trans_act)
    ;

    struct conf {
        static constexpr auto value = maki::machine_conf{}
            .transition_tables(table)
            .context_a<context>()
        ;
    };

    using machine_t = maki::machine<conf>;
}

TEST(MakiActions, EntryExitTransitionOrdering) {
    using namespace action_seq_ns;

    auto m = machine_t{};
    // Auto-start runs the entry action of the initial state.
    EXPECT_EQ(m.context().log, "off.entry;");

    m.context().log.clear();
    m.process_event(press{});
    EXPECT_TRUE(m.is<on>());
    EXPECT_EQ(m.context().log, "off.exit;trans;on.entry;");
}


namespace action_sig_ns {
    struct context { std::string log; };
    struct trigger { int payload = 0; };

    inline constexpr auto s0 = maki::state_mold{};
    inline constexpr auto s1 = maki::state_mold{};
    inline constexpr auto s2 = maki::state_mold{};
    inline constexpr auto s3 = maki::state_mold{};
    inline constexpr auto s4 = maki::state_mold{};

    // Namespace-scope hit counters make the no-context signatures (v, e)
    // observable — a broken impl that skips invocation is caught.
    inline int a_v_hits = 0;
    inline int a_e_hits = 0;

    constexpr auto a_v = maki::action_v([]{ ++a_v_hits; });
    constexpr auto a_c = maki::action_c(
        [](context& c){ c.log += "c;"; });
    constexpr auto a_e = maki::action_e(
        [](const trigger& e){ ++a_e_hits; (void)e; });
    constexpr auto a_ce = maki::action_ce(
        [](context& c, const trigger& e){
            c.log += "ce(" + std::to_string(e.payload) + ");";
        });

    inline constexpr auto table = maki::transition_table{}
        (maki::ini, s0)
        (s0, s1, maki::event<trigger>, a_v)
        (s1, s2, maki::event<trigger>, a_c)
        (s2, s3, maki::event<trigger>, a_e)
        (s3, s4, maki::event<trigger>, a_ce)
    ;

    struct conf {
        static constexpr auto value = maki::machine_conf{}
            .transition_tables(table)
            .context_a<context>()
        ;
    };

    using machine_t = maki::machine<conf>;
}

TEST(MakiActions, SignatureVariantsAllCallable) {
    using namespace action_sig_ns;

    a_v_hits = 0;
    a_e_hits = 0;

    auto m = machine_t{};

    m.process_event(trigger{});
    EXPECT_TRUE(m.is<s1>());
    EXPECT_EQ(a_v_hits, 1);
    EXPECT_EQ(m.context().log, "");

    m.process_event(trigger{});
    EXPECT_TRUE(m.is<s2>());
    EXPECT_EQ(m.context().log, "c;");

    m.process_event(trigger{});
    EXPECT_TRUE(m.is<s3>());
    EXPECT_EQ(a_e_hits, 1);
    EXPECT_EQ(m.context().log, "c;");

    m.process_event(trigger{7});
    EXPECT_TRUE(m.is<s4>());
    EXPECT_EQ(m.context().log, "c;ce(7);");
}


namespace entry_by_event_ns {
    struct context { std::string log; };
    struct ev_a{};
    struct ev_b{};

    inline constexpr auto s0 = maki::state_mold{};

    inline constexpr auto s1 = maki::state_mold{}
        .entry_action_c<ev_a>(
            [](context& c){ c.log += "s1.entry(ev_a);"; }
        )
        .entry_action_c<ev_b>(
            [](context& c){ c.log += "s1.entry(ev_b);"; }
        )
    ;

    inline constexpr auto table = maki::transition_table{}
        (maki::ini, s0)
        (s0, s1, maki::event<ev_a>)
        (s1, s0, maki::event<ev_b>)
        (s0, s1, maki::event<ev_b>)
    ;

    struct conf {
        static constexpr auto value = maki::machine_conf{}
            .transition_tables(table)
            .context_a<context>()
        ;
    };

    using machine_t = maki::machine<conf>;
}

TEST(MakiActions, EventTypedEntryActionFiresOnlyForMatchingEvent) {
    using namespace entry_by_event_ns;

    auto m = machine_t{};
    EXPECT_TRUE(m.is<s0>());
    EXPECT_EQ(m.context().log, "");

    m.process_event(ev_a{});
    EXPECT_TRUE(m.is<s1>());
    EXPECT_EQ(m.context().log, "s1.entry(ev_a);");

    m.context().log.clear();
    m.process_event(ev_b{});
    EXPECT_TRUE(m.is<s0>());
    m.process_event(ev_b{});
    EXPECT_TRUE(m.is<s1>());
    EXPECT_EQ(m.context().log, "s1.entry(ev_b);");
}


// ============================================================================
// MakiGuards
// ============================================================================

namespace guard_basic_ns {
    struct context { bool allow = false; };
    struct press{};

    inline constexpr auto off = maki::state_mold{};
    inline constexpr auto on  = maki::state_mold{};

    constexpr auto can_enter = maki::guard_c(
        [](const context& c){ return c.allow; }
    );

    inline constexpr auto table = maki::transition_table{}
        (maki::ini, off)
        (off, on, maki::event<press>, maki::null, can_enter)
    ;

    struct conf {
        static constexpr auto value = maki::machine_conf{}
            .transition_tables(table)
            .context_a<context>()
        ;
    };

    using machine_t = maki::machine<conf>;
}

TEST(MakiGuards, GuardBlocksAndAllows) {
    using namespace guard_basic_ns;

    auto m = machine_t{};
    EXPECT_TRUE(m.is<off>());

    m.process_event(press{});
    EXPECT_TRUE(m.is<off>());

    m.context().allow = true;
    m.process_event(press{});
    EXPECT_TRUE(m.is<on>());
}


// One machine per operator so each operator has a unique "wins" input and
// there are no dead rows in the transition table (&&/||/!= overlap heavily
// on two-var boolean inputs).
namespace guard_ops_ns {
    struct context {};
    struct evt {
        bool a = false;
        bool b = false;
    };

    inline constexpr auto s_off = maki::state_mold{};
    inline constexpr auto s_on  = maki::state_mold{};

    constexpr auto is_a = maki::guard_e([](const evt& e){ return e.a; });
    constexpr auto is_b = maki::guard_e([](const evt& e){ return e.b; });

    inline constexpr auto tt_and = maki::transition_table{}
        (maki::ini, s_off)
        (s_off, s_on, maki::event<evt>, maki::null, is_a && is_b)
    ;
    inline constexpr auto tt_or = maki::transition_table{}
        (maki::ini, s_off)
        (s_off, s_on, maki::event<evt>, maki::null, is_a || is_b)
    ;
    inline constexpr auto tt_xor = maki::transition_table{}
        (maki::ini, s_off)
        (s_off, s_on, maki::event<evt>, maki::null, is_a != is_b)
    ;
    inline constexpr auto tt_not = maki::transition_table{}
        (maki::ini, s_off)
        (s_off, s_on, maki::event<evt>, maki::null, !is_a)
    ;

    struct conf_and {
        static constexpr auto value = maki::machine_conf{}
            .transition_tables(tt_and).context_a<context>();
    };
    struct conf_or {
        static constexpr auto value = maki::machine_conf{}
            .transition_tables(tt_or).context_a<context>();
    };
    struct conf_xor {
        static constexpr auto value = maki::machine_conf{}
            .transition_tables(tt_xor).context_a<context>();
    };
    struct conf_not {
        static constexpr auto value = maki::machine_conf{}
            .transition_tables(tt_not).context_a<context>();
    };

    using m_and = maki::machine<conf_and>;
    using m_or  = maki::machine<conf_or>;
    using m_xor = maki::machine<conf_xor>;
    using m_not = maki::machine<conf_not>;
}

TEST(MakiGuards, BooleanOperatorComposition) {
    using namespace guard_ops_ns;

    { auto m = m_and{}; m.process_event(evt{true,  true});  EXPECT_TRUE (m.is<s_on>()); }
    { auto m = m_and{}; m.process_event(evt{true,  false}); EXPECT_FALSE(m.is<s_on>()); }
    { auto m = m_and{}; m.process_event(evt{false, true});  EXPECT_FALSE(m.is<s_on>()); }
    { auto m = m_and{}; m.process_event(evt{false, false}); EXPECT_FALSE(m.is<s_on>()); }

    { auto m = m_or{};  m.process_event(evt{true,  true});  EXPECT_TRUE (m.is<s_on>()); }
    { auto m = m_or{};  m.process_event(evt{true,  false}); EXPECT_TRUE (m.is<s_on>()); }
    { auto m = m_or{};  m.process_event(evt{false, true});  EXPECT_TRUE (m.is<s_on>()); }
    { auto m = m_or{};  m.process_event(evt{false, false}); EXPECT_FALSE(m.is<s_on>()); }

    { auto m = m_xor{}; m.process_event(evt{true,  true});  EXPECT_FALSE(m.is<s_on>()); }
    { auto m = m_xor{}; m.process_event(evt{true,  false}); EXPECT_TRUE (m.is<s_on>()); }
    { auto m = m_xor{}; m.process_event(evt{false, true});  EXPECT_TRUE (m.is<s_on>()); }
    { auto m = m_xor{}; m.process_event(evt{false, false}); EXPECT_FALSE(m.is<s_on>()); }

    { auto m = m_not{}; m.process_event(evt{true,  false}); EXPECT_FALSE(m.is<s_on>()); }
    { auto m = m_not{}; m.process_event(evt{false, false}); EXPECT_TRUE (m.is<s_on>()); }
}


namespace guard_sig_ns {
    struct context { int limit = 0; };
    struct trigger { int val = 0; };

    inline constexpr auto s0 = maki::state_mold{};
    inline constexpr auto sv = maki::state_mold{};
    inline constexpr auto sc = maki::state_mold{};
    inline constexpr auto se = maki::state_mold{};

    inline int g_v_hits = 0;

    constexpr auto g_v = maki::guard_v([]{ ++g_v_hits; return true; });
    constexpr auto g_c = maki::guard_c([](const context& c){ return c.limit > 0; });
    constexpr auto g_e = maki::guard_e([](const trigger& e){ return e.val > 100; });

    inline constexpr auto table = maki::transition_table{}
        (maki::ini, s0)
        (s0, se, maki::event<trigger>, maki::null, g_e)
        (s0, sc, maki::event<trigger>, maki::null, g_c)
        (s0, sv, maki::event<trigger>, maki::null, g_v)
    ;

    struct conf {
        static constexpr auto value = maki::machine_conf{}
            .transition_tables(table)
            .context_a<context>()
        ;
    };

    using machine_t = maki::machine<conf>;
}

TEST(MakiGuards, SignatureVariantsAllInvocable) {
    using namespace guard_sig_ns;

    {
        auto m = machine_t{};
        m.process_event(trigger{200});
        EXPECT_TRUE(m.is<se>());
    }
    {
        auto m = machine_t{};
        m.context().limit = 5;
        m.process_event(trigger{50});
        EXPECT_TRUE(m.is<sc>());
    }
    {
        g_v_hits = 0;
        auto m = machine_t{};
        m.process_event(trigger{50});
        EXPECT_TRUE(m.is<sv>());
        EXPECT_GE(g_v_hits, 1);
    }
}


// ============================================================================
// MakiInternal + MakiCompletion
// ============================================================================

namespace internal_ns {
    struct context {
        int counter = 0;
        std::string log;
    };

    struct tick{};

    inline constexpr auto running = maki::state_mold{}
        .entry_action_c([](context& c){ c.log += "entry;"; })
        .exit_action_c ([](context& c){ c.log += "exit;";  })
        .internal_action_c<tick>(
            [](context& c){ ++c.counter; }
        )
    ;

    inline constexpr auto table = maki::transition_table{}
        (maki::ini, running)
    ;

    struct conf {
        static constexpr auto value = maki::machine_conf{}
            .transition_tables(table)
            .context_a<context>()
        ;
    };

    using machine_t = maki::machine<conf>;
}

TEST(MakiInternal, InternalActionDoesNotReentryState) {
    using namespace internal_ns;

    auto m = machine_t{};
    EXPECT_EQ(m.context().log, "entry;");

    m.context().log.clear();
    for (int i = 0; i < 5; ++i) {
        m.process_event(tick{});
    }
    EXPECT_EQ(m.context().counter, 5);
    EXPECT_EQ(m.context().log, "");
    EXPECT_TRUE(m.is<running>());
}


namespace internal_in_table_ns {
    struct context { std::string log; };
    struct pulse{};

    inline constexpr auto s = maki::state_mold{}
        .entry_action_c([](context& c){ c.log += "entry;"; })
        .exit_action_c ([](context& c){ c.log += "exit;";  })
    ;

    constexpr auto do_pulse = maki::action_c([](context& c){ c.log += "pulse;"; });

    inline constexpr auto table = maki::transition_table{}
        (maki::ini, s)
        (s, maki::null, maki::event<pulse>, do_pulse)
    ;

    struct conf {
        static constexpr auto value = maki::machine_conf{}
            .transition_tables(table)
            .context_a<context>()
        ;
    };

    using machine_t = maki::machine<conf>;
}

TEST(MakiInternal, NullTargetInTableIsInternalTransition) {
    using namespace internal_in_table_ns;

    auto m = machine_t{};
    EXPECT_EQ(m.context().log, "entry;");

    m.context().log.clear();
    m.process_event(pulse{});
    EXPECT_EQ(m.context().log, "pulse;");
    EXPECT_TRUE(m.is<s>());
}


namespace completion_ns {
    struct context { std::string log; };
    struct go{};

    inline constexpr auto s0 = maki::state_mold{};
    inline constexpr auto s1 = maki::state_mold{};
    inline constexpr auto s2 = maki::state_mold{};
    inline constexpr auto s3 = maki::state_mold{};

    constexpr auto note1 = maki::action_c([](context& c){ c.log += "1;"; });
    constexpr auto note2 = maki::action_c([](context& c){ c.log += "2;"; });

    inline constexpr auto table = maki::transition_table{}
        (maki::ini, s0)
        (s0, s1, maki::event<go>)
        (s1, s2, maki::null, note1)
        (s2, s3, maki::null, note2)
    ;

    struct conf {
        static constexpr auto value = maki::machine_conf{}
            .transition_tables(table)
            .context_a<context>()
        ;
    };

    using machine_t = maki::machine<conf>;
}

TEST(MakiCompletion, ChainedCompletionTransitions) {
    using namespace completion_ns;

    auto m = machine_t{};
    EXPECT_TRUE(m.is<s0>());

    m.process_event(go{});
    EXPECT_TRUE(m.is<s3>());
    EXPECT_EQ(m.context().log, "1;2;");
}


// ============================================================================
// MakiTable — state_set source
// ============================================================================

namespace state_set_source_ns {
    struct context {};
    struct power_off{};
    struct next{};

    inline constexpr auto off   = maki::state_mold{};
    inline constexpr auto red   = maki::state_mold{};
    inline constexpr auto green = maki::state_mold{};
    inline constexpr auto blue  = maki::state_mold{};

    inline constexpr auto table = maki::transition_table{}
        (maki::ini, off)
        (off,   red,   maki::event<next>)
        (red,   green, maki::event<next>)
        (green, blue,  maki::event<next>)
        (!off,  off,   maki::event<power_off>)
    ;

    struct conf {
        static constexpr auto value = maki::machine_conf{}
            .transition_tables(table)
            .context_a<context>()
        ;
    };

    using machine_t = maki::machine<conf>;
}

TEST(MakiTable, SourceIsStateSet) {
    using namespace state_set_source_ns;

    auto m = machine_t{};
    EXPECT_TRUE(m.is<off>());

    m.process_event(power_off{});
    EXPECT_TRUE(m.is<off>());

    m.process_event(next{}); EXPECT_TRUE(m.is<red>());
    m.process_event(power_off{}); EXPECT_TRUE(m.is<off>());

    m.process_event(next{}); m.process_event(next{});
    EXPECT_TRUE(m.is<green>());
    m.process_event(power_off{}); EXPECT_TRUE(m.is<off>());

    m.process_event(next{}); m.process_event(next{}); m.process_event(next{});
    EXPECT_TRUE(m.is<blue>());
    m.process_event(power_off{}); EXPECT_TRUE(m.is<off>());
}
