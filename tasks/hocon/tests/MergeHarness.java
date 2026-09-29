import com.lattice.config.*;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness — config merging via withFallback: deep object merge, first-wins for scalars, a
 * higher-priority primitive blocking a lower-priority object, lists replacing (never merging), no
 * merge across an intervening array/primitive, and associativity of the merge operation.
 *
 * Design: one bundled case per distinct merge contract. Associativity is asserted by comparing the
 * rendered/queried result of different groupings of the same three-way merge.
 */
public class MergeHarness {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }

    static Config p(String s) { return ConfigFactory.parseString(s); }

    static {
        // ---- Scalar: the higher-priority (left) config wins on a conflicting key ----
        c("scalar_first_wins", () -> {
            Config m = p("a = 1, b = 2").withFallback(p("a = 99, c = 3"));
            return "a=" + m.getInt("a") + "|b=" + m.getInt("b") + "|c=" + m.getInt("c");
        });

        // ---- Nested objects deep-merge; conflicting leaves take the higher-priority value ----
        c("object_deep_merge", () -> {
            Config m = p("srv { host = a, port = 1 }").withFallback(p("srv { port = 99, timeout = 30 }"));
            return "host=" + m.getString("srv.host") + "|port=" + m.getInt("srv.port")
                 + "|timeout=" + m.getInt("srv.timeout")
                 + "|keys=" + new TreeSet<>(m.getObject("srv").keySet());
        });

        // ---- A higher-priority PRIMITIVE blocks a lower-priority OBJECT at the same key ----
        c("primitive_blocks_object", () -> {
            Config m = p("a = 42").withFallback(p("a { x = 1, y = 2 }"));
            return "a=" + m.getInt("a") + "|hasX=" + m.hasPath("a.x");
        });

        // ---- A higher-priority OBJECT is NOT overwritten by a lower-priority primitive ----
        c("object_over_primitive", () -> {
            Config m = p("a { x = 1 }").withFallback(p("a = 42"));
            return "x=" + m.getInt("a.x") + "|isObj=" + (m.getValue("a").valueType() == ConfigValueType.OBJECT);
        });

        // ---- Lists REPLACE, never merge; higher-priority list wins wholesale ----
        c("lists_replace", () -> {
            Config m = p("a = [1, 2]").withFallback(p("a = [3, 4, 5]"));
            return "list=" + m.getIntList("a");
        });

        // ---- An intervening array between two objects blocks the merge of those objects ----
        c("no_merge_across_array", () -> {
            Config m = p("a { c = 4 }").withFallback(p("a = [1, 2]")).withFallback(p("a { b = 1 }"));
            return "hasB=" + m.hasPath("a.b") + "|hasC=" + m.hasPath("a.c")
                 + "|type=" + m.getValue("a").valueType();
        });

        // ---- Associativity: (x wf y) wf z  ==  x wf (y wf z) for objects ----
        c("associative_merge", () -> {
            Config x = p("o { a = 1 }");
            Config y = p("o { a = 2, b = 2 }");
            Config z = p("o { b = 3, c = 3 }");
            Config left = x.withFallback(y).withFallback(z);
            Config right = x.withFallback(y.withFallback(z));
            String ls = "a=" + left.getInt("o.a") + ",b=" + left.getInt("o.b") + ",c=" + left.getInt("o.c");
            String rs = "a=" + right.getInt("o.a") + ",b=" + right.getInt("o.b") + ",c=" + right.getInt("o.c");
            return "left=" + ls + "|right=" + rs + "|equal=" + ls.equals(rs);
        });

        // ---- withFallback of a resolved substitution-bearing pair merges resolved objects ----
        c("merge_then_resolve", () -> {
            Config a = p("base { x = 1 }\nc = ${base}");
            Config b = p("base { y = 2 }\nc = ${base}");
            Config m = a.withFallback(b).resolve();
            return "cx=" + m.getInt("c.x") + "|baseKeys=" + new TreeSet<>(m.getObject("base").keySet());
        });

        // ---- withValue adds/overwrites a path on an immutable copy ----
        c("with_value", () -> {
            Config base = p("a = 1");
            Config m = base.withValue("b.c", ConfigValueFactory.fromAnyRef(2))
                           .withValue("a", ConfigValueFactory.fromAnyRef(99));
            return "a=" + m.getInt("a") + "|bc=" + m.getInt("b.c") + "|baseA=" + base.getInt("a");
        });

        // ---- withOnlyPath keeps a single subtree; withoutPath removes one ----
        c("with_only_and_without", () -> {
            Config base = p("a { x = 1, y = 2 }\nb = 3");
            Config only = base.withOnlyPath("a.x");
            Config without = base.withoutPath("a.x");
            return "onlyHasAX=" + only.hasPath("a.x") + "|onlyHasAY=" + only.hasPath("a.y")
                 + "|onlyHasB=" + only.hasPath("b")
                 + "|withoutHasAX=" + without.hasPath("a.x") + "|withoutHasAY=" + without.hasPath("a.y");
        });

        // ---- atPath / atKey wrap a config beneath a new path or key ----
        c("at_path_and_key", () -> {
            Config wrapped = p("x = 1").atPath("a.b.c");
            Config keyed = p("x = 1").atKey("root");
            return "atPath=" + wrapped.getInt("a.b.c.x") + "|atKey=" + keyed.getInt("root.x");
        });

        // ---- Deep-merge with a substitution-provided object plus an inline override ----
        c("merge_substituted_object_override", () -> {
            Config m = p("base { cluster = 6, region = us }\nprod = ${base} { region = eu }").resolve();
            return "cluster=" + m.getInt("prod.cluster")
                 + "|region=" + m.getString("prod.region");
        });
    }

    public static void main(String[] args) throws Exception { Runner.run(cases, args); }
}
