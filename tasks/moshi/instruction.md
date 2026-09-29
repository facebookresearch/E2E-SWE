# Build a JSON serialization library for the JVM (Moshi core + Kotlin reflection)

## Overview

Implement, in Kotlin for the JVM, a library that **encodes JVM objects to JSON and decodes JSON
into JVM objects**. Users build a `Moshi` instance through a fluent builder, ask it for a
`JsonAdapter<T>` for a specific type, and call `toJson(T)` / `fromJson(String)` on that adapter.
The library also exposes a low-level streaming reader and writer for callers that want to walk
JSON tokens directly instead of going through an adapter.

This library is the core `moshi` module together with the reflection-based `moshi-kotlin`
module (`KotlinJsonAdapterFactory`). It follows a factory-pipeline JSON serializer design in
package `com.squareup.moshi`, with the Kotlin reflection factory in
`com.squareup.moshi.kotlin.reflect`. This document specifies the **public API**, the
**observable contracts** callers rely on, and the **build layout**. It is a product spec, not
a line-by-line blueprint — how you satisfy the contracts is up to you as long as the observable
behavior matches.

## Project layout and build

- Source language: **Kotlin, JVM target only.**
- All library code must live as `.kt` files under `/app/src/` (any sub-directory structure)
  in packages **`com.squareup.moshi`**, **`com.squareup.moshi.internal`** (helpers you keep
  package-internal), and **`com.squareup.moshi.kotlin.reflect`** (the Kotlin reflection factory).
  The build compiles **every `.kt` file under `/app/src`** with `kotlinc` directly (offline),
  roughly:

  ```bash
  KOTLIN_LIB=/root/.sdkman/candidates/kotlin/current/lib
  kotlinc -jvm-default=enable -opt-in=kotlin.contracts.ExperimentalContracts \
    -cp "/opt/libs/okio-jvm-3.17.0.jar:$KOTLIN_LIB/kotlin-reflect.jar:/opt/libs/jsr305-3.0.2.jar:$KOTLIN_LIB/annotations-13.0.jar:$KOTLIN_LIB/kotlin-metadata-jvm.jar" \
    /app/src -d /app/moshi.jar
  ```

  The resulting jar is what callers depend on. **Do not** add a Gradle/Maven build; only the
  sources under `/app/src` and the public API surface documented below are what consumers see.
- **The entire `/app/src` must compile cleanly** in that single `kotlinc` invocation. One
  unresolved reference, type mismatch, or visibility error anywhere breaks the whole build and
  leaves consumers with a library they can't link against.
- **Callers link against the compiled jar and expect the exact signatures documented below** —
  including nullability (`T` vs `T?`), variance, and visibility. A public class or method whose
  signature differs from what's specified is an API break that stops consumers from compiling
  against the library. Before finishing, run the `kotlinc` command above and confirm clean
  exit; then grep `/app/src` for `abstract fun toJson` / `abstract fun fromJson` and verify
  they match the signatures in the `JsonAdapter<T>` section.
- The environment is **offline**: no dependency may be downloaded. Available on the classpath
  (pre-installed at the paths above):
  - **Okio 3.17.0** (`com.squareup.okio:okio-jvm`) — `Buffer`, `BufferedSource`, `BufferedSink`.
    Use it for streaming reader / writer I/O.
  - **kotlin-reflect** — needed by the `KotlinJsonAdapterFactory` to inspect Kotlin classes.
  - **kotlin-metadata-jvm** — parses the `@Metadata` annotation Kotlin puts on compiled classes.
  - **jsr305** (`javax.annotation.CheckReturnValue`) — a return-value hint that may be applied
    to several methods. It is compile-only; you may keep or omit the annotations.
  - **JetBrains annotations 13.0** (`org.intellij.lang.annotations.Language`) — used on a few
    method parameters to hint IntelliJ that a `String` is JSON. Compile-only.
- Keep no `main` function and no test files under `/app/src`.
- The public types below must keep the **exact package, names, and signatures** given here —
  they are the library's ABI.

