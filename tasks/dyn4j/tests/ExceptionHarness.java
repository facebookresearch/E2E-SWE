import org.physkit.geometry.*;
import org.physkit.dynamics.*;
import org.physkit.dynamics.joint.*;
import org.physkit.world.*;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness — the validation-exception subsystem (org.physkit.exception): the custom exception
 * types the library throws to guard its public API (ValueOutOfRangeException, ArgumentNullException,
 * NullElementException, EmptyCollectionException, SameObjectException, ObjectAlreadyExistsException,
 * ObjectAlreadyOwnedException, InvalidIndexException — several of which extend JDK exceptions like
 * IllegalArgumentException / NullPointerException / IndexOutOfBoundsException).
 *
 * Each case bundles several representative triggers of ONE exception type: it invokes each real
 * public API with invalid input inside try/catch, collects the SIMPLE class name of the thrown
 * exception (or "none" if nothing was thrown) for every trigger, and returns them joined with '|'.
 * Bundling every trigger of a single validation node into one multi-assertion case avoids rewarding
 * the same behavior multiple times. This is fully deterministic: the oracle for each case is the
 * exact '|'-joined string the reference throws (verified against the source guards). Oracle values
 * live in the committed /tests/expected.tsv fixture. Run with env CAPTURE=1 to print this part's
 * `name<TAB>value` lines; otherwise it grades against the fixture and emits one JSON line per case.
 * This file imports only PUBLIC dyn4j API.
 */
