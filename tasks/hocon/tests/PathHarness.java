import com.lattice.config.*;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness — path-expression utilities (ConfigUtil.joinPath / splitPath / quoteString) and
 * the quoting rules for keys with special characters. joinPath quotes elements needing it and
 * splitPath is its inverse; quoteString renders a JSON string literal. Invalid path expressions
 * raise ConfigException.
 *
 * Design: one bundled case per distinct rule, asserting exact rendered/parsed forms and round-trips.
 */
public class PathHarness {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }

    static String ex(Runnable r) {
        try { r.run(); return "NONE"; }
        catch (Throwable t) { return t.getClass().getSimpleName(); }
    }

    /**
     * Category of a thrown exception: "ConfigException" for ANY ConfigException (regardless of the
     * concrete subclass), the specific simple name otherwise, or "NONE". Used where the spec only
     * guarantees that a ConfigException is thrown but not which subclass.
     */
    static String exBase(Runnable r) {
        try { r.run(); return "NONE"; }
        catch (ConfigException ce) { return "ConfigException"; }
        catch (Throwable t) { return t.getClass().getSimpleName(); }
    }

    static {
        // ---- joinPath quotes elements that need it (empty, special char), leaves simple ones bare ----
        c("join_path", () -> {
            return "simple=" + ConfigUtil.joinPath("a", "b", "c")
                 + "|special=" + ConfigUtil.joinPath("", "a", "b", "$");
        });

        // ---- splitPath is the inverse of joinPath, recovering the exact element list ----
        c("split_path", () -> {
            List<String> simple = ConfigUtil.splitPath("a.b.c");
            List<String> special = ConfigUtil.splitPath("\"\".a.b.\"$\"");
            return "simple=" + simple + "|special=" + special;
        });

        // ---- Round-trip: splitPath(joinPath(elems)) == elems for tricky elements ----
        c("path_round_trip", () -> {
            List<String> elems = Arrays.asList("a b", "c.d", "", "normal");
            String joined = ConfigUtil.joinPath(elems);
            List<String> back = ConfigUtil.splitPath(joined);
            return "back=" + back + "|equal=" + back.equals(elems);
        });

        // ---- A quoted dotted element is ONE path element; unquoted numeric splits on '.' ----
        c("quoting_vs_splitting", () -> {
            return "quotedDot=" + ConfigUtil.splitPath("a.\"b.c\".d")
                 + "|numeric=" + ConfigUtil.splitPath("1.2.3");
        });

        // ---- quoteString renders a JSON string literal, escaping control chars ----
        c("quote_string", () -> {
            return "empty=" + ConfigUtil.quoteString("")
                 + "|plain=" + ConfigUtil.quoteString("a")
                 + "|newline=" + ConfigUtil.quoteString("\n")
                 + "|tab=" + ConfigUtil.quoteString("\t");
        });

        // ---- Invalid path expressions raise ConfigException. The splitPath cases raise BadPath
        //      specifically (documented); joining zero elements raises a ConfigException but the
        //      spec does not pin the subclass, so only require that it is a ConfigException. ----
        c("invalid_paths_throw", () -> {
            return "empty=" + ex(() -> ConfigUtil.splitPath(""))
                 + "|trailingDot=" + ex(() -> ConfigUtil.splitPath("a."))
                 + "|leadingDot=" + ex(() -> ConfigUtil.splitPath(".b"))
                 + "|doubleDot=" + ex(() -> ConfigUtil.splitPath("a..b"))
                 + "|joinEmpty=" + exBase(() -> ConfigUtil.joinPath());
        });

        // ---- Path expressions used as getter paths: quoted element with a dot ----
        c("path_in_getter", () -> {
            Config a = ConfigFactory.parseString("foo { \"a.b\" = 42 }");
            String joined = ConfigUtil.joinPath("foo", "a.b");
            return "joined=" + joined + "|value=" + a.getInt(joined);
        });
    }

    public static void main(String[] args) throws Exception { Runner.run(cases, args); }
}
