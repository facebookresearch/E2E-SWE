# JToon — TOON serialization for Java

Implement **JToon**, a Java library for the **TOON** (Token-Oriented Object Notation) format: a
compact, human-readable serialization format that combines YAML-like indentation with CSV-like
tabular arrays. The library converts between Java objects / JSON strings and TOON text, and back.

Put your implementation under `/app/src` as Java sources in package `dev.toonformat.jtoon` (and
sub-packages of your choosing). Target **Java 17**.

## Build & dependencies (offline)

The environment is offline; do not download anything. These jars are pre-baked under
`/opt/jtoon/libs/` and are the only dependencies you may use:

- **Jackson 3.2.1** — packages `tools.jackson.core` / `tools.jackson.databind` (core + databind)
  and `tools.jackson.module` (jackson-module-blackbird). NOTE: Jackson 3 lives under
  `tools.jackson.*`, **not** `com.fasterxml.jackson.*`. The Jackson **annotations** (e.g.
  `@JsonIgnore`) remain under `com.fasterxml.jackson.annotation`.
- **JSpecify 1.0.0** — `org.jspecify.annotations` (nullness annotations; optional to use).

Provide an executable `/app/setup.sh` that compiles your sources offline with `javac`, e.g.:

```bash
CP=$(ls /opt/jtoon/libs/*.jar | tr '\n' ':')
mkdir -p /app/out
find /app/src -name '*.java' -print0 | xargs -0 javac -cp "$CP" -d /app/out
```

Use Jackson's tree model (`JsonNode`, `ObjectMapper`) for JSON parsing and for POJO→tree
conversion. Configure the mapper so serialization does **not** sort keys alphabetically and
**always** includes null values.

## Public API

All entry points are `static` methods on a final `JToon` class:

```java
package dev.toonformat.jtoon;

public final class JToon {
    public static String encode(Object input);
    public static String encode(Object input, EncodeOptions options);
    public static String encodeJson(String json);                       // parse JSON, then encode
    public static String encodeJson(String json, EncodeOptions options);
    public static Object  decode(String toon);                          // Map/List/String/Number/Boolean/null
    public static Object  decode(String toon, DecodeOptions options);
    public static String  decodeToJson(String toon);                    // decode, then JSON-serialize
    public static String  decodeToJson(String toon, DecodeOptions options);
}
```

`encode`/`decode`/`encodeJson`/`decodeToJson` throw `NullPointerException` if the `options` argument
is null. `encodeJson` throws `IllegalArgumentException` if the string is null, blank, or not valid
JSON.

### Options and enums

```java
public enum Delimiter { COMMA, TAB, PIPE }   // "," "\t" "|"
public enum KeyFolding { SAFE, OFF }
public enum PathExpansion { SAFE, OFF }

public record EncodeOptions(int indent, Delimiter delimiter, boolean lengthMarker,
                            KeyFolding flatten, int flattenDepth) {
    public static final EncodeOptions DEFAULT;          // (2, COMMA, false, OFF, Integer.MAX_VALUE)
    public static final int MAX_ALLOWED_INDENT = 100;
    public EncodeOptions();                             // == DEFAULT
    public static EncodeOptions withIndent(int indent);
    public static EncodeOptions withDelimiter(Delimiter d);
    public static EncodeOptions withLengthMarker(boolean lengthMarker);
    public static EncodeOptions withFlatten(boolean flatten);      // true -> SAFE, else OFF
    public static EncodeOptions withFlattenDepth(int flattenDepth);// flatten SAFE with this depth
}

public record DecodeOptions(int indent, Delimiter delimiter, boolean strict,
                            PathExpansion expandPaths, int maxDepth, int maxArraySize,
                            int maxStringLength) {
    public static final DecodeOptions DEFAULT;          // (2, COMMA, true, OFF, 512, 10_000_000, 10_000_000)
    public static final int MAX_ALLOWED_INDENT = 100;
    public static final int MAX_ALLOWED_DEPTH = 512;
    public static final int DEFAULT_MAX_ARRAY_SIZE = 10_000_000;
    public static final int DEFAULT_MAX_STRING_LENGTH = 10_000_000;
    public DecodeOptions();                             // == DEFAULT
    public static DecodeOptions withIndent(int indent);
    public static DecodeOptions withDelimiter(Delimiter d);
    public static DecodeOptions withStrict(boolean strict);
}
```