public class ExceptionHarness {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }

    /** Run the body; return the thrown exception's simple name, or "none". */
    static String thrown(Runnable r) {
        try { r.run(); return "none"; }
        catch (Exception e) { return e.getClass().getSimpleName(); }
    }

    /** Bundle multiple triggers: return their thrown simple-names joined with '|'. */
    @SafeVarargs
    static String bundle(Runnable... triggers) {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < triggers.length; i++) {
            if (i > 0) sb.append('|');
            sb.append(thrown(triggers[i]));
        }
        return sb.toString();
    }

    /** Build a valid, mass-bearing unit-square body (for joint / world triggers). */
    static Body square() {
        Body b = new Body();
        b.addFixture(Geometry.createSquare(1.0), 1.0);
        b.setMass(MassType.NORMAL);
        return b;
    }

    static {
        // =====================================================================
        // ValueOutOfRangeException — numeric / count out-of-range guards.
        // Bundles: Circle radius <= 0, Rectangle width/height <= 0, Capsule width <= 0,
        // Mass negative mass/inertia, Polygon with < 3 vertices.
        // =====================================================================
        c("exc_value_out_of_range", () -> bundle(
                () -> new Circle(-1.0),                                   // radius must be > 0
                () -> new Circle(0.0),                                    // radius zero also out of range
                () -> new Rectangle(-2.0, 1.0),                           // width must be > 0
                () -> new Rectangle(2.0, -1.0),                           // height must be > 0
                () -> new Capsule(-1.0, 0.5),                             // width must be > 0
                () -> new Mass(new Vector2(0, 0), -1.0, 1.0),            // negative mass
                () -> new Mass(new Vector2(0, 0), 1.0, -1.0),           // negative inertia
                () -> new Polygon(new Vector2(0, 0), new Vector2(1, 0))  // < 3 vertices
        ));

        // =====================================================================
        // ArgumentNullException — null-argument guards (extends NullPointerException).
        // Bundles: Mass null center, Geometry.createPolygon(null), Mass.create(null),
        // DistanceJoint null anchor.
        // =====================================================================
        c("exc_argument_null", () -> bundle(
                () -> new Mass(null, 1.0, 1.0),                          // center may not be null
                () -> Geometry.createPolygon((Vector2[]) null),          // null vertex array
                () -> Mass.create((List<Mass>) null),                    // null list
                () -> {                                                   // null joint anchor
                    Body b1 = square(), b2 = square();
                    new DistanceJoint<Body>(b1, b2, null, new Vector2(1, 0));
                }
        ));

        // =====================================================================
        // NullElementException — a null element inside an otherwise-valid collection.
        // =====================================================================
        c("exc_null_element", () -> bundle(
                () -> new Polygon(new Vector2(0, 0), null, new Vector2(1, 1))
        ));

        // =====================================================================
        // EmptyCollectionException — empty where non-empty is required.
        // =====================================================================
        c("exc_empty_collection", () -> bundle(
                () -> Mass.create(new ArrayList<Mass>())
        ));

        // =====================================================================
        // IllegalArgumentException — geometry-invariant guards (plain JDK IAE).
        // Bundles: degenerate/collinear polygon, Segment with coincident endpoints.
        // =====================================================================
        c("exc_illegal_argument", () -> bundle(
                () -> new Polygon(new Vector2(0, 0), new Vector2(1, 0), new Vector2(2, 0)), // collinear
                () -> new Segment(new Vector2(1, 1), new Vector2(1, 1))                     // same point
        ));

        // =====================================================================
        // SameObjectException — a paired-body joint linking a body to itself. All five paired-body
        // joints reject the same-object pair through the one shared super-constructor guard, so a
        // single bundled case covers that guard (PinJoint is single-body and is excluded).
        // =====================================================================
        c("exc_same_object", () -> bundle(
                () -> { Body b = square(); new DistanceJoint<Body>(b, b, new Vector2(0, 0), new Vector2(1, 0)); },
                () -> { Body b = square(); new RevoluteJoint<Body>(b, b, new Vector2(0, 0)); },
                () -> { Body b = square(); new WeldJoint<Body>(b, b, new Vector2(0, 0)); },
                () -> { Body b = square(); new PrismaticJoint<Body>(b, b, new Vector2(0, 0), new Vector2(1, 0)); },
                () -> { Body b = square(); new AngleJoint<Body>(b, b); }
        ));

        // =====================================================================
        // InvalidIndexException — joint body index outside {0, 1}.
        // =====================================================================
        c("exc_invalid_index", () -> bundle(
                () -> {
                    Body b1 = square(), b2 = square();
                    DistanceJoint<Body> dj = new DistanceJoint<>(b1, b2, new Vector2(0, 0), new Vector2(1, 0));
                    dj.getBody(2);   // valid indices are 0 and 1
                }
        ));

        // =====================================================================
        // ObjectAlreadyExistsException — adding the same body to a world twice.
        // =====================================================================
        c("exc_object_already_exists", () -> bundle(
                () -> {
                    World<Body> w = new World<>();
                    Body b = square();
                    w.addBody(b);
                    w.addBody(b);   // already owned by this world
                }
        ));

        // =====================================================================
        // ObjectAlreadyOwnedException — adding a body already owned by another world.
        // =====================================================================
        c("exc_object_already_owned", () -> bundle(
                () -> {
                    Body b = square();
                    World<Body> w1 = new World<>();
                    World<Body> w2 = new World<>();
                    w1.addBody(b);
                    w2.addBody(b);   // owned by w1
                }
        ));

        // =====================================================================
        // ArgumentNullException — null anchors/targets on the OTHER paired/pin joints.
        // (distinct bodies so the super-ctor same-object check passes first).
        // =====================================================================
        c("exc_argument_null_joints", () -> bundle(
                () -> { Body b1 = square(), b2 = square(); new RevoluteJoint<Body>(b1, b2, null); },
                () -> { Body b1 = square(), b2 = square(); new WeldJoint<Body>(b1, b2, null); },
                () -> { Body b = square(); new PinJoint<Body>(b, null); }
        ));

        // =====================================================================
        // ValueOutOfRangeException — non-positive dimensions on the curved shapes.
        // =====================================================================
        c("exc_value_out_of_range_shapes", () -> bundle(
                () -> new Capsule(1.0, -0.5),           // height must be > 0
                () -> new Ellipse(-2.0, 1.0),           // width must be > 0
                () -> new Slice(-1.0, Math.PI / 3),     // radius must be > 0
                () -> new HalfEllipse(2.0, -1.0)        // height must be > 0
        ));
    }

    public static void main(String[] args) throws Exception {
        Runner.run(cases, args);
    }
}
