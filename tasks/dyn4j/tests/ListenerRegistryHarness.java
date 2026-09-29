import org.physkit.geometry.*;
import org.physkit.dynamics.*;
import org.physkit.world.*;
import org.physkit.world.listener.*;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness — listener registration counts (lsn_registered_counts). Isolated, and uses BARE
 * adapter instances (no overridden callbacks) so it depends only on the adapter/interface types
 * existing and the add/get listener API — not on any callback signature. Keeps this registration
 * check alive even if a specific callback signature (which its own driver tests) doesn't match.
 */
public class ListenerRegistryHarness {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }

    static {
        // Listener registration counts across the collision + contact + bounds getters.
        c("lsn_registered_counts", () -> {
            World<Body> w = new World<>();
            w.addCollisionListener(new CollisionListenerAdapter<Body, BodyFixture>() {});
            w.addContactListener(new ContactListenerAdapter<Body>() {});
            w.addBoundsListener(new BoundsListener<Body, BodyFixture>() {
                @Override public void outside(Body b) { }
            });
            return "col=" + w.getCollisionListeners().size()
                 + " con=" + w.getContactListeners().size()
                 + " bnd=" + w.getBoundsListeners().size();
        });
    }

    public static void main(String[] args) throws Exception {
        Runner.run(cases, args);
    }
}
