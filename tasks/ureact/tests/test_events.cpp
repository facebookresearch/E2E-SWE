/* Group: events — the events surface and its interaction with (nested) transactions. */
#include "harness.h"
#include <ureact/ureact.hpp>
#include <vector>
using namespace ureact;

static void t_fold_txn(void) {
    context ctx;
    auto s = make_source<int>(ctx);
    int calls = 0;
    auto sum = fold(s, 0, [&](int e, int a){ ++calls; return a + e; });
    calls = 0;
    { transaction t(ctx); s.emit(10); s.emit(20); s.emit(30); }
    CHECK(sum.get() == 60 && calls == 3, "fold_txn sum=%d calls=%d (expected 60,3)", sum.get(), calls);
}

static void t_fold_mixed(void) {
    context ctx;
    auto s = make_source<int>(ctx);
    auto sum = fold(s, 0, [](int e, int a){ return a + e; });
    int obs = 0; auto o = observe(sum, [&](int){ ++obs; });
    s.emit(5); { transaction t(ctx); s.emit(10); s.emit(20); } s.emit(3);
    CHECK(sum.get() == 38 && obs == 3, "fold_mixed sum=%d obs=%d (expected 38,3)", sum.get(), obs);
}

static void t_merge_txn(void) {
    context ctx;
    auto a = make_source<int>(ctx), b = make_source<int>(ctx);
    auto m = merge(a, b);
    auto sum = fold(m, 0, [](int e, int x){ return x + e; });
    auto cnt = fold(m, 0, [](int, int x){ return x + 1; });
    { transaction t(ctx); a.emit(1); b.emit(2); a.emit(3); }
    CHECK(sum.get() == 6 && cnt.get() == 3, "merge_txn sum=%d cnt=%d (expected 6,3)", sum.get(), cnt.get());
}

static void t_filter_txn(void) {
    context ctx;
    auto s = make_source<int>(ctx);
    auto evens = filter(s, [](int e){ return e % 2 == 0; });   /* keep handles in scope */
    auto sum = fold(evens, 0, [](int e, int a){ return a + e; });
    { transaction t(ctx); for (int i = 1; i <= 6; ++i) s.emit(i); }
    CHECK(sum.get() == 12, "filter_txn sum=%d (expected 12)", sum.get());
}

static void t_transform_txn(void) {
    context ctx;
    auto s = make_source<int>(ctx);
    auto scaled = transform(s, [](int e){ return e * 10; });
    auto sum = fold(scaled, 0, [](int e, int a){ return a + e; });
    { transaction t(ctx); s.emit(1); s.emit(2); s.emit(3); }
    CHECK(sum.get() == 60, "transform_txn sum=%d (expected 60)", sum.get());
}

static void t_filter_transform_txn(void) {
    context ctx;
    auto s = make_source<int>(ctx);
    auto evens = filter(s, [](int e){ return e % 2 == 0; });
    auto sq = transform(evens, [](int e){ return e * e; });
    auto sum = fold(sq, 0, [](int e, int a){ return a + e; });
    { transaction t(ctx); for (int i = 1; i <= 6; ++i) s.emit(i); }
    CHECK(sum.get() == 56, "filter_transform_txn sum=%d (expected 56)", sum.get());
}

static void t_hold_txn_last(void) {
    context ctx;
    auto s = make_source<int>(ctx);
    ureact::signal<int> h = hold(s, -1);
    { transaction t(ctx); s.emit(7); s.emit(8); s.emit(9); }
    CHECK(h.get() == 9, "hold_txn last=%d (expected 9, last of batch)", h.get());
}

static void t_hold_lift_txn(void) {
    context ctx;
    auto s = make_source<int>(ctx);
    ureact::signal<int> h = hold(s, 0);
    int lc = 0; auto d = lift(h, [&](int v){ ++lc; return v * 10; });
    lc = 0;
    { transaction t(ctx); s.emit(1); s.emit(2); s.emit(3); }
    CHECK(d.get() == 30 && lc == 1, "hold_lift_txn d=%d lift_calls=%d (expected 30,1)", d.get(), lc);
}

static void t_two_folds_txn(void) {
    context ctx;
    auto s = make_source<int>(ctx);
    auto sum = fold(s, 0, [](int e, int a){ return a + e; });
    auto cnt = fold(s, 0, [](int, int a){ return a + 1; });
    { transaction t(ctx); s.emit(4); s.emit(5); s.emit(6); }
    CHECK(sum.get() == 15 && cnt.get() == 3, "two_folds sum=%d cnt=%d (expected 15,3)", sum.get(), cnt.get());
}

static void t_observe_order_txn(void) {
    context ctx;
    auto s = make_source<int>(ctx);
    std::vector<int> g; auto o = observe(s, [&](int e){ g.push_back(e); });
    { transaction t(ctx); s.emit(1); s.emit(2); s.emit(3); }
    CHECK(g.size() == 3 && g[0] == 1 && g[1] == 2 && g[2] == 3,
          "observe_order_txn n=%zu (expected [1,2,3])", g.size());
}

static void t_snapshot_txn(void) {
    context ctx;
    auto trig = make_source<int>(ctx);
    auto tgt = make_var(ctx, 42);
    ureact::signal<int> snap = snapshot(trig, tgt);
    { transaction t(ctx); tgt <<= 50; trig.emit(0); }
    CHECK(snap.get() == 50, "snapshot_txn=%d (expected 50, samples batched target)", snap.get());
}

