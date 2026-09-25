// Utility layer tests: cs_new/ptr/wptr shared-ptr lifetime, strfmt printf-
// style formatter, async_result future+continuation semantics, and
// asio_service scheduler firing + cancellation. These are the primitives on
// which every other cornerstone subsystem is built.

#include <gtest/gtest.h>

#include <cornerstone/cornerstone.hxx>

#include <atomic>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <exception>
#include <fstream>
#include <memory>
#include <string>
#include <thread>
#include <vector>

using namespace cornerstone;

namespace ptr_test
{
// File-scoped destruction counters so the ptr test can observe when derived
// vs base destructors fire.
inline int& base_dtor()
{
    static int n = 0;
    return n;
}
inline int& derived_dtor()
{
    static int n = 0;
    return n;
}

struct Base
{
    Base(int v) : value(v) {}
    virtual ~Base() { ++base_dtor(); }
    virtual int who() { return 1; }
    int value;
};

struct Derived : Base
{
    Derived(int v) : Base(v + 10) {}
    ~Derived() override { ++derived_dtor(); }
    int who() override { return 2; }
};

struct SafeTarget : std::enable_shared_from_this<SafeTarget>
{
    ptr<SafeTarget> self() { return shared_from_this(); }
};
} // namespace ptr_test

// TEST 16 — cs_new<T>(args) forwards to std::make_shared, so ptr<Base> holding
// a Derived must virtual-dispatch through who(), and the Derived destructor
// must fire when the last ptr is dropped. wptr::lock() must return a live
// ptr while any strong ref exists, and null after they all go.
TEST(Utility, PtrSharedWeakLifetime)
{
    using namespace ptr_test;
    base_dtor() = 0;
    derived_dtor() = 0;

    wptr<Derived> weak;
    {
        ptr<Base> b = cs_new<Derived>(5);
        EXPECT_EQ(b->value, 15);
        EXPECT_EQ(b->who(), 2);

        // enable_shared_from_this integration
        ptr<SafeTarget> s = cs_new<SafeTarget>();
        ptr<SafeTarget> s2 = s->self();
        EXPECT_EQ(s.get(), s2.get());

        ptr<Derived> d = cs_new<Derived>(7);
        weak = d;
        ptr<Derived> locked = weak.lock();
        ASSERT_NE(locked, nullptr);
        EXPECT_EQ(locked->value, 17);
    }
    EXPECT_TRUE(weak.expired());
    EXPECT_EQ(weak.lock(), nullptr);

    // Both Derived instances (through b and through d) must have destroyed.
    EXPECT_EQ(derived_dtor(), 2);
    // Base destructor fires once per Derived (virtual dtor chain).
    EXPECT_EQ(base_dtor(), 2);
}

// TEST 17 — strfmt<N> is a printf-style formatter with an internal
// N-byte buffer. Successive fmt() calls must overwrite the buffer and
// return a pointer to the freshly-formatted string.
TEST(Utility, StrfmtVariadicFormats)
{
    strfmt<32> f("value=%d name=%s");
    const char* s1 = f.fmt(42, "hello");
    EXPECT_STREQ(s1, "value=42 name=hello");

    strfmt<64> tri("a=%d b=%d c=%d");
    EXPECT_STREQ(tri.fmt(1, 2, 3), "a=1 b=2 c=3");
}

// TEST 18 — async_result<T> combines a futures-style get() (blocks until
// set_result) with a fluent when_ready(handler) continuation. Both must
// work in the sync-set-then-observe and set-later-and-wait orderings, and
// an exception passed to set_result must propagate through both get()
// (as throw) and when_ready (as the second handler argument).
TEST(Utility, AsyncResultSyncAsyncExceptions)
{
    ptr<std::exception> no_err;

    // Sync: set before observing.
    {
        auto p = cs_new<async_result<int>>();
        int v = 42;
        p->set_result(v, no_err);
        EXPECT_EQ(p->get(), 42);

        std::atomic<bool> handler_ran{false};
        p->when_ready([&](int result, const ptr<std::exception>& err) {
            EXPECT_EQ(result, 42);
            EXPECT_EQ(err, nullptr);
            handler_ran = true;
        });
        EXPECT_TRUE(handler_ran.load());
    }

    // Async: register handler first, set later on another thread.
    {
        auto p = cs_new<async_result<int>>();
        std::atomic<bool> handler_ran{false};
        p->when_ready([&](int result, const ptr<std::exception>&) {
            EXPECT_EQ(result, 100);
            handler_ran = true;
        });
        std::thread t([p]() {
            std::this_thread::sleep_for(std::chrono::milliseconds(50));
            ptr<std::exception> no_err_local;
            int v = 100;
            p->set_result(v, no_err_local);
        });
        EXPECT_EQ(p->get(), 100);
        t.join();
        EXPECT_TRUE(handler_ran.load());
    }

    // Exception path: set_result with a non-null exception -> get() throws
    // (as ptr<std::exception>) and when_ready sees the exception.
    {
        auto p = cs_new<async_result<int>>();
        ptr<std::exception> ex = cs_new<std::bad_exception>();
        std::atomic<bool> handler_ran{false};
        p->when_ready([&](int, const ptr<std::exception>& e) {
            EXPECT_EQ(e.get(), ex.get());
            handler_ran = true;
        });
        int v = 0;
        p->set_result(v, ex);
        EXPECT_TRUE(handler_ran.load());

        bool caught = false;
        try
        {
            p->get();
        }
        catch (const ptr<std::exception>& thrown)
        {
            EXPECT_EQ(thrown.get(), ex.get());
            caught = true;
        }
        EXPECT_TRUE(caught);
    }
}