## Core types

### `Moshi` (package `com.squareup.moshi`)

The user's entry point. Users build one with `Moshi.Builder().build()` (or with factories added
first) and then call `adapter` on it to get a typed `JsonAdapter<T>`.

Contract:

- `class Moshi` with a `companion object` or member. Adapter lookup APIs:
  - `fun <T> adapter(type: java.lang.reflect.Type): JsonAdapter<T>` — the main entry.
  - Convenience overloads may exist for `Class<T>` and for callers that pass annotations.
- **Adapter cache.** The second call to `adapter` for the same `(type, annotations)` key MUST
  return the same `JsonAdapter<T>` instance (`===`) that the first call returned. Adapters are
  expensive to build; users rely on identity as proof the cache is working.
- **Reentrant lookups.** A `JsonAdapter` may be requested during construction of another
  `JsonAdapter` (e.g. adapting `class Node(val name: String, val children: List<Node>)` — building
  the `Node` adapter needs the `List<Node>` adapter, which needs `Node` again). The lookup
  must terminate correctly, produce a working adapter for the recursive type, and only cache
  the final adapter once the outermost lookup succeeds. Failing lookups must not pollute the
  cache with partial adapters.

`Moshi.Builder` — mutable builder. Order matters (see "Factory pipeline" below). Must expose:

- `fun add(factory: JsonAdapter.Factory): Builder` — registers a factory.
- `fun <T> add(type: java.lang.reflect.Type, jsonAdapter: JsonAdapter<T>): Builder` — shorthand
  for a single-type factory.
- `fun <T> add(type: java.lang.reflect.Type, annotation: Class<out Annotation>, jsonAdapter: JsonAdapter<T>): Builder`
  — shorthand for a qualifier-annotated single-type factory.
- `fun add(adapter: Any): Builder` — the argument is an "adapter methods" object whose `@ToJson`
  and `@FromJson` methods are reflected out into a `JsonAdapter.Factory`. See "Adapter methods
  objects" below.
- `fun build(): Moshi`.

### `JsonAdapter<T>` (package `com.squareup.moshi`)

`abstract class JsonAdapter<T>` — a bidirectional codec for a single type. **The exact Kotlin
signatures below are load-bearing** — external callers subclass `JsonAdapter<Something>` and
override these methods. Abstract signatures that don't match exactly (e.g. making `value`
nullable as `value: T?`) break every downstream subclass.

```kotlin
abstract class JsonAdapter<T> {
  // Low-level abstract methods — callers override THESE exact signatures.
  //   fromJson: return type is `T`. Kotlin's unbounded T
  //             defaults to nullable (T : Any?), so implementations may still return null
  //             when reading JSON null; a wrapper adapter (.nullSafe()) makes that explicit.
  //             Do NOT declare it as `T?` — Kotlin treats T? and T as distinct types in
  //             override resolution, so any downstream subclass that overrides `T` while
  //             this abstract says `T?` will fail to compile.
  //   toJson:   takes value: T. Null handling for writing is delegated to the .nullSafe()
  //             wrapper, not the abstract method.
  abstract fun fromJson(reader: JsonReader): T
  abstract fun toJson(writer: JsonWriter, value: T)

  // String-based convenience overloads (fromJson may return null when the
  // input was JSON null, so this overload is nullable-return; toJson takes non-null T).
  open fun fromJson(string: String): T?
  open fun toJson(value: T): String

  // Wrappers — each returns a NEW adapter, `this` is untouched. Signatures matter for chaining.
  fun nullSafe(): JsonAdapter<T?>
  fun nonNull(): JsonAdapter<T>
  fun serializeNulls(): JsonAdapter<T>
  fun indent(indent: String): JsonAdapter<T>
  fun lenient(): JsonAdapter<T>          // returned adapter reads/writes in lenient mode

  // Factory interface — pluggable extension mechanism.
  fun interface Factory {
    fun create(type: java.lang.reflect.Type,
               annotations: Set<out Annotation>,
               moshi: Moshi): JsonAdapter<*>?
  }
}
```

