import org.physkit.geometry.Vector2;
import org.physkit.geometry.simplify.*;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness — the polygon simplification subsystem (org.physkit.geometry.simplify):
 * the {@link Simplifier} interface and its concrete implementations {@link VertexClusterReduction}
 * (merges adjacent vertices closer than a cluster tolerance), {@link DouglasPeucker} (removes points
 * within an epsilon distance of a guide segment), and {@link Visvalingam} (removes vertices whose
 * triangular area is below a minimum). Each named case produces a single string; oracle values live
 * in the committed /tests/expected.tsv fixture (captured from the reference). Run with env CAPTURE=1
 * to print this part's `name<TAB>value` lines (to regenerate the fixture); otherwise it grades its
 * own cases against the fixture and emits one JSON line per case for the CTRF bridge.
 *
 * Numeric outputs are ROUNDED to 6 decimals via f()/v() so tiny cross-JDK / cross-platform floating
 * point differences do not cause spurious mismatches. Result vertex SETS are canonicalized by sorting
 * their 6dp string form so the assertion does not depend on the algorithm's traversal order/rotation.
 * All inputs and tolerances are HARDCODED so every case is deterministic. Both simplify() overloads
 * (List and varargs) are exercised. This file imports ONLY org.physkit.geometry(.simplify), so it
 * compiles for any submission that implements the simplify package.
 */
public class SimplifyHarness {
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

    static List<Vector2> list(double... xy) {
        List<Vector2> l = new ArrayList<>();
        for (int i = 0; i < xy.length; i += 2) l.add(new Vector2(xy[i], xy[i + 1]));
        return l;
    }

    /** Order-independent canonical form: "n=<count>[v0 v1 ...]" with vertices sorted by 6dp string. */
    static String canon(List<Vector2> r) {
        List<String> parts = new ArrayList<>();
        for (Vector2 p : r) parts.add(v(p));
        Collections.sort(parts);
        StringBuilder sb = new StringBuilder("n=").append(r.size()).append("[");
        for (int i = 0; i < parts.size(); i++) {
            if (i > 0) sb.append(" ");
            sb.append(parts.get(i));
        }
        return sb.append("]").toString();
    }

    /** Just the resulting vertex count. */
    static String count(List<Vector2> r) { return "n=" + r.size(); }