// TEST 19 — asio_service.schedule(task, ms) fires task->exec() after ms
// milliseconds. cancel(task) before its fire time must suppress exec().
// Re-scheduling a cancelled task must reset and fire again.
TEST(Utility, SchedulerFireAndCancel)
{
    asio_service svc;
    std::atomic<int> counter{0};

    timer_task<void>::executor handler = [&counter]() { counter++; };
    ptr<delayed_task> task = cs_new<timer_task<void>>(handler);

    // Schedule +100 ms, wait +200, expect one fire.
    svc.schedule(task, 100);
    std::this_thread::sleep_for(std::chrono::milliseconds(250));
    EXPECT_EQ(counter.load(), 1);

    // Reset (asio_service internals) and schedule +200; cancel after 50 ms
    // (before the timer fires); wait +250 more; counter must stay at 1.
    task->reset();
    svc.schedule(task, 200);
    std::this_thread::sleep_for(std::chrono::milliseconds(50));
    svc.cancel(task);
    std::this_thread::sleep_for(std::chrono::milliseconds(250));
    EXPECT_EQ(counter.load(), 1);

    // Reset + schedule again — the cancel must not have poisoned the task.
    task->reset();
    svc.schedule(task, 100);
    std::this_thread::sleep_for(std::chrono::milliseconds(250));
    EXPECT_EQ(counter.load(), 2);

    svc.stop();
    std::this_thread::sleep_for(std::chrono::milliseconds(200));
}

// TEST 20 — asio_service::create_logger(level, filename) returns a logger
// that filters messages by severity: only calls at or above the configured
// level are emitted. Setting level=warnning must drop debug + info lines
// and emit only warn + err lines; level=debug must emit all four. This is
// the one behavioral contract worth pinning; the exact line format (e.g.
// per-line timestamp) is not part of the specification.
TEST(Utility, AsioLoggerFiltersByLevel)
{
    const std::string debug_path = "/tmp/cornerstone_test_logger_debug.log";
    const std::string warn_path = "/tmp/cornerstone_test_logger_warn.log";
    std::remove(debug_path.c_str());
    std::remove(warn_path.c_str());

    auto contains = [](const std::string& path, const std::string& needle) {
        std::ifstream in(path);
        if (!in) return false;
        std::string line;
        while (std::getline(in, line))
            if (line.find(needle) != std::string::npos) return true;
        return false;
    };

    // Level = debug: all four calls emitted.
    {
        asio_service svc;
        ptr<logger> lg = svc.create_logger(asio_service::log_level::debug, debug_path);
        lg->debug("D_LINE_X");
        lg->info("I_LINE_X");
        lg->warn("W_LINE_X");
        lg->err("E_LINE_X");
        svc.stop();
        std::this_thread::sleep_for(std::chrono::milliseconds(200));
    }
    EXPECT_TRUE(contains(debug_path, "D_LINE_X")) << "debug line missing at level=debug";
    EXPECT_TRUE(contains(debug_path, "I_LINE_X")) << "info line missing at level=debug";
    EXPECT_TRUE(contains(debug_path, "W_LINE_X")) << "warn line missing at level=debug";
    EXPECT_TRUE(contains(debug_path, "E_LINE_X")) << "err line missing at level=debug";

    // Level = warnning: debug + info must be dropped; warn + err kept.
    {
        asio_service svc;
        ptr<logger> lg = svc.create_logger(asio_service::log_level::warnning, warn_path);
        lg->debug("D_LINE_Y");
        lg->info("I_LINE_Y");
        lg->warn("W_LINE_Y");
        lg->err("E_LINE_Y");
        svc.stop();
        std::this_thread::sleep_for(std::chrono::milliseconds(200));
    }
    EXPECT_FALSE(contains(warn_path, "D_LINE_Y")) << "debug line must be filtered at level=warnning";
    EXPECT_FALSE(contains(warn_path, "I_LINE_Y")) << "info line must be filtered at level=warnning";
    EXPECT_TRUE(contains(warn_path, "W_LINE_Y")) << "warn line must be present at level=warnning";
    EXPECT_TRUE(contains(warn_path, "E_LINE_Y")) << "err line must be present at level=warnning";

    std::remove(debug_path.c_str());
    std::remove(warn_path.c_str());
}
