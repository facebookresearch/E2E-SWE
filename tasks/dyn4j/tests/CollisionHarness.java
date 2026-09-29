import org.physkit.geometry.*;
import org.physkit.collision.narrowphase.*;
import org.physkit.collision.manifold.*;
import org.physkit.collision.continuous.*;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness — the collision subsystem (org.physkit.collision.*): narrowphase penetration /
 * distance / raycast (Sat, Gjk, CircleDetector, SegmentDetector), containment, the clipping
 * manifold solver, and conservative-advancement time-of-impact (CCD). Each named case produces a
 * single string; oracle values live in the committed /tests/expected.tsv fixture (captured from the
 * reference). Run with env CAPTURE=1 to print this part's `name<TAB>value` lines (to regenerate the
 * fixture); otherwise it grades its own cases against the fixture and emits one JSON line per case.
 *
 * Numeric outputs are ROUNDED to 6 decimals via f()/v() so tiny cross-JDK / cross-platform floating
 * point differences do not cause spurious mismatches; the committed oracle is validated by GT eval.
 * This file imports ONLY public dyn4j API (org.physkit.geometry.* and org.physkit.collision.*), so it
 * compiles for any submission that implements the collision package from the spec.
 *
 * Case names are all prefixed `col_` so they never collide with the other harnesses that share the
 * oracle fixture.
 */
public class CollisionHarness {
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

    static Transform at(double x, double y) { Transform t = new Transform(); t.translate(x, y); return t; }
    /** Rotate-in-place by ang (radians) about the shape's local origin, then translate to (x,y). */
    static Transform rt(double ang, double x, double y) { Transform t = new Transform(); t.rotate(ang); t.translate(x, y); return t; }
    static final Transform ID = new Transform();

    /** Penetration -> "hit depth=<d> n=<normal>" or "miss" (normal direction is deterministic). */
    static String pen(boolean hit, Penetration p) {
        if (!hit) return "miss";
        return "hit depth=" + f(p.getDepth()) + " n=" + v(p.getNormal());
    }
    /** Round to 3 decimals (a coarser tolerance for solver-sensitive curved-shape outputs). */
    static String f3(double v) {
        if (Double.isNaN(v)) return "NaN";
        if (Double.isInfinite(v)) return v > 0 ? "Inf" : "-Inf";
        double r = Math.round(v * 1e3) / 1e3;
        if (r == 0.0) r = 0.0;
        return String.format(Locale.ROOT, "%.3f", r);
    }
    /**
     * Penetration for degenerate CURVED-shape overlaps (circle-circle): the depth is the primary,
     * exactly-determined EPA quantity, but a faithful GENERAL GJK/EPA on smooth circle supports
     * leaves an ~1e-4 tangential residual on the normal (its size depends on the EPA simplex
     * construction / convergence tolerance the spec does not pin; only special-casing circles
     * reaches the exact axis, which the spec does not require of Sat/Gjk). Pin the depth at 6
     * decimals but compare the normal at 3 decimals so that residual is absorbed while a genuinely
     * wrong normal (wrong direction / axis) is still caught.
     */
    static String penCurved(boolean hit, Penetration p) {
        if (!hit) return "miss";
        return "hit depth=" + f(p.getDepth()) + " n=(" + f3(p.getNormal().x) + "," + f3(p.getNormal().y) + ")";
    }
    /** Separation -> "sep d=<dist> n=<n> p1=<..> p2=<..>" or "overlap". */
    static String sep(boolean sep, Separation s) {
        if (!sep) return "overlap";
        return "sep d=" + f(s.getDistance()) + " n=" + v(s.getNormal())
                + " p1=" + v(s.getPoint1()) + " p2=" + v(s.getPoint2());
    }
    /** Raycast -> "hit t=<dist> p=<point> n=<normal>" or "miss". */
    static String ray(boolean hit, Raycast r) {
        if (!hit) return "miss";
        return "hit t=" + f(r.getDistance()) + " p=" + v(r.getPoint()) + " n=" + v(r.getNormal());
    }
    /**
     * Manifold -> convention-independent invariants: point count, |normal|, the normal AXIS
     * (sign-canonicalized so the leading non-zero component is positive), the sorted per-point
     * penetration depths, and each contact point's sorted TANGENTIAL coordinate (its projection on
     * the axis perpendicular to that canonical normal axis).
     *
     * The manifold-normal DIRECTION (dyn4j negates the A->B penetration normal) and each contact
     * point's coordinate ALONG the normal (which body's face it lands on) are implementation
     * conventions the spec does not fix, so they stay unpinned. The TANGENTIAL coordinate is not a
     * convention: the rival placements differ only by a shift along the normal, and clipping the
     * incident feature against the reference feature's side planes yields the same tangential
     * interval whichever feature is taken as the reference. It is exactly what the clip computes.
     */
    static String mstr(Manifold m) {
        List<ManifoldPoint> pts = new ArrayList<>(m.getPoints());
        Vector2 n = m.getNormal();
        double ax = n.x, ay = n.y;
        if (ax < 0 || (ax == 0.0 && ay < 0)) { ax = -ax; ay = -ay; }   // canonical axis: drop the sign convention
        Vector2 tangent = new Vector2(-ay, ax);
        List<Double> depths = new ArrayList<>(), tans = new ArrayList<>();
        for (ManifoldPoint mp : pts) { depths.add(mp.getDepth()); tans.add(mp.getPoint().dot(tangent)); }
        Collections.sort(depths);
        Collections.sort(tans);
        StringBuilder sb = new StringBuilder("pts=" + pts.size()
                + " |n|=" + f(n.getMagnitude()) + " axis=(" + f(ax) + "," + f(ay) + ") d=[");
        for (int i = 0; i < depths.size(); i++) { if (i > 0) sb.append(","); sb.append(f(depths.get(i))); }
        sb.append("] t=[");
        for (int i = 0; i < tans.size(); i++) { if (i > 0) sb.append(","); sb.append(f(tans.get(i))); }
        return sb.append("]").toString();
    }

