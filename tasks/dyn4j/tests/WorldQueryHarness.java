import org.physkit.geometry.*;
import org.physkit.dynamics.*;
import org.physkit.world.*;
import org.physkit.world.result.*;
import org.physkit.collision.narrowphase.Raycast;
import org.physkit.collision.continuous.TimeOfImpact;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness — the World spatial-query result subsystem (org.physkit.world.result): the result
 * objects returned by the World's AABB detect / raycast / convex-cast queries, i.e. DetectResult,
 * RaycastResult and ConvexCastResult (plus their getters getBody()/getFixture()/getRaycast()/
 * getTimeOfImpact()). Each named case builds a deterministic World<Body> of fixed bodies at known
 * positions (as in DynamicsHarness), issues a spatial query, and canonicalizes the returned result
 * collection (sort + count + a stable identifier) so the oracle is order-independent.
 *
 * Determinism: bodies/positions/rays are fixed constants; every result collection is canonicalized
 * (sorted by a stable key, reported as count + set) and every numeric quantity is ROUNDED to 6
 * decimals via f()/v() so tiny cross-JDK floating-point differences do not cause spurious
 * mismatches. Oracle values live in the committed /tests/expected.tsv fixture (captured from the
 * reference). Run with env CAPTURE=1 to print this part's `name<TAB>value` lines (to regenerate the
 * fixture); otherwise it grades its cases against the fixture and emits one JSON line per case.
 * This file imports only PUBLIC dyn4j API.
 */
public class WorldQueryHarness {
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

    /** A non-filtering DetectFilter (allows everything). raycastClosest requires a non-null filter. */
    static DetectFilter<Body, BodyFixture> ALL() {
        return new DetectFilter<Body, BodyFixture>(false, false, null);
    }

    /** A dynamic square of the given side at (x,y). We tag each body via setUserData for a stable id. */
    static Body sq(String id, double side, double x, double y) {
        Body b = new Body();
        b.addFixture(Geometry.createSquare(side), 1.0);
        b.setMass(MassType.NORMAL);
        b.translate(x, y);
        b.setUserData(id);
        return b;
    }

    /**
     * A fixed 3-body world: A at (0,0), B at (5,0), C at (0,5); each a 1x1 square. No stepping —
     * queries are against the static initial layout, fully deterministic.
     */
    static World<Body> world3() {
        World<Body> w = new World<>();
        w.setGravity(World.ZERO_GRAVITY);
        w.addBody(sq("A", 1.0, 0.0, 0.0));
        w.addBody(sq("B", 1.0, 5.0, 0.0));
        w.addBody(sq("C", 1.0, 0.0, 5.0));
        return w;
    }

    /** Canonical id-set of the bodies referenced by a list of DetectResults (sorted, deduped). */
    static <R extends DetectResult<Body, BodyFixture>> String bodySet(List<R> results) {
        TreeSet<String> ids = new TreeSet<>();
        for (R r : results) ids.add(String.valueOf(r.getBody().getUserData()));
        return "n=" + results.size() + " {" + String.join(",", ids) + "}";
    }