Contract details for the wrappers:

- `nullSafe()` — reads a JSON `null` as Kotlin `null`, writes Kotlin `null` as JSON `null`.
  Returned adapter has type `JsonAdapter<T?>` so callers can pass and receive nulls.
- `nonNull()` — reading JSON `null` throws `JsonDataException`; the delegate is only called for
  non-null values. Note there is no way to *write* Kotlin null through the low-level
  `toJson(writer, value: T)` because `value` is non-null at the type level — that is precisely
  why the abstract signature uses `T` and not `T?`.
- `serializeNulls()` — makes the writer emit `"field":null` for null values instead of skipping
  the field. Callers use this when they want an explicit `"nickname":null` in the output rather
  than omitting the field entirely.
- `indent(indent)` — returned adapter pretty-prints. `[1, 2]` with `indent = "  "` becomes
  `[\n  1,\n  2\n]`.

`JsonAdapter.Factory.create` returning `null` means "not my type — try the next factory".

### `JsonReader` (package `com.squareup.moshi`)

`abstract class JsonReader` — a streaming pull-parser over UTF-8 or in-memory JSON. Contract:

- Construction: `companion object` method `fun of(source: okio.BufferedSource): JsonReader`.
  Callers typically pass an `okio.Buffer().writeUtf8(json)` (which IS a `BufferedSource`).
- Navigation (all `@Throws(IOException::class)` in practice):
  - `fun beginObject()`, `fun endObject()`
  - `fun beginArray()`, `fun endArray()`
  - `fun hasNext(): Boolean`
  - `fun nextName(): String`, `fun skipName()`
  - `fun nextString(): String`, `fun nextInt(): Int`, `fun nextLong(): Long`,
    `fun nextDouble(): Double`, `fun nextBoolean(): Boolean`, `fun nextNull(): Nothing?`
  - `fun peek(): Token` (an enum of the next lexical class)
  - `fun skipValue()` — skip the current value and any children.
  - `fun peekJson(): JsonReader` — returns an **independent** reader positioned at the current
    location. Reading from the peek must not advance the original.
  - `fun close()`
- **`val path: String`** — a JSONPath-style location the reader is currently at, e.g. `$` at
  the document root, `$.foo` inside object field `foo`, `$.foo[2]` at index 2 inside `foo`.
  Callers use this during a parse to report the exact location of an error or diagnostic.
  Callers from Java see this as `getPath()`. **Must be a Kotlin `val`/property**, not a method
  named `getPath()` — callers access it as `reader.path`.
- Mode flags (mutable **Kotlin properties**, exactly named — callers access them as
  properties like `reader.lenient = true`, NOT via method-call syntax like
  `reader.setLenient(true)`, and NOT `is`-prefixed forms like `reader.isLenient = true`):
  - `var lenient: Boolean` (default `false`). When `true`, the reader accepts JSON5-ish input:
    unquoted object keys, single-quoted strings, comments, etc.
  - `var failOnUnknown: Boolean` (default `false`). When `true`, `skipValue()` throws
    `JsonDataException` instead of silently skipping. Callers use it to enforce strict schemas
    where any object key they didn't expect must be surfaced as an error.
  - `var serializeNulls`, `var indent`, `var promoteValueToName` may also be present on the
    writer / reader as appropriate.
- **`JsonReader.Options`.** An immutable, precompiled set of expected object-key names for the
  generated-code path:

  ```
  class Options {
    companion object {
      fun of(vararg strings: String): Options
    }
  }
  ```

  Reader methods that consume it:

  - `fun selectName(options: Options): Int` — while positioned at a name, returns the index of the
    matching name in `options`, or `-1` if the current name is not in the set. On a hit the reader
    also consumes the name (subsequent call is `nextInt`/`nextString`/etc. for the value). On `-1`
    the reader does NOT consume the name; the caller is expected to call `skipName()` +
    `skipValue()` to drop the pair.
  - `fun selectString(options: Options): Int` — the value-side symmetric to `selectName`. While
    positioned at a string VALUE, returns the index of the matching value in `options`, or `-1`
    if the current string is not in the set. On a hit the reader consumes the string; on `-1` it
    does NOT consume (the caller must call `nextString`/`skipValue`). Both methods have the same
    hit/miss contract.

  Rationale: `selectName`/`selectString` let generated code dispatch object keys / enum-like
  values with an int switch instead of string compares, without materializing the string.

