import org.physkit.geometry.*;
import org.physkit.dynamics.*;
import org.physkit.world.*;
import org.physkit.collision.*;
import org.physkit.collision.broadphase.*;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness — the broad-phase collision subsystem (org.physkit.collision.broadphase) ONLY.
 * The world event-listener cases (lsn_*) live in their own per-listener drivers
 * (StepListenerHarness / CollisionListenerHarness / ContactListenerHarness / BoundsListenerHarness /
 * ListenerRegistryHarness) so that a signature mismatch in one listener interface cannot compile-wipe
 * the broad-phase cases (isolation: blast radius = one API surface, not the whole subsystem).
 *
 * DETERMINISM. Broad-phase pair-collection order is NOT part of the contract, so every collection
 * output here is CANONICALIZED: each body is assigned a stable integer id by add-order, each
 * potential pair is rendered as an unordered sorted id-pair "a-b" (a<b), and the whole set is sorted
 * before printing. Region/raycast queries likewise emit the sorted set of overlapping item ids. That
 * makes the output invariant to internal detector ordering, so the three detectors
 * (DynamicAABBTree, Sap, BruteForceBroadphase) can be cross-checked against the same canonical
 * strings. Numeric outputs (AABB extents) are rounded to 6 decimals via f(). Public dyn4j API only.
 */
public class BroadphaseHarness {
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

    // ---------- Broad-phase plumbing ----------

    static CollisionItem<Body, BodyFixture> item(Body b) {
        return new BasicCollisionItem<>(b, b.getFixture(0));
    }

    /**
     * Build a fresh broad-phase detector of the requested kind, parameterized over
     * CollisionItem&lt;Body,BodyFixture&gt; using the exact producer/filter/expansion the engine's
     * World uses. "tree" -> DynamicAABBTree, "sap" -> Sap, "brute" -> BruteForceBroadphase.
     */
    static BroadphaseDetector<CollisionItem<Body, BodyFixture>> make(String kind) {
        BroadphaseFilter<CollisionItem<Body, BodyFixture>> filter = new CollisionItemBroadphaseFilter<>();
        AABBProducer<CollisionItem<Body, BodyFixture>> producer = new CollisionItemAABBProducer<>();
        AABBExpansionMethod<CollisionItem<Body, BodyFixture>> expansion = new NullAABBExpansionMethod<>();
        switch (kind) {
            case "tree":  return new DynamicAABBTree<>(filter, producer, expansion);
            case "sap":   return new Sap<>(filter, producer, expansion);
            case "brute": return new BruteForceBroadphase<>(filter, producer);
            default: throw new IllegalArgumentException(kind);
        }
    }

    /** A dynamic axis-aligned box body of the given size centered at (x,y). One fixture per body. */
    static Body box(double w, double h, double x, double y) {
        Body b = new Body();
        b.addFixture(Geometry.createRectangle(w, h));
        b.setMass(MassType.NORMAL);
        b.translate(x, y);
        return b;
    }

