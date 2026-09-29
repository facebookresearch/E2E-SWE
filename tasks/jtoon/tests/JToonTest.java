package wrg.hidden;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertInstanceOf;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.fasterxml.jackson.annotation.JsonIgnore;
import dev.toonformat.jtoon.DecodeOptions;
import dev.toonformat.jtoon.Delimiter;
import dev.toonformat.jtoon.EncodeOptions;
import dev.toonformat.jtoon.JToon;
import dev.toonformat.jtoon.KeyFolding;
import dev.toonformat.jtoon.PathExpansion;
import java.math.BigDecimal;
import java.math.BigInteger;
import java.time.Instant;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.time.ZonedDateTime;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.stream.Stream;
import org.junit.jupiter.api.Test;

/**
 * End-to-end contract tests for the JToon TOON encoder/decoder facade. Each test drives a
 * realistic workflow through the public {@code JToon} facade and asserts many exact-value
 * contracts as a unit, so a single behavioral regression fails the whole scenario. Tests that
 * reward the same underlying engine (scalar/string quoting, object+key rendering, the array
 * dispatcher, type normalization, structural decoding, ...) are bundled together; genuinely
 * distinct algorithms (key folding, string unescaping, strict/lenient mode, security limits,
 * option validation, decodeToJson/round-trip) stay separate.
 */
class JToonTest {

    // ---- helpers ---------------------------------------------------------

    private static Map<String, Object> map(final Object... kv) {
        final LinkedHashMap<String, Object> m = new LinkedHashMap<>();
        for (int i = 0; i < kv.length; i += 2) {
            m.put((String) kv[i], kv[i + 1]);
        }
        return m;
    }

    private static List<Object> list(final Object... items) {
        return new ArrayList<>(Arrays.asList(items));
    }

    // ===================================================================
    // ENCODING
    // ===================================================================

    /** Scalar root values + the string quoting/escaping engine (unquoted-safe vs quoted-ambiguous). */
    @Test
    void encodesScalarsAndStringQuoting() {
        // -- root scalar rendering --
        assertEquals("42", JToon.encode(42));
        assertEquals("3.14", JToon.encode(3.14));
        assertEquals("-7", JToon.encode(-7));
        assertEquals("0", JToon.encode(0));
        assertEquals("0", JToon.encode(-0.0));
        assertEquals("1000000", JToon.encode(1000000));
        assertEquals("0.000001", JToon.encode(0.000001));
        assertEquals("9007199254740991", JToon.encode(9007199254740991L));
        assertEquals("true", JToon.encode(true));
        assertEquals("false", JToon.encode(false));
        assertEquals("null", JToon.encode(null));
        // Safe unquoted strings, including Unicode passthrough.
        assertEquals("hello", JToon.encode("hello"));
        assertEquals("Ada_99", JToon.encode("Ada_99"));
        assertEquals("café", JToon.encode("café"));
        assertEquals("你好", JToon.encode("你好"));
        assertEquals("🚀", JToon.encode("🚀"));
        assertEquals("hello 👋 world", JToon.encode("hello 👋 world"));

        // -- ambiguous string quoting/escaping --
        // Empty and keyword-like strings are quoted so they never read back as a non-string.
        assertEquals("\"\"", JToon.encode(""));
        assertEquals("\"true\"", JToon.encode("true"));
        assertEquals("\"false\"", JToon.encode("false"));
        assertEquals("\"null\"", JToon.encode("null"));
        // Numeric-like strings are quoted.
        assertEquals("\"42\"", JToon.encode("42"));
        assertEquals("\"-3.14\"", JToon.encode("-3.14"));
        assertEquals("\"1e-6\"", JToon.encode("1e-6"));
        assertEquals("\"05\"", JToon.encode("05"));
        // Escaping of control characters within quotes.
        assertEquals("\"line1\\nline2\"", JToon.encode("line1\nline2"));
        assertEquals("\"tab\\there\"", JToon.encode("tab\there"));
        assertEquals("\"return\\rcarriage\"", JToon.encode("return\rcarriage"));
        assertEquals("\"C:\\\\Users\\\\path\"", JToon.encode("C:\\Users\\path"));
        // Other control chars -> \\uXXXX (lowercase hex), observed as an object value.
        assertEquals("val: \"a\\u0004b\"", JToon.encode(map("val", "ab")));
        // Structural / list-marker-like strings are quoted.
        assertEquals("\"[3]: x,y\"", JToon.encode("[3]: x,y"));
        assertEquals("\"[test]\"", JToon.encode("[test]"));
        assertEquals("\"{key}\"", JToon.encode("{key}"));
        assertEquals("\"- item\"", JToon.encode("- item"));
        assertEquals("marker: \"-\"", JToon.encode(map("marker", "-")));
    }

