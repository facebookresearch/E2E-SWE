/*
 * C-native behavioral test for the units library. Builds a unit system through
 * the public API, asserts observable behavior (numeric conversions, convertibility,
 * status codes) per test, and writes a CTRF report to $CTRF_PATH (default
 * /logs/verifier/ctrf.json). Exit status is 0 iff every test passes.
 *
 * Expected values are derived from the ground-truth library. Assertions are on
 * behavior only — never on textual surface form.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include "udunits2.h"
#include "converter.h"

static ut_system *sys;
static ut_unit *meter, *kg, *second, *kelvin, *radian, *one, *celsius, *km, *watt, *mW, *bel;

typedef struct { const char* name; int passed; char msg[400]; } Result;
static Result R[64];
static int NR = 0;
static Result* cur;

#define FAIL(...) do { snprintf(cur->msg, sizeof cur->msg, __VA_ARGS__); cur->passed = 0; return; } while (0)
#define CHECK(c, ...) do { if (!(c)) FAIL(__VA_ARGS__); } while (0)

/* Relative tolerance ~1e-6 (≈ 6 significant figures): tight enough to catch real
 * errors, lenient enough not to reject correct answers carrying float noise from
 * log/pow conversion paths. */
static int approx(double a, double b) { return fabs(a - b) <= 1e-6 * (1.0 + fabs(b)); }

/* Convert value through the from->to converter; -999999 sentinel if not convertible. */
static double conv(const ut_unit* f, ut_unit* t, double v) {
    cv_converter* c = ut_get_converter((ut_unit*)f, t);
    if (!c) return -999999.0;
    return cv_convert_double(c, v);
}

static void setup(void) {
    sys = ut_new_system();
    one = ut_get_dimensionless_unit_one(sys);
    meter = ut_new_base_unit(sys);
    kg = ut_new_base_unit(sys);
    second = ut_new_base_unit(sys); ut_set_second(second);
    kelvin = ut_new_base_unit(sys);
    radian = ut_new_dimensionless_unit(sys);
    celsius = ut_offset(kelvin, 273.15);
    km = ut_scale(1000.0, meter);
    watt = ut_multiply(ut_multiply(ut_raise(meter, 2), kg), ut_raise(second, -3));
    mW = ut_scale(0.001, watt);
    bel = ut_log(10.0, mW);
}

static void t_offset_dropped(void) {
    ut_unit* a = ut_multiply(meter, celsius); ut_unit* b = ut_multiply(meter, kelvin);
    CHECK(approx(conv(a, b, 5), 5) && approx(conv(a, b, 100), 100), "m*degC != m*K (offset not dropped)");
    ut_unit* a2 = ut_raise(celsius, 3); ut_unit* b2 = ut_raise(kelvin, 3);
    CHECK(approx(conv(a2, b2, 5), 5) && approx(conv(a2, b2, 100), 100), "degC^3 != K^3 (offset not dropped)");
}

static void t_product_cancels(void) {
    ut_unit* x = ut_divide(ut_raise(meter, 2), ut_raise(second, 2));
    ut_unit* y = ut_divide(x, x);
    CHECK(ut_is_dimensionless(y) == 1, "cancelled product not dimensionless");
    CHECK(ut_are_convertible(y, one) == 1, "cancelled product not convertible to one");
}

static void t_root_powers(void) {
    ut_unit* u = ut_root(ut_raise(meter, 2), 2);
    CHECK(u != NULL && approx(conv(u, meter, 5), 5), "root(m^2,2) not m");
    ut_unit* bad = ut_root(ut_raise(meter, 3), 2);
    CHECK(bad == NULL && ut_get_status() == UT_MEANINGLESS, "root of non-divisible powers not MEANINGLESS");
}

static void t_log_legality(void) {
    CHECK(ut_raise(bel, 2) == NULL && ut_get_status() == UT_MEANINGLESS, "raise(log) not MEANINGLESS");
    CHECK(ut_root(bel, 2) == NULL && ut_get_status() == UT_MEANINGLESS, "root(log) not MEANINGLESS");
    CHECK(ut_multiply(bel, meter) == NULL && ut_get_status() == UT_MEANINGLESS, "log*nondimensionless not MEANINGLESS");
    CHECK(ut_multiply(bel, radian) != NULL, "log*dimensionless not allowed");
}

