/* Group: signals — core propagation, glitch-freedom, value-based pruning. */
#include "harness.h"
#include <ureact/ureact.hpp>
using namespace ureact;

static void t_propagation_and_suppression(void) {
    context ctx;
    var_signal<int> b = make_var(ctx, 1), c = make_var(ctx, 2);
    ureact::signal<int> a = b + c;
    int obs = 0; auto o = observe(a, [&](int){ ++obs; });
    CHECK(a.get() == 3, "init a=%d (expected 3)", a.get());
    obs = 0; b <<= 10;
    CHECK(a.get() == 12 && obs == 1, "after b<<=10 a=%d obs=%d (expected 12,1)", a.get(), obs);
    obs = 0; b <<= 10;
    CHECK(obs == 0, "same-value must be suppressed, observer fired %d", obs);
}

static void t_glitch_free(void) {
    context ctx;
    auto b = make_var(ctx, 1);
    auto x = lift(b, [](int v){ return v + 1; });
    auto y = lift(b, [](int v){ return v * 2; });
    int calc = 0;
    auto d = lift(with(x, y), [&](int xx, int yy){ ++calc; return xx + yy; });
    int obs = 0; auto o = observe(d, [&](int){ ++obs; });
    calc = 0; obs = 0; b <<= 10;
    CHECK(d.get() == 31 && calc == 1 && obs == 1,
          "diamond d=%d recompute=%d obs=%d (expected 31,1,1)", d.get(), calc, obs);
}

static void t_value_pruning(void) {
    context ctx;
    auto b = make_var(ctx, 1);
    auto z = lift(b, [](int v){ return v > 0 ? 7 : -7; });
    int wcalc = 0;
    auto w = lift(z, [&](int zz){ ++wcalc; return zz * 100; });
    wcalc = 0; b <<= 40;
    CHECK(w.get() == 700 && wcalc == 0, "pruning w=%d recompute=%d (expected 700,0)", w.get(), wcalc);
}

static const TestEntry TESTS[] = {
    {"test_propagation_and_suppression", t_propagation_and_suppression},
    {"test_glitch_free_diamond", t_glitch_free},
    {"test_value_based_pruning", t_value_pruning},
};
int main(int argc, char **argv) {
    return run_group(TESTS, (int)(sizeof(TESTS)/sizeof(*TESTS)), argc > 1 ? argv[1] : "/dev/stdout") >= 0 ? 0 : 1;
}
