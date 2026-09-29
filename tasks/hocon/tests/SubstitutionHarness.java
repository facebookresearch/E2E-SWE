import com.lattice.config.*;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness — substitution resolution: `${path}` (required) and `${?path}` (optional),
 * resolution against the FINAL merged value, chains, self-reference look-back through the merge
 * stack, cycle detection, optional-vanish semantics, substitution inside string concatenation, and
 * the resolveWith / isResolved / allowUnresolved contracts.
 *
 * Design: one bundled case per distinct resolution behavior. Cycle/unresolved cases assert both the
 * exception SUBCLASS and a load-bearing message substring ("cycle") where the spec guarantees it.
 */
public class SubstitutionHarness {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }

    static Config resolve(String s) { return ConfigFactory.parseString(s).resolve(); }

    /** class name + whether its message contains a marker word, e.g. "UnresolvedSubstitution/cycle". */
    static String exWith(Runnable r, String marker) {
        try { r.run(); return "NONE"; }
        catch (Throwable t) {
            String m = String.valueOf(t.getMessage());
            return t.getClass().getSimpleName() + "/" + m.toLowerCase(Locale.ROOT).contains(marker);
        }
    }

    static {
        // ---- Basic reference resolves to the referenced value's type/value ----
        c("basic_reference", () -> {
            Config a = resolve("bar { i = 42, b = true, s = hello }\nfoo = ${bar.i}\ng = ${bar.b}\nh = ${bar.s}");
            return "foo=" + a.getInt("foo") + "|g=" + a.getBoolean("g") + "|h=" + a.getString("h");
        });

        // ---- Reference resolves to the FINAL value of the key (later override wins) ----
        c("resolves_to_final_value", () -> {
            Config a = resolve("a = 1\nb = ${a}\na = 2");
            return "b=" + a.getInt("b") + "|a=" + a.getInt("a");
        });

        // ---- Chain of references resolves transitively ----
        c("reference_chain", () -> {
            Config a = resolve("x { y { z = 57 } }\nfoo = ${bar}\nbar = ${x.y.z}");
            return "foo=" + a.getInt("foo") + "|bar=" + a.getInt("bar");
        });

        // ---- Optional missing reference: field vanishes; whole config can become empty ----
        c("optional_vanish", () -> {
            Config a = resolve("a = ${?missing}\nb = ${?also.missing}");
            Config arr = resolve("a = [ ${?missing}, ${?gone} ]");
            return "rootSize=" + a.root().size()
                 + "|arrLen=" + arr.getList("a").size();
        });

        // ---- Substitution inside string concatenation; optional-missing -> empty span ----
        c("substitution_in_concat", () -> {
            Config a = resolve("bar { i = 43 }\nx = start<${bar.i}>end");
            Config o = resolve("y = start<${?missing}>end");
            return "x=" + a.getString("x") + "|y=" + o.getString("y");
        });

        // ---- Required missing reference -> UnresolvedSubstitution, message does NOT say "cycle" ----
        c("required_missing_throws", () -> exWith(() -> resolve("a = ${nonexistent}").root(), "cycle"));

        // ---- Direct self-cycle -> UnresolvedSubstitution whose message mentions "cycle" ----
        c("self_cycle_throws", () -> exWith(() -> resolve("a = ${a}").root(), "cycle"));

        // ---- Two-node cycle -> UnresolvedSubstitution mentioning "cycle" ----
        c("two_node_cycle", () -> exWith(() -> resolve("a = ${b}\nb = ${a}").root(), "cycle"));

        // ---- Self-reference look-back: a = ${a} appended after a prior value uses the PRIOR value ----
        c("self_reference_lookback", () -> {
            Config a = resolve("a = 1\na = ${a}");
            return "a=" + a.getInt("a");
        });

        // ---- Self-reference in string concat accumulates across successive overrides ----
        c("self_reference_concat", () -> {
            Config a = resolve("a = 1\na = ${a}foo");
            Config b = resolve("a = 1\na = ${a}x\na = ${a}y\na = ${a}z");
            return "a=" + a.getString("a") + "|b=" + b.getString("a");
        });

        // ---- Optional self-reference that has no prior value simply vanishes ----
        c("optional_self_reference", () -> {
            Config a = resolve("a = ${?a}");
            Config b = resolve("a = ${?a}foo");
            return "aSize=" + a.root().size() + "|b=" + b.getString("a");
        });

        // ---- An override HIDES an otherwise-undefined or circular reference ----
        c("override_hides_undefined", () -> {
            Config a = resolve("a = ${nonexistent}\na = 42");
            Config b = resolve("a = ${a}\na = 42");
            return "a=" + a.getInt("a") + "|b=" + b.getInt("a");
        });

        // ---- Child-field reference within an object is NOT a self-reference ----
        c("child_field_not_self", () -> {
            Config a = resolve("bar { foo = 42, baz = ${bar.foo} }");
            return "baz=" + a.getInt("bar.baz");
        });

        // ---- resolveWith uses an external source, ignoring this config's own values ----
        c("resolve_with_source", () -> {
            Config unresolved = ConfigFactory.parseString("foo = ${a}\na = 42");
            Config src = ConfigFactory.parseString("a = 43");
            Config r = unresolved.resolveWith(src);
            return "foo=" + r.getInt("foo");
        });

        // ---- isResolved: false with pending substitutions, true after resolve / when none present ----
        c("is_resolved_flag", () -> {
            Config noSubst = ConfigFactory.parseString("a = 1");
            Config withSubst = ConfigFactory.parseString("a = 1\nb = ${a}");
            return "noSubst=" + noSubst.isResolved()
                 + "|beforeResolve=" + withSubst.isResolved()
                 + "|afterResolve=" + withSubst.resolve().isResolved();
        });

        // ---- allowUnresolved leaves unresolved refs in place; getting one throws NotResolved ----
        c("allow_unresolved", () -> {
            Config r = ConfigFactory.parseString("a = ${missing}\nb = 2")
                    .resolve(ConfigResolveOptions.defaults().setAllowUnresolved(true));
            String getB = "b=" + r.getInt("b");
            String getA;
            try { r.getInt("a"); getA = "NONE"; }
            catch (Throwable t) { getA = t.getClass().getSimpleName(); }
            return getB + "|resolved=" + r.isResolved() + "|getA=" + getA;
        });

        // ---- A substitution can resolve to a whole OBJECT; deep access works after resolve ----
        c("substitution_to_object", () -> {
            Config a = resolve("base { x = 1, y = 2 }\nc = ${base}");
            return "cx=" + a.getInt("c.x") + "|cy=" + a.getInt("c.y")
                 + "|keys=" + new TreeSet<>(a.getObject("c").keySet());
        });

        // ---- A substitution can resolve to a whole LIST ----
        c("substitution_to_list", () -> {
            Config a = resolve("xs = [1, 2, 3]\nc = ${xs}");
            return "c=" + a.getIntList("c");
        });

        // ---- A chain where one link is an object, then a field of it is referenced ----
        c("chain_through_object", () -> {
            Config a = resolve("a { b = 10 }\nc = ${a}\nd = ${c.b}");
            return "d=" + a.getInt("d") + "|cb=" + a.getInt("c.b");
        });

        // ---- An optional substitution that DOES resolve overrides normally ----
        c("optional_present", () -> {
            Config a = resolve("x = 5\ny = ${?x}");
            return "y=" + a.getInt("y");
        });

        // ---- Object-concatenation with a leading substitution merges (inheritance shorthand) ----
        c("substitution_object_concat", () -> {
            Config a = resolve("d { cluster = 6 }\ne = ${d} { name = east }");
            return "cluster=" + a.getInt("e.cluster") + "|name=" + a.getString("e.name");
        });
    }

    public static void main(String[] args) throws Exception { Runner.run(cases, args); }
}