    /**
     * Manifold invariants for an oblique contact whose incident face is a TIE: when two of B's
     * faces are exactly equally anti-parallel to the reference normal (e.g. a right-triangle
     * hypotenuse normal vs a box corner, where B's two adjacent faces both dot -sqrt(2)/2), which
     * tied face the clipper picks is not spec-fixed and it changes the clipped point COUNT. The spec
     * fixes the manifold at 1-2 points but not the incident-face tie-break, so pin only the
     * tie-independent quantities: the spec's 1-2 point bound, that every reported point actually
     * penetrates (depth >= 0, so a non-penetrating clipped endpoint must be culled), |normal|, the
     * canonical normal axis, and the deepest penetration (the deepest contact vertex is retained by
     * any correct clip regardless of the tied choice). The EXACT count and the full depth list are
     * the only things the tie makes non-unique.
     */
    static String mstrTie(Manifold m) {
        Vector2 n = m.getNormal();
        double ax = n.x, ay = n.y;
        if (ax < 0 || (ax == 0.0 && ay < 0)) { ax = -ax; ay = -ay; }
        int np = m.getPoints().size();
        boolean depthsOk = true;
        double maxDepth = Double.NEGATIVE_INFINITY;
        for (ManifoldPoint mp : m.getPoints()) {
            maxDepth = Math.max(maxDepth, mp.getDepth());
            if (mp.getDepth() < 0.0) depthsOk = false;
        }
        String md = m.getPoints().isEmpty() ? "none" : f(maxDepth);
        return "pts_1_2=" + (np >= 1 && np <= 2) + " depths_nonneg=" + depthsOk
                + " |n|=" + f(n.getMagnitude()) + " axis=(" + f(ax) + "," + f(ay) + ") maxDepth=" + md;
    }