    /** Object rendering (order, nulls, nesting, value quoting) + object-key quoting/escaping. */
    @Test
    void encodesObjectsAndKeyQuoting() {
        // -- object body: order, nulls, nesting, value quoting --
        assertEquals("id: 123\nname: Ada\nactive: true",
                JToon.encode(map("id", 123, "name", "Ada", "active", true)));
        assertEquals("id: 123\nvalue: null", JToon.encode(map("id", 123, "value", null)));
        // Empty object is the empty string; empty nested object is a bare "key:".
        assertEquals("", JToon.encode(map()));
        assertEquals("user:", JToon.encode(map("user", map())));
        assertEquals("a:\n  b:\n    c: deep",
                JToon.encode(map("a", map("b", map("c", "deep")))));
        // Object string values quote on colon/comma/leading-space; dots are fine unquoted keys.
        assertEquals("note: \"a:b\"", JToon.encode(map("note", "a:b")));
        assertEquals("note: \"a,b\"", JToon.encode(map("note", "a,b")));
        assertEquals("text: \" padded \"", JToon.encode(map("text", " padded ")));
        assertEquals("user.name: Ada", JToon.encode(map("user.name", "Ada")));

        // -- object key quoting/escaping --
        assertEquals("\"order:id\": 7", JToon.encode(map("order:id", 7)));
        assertEquals("\"[index]\": 5", JToon.encode(map("[index]", 5)));
        assertEquals("\"{key}\": 5", JToon.encode(map("{key}", 5)));
        assertEquals("\"a,b\": 1", JToon.encode(map("a,b", 1)));
        assertEquals("\"full name\": Ada", JToon.encode(map("full name", "Ada")));
        assertEquals("\"-lead\": 1", JToon.encode(map("-lead", 1)));
        assertEquals("\" a \": 1", JToon.encode(map(" a ", 1)));
        assertEquals("\"123\": x", JToon.encode(map("123", "x")));
        assertEquals("\"\": 1", JToon.encode(map("", 1)));
        assertEquals("\"line\\nbreak\": 1", JToon.encode(map("line\nbreak", 1)));
        assertEquals("\"he said \\\"hi\\\"\": 1", JToon.encode(map("he said \"hi\"", 1)));
        assertEquals("\"a\\u0004b\": 1", JToon.encode(map("ab", 1)));
    }

    /** The array dispatcher: inline primitive arrays + nested / mixed / root-level array shapes. */
    @Test
    void encodesInlineAndStructuralArrays() {
        // -- inline primitive arrays (incl. per-element quoting, empties, blanks) --
        assertEquals("tags[2]: reading,gaming", JToon.encode(map("tags", list("reading", "gaming"))));
        assertEquals("nums[3]: 1,2,3", JToon.encode(map("nums", list(1, 2, 3))));
        assertEquals("data[4]: x,y,true,10", JToon.encode(map("data", list("x", "y", true, 10))));
        assertEquals("items: []", JToon.encode(map("items", list())));
        assertEquals("\"\"[3]: 1,2,3", JToon.encode(map("", list(1, 2, 3))));
        assertEquals("\"\": []", JToon.encode(map("", list())));
        assertEquals("items[1]: \"\"", JToon.encode(map("items", list(""))));
        assertEquals("items[3]: a,\"\",b", JToon.encode(map("items", list("a", "", "b"))));
        assertEquals("items[2]: \" \",\"  \"", JToon.encode(map("items", list(" ", "  "))));
        assertEquals("items[3]: a,\"b,c\",\"d:e\"",
                JToon.encode(map("items", list("a", "b,c", "d:e"))));
        assertEquals("items[4]: x,\"true\",\"42\",\"-3.14\"",
                JToon.encode(map("items", list("x", "true", "42", "-3.14"))));
        assertEquals("items[3]: \"[5]\",\"- item\",\"{key}\"",
                JToon.encode(map("items", list("[5]", "- item", "{key}"))));

        // -- nested / mixed / root-level array shapes --
        assertEquals("pairs[2]:\n  - [2]: a,b\n  - [2]: c,d",
                JToon.encode(map("pairs", list(list("a", "b"), list("c", "d")))));
        assertEquals("pairs[2]:\n  - [2]: a,b\n  - [3]: \"c,d\",\"e:f\",\"true\"",
                JToon.encode(map("pairs", list(list("a", "b"), list("c,d", "e:f", "true")))));
        assertEquals("pairs[2]:\n  - [0]:\n  - [0]:",
                JToon.encode(map("pairs", list(list(), list()))));
        assertEquals("pairs[2]:\n  - [1]: 1\n  - [2]: 2,3",
                JToon.encode(map("pairs", list(list(1), list(2, 3)))));
        // Root-level arrays.
        assertEquals("[5]: x,y,\"true\",true,10",
                JToon.encode(list("x", "y", "true", true, 10)));
        assertEquals("[2]{id}:\n  1\n  2", JToon.encode(list(map("id", 1), map("id", 2))));
        assertEquals("[2]:\n  - id: 1\n  - id: 2\n    name: Ada",
                JToon.encode(list(map("id", 1), map("id", 2, "name", "Ada"))));
        assertEquals("[3]:\n  - summary\n  - id: 1\n    name: Ada\n  - [2]:\n    - id: 2\n    - status: draft",
                JToon.encode(list("summary", map("id", 1, "name", "Ada"),
                        list(map("id", 2), map("status", "draft")))));
        assertEquals("[2]:\n  - [2]: 1,2\n  - [0]:", JToon.encode(list(list(1, 2), list())));
        assertEquals("[]", JToon.encode(list()));
        // Mixed primitives/objects inside a keyed array use list form.
        assertEquals("items[3]:\n  - 1\n  - a: 1\n  - text",
                JToon.encode(map("items", list(1, map("a", 1), "text"))));
    }

