import io.evolab.stat.*;
import io.evolab.util.*;

import java.util.*;
import java.util.function.Supplier;
import java.util.stream.*;

/**
 * WRG test harness — jenetics MOMENT STATISTICS + ranges (io.evolab.stat + io.evolab.util ranges).
 * Covers DoubleMomentStatistics / IntMomentStatistics / LongMomentStatistics / MinMax / Quantile /
 * Summary / DoubleRange / IntRange / LongRange.
 *
 * Split out of the former monolithic StatHarness so the fragile Seq/util idioms
 * (Seq.toString(String) / static ISeq.toISeq()) — now in SeqHarness — cannot compile-wipe these
 * deterministic moment-statistics cases. Self-contained: its own imports + only the helpers these
 * cases reference. Case bodies are verbatim. Runner is shared.
 */
public class MomentStatHarness {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }

    static String f(double v) {
        if (Double.isNaN(v)) return "NaN";
        if (Double.isInfinite(v)) return v > 0 ? "Inf" : "-Inf";
        double r = Math.round(v * 1e6) / 1e6;
        if (r == 0.0) r = 0.0;
        return String.format(Locale.ROOT, "%.6f", r);
    }

    // Fixed classic dataset: n=8, sum=40, mean=5, sample variance=32/7 (=4.571429).
    static final double[] D8 = {2, 4, 4, 4, 5, 5, 7, 9};

    /** P^2 estimate of each p over the deterministic ramp 1..n, joined with '|'. */
    static String quantiles(int n, double... ps) {
        StringBuilder sb = new StringBuilder();
        for (double p : ps) {
            Quantile q = new Quantile(p);
            for (int i = 1; i <= n; i++) q.accept(i);
            if (sb.length() > 0) sb.append("|");
            sb.append(f(q.value()));
        }
        return sb.toString();
    }

    static {
        // ---- DoubleMomentStatistics: base moments over {2,4,4,4,5,5,7,9} ----
        // count=8, min=2, max=9, sum=40, mean=5, sample variance=32/7 (all in one node).
        c("stat_dms_base", () -> {
            DoubleMomentStatistics s = new DoubleMomentStatistics();
            for (double x : D8) s.accept(x);
            return s.count() + "|" + f(s.min()) + "|" + f(s.max()) + "|" +
                   f(s.sum()) + "|" + f(s.mean()) + "|" + f(s.variance());
            // 8|2.000000|9.000000|40.000000|5.000000|4.571429
        });
        // (Double skewness+kurtosis are covered live-equivalent by stat_dms_record's full 8-field
        //  toDoubleMoments() round-trip, matching the Int/Long base+record structure.)

        // ---- IntMomentStatistics over 1..10 ----
        // count=10, min=1, max=10, sum=55, mean=5.5, sample variance=110/12=9.166667.
        c("stat_ims_base", () -> {
            IntMomentStatistics s = new IntMomentStatistics();
            for (int i = 1; i <= 10; i++) s.accept(i);
            return s.count() + "|" + s.min() + "|" + s.max() + "|" +
                   s.sum() + "|" + f(s.mean()) + "|" + f(s.variance());
            // 10|1|10|55|5.500000|9.166667
        });

        // ---- LongMomentStatistics over {10,20,30,40,50} ----
        // count=5, min=10, max=50, sum=150, mean=30, sample variance=250.
        c("stat_lms_base", () -> {
            LongMomentStatistics s = new LongMomentStatistics();
            for (long v : new long[]{10, 20, 30, 40, 50}) s.accept(v);
            return s.count() + "|" + s.min() + "|" + s.max() + "|" +
                   s.sum() + "|" + f(s.mean()) + "|" + f(s.variance());
            // 5|10|50|150|30.000000|250.000000
        });

        // ---- MinMax accumulator (canonical: MinMax.of() + accept + min()/max()) ----
        // Feed {7,2,5,3,9,1} -> min=1, max=9, count=6.
        c("stat_minmax", () -> {
            MinMax<Integer> mm = MinMax.of();
            for (int v : new int[]{7, 2, 5, 3, 9, 1}) mm.accept(v);
            return mm.min() + "|" + mm.max() + "|" + mm.count();   // 1|9|6
        });

        // ---- Quantile (P^2 online estimator): new Quantile(p) + accept + value()/quantile()/count() ----
        // value() is the estimate of the p-quantile. At p=1.0 that is the running MAXIMUM of the accepted
        // values (9.0 over {5,1,9,3,7}), so asserting it exercises the real estimator state -- a stub that
        // only stores p and counts (value() left at its init) FAILS. quantile() echoes p; count() the number
        // accepted. The p=0.0 value() is NOT asserted: jenetics returns the 0.0 init marker there, not the
        // true minimum. stat_quantile_multi_p asserts the exact estimate at non-degenerate p.
        c("stat_quantile_bounds", () -> {
            Quantile lo = new Quantile(0.0);
            Quantile hi = new Quantile(1.0);
            for (double v : new double[]{5, 1, 9, 3, 7}) { lo.accept(v); hi.accept(v); }
            return f(hi.value()) + "|" + f(hi.quantile()) + "|" + f(lo.quantile()) + "|" + hi.count();
            // 9.000000|1.000000|0.000000|5
        });

        // ---- Summary statics (bundled): DoubleSummary over D8 + IntSummary over {3,1,4,1,5,9,2,6} ----
        // Two trivial same-node array-reduction clusters merged into one multi-assertion case (all eight
        // sub-values preserved: double min/max/sum/mean then int min/max/sum/mean).
        c("stat_summary", () -> {
            int[] xs = {3, 1, 4, 1, 5, 9, 2, 6};
            return f(DoubleSummary.min(D8)) + "|" + f(DoubleSummary.max(D8)) + "|" +
                   f(DoubleSummary.sum(D8)) + "|" + f(DoubleSummary.mean(D8)) + "||" +
                   IntSummary.min(xs) + "|" + IntSummary.max(xs) + "|" +
                   IntSummary.sum(xs) + "|" + f(IntSummary.mean(xs));
            // 2.000000|9.000000|40.000000|5.000000||1|9|31|3.875000
        });

        // ---- IntRange: bounds + size() (half-open size = max-min) ----
        c("stat_irange", () -> {
            IntRange r = IntRange.of(3, 10);
            return r.min() + "|" + r.max() + "|" + r.size();   // 3|10|7
        });

        // ---- DoubleMoments record: full accumulator -> record round-trip, EVERY accessor exact ----
        // Reads all eight fields (count/min/max/sum/mean/variance/skewness/kurtosis) back from the
        // immutable record, so a wrong higher-moment recurrence OR a mis-ordered record field is caught.
        c("stat_dms_record", () -> {
            double[] xs = {2, 3, 5, 7, 11, 13, 17, 19};
            DoubleMomentStatistics s = new DoubleMomentStatistics();
            for (double x : xs) s.accept(x);
            DoubleMoments m = s.toDoubleMoments();
            return m.count() + "|" + f(m.min()) + "|" + f(m.max()) + "|" + f(m.sum()) + "|" +
                   f(m.mean()) + "|" + f(m.variance()) + "|" + f(m.skewness()) + "|" + f(m.kurtosis());
            // oracle-captured
        });

        // ---- IntMoments record: full accumulator -> record round-trip over a skewed int stream ----
        // count(long)/min(int)/max(int)/sum(long)/mean/variance/skewness/kurtosis — verifies the int
        // record's mixed-type field layout AND the higher-moment values simultaneously.
        c("stat_ims_record", () -> {
            int[] xs = {4, 4, 5, 5, 6, 6, 7, 30};
            IntMomentStatistics s = new IntMomentStatistics();
            for (int x : xs) s.accept(x);
            IntMoments m = s.toIntMoments();
            return m.count() + "|" + m.min() + "|" + m.max() + "|" + m.sum() + "|" +
                   f(m.mean()) + "|" + f(m.variance()) + "|" + f(m.skewness()) + "|" + f(m.kurtosis());
            // oracle-captured
        });

        // ---- LongMomentStatistics record round-trip: full 8-field toLongMoments() ----
        // Mirrors the Double/Int record cases for the LONG path: count(long)/min(long)/max(long)/
        // sum(long)/mean/variance/skewness/kurtosis — catches a wrong long recurrence OR record layout.
        c("stat_lms_record", () -> {
            long[] xs = {5, 7, 7, 8, 10, 12, 15, 22};
            LongMomentStatistics s = new LongMomentStatistics();
            for (long x : xs) s.accept(x);
            LongMoments m = s.toLongMoments();
            return m.count() + "|" + m.min() + "|" + m.max() + "|" + m.sum() + "|" +
                   f(m.mean()) + "|" + f(m.variance()) + "|" + f(m.skewness()) + "|" + f(m.kurtosis());
            // oracle-captured
        });

        // ---- Quantile P^2 estimator at EIGHT non-degenerate p over two known streams ----
        // The exact 6-dp value() of the P^2 marker recurrence, at p=0.25/0.5/0.75/0.9 over 1..1000 and
        // p=0.1/0.4/0.6/0.95 over 1..500. Both streams are tie-free uniform ramps, so the published
        // algorithm's output is fully determined: the middle marker chases its desired position
        // 1+p*(n-1) but only ever steps by whole positions, so it settles ONE marker below the true
        // quantile (250 vs 250.75, 50 vs 50.9, ...). Verified identical across faithful formulation
        // variants (incremental vs recomputed desired positions, 0- vs 1-based marker positions,
        // sequential vs snapshot marker update, either cell-boundary comparison). An impl that returns
        // the interpolated quantile (250.750000) or any crude running estimate MISSES these values.
        // The degenerate p (0.0 / 1.0) are excluded here -- stat_quantile_bounds covers p=1.0.
        c("stat_quantile_multi_p", () ->
            quantiles(1000, 0.25, 0.5, 0.75, 0.9) + "||" + quantiles(500, 0.1, 0.4, 0.6, 0.95)
            // 250.000000|500.000000|750.000000|900.000000||50.000000|200.000000|300.000000|475.000000
        );
    }

    public static void main(String[] args) throws Exception { Runner.run(cases, args); }
}
