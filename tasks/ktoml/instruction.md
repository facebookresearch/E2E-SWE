# Build a TOML library for Kotlin on top of kotlinx-serialization

## Overview

Implement a TOML 1.0 parsing and serialization library for the JVM, written in
Kotlin, that plugs into [`kotlinx-serialization`](https://github.com/Kotlin/kotlinx.serialization).
The library reads TOML text into Kotlin `@Serializable` classes and writes
`@Serializable` objects back out as TOML.

The public entry point is a class `Toml` that implements the
`kotlinx.serialization.StringFormat` interface. A user annotates their data
classes with `@Serializable` and then calls `decodeFromString` / `encodeToString`,
exactly as they would with `kotlinx.serialization.json.Json`.

You are expected to already know the [TOML 1.0 specification](https://toml.io/en/v1.0.0)
(quoting rules, table/array-of-tables grammar, number formats, datetime grammar,
etc.). This document does **not** restate the spec; it specifies the **public API**,
the **library-specific behavior**, and the **configuration surface** your
implementation must provide so that the hidden test suite passes.

## Project layout and build

- Source language: Kotlin, JVM target only.
- All your library code must live as `.kt` source files under `/app/src/`
  (organized into whatever sub-directories you like) and compile to the package
  `com.akuleshov7.ktoml` (and sub-packages). The grader compiles **every `.kt`
  file under `/app/src`** with `kotlinc` directly, against the pre-installed
  `kotlinx-serialization-core` runtime and the serialization compiler plugin,
  then compiles a hidden JUnit 5 test suite against the resulting classes.
  **Do not** add a Gradle/Maven build, and do not rely on any build artifact
  your own `setup.sh` produces — only the sources under `/app/src` and the public
  types/signatures below are used for grading. Keep no `.kt` files under
  `/app/src` other than your implementation (no test files, no `main`).
- You may organize files however you like, but the public types below must keep
  the exact package, names, and signatures given here, because the tests import
  them.

## Public API

### `com.akuleshov7.ktoml.Toml`

```kotlin
package com.akuleshov7.ktoml

public open class Toml(
    inputConfig: TomlInputConfig = TomlInputConfig(),
    outputConfig: TomlOutputConfig = TomlOutputConfig(),
    serializersModule: SerializersModule = EmptySerializersModule(),
) : StringFormat {
    override fun <T> decodeFromString(deserializer: DeserializationStrategy<T>, string: String): T
    override fun <T> encodeToString(serializer: SerializationStrategy<T>, value: T): String

    // Decode only the sub-tree under a fully-qualified table name (e.g. "a.b.c").
    // Throws if the named table is absent.
    public fun <T> partiallyDecodeFromString(
        deserializer: DeserializationStrategy<T>,
        toml: String,
        tomlTableName: String,
        config: TomlInputConfig = /* this instance's input config */
    ): T

    public companion object Default : Toml(TomlInputConfig(), TomlOutputConfig())
}
```

Because `Toml` implements `StringFormat`, the standard reified extension helpers
from `kotlinx.serialization` work and the tests use them:

```kotlin
import kotlinx.serialization.decodeFromString
import kotlinx.serialization.encodeToString

val cfg: Config = Toml.decodeFromString("""...""")     // uses Toml.Default
val text: String = Toml.encodeToString(cfg)
```

`Toml.Default` (the companion `Default`) is an instance configured with the
default `TomlInputConfig()` / `TomlOutputConfig()`.

### Configuration

```kotlin
package com.akuleshov7.ktoml

public data class TomlInputConfig(
    val ignoreUnknownNames: Boolean = false,
    val allowEmptyValues: Boolean = true,
    val allowNullValues: Boolean = true,
    val allowEmptyToml: Boolean = true,
    val allowEscapedQuotesInLiteralStrings: Boolean = true,
    val ignoreDefaultValues: Boolean = false,
)

public data class TomlOutputConfig(
    val indentation: TomlIndentation = TomlIndentation.FOUR_SPACES,
    val allowEscapedQuotesInLiteralStrings: Boolean = true,
    val ignoreNullValues: Boolean = true,
    val ignoreDefaultValues: Boolean = false,
    val explicitTables: Boolean = false,
)

public enum class TomlIndentation(public val value: String) {
    FOUR_SPACES("    "),
    NONE(""),
    TAB("\t"),
    TWO_SPACES("  "),
}
```

Config option meanings:

- `ignoreUnknownNames` — when `false` (default), decoding a key that has no
  matching property throws; when `true`, unknown keys/tables are skipped.
- `allowEmptyValues` — allow a key with no value, e.g. `a = ` or `a = # comment`,
  decoded as `null`.
- `allowNullValues` — allow the literal extension values `null`, `nil`, `NULL`,
  `Nil`, `NIL` (TOML has no native null) to decode as `null`. When `false`,
  encountering such a value during parsing throws.
- `allowEmptyToml` — allow decoding an empty document.
- `allowEscapedQuotesInLiteralStrings` — allow `\'` inside literal (single-quoted)
  strings, which is a ktoml extension over strict TOML.
- `ignoreDefaultValues` — on decode, makes properties that have Kotlin default
  values still required in the input (throws if missing); on encode (the
  `TomlOutputConfig` flag), omit properties whose value equals the default.
- `ignoreNullValues` (output) — when `true` (default), `null`-valued properties
  are omitted from the output.
- `explicitTables` (output) — when `true`, emit parent table headers even when a
  parent only contains sub-tables.

### Exceptions

```kotlin
package com.akuleshov7.ktoml.exceptions

public sealed class TomlDecodingException(message: String) : SerializationException(message)
public sealed class TomlEncodingException(message: String) : SerializationException(message)
```

All decode/parse-time errors your library raises must be subclasses of
`TomlDecodingException`; all encode/write-time errors must be subclasses of
`TomlEncodingException`. The concrete subclasses are an internal detail — the
tests only ever assert on these two public sealed base types (and that they are
`SerializationException`s). Make the concrete subclasses `internal`.

The kinds of decoding errors you must raise (as some subclass of
`TomlDecodingException`) include at least:

- a syntactic parse error (malformed line, e.g. `b = 6 = 7`, an unterminated
  string, an unknown escape sequence, a trailing comma in an inline table);
- an unknown key when `ignoreUnknownNames = false`;
- a missing required property (a non-default, non-nullable property absent from
  the input) — the message must name the missing field as `<name>`;
- a type/range error, e.g. a value `256` decoded into a `UByte`, `128` into a
  `Byte`, or a non-integer into an `Int`;
- a `null` value bound to a non-nullable property.

The kinds of encoding errors (subclass of `TomlEncodingException`) include
emitting a value the writer cannot represent (e.g. a literal string containing a
control character).

## Behavioral contract (what the tests exercise)

### Strings

- Basic strings `"..."`: standard TOML escape handling (`\t \n \r \b \f \\ \"`,
  `\uXXXX`, `\UXXXXXXXX`). An unknown escape (e.g. `\h`, `\x33`) is a parse
  error. An out-of-range unicode escape (`\UFFFFFFFF`, surrogate code points) is
  a parse error.
- Literal strings `'...'`: no escape processing (except the `\'` extension
  governed by `allowEscapedQuotesInLiteralStrings`).
- Multi-line basic `"""..."""` and literal `'''...'''` strings, including:
  trimming of a newline immediately after the opening delimiter; line-ending
  backslash continuation (with whitespace trimming on following lines) in basic
  multi-line strings; `#` not being treated as a comment inside a multi-line
  string; correct handling of up to two adjacent quote characters inside the
  body. A multi-line string that is never closed is a parse error.
- A `#` outside a string starts a comment to end of line. A `#` inside a quoted
  value is literal.

Example:

```kotlin
@Serializable data class Cfg(val a: String, val b: Int)

Toml.decodeFromString<Cfg>(
    "a = \"\"\"first line\nsecond line\"\"\"\nb = 2"
) // Cfg(a = "first line\nsecond line", b = 2)
```

### Numbers

- Integers decode into `Byte`/`Short`/`Int`/`Long` and the unsigned
  `UByte`/`UShort`/`UInt`/`ULong`, with range checking (out-of-range → decoding
  error). A leading `+` is allowed; `_` digit separators are allowed.
- Non-decimal integer literals: hexadecimal `0x...`, octal `0o...`, binary
  `0b...` (each may contain `_` separators) decode to the same integer value as
  their decimal equivalent.
- Floats decode into `Float`/`Double`, including `inf`, `+inf`, `-inf`, `nan`.

### Booleans, null

- `true` / `false` → `Boolean`.
- The null extension values listed under `allowNullValues` decode to `null` for
  nullable properties.

### Datetimes (grammar only)

TOML datetime values (offset date-time `1979-05-27T07:32:00Z` /
`...-07:00`, local date-time `1979-05-27T07:32:00`, local date `1979-05-27`,
local time `07:32:00`, optional fractional seconds, space or `T` separator) must
be **recognized as datetime values by the parser** (i.e. classified as a
datetime token rather than a string, integer, or syntax error). A
syntactically-malformed datetime (e.g. `1979/05/27`, `1979-05-27T07:32:00INVALID`)
is a parse error.

You do **not** need to decode datetimes into any specific date/time Kotlin type
for this task. (Tests assert datetime grammar recognition and rejection of
malformed datetimes; they do not bind datetimes to `kotlinx-datetime` types.)

### Keys

- Bare keys, basic-quoted keys `"..."`, literal-quoted keys `'...'`.
- Dotted keys `a.b.c = 1` create the implied nested tables; quoted segments may
  contain dots (`a."b.c".d`). Whitespace around the dots is allowed
  (`a .  b = 1`).
- Use `@SerialName("...")` on a property to map a TOML key (including keys with
  spaces or dots) to a Kotlin property.

### Tables and arrays of tables

- `[table]` headers, including nested/dotted headers `[a.b.c]`, and sub-tables
  declared in any order (a child table may appear before its parent).
- Arrays of tables `[[products]]`, including nested `[[a.b]]` and mixing with
  plain sub-tables.
- Inline tables `a = { b = 1, c = "x" }`, including nested inline tables and
  dotted keys inside them; an empty inline table `{}` is equivalent to an empty
  `[table]`. A trailing comma inside an inline table is a parse error.
- Arrays `[1, 2, 3]` (trailing comma allowed), nested arrays, arrays of inline
  tables, and arrays containing the null extension value for nullable element
  types.

### Decoding into collections and maps

- `List` / `MutableList` properties decode from TOML arrays (and from arrays of
  tables). An empty array decodes to an empty list.
- `Map<String, V>` properties decode from a table.

### Enums

- A TOML string decodes into a Kotlin `enum` by matching the constant name. An
  unmatched name is a decoding error.

## Encoding contract

`encodeToString` must produce TOML that round-trips back to an equal object via
`decodeFromString` (for the supported value space), and must match these
formatting rules the tests rely on:

- Top-level scalar key/value pairs are emitted first, then `[table]` sections.
  Within an object, properties are emitted in declaration order, except that
  sub-table-valued properties are emitted after scalar/array-valued ones.
- Document framing: the returned string has no trailing newline — the final
  emitted line is not newline-terminated. The blank line that precedes a
  `[table]` section separates it from the content above, so it appears only
  *between* sections; a document whose first emitted line is a table header
  (e.g. a single empty `@Serializable object`) has no leading blank line.
- Table bodies are indented by `TomlOutputConfig.indentation` (default four
  spaces) relative to their header; nested tables use headers like `[a.b]`.
- Strings are emitted as basic strings with proper escaping; an empty object
  `@Serializable object` / empty class emits just its `[header]` with no body.
- Arrays of scalars are emitted inline as `[ 1, 2, 3 ]` (note the spaces inside
  the brackets and after commas).
- `Double.NaN` emits as `nan`, infinities as `inf` / `-inf`.
- With `ignoreNullValues = true` (default) null properties are omitted; with
  `ignoreDefaultValues = true` properties equal to their declared default are
  omitted.
- Annotations affecting output:
  - `@SerialName` sets the emitted key (quoted if it contains spaces/quotes/dots,
    using basic quoting, or literal quoting if it itself contains quotes);
  - `com.akuleshov7.ktoml.annotations.TomlComments(vararg val lines: String, val inline: String = "")`
    emits each of `lines` as a `#` comment line above a pair/table and/or `inline`
    as a trailing `# ...` comment after it;
  - `com.akuleshov7.ktoml.annotations.TomlInteger(representation)` controls the
    integer representation on output (`DECIMAL`, `HEX`, `OCTAL`, `BINARY`,
    `GROUPED` — where `GROUPED` inserts `_` every three digits);
  - `com.akuleshov7.ktoml.annotations.TomlLiteral` emits a string as a literal
    (single-quoted) string;
  - `com.akuleshov7.ktoml.annotations.TomlInlineTable` emits a class as an inline
    table;
  - `com.akuleshov7.ktoml.annotations.TomlMultiline` emits a string/array in
    multi-line form.

```kotlin
package com.akuleshov7.ktoml.writers
public enum class IntegerRepresentation { DECIMAL, HEX, OCTAL, BINARY, GROUPED }
```

Example:

```kotlin
@Serializable data class File(val a: Long = 0, val table: Table = Table())
@Serializable data class Table(val c: String = "value", val d: Boolean = false)

Toml.encodeToString(File())
// a = 0
//
// [table]
//     c = "value"
//     d = false
```