Validation in the record constructors (throw `IllegalArgumentException` unless noted):
`indent < 0` or `indent > 100`; a null `delimiter` throws `NullPointerException`;
`EncodeOptions.flattenDepth < 0`; `DecodeOptions.maxDepth <= 0` or `> 512`;
`DecodeOptions.maxArraySize <= 0`; `DecodeOptions.maxStringLength <= 0`.

`Delimiter` also exposes `char getValue()` (the delimiter char) and `toString()` (the delimiter
string).

## Encoding

Encoding first **normalizes** the input to a JSON tree (see "Type normalization"), then renders it.
Global rules: **2-space indentation** per depth level by default (configurable via `indent`); lines
joined with `\n`; **no trailing newline** and **no trailing spaces** on any line.

**Root values.** A null (or JSON null) encodes to `null`. A root scalar encodes to just its value
(`42`, `3.14`, `true`, `hello`). A root **empty object** encodes to an **empty (zero-length)
string** — not `""`; the two-character `""` is reserved for an empty *string* value. A root
**empty array** encodes to `[]`.

**Objects.** Each entry renders as `key: value` on its own line, in insertion order. A primitive
value uses `key: value` (colon + space). A nested non-empty object uses `key:` (bare colon) then its
fields indented one level deeper. An **empty nested object** renders as a bare `key:` with no
children. Null values render as `key: null`.

**Primitive string values — quoting.** A string value is written **unquoted** when safe, otherwise
wrapped in double quotes with escaping. A value MUST be quoted when it: is empty; has a leading or
trailing space; equals a keyword `true`/`false`/`null`; looks numeric (optional leading `-`, digits,
at most one `.`, optional `e`/`E` exponent with optional sign — e.g. `42`, `-3.14`, `1e-6`); contains
any of `:` `"` `\` `[` `]` `{` `}`, a newline/CR/tab, or any control char (≤ U+001F); contains the
**active delimiter** character; or **starts with `-`** (list-marker ambiguity). Otherwise it is
unquoted, including arbitrary Unicode (`café`, `你好`, `🚀`, `hello 👋 world` are all unquoted). A
string with a leading zero such as `05` is not treated as a number, but because it still reads as
number-like it is quoted: encode `"05"` → `"05"`.

**Escaping inside quotes:** `\` → `\\`, `"` → `\"`, newline → `\n`, CR → `\r`, tab → `\t`, any other
control char (≤ U+001F) → `\uXXXX` with **lowercase** 4-digit hex. Example: the string `a<U+0004>b`
renders (as an object value) `val: "ab"`.

**Object keys — quoting.** A key is unquoted iff its first char is a Java identifier start (letter,
`_`, `$`) and every remaining char is a Java identifier part **or `.`** and not a control char.
Dots are allowed unquoted (`user.name`). Otherwise the key is quoted and escaped with the same
escaping as values. Keys are quoted for: spaces, leading `-`, digit-first (`123`), empty string,
`:`, `,`, brackets/braces, and control chars. The keyword/number-like rule is values-only (it does
not force key quoting), though a digit-first key is quoted anyway since it is not an identifier
start.

**Arrays.**

- *Inline primitive array* (all elements scalar): `key[N]: v1,v2,...` — length `N` in brackets, a
  space after the colon, values joined by the delimiter with no surrounding spaces. Each value is
  quoted per the value rules above. An empty array is `key: []`. A root inline array is `[N]: ...`.
- *Tabular array* (array of ≥1 objects, every element an object with the **same set of keys as the
  first** and **all values scalar**): header `key[N]{f1,f2,...}:` (field names in first-object order,
  each quoted if needed), then one row per element indented one level, values in header-field order
  joined by the delimiter. `null` fields render as `null`. Header field order comes from the first
  object. A root tabular array is `[N]{...}:`.
- *Nested arrays* (array whose elements are arrays): header `key[N]:`, then one `- ` item per inner
  array, each rendered as an inline array `- [M]: ...` (empty inner array → `- [0]:`).
- *Mixed / non-uniform arrays* (mixing scalars, objects, arrays, or objects with differing keys):
  header `key[N]:`, then one `- ` item per element indented one level. A scalar item is `- value`;
  an object item places its **first** field on the `- ` line (`- k: v`) with remaining fields
  indented one further level; an **empty object** item is a bare `-`; an inner array item is
  `- [M]: ...`, rendered per the array rules above. Within a list-item object, a first field that is
  itself an inline/tabular/nested array follows the same array rendering with its rows/items at the
  appropriate deeper indent, and a first field that is an object uses `- k:` then its fields deeper.

Any array that does not qualify as tabular (a non-object element, mismatched key sets, an empty
first object, or any non-scalar field value) falls back to the mixed/list form.