    /** Tabular-array path + its fallback: complex nested objects and list-item objects. */
    @Test
    void encodesTabularAndListItemObjects() {
        // -- tabular arrays (uniform scalar-valued objects) --
        assertEquals("items[2]{sku,qty,price}:\n  A1,2,9.99\n  B2,1,14.5",
                JToon.encode(map("items", list(
                        map("sku", "A1", "qty", 2, "price", 9.99),
                        map("sku", "B2", "qty", 1, "price", 14.5)))));
        assertEquals("items[2]{id,value}:\n  1,null\n  2,test",
                JToon.encode(map("items", list(
                        map("id", 1, "value", null),
                        map("id", 2, "value", "test")))));
        assertEquals("items[2]{sku,desc,qty}:\n  \"A,1\",cool,2\n  B2,\"wip: test\",1",
                JToon.encode(map("items", list(
                        map("sku", "A,1", "desc", "cool", "qty", 2),
                        map("sku", "B2", "desc", "wip: test", "qty", 1)))));
        assertEquals("items[2]{id,status}:\n  1,\"true\"\n  2,\"false\"",
                JToon.encode(map("items", list(
                        map("id", 1, "status", "true"),
                        map("id", 2, "status", "false")))));
        assertEquals("items[2]{\"order:id\",\"full name\"}:\n  1,Ada\n  2,Bob",
                JToon.encode(map("items", list(
                        map("order:id", 1, "full name", "Ada"),
                        map("order:id", 2, "full name", "Bob")))));
        // Header field order is taken from the first object.
        assertEquals("items[2]{a,b,c}:\n  1,2,3\n  10,20,30",
                JToon.encode(map("items", list(
                        map("a", 1, "b", 2, "c", 3),
                        map("c", 30, "b", 20, "a", 10)))));

        // -- complex nested objects and list-item objects (tabular fallback) --
        assertEquals("user:\n  id: 123\n  name: Ada\n  tags[2]: reading,gaming\n  active: true\n  prefs: []",
                JToon.encode(map("user", map("id", 123, "name", "Ada",
                        "tags", list("reading", "gaming"), "active", true, "prefs", list()))));
        assertEquals("items[2]:\n  - id: 1\n    name: First\n  - id: 2\n    name: Second\n    extra: true",
                JToon.encode(map("items", list(
                        map("id", 1, "name", "First"),
                        map("id", 2, "name", "Second", "extra", true)))));
        assertEquals("items[1]:\n  - id: 1\n    nested:\n      x: 1",
                JToon.encode(map("items", list(map("id", 1, "nested", map("x", 1))))));
        // Field order preserved in list items (array first vs primitive first).
        assertEquals("items[1]:\n  - nums[3]: 1,2,3\n    name: Ada",
                JToon.encode(map("items", list(map("nums", list(1, 2, 3), "name", "Ada")))));
        // Nested uniform object array becomes tabular under a list item (rows at depth+2).
        assertEquals("items[1]:\n  - users[2]{id,name}:\n      1,Ada\n      2,Bob\n    status: active",
                JToon.encode(map("items", list(map(
                        "users", list(map("id", 1, "name", "Ada"), map("id", 2, "name", "Bob")),
                        "status", "active")))));
        // Empty object list items encode as a bare hyphen.
        assertEquals("items[3]:\n  - first\n  - second\n  -",
                JToon.encode(map("items", list("first", "second", map()))));
        assertEquals("items[2]:\n  -\n  -", JToon.encode(map("items", list(map(), map()))));
        // Array of arrays inside a list-item object.
        assertEquals("items[1]:\n  - matrix[2]:\n      - [2]: 1,2\n      - [2]: 3,4\n    name: grid",
                JToon.encode(map("items", list(map(
                        "matrix", list(list(1, 2), list(3, 4)), "name", "grid")))));
    }

    /** Formatting EncodeOptions: delimiters (with delimiter-aware quoting), length marker, indent. */
    @Test
    void encodesWithFormattingOptions() {
        // -- delimiters (TAB / PIPE) and delimiter-aware quoting --
        final EncodeOptions tab = EncodeOptions.withDelimiter(Delimiter.TAB);
        final EncodeOptions pipe = EncodeOptions.withDelimiter(Delimiter.PIPE);
        assertEquals("tags[3\t]: reading\tgaming\tcoding",
                JToon.encode(map("tags", list("reading", "gaming", "coding")), tab));
        assertEquals("tags[3|]: reading|gaming|coding",
                JToon.encode(map("tags", list("reading", "gaming", "coding")), pipe));
        assertEquals("items[2\t]{sku\tqty\tprice}:\n  A1\t2\t9.99\n  B2\t1\t14.5",
                JToon.encode(map("items", list(
                        map("sku", "A1", "qty", 2, "price", 9.99),
                        map("sku", "B2", "qty", 1, "price", 14.5))), tab));
        assertEquals("[2|]{id}:\n  1\n  2", JToon.encode(list(map("id", 1), map("id", 2)), pipe));
        assertEquals("pairs[2|]:\n  - [2|]: a|b\n  - [2|]: c|d",
                JToon.encode(map("pairs", list(list("a", "b"), list("c", "d"))), pipe));
        // Delimiter-aware quoting: active delimiter forces quoting; comma no longer special.
        assertEquals("items[3|]: a|\"b|c\"|d", JToon.encode(map("items", list("a", "b|c", "d")), pipe));
        assertEquals("items[2\t]: a,b\tc,d", JToon.encode(map("items", list("a,b", "c,d")), tab));
        assertEquals("note: a,b", JToon.encode(map("note", "a,b"), pipe));
        assertEquals("items[3|]: \"true\"|\"42\"|\"-3.14\"",
                JToon.encode(map("items", list("true", "42", "-3.14")), pipe));

        // -- length marker + custom indent + no-trailing-newline --
        final EncodeOptions marker = EncodeOptions.withLengthMarker(true);
        assertEquals("tags[#3]: a,b,c", JToon.encode(map("tags", list("a", "b", "c")), marker));
        assertEquals("items[#2]{id,name}:\n  1,Ada\n  2,Bob",
                JToon.encode(map("items", list(map("id", 1, "name", "Ada"),
                        map("id", 2, "name", "Bob"))), marker));
        assertEquals("user:\n    name: Ada\n    role: admin",
                JToon.encode(map("user", map("name", "Ada", "role", "admin")),
                        EncodeOptions.withIndent(4)));
        // No trailing newline at end of output.
        assertEquals("id: 123", JToon.encode(map("id", 123)));
    }

