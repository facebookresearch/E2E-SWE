import org.physkit.geometry.*;
import org.physkit.dynamics.*;
import org.physkit.world.*;
import org.physkit.world.listener.*;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness — StepListener callbacks (lsn_step_*). Isolated into its own driver so a
 * StepListener/PhysicsWorld signature mismatch cannot compile-wipe the other listener or broad-phase
 * cases. Deterministic fixed-step simulation via world.step(n, dt); asserts integer callback counts.
 */
public class StepListenerHarness {
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

    /** Counting StepListener: tallies each of the four step callbacks. */
    static final class CountingStep extends StepListenerAdapter<Body> {
        int begin, update, post, end;
        @Override public void begin(TimeStep s, PhysicsWorld<Body, ?> w) { begin++; }
        @Override public void updatePerformed(TimeStep s, PhysicsWorld<Body, ?> w) { update++; }
        @Override public void postSolve(TimeStep s, PhysicsWorld<Body, ?> w) { post++; }
        @Override public void end(TimeStep s, PhysicsWorld<Body, ?> w) { end++; }
    }

    static {
        // StepListener.begin/end fire exactly once per world.step, so N single-steps -> N each;
        // postSolve likewise runs once per step (after the solve). updatePerformed is NOT asserted:
        // its firing cadence is a dyn4j-internal accumulator detail the spec does not define.
        c("lsn_step_counts", () -> {
            World<Body> w = new World<>();
            w.setGravity(World.ZERO_GRAVITY);
            CountingStep sl = new CountingStep();
            w.addStepListener(sl);
            w.addBody(box(1, 1, 0, 0));
            for (int i = 0; i < 5; i++) w.step(1, DT);
            return "begin=" + sl.begin + " post=" + sl.post + " end=" + sl.end;
        });

        // A single batched step(n, dt) invocation still fires the step callbacks n times.
        c("lsn_step_batched", () -> {
            World<Body> w = new World<>();
            w.setGravity(World.ZERO_GRAVITY);
            CountingStep sl = new CountingStep();
            w.addStepListener(sl);
            w.addBody(box(1, 1, 0, 0));
            w.step(7, DT);
            return "begin=" + sl.begin + " end=" + sl.end;
        });

        // Removing a step listener stops further callbacks (registration round-trip).
        c("lsn_step_remove", () -> {
            World<Body> w = new World<>();
            w.setGravity(World.ZERO_GRAVITY);
            CountingStep sl = new CountingStep();
            w.addStepListener(sl);
            w.addBody(box(1, 1, 0, 0));
            w.step(3, DT);
            int afterFirst = sl.begin;
            boolean removed = w.removeStepListener(sl);
            w.step(3, DT);
            return "afterFirst=" + afterFirst + " removed=" + removed + " final=" + sl.begin;
        });

        // getStepListeners reflects registered listeners.
        c("lsn_step_registered", () -> {
            World<Body> w = new World<>();
            w.addStepListener(new CountingStep());
            w.addStepListener(new CountingStep());
            return String.valueOf(w.getStepListeners().size());
        });
    }

    public static void main(String[] args) throws Exception {
        Runner.run(cases, args);
    }
}
