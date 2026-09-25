import com.lattice.config.*;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness — JSON strict-subset parsing and Java .properties parsing. The config format is a
 * strict superset of JSON (all valid JSON parses identically; the invalid-JSON catalog is rejected),
 * and .properties files map dotted keys to nested objects with numeric keys collapsing to lists.
 *
 * Design: one bundled case per distinct behavior. JSON-mode results are compared against CONF-mode
 * results to prove superset equivalence.
 */
public class JsonPropsHarness {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }

    static String ex(Runnable r) {
        try { r.run(); return "NONE"; }
        catch (Throwable t) { return t.getClass().getSimpleName(); }
    }

    static Config json(String s) {
        return ConfigFactory.parseString(s, ConfigParseOptions.defaults().setSyntax(ConfigSyntax.JSON));
    }

    static Config props(String s) {
        try {
            java.util.Properties p = new java.util.Properties();
            p.load(new java.io.StringReader(s));
            return ConfigFactory.parseProperties(p);
        } catch (java.io.IOException e) { throw new RuntimeException(e); }
    }

    static {
        // ---- Valid JSON parses with correct types and nesting ----
        c("json_valid", () -> {
            Config a = json("{ \"a\" : 1, \"b\" : { \"c\" : [true, false] }, \"s\" : \"hi\" }");
            return "a=" + a.getInt("a") + "|c=" + a.getBooleanList("b.c") + "|s=" + a.getString("s");
        });

        // ---- JSON-mode result equals CONF-mode result for the same valid-JSON input (superset) ----
        c("json_equals_conf", () -> {
            String doc = "{ \"a\" : 1, \"b\" : [1, 2, 3] }";
            Config asJson = json(doc);
            Config asConf = ConfigFactory.parseString(doc);
            return "equal=" + asJson.root().equals(asConf.root())
                 + "|a=" + asJson.getInt("a") + "|blen=" + asJson.getIntList("b").size();
        });

        // ---- JSON mode rejects the extended leniencies: unquoted keys, comments, trailing comma ----
        c("json_rejects_extensions", () -> {
            return "unquotedKey=" + ex(() -> json("{ a : 1 }").root())
                 + "|comment=" + ex(() -> json("{ \"a\" : 1 // c\n}").root())
                 + "|trailingComma=" + ex(() -> json("{ \"a\" : 1, }").root())
                 + "|missingColon=" + ex(() -> json("{ \"a\" 1 }").root());
        });

        // ---- JSON rejects malformed numbers / unterminated strings ----
        c("json_rejects_malformed", () -> {
            return "plusNum=" + ex(() -> json("{ \"a\" : +1 }").root())
                 + "|unterminated=" + ex(() -> json("{ \"a\" : \"oops }").root())
                 + "|emptyArrayComma=" + ex(() -> json("{ \"a\" : [ , ] }").root());
        });

        // ---- .properties dotted keys become nested objects ----
        c("props_nested", () -> {
            Config a = props("a.b.c=42\na.b.d=hello\nx=1");
            return "abc=" + a.getInt("a.b.c") + "|abd=" + a.getString("a.b.d") + "|x=" + a.getInt("x");
        });

        // ---- .properties numeric keys collapse into a list in numeric order ----
        c("props_numeric_list", () -> {
            Config a = props("a.0=zero\na.1=one\na.2=two");
            return "list=" + a.getStringList("a") + "|size=" + a.getStringList("a").size();
        });

        // ---- .properties numeric keys with a gap: present indices are collected in numeric order ----
        c("props_numeric_gaps", () -> {
            Config a = props("a.0=zero\na.1=one\na.3=three");
            return "list=" + a.getStringList("a");
        });

        // ---- .properties: an object-valued key wins over a string at the same prefix ----
        c("props_object_wins", () -> {
            Config a = props("a.b=child\na=parent\nx.y.z=deep");
            return "hasAB=" + a.hasPath("a.b") + "|ab=" + a.getString("a.b") + "|deep=" + a.getString("x.y.z");
        });
    }

    public static void main(String[] args) throws Exception { Runner.run(cases, args); }
}