    /** Key folding (KeyFolding.SAFE): the dotted-path collapse algorithm and its guards. */
    @Test
    void encodesWithKeyFolding() {
        final EncodeOptions safe = EncodeOptions.withFlatten(true);
        assertEquals("a.b.c: 1", JToon.encode(map("a", map("b", map("c", 1))), safe));
        assertEquals("data.meta.items[2]: x,y",
                JToon.encode(map("data", map("meta", map("items", list("x", "y")))), safe));
        assertEquals("a.b.items[2]{id,name}:\n  1,A\n  2,B",
                JToon.encode(map("a", map("b", map("items", list(
                        map("id", 1, "name", "A"), map("id", 2, "name", "B"))))), safe));
        // Folding skipped when a segment would need quotes.
        assertEquals("data:\n  \"full-name\":\n    x: 1",
                JToon.encode(map("data", map("full-name", map("x", 1))), safe));
        // Folding skipped on sibling literal-key collision.
        assertEquals("data:\n  meta:\n    items[2]: 1,2\ndata.meta.items: literal",
                JToon.encode(map("data", map("meta", map("items", list(1, 2))),
                        "data.meta.items", "literal"), safe));
        // Depth control.
        assertEquals("a.b:\n  c:\n    d: 1",
                JToon.encode(map("a", map("b", map("c", map("d", 1)))),
                        EncodeOptions.withFlattenDepth(2)));
        assertEquals("a.b.c.d: 1", JToon.encode(map("a", map("b", map("c", map("d", 1)))), safe));
        // Folding stops at an array boundary and preserves sibling order.
        assertEquals("a.b[2]: 1,2", JToon.encode(map("a", map("b", list(1, 2))), safe));
        assertEquals("first.second.third: 1\nsimple: 2\nshort.path: 3",
                JToon.encode(map("first", map("second", map("third", 1)),
                        "simple", 2, "short", map("path", 3)), safe));
        // Folded chain ending with an empty object.
        assertEquals("a.b.c:", JToon.encode(map("a", map("b", map("c", map()))), safe));
    }

    // ===================================================================
    // NORMALIZATION (observed through encode of native Java types)
    // ===================================================================

    /** Scalar type normalization: numeric special cases + temporal ISO rendering. */
    @Test
    void normalizesScalarsAndTemporal() {
        // -- numeric special cases --
        // Non-finite doubles/floats normalize to null.
        assertEquals("v: null", JToon.encode(map("v", Double.NaN)));
        assertEquals("v: null", JToon.encode(map("v", Double.POSITIVE_INFINITY)));
        assertEquals("v: null", JToon.encode(map("v", Double.NEGATIVE_INFINITY)));
        assertEquals("v: null", JToon.encode(map("v", Float.NaN)));
        // Whole-valued doubles collapse to integers; regular decimals stay.
        assertEquals("v: 42", JToon.encode(map("v", 42.0)));
        assertEquals("v: 0", JToon.encode(map("v", -0.0)));
        assertEquals("v: 3.14159", JToon.encode(map("v", 3.14159)));
        // Byte / Short widen to integer text.
        assertEquals("v: 127", JToon.encode(map("v", (byte) 127)));
        assertEquals("v: 32767", JToon.encode(map("v", (short) 32767)));
        // BigInteger within long range -> integer; beyond -> string.
        assertEquals("v: 123456789", JToon.encode(map("v", BigInteger.valueOf(123456789L))));
        assertEquals("v: \"99999999999999999999999999999999\"",
                JToon.encode(map("v", new BigInteger("99999999999999999999999999999999"))));
        // BigDecimal keeps its full value.
        assertEquals("v: 123.456", JToon.encode(map("v", new BigDecimal("123.456"))));
        // Decimals render in plain notation (never scientific) with trailing zeros stripped.
        assertEquals("v: 0.1", JToon.encode(map("v", 0.1)));
        assertEquals("v: 100000000000000000000", JToon.encode(map("v", 1e20)));
        assertEquals("v: 1.5", JToon.encode(map("v", new BigDecimal("1.500"))));
        assertEquals("v: 1", JToon.encode(map("v", new BigDecimal("1.0"))));

        // -- temporal types -> ISO-8601 strings (colon-bearing ones are quoted) --
        assertEquals("v: \"2023-10-15T14:30:45\"",
                JToon.encode(map("v", LocalDateTime.of(2023, 10, 15, 14, 30, 45))));
        assertEquals("v: 2023-10-15", JToon.encode(map("v", LocalDate.of(2023, 10, 15))));
        assertEquals("v: \"14:30:45\"", JToon.encode(map("v", LocalTime.of(14, 30, 45))));
        assertEquals("v: \"2023-10-15T14:30:45Z\"",
                JToon.encode(map("v", ZonedDateTime.of(2023, 10, 15, 14, 30, 45, 0, ZoneId.of("UTC")))));
        assertEquals("v: \"2023-10-15T14:30:45Z\"",
                JToon.encode(map("v", OffsetDateTime.of(2023, 10, 15, 14, 30, 45, 0, ZoneOffset.UTC))));
        assertEquals("v: \"2023-10-15T14:30:45.123Z\"",
                JToon.encode(map("v", Instant.parse("2023-10-15T14:30:45.123Z"))));
        assertEquals("v: \"2025-11-26T15:45:00+01:00\"",
                JToon.encode(map("v", OffsetDateTime.of(2025, 11, 26, 15, 45, 0, 0,
                        ZoneOffset.ofHours(1)))));
    }