static void t_nested_txn_events(void) {
    context ctx;
    auto s = make_source<int>(ctx);
    auto sum = fold(s, 0, [](int e, int a){ return a + e; });
    int obs = 0; auto o = observe(sum, [&](int){ ++obs; });
    obs = 0;
    { transaction t1(ctx); s.emit(1); { transaction t2(ctx); s.emit(2); } s.emit(3); }
    CHECK(sum.get() == 6 && obs == 1, "nested_txn sum=%d obs=%d (expected 6,1 at outermost end)", sum.get(), obs);
}

static void t_empty_txn(void) {
    context ctx;
    auto s = make_source<int>(ctx);
    int obs = 0; auto o = observe(s, [&](int){ ++obs; });
    { transaction t(ctx); }
    CHECK(obs == 0, "empty_txn obs=%d (expected 0)", obs);
}

/* --- composed / deeper transaction×events variations --- */

/* value-based pruning through events: a batch whose held value nets back to the
 * current value must not recompute downstream. */
static void t_prune_events(void) {
    context ctx;
    auto s = make_source<int>(ctx);
    ureact::signal<int> h = hold(s, 5);
    int dc = 0; auto d = lift(h, [&](int v){ ++dc; return v * 10; });
    dc = 0;
    { transaction t(ctx); s.emit(7); s.emit(5); }   /* last value 5 == current */
    CHECK(d.get() == 50 && dc == 0, "prune_events d=%d recompute=%d (expected 50,0)", d.get(), dc);
}

/* a signal change and event emissions batched together in one transaction. */
static void t_mixed_signal_event(void) {
    context ctx;
    auto v = make_var(ctx, 0);
    auto s = make_source<int>(ctx);
    auto total = fold(s, 0, [](int e, int a){ return a + e; });
    int calc = 0;
    auto combined = lift(with(v, total), [&](int a, int b){ ++calc; return a + b; });
    int obs = 0; auto o = observe(combined, [&](int){ ++obs; });
    calc = 0; obs = 0;
    { transaction t(ctx); v <<= 10; s.emit(1); s.emit(2); }
    CHECK(combined.get() == 13 && calc == 1 && obs == 1,
          "mixed combined=%d recompute=%d obs=%d (expected 13,1,1)", combined.get(), calc, obs);
}

/* longer chain fold -> lift -> observe, batched: one recompute, one notification. */
static void t_chain_in_txn(void) {
    context ctx;
    auto s = make_source<int>(ctx);
    auto sum = fold(s, 0, [](int e, int a){ return a + e; });
    int lc = 0; auto scaled = lift(sum, [&](int v){ ++lc; return v * 2; });
    int obs = 0; auto o = observe(scaled, [&](int){ ++obs; });
    lc = 0; obs = 0;
    { transaction t(ctx); s.emit(1); s.emit(2); s.emit(3); }
    CHECK(scaled.get() == 12 && lc == 1 && obs == 1,
          "chain scaled=%d recompute=%d obs=%d (expected 12,1,1)", scaled.get(), lc, obs);
}

/* merge of three sources, all emitted into one transaction. */
static void t_merge3_in_txn(void) {
    context ctx;
    auto a = make_source<int>(ctx), b = make_source<int>(ctx), c = make_source<int>(ctx);
    auto m = merge(a, b, c);
    auto sum = fold(m, 0, [](int e, int x){ return x + e; });
    auto cnt = fold(m, 0, [](int, int x){ return x + 1; });
    { transaction t(ctx); a.emit(1); b.emit(2); c.emit(3); a.emit(4); }
    CHECK(sum.get() == 10 && cnt.get() == 4, "merge3 sum=%d cnt=%d (expected 10,4)", sum.get(), cnt.get());
}

/* accumulator state must carry correctly across two separate transactions. */
static void t_two_sequential_txns(void) {
    context ctx;
    auto s = make_source<int>(ctx);
    auto sum = fold(s, 0, [](int e, int a){ return a + e; });
    { transaction t(ctx); s.emit(1); s.emit(2); }
    int mid = sum.get();
    { transaction t(ctx); s.emit(3); s.emit(4); }
    CHECK(mid == 3 && sum.get() == 10, "two_txn mid=%d final=%d (expected 3,10)", mid, sum.get());
}

static const TestEntry TESTS[] = {
    {"test_fold_in_transaction", t_fold_txn},
    {"test_fold_mixed_inside_outside_txn", t_fold_mixed},
    {"test_merge_in_transaction", t_merge_txn},
    {"test_filter_in_transaction", t_filter_txn},
    {"test_transform_in_transaction", t_transform_txn},
    {"test_filter_transform_in_transaction", t_filter_transform_txn},
    {"test_hold_last_of_batch", t_hold_txn_last},
    {"test_hold_lift_in_transaction", t_hold_lift_txn},
    {"test_two_folds_in_transaction", t_two_folds_txn},
    {"test_observe_order_in_transaction", t_observe_order_txn},
    {"test_snapshot_in_transaction", t_snapshot_txn},
    {"test_nested_transaction_events", t_nested_txn_events},
    {"test_empty_transaction", t_empty_txn},
    {"test_value_pruning_through_events", t_prune_events},
    {"test_mixed_signal_and_event_in_txn", t_mixed_signal_event},
    {"test_chain_fold_lift_observe_in_txn", t_chain_in_txn},
    {"test_merge_three_sources_in_txn", t_merge3_in_txn},
    {"test_two_sequential_transactions", t_two_sequential_txns},
};
int main(int argc, char **argv) {
    return run_group(TESTS, (int)(sizeof(TESTS)/sizeof(*TESTS)), argc > 1 ? argv[1] : "/dev/stdout") >= 0 ? 0 : 1;
}
