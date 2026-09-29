/* Group: dynamic — flatten tracking, detachment, and glitch-free re-leveling. */
#include "harness.h"
#include <ureact/ureact.hpp>
using namespace ureact;

static void t_flatten_switch(void) {
    context ctx;
    var_signal<int> inner1v = make_var(ctx, 100), inner2v = make_var(ctx, 200);
    ureact::signal<int> inner1 = inner1v, inner2 = inner2v;
    var_signal<ureact::signal<int>> outer = make_var(ctx, inner1);
    ureact::signal<int> flat = flatten(outer);
    int obs = 0; auto o = observe(flat, [&](int){ ++obs; });
    CHECK(flat.get() == 100, "flatten init=%d", flat.get());
    obs = 0; inner1v <<= 150; CHECK(flat.get() == 150 && obs == 1, "inner-change %d,%d", flat.get(), obs);
    obs = 0; outer <<= inner2; CHECK(flat.get() == 200 && obs == 1, "switch %d,%d", flat.get(), obs);
    obs = 0; inner1v <<= 999; CHECK(flat.get() == 200 && obs == 0, "old-inner %d,%d", flat.get(), obs);
}

static void t_flatten_levelshift(void) {
    context ctx;
    ureact::signal<int> shallow = make_var(ctx, 200);
    auto base = make_var(ctx, 1);
    ureact::signal<int> deep = lift(lift(lift(base,
                    [](int v){return v + 1;}), [](int v){return v * 2;}), [](int v){return v + 3;});
    var_signal<ureact::signal<int>> sel = make_var(ctx, shallow);
    ureact::signal<int> flat2 = flatten(sel);
    auto combo = lift(with(flat2, deep), [](int a, int b){ return a + b; });
    sel <<= deep;
    CHECK(flat2.get() == 7 && combo.get() == 14, "level-shift flat2=%d combo=%d (expected 7,14)", flat2.get(), combo.get());
}

static const TestEntry TESTS[] = {
    {"test_flatten_dynamic_switch", t_flatten_switch},
    {"test_flatten_level_shift", t_flatten_levelshift},
};
int main(int argc, char **argv) {
    return run_group(TESTS, (int)(sizeof(TESTS)/sizeof(*TESTS)), argc > 1 ? argv[1] : "/dev/stdout") >= 0 ? 0 : 1;
}
