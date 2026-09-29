import com.lattice.config.*;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness — parsing of the human-friendly config format (the JSON superset). Exercises the
 * lenient syntax a real user relies on: dropped root braces, `=`/`:` separators, omitted commas,
 * dotted keys, unquoted strings, duplicate-key merge + null/non-object reset, trailing commas,
 * comments, quoted specials, triple-quoted strings, and numeric-key path splitting.
 *
 * Design: ONE bundled, multi-assertion case per distinct parsing behavior. Each case parses one
 * realistic document via ConfigFactory.parseString(...) and joins the observable results with '|'
 * so a single CTRF entry rewards one parsing contract. Error cases assert the exception SUBCLASS
 * (Parse / BadPath) — the load-bearing observable contract — via ex().
 */
public class ParseHarness {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }

    /** Simple class name of the exception thrown, or "NONE" if no throw. Uses nested class simple names. */
    static String ex(Runnable r) {
        try { r.run(); return "NONE"; }
        catch (Throwable t) { return t.getClass().getSimpleName(); }
    }

    static Config parse(String s) { return ConfigFactory.parseString(s); }

    static {
        // ---- Dropped root braces + `=`/`:` mix + omitted `=` before `{` ----
        c("syntax_lenient_forms", () -> {
            Config a = parse("foo { bar = 10, baz : 12 }");
            Config b = parse("foo.bar=10\nfoo.baz=12");   // dotted, newline-separated, no commas
            return "bar=" + a.getInt("foo.bar")
                 + "|baz=" + a.getInt("foo.baz")
                 + "|dotBar=" + b.getInt("foo.bar")
                 + "|dotBaz=" + b.getInt("foo.baz");
        });

        // ---- Omitted commas across newlines vs single-line comma-separated dotted keys ----
        c("syntax_comma_optional", () -> {
            Config a = parse("a = y\nb = z\nc = [1, 2, 3]");
            Config b = parse("foo.bar=10, foo.baz=12");
            return "a=" + a.getString("a") + "|b=" + a.getString("b")
                 + "|clen=" + a.getIntList("c").size() + "|c1=" + a.getIntList("c").get(1)
                 + "|bar=" + b.getInt("foo.bar") + "|baz=" + b.getInt("foo.baz");
        });

        // ---- Trailing commas allowed after last element in objects and arrays ----
        c("syntax_trailing_commas", () -> {
            Config a = parse("{ a : 1, b : 2, }");
            Config l = parse("x = [1, 2, 3, ]");
            return "a=" + a.getInt("a") + "|b=" + a.getInt("b")
                 + "|len=" + l.getIntList("x").size() + "|last=" + l.getIntList("x").get(2);
        });

        // ---- Duplicate scalar key: last wins; root size collapses to 1 ----
        c("dup_key_last_wins", () -> {
            Config a = parse("{ \"a\" : 10, \"a\" : 11 }");
            return "a=" + a.getInt("a") + "|rootSize=" + a.root().size();
        });

        // ---- Duplicate object key: deep recursive merge (later fields win, earlier retained) ----
        c("dup_key_object_merge", () -> {
            Config a = parse("a { x : 1, y : 2 }\na { x : 42, z : 100 }");
            return "keys=" + new TreeSet<>(a.getObject("a").keySet())
                 + "|x=" + a.getInt("a.x") + "|y=" + a.getInt("a.y") + "|z=" + a.getInt("a.z");
        });

        // ---- Null / non-object value RESETS a prior object before a later object merges ----
        c("dup_key_null_reset", () -> {
            Config viaNull = parse("a { b : 1 }\na : null\na { c : 2 }");
            Config viaNum  = parse("a { b : 1 }\na : 42\na { c : 2 }");
            return "nullHasB=" + viaNull.hasPath("a.b") + "|nullC=" + viaNull.getInt("a.c")
                 + "|numHasB=" + viaNum.hasPath("a.b") + "|numC=" + viaNum.getInt("a.c");
        });

        // ---- Comments (`#` and `//`) are ignored; do not affect values ----
        c("comments_ignored", () -> {
            Config a = parse("# leading comment\n"
                           + "a = 1 // trailing comment\n"
                           + "b = 2 # another\n"
                           + "// full line\n"
                           + "c = 3");
            return "a=" + a.getInt("a") + "|b=" + a.getInt("b") + "|c=" + a.getInt("c")
                 + "|size=" + a.root().size();
        });

        // ---- Unquoted string value tokens join into one string; quoted keeps exact text ----
        c("unquoted_strings", () -> {
            Config a = parse("path = /usr/local/bin\nname = hello world things");
            return "path=" + a.getString("path") + "|name=" + a.getString("name");
        });

        // ---- Keys containing slashes are ordinary unquoted keys ----
        c("slash_keys", () -> {
            Config a = parse("/a/b/c = 42\nx/y/z : 32");
            return "abc=" + a.getInt("/a/b/c") + "|xyz=" + a.getInt("x/y/z");
        });

        // ---- Numeric-looking dotted keys split on '.' into nested objects ----
        c("numeric_dotted_paths", () -> {
            Config a = parse("0.1.2.3 = foobar1\n10.0 = foobar2");
            return "deep=" + a.getString("0.1.2.3")
                 + "|split100=" + a.getConfig("10").getString("0");
        });

        // ---- Quoted key with special chars stays a single key; dotted quoted stays one element ----
        c("quoted_special_keys", () -> {
            Config a = parse("\"a.b\" : 5\nfoo.\"bar.baz\".q : 7");
            return "ab=" + a.getInt("\"a.b\"")
                 + "|nested=" + a.getConfig("foo").getConfig("\"bar.baz\"").getInt("q");
        });

        // ---- Deeply nested quoted key holding an object; access via a joined path ----
        c("nested_quoted_object_key", () -> {
            Config a = parse("a { \"x.y\" { z = 9 } }");
            return "viaGet=" + a.getInt("a.\"x.y\".z")
                 + "|objHasKey=" + a.getConfig("a").root().containsKey("x.y")
                 + "|joined=" + ConfigUtil.joinPath("a", "x.y", "z");
        });

        // ---- Mixed dotted + quoted-dotted key on one line splits correctly ----
        c("mixed_dotted_quoted", () -> {
            Config a = parse("outer.\"in.ner\".leaf = 42");
            return "leaf=" + a.getConfig("outer").getConfig("\"in.ner\"").getInt("leaf")
                 + "|outerKeys=" + new TreeSet<>(a.getObject("outer").keySet());
        });

        // ---- Triple-quoted multi-line string preserves inner newlines verbatim ----
        c("triple_quoted_string", () -> {
            Config a = parse("a = \"\"\"line1\nline2\nline3\"\"\"");
            String v = a.getString("a");
            return "value=" + v.replace("\n", "\\n") + "|lines=" + (v.split("\n", -1).length);
        });

        // ---- Quoted string escapes: \n \t \" \\ decoded on parse ----
        c("quoted_escapes", () -> {
            Config a = parse("a = \"x\\ny\\tz\\\"q\\\\r\"");
            String v = a.getString("a");
            return "hasNL=" + v.contains("\n") + "|hasTab=" + v.contains("\t")
                 + "|hasQuote=" + v.contains("\"") + "|hasBackslash=" + v.contains("\\")
                 + "|len=" + v.length();
        });

        // ---- Missing separator between two key-values is a Parse error ----
        c("err_missing_separator", () -> ex(() -> parse("{ a : y b : z }").root()));

        // ---- Unclosed brace is a Parse error ----
        c("err_unclosed_brace", () -> ex(() -> parse("a { b : 1 ").root()));

        // ---- Bare '}' with no value is a Parse error ----
        c("err_bad_token", () -> ex(() -> parse("a = }").root()));
    }

    public static void main(String[] args) throws Exception { Runner.run(cases, args); }
}