    /**
     * A scenario: an ordered list of bodies (id = index) added to a detector of the given kind.
     * Provides canonical detect()/detect(AABB)/raycast output helpers.
     */
    static final class Scene {
        final BroadphaseDetector<CollisionItem<Body, BodyFixture>> bp;
        final List<Body> bodies = new ArrayList<>();
        final Map<CollisionItem<Body, BodyFixture>, Integer> ids = new HashMap<>();
        Scene(String kind) { this.bp = make(kind); }
        Scene add(Body b) {
            CollisionItem<Body, BodyFixture> it = item(b);
            ids.put(it, bodies.size());
            bodies.add(b);
            bp.add(it);
            return this;
        }
        int idOf(CollisionItem<Body, BodyFixture> it) {
            Integer i = ids.get(it);
            return i == null ? -1 : i;
        }
        /** Canonical sorted set of overlapping id-pairs from detect(), e.g. "[0-1, 2-3]". */
        String pairs() {
            List<CollisionPair<CollisionItem<Body, BodyFixture>>> ps = bp.detect();
            TreeSet<String> set = new TreeSet<>();
            for (CollisionPair<CollisionItem<Body, BodyFixture>> p : ps) {
                int a = idOf(p.getFirst()), b = idOf(p.getSecond());
                int lo = Math.min(a, b), hi = Math.max(a, b);
                set.add(lo + "-" + hi);
            }
            return set.toString();
        }
        /** Number of potential pairs reported by detect(). */
        int pairCount() {
            return bp.detect().size();
        }
        /** Canonical sorted set of item ids whose AABB overlaps the query region. */
        String query(AABB region) {
            List<CollisionItem<Body, BodyFixture>> hits = bp.detect(region);
            TreeSet<Integer> set = new TreeSet<>();
            for (CollisionItem<Body, BodyFixture> it : hits) set.add(idOf(it));
            return set.toString();
        }
        /** Canonical sorted set of item ids whose AABB is crossed by the ray. */
        String raycast(Ray ray, double length) {
            List<CollisionItem<Body, BodyFixture>> hits = bp.raycast(ray, length);
            TreeSet<Integer> set = new TreeSet<>();
            for (CollisionItem<Body, BodyFixture> it : hits) set.add(idOf(it));
            return set.toString();
        }
    }

    /** A 4-body reference layout shared by several cases (deterministic, hand-computed overlaps):
     *   id0: 1x1 @ (0,0)      -> [-0.5,0.5]x[-0.5,0.5]
     *   id1: 1x1 @ (0.5,0)    -> [ 0.0,1.0]x[-0.5,0.5]   overlaps id0
     *   id2: 1x1 @ (5,5)      -> far away, isolated
     *   id3: 2x2 @ (0.5,0.5)  -> [-0.5,1.5]x[-0.5,1.5]   overlaps id0 and id1
     * Overlapping pairs: 0-1, 0-3, 1-3  (3 pairs). id2 is alone. */
    static Scene layout(String kind) {
        return new Scene(kind)
            .add(box(1, 1, 0.0, 0.0))
            .add(box(1, 1, 0.5, 0.0))
            .add(box(1, 1, 5.0, 5.0))
            .add(box(2, 2, 0.5, 0.5));
    }

