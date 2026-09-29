import org.physkit.geometry.Vector2;
import org.physkit.geometry.hull.HullGenerator;
import org.physkit.geometry.hull.GiftWrap;
import org.physkit.geometry.hull.GrahamScan;
import org.physkit.geometry.hull.DivideAndConquer;
import org.physkit.geometry.hull.MonotoneChain;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness — the convex hull subsystem (org.physkit.geometry.hull): the {@link HullGenerator}
 * interface and its four implementations {@link GiftWrap}, {@link GrahamScan},
 * {@link DivideAndConquer} and {@link MonotoneChain}. Each named case produces a single string;
 * oracle values live in the committed /tests/expected.tsv fixture (captured from the reference).
 * Run with env CAPTURE=1 to print this part's `name<TAB>value` lines (to regenerate the fixture);
 * otherwise it grades its own cases against the fixture and emits one JSON line per case for the
 * CTRF bridge.
 *
 * All input point sets are HARDCODED (no RNG). Because a generator's returned winding / starting
 * vertex is an implementation detail, every hull is CANONICALIZED: the returned vertices are sorted
 * by (x,y) and formatted via v() so ordering differences never cause spurious mismatches. Numeric
 * output is rounded to 6 decimals via f()/v(). This file imports ONLY org.physkit.geometry.Vector2 and
 * org.physkit.geometry.hull.*, so it compiles for any submission that implements the hull package.
 *
 * Consolidated to avoid test fragmentation: instead of one case per (input, generator) pair, each
 * distinct input has a single "agree" case that (a) runs ALL FOUR generators, (b) asserts they
 * produce the identical canonical hull, and (c) pins the exact canonical vertex set. That one case
 * therefore exercises every generator AND fixes the answer, subsuming the old per-generator repeats.
 * Distinct hull BEHAVIORS (collinear-edge-point exclusion, interior-point exclusion, duplicate-point
 * handling) are each pinned exactly by a dedicated agree case on an input that isolates them.
 */
