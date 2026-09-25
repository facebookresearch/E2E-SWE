import com.lattice.config.*;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness — value concatenation: unquoted tokens on one line concatenate into a string,
 * arrays on one line concatenate element-wise, objects concatenate (merge), the `+=` array-append
 * shorthand, and the error contract when concatenating incompatible types ("Cannot concatenate").
 *
 * Design: one bundled case per distinct concatenation rule. Error cases assert the exception
 * SUBCLASS plus whether the message carries the documented "Cannot concatenate" marker.
 */
public class ConcatHarness {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }

    static Config resolve(String s) { return ConfigFactory.parseString(s).resolve(); }

    static String exWith(Runnable r, String marker) {
        try { r.run(); return "NONE"; }
        catch (Throwable t) {
            String m = String.valueOf(t.getMessage());
            return t.getClass().getSimpleName() + "/" + m.contains(marker);
        }
    }

    static {
        // ---- Unquoted tokens of mixed kinds on one line join with single spaces ----
        c("string_concat_tokens", () -> {
            Config a = resolve("a = true \"xyz\" 123 foo");
            return "a=" + a.getString("a");
        });

        // ---- Substitution concatenated into an unquoted string ----
        c("string_concat_substitution", () -> {
            Config a = resolve("x = 1\na = ${x}foo");
            Config b = resolve("x = 1\nb = ${x}foo${x}");
            return "a=" + a.getString("a") + "|b=" + b.getString("b");
        });

        // ---- Two arrays on one line concatenate element-wise ----
        c("array_concat", () -> {
            Config a = resolve("a = [1, 2] [3, 4]");
            return "a=" + a.getIntList("a");
        });

        // ---- Array concatenation with substitution and self-reference accumulation ----
        c("array_concat_self", () -> {
            Config a = resolve("a = [1, 2]\na = ${a} [3, 4]\na = ${a} [5, 6]");
            return "a=" + a.getIntList("a");
        });

        // ---- Two objects on one line concatenate (merge, last field wins) ----
        c("object_concat", () -> {
            Config a = resolve("a = { b = c } { x = y }");
            Config m = resolve("a = { b = 1 } { b = 2 } { b = 3 } { b = 4 }");
            return "keys=" + new TreeSet<>(a.getObject("a").keySet())
                 + "|b=" + a.getString("a.b") + "|x=" + a.getString("a.x")
                 + "|merged=" + m.getInt("a.b");
        });

        // ---- Whitespace-separated tokens inside [] with no comma/newline concatenate to one string ----
        c("array_element_concat", () -> {
            Config a = resolve("a = [ 1 2 3 ]");        // one element "1 2 3"
            Config b = resolve("a = [ foo bar 10 ]");   // one element "foo bar 10"
            return "aLen=" + a.getStringList("a").size() + "|a0=" + a.getStringList("a").get(0)
                 + "|bLen=" + b.getStringList("a").size() + "|b0=" + b.getStringList("a").get(0);
        });

        // ---- Newline-separated tokens inside [] are distinct elements (no concatenation) ----
        c("array_newline_elements", () -> {
            Config a = resolve("a = [\n foo\n bar\n 10\n ]");
            return "len=" + a.getStringList("a").size() + "|list=" + a.getStringList("a");
        });

        // ---- `+=` appends to an existing array; to a missing path it creates a singleton ----
        c("plus_equals", () -> {
            Config a = resolve("a = [1]\na += 2\na += 3");
            Config b = resolve("b += 2");
            return "a=" + a.getIntList("a") + "|b=" + b.getIntList("b");
        });

        // ---- Optional-substitution concatenation: undefined vanishes, defined appends ----
        c("optional_concat", () -> {
            Config undef = resolve("a = foo${?bar}");
            Config def = resolve("bar = X\na = foo${?bar}");
            Config arrUndef = resolve("a = [1] ${?bar}");
            Config arrDef = resolve("bar = [2]\na = [1] ${?bar}");
            return "undef=" + undef.getString("a") + "|def=" + def.getString("a")
                 + "|arrUndef=" + arrUndef.getIntList("a") + "|arrDef=" + arrDef.getIntList("a");
        });

        // ---- Concatenating an object/array/null INTO a string is a WrongType "Cannot concatenate" ----
        c("concat_type_errors", () -> {
            return "obj=" + exWith(() -> resolve("a = foo { x = 1 }").getString("a"), "Cannot concatenate")
                 + "|arr=" + exWith(() -> resolve("a = foo [1, 2]").getString("a"), "Cannot concatenate");
        });

        // ---- `+=` onto a non-array value is a WrongType "Cannot concatenate" ----
        c("plus_equals_type_error", () ->
            exWith(() -> resolve("a = 5\na += 2").getList("a"), "Cannot concatenate"));

        // ---- A concatenation cannot span a newline: parse fails ----
        c("concat_no_span_newline", () -> {
            try { resolve("x = 1\na = ${x}\nfoo").root(); return "NONE"; }
            catch (Throwable t) { return t.getClass().getSimpleName(); }
        });

        // ---- Number followed by an unquoted word concatenates to a string ----
        c("number_word_concat", () -> {
            Config a = resolve("v = 42 foo");
            return "v=" + a.getString("v");
        });

        // ---- += onto an optional-missing base creates the array from scratch ----
        c("plus_equals_from_missing", () -> {
            Config a = resolve("q = ${?nope}\nq += 1\nq += 2");
            return "q=" + a.getIntList("q");
        });
    }

    public static void main(String[] args) throws Exception { Runner.run(cases, args); }
}
