# Lattice Configuration Library (`com.lattice.config`)

Implement a configuration library for the JVM, written in **plain Java with no external
dependencies**. It parses a human-friendly configuration format (a superset of JSON, described
below), exposes an immutable typed-access API over the parsed data, resolves variable
substitutions, merges configurations, converts values into durations/periods/byte-sizes, and can
bind a configuration subtree onto a Java bean.

Everything lives under the package `com.lattice.config`. Organize internal helper classes however
you like, but the public types named below must be importable at exactly the paths given (tests
`import com.lattice.config.*;`).

The library must compile as plain Java (target Java 8) with `javac` and have no third-party
dependencies.

---

## 1. The configuration format

The format is a superset of JSON: **every valid JSON document is a valid configuration document and
parses to the same data.** On top of JSON it adds the leniencies below. A parsed document is always
a JSON-equivalent tree (objects, lists, strings, numbers, booleans, null).

**Leniencies over JSON:**

- **Comments**: `#` and `//` begin a comment that runs to end of line. Comments never affect values.
- **Root braces optional**: a document may omit the outermost `{ }`.
- **`=` as a synonym for `:`** between a key and its value.
- **Omit the separator before `{`**: `foo { a : 1 }` means `foo : { a : 1 }`.
- **Commas optional**: a newline can separate object fields or array elements in place of a comma.
- **Trailing commas** are allowed after the last element of an object or array.
- **Unquoted strings**: an unquoted run of characters is a string. Adjacent value tokens on one line
  concatenate (see §5).
- **Unquoted keys with dots**: `foo.bar = 1` is equivalent to `foo { bar = 1 }` (the key path is
  split on `.` into nested objects). This applies to numeric-looking keys too: `0.1.2 = x` nests
  three levels (`0` → `1` → `2`).
- **Duplicate keys**: a later value for the same key overrides an earlier one, **except** when both
  values are objects, in which case the two objects are **deep-merged** (recursively, later fields
  winning). A non-object value (including `null`) assigned to a key **resets** it, discarding any
  earlier object before a later object merges on top.
- **Quoted keys/values** use JSON string syntax. A quoted key containing `.` (e.g. `"a.b"`) is a
  **single** key element, not a path. Standard JSON escapes (`\n \t \" \\ \b \f \r` and `\uXXXX`)
  are decoded on parse.
- **Triple-quoted strings** (`"""..."""`) are multi-line raw strings: inner newlines and characters
  are preserved verbatim, no escape processing.
- Keys may contain characters like `/` and `-` unquoted (e.g. `/a/b/c = 42`).

**Parse errors** (see §8 for the exception hierarchy) are reported as `ConfigException.Parse` — for
example two key/value pairs on one line with no separator between them, an unclosed brace, or a
missing value. In JSON-syntax mode (see §7), the extended leniencies above are rejected as parse
errors.

---

## 2. Entry points (`ConfigFactory`)

`public final class ConfigFactory` — static factory methods. The ones you must provide:

- `Config parseString(String s)` — parse a document in the default (superset) syntax.
- `Config parseString(String s, ConfigParseOptions options)` — parse using the given options
  (see §7 for `ConfigParseOptions` / `ConfigSyntax`).
- `Config parseProperties(java.util.Properties props)` — build a `Config` from a Java `Properties`
  object (see §9).
- `Config empty()` — an empty `Config` (`isEmpty()` is true).

A freshly parsed `Config` is **not** resolved: substitutions (§4) are handled only when you call
`resolve()`.

---

## 3. Reading values (`Config`)

`public interface Config` is an **immutable** map from dot-separated **path expressions** to values.
A path like `a.b.c` looks up key `c` in object `b` in object `a`. All transforming methods return a
**new** `Config`; nothing mutates in place. Values read through `Config` are never null (a JSON
`null` is treated as absent — see `hasPath` / `getIsNull`).

**Structure / navigation:**