    /** Container/object normalization: Optional, Stream, Map keys, Java arrays, and POJOs. */
    @Test
    void normalizesContainersArraysAndPojos() {
        // -- Optional / Stream / non-String Map keys / Java arrays --
        // Optional unwrapping (empty -> null, present -> value, nested).
        assertEquals("v: null", JToon.encode(map("v", Optional.empty())));
        assertEquals("v: hello", JToon.encode(map("v", Optional.of("hello"))));
        assertEquals("v: 42", JToon.encode(map("v", Optional.of(Optional.of(42)))));
        // Stream materializes to an array.
        assertEquals("v[3]: 1,2,3", JToon.encode(map("v", Stream.of(1, 2, 3))));
        // Map with non-String keys stringifies the keys.
        final LinkedHashMap<Integer, String> intKeys = new LinkedHashMap<>();
        intKeys.put(1, "one");
        intKeys.put(2, "two");
        assertEquals("\"1\": one\n\"2\": two", JToon.encode(intKeys));
        // Primitive arrays: int[], boolean[], char[] (-> strings), double[] with non-finite -> null.
        assertEquals("v[3]: 1,2,3", JToon.encode(map("v", new int[]{1, 2, 3})));
        assertEquals("v[2]: true,false", JToon.encode(map("v", new boolean[]{true, false})));
        assertEquals("v[3]: a,b,c", JToon.encode(map("v", new char[]{'a', 'b', 'c'})));
        assertEquals("v[3]: 1,null,null",
                JToon.encode(map("v", new double[]{1.0, Double.NaN, Double.POSITIVE_INFINITY})));
        // Nested primitive array (int[][]) -> nested list form.
        assertEquals("m[2]:\n  - [2]: 1,2\n  - [2]: 3,4",
                JToon.encode(map("m", new int[][]{{1, 2}, {3, 4}})));

        // -- POJOs (record components in declaration order) and @JsonIgnore --
        // A record's components serialize in declaration order.
        assertEquals("name: Alice\nage: 25", JToon.encode(new SimplePojo("Alice", 25)));
        // Collections of POJOs with uniform primitive fields become tabular.
        assertEquals("[2]{name,age}:\n  Alice,25\n  Bob,30",
                JToon.encode(list(new SimplePojo("Alice", 25), new SimplePojo("Bob", 30))));
        // @JsonIgnore fields are omitted from the encoding (line order across getters is not
        // asserted, since Jackson getter ordering is not a documented contract).
        final String out = JToon.encode(new Account("ada", "s3cret", 5));
        assertTrue(out.contains("user: ada"));
        assertTrue(out.contains("level: 5"));
        assertFalse(out.contains("password"));
        assertFalse(out.contains("s3cret"));
        assertEquals(2, out.split("\n").length);
    }

    record SimplePojo(String name, int age) {
    }

    static final class Account {
        private final String user;
        private final String password;
        private final int level;

        Account(final String user, final String password, final int level) {
            this.user = user;
            this.password = password;
            this.level = level;
        }

        public String getUser() {
            return user;
        }

        @JsonIgnore
        public String getPassword() {
            return password;
        }

        public int getLevel() {
            return level;
        }
    }

    // ===================================================================
    // encodeJson (parse JSON, then encode -- distinct entry point)
    // ===================================================================

    @Test
    void encodesFromJsonStrings() {
        assertEquals("id: 123\nname: Ada", JToon.encodeJson("{\"id\":123,\"name\":\"Ada\"}"));
        assertEquals("tags[3]: admin,ops,dev",
                JToon.encodeJson("{\"tags\":[\"admin\",\"ops\",\"dev\"]}"));
        assertEquals("items[2]{sku,qty,price}:\n  A1,2,9.99\n  B2,1,14.5",
                JToon.encodeJson("{\"items\":[{\"sku\":\"A1\",\"qty\":2,\"price\":9.99},"
                        + "{\"sku\":\"B2\",\"qty\":1,\"price\":14.5}]}"));
        assertEquals("[3]:\n  - summary\n  - id: 1\n    name: Ada\n  - [2]:\n    - id: 2\n    - status: draft",
                JToon.encodeJson("[\"summary\", { \"id\": 1, \"name\": \"Ada\" },"
                        + " [{ \"id\": 2 }, { \"status\": \"draft\" }]]"));
        // Custom options: pipe delimiter + length marker.
        assertEquals("tags[#3|]: reading|gaming|coding\nitems[#2|]{sku|qty|price}:\n  A1|2|9.99\n  B2|1|14.5",
                JToon.encodeJson("{\"tags\":[\"reading\",\"gaming\",\"coding\"],"
                        + "\"items\":[{\"sku\":\"A1\",\"qty\":2,\"price\":9.99},"
                        + "{\"sku\":\"B2\",\"qty\":1,\"price\":14.5}]}",
                        new EncodeOptions(2, Delimiter.PIPE, true, KeyFolding.OFF, Integer.MAX_VALUE)));
        assertThrows(IllegalArgumentException.class, () -> JToon.encodeJson("{invalid}"));
        assertThrows(IllegalArgumentException.class, () -> JToon.encodeJson("   \n \t  "));
    }