**Delimiters.** With `Delimiter.TAB` or `PIPE`, values/fields are joined by that char, and for
non-comma delimiters the length bracket carries the **actual delimiter character** itself (comma
uses plain `[N]`). For `PIPE` this is a literal pipe — `[N|]`. For `TAB` it is a **real tab
character** between the length and `]` (the tab char itself — the same character that joins the
values — **not** the two-character escape sequence `\t`). Quoting follows the **active** delimiter:
a value containing the active delimiter is quoted, and a value containing a comma is **not** quoted
when the active delimiter is tab/pipe.
Ambiguity quoting (keywords/numbers) is independent of the delimiter.

**Length marker.** With `lengthMarker = true`, a `#` is inserted right after `[` in every array
header: `[#N]`, `[#N|]`, and tabular `[#N]{...}`.

**Key folding** (`flatten = KeyFolding.SAFE`). Collapse chains of single-key nested objects into a
dotted path: `{a:{b:{c:1}}}` → `a.b.c: 1`. A chain folds only while each level is an object with
exactly one key, requires ≥2 segments, and every segment must match `[A-Za-z_]\w*` (a segment
needing quotes, e.g. `full-name`, stops folding — emit standard nesting instead). Folding stops at
an array or scalar boundary and applies the array/scalar rendering to the folded key (`{a:{b:[1,2]}}`
→ `a.b[2]: 1,2`; `{data:{meta:{items:[...]}}}` → `data.meta.items[...]:`). A chain ending in an empty
object folds to `a.b.c:`. Folding is skipped for a chain when the resulting dotted key would collide
with an existing sibling literal key. This collision test uses the fold's **fully-resolved path from
the document root**, so the skip propagates into nested folds: within a chain left unfolded by such a
collision, an interior single-key sub-chain whose resolved path still equals that literal key is left
unfolded too — e.g. `{cfg:{opts:{vals:[...]}}}` beside a sibling literal key `cfg.opts.vals`
renders as standard nesting throughout (`cfg:` / `opts:` / `vals[...]:`), not a partially-folded
`cfg:` / `opts.vals[...]:`. `flattenDepth` caps the number of folded segments
(`withFlattenDepth(2)` on `{a:{b:{c:{d:1}}}}` → `a.b:` then `c:` / `d: 1`); `flattenDepth = 0`
disables folding. Sibling field order is preserved.

## Type normalization (encode of native Java values)

`encode(Object)` normalizes Java values to a JSON tree before rendering:

- **Numbers.** Non-finite `Double`/`Float` (`NaN`, `±Infinity`) → null. `-0.0` and `+0.0` → integer
  `0`. A whole-valued `double` in `long` range → integer (`42.0` → `42`). Other decimals keep their
  value (`3.14159`). `Byte`/`Short` → integer. `BigInteger` within `long` range → integer; outside →
  its decimal **string**. `BigDecimal` keeps its full value (`123.456`). Decimals are rendered in
  **plain decimal notation, never scientific/exponent form**, with trailing fractional zeros
  stripped: `0.000001` (not `1.0E-6`), `1e20` → `100000000000000000000`, `BigDecimal("1.500")` →
  `1.5`, `BigDecimal("1.0")` → `1`.
- **Temporal → ISO-8601 string.** `LocalDate` → `2023-10-15`; `LocalDateTime` →
  `2023-10-15T14:30:45`; `LocalTime` → `14:30:45`; `OffsetDateTime` → ISO offset
  (`2023-10-15T14:30:45Z`, `2025-11-26T15:45:00+01:00`); `ZonedDateTime` → its offset form
  (`2023-10-15T14:30:45Z`, without any `[Zone]` suffix); `Instant` → its ISO instant
  (`2023-10-15T14:30:45.123Z`). (These ISO strings contain `:` and are therefore emitted quoted as
  object values; pure dates are not.)
- **Containers.** `Optional` unwraps (empty → null, present → value, nested Optionals unwrap fully).
  `Stream` and `Collection`/`Set` → array. `Map` → object, stringifying non-String keys via
  `String.valueOf`.
- **Arrays.** Java arrays → arrays. `char[]` → array of one-char strings. `int[]`/`long[]`/`short[]`/
  `byte[]` → integers; `boolean[]` → booleans; `double[]`/`float[]` → numbers with non-finite
  elements becoming null; `Object[]`/nested arrays recurse.
- **POJOs.** Any other object is converted with Jackson's tree conversion (public getters / record
  components, in declaration order). Fields annotated
  `@com.fasterxml.jackson.annotation.JsonIgnore` are omitted.