- `ConfigObject root()` — the underlying object tree (see §6).
- `boolean isEmpty()`
- `boolean hasPath(String path)` — true if a **non-null** value is present at `path`.
- `boolean hasPathOrNull(String path)` — true if a value is present, **even if it is null**.
- `boolean getIsNull(String path)` — true if the value at `path` exists and is null; throws
  `ConfigException.Missing` if the path is entirely unset.
- `java.util.Set<java.util.Map.Entry<String, ConfigValue>> entrySet()` — the set of **leaf**
  path→value pairs (recurses the tree; excludes null values; keys are path expressions).
- `Config getConfig(String path)` — the subtree at `path` as a `Config`.
- `ConfigObject getObject(String path)` — the subtree as a `ConfigObject`.
- `ConfigValue getValue(String path)` — the raw value (see §6).

**Typed getters.** Each throws `ConfigException.Missing` if unset, `ConfigException.Null` if the
value is null, and `ConfigException.WrongType` if present but not convertible. Path syntax errors
throw `ConfigException.BadPath`.

- `boolean getBoolean(String path)`, `Number getNumber(String path)`,
  `int getInt(String path)`, `long getLong(String path)`, `double getDouble(String path)`,
  `String getString(String path)`, `Object getAnyRef(String path)`.
- List forms returning `java.util.List<T>`: `getBooleanList`, `getNumberList`, `getIntList`,
  `getLongList`, `getDoubleList`, `getStringList`, `getObjectList`, `getConfigList`,
  `getAnyRefList`, and `ConfigList getList(String path)` (see §6).
- Enum forms: `<T extends Enum<T>> T getEnum(Class<T> enumClass, String path)` reads an enum constant
  by its name; `<T extends Enum<T>> List<T> getEnumList(Class<T> enumClass, String path)` reads a
  list of them. An unrecognized constant name throws `ConfigException.BadValue`.

**Type conversions** performed by the getters:

- **Number ↔ string**: a number read via `getString` yields its literal string form; a numeric
  string read via `getInt`/`getDouble`/etc. is parsed as that number.
- **String → boolean**: `true`/`yes`/`on` → `true`; `false`/`no`/`off` → `false`. Any other string
  is `WrongType` for `getBoolean`.
- **`getInt` truncation**: a floating value is narrowed toward zero (`3.99` → `3`, `-3.99` → `-3`),
  as with a Java narrowing primitive conversion.
- **`getInt` range**: a value outside 32-bit `int` range throws `ConfigException.WrongType` (it does
  not silently wrap); `getLong` still returns it.
- An **empty array** `[]` is a valid value for **any** typed-list getter (yielding an empty list).

**Transforming a `Config` (each returns a new instance):**

- `Config withValue(String path, ConfigValue value)` — copy with `path` set to `value`
  (see `ConfigValueFactory`, §6).
- `Config withOnlyPath(String path)` — copy retaining only that path (and its subtree).
- `Config withoutPath(String path)` — copy with that path removed.
- `Config atPath(String path)` — wrap this config beneath `path` (a path expression).
- `Config atKey(String key)` — wrap this config beneath a single `key` (not a path).
- `Config withFallback(ConfigMergeable other)` — merge (see §4/§5-merge).

**Validation:**

- `void checkValid(Config reference, String... restrictToPaths)` — validate this (resolved) config
  against a `reference` config, throwing `ConfigException.ValidationFailed` if it is invalid. Rules:
  every path present in `reference` must be present here, or validation fails; a type that is
  incompatible with the reference's type at the same path fails (with the important exception that a
  **string is treated as compatible with any scalar type** — strings often stand in for numbers,
  durations, etc. — and any type may be null or override null). An **object vs. non-object** (or
  list vs. non-list) mismatch does fail. If `restrictToPaths` is non-empty, only those paths (and
  their subtrees) are validated; paths in `reference` but not under any restrict path are ignored.
  Both configs must be resolved first: calling `checkValid` on an unresolved config throws
  `ConfigException.NotResolved`. The thrown `ValidationFailed` exposes an
  `Iterable` of problem descriptions via `problems()` (one per offending path).

