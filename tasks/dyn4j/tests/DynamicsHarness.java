import org.physkit.geometry.*;
import org.physkit.dynamics.*;
import org.physkit.dynamics.joint.*;
import org.physkit.world.*;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness — the dynamics + world subsystem (org.physkit.dynamics, org.physkit.dynamics.joint,
 * org.physkit.world): rigid-body mass/inertia, force/impulse/torque accumulation and integration,
 * deterministic world simulation under gravity, collisions/resting contacts, and joint invariants.
 * Each named case produces a single string; oracle values live in the committed /tests/expected.tsv
 * fixture (captured from the reference). Run with env CAPTURE=1 to print this part's `name<TAB>value`
 * lines; otherwise it grades its own cases against the fixture and emits one JSON line per case.
 *
 * Determinism: every simulated case steps the world with an explicit fixed timestep via
 * world.step(n, dt) (never wall-clock update()), so integration is reproducible. Numeric outputs are
 * ROUNDED to 6 decimals via f()/v() so tiny cross-JDK floating-point differences don't cause spurious
 * mismatches; solver-sensitive quantities use INVARIANT-style assertions with tolerance-friendly
 * rounding. This file imports only PUBLIC dyn4j API.
 */
public class DynamicsHarness {
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

    /** Round to a coarser number of decimals (for solver-sensitive invariants). */
    static String fr(double val, int decimals) {
        double scale = Math.pow(10, decimals);
        double r = Math.round(val * scale) / scale;
        if (r == 0.0) r = 0.0;
        return String.format(Locale.ROOT, "%." + decimals + "f", r);
    }

    static final double DT = 1.0 / 60.0;

    /** A fresh 1x1 square dynamic body of density 1 with computed mass. */
    static Body dynSquare(double side, double density, double x, double y) {
        Body b = new Body();
        b.addFixture(Geometry.createSquare(side), density);
        b.setMass(MassType.NORMAL);
        b.translate(x, y);
        return b;
    }