static void t_kelvin_celsius(void) {
    CHECK(approx(conv(kelvin, celsius, 273.15), 0) && approx(conv(kelvin, celsius, 0), -273.15), "kelvin->celsius wrong");
    CHECK(approx(conv(celsius, kelvin, 0), 273.15) && approx(conv(celsius, kelvin, 100), 373.15), "celsius->kelvin wrong");
}

static void t_combine_scale_offset(void) {
    cv_converter* cc = cv_combine(cv_get_scale(3.0), cv_get_offset(5.0));  /* 3x+5 */
    CHECK(approx(cv_convert_double(cc, 0), 5) && approx(cv_convert_double(cc, 2), 11)
          && approx(cv_convert_double(cc, 10), 35), "scale then offset != 3x+5");
}

static void t_combine_offset_offset(void) {
    cv_converter* cc = cv_combine(cv_get_offset(2.0), cv_get_offset(3.0));  /* x+5 */
    CHECK(approx(cv_convert_double(cc, 0), 5) && approx(cv_convert_double(cc, 10), 15), "offset+offset != x+5");
}

static void t_combine_identity(void) {
    cv_converter* cc = cv_combine(cv_get_scale(2.0), cv_get_scale(0.5));  /* identity */
    CHECK(approx(cv_convert_double(cc, 3), 3) && approx(cv_convert_double(cc, 7), 7), "scale*inverse != identity");
}

static void t_galilean_behavior(void) {
    cv_converter* a = cv_get_galilean(1.0, 5.0);  /* x+5 */
    CHECK(approx(cv_convert_double(a, 0), 5) && approx(cv_convert_double(a, 2), 7), "galilean(1,5) != x+5");
    cv_converter* b = cv_get_galilean(3.0, 0.0);  /* 3x */
    CHECK(approx(cv_convert_double(b, 0), 0) && approx(cv_convert_double(b, 2), 6), "galilean(3,0) != 3x");
}

static void t_convertibility(void) {
    CHECK(ut_are_convertible(meter, km) == 1, "m not convertible to km");
    CHECK(ut_are_convertible(meter, kelvin) == 0, "m wrongly convertible to K");
    CHECK(ut_are_convertible(meter, radian) == 0, "m wrongly convertible to rad");
}

static void t_array_in_place(void) {
    cv_converter* cc = cv_get_scale(2.0);
    double a[3] = {1.0, 2.0, 3.0};
    cv_convert_doubles(cc, a, 3, a);
    CHECK(approx(a[0], 2) && approx(a[1], 4) && approx(a[2], 6), "in-place array convert wrong");
}

static void t_scale_bad_arg(void) {
    ut_unit* u = ut_scale(0.0, meter);
    CHECK(u == NULL && ut_get_status() == UT_BAD_ARG, "scale(0) not BAD_ARG");
}

static void t_log_to_absolute(void) {
    CHECK(approx(conv(bel, watt, 0), 0.001) && approx(conv(bel, watt, 3), 1), "bel->watt wrong");
    ut_unit* decibel = ut_scale(0.1, bel);
    CHECK(approx(conv(decibel, watt, 0), 0.001) && approx(conv(decibel, watt, 30), 1), "decibel->watt wrong");
}

static void t_affine_scale_compose(void) {
    ut_unit* u = ut_offset(ut_scale(2.0, kelvin), 5.0);
    CHECK(approx(conv(u, kelvin, 0), 10) && approx(conv(u, kelvin, 10), 30), "offset*scale compose wrong");
}

static void t_timestamp_origin_diff(void) {
    ut_unit* t1 = ut_offset_by_time(second, ut_encode_time(2001, 1, 1, 0, 0, 0));
    ut_unit* t2 = ut_offset_by_time(second, ut_encode_time(2001, 1, 2, 0, 0, 0));
    CHECK(approx(conv(t1, t2, 86400), 0) && approx(conv(t1, t2, 0), -86400), "timestamp origin diff wrong");
}

static void t_calendar_roundtrip(void) {
    int y, mo, d, h, mi; double s, res;
    ut_decode_time(ut_encode_time(2001, 3, 15, 12, 30, 0), &y, &mo, &d, &h, &mi, &s, &res);
    CHECK(y == 2001 && mo == 3 && d == 15 && h == 12 && mi == 30 && approx(s, 0), "calendar round-trip wrong");
}