---

## 4. Substitutions and resolution

A value may reference another path with the substitution syntax:

- `${path}` — a **required** reference.
- `${?path}` — an **optional** reference.

A freshly parsed `Config` that contains **no** substitutions is already fully resolved
(`isResolved()` is true), and all typed getters — including the unit getters of §11 (`getBytes`,
`getDuration`, `getPeriod`, …) — work on it directly **without** an explicit `resolve()` call. You
only need `resolve()` when the document actually contains `${...}` references. Calling a getter for
a value that still contains an unresolved substitution throws `ConfigException.NotResolved`.

Resolution is triggered by:

- `Config resolve()` — return a copy with all substitutions replaced. Uses this config as the
  lookup root: `${a.b}` resolves to `getValue("a.b")`.
- `Config resolve(ConfigResolveOptions options)` — as above with options; with
  `setAllowUnresolved(true)`, unresolved references are left in place instead of throwing.
- `boolean isResolved()` — true if no unresolved substitutions remain (true immediately for a
  document that had none).
- `Config resolveWith(Config source)` — resolve using `source` as the lookup root instead of this
  config (this config's own values are **not** consulted).

**Resolution semantics:**

- A `${path}` resolves to the value the referenced path has **after** all overrides/merges are
  applied (references see the final value, not an intermediate one).
- References may chain (`a → b → c`) and are followed transitively.
- **Required missing** (`${x}` with no `x`) → `ConfigException.UnresolvedSubstitution`.
- **Optional missing** (`${?x}` with no `x`): the enclosing field/element simply **disappears** (an
  object field vanishes; an array element is dropped; a whole document can become empty).
- **Cycles** (`a: ${a}`, or `a: ${b}, b: ${a}`) → `ConfigException.UnresolvedSubstitution` whose
  message contains the word `cycle`. A required-missing error message does **not** contain `cycle`.
- **Self-reference / look-back**: when a key is assigned `${sameKey}` after already having a value,
  the substitution uses the **prior** value of that key in the merge stack (`a = 1` then
  `a = ${a}` → `1`). This includes accumulation in string concatenation: `a = 1`, then
  `a = ${a}foo` → `"1foo"`; repeated appends accumulate (`${a}x`,`${a}y`,`${a}z` → `"1xyz"`).
- An **override hides** an otherwise-undefined or circular reference: `a = ${nonexistent}` followed
  by `a = 42` resolves to `42`.
- **Optional self-reference with no prior value** vanishes: `a = ${?a}` → the field disappears;
  `a = ${?a}foo` → `"foo"`.
- A reference to a **child field** of an object from a sibling field within the same object is a
  normal reference, not a self-reference: `bar { foo = 42, baz = ${bar.foo} }` → `baz` = 42.
- A substitution inside a quoted/unquoted string concatenation substitutes into the string
  (`start<${x}>end`). An optional-missing reference inside a string yields an empty span
  (`start<${?missing}>end` → `"start<>end"`).

If you call a getter for a still-unresolved value (e.g. after `resolve(..., allowUnresolved=true)`),
throw `ConfigException.NotResolved`.

---

## 5. Concatenation and merging

**Value concatenation** (values that appear next to each other on one line):

- **Strings**: adjacent value tokens on a line concatenate into one string, joined by single spaces:
  `a : true "xyz" 123 foo` → `"true xyz 123 foo"`. Inside `[ ]`, whitespace-separated tokens with no
  comma/newline concatenate into a single element (`[ 1 2 3 ]` → one element `"1 2 3"`), while
  newline/comma-separated tokens are distinct elements.
- **Arrays**: two arrays on one line concatenate element-wise: `[1, 2] [3, 4]` → `[1,2,3,4]`.
- **Objects**: two objects on one line merge: `{ a : 1 } { b : 2 }` → `{ a:1, b:2 }` (later fields
  win on conflict).
- **`+=`**: `path += value` appends `value` to the array at `path` (creating a one-element array if
  `path` is unset). Equivalent to `path = ${?path} [ value ]`.
- Concatenating an object, array, or null **into a string** is a `ConfigException.WrongType` whose
  message contains `Cannot concatenate`. A `+=` onto a non-array value is likewise
  `WrongType`/`Cannot concatenate`.
- A concatenation may not span a newline; doing so is a `ConfigException.Parse`.
- Optional substitutions in concatenations follow §4 (missing → contributes nothing).

**Merging** via `Config withFallback(ConfigMergeable other)` — combine two configs, with **this**
config taking priority over `other`:

- Scalars: the higher-priority (this) value wins on a conflicting key.
- Objects: nested objects **deep-merge**; conflicting leaves take the higher-priority value.
- A higher-priority **primitive blocks** a lower-priority object at the same key (and vice versa: a
  higher-priority object is not overwritten by a lower-priority primitive).
- **Lists replace** wholesale; they never merge element-wise.
- An intervening non-object value between two objects **blocks** their merge.
- `withFallback` is **associative**: `(x.withFallback(y)).withFallback(z)` equals
  `x.withFallback(y.withFallback(z))`.

`Config` extends `ConfigMergeable`; `withFallback` accepts any `ConfigMergeable`.

---

## 6. The value model (`ConfigValue`, `ConfigObject`, `ConfigList`)

- `interface ConfigValue` — a parsed value. Methods: `ConfigValueType valueType()`,
  `Object unwrapped()` (the value as a plain Java `Boolean`/`Number`/`String`/`Map`/`List`/`null`).
- `enum ConfigValueType { OBJECT, LIST, NUMBER, BOOLEAN, NULL, STRING }`.
- `interface ConfigObject extends ConfigValue, java.util.Map<String, ConfigValue>` — an object node.
  Implements `Map` as an **unmodifiable** map (all mutators — `put`, `remove`, `clear`, `putAll` —
  throw `UnsupportedOperationException`). `valueType()` is `OBJECT`. `Config toConfig()` returns the
  `Config` view. Keys are literal keys, not path expressions.
- `interface ConfigList extends ConfigValue, java.util.List<ConfigValue>` — a list node,
  **unmodifiable** (mutators throw `UnsupportedOperationException`). `valueType()` is `LIST`.

**Equality:**

- Numeric values are equal across `int`/`long`/`double` when they represent the same value
  (`fromAnyRef(42).equals(fromAnyRef(42L))`, `fromAnyRef(3.0).equals(fromAnyRef(3))`).
- A `ConfigObject` is **never** equal to its own `Config` view; two objects with equal contents have
  equal `Config` views.
- Numbers round-trip through their original literal string on `getString` (e.g. `1e6` → `"1e6"`,
  `0.00005` → `"0.00005"`).

**Construction (`ConfigValueFactory`)** — `public final class` with static methods:

- `ConfigValue fromAnyRef(Object o)` — wrap a plain Java value (`Boolean`→BOOLEAN, whole/`Integer`
  and `Long`→NUMBER, `Double`→NUMBER, `String`→STRING, `null`→NULL, `Map`→object, `Iterable`→list).
- `ConfigObject fromMap(java.util.Map<String,? extends Object> m)` — keys are literal keys.
- `ConfigList fromIterable(Iterable<? extends Object> it)`.

**`ConfigMemorySize`** — `public final class`. `static ConfigMemorySize ofBytes(long n)`,
`long toBytes()`, `java.math.BigInteger toBytesBigInteger()` (for sizes exceeding `long`), plus
value equality.

**Rendering** — `ConfigObject.render(ConfigRenderOptions options)` produces a string form.
`ConfigRenderOptions.concise()` gives a compact JSON-like render. When rendering an object, keys
that look like non-negative integers are ordered **numerically ascending** and placed **before**
non-numeric keys (which follow in their own order).

---

## 7. Options and syntax

- `enum ConfigSyntax { JSON, CONF, PROPERTIES }`.
- `ConfigParseOptions` — `static ConfigParseOptions defaults()`,
  `ConfigParseOptions setSyntax(ConfigSyntax s)`. In `JSON` syntax the superset leniencies (§1) are
  rejected: unquoted keys, comments, trailing commas, a missing `:` between key and value, a leading
  `+` on a number, unterminated strings, and `[ , ]` all raise `ConfigException.Parse`.
- `ConfigResolveOptions` — `static ConfigResolveOptions defaults()`,
  `ConfigResolveOptions setAllowUnresolved(boolean b)`.
- `ConfigRenderOptions` — `static ConfigRenderOptions concise()`.

---

## 8. Exceptions (`ConfigException`)

`public abstract class ConfigException extends RuntimeException`, with these nested subclasses (all
`public static`):

- `Missing` — path unset. Message includes the path.
- `Null extends Missing` — value present but null where a value was required.
- `WrongType` — value present but not convertible to the requested type.
- `BadPath` — a path expression is syntactically invalid.
- `BadValue` — a value could not be parsed as requested (e.g. an unparseable duration/size).
- `Parse` — a document could not be parsed.
- `UnresolvedSubstitution extends Parse` — a substitution did not resolve (message contains `cycle`
  for a cyclic reference).
- `NotResolved extends BugOrBroken` — a resolution-requiring operation was used before `resolve()`.
- `BugOrBroken`, `Generic`, `IO` — general categories.
- `ValidationFailed` — thrown by bean validation (§10); `Iterable<ValidationProblem> problems()`.
- `BadBean extends BugOrBroken` — a bean type could not be mapped.

---

## 9. Path expressions and `.properties` (`ConfigUtil`, `parseProperties`)

**`ConfigUtil`** — `public final class` with static path utilities:

- `String joinPath(String... elements)` / `String joinPath(java.util.List<String> elements)` — join
  path elements into a path expression, quoting any element that needs it (empty string, or one
  containing `.` or other special characters). `joinPath("a","b","c")` → `a.b.c`;
  `joinPath("","a","b","$")` → `"".a.b."$"`. Joining zero elements throws `ConfigException`.
- `java.util.List<String> splitPath(String path)` — inverse of `joinPath`. `splitPath("a.b.c")` →
  `[a, b, c]`; `splitPath("\"\".a.b.\"$\"")` → `["", a, b, $]`; a quoted dotted element stays one
  element (`splitPath("a.\"b.c\".d")` → `[a, b.c, d]`); numeric keys split on `.`
  (`splitPath("1.2.3")` → `[1, 2, 3]`). Invalid path expressions (`""`, `"a."`, `".b"`, `"a..b"`)
  throw `ConfigException.BadPath`. `splitPath(joinPath(x))` round-trips `x`.
- `String quoteString(String s)` — render `s` as a JSON string literal, escaping control characters
  (`quoteString("")` → `""` with quotes; `quoteString("\n")` → a 4-char string `"\n"`).

**`parseProperties`** (§2) maps a Java `Properties` object to a `Config`:

- Dotted property keys become nested objects: `a.b.c=42` → `a { b { c = 42 } }`.
- Numeric leaf keys under a common prefix collapse into a **list**, ordered by numeric index:
  `a.0=zero, a.1=one, a.2=two` → `a = [zero, one, two]`. Present indices are collected in numeric
  order (a missing index does not truncate — `a.0, a.1, a.3` yields the three present values in
  order).
- If a key is both an object prefix and a leaf (`a.b=child` and `a=parent`), the **object wins**
  (the `a.b` object form is kept).

---

## 10. Bean binding (`ConfigBeanFactory`)

`public final class ConfigBeanFactory` with:

- `static <T> T create(Config config, Class<T> clazz)` — instantiate a JavaBean (public no-arg
  constructor, standard getters/setters) from a resolved `Config`, mapping each bean property from
  the config key of the same name.

Supported property types: primitives and their boxed forms (with the same string→number and
string→boolean coercions as the getters), `String`, enums (bound from their constant name),
`java.util.List<E>` of a supported element type, `java.time.Duration`, and `ConfigMemorySize`.

Behaviors:

- **camelCase ↔ hyphen**: a bean property `fooBar` binds from a config key `foo-bar`.
- **Unknown keys** in the config that don't map to a bean property are ignored by default.
- A **missing** required (non-optional) property → `ConfigException.ValidationFailed`.
- An **invalid enum** constant → `ConfigException.BadValue`.
- `Duration` fields parse unit strings (§11), `ConfigMemorySize` fields parse byte-size strings.

---

## 11. Units: durations, periods, and byte sizes

Getters that interpret unit strings:

- `long getDuration(String path, java.util.concurrent.TimeUnit unit)` and
  `java.time.Duration getDuration(String path)`; `List<Long> getDurationList(String path, TimeUnit)`.
- `java.time.Period getPeriod(String path)`; `java.time.temporal.TemporalAmount getTemporal(String)`.
  `getTemporal` first tries to parse the value as a `java.time.Duration`; if that fails it parses it
  as a `java.time.Period`. Because the duration units win first, a **bare `m` is interpreted as
  minutes** (a `Duration`), **not** months — use `mo` to get months (a `Period`). So
  `getTemporal("5m")` → a `Duration` of 5 minutes, while `getTemporal("5mo")` → a `Period` of 5 months.
- `Long getBytes(String path)`, `List<Long> getBytesList(String path)`,
  `ConfigMemorySize getMemorySize(String path)`, `List<ConfigMemorySize> getMemorySizeList(String)`.

**General unit format**: a value may be a bare number (interpreted in the family's default unit) or a
string of `<number><optional whitespace><unit>`.

**Durations** — default unit is **milliseconds**. Unit strings are **case-sensitive lowercase**:

- `ns nano nanos nanosecond nanoseconds`
- `us micro micros microsecond microseconds`
- `ms milli millis millisecond milliseconds`
- `s second seconds`
- `m minute minutes`
- `h hour hours`
- `d day days`

So `1s`, `1 s`, `1second`, `1 seconds`, `1000ms`, `1000000us`, `1000000000ns`, and the bare number
`1000` all equal 1000 ms. `1d` = 86 400 000 ms = 86 400 000 000 000 ns.

**Periods** — default unit is **days**. Case-sensitive lowercase units:

- `d day days`
- `w week weeks`
- `m mo month months`
- `y year years`

So `1y`, `1 year`, `365`, `365d`, and `12m`/`12mo`/`12 months` all denote one year's worth (note a
`Period` keeps its unit granularity: `1y` → 1 year, `365d` → 365 days, `12m` → 12 months).

**Byte sizes** — default unit is **bytes**. The critical rule is **powers of two vs powers of ten**:

- Single bytes: `B b byte bytes`.
- **Powers of ten (1000ⁿ)**: `kB kilobyte kilobytes`, `MB megabyte megabytes`, `GB…`, `TB…`, `PB…`,
  `EB…`, `ZB…`, `YB…`.
- **Powers of two (1024ⁿ)**: `K k Ki KiB kibibyte kibibytes`, `M m Mi MiB mebibyte mebibytes`,
  `G g Gi GiB…`, `T t Ti TiB…`, `P p Pi PiB…`, `E e Ei EiB…`, `Z z Zi ZiB…`, `Y y Yi YiB…`.

Consequences: `512K` = 512 × 1024 = **524288**; `512kB` = 512 × 1000 = **512000**; `1M` = 1048576;
`1MB` = 1000000; `0.5M` = 524288. `1YB` = 10²⁴ bytes (use `getMemorySize().toBytesBigInteger()`).

**Errors**: an unrecognized unit or malformed number, and (for sizes) overflow of a signed 64-bit
value or a negative size, throw `ConfigException.BadValue`.