`encodeJson(String)` parses the JSON to a tree and encodes it directly (no Java-type normalization).

## Decoding

`decode(String)` returns Java values: an object → **`LinkedHashMap<String,Object>`** (source key
order preserved); an array → **`List<Object>`**; scalars → `String` / `Long` / `Double` / `Boolean`
/ `null`. Special whole-document cases: `null` (literal, after trim) → Java null; `[]` → empty list;
a null/blank/whitespace-only document → an empty map.

**Scalar parsing.** `true`/`false` → Boolean; `null` → null; a quoted string → its unescaped
contents (a **String**, even if it looks like a keyword/number: `"true"` → `"true"`, `"42"` →
`"42"`, `""` → `""`). An unquoted token containing no `.`/`e`/`E` parses as **`Long`** (`42` → `42L`,
`-0` → `0L`); one containing `.`/`e`/`E` parses via `double`, then: a value equal to `0` → `0L`; a
finite whole number in `long` range → `Long` (`3.0`→`3`, `1e3`→`1000`, `2.5e2`→`250`, `-1E+03`→
`-1000`); otherwise `Double` (`3.14`, `1.5`, `0.03`, `-0.001`). A token that looks numeric but has a
**forbidden leading zero** (`05`, `007`, `0123`, `-05`) is returned as a **String**. (No
`BigInteger`/`BigDecimal` is produced; an integer beyond `long` range decodes to a String.)

**Objects.** `key: value` lines, nesting by indentation (default 2 spaces). A `key:` with no value
decodes to an **empty map** for that key.

**Inline arrays.** `key[N]: v1,v2,...` — values split on the delimiter (respecting quotes and
escapes; surrounding whitespace tolerated), each parsed as a scalar. `key: []` → empty list. The
declared length `N` must equal the actual element count (see strict mode). A header may embed a
delimiter override (`[N|]`, `[N\t]`).

**Tabular arrays.** `key[N]{f1,f2,...}:` then rows; each row → a `LinkedHashMap` pairing field names
to parsed scalar values. Quoted field names and row values are unescaped (`{"order:id","full name"}`
keys; `1,"a:b"` values). An unquoted-colon line at row depth **terminates** the tabular block and
begins a new key/value pair. Row value count must match the field count and row count must match
`N`.

**List-style arrays.** `key[N]:` then `- ` items (scalars, objects with fields, or nested arrays),
as produced by the encoder. The item count must match `N`.

**Path expansion** (`expandPaths = PathExpansion.SAFE`). An unquoted dotted key whose every segment
matches `[A-Za-z_]\w*` expands into nested maps: `a.b.c: 1` → `{a:{b:{c:1}}}`; sibling dotted keys
deep-merge (`a.b: 1` + `a.c: 2` → `{a:{b:1,c:2}}`). With the default `OFF`, a dotted key stays
literal (`{"a.b.c":1}`).

**String unescaping.** Quoted values are unescaped: `\n`, `\r`, `\t`, `\"`, `\\`, and `\uXXXX` (hex
is case-insensitive; surrogate pairs supported). Invalid escapes (`\x`), truncated unicode (`\u00b`),
lone surrogates (`\uD800`), and an unterminated quoted string are errors.

**Strict vs lenient.** With `strict = true` (default), structurally invalid input throws
`IllegalArgumentException`. This includes: array length / row / field count mismatches; invalid array
headers (`[03]` leading zero, `[-1]` negative, `[bar]` non-integer, `foo[1][bar]`, `items[2] :`
whitespace before colon, a header missing its colon); duplicate sibling keys; multiple primitives at
the root; a missing colon in a key/value context; and the string-escape errors above. With
`strict = false`, decoding is best-effort: a fatal top-level error yields `null` instead of throwing,
duplicate keys keep the last value, and multiple root primitives yield the first.

**decodeToJson.** Decodes, then serializes the result back to a JSON string, preserving key order
(not alphabetized) and including nulls (`id: 123\nname: Ada` → `{"id":123,"name":"Ada"}`;
`id: 1\nvalue: null` → `{"id":1,"value":null}`). A decoded null → the literal string `null`.

**Security limits (decode).** `maxDepth` (default 512) bounds object nesting; deeper input throws.
`maxArraySize` (default 10,000,000) bounds declared and actual array sizes (an oversized or
out-of-int-range declared length throws). `maxStringLength` (default 10,000,000) bounds scalar token
length. All limit violations throw `IllegalArgumentException` (subject to lenient-mode swallowing).