    static {
        // =====================================================================
        // detect(AABB, DetectFilter) -> List<DetectResult<Body,BodyFixture>>
        // =====================================================================

        // A small region around the origin overlaps only body A.
        c("wq_detect_aabb_hits_A", () -> {
            World<Body> w = world3();
            AABB region = new AABB(-0.6, -0.6, 0.6, 0.6);
            List<DetectResult<Body, BodyFixture>> r = w.detect(region, ALL());
            return bodySet(r);   // n=1 {A}
        });

        // A wide horizontal band across y=0 overlaps A and B (both on the x-axis), not C.
        c("wq_detect_aabb_hits_A_B", () -> {
            World<Body> w = world3();
            AABB region = new AABB(-1.0, -0.6, 6.0, 0.6);
            return bodySet(w.detect(region, ALL()));   // n=2 {A,B}
        });

        // A big box enclosing everything hits all three.
        c("wq_detect_aabb_hits_all", () -> {
            World<Body> w = world3();
            AABB region = new AABB(-2.0, -2.0, 7.0, 7.0);
            return bodySet(w.detect(region, ALL()));   // n=3 {A,B,C}
        });

        // A region in empty space (far away) hits nothing.
        c("wq_detect_aabb_empty", () -> {
            World<Body> w = world3();
            AABB region = new AABB(20.0, 20.0, 21.0, 21.0);
            return bodySet(w.detect(region, ALL()));   // n=0 {}
        });

        // A region touching only C (near (0,5)).
        c("wq_detect_aabb_hits_C", () -> {
            World<Body> w = world3();
            AABB region = new AABB(-0.4, 4.4, 0.4, 5.6);
            return bodySet(w.detect(region, ALL()));   // n=1 {C}
        });

        // detect(AABB, body, filter): restrict the query to a SINGLE body's fixtures. Even though
        // the region encloses all three bodies, only body A's own fixtures are tested -> {A}.
        c("wq_detect_aabb_single_body", () -> {
            World<Body> w = world3();
            Body a = null;
            for (Body b : w.getBodies()) if ("A".equals(b.getUserData())) a = b;
            AABB region = new AABB(-2.0, -2.0, 7.0, 7.0);   // encloses all
            List<DetectResult<Body, BodyFixture>> r = w.detect(region, a, ALL());
            return bodySet(r);   // n=1 {A}
        });

        // =====================================================================
        // detect(Convex, Transform, DetectFilter) -> List<ConvexDetectResult>
        // =====================================================================

        // A convex probe (unit circle) placed at origin overlaps A only.
        c("wq_convex_detect_at_origin", () -> {
            World<Body> w = world3();
            Transform t = new Transform();   // identity -> circle centered at origin
            List<ConvexDetectResult<Body, BodyFixture>> r =
                    w.detect(Geometry.createCircle(0.5), t, ALL());
            return bodySet(r);   // n=1 {A}
        });

        // Convex probe (radius 0.6 circle) centered on B (1x1 square, same center) overlaps B only;
        // penetration depth = half-width 0.5 + radius 0.6 = 1.1 (a well-defined scalar).
        c("wq_convex_detect_penetration", () -> {
            World<Body> w = world3();
            Transform t = new Transform(); t.translate(5.0, 0.0);
            List<ConvexDetectResult<Body, BodyFixture>> r =
                    w.detect(Geometry.createCircle(0.6), t, ALL());
            String set = bodySet(r);
            String depth = r.isEmpty() ? "none" : f(r.get(0).getPenetration().getDepth());
            return set + " depth=" + depth;   // n=1 {B} depth=1.100000
        });

        // =====================================================================
        // raycast(Ray, maxLength, DetectFilter) -> List<RaycastResult>
        // =====================================================================

        // Ray from (-3,0) pointing +x along the x-axis crosses A then B.
        c("wq_raycast_axis_hits_A_B", () -> {
            World<Body> w = world3();
            Ray ray = new Ray(new Vector2(-3.0, 0.0), new Vector2(1.0, 0.0));
            List<RaycastResult<Body, BodyFixture>> r = w.raycast(ray, 20.0, ALL());
            return bodySet(r);   // n=2 {A,B}
        });

        // Same ray but short max length only reaches A.
        c("wq_raycast_short_length", () -> {
            World<Body> w = world3();
            Ray ray = new Ray(new Vector2(-3.0, 0.0), new Vector2(1.0, 0.0));
            List<RaycastResult<Body, BodyFixture>> r = w.raycast(ray, 3.0, ALL());
            return bodySet(r);   // n=1 {A}
        });

        // A ray pointing away from every body hits nothing.
        c("wq_raycast_miss", () -> {
            World<Body> w = world3();
            Ray ray = new Ray(new Vector2(-3.0, -3.0), new Vector2(0.0, -1.0));
            List<RaycastResult<Body, BodyFixture>> r = w.raycast(ray, 20.0, ALL());
            return bodySet(r);   // n=0 {}
        });

        // Manual "closest" from raycast list: sort by distance (RaycastResult is Comparable) and
        // take the nearest — that's body A. Assert its body id + hit distance (~2.5: ray starts at
        // x=-3, A's left face at x=-0.5).
        c("wq_raycast_sorted_closest", () -> {
            World<Body> w = world3();
            Ray ray = new Ray(new Vector2(-3.0, 0.0), new Vector2(1.0, 0.0));
            List<RaycastResult<Body, BodyFixture>> r = w.raycast(ray, 20.0, ALL());
            Collections.sort(r);   // uses RaycastResult.compareTo (by raycast distance)
            RaycastResult<Body, BodyFixture> closest = r.get(0);
            Raycast rc = closest.getRaycast();
            return "body=" + closest.getBody().getUserData()
                    + " dist=" + f(rc.getDistance())
                    + " point=" + v(rc.getPoint());
        });

        // =====================================================================
        // raycastClosest(Ray, maxLength, DetectFilter) -> RaycastResult
        // =====================================================================

        // Closest hit along +x is body A; assert body id, distance, hit point, that a fixture is
        // attached, and the surface normal of A's left face (the +x ray enters there, so it is
        // deterministically (-1,0)). Exercises RaycastResult.getBody()/getFixture()/getRaycast()
        // and Raycast.getDistance()/getPoint()/getNormal() in one closest-hit query.
        c("wq_raycast_closest_A", () -> {
            World<Body> w = world3();
            Ray ray = new Ray(new Vector2(-3.0, 0.0), new Vector2(1.0, 0.0));
            RaycastResult<Body, BodyFixture> res = w.raycastClosest(ray, 20.0, ALL());
            if (res == null) return "null";
            Raycast rc = res.getRaycast();
            boolean hasFixture = res.getFixture() != null;
            return "body=" + res.getBody().getUserData()
                    + " dist=" + f(rc.getDistance())
                    + " point=" + v(rc.getPoint())
                    + " fixture=" + hasFixture
                    + " n=" + v(rc.getNormal());
        });

        // raycastClosest that misses everything returns null.
        c("wq_raycast_closest_miss", () -> {
            World<Body> w = world3();
            Ray ray = new Ray(new Vector2(-3.0, -3.0), new Vector2(0.0, -1.0));
            RaycastResult<Body, BodyFixture> res = w.raycastClosest(ray, 20.0, ALL());
            return res == null ? "null" : "hit";   // null
        });

        // =====================================================================
        // convexCast(Convex, Transform, deltaPosition, deltaAngle, filter) -> List<ConvexCastResult>
        // convexCastClosest(...) -> ConvexCastResult
        // =====================================================================

        // Sweep a radius-0.25 circle from (-3,0) by delta (6,0) toward body A (left face at x=-0.5):
        // contact when the circle's leading edge reaches the face, i.e. center at x=-0.75, so the
        // time-of-impact = 2.25/6 = 0.375 (a well-defined value) — assert it exactly.
        c("wq_convex_cast_closest_A", () -> {
            World<Body> w = world3();
            Convex probe = Geometry.createCircle(0.25);
            Transform start = new Transform(); start.translate(-3.0, 0.0);
            Vector2 delta = new Vector2(6.0, 0.0);   // sweep to (3,0)
            ConvexCastResult<Body, BodyFixture> res =
                    w.convexCastClosest(probe, start, delta, 0.0, ALL());
            if (res == null) return "null";
            return "body=" + res.getBody().getUserData() + " t=" + f(res.getTimeOfImpact().getTime());
        });

        // convexCast list form: sweeping across the x-axis from far left to far right hits A and B.
        c("wq_convex_cast_list_A_B", () -> {
            World<Body> w = world3();
            Convex probe = Geometry.createCircle(0.25);
            Transform start = new Transform(); start.translate(-3.0, 0.0);
            Vector2 delta = new Vector2(10.0, 0.0);   // sweep past both A and B
            List<ConvexCastResult<Body, BodyFixture>> r =
                    w.convexCast(probe, start, delta, 0.0, ALL());
            return bodySet(r);   // n=2 {A,B}
        });

        // A sweep that never reaches any body (too short) hits nothing.
        c("wq_convex_cast_miss", () -> {
            World<Body> w = world3();
            Convex probe = Geometry.createCircle(0.25);
            Transform start = new Transform(); start.translate(-10.0, 0.0);
            Vector2 delta = new Vector2(1.0, 0.0);   // stays far to the left
            ConvexCastResult<Body, BodyFixture> res =
                    w.convexCastClosest(probe, start, delta, 0.0, ALL());
            return res == null ? "null" : "hit";   // null
        });
    }

    public static void main(String[] args) throws Exception {
        Runner.run(cases, args);
    }
}