- **Non-String map keys via key/value promotion.** These pair of reader/writer methods enable
  `Map<K, V>` for K that isn't `String` (e.g. `Map<Int, String>`) — the JSON object's keys are
  still strings on the wire, but the reader treats each key as a value to parse into K:
  - `JsonReader.promoteNameToValue()` — call inside a `while (reader.hasNext())` object loop,
    right after `beginObject()`, so the very next `nextInt()` / `nextString()` reads the object
    KEY as if it were a value. The built-in `MapJsonAdapter` uses this to delegate key decoding
    to the K-typed adapter.
  - `JsonWriter.promoteValueToName()` — symmetric for writing: makes the next `value(...)` call
    emit its argument as the object KEY instead of a value.
  Concretely: the built-in Map factory MUST accept any `Map<K, V>` where both K and V have
  adapters (not just `Map<String, V>`) — e.g. a JSON object like
  `{"1":"one","2":"two"}` must decode into a `Map<Int, String>` where the object's string keys
  have been parsed into `Int` via the key adapter.

### `JsonWriter` (package `com.squareup.moshi`)

`abstract class JsonWriter` — a streaming encoder to UTF-8. Contract:

- Construction: `companion object` method `fun of(sink: okio.BufferedSink): JsonWriter`.
- Navigation (all IOException-throwing):
  - `fun beginObject(): JsonWriter`, `fun endObject(): JsonWriter`
  - `fun beginArray(): JsonWriter`, `fun endArray(): JsonWriter`
  - `fun name(name: String): JsonWriter` — the next `value(...)` call assigns to this key.
  - `fun value(...)` overloads: `String?`, `Boolean?`, `Long`, `Int`, `Double`, `Number?`, ...
  - `fun nullValue(): JsonWriter`.
  - `fun close()`.
- Chained method calls MUST be supported (each returns `this`), so tests write
  `w.name("k").value(1)` etc.
- Mode flags: `var isLenient`, `var serializeNulls`, `var indent`, similar to reader.
- Compact output form is the default. Given `beginObject(); name("count"); value(2);
  name("payload"); beginObject(); name("leaf"); value("x"); endObject(); endObject()` the
  writer must emit exactly `{"count":2,"payload":{"leaf":"x"}}` (no whitespace).
- **State machine invariants**:
  - `endObject()` at document root (no matching `beginObject()`) throws `IllegalStateException`.
  - Inside an object context, `value(...)` with no preceding `name(...)` throws
    `IllegalStateException` (objects require key-value pairs, not bare values).
- Corresponding invariant on the READER: `beginObject()` followed by `endArray()` (mismatched
  container close) throws — either `JsonEncodingException` or `IllegalStateException` is
  acceptable, both signal a container-shape violation.

### `Types` (package `com.squareup.moshi`)

Static helpers for building `java.lang.reflect.Type` instances that callers use to name generic
types that lack a `Class<T>` (e.g. `List<String>`, `Map<String, List<Int>>`):

- `fun newParameterizedType(rawType: Type, vararg typeArguments: Type): ParameterizedType`
- `fun arrayOf(componentType: Type): GenericArrayType`
- `fun subtypeOf(bound: Type): WildcardType` — returns a `WildcardType` representing
  `? extends bound`, with `upperBounds = [bound]` and `lowerBounds = []`. Used to build
  `List<? extends Number>`-style types.
- `fun supertypeOf(bound: Type): WildcardType` — returns a `WildcardType` representing
  `? super bound`, with `lowerBounds = [bound]` and `upperBounds = [Object.class]`
  (the default upper bound for a lower-bounded wildcard).
