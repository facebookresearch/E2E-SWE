import org.physkit.geometry.*;
import org.physkit.dynamics.*;
import org.physkit.world.*;
import org.physkit.world.listener.*;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness — ContactListener callbacks (lsn_contact_*). Isolated so the ContactListener
 * 2-arg begin/end(ContactCollisionData, Contact) signature cannot compile-wipe other cases.
 */
public class ContactListenerHarness {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }

    static final double DT = 1.0 / 60.0;

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

    /** Counting ContactListener: tallies begin/end/collision contact callbacks. */
    static final class CountingContact extends ContactListenerAdapter<Body> {
        int begin, end, collision;
        @Override public void begin(ContactCollisionData<Body> d, org.physkit.dynamics.contact.Contact ct) { begin++; }
        @Override public void end(ContactCollisionData<Body> d, org.physkit.dynamics.contact.Contact ct) { end++; }
        @Override public void collision(ContactCollisionData<Body> d) { collision++; }
    }

    static {
        // ContactListener: a box landing and resting on the floor generates contact begins.
        c("lsn_contact_fires", () -> {
            World<Body> w = new World<>();
            w.addBody(floor());
            w.addBody(faller(4.0));
            CountingContact ct = new CountingContact();
            w.addContactListener(ct);
            w.step(240, DT);
            return "begin=" + (ct.begin > 0) + " collision=" + (ct.collision > 0);
        });
    }

    public static void main(String[] args) throws Exception {
        Runner.run(cases, args);
    }
}