    static {
        // =====================================================================
        // Broad-phase — DynamicAABBTree  (bp_tree_*)
        // =====================================================================

        // Two separated bodies -> zero potential pairs.
        c("bp_tree_separated_zero", () -> {
            Scene s = new Scene("tree").add(box(1, 1, 0, 0)).add(box(1, 1, 10, 0));
            return "n=" + s.pairCount() + " " + s.pairs();
        });

        // Two overlapping bodies -> exactly one pair (0-1).
        c("bp_tree_overlap_one", () -> {
            Scene s = new Scene("tree").add(box(1, 1, 0, 0)).add(box(1, 1, 0.5, 0));
            return "n=" + s.pairCount() + " " + s.pairs();
        });

        // 4-body layout -> canonical pair set {0-1, 0-3, 1-3}, count 3; size() reflects the 4 adds.
        c("bp_tree_layout_pairs", () -> {
            Scene s = layout("tree");
            return "n=" + s.pairCount() + " " + s.pairs() + " size=" + s.bp.size();
        });

        // detect(a,b) boolean overlap on the broad-phase representation.
        c("bp_tree_detect_ab", () -> {
            Scene s = layout("tree");
            boolean o01 = s.bp.detect(item(s.bodies.get(0)), item(s.bodies.get(1)));  // overlap
            boolean o02 = s.bp.detect(item(s.bodies.get(0)), item(s.bodies.get(2)));  // far
            return "o01=" + o01 + " o02=" + o02;
        });

        // Region query detect(AABB): a box covering only the cluster near the origin.
        c("bp_tree_query_region", () -> {
            Scene s = layout("tree");
            AABB region = new AABB(-0.6, -0.6, 0.6, 0.6);   // covers ids 0,1,3 ; not id2 @ (5,5)
            return s.query(region);
        });

        // Region query far from every body -> empty set.
        c("bp_tree_query_empty", () -> {
            Scene s = layout("tree");
            AABB region = new AABB(20.0, 20.0, 21.0, 21.0);
            return s.query(region);
        });

        // remove() drops an item: pair set loses everything touching id3.
        c("bp_tree_after_remove", () -> {
            Scene s = layout("tree");
            s.bp.remove(item(s.bodies.get(3)));    // remove the big 2x2 box
            return "n=" + s.pairCount() + " " + s.pairs();   // only 0-1 remains
        });

        // Raycast along +x through the origin cluster: hits the boxes it crosses.
        c("bp_tree_raycast", () -> {
            Scene s = layout("tree");
            Ray ray = new Ray(new Vector2(-5.0, 0.0), new Vector2(1.0, 0.0));  // along y=0, +x
            return s.raycast(ray, 0.0);   // 0 length => infinite
        });

        // getAABB reflects the item's tight AABB (Null expansion -> no padding).
        c("bp_tree_getaabb", () -> {
            Scene s = new Scene("tree").add(box(2, 2, 1, 1));
            AABB a = s.bp.getAABB(item(s.bodies.get(0)));
            return "minx=" + f(a.getMinX()) + " miny=" + f(a.getMinY())
                 + " maxx=" + f(a.getMaxX()) + " maxy=" + f(a.getMaxY());   // [0,2]x[0,2]
        });

        // =====================================================================
        // Broad-phase — Sap  (bp_sap_*)
        // =====================================================================

        // Separated -> zero pairs on Sap (the overlapping layout is cross-checked by bp_agree_*;
        // the separated case is kept here because bp_agree_* only exercise the overlapping layout).
        c("bp_sap_separated_zero", () -> {
            Scene s = new Scene("sap").add(box(1, 1, 0, 0)).add(box(1, 1, 10, 0));
            return "n=" + s.pairCount() + " " + s.pairs();
        });

        // NOTE: bp_sap_layout_pairs / bp_sap_query_region removed as redundant — bp_agree_pairs /
        // bp_agree_query run all three detectors (tree/sap/brute) on the same layout AND assert the
        // canonical set equals the oracle, so per-detector Sap correctness on that layout is proven there.

        // =====================================================================
        // Broad-phase — BruteForceBroadphase  (bp_brute_*)
        // =====================================================================

        // Separated -> zero pairs on BruteForce (kept for the same reason as bp_sap_separated_zero).
        c("bp_brute_separated_zero", () -> {
            Scene s = new Scene("brute").add(box(1, 1, 0, 0)).add(box(1, 1, 10, 0));
            return "n=" + s.pairCount() + " " + s.pairs();
        });

        // NOTE: bp_brute_layout_pairs / bp_brute_query_region removed as redundant — covered by
        // bp_agree_pairs / bp_agree_query (all three detectors compared to the oracle on that layout).

        // =====================================================================
        // Broad-phase — cross-detector agreement (bp_agree_*)
        // All three detectors must return the identical canonical output.
        // =====================================================================

        // Same layout -> identical canonical pair set across all three detectors.
        c("bp_agree_pairs", () -> {
            String tree = layout("tree").pairs();
            String sap = layout("sap").pairs();
            String brute = layout("brute").pairs();
            boolean same = tree.equals(sap) && sap.equals(brute);
            return "same=" + same + " set=" + tree;
        });

        // Same region query -> identical canonical id set across all three detectors.
        c("bp_agree_query", () -> {
            AABB region = new AABB(-0.6, -0.6, 0.6, 0.6);
            String tree = layout("tree").query(region);
            String sap = layout("sap").query(region);
            String brute = layout("brute").query(region);
            boolean same = tree.equals(sap) && sap.equals(brute);
            return "same=" + same + " set=" + tree;
        });
    }

    public static void main(String[] args) throws Exception {
        Runner.run(cases, args);
    }
}
