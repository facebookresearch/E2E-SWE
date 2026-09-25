import org.physkit.geometry.*;
import org.physkit.dynamics.*;
import org.physkit.world.*;
import org.physkit.world.listener.*;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness — BoundsListener callbacks (lsn_bounds_*). Isolated so the BoundsListener /
 * AxisAlignedBounds surface cannot compile-wipe other cases.
 */
public class BoundsListenerHarness {
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

    /** Counting BoundsListener: records whether any body left the world bounds. */
    static final class CountingBounds implements BoundsListener<Body, BodyFixture> {
        int outside;
        @Override public void outside(Body b) { outside++; }
    }

    static {
        // BoundsListener: with tight bounds, a body falling under gravity leaves the region.
        c("lsn_bounds_outside", () -> {
            World<Body> w = new World<>();
            w.setBounds(new org.physkit.collision.AxisAlignedBounds(4.0, 4.0));  // [-2,2]x[-2,2]
            CountingBounds bl = new CountingBounds();
            w.addBoundsListener(bl);
            Body b = box(0.5, 0.5, 0.0, 0.0);  // starts inside, falls out the bottom
            w.addBody(b);
            w.step(120, DT);
            return "outside=" + (bl.outside > 0);
        });

        // BoundsListener: a body that stays well within bounds never triggers outside().
        c("lsn_bounds_inside", () -> {
            World<Body> w = new World<>();
            w.setGravity(World.ZERO_GRAVITY);
            w.setBounds(new org.physkit.collision.AxisAlignedBounds(100.0, 100.0));
            CountingBounds bl = new CountingBounds();
            w.addBoundsListener(bl);
            w.addBody(box(1, 1, 0, 0));
            w.step(60, DT);
            return "outside=" + bl.outside;
        });
    }

    public static void main(String[] args) throws Exception {
        Runner.run(cases, args);
    }
}
