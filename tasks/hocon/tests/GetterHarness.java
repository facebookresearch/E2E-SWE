import com.lattice.config.*;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness — the typed getter contract on a resolved config: type coercion (string<->number,
 * string->boolean), typed list getters, null-vs-missing handling (hasPath / hasPathOrNull /
 * getIsNull), empty-array-as-any-typed-list, and the exact exception SUBCLASS thrown for each
 * failure mode (Missing / Null / WrongType / BadPath).
 *
 * Design: one bundled case per distinct getter behavior; exception cases assert the nested exception
 * class simple name (the observable, documented contract). Doubles are formatted via f() to 6dp so a
 * correct reimplementation isn't punished for float formatting noise.
 */
public class GetterHarness {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }

    static String f(double v) {
        double r = Math.round(v * 1e6) / 1e6;
        if (r == 0.0) r = 0.0;
        return String.format(Locale.ROOT, "%.6f", r);
    }

    static String ex(Runnable r) {
        try { r.run(); return "NONE"; }
        catch (Throwable t) { return t.getClass().getSimpleName(); }
    }

    static Config parse(String s) { return ConfigFactory.parseString(s); }

    static {
        // ---- Primitive getters: int / long / double / boolean / string at exact values ----
        c("primitive_getters", () -> {
            Config a = parse("i = 42\nl = 42\nd = 3.14\nb = true\ns = hello");
            return "int=" + a.getInt("i") + "|long=" + a.getLong("l")
                 + "|double=" + f(a.getDouble("d")) + "|bool=" + a.getBoolean("b")
                 + "|str=" + a.getString("s")
                 + "|num=" + a.getNumber("i").intValue();
        });

        // ---- getInt truncates a floating value toward zero (narrowing conversion) ----
        c("int_truncates_double", () -> {
            Config a = parse("x = 3.99\ny = -3.99");
            return "x=" + a.getInt("x") + "|y=" + a.getInt("y")
                 + "|xl=" + a.getLong("x");
        });

        // ---- Number -> string coercion (a numeric value read as a string) ----
        c("number_to_string", () -> {
            Config a = parse("x = 42\ny = 3.14");
            return "x=" + a.getString("x") + "|y=" + a.getString("y");
        });

        // ---- String -> number coercion (a quoted numeric string read as int/double) ----
        c("string_to_number", () -> {
            Config a = parse("x = \"57\"\ny = \"3.5\"");
            return "x=" + a.getInt("x") + "|y=" + f(a.getDouble("y"));
        });

        // ---- String -> boolean coercion: true/yes/on -> true; false/no/off -> false ----
        c("string_to_boolean", () -> {
            Config a = parse("t1=true\nt2=yes\nt3=on\nf1=false\nf2=no\nf3=off");
            return "t1=" + a.getBoolean("t1") + "|t2=" + a.getBoolean("t2") + "|t3=" + a.getBoolean("t3")
                 + "|f1=" + a.getBoolean("f1") + "|f2=" + a.getBoolean("f2") + "|f3=" + a.getBoolean("f3");
        });

        // ---- Typed list getters: int / long / number / string / double / boolean / anyRef lists ----
        c("typed_lists", () -> {
            Config a = parse("ints=[1,2,3]\nstrs=[a,b,c]\ndbls=[1.5,2.5]\nbools=[true,false,true]");
            return "ints=" + a.getIntList("ints")
                 + "|longs=" + a.getLongList("ints")
                 + "|nums=" + a.getNumberList("ints")
                 + "|strs=" + a.getStringList("strs")
                 + "|dbls=" + a.getDoubleList("dbls")
                 + "|bools=" + a.getBooleanList("bools")
                 + "|anyRef=" + a.getAnyRefList("ints");
        });

        // ---- Empty array is a valid value for any typed list getter ----
        c("empty_array_any_list", () -> {
            Config a = parse("e = []");
            return "ints=" + a.getIntList("e").size()
                 + "|strs=" + a.getStringList("e").size()
                 + "|bools=" + a.getBooleanList("e").size()
                 + "|objs=" + a.getObjectList("e").size();
        });

        // ---- getConfig / getObject navigate nested subtrees; getConfigList reads a list of objects ----
        c("nested_config_object", () -> {
            Config a = parse("srv { host = localhost, port = 8080, opts { debug = true } }\n"
                           + "peers = [ { id = 1 }, { id = 2 }, { id = 3 } ]");
            Config srv = a.getConfig("srv");
            java.util.List<? extends Config> peers = a.getConfigList("peers");
            return "host=" + srv.getString("host") + "|port=" + srv.getInt("port")
                 + "|debug=" + a.getBoolean("srv.opts.debug")
                 + "|objKeys=" + new TreeSet<>(a.getObject("srv").keySet())
                 + "|peerCount=" + peers.size() + "|peer1Id=" + peers.get(1).getInt("id");
        });

        // ---- hasPath / hasPathOrNull / getIsNull distinguish unset vs null vs present ----
        c("has_path_null_semantics", () -> {
            Config a = parse("present = 1\nnullv = null");
            return "presHas=" + a.hasPath("present")
                 + "|nullHas=" + a.hasPath("nullv")            // false: null treated as missing by hasPath
                 + "|nullHasOrNull=" + a.hasPathOrNull("nullv") // true
                 + "|nullIsNull=" + a.getIsNull("nullv")        // true
                 + "|absentHas=" + a.hasPath("absent")
                 + "|absentHasOrNull=" + a.hasPathOrNull("absent");
        });

        // ---- entrySet flattens to leaf path->value pairs, skipping nulls ----
        c("entryset_flattens", () -> {
            Config a = parse("a { b = 1, c = 2 }\nd = 3\ne = null");
            TreeSet<String> paths = new TreeSet<>();
            for (Map.Entry<String, ConfigValue> en : a.entrySet()) paths.add(en.getKey());
            return "size=" + a.entrySet().size() + "|paths=" + paths;
        });

        // ---- isEmpty on an empty vs non-empty config ----
        c("is_empty", () -> {
            return "empty=" + ConfigFactory.empty().isEmpty()
                 + "|nonEmpty=" + parse("a = 1").isEmpty();
        });

        // ---- Exceptions: missing -> Missing; null -> Null; wrong type -> WrongType; bad path -> BadPath ----
        c("getter_exception_types", () -> {
            Config a = parse("num = 42\nnullv = null\nstr = notanumber\nobj { x = 1 }");
            return "missing=" + ex(() -> a.getInt("nope"))
                 + "|null=" + ex(() -> a.getInt("nullv"))
                 + "|wrongType=" + ex(() -> a.getInt("str"))
                 + "|objAsInt=" + ex(() -> a.getInt("obj"))
                 + "|badPath=" + ex(() -> a.getInt("a."));
        });

        // ---- getInt out of 32-bit range -> WrongType (not silent truncation) ----
        c("int_range_check", () -> {
            Config a = parse("big = 9999999999");   // > Integer.MAX_VALUE
            return "asLong=" + a.getLong("big") + "|intThrows=" + ex(() -> a.getInt("big"));
        });

        // ---- getAnyRef unwraps to plain Java values; getValue exposes ConfigValueType ----
        c("anyref_and_valuetype", () -> {
            Config a = parse("i = 42\ns = hi\nb = true\nlist = [1,2]");
            return "iType=" + a.getValue("i").valueType()
                 + "|sType=" + a.getValue("s").valueType()
                 + "|bType=" + a.getValue("b").valueType()
                 + "|listType=" + a.getValue("list").valueType()
                 + "|anyI=" + a.getAnyRef("i") + "|anyB=" + a.getAnyRef("b");
        });
    }

    public static void main(String[] args) throws Exception { Runner.run(cases, args); }
}