    // ===================================================================
    // DECODING
    // ===================================================================

    /** Scalar decoding: correct Java types for keywords/quotes + numeric-token edge cases. */
    @Test
    void decodesScalarsAndNumbers() {
        // -- scalar types --
        assertEquals(42L, JToon.decode("42"));
        assertEquals(3.14, JToon.decode("3.14"));
        assertEquals(-7L, JToon.decode("-7"));
        assertEquals(Boolean.TRUE, JToon.decode("true"));
        assertEquals(Boolean.FALSE, JToon.decode("false"));
        assertNull(JToon.decode("null"));
        assertEquals("hello", JToon.decode("hello"));
        assertEquals("café", JToon.decode("café"));
        // Quoted scalars stay strings even when they look like keywords / numbers.
        assertEquals("true", JToon.decode("\"true\""));
        assertEquals("42", JToon.decode("\"42\""));
        assertEquals("-3.14", JToon.decode("\"-3.14\""));
        assertEquals("", JToon.decode("\"\""));
        // Integers decode to Long, not Integer/BigInteger.
        assertInstanceOf(Long.class, JToon.decode("42"));
        assertInstanceOf(Double.class, JToon.decode("3.14"));

        // -- numeric-token edge cases --
        assertEquals(map("value", 1.5), JToon.decode("value: 1.5000"));
        assertEquals(map("value", -1000L), JToon.decode("value: -1E+03"));
        assertEquals(map("value", 250L), JToon.decode("value: 2.5e2"));
        assertEquals(map("value", 0.03), JToon.decode("value: 3E-02"));
        assertEquals(map("value", 0L), JToon.decode("value: -0"));
        assertEquals(map("value", 0L), JToon.decode("value: -0.0"));
        assertEquals(map("value", 0L), JToon.decode("value: 0e1"));
        // Leading-zero tokens are strings, not numbers (single value, object, and arrays).
        assertEquals("05", JToon.decode("05"));
        assertEquals("-05", JToon.decode("-05"));
        assertEquals(map("a", "05"), JToon.decode("a: 05"));
        assertEquals(map("nums", list("05", "007", "0123")), JToon.decode("nums[3]: 05,007,0123"));
        assertEquals(1000000L, JToon.decode("1e6"));
        assertEquals(-0.001, JToon.decode("-1e-3"));
        // Mixed numeric forms in an inline array.
        assertEquals(map("nums", list(42L, -1000L, 1.5, 0L, 250L)),
                JToon.decode("nums[5]: 42,-1E+03,1.5000,-0,2.5e2"));
    }

    /** Structural object decoding: order + nesting, inline-array validation, and path expansion. */
    @Test
    void decodesObjectsInlineArraysAndPathExpansion() {
        // -- objects: order + nesting + empty/blank cases --
        final Object result = JToon.decode("id: 123\nname: Ada\nactive: true");
        assertInstanceOf(Map.class, result);
        assertEquals(map("id", 123L, "name", "Ada", "active", true), result);
        // Insertion order is preserved.
        assertEquals(list("id", "name", "active"),
                new ArrayList<>(((Map<?, ?>) result).keySet()));
        assertEquals(map("a", map("b", map("c", "deep"))), JToon.decode("a:\n  b:\n    c: deep"));
        // A bare "key:" value decodes to an empty object.
        assertEquals(map("user", map()), JToon.decode("user:"));
        // Blank/whitespace-only document decodes to an empty object.
        assertEquals(map(), JToon.decode("   "));

        // -- inline arrays with length validation --
        assertEquals(map("tags", list("a", "b", "c")), JToon.decode("tags[3]: a,b,c"));
        assertEquals(map("a", list(1L, 2L, 3L)), JToon.decode("a[3]: 1,2,3"));
        // Whitespace around delimiters is tolerated.
        assertEquals(map("a", list(1L, 2L)), JToon.decode("a[2]: 1 , 2"));
        // Quoted element preserves the delimiter as data.
        assertEquals(map("a", list("x", "y,z")), JToon.decode("a[2]: x,\"y,z\""));
        // Declared length must match the actual element count (strict default).
        assertThrows(IllegalArgumentException.class, () -> JToon.decode("tags[2]: a,b,c"));
        assertThrows(IllegalArgumentException.class, () -> JToon.decode("tags[3]: a,b"));
        // key: [] decodes to an empty list.
        assertEquals(map("items", list()), JToon.decode("items: []"));

        // -- path expansion (PathExpansion.SAFE) vs OFF default --
        final DecodeOptions safe = new DecodeOptions(2, Delimiter.COMMA, true, PathExpansion.SAFE,
                DecodeOptions.MAX_ALLOWED_DEPTH, DecodeOptions.DEFAULT_MAX_ARRAY_SIZE,
                DecodeOptions.DEFAULT_MAX_STRING_LENGTH);
        assertEquals(map("a", map("b", map("c", 1L))), JToon.decode("a.b.c: 1", safe));
        assertEquals(map("data", map("meta", map("items", list("a", "b")))),
                JToon.decode("data.meta.items[2]: a,b", safe));
        // Deep merge of two dotted keys under a shared prefix.
        assertEquals(map("a", map("b", 1L, "c", 2L)), JToon.decode("a.b: 1\na.c: 2", safe));
        // With expansion OFF (default), a dotted key stays literal.
        assertEquals(map("a.b.c", 1L), JToon.decode("a.b.c: 1"));
    }