    static {
        // A unit square with THREE extra exactly-collinear points inserted along the bottom edge
        // (y=0): (0.25,0),(0.5,0),(0.75,0). The 4 true corners are (0,0),(1,0),(1,1),(0,1).
        // These interior points lie exactly on the bottom edge, so any epsilon>0 (or cluster of the
        // right size) can drop them, leaving the 4 corners.
        // ---- VertexClusterReduction: distance-based merge ----

        // clusterTolerance 0 => nothing merges (no two adjacent vertices are coincident): identity.
        c("simp_vcr_zero_identity", () -> {
            List<Vector2> in = list(0,0, 0.25,0, 0.5,0, 0.75,0, 1,0, 1,1, 0,1);
            return canon(new VertexClusterReduction(0.0).simplify(in));
        });

        // Two nearly-coincident vertices (distance 0.05) with tolerance 0.1 => the pair merges to one
        // (5 -> 4). Which representative survives a merged cluster (the first vertex vs the centroid)
        // is a cluster-representative rule the spec does not define, so only the merged vertex is left
        // unpinned: the other three corners are >= 0.95 from every other vertex, hence outside every
        // cluster, so they must survive UNCHANGED under any representative rule -- assert that exact
        // set, plus that exactly one survivor lies inside the merged cluster.
        // Also checks the varargs overload agrees with the List overload (same result) in one case.
        c("simp_vcr_merge_close_pair", () -> {
            List<Vector2> in = list(0,0, 1,0, 1.0,0.05, 1,1, 0,1);
            Vector2[] arr = { new Vector2(0,0), new Vector2(1,0), new Vector2(1.0,0.05),
                              new Vector2(1,1), new Vector2(0,1) };
            List<Vector2> res = new VertexClusterReduction(0.1).simplify(in);
            List<Vector2> outside = new ArrayList<>();
            int inCluster = 0;
            for (Vector2 p : res) {
                if (p.distance(new Vector2(1, 0)) <= 0.1) inCluster++; else outside.add(p);
            }
            String viaList = count(res);
            String viaArr = count(Arrays.asList(new VertexClusterReduction(0.1).simplify(arr)));
            return viaList + " outside_cluster=" + canon(outside) + " in_cluster=" + inCluster
                    + " varargs_matches=" + viaList.equals(viaArr);
        });

        // tolerance smaller than the gap => no merge (0.05 gap, tolerance 0.01): identity count.
        c("simp_vcr_below_tolerance_identity", () -> {
            List<Vector2> in = list(0,0, 1,0, 1.0,0.05, 1,1, 0,1);
            return count(new VertexClusterReduction(0.01).simplify(in));
        });

        // A dense run of 3 points within a tiny cluster near the origin collapses to a corner.
        // Points (0,0),(0.02,0),(0.04,0) each within 0.03 of the previous, tolerance 0.05.
        c("simp_vcr_collapse_run", () -> {
            List<Vector2> in = list(0,0, 0.02,0, 0.04,0, 1,0, 1,1, 0,1);
            return count(new VertexClusterReduction(0.05).simplify(in));
        });

        // ---- DouglasPeucker: perpendicular-distance-to-guide-segment removal ----
        // Use clusterTolerance 0 so the DP epsilon is the only thing acting.

        // Square with 3 collinear interior points on the bottom edge (perp distance 0) => corners kept.
        // Also checks the varargs overload agrees with the List overload (same result) in one case.
        c("simp_dp_drop_collinear", () -> {
            List<Vector2> in = list(0,0, 0.25,0, 0.5,0, 0.75,0, 1,0, 1,1, 0,1);
            Vector2[] arr = { new Vector2(0,0), new Vector2(0.25,0), new Vector2(0.5,0),
                              new Vector2(0.75,0), new Vector2(1,0), new Vector2(1,1), new Vector2(0,1) };
            String viaList = canon(new DouglasPeucker(0.0, 0.01).simplify(in));
            String viaArr = canon(Arrays.asList(new DouglasPeucker(0.0, 0.01).simplify(arr)));
            return viaList + " varargs_matches=" + viaList.equals(viaArr);
        });

        // Same square but the middle bottom point bulges up by 0.05. With epsilon 0.1 (> 0.05) the
        // bulge is within tolerance of the guide and is removed => exactly the 4 corners. DouglasPeucker
        // only REMOVES points, so the surviving SET is well-defined; assert it (not just the count).
        c("simp_dp_drop_small_bulge", () -> {
            List<Vector2> in = list(0,0, 0.25,0, 0.5,0.05, 0.75,0, 1,0, 1,1, 0,1);
            return canon(new DouglasPeucker(0.0, 0.1).simplify(in));
        });

        // Same bulge but epsilon 0.01 (< 0.05) => the bulge is a significant feature and is retained.
        c("simp_dp_keep_significant_bulge", () -> {
            List<Vector2> in = list(0,0, 0.25,0, 0.5,0.05, 0.75,0, 1,0, 1,1, 0,1);
            return count(new DouglasPeucker(0.0, 0.01).simplify(in));
        });

        // A polygon with genuine corners only (a plain square) is unchanged by DP.
        c("simp_dp_square_identity", () -> {
            List<Vector2> in = list(0,0, 1,0, 1,1, 0,1);
            return canon(new DouglasPeucker(0.0, 0.5).simplify(in));
        });

        // ---- Visvalingam: triangular-area-based removal ----
        // clusterTolerance 0 so only the area threshold acts.

        // Collinear interior points form zero-area triangles => removed by any positive threshold.
        c("simp_vis_drop_collinear", () -> {
            List<Vector2> in = list(0,0, 0.25,0, 0.5,0, 0.75,0, 1,0, 1,1, 0,1);
            return canon(new Visvalingam(0.0, 0.001).simplify(in));
        });

        // Square with one bumped point (0.5,0.05): triangle area at that vertex = 0.5*base*height
        // = 0.5*1.0*0.05 = 0.025. Threshold 0.1 (> 0.025) removes it => exactly the 4 corners.
        // Visvalingam only REMOVES points, so the surviving SET is well-defined; assert it exactly.
        c("simp_vis_drop_small_area", () -> {
            List<Vector2> in = list(0,0, 0.5,0.05, 1,0, 1,1, 0,1);
            return canon(new Visvalingam(0.0, 0.1).simplify(in));
        });

        // Same bumped point but threshold 0.001 (< 0.025) keeps it => retained.
        c("simp_vis_keep_larger_area", () -> {
            List<Vector2> in = list(0,0, 0.5,0.05, 1,0, 1,1, 0,1);
            return count(new Visvalingam(0.0, 0.001).simplify(in));
        });

        // A plain square: every vertex's triangle area is 0.5 (>= threshold 0.1) => identity.
        c("simp_vis_square_identity", () -> {
            List<Vector2> in = list(0,0, 1,0, 1,1, 0,1);
            return canon(new Visvalingam(0.0, 0.1).simplify(in));
        });

        // ---- Cross-cutting: no-redundancy polygon is invariant across all three simplifiers ----
        // A regular hexagon (6 genuine corners) simplifies to itself under a small tolerance.
        c("simp_hexagon_all_identity", () -> {
            // regular hexagon, radius 1, centered at origin
            List<Vector2> in = new ArrayList<>();
            for (int i = 0; i < 6; i++) {
                double a = Math.PI / 3.0 * i;
                in.add(new Vector2(Math.cos(a), Math.sin(a)));
            }
            int a = new VertexClusterReduction(0.001).simplify(in).size();
            int b = new DouglasPeucker(0.0, 0.001).simplify(in).size();
            int d = new Visvalingam(0.0, 0.001).simplify(in).size();
            return "vcr=" + a + " dp=" + b + " vis=" + d;
        });
    }

    public static void main(String[] args) throws Exception {
        Runner.run(cases, args);
    }
}
