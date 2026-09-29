import org.physkit.geometry.*;
import org.physkit.geometry.decompose.*;
// Single-type import so the simple name `Triangle` always resolves to the geometry type the spec
// names, even if a submission also declares a helper class called Triangle in the decompose package
// (permitted: "you may organize internal/helper classes freely"). Without it the two on-demand
// imports above make `Triangle` ambiguous and the whole driver fails to compile.
import org.physkit.geometry.Triangle;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness — the polygon decomposition / triangulation subsystem
 * (org.physkit.geometry.decompose): the {@link Decomposer} implementations
 * (Bayazit, EarClipping, SweepLine) that split a simple polygon into a list of
 * {@link Convex} pieces, and the {@link Triangulator} implementations
 * (EarClipping, SweepLine) that split a simple polygon into {@link Triangle}s.
 *
 * Each named case produces a single string; oracle values live in the committed
 * /tests/expected.tsv fixture (captured from the reference). Run with env
 * CAPTURE=1 to print this part's `name<TAB>value` lines (to regenerate the
 * fixture); otherwise it grades its own cases against the fixture and emits one
 * JSON line per case for the CTRF bridge.
 *
 * The assertions are deterministic, algorithm-independent INVARIANTS so the
 * cases are fair across any correct decompose implementation:
 *   - decompose returns a non-empty list of convex pieces (the exact piece count is
 *     algorithm-specific — it depends on the decomposer's merge strategy — so it is NOT pinned),
 *   - area conservation (sum of piece areas == original polygon area),
 *   - every piece is Convex (verified via cross-product sign consistency),
 *   - triangulate produces exactly n-2 triangles for an n-vertex simple polygon
 *     (a count the spec DOES fix), and the triangle areas sum to the polygon area,
 *   - a convex polygon decomposes into a single piece.
 *
 * Numeric outputs are ROUNDED to 6 decimals via f() so tiny cross-JDK /
 * cross-platform floating point differences do not cause spurious mismatches.
 * This file imports ONLY org.physkit.geometry.* and org.physkit.geometry.decompose.*,
 * so it compiles for any submission that implements those packages.
 */
public class DecomposeHarness {
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

    // ---- Hardcoded simple polygons (CCW winding; decomposers auto-reverse CW). ----

    /** L-shape (6 vertices, one reflex vertex), CCW, area = 3. */
    static Vector2[] lShape() {
        return new Vector2[] {
            new Vector2(0, 0), new Vector2(2, 0), new Vector2(2, 1),
            new Vector2(1, 1), new Vector2(1, 2), new Vector2(0, 2),
        };
    }

    /** Plus / cross shape (12 vertices, 4 reflex vertices), CCW, area = 5. */
    static Vector2[] plusShape() {
        return new Vector2[] {
            new Vector2(1, 0), new Vector2(2, 0), new Vector2(2, 1),
            new Vector2(3, 1), new Vector2(3, 2), new Vector2(2, 2),
            new Vector2(2, 3), new Vector2(1, 3), new Vector2(1, 2),
            new Vector2(0, 2), new Vector2(0, 1), new Vector2(1, 1),
        };
    }

    /** Arrow / chevron (5 vertices, 1 reflex vertex), CCW. */
    static Vector2[] arrowShape() {
        return new Vector2[] {
            new Vector2(0, 0), new Vector2(4, 2), new Vector2(0, 4),
            new Vector2(1, 2),
        };
    }

    /** Convex quadrilateral (a unit square), CCW, area = 1. */
    static Vector2[] square() {
        return new Vector2[] {
            new Vector2(0, 0), new Vector2(1, 0),
            new Vector2(1, 1), new Vector2(0, 1),
        };
    }

    /** Convex pentagon, CCW. */
    static Vector2[] pentagon() {
        return new Vector2[] {
            new Vector2(0, 0), new Vector2(2, 0), new Vector2(3, 2),
            new Vector2(1, 3), new Vector2(-1, 2),
        };
    }

    /** U / cup shape (8 vertices, 2 reflex vertices), CCW — a rectangle with a top-middle notch. */
    static Vector2[] uShape() {
        return new Vector2[] {
            new Vector2(0, 0), new Vector2(3, 0), new Vector2(3, 3), new Vector2(2, 3),
            new Vector2(2, 1), new Vector2(1, 1), new Vector2(1, 3), new Vector2(0, 3),
        };
    }

    /** T shape (8 vertices, 2 reflex vertices), CCW — a stem with a top bar. */
    static Vector2[] tShape() {
        return new Vector2[] {
            new Vector2(1, 0), new Vector2(2, 0), new Vector2(2, 2), new Vector2(3, 2),
            new Vector2(3, 3), new Vector2(0, 3), new Vector2(0, 2), new Vector2(1, 2),
        };
    }

    /** Comb / crenellated shape (12 vertices, 4 reflex vertices), CCW — a 5x3 bar with two
     *  rectangular notches cut from the top between three prongs. area = 15 - 2*2 = 11. */
    static Vector2[] combShape() {
        return new Vector2[] {
            new Vector2(0, 0), new Vector2(5, 0), new Vector2(5, 3), new Vector2(4, 3),
            new Vector2(4, 1), new Vector2(3, 1), new Vector2(3, 3), new Vector2(2, 3),
            new Vector2(2, 1), new Vector2(1, 1), new Vector2(1, 3), new Vector2(0, 3),
        };
    }

    /** Deep-copy a polygon so each decompose call gets its own array
     *  (decompose() mutates the input via reverseWinding). */
    static Vector2[] copy(Vector2[] p) {
        Vector2[] q = new Vector2[p.length];
        for (int i = 0; i < p.length; i++) q[i] = p[i].copy();
        return q;
    }

    /** True if every piece returned is Convex, verified via cross-product sign
     *  consistency over the piece's vertices (all turns same sign). */
    static boolean allConvex(List<Convex> pieces) {
        for (Convex piece : pieces) {
            if (!(piece instanceof Wound)) continue; // area/count invariants still hold
            Vector2[] vs = ((Wound) piece).getVertices();
            int n = vs.length;
            if (n < 3) return false;
            int sign = 0;
            for (int i = 0; i < n; i++) {
                Vector2 a = vs[i], b = vs[(i + 1) % n], cc = vs[(i + 2) % n];
                double cross = (b.x - a.x) * (cc.y - b.y) - (b.y - a.y) * (cc.x - b.x);
                int s = cross > 1e-9 ? 1 : (cross < -1e-9 ? -1 : 0);
                if (s == 0) continue;
                if (sign == 0) sign = s;
                else if (s != sign) return false;
            }
        }
        return true;
    }

    /** Sum of piece areas (Shape.getArea() is always >= 0). */
    static double totalArea(List<Convex> pieces) {
        double a = 0.0;
        for (Convex piece : pieces) a += piece.getArea();
        return a;
    }

    static double triTotalArea(List<Triangle> tris) {
        double a = 0.0;
        for (Triangle t : tris) a += t.getArea();
        return a;
    }

    /** decompose invariant string: "n=<count> convex=<bool> area=<total>". */
    static String decInv(Decomposer d, Vector2[] poly) {
        List<Convex> pieces = d.decompose(copy(poly));
        return "n=" + pieces.size()
             + " convex=" + allConvex(pieces)
             + " area=" + f(totalArea(pieces));
    }

    /** decompose invariant WITHOUT the piece count: "nonempty=<bool> convex=<bool> area=<total>".
     *  For a concave polygon the number of convex pieces is algorithm-specific (it depends on the
     *  decomposer's diagonal/merge strategy, which the spec does not fix), so only non-emptiness,
     *  convexity of every piece, and total-area conservation are pinned. */
    static String decInvNoCount(Decomposer d, Vector2[] poly) {
        List<Convex> pieces = d.decompose(copy(poly));
        return "nonempty=" + (pieces.size() > 0)
             + " convex=" + allConvex(pieces)
             + " area=" + f(totalArea(pieces));
    }

    /** triangulate invariant string: "n=<count> area=<total>". */
    static String triInv(Triangulator t, Vector2[] poly) {
        List<Triangle> tris = t.triangulate(copy(poly));
        return "n=" + tris.size() + " area=" + f(triTotalArea(tris));
    }

    static {
        // ---- Bayazit decomposition: convexity + area conservation (piece count not pinned). ----
        c("dec_bayazit_lshape", () -> decInvNoCount(new Bayazit(), lShape()));
        c("dec_bayazit_plus",   () -> decInvNoCount(new Bayazit(), plusShape()));
        c("dec_bayazit_arrow",  () -> decInvNoCount(new Bayazit(), arrowShape()));

        // ---- EarClipping decomposition. ----
        c("dec_earclip_lshape", () -> decInvNoCount(new EarClipping(), lShape()));
        c("dec_earclip_plus",   () -> decInvNoCount(new EarClipping(), plusShape()));
        c("dec_earclip_arrow",  () -> decInvNoCount(new EarClipping(), arrowShape()));

        // ---- SweepLine decomposition. ----
        c("dec_sweepline_lshape", () -> decInvNoCount(new SweepLine(), lShape()));
        c("dec_sweepline_plus",   () -> decInvNoCount(new SweepLine(), plusShape()));
        c("dec_sweepline_arrow",  () -> decInvNoCount(new SweepLine(), arrowShape()));

        // ---- Additional concave polygons in the EarClipping / SweepLine decompose vein. ----
        // U/cup and T shapes (2 reflex vertices each): convex-piece area conservation + convexity.
        c("dec_earclip_ushape",   () -> decInvNoCount(new EarClipping(), uShape()));
        c("dec_sweepline_ushape", () -> decInvNoCount(new SweepLine(), uShape()));
        c("dec_earclip_tshape",   () -> decInvNoCount(new EarClipping(), tShape()));
        c("dec_sweepline_tshape", () -> decInvNoCount(new SweepLine(), tShape()));

        // ---- Reflex-heavy comb polygon (4 reflex vertices): convexity + area (count not pinned). ----
        c("dec_earclip_comb",   () -> decInvNoCount(new EarClipping(), combShape()));
        c("dec_sweepline_comb", () -> decInvNoCount(new SweepLine(), combShape()));

        // ---- Convex polygon decomposes into a single piece (itself). ----
        c("dec_bayazit_square_convex",   () -> decInv(new Bayazit(), square()));
        c("dec_earclip_pentagon_convex", () -> decInv(new EarClipping(), pentagon()));
        c("dec_sweepline_pentagon_convex", () -> decInv(new SweepLine(), pentagon()));

        // ---- Triangulation: exactly n-2 triangles, area conserved. ----
        // L-shape: 6 vertices -> 4 triangles; plus: 12 -> 10; pentagon: 5 -> 3.
        c("dec_tri_earclip_lshape",   () -> triInv(new EarClipping(), lShape()));
        c("dec_tri_earclip_plus",     () -> triInv(new EarClipping(), plusShape()));
        c("dec_tri_earclip_pentagon", () -> triInv(new EarClipping(), pentagon()));
        c("dec_tri_sweepline_lshape", () -> triInv(new SweepLine(), lShape()));
        c("dec_tri_sweepline_plus",   () -> triInv(new SweepLine(), plusShape()));
    }

    public static void main(String[] args) throws Exception {
        Runner.run(cases, args);
    }
}