    static {
        // =====================================================================
        // Body / mass  (org.physkit.dynamics)
        // =====================================================================

        // Mass of a square fixture with density: m = density * area.
        c("dyn_body_mass_square", () -> {
            Body b = new Body();
            b.addFixture(Geometry.createSquare(2.0), 3.0);   // area 4, density 3 -> m=12
            b.setMass(MassType.NORMAL);
            return mass(b.getMass());
        });

        // Mass of a circle fixture: m = density * pi * r^2, I about center.
        c("dyn_body_mass_circle", () -> {
            Body b = new Body();
            b.addFixture(Geometry.createCircle(1.0), 2.0);
            b.setMass(MassType.NORMAL);
            return mass(b.getMass());
        });

        // INFINITE mass type -> zero inverse mass (static-like), reported mass 0.
        c("dyn_body_mass_infinite", () -> {
            Body b = new Body();
            b.addFixture(Geometry.createSquare(1.0), 1.0);
            b.setMass(MassType.INFINITE);
            Mass m = b.getMass();
            return "m=" + f(m.getMass()) + " I=" + f(m.getInertia());
        });

        // FIXED_LINEAR_VELOCITY: infinite linear mass, finite inertia.
        c("dyn_body_mass_fixed_linear", () -> {
            Body b = new Body();
            b.addFixture(Geometry.createSquare(2.0), 1.0);
            b.setMass(MassType.FIXED_LINEAR_VELOCITY);
            Mass m = b.getMass();
            return "m=" + f(m.getMass()) + " I=" + f(m.getInertia());
        });

        // Two fixtures combine mass and shift the center of mass.
        c("dyn_body_mass_two_fixtures", () -> {
            Body b = new Body();
            BodyFixture f1 = b.addFixture(Geometry.createSquare(1.0), 1.0);       // at origin
            BodyFixture f2 = b.addFixture(Geometry.createSquare(1.0), 1.0);       // shifted
            f2.getShape().translate(2.0, 0.0);
            b.setMass(MassType.NORMAL);
            return mass(b.getMass());   // total m=2, center at (1,0)
        });

        // applyForce accumulates into the (world-frame) force accumulator.
        c("dyn_body_accum_force", () -> {
            Body b = dynSquare(1.0, 1.0, 0, 0);
            b.applyForce(new Vector2(3.0, -4.0));
            b.applyForce(new Vector2(1.0, 1.0));
            return v(b.getAccumulatedForce());   // (4,-3)
        });

        // applyTorque accumulates torque.
        c("dyn_body_accum_torque", () -> {
            Body b = dynSquare(1.0, 1.0, 0, 0);
            b.applyTorque(2.5);
            b.applyTorque(0.5);
            return f(b.getAccumulatedTorque());   // 3.0
        });

        // Off-center force also produces torque about the center of mass.
        c("dyn_body_force_at_point", () -> {
            Body b = dynSquare(2.0, 1.0, 0, 0);   // center at origin
            b.applyForce(new Vector2(0.0, 5.0), new Vector2(1.0, 0.0));  // r=(1,0) x F=(0,5) => tau=5
            return "F=" + v(b.getAccumulatedForce()) + " T=" + f(b.getAccumulatedTorque());
        });

        // applyImpulse changes linear velocity immediately: dv = J / m.
        c("dyn_body_impulse_linear", () -> {
            Body b = new Body();
            b.addFixture(Geometry.createSquare(2.0), 1.0);   // m=4
            b.setMass(MassType.NORMAL);
            b.applyImpulse(new Vector2(8.0, -4.0));           // dv = (2,-1)
            return v(b.getLinearVelocity());
        });

        // Angular impulse changes angular velocity: dw = J / I.
        c("dyn_body_impulse_angular", () -> {
            Body b = new Body();
            b.addFixture(Geometry.createSquare(2.0), 1.0);
            b.setMass(MassType.NORMAL);
            double I = b.getMass().getInertia();
            b.applyImpulse(I * 2.0);        // dw = 2.0
            return f(b.getAngularVelocity());
        });

        // A constant force integrated one explicit step: v = (F/m)*dt (semi-implicit Euler).
        c("dyn_body_integrate_force_1step", () -> {
            World<Body> w = new World<>();
            w.setGravity(World.ZERO_GRAVITY);
            Body b = new Body();
            b.addFixture(Geometry.createSquare(2.0), 1.0);   // m=4
            b.setMass(MassType.NORMAL);
            b.applyForce(new Vector2(4.0, 0.0));             // a = 1 m/s^2
            w.addBody(b);
            w.step(1, DT);
            return v(b.getLinearVelocity());   // v = (1*dt, 0)
        });

        // =====================================================================
        // World simulation  (org.physkit.world.World) — deterministic fixed steps
        // =====================================================================

        // Free fall under gravity: velocity after N steps = g * N * dt.
        c("dyn_world_freefall_velocity", () -> {
            World<Body> w = new World<>();   // default EARTH_GRAVITY (0,-9.8)
            Body b = dynSquare(1.0, 1.0, 0, 0);
            w.addBody(b);
            w.step(10, DT);
            return v(b.getLinearVelocity());
        });

        // Free fall position after N steps (deterministic integrator trajectory).
        c("dyn_world_freefall_position", () -> {
            World<Body> w = new World<>();
            Body b = dynSquare(1.0, 1.0, 0, 5);
            w.addBody(b);
            w.step(30, DT);
            return v(b.getWorldCenter());
        });

        // Zero gravity + no forces: body stays exactly put.
        c("dyn_world_no_gravity_static", () -> {
            World<Body> w = new World<>();
            w.setGravity(World.ZERO_GRAVITY);
            Body b = dynSquare(1.0, 1.0, 2, 3);
            w.addBody(b);
            w.step(50, DT);
            return v(b.getWorldCenter());
        });

        // Initial velocity in zero gravity: pure translation x = v*t.
        c("dyn_world_ballistic_zero_g", () -> {
            World<Body> w = new World<>();
            w.setGravity(World.ZERO_GRAVITY);
            Body b = dynSquare(1.0, 1.0, 0, 0);
            b.setLinearVelocity(new Vector2(2.0, 0.0));
            w.addBody(b);
            w.step(60, DT);
            return v(b.getWorldCenter());   // x = 2 * 60 * dt = 2.0
        });

        // Static (infinite) floor: a body falling onto it comes to rest (restitution 0).
        // Invariant: resting y is stable — assert with coarse rounding to absorb solver detail.
        c("dyn_world_rest_on_floor", () -> {
            World<Body> w = new World<>();
            // floor: wide static box centered at y=0, top at y=0.5
            Body floor = new Body();
            floor.addFixture(Geometry.createRectangle(20.0, 1.0));
            floor.setMass(MassType.INFINITE);
            floor.translate(0.0, 0.0);
            w.addBody(floor);
            // falling 1x1 box starting above the floor
            Body box = new Body();
            BodyFixture bf = box.addFixture(Geometry.createSquare(1.0), 1.0);
            bf.setRestitution(0.0);
            box.setMass(MassType.NORMAL);
            box.translate(0.0, 4.0);
            w.addBody(box);
            w.step(240, DT);   // plenty of time to settle
            // box half-height 0.5 rests on floor top 0.5 -> center ~1.0. Rounded to 1 decimal so the
            // solver's (unspecified) resting penetration slop is absorbed: any near-rest settles to 1.0.
            return "y=" + fr(box.getWorldCenter().y, 1);
        });

        // After resting, the box's vertical velocity is ~0 (invariant, coarse round).
        c("dyn_world_rest_velocity_zero", () -> {
            World<Body> w = new World<>();
            Body floor = new Body();
            floor.addFixture(Geometry.createRectangle(20.0, 1.0));
            floor.setMass(MassType.INFINITE);
            w.addBody(floor);
            Body box = new Body();
            BodyFixture bf = box.addFixture(Geometry.createSquare(1.0), 1.0);
            bf.setRestitution(0.0);
            box.setMass(MassType.NORMAL);
            box.translate(0.0, 4.0);
            w.addBody(box);
            w.step(240, DT);
            return "vy=" + fr(box.getLinearVelocity().y, 2);
        });

        // Elastic bounce off a floor (restitution 1): body rises back up.
        // Invariant: after bouncing, vy becomes positive (going up). Coarse sign/magnitude.
        c("dyn_world_elastic_bounce_up", () -> {
            World<Body> w = new World<>();
            Body floor = new Body();
            BodyFixture ff = floor.addFixture(Geometry.createRectangle(20.0, 1.0));
            ff.setRestitution(1.0);
            floor.setMass(MassType.INFINITE);
            w.addBody(floor);
            Body ball = new Body();
            BodyFixture bf = ball.addFixture(Geometry.createCircle(0.5), 1.0);
            bf.setRestitution(1.0);
            ball.setMass(MassType.NORMAL);
            ball.translate(0.0, 3.0);
            w.addBody(ball);
            // step until it has bounced (velocity turns upward)
            boolean bounced = false;
            for (int i = 0; i < 200 && !bounced; i++) {
                w.step(1, DT);
                if (ball.getLinearVelocity().y > 0.5) bounced = true;
            }
            return String.valueOf(bounced);
        });

        // Inelastic head-on collision of two equal free bodies (zero g, restitution 0). By momentum
        // conservation the symmetric pair (v=+1 / v=-1) coalesces to the common center-of-mass
        // velocity 0, so BOTH bodies come to rest in x. This discriminates real collision response:
        // a pass-through / broken solver leaves a at vx=+1 and fails, whereas the trivially-conserved
        // total momentum (already 0 initially) would pass either way. Coarse round.
        c("dyn_world_inelastic_common_velocity", () -> {
            World<Body> w = new World<>();
            w.setGravity(World.ZERO_GRAVITY);
            Body a = new Body();
            BodyFixture af = a.addFixture(Geometry.createSquare(1.0), 1.0);   // m=1
            af.setRestitution(0.0);
            a.setMass(MassType.NORMAL);
            a.translate(-2.0, 0.0);
            a.setLinearVelocity(new Vector2(1.0, 0.0));
            w.addBody(a);
            Body b = new Body();
            BodyFixture bf = b.addFixture(Geometry.createSquare(1.0), 1.0);   // m=1
            bf.setRestitution(0.0);
            b.setMass(MassType.NORMAL);
            b.translate(2.0, 0.0);
            b.setLinearVelocity(new Vector2(-1.0, 0.0));
            w.addBody(b);
            w.step(300, DT);
            return "a_vx=" + fr(a.getLinearVelocity().x, 2) + " b_vx=" + fr(b.getLinearVelocity().x, 2);
        });

        // Symmetric elastic head-on collision: bodies separate (relative velocity reverses sign).
        // Invariant: after collision a moves left / b moves right (they bounced apart).
        c("dyn_world_collision_separates", () -> {
            World<Body> w = new World<>();
            w.setGravity(World.ZERO_GRAVITY);
            Body a = new Body();
            BodyFixture af = a.addFixture(Geometry.createSquare(1.0), 1.0);
            af.setRestitution(1.0);
            a.setMass(MassType.NORMAL);
            a.translate(-2.0, 0.0);
            a.setLinearVelocity(new Vector2(2.0, 0.0));
            w.addBody(a);
            Body b = new Body();
            BodyFixture bf = b.addFixture(Geometry.createSquare(1.0), 1.0);
            bf.setRestitution(1.0);
            b.setMass(MassType.NORMAL);
            b.translate(2.0, 0.0);
            b.setLinearVelocity(new Vector2(-2.0, 0.0));
            w.addBody(b);
            w.step(300, DT);
            boolean separated = a.getLinearVelocity().x < 0 && b.getLinearVelocity().x > 0;
            return String.valueOf(separated);
        });

        // World gravity: default is EARTH_GRAVITY (0,-9.8), and setGravity/getGravity round-trips a
        // non-default value (so a stub that just hardcodes the default constant fails the round-trip).
        c("dyn_world_gravity_default", () -> {
            World<Body> w = new World<>();
            String def = v(w.getGravity());          // default (0,-9.8)
            w.setGravity(new Vector2(1.0, -3.5));
            return "default=" + def + " set=" + v(w.getGravity());
        });

        // =====================================================================
        // Joints  (org.physkit.dynamics.joint) — assert enforced invariants
        // =====================================================================

        // DistanceJoint (rigid, spring disabled): distance between anchors stays ~constant
        // even as the hung body swings under gravity. Coarse round to absorb constraint drift.
        c("dyn_joint_distance_invariant", () -> {
            World<Body> w = new World<>();
            Body anchor = new Body();
            anchor.addFixture(Geometry.createCircle(0.1));
            anchor.setMass(MassType.INFINITE);
            anchor.translate(0.0, 5.0);
            w.addBody(anchor);
            Body bob = dynSquare(0.5, 1.0, 2.0, 5.0);
            w.addBody(bob);
            DistanceJoint<Body> dj = new DistanceJoint<>(anchor, bob,
                    new Vector2(0.0, 5.0), new Vector2(2.0, 5.0));   // rest distance 2
            w.addJoint(dj);
            w.step(120, DT);   // let it swing
            double dist = dj.getAnchor1().distance(dj.getAnchor2());
            return "d=" + fr(dist, 1) + " rest=" + f(dj.getRestDistance());
        });

        // DistanceJoint rest distance is set from the initial anchor separation.
        c("dyn_joint_distance_rest", () -> {
            Body b1 = dynSquare(1, 1, 0, 0);
            Body b2 = dynSquare(1, 1, 3, 4);
            DistanceJoint<Body> dj = new DistanceJoint<>(b1, b2,
                    new Vector2(0, 0), new Vector2(3, 4));
            return f(dj.getRestDistance());   // 5
        });

        // RevoluteJoint: the two anchor points stay coincident (that's what it enforces).
        // Coarse round to absorb small solver separation.
        c("dyn_joint_revolute_coincident", () -> {
            World<Body> w = new World<>();
            Body base = new Body();
            base.addFixture(Geometry.createSquare(0.5));
            base.setMass(MassType.INFINITE);
            base.translate(0.0, 5.0);
            w.addBody(base);
            Body arm = dynSquare(1.0, 1.0, 1.0, 5.0);
            w.addBody(arm);
            RevoluteJoint<Body> rj = new RevoluteJoint<>(base, arm, new Vector2(0.0, 5.0));
            w.addJoint(rj);
            w.step(120, DT);
            double gap = rj.getAnchor1().distance(rj.getAnchor2());
            return "gap=" + fr(gap, 2);   // ~0
        });

        // WeldJoint: rigidly locks two bodies — anchors coincident AND relative angle fixed.
        c("dyn_joint_weld_locks", () -> {
            World<Body> w = new World<>();
            Body base = new Body();
            base.addFixture(Geometry.createSquare(0.5));
            base.setMass(MassType.INFINITE);
            base.translate(0.0, 5.0);
            w.addBody(base);
            Body b = dynSquare(1.0, 1.0, 1.0, 5.0);
            w.addBody(b);
            WeldJoint<Body> wj = new WeldJoint<>(base, b, new Vector2(0.5, 5.0));
            w.addJoint(wj);
            double angle0 = b.getTransform().getRotationAngle();
            w.step(120, DT);
            double gap = wj.getAnchor1().distance(wj.getAnchor2());
            double dAngle = Math.abs(b.getTransform().getRotationAngle() - angle0);
            return "gap=" + fr(gap, 2) + " dAngle=" + fr(dAngle, 2);
        });

        // PrismaticJoint: motion constrained to the axis — bodies stay collinear along it.
        // Invariant: the anchor separation perpendicular to the axis stays ~0.
        c("dyn_joint_prismatic_axis", () -> {
            World<Body> w = new World<>();
            w.setGravity(new Vector2(0.0, -9.8));
            Body base = new Body();
            base.addFixture(Geometry.createSquare(0.5));
            base.setMass(MassType.INFINITE);
            base.translate(0.0, 5.0);
            w.addBody(base);
            Body slider = dynSquare(0.5, 1.0, 0.0, 5.0);
            w.addBody(slider);
            // vertical axis: slider may move up/down but not sideways
            PrismaticJoint<Body> pj = new PrismaticJoint<>(base, slider,
                    new Vector2(0.0, 5.0), new Vector2(0.0, 1.0));
            w.addJoint(pj);
            w.step(120, DT);
            // slider's x should stay at the base x (no lateral drift)
            return "x=" + fr(slider.getWorldCenter().x, 2);   // ~0
        });

        // PinJoint (target spring): it attaches the body to the world-space target with a spring.
        // Pin the body to its start position and run under gravity: an unpinned body would free-fall
        // ~19.6m in 2s, but the spring must hold this one at the target. Assert that + the target getter.
        c("dyn_joint_pin_target", () -> {
            World<Body> w = new World<>();   // default EARTH_GRAVITY (0,-9.8)
            Body b = dynSquare(1, 1, 0, 5);
            w.addBody(b);
            Vector2 target = new Vector2(0.0, 5.0);
            PinJoint<Body> pin = new PinJoint<>(b, target);
            w.addJoint(pin);
            for (int i = 0; i < 120; i++) w.step(1, DT);
            boolean held = b.getWorldCenter().distance(target) < 0.5;   // spring held it against gravity
            return "target=" + v(pin.getTarget()) + " held=" + held;
        });

        // AngleJoint: with ratio 1.0 it couples the two bodies' rotations, so torquing one keeps their
        // RELATIVE angle locked. Assert the enforced invariant (dRel ~ 0) plus the ratio default.
        c("dyn_joint_angle_ratio", () -> {
            World<Body> w = new World<>();
            w.setGravity(World.ZERO_GRAVITY);
            Body b1 = dynSquare(1, 1, 0, 0);
            Body b2 = dynSquare(1, 1, 2, 0);
            w.addBody(b1);
            w.addBody(b2);
            AngleJoint<Body> aj = new AngleJoint<>(b1, b2);
            w.addJoint(aj);
            double rel0 = b2.getTransform().getRotationAngle() - b1.getTransform().getRotationAngle();
            b1.applyTorque(5.0);   // spin b1; the joint must drag b2 along so the relative angle holds
            for (int i = 0; i < 120; i++) w.step(1, DT);
            double rel1 = b2.getTransform().getRotationAngle() - b1.getTransform().getRotationAngle();
            boolean locked = Math.abs(rel1 - rel0) < 0.1;
            return "ratio=" + f(aj.getRatio()) + " locked=" + locked;
        });

        // Two revolute-linked bodies: relative angle can change (pendulum swings), but anchor
        // coincidence holds. This exercises the joint under real dynamics.
        c("dyn_joint_revolute_pendulum", () -> {
            World<Body> w = new World<>();
            Body pivot = new Body();
            pivot.addFixture(Geometry.createCircle(0.05));
            pivot.setMass(MassType.INFINITE);
            pivot.translate(0.0, 5.0);
            w.addBody(pivot);
            Body rod = dynSquare(0.4, 2.0, 1.0, 5.0);
            w.addBody(rod);
            RevoluteJoint<Body> rj = new RevoluteJoint<>(pivot, rod, new Vector2(0.0, 5.0));
            w.addJoint(rj);
            w.step(60, DT);
            // pivot anchor stays put; rod fell so its center moved down from y=5
            boolean pivotFixed = fr(rj.getAnchor1().distance(new Vector2(0.0, 5.0)), 3).equals("0.000");
            boolean rodDropped = rod.getWorldCenter().y < 5.0;
            return "pivotFixed=" + pivotFixed + " rodDropped=" + rodDropped;
        });
    }

    public static void main(String[] args) throws Exception {
        Runner.run(cases, args);
    }
}