- Plus a `Type.rawType` extension property that
  reduces any `Type` to its raw `Class<*>`.
- Plus `Types.getRawType(type: Type): Class<*>` and helpers for annotation walking
  (`nextAnnotations`) as needed by the factories.

### `KotlinJsonAdapterFactory` (package `com.squareup.moshi.kotlin.reflect`)

`class KotlinJsonAdapterFactory : JsonAdapter.Factory` — a factory that supplies an adapter for
Kotlin classes by reflecting on their primary constructor via `kotlin-reflect` +
`kotlin-metadata-jvm`. Users construct it and add it to the builder:

```kotlin
val moshi = Moshi.Builder().add(KotlinJsonAdapterFactory()).build()
```

Contract on the adapter it produces:

- Uses the target class's primary constructor and its parameter list to decide which JSON keys
  to consume and how to assemble the instance.
- In addition to the primary-constructor parameters, also binds mutable (`var`) properties
  declared in the class body (outside the primary constructor): on write it emits them, and on
  read it assigns them through their setters after the instance is constructed. This means a
  Kotlin class that holds its state in body `var` properties — e.g. an empty (no-arg) primary
  constructor plus `var name: String` / `var children: List<Node>` in the body — still
  round-trips its data. Read-only non-constructor `val` properties (no setter) are not bound.
- Honors `@field:Json(name = "...")` — reads/writes the JSON key given by the annotation instead
  of the Kotlin property name.
- Honors `@field:Json(ignore = true)` — the property is invisible on both write and read.
- Distinguishes constructor parameters with defaults (may be absent in JSON — use the default)
  from mandatory ones (JSON key absent → throw `JsonDataException`). For example, a class
  `class ServerConfig(val host: String, val port: Int = 8080)` decoded from
  `{"host":"x"}` must yield `port = 8080`; decoded from `{}` must throw `JsonDataException`
  because `host` has no default.
- Honors `@JsonQualifier`-marked annotations on constructor parameters when looking up the
  per-field adapter. See "Qualifiers" below.
- Refuses local classes, inner classes, anonymous classes, and object declarations, throwing an
  informative exception at adapter-creation time.

**Also required:** the core `ClassJsonAdapter` (the reflection factory for **Java** classes)
must **refuse Kotlin classes** — throw `IllegalArgumentException` with a message pointing the
user at `KotlinJsonAdapterFactory`. This is what makes `KotlinJsonAdapterFactory` load-bearing;
without the refusal, Kotlin classes would silently mis-behave under the Java reflection path.

## Factory pipeline

Moshi resolves an adapter by walking a **prioritized list of `JsonAdapter.Factory`** and picking
the first one that returns non-null. The order, from highest to lowest priority, is:

1. Factories the user added via `Moshi.Builder.add(...)`, in the order they were added.
2. The **built-in** factories: standard-adapter factory (primitives, boxed types, String,
   enums), collection factory (`List`, `Set`), map factory (`Map<String, V>`), array factory, and the
   **Java-class reflection factory** (`ClassJsonAdapter`) at the end.

Concrete consequences of this ordering:

- Registering two factories `LiteralA` then `LiteralB` for the same type means `LiteralA`
  wins (first-added wins for a given type).
- A user-registered factory for `String` beats the built-in String adapter, so a caller can
  register an `UppercaseStringAdapter` and expect all `String` serialization to go through it.

## Adapter methods objects

`Moshi.Builder.add(adapter: Any)` inspects `adapter`'s methods for two annotations and turns the
result into a factory:

- `@ToJson` on a method whose parameters are the value to serialize (optionally with the writer)
  and whose return is either the JSON string or a "pre-serialized" intermediate value.
- `@FromJson` on a method whose parameters are the intermediate value (or JSON reader) and whose
  return is the deserialized value.

Two supported call shapes:

1. **Pre-serialized intermediate.** The method takes a plain value (e.g. `List<Int>`) and returns
   the domain type (e.g. `Point`), and its pair returns the intermediate from the domain type.
   Moshi delegates the actual reader/writer work to the built-in adapter for the intermediate.

   ```kotlin
   class PointTupleAdapter {
     @ToJson fun toJson(p: Point): List<Int> = listOf(p.x, p.y)
     @FromJson fun fromJson(list: List<Int>): Point = Point(list[0], list[1])
   }
   ```

2. **Qualifier-annotated primitive.** A `@JsonQualifier` annotation attached to the value
   parameter (via `@Hex value: Int`) tells Moshi to only apply this adapter when the requesting
   field carries the same qualifier. See "Qualifiers".

## Annotations

All in package `com.squareup.moshi`.

- `@Json(name: String = "\u0000", ignore: Boolean = false)` — customises a field's JSON
  handling. Applied on the field via `@field:Json(name = "user_name")` (rename JSON key) or
  `@field:Json(ignore = true)` (field is invisible to both write and read paths — never emitted,
  never consumed; if a value must be produced on read the Kotlin constructor default is used,
  and if the parameter has no default the field cannot be reconstructed).
- `@JsonClass(generateAdapter: Boolean, generator: String = "", inline: Boolean = false)` — a
  marker annotation intended for a separate compile-time codegen module. This library only
  needs to declare the annotation; no codegen behavior is required at runtime, because Kotlin
  classes are served by `KotlinJsonAdapterFactory` instead.
- `@JsonQualifier` — meta-annotation. A qualifier is a user-defined annotation `@interface Foo`
  itself annotated with `@JsonQualifier`. Presence of the qualifier on a field routes adapter
  lookup to a factory registered for `(type, Foo::class)` rather than plain `(type)`.
- `@ToJson`, `@FromJson` — see "Adapter methods objects" above.

## Qualifiers

Rule: `Moshi.adapter(type)` (no annotations) skips any factory whose registration carries
qualifier annotations. `Moshi.adapter(type, qualifierAnnotation)` (or a `KotlinJsonAdapterFactory`
lookup for a field whose declared type carries qualifier annotations) uses those annotations as
part of the cache key and dispatches to the factory registered for that same `(type, annotation)`
pair.

Example:

```kotlin
@JsonQualifier @Retention(RUNTIME) annotation class Hex
class HexAdapter {
  @ToJson fun toJson(@Hex v: Int) = "0x" + v.toString(16)
  @FromJson @Hex fun fromJson(s: String) = s.removePrefix("0x").toInt(16)
}
class Widget(val id: Int, @field:Hex val color: Int)

val m = Moshi.Builder().add(HexAdapter()).add(KotlinJsonAdapterFactory()).build()
// id -> decimal (built-in), color -> hex (HexAdapter):
m.adapter(Widget::class.java).toJson(Widget(100, 0x123ABC))
// -> {"id":100,"color":"0x123abc"}

// A plain Int adapter (no @Hex) ignores HexAdapter entirely:
m.adapter(Int::class.javaObjectType).toJson(255)  // "255"
```

## Built-in adapters — output/input contracts

- **Primitives** (Int/Long/Double/Float/Boolean/String and their boxed forms): JSON canonical
  form. `42` ↔ `42`, `true` ↔ `true`, a `Double` like `2.71` round-trips as `2.71`,
  `Long.MAX_VALUE` renders as `9223372036854775807`, `"a"` ↔ `"a"`. Numeric parsing accepts
  strict JSON forms (no leading/trailing whitespace inside the numeric token).
  Additional numeric contracts:
  - **Scientific notation → Long.** `reader.nextLong()` must accept scientific notation for
    integer values that fit in Long — e.g. `3e9` must decode to `3_000_000_000L`. Naïve
    "digits-only" integer parsers that reject the `e` will fail this.
  - **Long overflow → `JsonDataException`.** Reading a decimal integer greater than
    `Long.MAX_VALUE` (any value above `9223372036854775807`) via `nextLong()` must throw
    `JsonDataException`
    (value-level shape violation). Silently wrapping around or truncating is wrong.
  - **Negative zero preservation.** `-0.0` has a different IEEE 754 bit pattern than `0.0` (sign
    bit set). Round-tripping a `Double` value of `-0.0` must preserve the sign bit — the writer
    emits `-0.0` (or equivalent) and the reader decodes back to a Double whose raw bits equal
    `Double.doubleToRawLongBits(-0.0)`.
