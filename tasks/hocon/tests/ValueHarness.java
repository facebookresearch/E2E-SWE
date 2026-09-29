import com.lattice.config.*;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness — the value model: ConfigValue / ConfigObject / ConfigList equality and
 * immutability, ConfigValueFactory construction from plain Java values, unwrapped() round-trips,
 * cross-type numeric equality, the Config-vs-ConfigObject relationship, and rendering.
 *
 * Design: one bundled case per distinct value-model contract. Immutability is asserted by the
 * exception thrown from a mutator (UnsupportedOperationException).
 */
public class ValueHarness {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }

    static String ex(Runnable r) {
        try { r.run(); return "NONE"; }
        catch (Throwable t) { return t.getClass().getSimpleName(); }
    }

    static {
        // ---- ConfigValueFactory.fromAnyRef wraps plain values with the right ConfigValueType ----
        c("from_any_ref_types", () -> {
            return "bool=" + ConfigValueFactory.fromAnyRef(true).valueType()
                 + "|int=" + ConfigValueFactory.fromAnyRef(42).valueType()
                 + "|dbl=" + ConfigValueFactory.fromAnyRef(3.14).valueType()
                 + "|str=" + ConfigValueFactory.fromAnyRef("hi").valueType()
                 + "|null=" + ConfigValueFactory.fromAnyRef(null).valueType();
        });

        // ---- fromMap builds a ConfigObject; fromIterable builds a ConfigList (keys are literal keys) ----
        c("from_map_and_iterable", () -> {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("a", 1); m.put("b", 2);
            ConfigObject obj = ConfigValueFactory.fromMap(m);
            ConfigList list = ConfigValueFactory.fromIterable(Arrays.asList(1, 2, 3));
            return "objSize=" + obj.size() + "|objType=" + obj.valueType()
                 + "|a=" + obj.toConfig().getInt("a") + "|b=" + obj.toConfig().getInt("b")
                 + "|listSize=" + list.size() + "|listType=" + list.valueType()
                 + "|elems=" + list.unwrapped();
        });

        // ---- unwrapped() round-trips a wrapped value back to a plain Java value ----
        c("unwrapped_round_trip", () -> {
            ConfigValue v = ConfigValueFactory.fromAnyRef(42);
            ConfigObject o = ConfigFactory.parseString("a = 1, b = [2, 3]").root();
            return "scalar=" + v.unwrapped()
                 + "|mapClass=" + (o.unwrapped() instanceof Map)
                 + "|a=" + ((Map<?, ?>) o.unwrapped()).get("a");
        });

        // ---- Cross-type numeric equality: int/long/double of the same value are equal ----
        c("numeric_equality", () -> {
            ConfigValue i = ConfigValueFactory.fromAnyRef(42);
            ConfigValue l = ConfigValueFactory.fromAnyRef(42L);
            ConfigValue d = ConfigValueFactory.fromAnyRef(3.0);
            ConfigValue d3 = ConfigValueFactory.fromAnyRef(3);
            return "intEqLong=" + i.equals(l)
                 + "|dblEqInt=" + d.equals(d3)
                 + "|neq=" + i.equals(ConfigValueFactory.fromAnyRef(43));
        });

        // ---- A ConfigObject is never equal to its own Config view; equal objects -> equal Configs ----
        c("config_vs_object", () -> {
            Config c1 = ConfigFactory.parseString("a = 1");
            Config c2 = ConfigFactory.parseString("a = 1");
            ConfigObject o1 = c1.root();
            return "objEqObj=" + o1.equals(c2.root())
                 + "|cfgEqCfg=" + c1.equals(c2)
                 + "|objNeqCfg=" + o1.equals(c1);
        });

        // ---- ConfigObject implements an unmodifiable java.util.Map; mutators throw ----
        c("object_immutable_map", () -> {
            ConfigObject o = ConfigFactory.parseString("a = 1, b = 2").root();
            return "size=" + o.size() + "|hasKey=" + o.containsKey("a")
                 + "|keys=" + new TreeSet<>(o.keySet())
                 + "|put=" + ex(() -> o.put("c", ConfigValueFactory.fromAnyRef(3)))
                 + "|clear=" + ex(() -> o.clear());
        });

        // ---- ConfigList implements an unmodifiable java.util.List; mutators throw ----
        c("list_immutable", () -> {
            ConfigList l = (ConfigList) ConfigFactory.parseString("a = [10, 20, 30]").getList("a");
            return "size=" + l.size() + "|get1=" + l.get(1).unwrapped()
                 + "|add=" + ex(() -> l.add(ConfigValueFactory.fromAnyRef(40)))
                 + "|set=" + ex(() -> l.set(0, ConfigValueFactory.fromAnyRef(0)));
        });

        // ---- toConfig / root convert between the two views for free ----
        c("to_config_and_root", () -> {
            Config c = ConfigFactory.parseString("a { b = 1 }");
            ConfigObject o = c.root();
            Config back = o.toConfig();
            return "rootB=" + c.getInt("a.b") + "|backB=" + back.getInt("a.b")
                 + "|objGet=" + ((ConfigObject) o.get("a")).toConfig().getInt("b");
        });

        // ---- Numbers render back to their original literal string form via getString ----
        c("number_string_round_trip", () -> {
            Config a = ConfigFactory.parseString("a = 1e6\nb = 0.00005\nc = 132454454354353245");
            return "a=" + a.getString("a") + "|b=" + a.getString("b") + "|c=" + a.getString("c");
        });

        // ---- ConfigMemorySize value semantics: equality and toBytes ----
        c("memory_size_value", () -> {
            ConfigMemorySize a = ConfigMemorySize.ofBytes(1024);
            ConfigMemorySize b = ConfigMemorySize.ofBytes(1024);
            ConfigMemorySize c = ConfigMemorySize.ofBytes(2048);
            return "toBytes=" + a.toBytes() + "|eq=" + a.equals(b) + "|neq=" + a.equals(c);
        });

        // ---- Rendering: numeric keys sort numerically ahead of alphabetic keys (concise) ----
        c("render_key_sorting", () -> {
            Config a = ConfigFactory.parseString("{ \"10\" = a, \"2\" = b, \"1\" = c, z = d }");
            String r = a.root().render(ConfigRenderOptions.concise());
            // Assert relative ordering of keys in the concise render (numeric ascending, then alpha).
            int i1 = r.indexOf("\"1\""), i2 = r.indexOf("\"2\""), i10 = r.indexOf("\"10\""), iz = r.indexOf("\"z\"");
            return "order_1_2=" + (i1 < i2) + "|order_2_10=" + (i2 < i10) + "|order_10_z=" + (i10 < iz);
        });

        // ---- Render -> re-parse round-trip: a rendered config re-parses to an equal object tree ----
        c("render_round_trip", () -> {
            Config orig = ConfigFactory.parseString("a { b = 1, c = [2, 3], d = hello }\nz = true").resolve();
            String rendered = orig.root().render(ConfigRenderOptions.concise());
            Config reparsed = ConfigFactory.parseString(rendered).resolve();
            return "equal=" + orig.root().equals(reparsed.root())
                 + "|b=" + reparsed.getInt("a.b") + "|c=" + reparsed.getIntList("a.c")
                 + "|d=" + reparsed.getString("a.d") + "|z=" + reparsed.getBoolean("z");
        });
    }

    public static void main(String[] args) throws Exception { Runner.run(cases, args); }
}