static void t_log_across_references(void) {
    ut_unit* bel_W = ut_log(10.0, watt);
    CHECK(approx(conv(bel, bel_W, 0), -3) && approx(conv(bel, bel_W, 3), 0), "bel(1mW)->bel(1W) wrong");
}

static void t_timestamp_scale_compose(void) {
    ut_unit* t1 = ut_offset_by_time(second, ut_encode_time(2000, 1, 1, 0, 0, 0));
    ut_unit* hours = ut_scale(3600.0, second);
    ut_unit* t2 = ut_offset_by_time(hours, ut_encode_time(2001, 1, 1, 0, 0, 0));
    CHECK(approx(conv(t1, t2, 0), -8784) && approx(conv(t1, t2, 86400), -8760), "timestamp+scale compose wrong");
}

static void t_affine_product_chain(void) {
    ut_unit* u = ut_multiply(ut_raise(celsius, 2), ut_invert(kelvin));
    CHECK(approx(conv(u, kelvin, 0), 0) && approx(conv(u, kelvin, 5), 5), "degC^2*(1/K) != K");
}

static void t_deep_converter_chain(void) {
    cv_converter* cc = cv_combine(cv_combine(cv_combine(cv_get_scale(2.0), cv_get_offset(3.0)),
                                             cv_get_scale(4.0)), cv_get_offset(1.0));
    CHECK(approx(cv_convert_double(cc, 0), 13) && approx(cv_convert_double(cc, 1), 21)
          && approx(cv_convert_double(cc, 5), 53), "deep chain != 8x+13");
}

static struct { const char* name; void (*fn)(void); } TESTS[] = {
    {"test_offset_dropped_under_product_ops", t_offset_dropped},
    {"test_product_cancels_to_one", t_product_cancels},
    {"test_root_powers", t_root_powers},
    {"test_log_unit_legality", t_log_legality},
    {"test_kelvin_celsius_conversion", t_kelvin_celsius},
    {"test_combine_scale_then_offset", t_combine_scale_offset},
    {"test_combine_offset_offset", t_combine_offset_offset},
    {"test_combine_inverse_is_identity", t_combine_identity},
    {"test_galilean_converter_behavior", t_galilean_behavior},
    {"test_convertibility", t_convertibility},
    {"test_array_convert_in_place", t_array_in_place},
    {"test_scale_zero_factor_bad_arg", t_scale_bad_arg},
    {"test_log_to_absolute_conversion", t_log_to_absolute},
    {"test_affine_scale_compose", t_affine_scale_compose},
    {"test_timestamp_origin_diff", t_timestamp_origin_diff},
    {"test_calendar_roundtrip", t_calendar_roundtrip},
    {"test_log_across_references", t_log_across_references},
    {"test_timestamp_scale_compose", t_timestamp_scale_compose},
    {"test_affine_product_chain", t_affine_product_chain},
    {"test_deep_converter_chain", t_deep_converter_chain},
};

int main(void) {
    setup();
    int n = (int)(sizeof(TESTS) / sizeof(TESTS[0]));
    int passed = 0;
    for (int i = 0; i < n; i++) {
        cur = &R[NR++];
        cur->name = TESTS[i].name; cur->passed = 1; cur->msg[0] = '\0';
        TESTS[i].fn();
        if (cur->passed) passed++;
    }

    const char* path = getenv("CTRF_PATH");
    if (!path) path = "/logs/verifier/ctrf.json";
    FILE* fp = fopen(path, "w");
    if (fp) {
        fprintf(fp, "{\"results\":{\"tool\":{\"name\":\"udunits-ctest\",\"version\":\"1\"},");
        fprintf(fp, "\"summary\":{\"tests\":%d,\"passed\":%d,\"failed\":%d,\"skipped\":0,\"pending\":0,\"other\":0,\"start\":0,\"stop\":0},",
                n, passed, n - passed);
        fprintf(fp, "\"tests\":[");
        for (int i = 0; i < NR; i++) {
            fprintf(fp, "%s{\"name\":\"%s\",\"status\":\"%s\",\"duration\":0,\"message\":\"%s\"}",
                    i ? "," : "", R[i].name, R[i].passed ? "passed" : "failed", R[i].msg);
        }
        fprintf(fp, "]}}\n");
        fclose(fp);
    }

    for (int i = 0; i < NR; i++)
        if (!R[i].passed) printf("FAIL %s: %s\n", R[i].name, R[i].msg);
    printf("passed %d/%d\n", passed, n);
    return passed == n ? 0 : 1;
}
