import org.physkit.geometry.*;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness — the geometry subsystem (org.physkit.geometry): vectors, transforms, mass/inertia
 * of shapes, AABBs, and shape geometry. Each named case produces a single string; oracle values live
 * in the committed /tests/expected.tsv fixture (captured from the reference). Run with env CAPTURE=1
 * to print this part's `name<TAB>value` lines (to regenerate the fixture); otherwise it grades its
 * own cases against the fixture and emits one JSON line per case for the CTRF bridge.
 *
 * Numeric outputs are ROUNDED to 6 decimals via f()/v() so tiny cross-JDK / cross-platform floating
 * point differences do not cause spurious mismatches; the committed oracle is validated by GT eval.
 * This file imports ONLY org.physkit.geometry.*, so it compiles for any submission that implements the
 * geometry package independent of collision/dynamics.
 */
public class GeometryHarness {
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
    static String mass(Mass m) { return "m=" + f(m.getMass()) + " I=" + f(m.getInertia()) + " c=" + v(m.getCenter()); }

    static {
        // ---- Vector2 algebra (bundled: each cluster of trivial same-node ops is one case) ----
        // Scalar-returning queries: dot / cross / magnitude / distance / direction / angleBetween.
        c("vec_algebra", () -> {
            Vector2 a = new Vector2(1, 2), b = new Vector2(3, 4);
            return "dot=" + f(a.dot(b))                                       // 11
                 + " cross=" + f(a.cross(b))                                  // -2
                 + " mag=" + f(new Vector2(3, 4).getMagnitude())             // 5
                 + " dist=" + f(new Vector2(0, 0).distance(new Vector2(3, 4)))// 5
                 + " dir=" + f(new Vector2(1, 1).getDirection())            // pi/4
                 + " ang=" + f(new Vector2(1, 0).getAngleBetween(new Vector2(0, 1))); // pi/2
        });
        // The two orthogonal-vector accessors.
        c("vec_ortho", () -> "left=" + v(new Vector2(1, 0).getLeftHandOrthogonalVector())  // (0,-1)
                           + " right=" + v(new Vector2(1, 0).getRightHandOrthogonalVector())); // (0,1)
        // Vector-returning transforms: normalize / project / rotate / lerp / tripleProduct.
        c("vec_vectorops", () -> "norm=" + v(new Vector2(3, 4).getNormalized())            // (0.6,0.8)
                               + " proj=" + v(new Vector2(2, 2).project(new Vector2(1, 0)))// (2,0)
                               + " rot=" + v(new Vector2(1, 0).copy().rotate(Math.PI / 2)) // (0,1)
                               + " lerp=" + v(new Vector2(0, 0).lerp(new Vector2(4, 8), 0.25)) // (1,2)
                               + " triple=" + v(Vector2.tripleProduct(new Vector2(1, 0), new Vector2(0, 1), new Vector2(1, 0))));

        // ---- Transform: rotate then translate, forward + inverse ----
        // Bundled: forward getTransformed + getRotationAngle readback (same Transform node).
        c("xf_transform", () -> {
            Transform t = new Transform();
            t.rotate(Math.PI / 2);        // (1,0) -> (0,1)
            t.translate(1, 2);            // + (1,2) -> (1,3)
            return "p=" + v(t.getTransformed(new Vector2(1, 0))) + " ang=" + f(t.getRotationAngle());
        });
        c("xf_inverse_roundtrip", () -> {
            Transform t = new Transform();
            t.rotate(0.7); t.translate(3, -2);
            Vector2 p = new Vector2(5, 7);
            return v(t.getInverseTransformed(t.getTransformed(p)));   // back to (5,7)
        });

        // ---- Mass / inertia (createMass(density)) ----
        c("mass_circle",    () -> mass(Geometry.createCircle(1.0).createMass(1.0)));                 // m=pi, I=0.5*m*r^2
        c("mass_rectangle", () -> mass(Geometry.createRectangle(2.0, 1.0).createMass(1.0)));         // m=2, I=m*(w^2+h^2)/12
        c("mass_square",    () -> mass(Geometry.createSquare(2.0).createMass(2.0)));                 // m=8
        c("mass_triangle",  () -> mass(Geometry.createEquilateralTriangle(1.0).createMass(1.0)));

        // ---- Shape geometry: area / radius / AABB ----
        // Bundled trivial getArea() readbacks for two shapes (same getter node, distinct shapes).
        c("area_shapes", () -> "rect=" + f(Geometry.createRectangle(2.0, 3.0).getArea())             // 6
                             + " circle=" + f(Geometry.createCircle(2.0).getArea()));                // 4*pi
        // Rotated-rect AABB projection kept SEPARATE (discriminating: extents of a rotated shape).
        c("aabb_rect_rot45", () -> {
            Transform t = new Transform(); t.rotate(Math.PI / 4);
            AABB a = Geometry.createRectangle(2.0, 2.0).createAABB(t);
            return "w=" + f(a.getWidth()) + " h=" + f(a.getHeight());                                // 2*sqrt(2)
        });
        // Bundled AABB accessors + predicates (circle extents, union, intersection, overlaps both
        // ways) into one multi-assertion case — folds the former bare-boolean aabb_overlaps into an
        // exact-value case.
        c("aabb_accessors", () -> {
            AABB ca = Geometry.createCircle(1.5).createAABB(new Transform());
            AABB a  = Geometry.createRectangle(2, 2).createAABB(new Transform());
            Transform tf = new Transform(); tf.translate(3, 0);
            AABB far = Geometry.createRectangle(2, 2).createAABB(tf);
            Transform tn = new Transform(); tn.translate(1.5, 0);
            AABB near = Geometry.createRectangle(2, 2).createAABB(tn);
            AABB u  = a.getUnion(far);
            AABB ix = a.getIntersection(near);
            return "cw=" + f(ca.getWidth()) + " ch=" + f(ca.getHeight()) + " cc=" + v(ca.getCenter())
                 + " uminx=" + f(u.getMinX()) + " umaxx=" + f(u.getMaxX())                            // -1 .. 4
                 + " overlaps_near=" + a.overlaps(near) + " overlaps_far=" + a.overlaps(far)
                 + " ixminx=" + f(ix.getMinX()) + " ixmaxx=" + f(ix.getMaxX());
        });

        // ---- Geometry helpers ----
        c("area_weighted_center", () -> v(Geometry.getAreaWeightedCenter(
                new Vector2(0, 0), new Vector2(2, 0), new Vector2(2, 2), new Vector2(0, 2))));       // (1,1)
    }

    public static void main(String[] args) throws Exception {
        Runner.run(cases, args);
    }
}