    /** The two multi-line array decode paths: tabular blocks and list-style ("- ") items. */
    @Test
    void decodesTabularAndListArrays() {
        // -- tabular arrays --
        assertEquals(map("items", list(
                        map("sku", "A1", "qty", 2L, "price", 9.99),
                        map("sku", "B2", "qty", 1L, "price", 14.5))),
                JToon.decode("items[2]{sku,qty,price}:\n  A1,2,9.99\n  B2,1,14.5"));
        assertEquals(map("items", list(
                        map("id", 1L, "value", null),
                        map("id", 2L, "value", "test"))),
                JToon.decode("items[2]{id,value}:\n  1,null\n  2,\"test\""));
        assertEquals(map("items", list(
                        map("id", 1L, "note", "a:b"),
                        map("id", 2L, "note", "c:d"))),
                JToon.decode("items[2]{id,note}:\n  1,\"a:b\"\n  2,\"c:d\""));
        assertEquals(map("items", list(
                        map("order:id", 1L, "full name", "Ada"),
                        map("order:id", 2L, "full name", "Bob"))),
                JToon.decode("items[2]{\"order:id\",\"full name\"}:\n  1,Ada\n  2,Bob"));
        // An unquoted colon after the rows terminates the tabular block and starts a new pair.
        assertEquals(map("items", list(map("id", 1L, "name", "Alice"), map("id", 2L, "name", "Bob")),
                        "count", 2L),
                JToon.decode("items[2]{id,name}:\n  1,Alice\n  2,Bob\ncount: 2"));
        // Row/length mismatches throw in strict mode.
        assertThrows(IllegalArgumentException.class,
                () -> JToon.decode("items[2]{id,name}:\n  1,Ada\n  2"));
        assertThrows(IllegalArgumentException.class,
                () -> JToon.decode("[1]{id}:\n  1\n  2"));

        // -- list-style arrays ("- " items) --
        assertEquals(map("items", list(map("id", 1L, "name", "First"))),
                JToon.decode("items[1]:\n  - id: 1\n    name: First"));
        assertEquals(map("a", list(1L, "hi")), JToon.decode("a[2]:\n  - 1\n  - hi"));
        assertEquals(map("items", list(map("tags", list("a", "b")))),
                JToon.decode("items[1]:\n  - tags[2]: a,b"));
        // A list item carrying an object with several fields (first field on the hyphen line).
        assertEquals(map("items", list(map("id", 1L, "tags", list("a", "b")))),
                JToon.decode("items[1]:\n  - id: 1\n    tags[2]: a,b"));
        // Length is validated against the declared count.
        assertThrows(IllegalArgumentException.class, () -> JToon.decode("items[1]:\n  - 1\n  - 2"));
        assertThrows(IllegalArgumentException.class, () -> JToon.decode("items[2]:\n  - a"));
    }

    /** Quoted-string unescaping and its strict-mode error cases (distinct escape engine). */
    @Test
    void decodesStringUnescaping() {
        assertEquals("line1\nline2", JToon.decode("\"line1\\nline2\""));
        assertEquals("tab\there", JToon.decode("\"tab\\there\""));
        assertEquals("return\rcarriage", JToon.decode("\"return\\rcarriage\""));
        assertEquals("C:\\Users\\path", JToon.decode("\"C:\\\\Users\\\\path\""));
        assertEquals("say \"hello\"", JToon.decode("\"say \\\"hello\\\"\""));
        assertEquals(map("val", "ab"), JToon.decode("val: \"a\\u0004b\""));
        assertEquals(map("val", "a«b"), JToon.decode("val: \"a\\u00Abb\""));
        // Invalid / truncated / lone-surrogate escapes throw in strict mode.
        assertThrows(IllegalArgumentException.class, () -> JToon.decode("\"a\\x\""));
        assertThrows(IllegalArgumentException.class, () -> JToon.decode("val: \"a\\u00b\""));
        assertThrows(IllegalArgumentException.class, () -> JToon.decode("val: \"a\\uD800b\""));
        assertThrows(IllegalArgumentException.class, () -> JToon.decode("\"unterminated"));
    }

    /** Strict vs lenient decoding: which malformed inputs throw vs. are best-effort recovered. */
    @Test
    void enforcesStrictVsLenientMode() {
        final DecodeOptions lenient = DecodeOptions.withStrict(false);
        // Strict throws; lenient returns null (top-level swallow) for these malformed inputs.
        assertThrows(IllegalArgumentException.class, () -> JToon.decode("hello\nworld"));
        // Lenient mode is best-effort: multiple root primitives yield the first, not null.
        assertEquals("hello", JToon.decode("hello\nworld", lenient));
        assertThrows(IllegalArgumentException.class, () -> JToon.decode("a:\n  user"));
        assertThrows(IllegalArgumentException.class, () -> JToon.decode("name: Ada\nname: Bob"));
        assertThrows(IllegalArgumentException.class, () -> JToon.decode("items[2]{id,name}\n  1,Ada\n  2,Bob"));
        // Malformed array headers: leading zero, negative, non-integer, extra bracket, space before colon.
        assertThrows(IllegalArgumentException.class, () -> JToon.decode("items[03]: a,b,c"));
        assertThrows(IllegalArgumentException.class, () -> JToon.decode("items[-1]: a,b,c"));
        assertThrows(IllegalArgumentException.class, () -> JToon.decode("foo[bar]: 10"));
        assertThrows(IllegalArgumentException.class, () -> JToon.decode("foo[1][bar]: 10"));
        assertThrows(IllegalArgumentException.class, () -> JToon.decode("items[2] :\n  1,2"));
        // A duplicate-key mismatch is tolerated (last value wins) in lenient mode.
        assertEquals(map("name", "Bob"), JToon.decode("name: Ada\nname: Bob", lenient));
    }