public class HullHarness {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }

    /** Round to 6 decimals, fixed locale, normalize -0.0 -> 0.0. */
    static String f(double v) {
        if (Double.isNaN(v)) return "NaN";
        if (Double.isInfinite(v)) return v > 0 ? "Inf" : "-Inf";
        double r = Math.round(v * 1e6) / 1e6;
        if (r == 0.0) r = 0.0;
        return String.format(Locale.ROOT, "%.6f", r);
    }
    static String v(Vector2 p) { return "(" + f(p.x) + "," + f(p.y) + ")"; }

    /** Fresh copy of the input points (generators may sort/mutate the array in place). */
    static Vector2[] copy(Vector2[] pts) {
        Vector2[] out = new Vector2[pts.length];
        for (int i = 0; i < pts.length; i++) out[i] = new Vector2(pts[i].x, pts[i].y);
        return out;
    }

    /** Run one generator on a fresh copy and return the hull, canonicalized: vertices sorted by (x,y). */
    static String hull(HullGenerator g, Vector2[] pts) {
        Vector2[] h = g.generate(copy(pts));
        List<Vector2> list = new ArrayList<>(Arrays.asList(h));
        list.sort(Comparator.<Vector2>comparingDouble(a -> a.x).thenComparingDouble(a -> a.y));
        StringBuilder sb = new StringBuilder("n=").append(list.size()).append(" [");
        for (int i = 0; i < list.size(); i++) {
            if (i > 0) sb.append(",");
            sb.append(v(list.get(i)));
        }
        return sb.append("]").toString();
    }

    /**
     * Run ALL FOUR generators (GiftWrap, GrahamScan, DivideAndConquer, MonotoneChain) on the input;
     * assert they produce the identical canonical hull and return that hull. On agreement the value
     * pins the exact canonical vertex set, so a single case both cross-checks the four generators and
     * fixes the expected answer. On any disagreement it returns a MISMATCH marker naming the culprits.
     */
    static String allAgree(Vector2[] pts) {
        String gw = hull(new GiftWrap(), pts);
        String gs = hull(new GrahamScan(), pts);
        String dc = hull(new DivideAndConquer(), pts);
        String mc = hull(new MonotoneChain(), pts);
        if (gw.equals(gs) && gs.equals(dc) && dc.equals(mc)) return gw;
        return "MISMATCH gw=" + gw + " gs=" + gs + " dc=" + dc + " mc=" + mc;
    }

    // ---- Hardcoded, deterministic point sets ----

    /** Square corners (0,0)(2,0)(2,2)(0,2) plus interior points -> hull is the 4 corners. */
    static final Vector2[] SQUARE_WITH_INTERIOR = {
        new Vector2(0, 0), new Vector2(2, 0), new Vector2(2, 2), new Vector2(0, 2),
        new Vector2(1, 1), new Vector2(0.5, 0.5), new Vector2(1.5, 1.2), new Vector2(1, 0.5)
    };

    /** Square corners with two extra COLLINEAR points on the bottom and right edges -> still 4 corners. */
    static final Vector2[] SQUARE_WITH_COLLINEAR = {
        new Vector2(0, 0), new Vector2(1, 0), new Vector2(2, 0),   // (1,0) is collinear on bottom edge
        new Vector2(2, 1), new Vector2(2, 2),                       // (2,1) is collinear on right edge
        new Vector2(0, 2)
    };

    /** Triangle with an interior point -> hull excludes the interior point (3 vertices). */
    static final Vector2[] TRIANGLE_WITH_INTERIOR = {
        new Vector2(0, 0), new Vector2(4, 0), new Vector2(2, 3), new Vector2(2, 1)
    };

    /** A convex regular-ish pentagon (all 5 points on the hull). */
    static final Vector2[] PENTAGON = {
        new Vector2(0, 0), new Vector2(2, 0), new Vector2(3, 2), new Vector2(1, 3), new Vector2(-1, 2)
    };

    /**
     * A larger fixed "random-looking" cloud of 10 points. Extremes:
     * left (-3,1), right (5,0), top (2,5), bottom (0,-2), plus (4,4) and (-2,3) on the hull;
     * the rest ((1,1),(2,2),(0,3),(3,1)) are interior. Hull = 6 vertices.
     */
    static final Vector2[] CLOUD10 = {
        new Vector2(-3, 1), new Vector2(5, 0), new Vector2(2, 5), new Vector2(0, -2),
        new Vector2(4, 4), new Vector2(-2, 3),
        new Vector2(1, 1), new Vector2(2, 2), new Vector2(0, 3), new Vector2(3, 1)
    };

    /**
     * A triangle whose vertices each appear twice (duplicate coordinates) -> the hull is still the
     * 3 distinct corners; exercises duplicate-point handling across all four generators.
     */
    static final Vector2[] DUPLICATES = {
        new Vector2(0, 0), new Vector2(0, 0),
        new Vector2(4, 0), new Vector2(4, 0),
        new Vector2(2, 3), new Vector2(2, 3)
    };

    static {
        // ---- Consolidated agree+exact cases: each runs ALL FOUR generators, asserts they agree,
        //      and pins the exact canonical hull. One case per distinct input replaces the old
        //      per-generator repeats. ----

        // square (4 corners + interior points) -> the 4 corners
        c("hull_square_agree",            () -> allAgree(SQUARE_WITH_INTERIOR));       // n=4, four generators agree
        // square with collinear edge points -> still exactly the 4 corners
        c("hull_collinear_agree",         () -> allAgree(SQUARE_WITH_COLLINEAR));      // n=4, four generators agree
        // triangle with an interior point -> the 3 corners
        c("hull_triangle_interior_agree", () -> allAgree(TRIANGLE_WITH_INTERIOR));     // n=3, four generators agree
        // larger fixed cloud of 10 points -> 6 hull vertices
        c("hull_cloud10_agree",           () -> allAgree(CLOUD10));                    // n=6, four generators agree
        // fully-convex pentagon -> all 5 points on the hull
        c("hull_pentagon_agree",          () -> allAgree(PENTAGON));                   // n=5, four generators agree
        // duplicate coordinates collapse -> the 3 distinct corners
        c("hull_duplicate_agree",         () -> allAgree(DUPLICATES));                 // n=3, four generators agree

        // NOTE: collinear-edge-point exclusion and interior-point exclusion are already pinned
        // exactly (full canonical vertex set, all four generators) by hull_collinear_agree and
        // hull_triangle_interior_agree on the identical inputs, so no separate count-only case is
        // needed — a bare-count case would be a strict weakening of those agree cases.
    }

    public static void main(String[] args) throws Exception {
        Runner.run(cases, args);
    }
}