- **String escaping.** The writer escapes at minimum: `"` → `\"`, `\` → `\\`, control chars
  (`< U+0020`) as `\u00xx`, `\n` → `\n` (backslash-n), `\r`, `\t`. Round-tripping any string
  must yield an equal string. Non-ASCII (e.g. `é`) is preserved either as UTF-8 or as `\uXXXX`
  — both round-trip.
- **Enum** — round-trips as the JSON string equal to `Enum.name`.
- **`List<T>`** — a JSON array whose element positions correspond to list positions. Ordering
  preserved.
- **`Map<String, V>`** — a JSON object whose keys are the map's keys. **Iteration order of the
  input map is preserved in the output JSON.** Callers pass `LinkedHashMap` (or Kotlin's
  `linkedMapOf`) and expect the JSON to reflect that order.
- **`Array<T>`** — same shape as `List<T>` (JSON array).
- **`Set<T>`** — a JSON array. On READ, uses `LinkedHashSet` semantics: duplicate elements
  are deduplicated by `equals`, iteration order is first-seen insertion order. So JSON
  e.g. `["p","q","p","r","q"]` decodes to a Set of 3 elements: `p, q, r` (in that order).
- **Composite generics** work naturally: `Map<String, List<Int>>` and `List<Map<String, String>>`
  are constructible via nested `Types.newParameterizedType`.

## Exceptions

- `class JsonDataException : RuntimeException` (or subclass thereof; must be a `RuntimeException`
  so tests can `assertThrows`). Signals **bad-shape data at the value level** — e.g. reading a
  JSON string where an `Int` is expected. Distinct from a plain `IOException` (which signals
  low-level I/O problems).
- `class JsonEncodingException` — signals malformed JSON at the **token** level (unterminated
  input, missing brace, invalid escape, trailing comma outside lenient mode, etc.). MUST extend
  `java.io.IOException`. Callers catch it as `IOException`, so the concrete
  hierarchy `JsonEncodingException : IOException` is required — declaring it as a
  `RuntimeException` subclass would break every `catch (IOException)` block in caller code.

Concrete contract examples:

- Reading a JSON string value (e.g. `"not-a-number"`) as `Int` throws `JsonDataException`
  (bad shape at value level).
- Reading a truncated stream (e.g. an object opener followed by a partial member and a trailing
  comma with no closing brace: `{"foo":42,`) throws an `IOException` (token-level error). The
  concrete exception may be `JsonEncodingException` — either satisfies the `IOException`
  supertype callers expect.

## Streaming reader/writer — worked examples

Reader:

```kotlin
val reader = JsonReader.of(Buffer().writeUtf8("""{"city":"Portland","population":650}"""))
reader.beginObject()
reader.nextName()   // "city"
reader.nextString() // "Portland"
reader.nextName()   // "population"
reader.nextInt()    // 650
reader.endObject()
```

Writer (chained calls, compact form):

```kotlin
val buffer = Buffer()
JsonWriter.of(buffer).use { w ->
  w.beginObject()
  w.name("count").value(2)
  w.name("payload").beginObject()
  w.name("leaf").value("x")
  w.endObject()
  w.endObject()
}
buffer.readUtf8() == """{"count":2,"payload":{"leaf":"x"}}"""
```

Pretty-printing (via `JsonAdapter.indent("  ")`):

```
[
  1,
  2
]
```

`peekJson`:

```kotlin
val reader = JsonReader.of(Buffer().writeUtf8("""{"port":8443}"""))
reader.beginObject(); reader.nextName()  // positioned before the value
val peek = reader.peekJson()
peek.nextInt()  // 8443; peek advances
reader.nextInt() // 8443; original also still reads it — peek did NOT advance the original
```