    /** decodeToJson serialization (order + nulls preserved) and encode->decode round-trip. */
    @Test
    void decodesToJsonAndRoundTrips() {
        // Key order is preserved (not alphabetized) and nulls are kept.
        assertEquals("{\"id\":123,\"name\":\"Ada\",\"active\":true}",
                JToon.decodeToJson("id: 123\nname: Ada\nactive: true"));
        assertEquals("{\"id\":1,\"value\":null}", JToon.decodeToJson("id: 1\nvalue: null"));
        assertEquals("{\"items\":[{\"sku\":\"A1\",\"qty\":2},{\"sku\":\"B2\",\"qty\":1}]}",
                JToon.decodeToJson("items[2]{sku,qty}:\n  A1,2\n  B2,1"));
        assertEquals("null", JToon.decodeToJson("null"));
        // Round-trip: encode then decode a complex structure back to equal Java values.
        final Map<String, Object> original = map(
                "user", map("id", 123L, "name", "Ada", "tags", list("reading", "gaming")),
                "count", 2L);
        final String toon = JToon.encode(original);
        assertEquals(original, JToon.decode(toon));
    }

    // ===================================================================
    // SECURITY / OPTION VALIDATION
    // ===================================================================

    @Test
    void enforcesDecodeSecurityLimits() {
        // Within the default depth limit decodes; beyond it throws.
        assertTrue(JToon.decode(nestedToon(500)) instanceof Map);
        assertThrows(IllegalArgumentException.class, () -> JToon.decode(nestedToon(600)));
        // Declared array size beyond the maximum (and beyond Integer range) throws.
        assertThrows(IllegalArgumentException.class, () -> JToon.decode("items[10000001]: 1,2,3"));
        assertThrows(IllegalArgumentException.class, () -> JToon.decode("x[99999999999]: 1,2,3"));
        // A custom maxArraySize still admits arrays within its bound.
        final DecodeOptions custom = new DecodeOptions(2, Delimiter.COMMA, true, PathExpansion.OFF,
                DecodeOptions.MAX_ALLOWED_DEPTH, 100, DecodeOptions.DEFAULT_MAX_STRING_LENGTH);
        assertTrue(JToon.decode("items[50]: " + "x,".repeat(49) + "x", custom) instanceof Map);
        // String length limit.
        assertThrows(IllegalArgumentException.class,
                () -> JToon.decode("key: " + "x".repeat(10_000_001)));
    }

    private static String nestedToon(final int levels) {
        final StringBuilder sb = new StringBuilder();
        for (int i = 0; i < levels; i++) {
            sb.append("  ".repeat(i));
            if (i < levels - 1) {
                sb.append('a').append(i).append(":\n");
            } else {
                sb.append('a').append(i).append(": value");
            }
        }
        return sb.toString();
    }

    @Test
    void validatesEncodeAndDecodeOptions() {
        // EncodeOptions guards.
        assertThrows(IllegalArgumentException.class,
                () -> new EncodeOptions(-1, Delimiter.COMMA, false, KeyFolding.OFF, 10));
        assertThrows(IllegalArgumentException.class,
                () -> new EncodeOptions(EncodeOptions.MAX_ALLOWED_INDENT + 1, Delimiter.COMMA, false,
                        KeyFolding.OFF, 10));
        assertThrows(NullPointerException.class,
                () -> new EncodeOptions(2, null, false, KeyFolding.OFF, 10));
        assertThrows(IllegalArgumentException.class,
                () -> new EncodeOptions(2, Delimiter.COMMA, false, KeyFolding.SAFE, -1));
        // DecodeOptions guards.
        assertThrows(IllegalArgumentException.class,
                () -> new DecodeOptions(-1, Delimiter.COMMA, true, PathExpansion.OFF, 512,
                        DecodeOptions.DEFAULT_MAX_ARRAY_SIZE, DecodeOptions.DEFAULT_MAX_STRING_LENGTH));
        assertThrows(NullPointerException.class,
                () -> new DecodeOptions(2, null, true, PathExpansion.OFF, 512,
                        DecodeOptions.DEFAULT_MAX_ARRAY_SIZE, DecodeOptions.DEFAULT_MAX_STRING_LENGTH));
        assertThrows(IllegalArgumentException.class,
                () -> new DecodeOptions(2, Delimiter.COMMA, true, PathExpansion.OFF,
                        DecodeOptions.MAX_ALLOWED_DEPTH + 1, DecodeOptions.DEFAULT_MAX_ARRAY_SIZE,
                        DecodeOptions.DEFAULT_MAX_STRING_LENGTH));
        // encode/decode reject a null options argument.
        assertThrows(NullPointerException.class, () -> JToon.encode(map("a", 1), null));
        assertThrows(NullPointerException.class, () -> JToon.decode("a: 1", null));
    }
}
