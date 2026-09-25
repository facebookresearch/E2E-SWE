import org.physkit.geometry.*;
import org.physkit.dynamics.*;
import org.physkit.world.*;
import org.physkit.world.listener.*;
import org.physkit.collision.*;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness — CollisionListener callbacks (lsn_collision_*). Isolated so the three
 * *CollisionData stage overloads (a fragile signature surface) cannot compile-wipe other listener or
 * broad-phase cases. Deterministic fixed-step simulation; asserts callback firing.
 */
public class CollisionListenerHarness {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }

    static final double DT = 1.0 / 60.0;

    static Body box(double w, double h, double x, double y) {
        Body b = new Body();
        b.addFixture(Geometry.createRectangle(w, h));
        b.setMass(MassType.NORMAL);
        b.translate(x, y);
        return b;
    }

    /** floor: wide INFINITE static box, top at y=0.5 (centered at origin, 20x1). */
    static Body floor() {
        Body f = new Body();
        f.addFixture(Geometry.createRectangle(20.0, 1.0));
        f.setMass(MassType.INFINITE);
        return f;
    }

    /** falling 1x1 dynamic box (restitution 0) starting at the given height. */
    static Body faller(double y) {
        Body b = new Body();
        BodyFixture bf = b.addFixture(Geometry.createSquare(1.0));
        bf.setRestitution(0.0);
        b.setMass(MassType.NORMAL);
        b.translate(0.0, y);
        return b;
    }

    /** Counting CollisionListener: tallies broad/narrow/manifold collision callbacks. */
    static final class CountingCollision extends CollisionListenerAdapter<Body, BodyFixture> {
        int broad, narrow, manifold;
        @Override public boolean collision(BroadphaseCollisionData<Body, BodyFixture> d) { broad++; return true; }
        @Override public boolean collision(NarrowphaseCollisionData<Body, BodyFixture> d) { narrow++; return true; }
        @Override public boolean collision(ManifoldCollisionData<Body, BodyFixture> d) { manifold++; return true; }
    }

    static {
        // CollisionListener fires when a falling box lands on the floor (broad+narrow+manifold > 0).
        c("lsn_collision_fires", () -> {
            World<Body> w = new World<>();
            w.addBody(floor());
            w.addBody(faller(4.0));
            CountingCollision cl = new CountingCollision();
            w.addCollisionListener(cl);
            w.step(240, DT);   // let it fall and settle
            return "broad=" + (cl.broad > 0) + " narrow=" + (cl.narrow > 0)
                 + " manifold=" + (cl.manifold > 0);
        });

        // Two well-separated bodies in zero gravity never collide -> no collision callbacks.
        c("lsn_collision_none", () -> {
            World<Body> w = new World<>();
            w.setGravity(World.ZERO_GRAVITY);
            w.addBody(box(1, 1, 0, 0));
            w.addBody(box(1, 1, 10, 0));
            CountingCollision cl = new CountingCollision();
            w.addCollisionListener(cl);
            w.step(60, DT);
            return "broad=" + cl.broad + " narrow=" + cl.narrow + " manifold=" + cl.manifold;
        });
    }

    public static void main(String[] args) throws Exception {
        Runner.run(cases, args);
    }
}