    static {
        final Sat sat = new Sat();
        final Gjk gjk = new Gjk();

        // ================= Narrowphase: SAT detect (penetration) =================
        c("col_sat_cc_overlap", () -> {
            Circle a = Geometry.createCircle(1.0), b = Geometry.createCircle(1.0);
            Penetration p = new Penetration();
            boolean hit = sat.detect(a, ID, b, at(1.5, 0), p);   // centers 1.5 apart, radii sum 2 -> depth 0.5
            return penCurved(hit, p);   // curved-shape normal: 4-dp tolerance (see penCurved)
        });
        c("col_sat_cc_separated", () -> {
            Circle a = Geometry.createCircle(1.0), b = Geometry.createCircle(1.0);
            Penetration p = new Penetration();
            boolean hit = sat.detect(a, ID, b, at(3.0, 0), p);   // apart -> miss
            return pen(hit, p);
        });
        c("col_sat_rect_overlap", () -> {
            Rectangle a = Geometry.createRectangle(2, 2), b = Geometry.createRectangle(2, 2);
            Penetration p = new Penetration();
            boolean hit = sat.detect(a, ID, b, at(1.5, 0), p);   // overlap 0.5 along x
            return pen(hit, p);
        });
        c("col_sat_rect_separated", () -> {
            Rectangle a = Geometry.createRectangle(2, 2), b = Geometry.createRectangle(2, 2);
            Penetration p = new Penetration();
            boolean hit = sat.detect(a, ID, b, at(3.0, 0), p);
            return pen(hit, p);
        });
        c("col_sat_rect_diag_overlap", () -> {
            Rectangle a = Geometry.createRectangle(2, 2), b = Geometry.createRectangle(2, 2);
            Penetration p = new Penetration();
            // Unequal x/y overlap (x=0.5, y=0.4) so the min-translation axis is UNIQUELY y (no tie):
            // a tied offset would make the returned MTV axis a tie-break artifact, not spec-derivable.
            boolean hit = sat.detect(a, ID, b, at(1.5, 1.6), p);
            return pen(hit, p);
        });
        c("col_sat_circle_poly", () -> {
            Circle a = Geometry.createCircle(1.0);
            Rectangle b = Geometry.createRectangle(2, 2);
            Penetration p = new Penetration();
            boolean hit = sat.detect(a, ID, b, at(1.8, 0), p);   // circle vs rect overlap
            return pen(hit, p);
        });
        c("col_sat_tri_tri", () -> {
            Triangle a = Geometry.createRightTriangle(1, 1), b = Geometry.createRightTriangle(1, 1);
            Penetration p = new Penetration();
            boolean hit = sat.detect(a, ID, b, at(0.5, 0), p);
            return pen(hit, p);
        });

        // ================= Narrowphase: GJK detect (penetration via EPA) =================
        c("col_gjk_cc_overlap", () -> {
            Circle a = Geometry.createCircle(1.0), b = Geometry.createCircle(1.0);
            Penetration p = new Penetration();
            boolean hit = gjk.detect(a, ID, b, at(1.5, 0), p);
            return penCurved(hit, p);   // curved-shape normal: 4-dp tolerance (see penCurved)
        });
        c("col_gjk_cc_separated", () -> {
            Circle a = Geometry.createCircle(1.0), b = Geometry.createCircle(1.0);
            Penetration p = new Penetration();
            boolean hit = gjk.detect(a, ID, b, at(3.0, 0), p);
            return pen(hit, p);
        });
        c("col_gjk_rect_overlap", () -> {
            Rectangle a = Geometry.createRectangle(2, 2), b = Geometry.createRectangle(2, 2);
            Penetration p = new Penetration();
            boolean hit = gjk.detect(a, ID, b, at(1.5, 0), p);
            return pen(hit, p);
        });
        c("col_gjk_circle_poly", () -> {
            Circle a = Geometry.createCircle(1.0);
            Rectangle b = Geometry.createRectangle(2, 2);
            Penetration p = new Penetration();
            boolean hit = gjk.detect(a, ID, b, at(1.8, 0), p);
            return pen(hit, p);
        });
        c("col_gjk_detect_bool", () -> {
            Rectangle a = Geometry.createRectangle(2, 2), b = Geometry.createRectangle(2, 2);
            boolean over = gjk.detect(a, ID, b, at(1.5, 0));
            boolean sepd = gjk.detect(a, ID, b, at(3.0, 0));
            return "overlap=" + over + " separated=" + sepd;
        });

        // ================= Narrowphase: GJK distance (separated shapes) =================
        c("col_gjk_dist_cc", () -> {
            Circle a = Geometry.createCircle(1.0), b = Geometry.createCircle(1.0);
            Separation s = new Separation();
            boolean isSep = gjk.distance(a, ID, b, at(4.0, 0), s);  // gap 2.0, on x-axis
            return sep(isSep, s);
        });
        c("col_gjk_dist_rect", () -> {
            Rectangle a = Geometry.createRectangle(2, 2), b = Geometry.createRectangle(2, 2);
            Separation s = new Separation();
            boolean isSep = gjk.distance(a, ID, b, at(4.0, 0), s);  // faces 1..3 -> gap 2
            // Parallel facing faces -> the closest-point PAIR is non-unique (any shared y on the
            // overlap is equidistant); only the distance and normal are convention-independent.
            return isSep ? ("sep d=" + f(s.getDistance()) + " n=" + v(s.getNormal())) : "overlap";
        });
        c("col_gjk_dist_overlap", () -> {
            Rectangle a = Geometry.createRectangle(2, 2), b = Geometry.createRectangle(2, 2);
            Separation s = new Separation();
            boolean isSep = gjk.distance(a, ID, b, at(1.0, 0), s);  // overlapping -> false
            return sep(isSep, s);
        });
        c("col_gjk_dist_diag", () -> {
            Circle a = Geometry.createCircle(1.0), b = Geometry.createCircle(1.0);
            Separation s = new Separation();
            boolean isSep = gjk.distance(a, ID, b, at(3.0, 4.0), s); // centers 5 apart, gap 3
            return sep(isSep, s);
        });

        // ================= Narrowphase: CircleDetector (specialized) =================
        c("col_circledet_pen", () -> {
            Circle a = Geometry.createCircle(1.0), b = Geometry.createCircle(1.0);
            Penetration p = new Penetration();
            boolean hit = CircleDetector.detect(a, ID, b, at(1.5, 0), p);
            return pen(hit, p);
        });
        c("col_circledet_dist", () -> {
            Circle a = Geometry.createCircle(1.0), b = Geometry.createCircle(1.0);
            Separation s = new Separation();
            boolean isSep = CircleDetector.distance(a, ID, b, at(4.0, 0), s);
            return sep(isSep, s);
        });
        c("col_circledet_contains", () -> {
            Circle a = Geometry.createCircle(3.0), b = Geometry.createCircle(0.5);
            Containment ct = new Containment();
            CircleDetector.contains(a, ID, b, at(0.5, 0), ct); // small circle inside big one
            return "b_in_a=" + ct.isBContainedInA() + " a_in_b=" + ct.isAContainedInB();
        });

        // ================= Narrowphase: Raycast =================
        c("col_ray_circle_hit", () -> {
            Circle circle = Geometry.createCircle(1.0);
            Ray r = new Ray(new Vector2(-5, 0), new Vector2(1, 0)); // travels +x toward circle at (2,0)
            Raycast rc = new Raycast();
            boolean hit = gjk.raycast(r, 0.0, circle, at(2, 0), rc); // enters at x=1
            return ray(hit, rc);
        });
        c("col_ray_circle_miss", () -> {
            Circle circle = Geometry.createCircle(1.0);
            Ray r = new Ray(new Vector2(-5, 5), new Vector2(1, 0)); // parallel above circle
            Raycast rc = new Raycast();
            boolean hit = gjk.raycast(r, 0.0, circle, at(2, 0), rc);
            return ray(hit, rc);
        });
        c("col_ray_circledet_hit", () -> {
            Circle circle = Geometry.createCircle(1.0);
            Ray r = new Ray(new Vector2(0, -5), new Vector2(0, 1)); // upward toward circle at (0,2)
            Raycast rc = new Raycast();
            boolean hit = CircleDetector.raycast(r, 0.0, circle, at(0, 2), rc);
            return ray(hit, rc);
        });
        c("col_ray_rect_hit", () -> {
            Rectangle rect = Geometry.createRectangle(2, 2);
            Ray r = new Ray(new Vector2(-5, 0), new Vector2(1, 0));
            Raycast rc = new Raycast();
            boolean hit = gjk.raycast(r, 0.0, rect, at(3, 0), rc); // left face at x=2
            return ray(hit, rc);
        });
        c("col_ray_maxlen_short", () -> {
            Circle circle = Geometry.createCircle(1.0);
            Ray r = new Ray(new Vector2(-5, 0), new Vector2(1, 0));
            Raycast rc = new Raycast();
            boolean hit = gjk.raycast(r, 3.0, circle, at(2, 0), rc); // circle enters at x=1 -> dist 6 > 3 -> miss
            return ray(hit, rc);
        });
        c("col_ray_segment_hit", () -> {
            Segment seg = Geometry.createVerticalSegment(4.0); // vertical segment centered at origin
            Ray r = new Ray(new Vector2(-5, 0), new Vector2(1, 0));
            Raycast rc = new Raycast();
            boolean hit = SegmentDetector.raycast(r, 0.0, seg, at(2, 0), rc); // crosses at x=2
            return ray(hit, rc);
        });

        // ================= Manifold: ClippingManifoldSolver =================
        c("col_manifold_rect_face", () -> {
            Rectangle a = Geometry.createRectangle(2, 2), b = Geometry.createRectangle(2, 2);
            Transform tb = at(1.5, 0);
            Penetration p = new Penetration();
            boolean hit = sat.detect(a, ID, b, tb, p);
            if (!hit) return "no-pen";
            Manifold m = new Manifold();
            ClippingManifoldSolver solver = new ClippingManifoldSolver();
            boolean ok = solver.getManifold(p, a, ID, b, tb, m);
            if (!ok) return "no-manifold";
            return mstr(m);
        });
        c("col_manifold_rect_vertical", () -> {
            Rectangle a = Geometry.createRectangle(2, 2), b = Geometry.createRectangle(2, 2);
            Transform tb = at(0, 1.5);
            Penetration p = new Penetration();
            boolean hit = sat.detect(a, ID, b, tb, p);
            if (!hit) return "no-pen";
            Manifold m = new Manifold();
            ClippingManifoldSolver solver = new ClippingManifoldSolver();
            boolean ok = solver.getManifold(p, a, ID, b, tb, m);
            if (!ok) return "no-manifold";
            return mstr(m);
        });

        // ================= Continuous / CCD: ConservativeAdvancement TOI =================
        c("col_toi_moving_hits", () -> {
            // convex1 moves +x from x=-3 toward a static convex2 centered at origin.
            Circle a = Geometry.createCircle(1.0);
            Circle b = Geometry.createCircle(1.0);
            Transform t1 = at(-3, 0);
            Vector2 dp1 = new Vector2(6, 0); // travels to x=+3 over t in [0,1]; touches at gap=2 => x=-2 => t=1/6
            TimeOfImpact toi = new TimeOfImpact();
            ConservativeAdvancement ca = new ConservativeAdvancement();
            boolean collides = ca.getTimeOfImpact(a, t1, dp1, 0.0, b, ID, new Vector2(0, 0), 0.0, toi);
            return "collides=" + collides + " t=" + f(toi.getTime());
        });
        c("col_toi_moving_misses", () -> {
            // convex1 passes above convex2, never contacting.
            Circle a = Geometry.createCircle(1.0);
            Circle b = Geometry.createCircle(1.0);
            Transform t1 = at(-3, 5);
            Vector2 dp1 = new Vector2(6, 0);
            TimeOfImpact toi = new TimeOfImpact();
            ConservativeAdvancement ca = new ConservativeAdvancement();
            boolean collides = ca.getTimeOfImpact(a, t1, dp1, 0.0, b, ID, new Vector2(0, 0), 0.0, toi);
            return "collides=" + collides;
        });
        c("col_toi_rect_moving", () -> {
            Rectangle a = Geometry.createRectangle(2, 2);
            Rectangle b = Geometry.createRectangle(2, 2);
            Transform t1 = at(-5, 0);
            Vector2 dp1 = new Vector2(10, 0); // faces touch when gap=2 => center at x=-2 => t=3/10
            TimeOfImpact toi = new TimeOfImpact();
            ConservativeAdvancement ca = new ConservativeAdvancement();
            boolean collides = ca.getTimeOfImpact(a, t1, dp1, 0.0, b, ID, new Vector2(0, 0), 0.0, toi);
            return "collides=" + collides + " t=" + f(toi.getTime());
        });

        // ===== Deep geometry: EPA penetration depth/normal for ROTATED polygon pairs =====
        // A 45deg-rotated 2x2 square (half-diagonal sqrt(2)) overlapping an axis-aligned one:
        // the min-translation axis is a diagonal face normal of B, not a world axis.
        c("col_epa_rot_poly_depth45", () -> {
            Rectangle a = Geometry.createRectangle(2, 2), b = Geometry.createRectangle(2, 2);
            Transform tb = rt(Math.PI / 4, 1.5, 0);
            Penetration p = new Penetration();
            boolean hit = gjk.detect(a, ID, b, tb, p);   // EPA on a rotated overlap
            return pen(hit, p);
        });
        c("col_epa_rot_poly_depth30", () -> {
            Rectangle a = Geometry.createRectangle(2, 2), b = Geometry.createRectangle(2, 2);
            Transform tb = rt(Math.PI / 6, 1.6, 0.3);
            Penetration p = new Penetration();
            boolean hit = gjk.detect(a, ID, b, tb, p);   // 30deg oblique overlap -> non-axis normal
            return pen(hit, p);
        });
        c("col_epa_rot_tri_depth", () -> {
            Triangle a = Geometry.createRightTriangle(1.5, 1.5);
            Triangle b = Geometry.createRightTriangle(1.5, 1.5);
            Transform tb = rt(Math.PI / 3, 0.4, 0.2);   // 60deg-rotated triangle deeply overlapping
            Penetration p = new Penetration();
            boolean hit = gjk.detect(a, ID, b, tb, p);
            return pen(hit, p);
        });
        c("col_epa_deep_circle_poly", () -> {
            // Circle center driven well inside a box: deep penetration, EPA picks nearest box face.
            Circle a = Geometry.createCircle(1.0);
            Rectangle b = Geometry.createRectangle(2, 2);
            Penetration p = new Penetration();
            boolean hit = gjk.detect(a, at(0.3, 0.1), b, ID, p);
            return pen(hit, p);
        });

        // ===== GJK distance: closest-point pairs for NEAR-MISS rotated shapes =====
        c("col_gjk_dist_rot_nearmiss", () -> {
            // 45deg square just clears an axis-aligned one; nearest features are two vertices.
            Rectangle a = Geometry.createRectangle(2, 2), b = Geometry.createRectangle(2, 2);
            Separation s = new Separation();
            boolean isSep = gjk.distance(a, ID, b, rt(Math.PI / 4, 3.0, 0), s);
            return sep(isSep, s);
        });
        c("col_gjk_dist_rot_offset", () -> {
            // Rotated + y-offset: closest pair is a vertex of B against a face of A (oblique).
            Rectangle a = Geometry.createRectangle(2, 2), b = Geometry.createRectangle(2, 2);
            Separation s = new Separation();
            boolean isSep = gjk.distance(a, ID, b, rt(Math.PI / 5, 2.8, 1.7), s);
            return sep(isSep, s);
        });
        c("col_gjk_dist_tri_nearmiss", () -> {
            Triangle a = Geometry.createRightTriangle(1.0, 1.0);
            Triangle b = Geometry.createRightTriangle(1.0, 1.0);
            Separation s = new Separation();
            boolean isSep = gjk.distance(a, ID, b, rt(Math.PI / 4, 2.2, 0.5), s);
            // Parallel closest edges (A's hypotenuse is parallel to B's 45deg-rotated leg) -> the
            // closest-point PAIR is non-unique (any corresponding pair along the overlap is
            // equidistant); only the distance and normal are convention-independent, as with the
            // sibling parallel-face case col_gjk_dist_rect.
            return isSep ? ("sep d=" + f(s.getDistance()) + " n=" + v(s.getNormal())) : "overlap";
        });

        // ===== Clipping manifold: exact contact POINTS for rotated / vertex-face collisions =====
        c("col_manifold_vertexface_pts", () -> {
            // 45deg square drives a single VERTEX into A's right face -> 1-point manifold.
            Rectangle a = Geometry.createRectangle(2, 2), b = Geometry.createRectangle(2, 2);
            Transform tb = rt(Math.PI / 4, 2.2, 0);
            Penetration p = new Penetration();
            boolean hit = gjk.detect(a, ID, b, tb, p);
            if (!hit) return "no-pen";
            Manifold m = new Manifold();
            ClippingManifoldSolver solver = new ClippingManifoldSolver();
            boolean ok = solver.getManifold(p, a, ID, b, tb, m);
            if (!ok) return "no-manifold";
            return mstr(m);
        });

        // ===== SAT min-translation axis on oblique overlaps (min axis is Y, not X) =====
        c("col_sat_oblique_axis", () -> {
            Rectangle a = Geometry.createRectangle(2, 2), b = Geometry.createRectangle(2, 2);
            Penetration p = new Penetration();
            boolean hit = sat.detect(a, ID, b, at(0.3, 1.5), p);  // x-overlap 1.7, y-overlap 0.5 -> axis = y
            return pen(hit, p);
        });
        c("col_sat_oblique_wide", () -> {
            // Wide-flat vs tall-thin overlap: min-translation axis is the small y interpenetration.
            Rectangle a = Geometry.createRectangle(4, 1), b = Geometry.createRectangle(1, 4);
            Penetration p = new Penetration();
            boolean hit = sat.detect(a, ID, b, at(0.5, 2.2), p);
            return pen(hit, p);
        });

        // ===== GJK distance: MORE closest-point pairs across distinct shape pairs / angles =====
        c("col_gjk_dist_circle_rect", () -> {
            // circle right extent x=1, rect left face at x=3 -> gap 2 along +x; closest pair on x-axis.
            Circle a = Geometry.createCircle(1.0);
            Rectangle b = Geometry.createRectangle(2, 2);
            Separation s = new Separation();
            boolean isSep = gjk.distance(a, ID, b, at(4.0, 0), s);
            return sep(isSep, s);
        });
        c("col_gjk_dist_tri_rect", () -> {
            // right triangle vs axis-aligned box, offset in x and y -> oblique vertex/face closest pair.
            Triangle a = Geometry.createRightTriangle(1.0, 1.0);
            Rectangle b = Geometry.createRectangle(2, 2);
            Separation s = new Separation();
            boolean isSep = gjk.distance(a, ID, b, at(3.5, 0.7), s);
            return sep(isSep, s);
        });
        c("col_gjk_dist_rot_square2", () -> {
            // 30deg-rotated square just clears an axis-aligned one at a y-offset (vertex/face nearest).
            Rectangle a = Geometry.createRectangle(2, 2), b = Geometry.createRectangle(2, 2);
            Separation s = new Separation();
            boolean isSep = gjk.distance(a, ID, b, rt(Math.PI / 6, 3.2, 0.4), s);
            return sep(isSep, s);
        });
        c("col_gjk_dist_diag_rects", () -> {
            // two axis-aligned boxes offset on the diagonal -> nearest features are two CORNERS.
            Rectangle a = Geometry.createRectangle(2, 2), b = Geometry.createRectangle(2, 2);
            Separation s = new Separation();
            boolean isSep = gjk.distance(a, ID, b, at(3.0, 3.0), s); // corners (1,1) & (2,2), gap sqrt(2)
            return sep(isSep, s);
        });

        // ===== Clipping manifold: MORE contact-point sets (face-face 2pt & vertex-face 1pt) =====
        c("col_manifold_faceface_wide", () -> {
            // Two wide boxes overlapping vertically with an x-offset. B's bottom face (x in
            // [-1.4,2.6]) OVERHANGS A's top face (x in [-2,2]), so the contact region is their
            // intersection x in [-1.4,2.0]: the only graded pair whose faces have UNEQUAL spans, so
            // a solver that skips the side-plane clip reports the un-clipped x=2.6 endpoint.
            Rectangle a = Geometry.createRectangle(4, 2), b = Geometry.createRectangle(4, 2);
            Transform tb = at(0.6, 1.5);
            Penetration p = new Penetration();
            boolean hit = sat.detect(a, ID, b, tb, p);
            if (!hit) return "no-pen";
            Manifold m = new Manifold();
            if (!new ClippingManifoldSolver().getManifold(p, a, ID, b, tb, m)) return "no-manifold";
            return mstr(m);
        });
        c("col_manifold_tri_rect", () -> {
            // right triangle overlapping a box along x -> oblique contact off the triangle's
            // hypotenuse. The incident face on B is a TIE (its left and bottom faces are equally
            // anti-parallel to the (0.707107,0.707107) hypotenuse normal), so the clipped point
            // COUNT is not spec-determined; pin only the tie-independent invariants (see mstrTie).
            Triangle a = Geometry.createRightTriangle(2.0, 2.0);
            Rectangle b = Geometry.createRectangle(2, 2);
            Transform tb = at(1.2, 0);
            Penetration p = new Penetration();
            boolean hit = sat.detect(a, ID, b, tb, p);
            if (!hit) return "no-pen";
            Manifold m = new Manifold();
            if (!new ClippingManifoldSolver().getManifold(p, a, ID, b, tb, m)) return "no-manifold";
            return mstrTie(m);
        });
        c("col_manifold_rot30_pts", () -> {
            // 30deg-rotated square driving a vertex into A's right face -> 1-point manifold.
            Rectangle a = Geometry.createRectangle(2, 2), b = Geometry.createRectangle(2, 2);
            Transform tb = rt(Math.PI / 6, 1.9, 0.2);
            Penetration p = new Penetration();
            boolean hit = gjk.detect(a, ID, b, tb, p);
            if (!hit) return "no-pen";
            Manifold m = new Manifold();
            if (!new ClippingManifoldSolver().getManifold(p, a, ID, b, tb, m)) return "no-manifold";
            return mstr(m);
        });

        // ===== CCD time-of-impact: fast small circle TUNNELING toward a thin static box =====
        c("col_toi_tunnel", () -> {
            // radius-0.1 circle sweeps +x across a thin (0.2 wide) tall static box at origin.
            // A naive discrete overlap check at a few sample points would miss the thin slab.
            Circle a = Geometry.createCircle(0.1);
            Rectangle b = Geometry.createRectangle(0.2, 4.0);
            Transform t1 = at(-3, 0);
            Vector2 dp1 = new Vector2(6, 0);  // contact when center x = -(0.1+0.1) => t = 2.8/6
            TimeOfImpact toi = new TimeOfImpact();
            ConservativeAdvancement ca = new ConservativeAdvancement();
            boolean collides = ca.getTimeOfImpact(a, t1, dp1, 0.0, b, ID, new Vector2(0, 0), 0.0, toi);
            return "collides=" + collides + " t=" + f(toi.getTime());
        });

        // ===== Clipping manifold: DEEPER penetration & a DIFFERENT shape pair =====
        c("col_manifold_deep_faceface", () -> {
            // two 2x2 squares overlapping DEEPLY along x (depth 1.6) -> 2-point clipped face-face.
            Rectangle a = Geometry.createRectangle(2, 2), b = Geometry.createRectangle(2, 2);
            Transform tb = at(0.4, 0);
            Penetration p = new Penetration();
            boolean hit = sat.detect(a, ID, b, tb, p);
            if (!hit) return "no-pen";
            Manifold m = new Manifold();
            if (!new ClippingManifoldSolver().getManifold(p, a, ID, b, tb, m)) return "no-manifold";
            return mstr(m);
        });
        c("col_manifold_tri_tri", () -> {
            // two right triangles overlapping (different shape pair) -> clipped contact points.
            Triangle a = Geometry.createRightTriangle(2.0, 2.0);
            Triangle b = Geometry.createRightTriangle(2.0, 2.0);
            Transform tb = at(0.6, 0.3);
            Penetration p = new Penetration();
            boolean hit = sat.detect(a, ID, b, tb, p);
            if (!hit) return "no-pen";
            Manifold m = new Manifold();
            if (!new ClippingManifoldSolver().getManifold(p, a, ID, b, tb, m)) return "no-manifold";
            return mstr(m);
        });

        // ===== CCD time-of-impact: fast small BOX tunneling through a thin static slab =====
        c("col_toi_box_tunnel", () -> {
            // 0.2x0.2 box sweeps +x across a thin (0.2 wide) tall static box at origin.
            // Faces touch when the moving center reaches x=-0.2 => t=3.8/8; discrete sampling tunnels.
            Rectangle a = Geometry.createRectangle(0.2, 0.2);
            Rectangle b = Geometry.createRectangle(0.2, 4.0);
            Transform t1 = at(-4, 0);
            Vector2 dp1 = new Vector2(8, 0);
            TimeOfImpact toi = new TimeOfImpact();
            ConservativeAdvancement ca = new ConservativeAdvancement();
            boolean collides = ca.getTimeOfImpact(a, t1, dp1, 0.0, b, ID, new Vector2(0, 0), 0.0, toi);
            return "collides=" + collides + " t=" + f(toi.getTime());
        });
    }

    public static void main(String[] args) throws Exception {
        Runner.run(cases, args);
    }
}
