/*
 * Hidden test suite for the moshi (Kotlin) WRG task. The agent never sees this file — it is only
 * uploaded into the grading container. Each test exercises a distinct behavioral contract of
 * moshi's public API (per README §5.1: one distinct behavior per test, equal-weighted).
 *
 * Testing surface: the public API of `com.squareup.moshi` — Moshi.Builder, JsonAdapter,
 * JsonReader, JsonWriter, Types, @JsonClass, @Json, @JsonQualifier, @ToJson, @FromJson,
 * JsonDataException. No internal .internal APIs are imported directly — those are exercised
 * indirectly through the public surface (per §5.2 "match the spec to the surface you test").
 */
package wrg.hidden

import com.squareup.moshi.FromJson
import com.squareup.moshi.Json
import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.JsonDataException
import com.squareup.moshi.JsonQualifier
import com.squareup.moshi.JsonReader
import com.squareup.moshi.JsonWriter
import com.squareup.moshi.Moshi
import com.squareup.moshi.ToJson
import com.squareup.moshi.Types
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import java.io.IOException
import java.lang.reflect.Type
import okio.Buffer
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertNotNull
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertSame
import org.junit.jupiter.api.Assertions.assertThrows
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

// ---------- Test data classes ----------
// Constructor-arg `val` fields work because moshi's ClassJsonAdapter falls back to
// sun.misc.Unsafe.allocateInstance() (no constructor call) then sets fields reflectively.

private class Person(val name: String = "", val age: Int = 0)
private class Address(val street: String = "", val zip: String = "")
private class Employee(val person: Person = Person(), val address: Address = Address())
private class NullablePerson(val name: String = "", val nickname: String? = null)
private class RenamedPerson(
  @field:Json(name = "user_name") val userName: String = "",
  val age: Int = 0,
)
private class Point(val x: Int = 0, val y: Int = 0)
private enum class Color { RED, GREEN, BLUE }
private class Enclave(val color: Color = Color.RED, val size: Int = 0)
private class Node {
  var name: String = ""
  var children: List<Node> = emptyList()
}

private class Widget(val id: Int = 0, @field:Hex val color: Int = 0)

@JsonQualifier
@Retention(AnnotationRetention.RUNTIME)
@Target(
  AnnotationTarget.FIELD,
  AnnotationTarget.VALUE_PARAMETER,
  AnnotationTarget.FUNCTION,
  AnnotationTarget.PROPERTY_GETTER,
  AnnotationTarget.TYPE,  // needed for `List<@Hex Int>` in test41
)
private annotation class Hex

// Adapter methods object exercised by test14 + test15 (registered via Moshi.Builder.add(any)).
private class HexAdapter {
  @ToJson fun toJson(@Hex value: Int): String = "0x" + value.toString(16)
  @FromJson @Hex fun fromJson(value: String): Int = value.removePrefix("0x").toInt(16)
}

// A SECOND, distinct qualifier + adapter (test15): dispatch must key on the qualifier TYPE, so a
// @Reversed String field resolves to ReverseAdapter and not to the @Hex Int adapter.
@JsonQualifier
@Retention(AnnotationRetention.RUNTIME)
@Target(
  AnnotationTarget.FIELD,
  AnnotationTarget.VALUE_PARAMETER,
  AnnotationTarget.FUNCTION,
  AnnotationTarget.PROPERTY_GETTER,
)
private annotation class Reversed

private class ReverseAdapter {
  @ToJson fun toJson(@Reversed value: String): String = value.reversed()
  @FromJson @Reversed fun fromJson(value: String): String = value.reversed()
}

// A class carrying two DIFFERENTLY-qualified sibling fields (test15).
private class Tagged(@field:Hex val code: Int = 0, @field:Reversed val label: String = "")

// Adapter methods for test 13 (POJO ↔ tuple form).
private class PointTupleAdapter {
  @ToJson fun toJson(p: Point): List<Int> = listOf(p.x, p.y)
  @FromJson fun fromJson(list: List<Int>): Point = Point(list[0], list[1])
}

/** Full-class custom adapter used by test 11. */
private class UppercaseStringAdapter : JsonAdapter<String>() {
  override fun fromJson(reader: JsonReader): String = reader.nextString().lowercase()
  override fun toJson(writer: JsonWriter, value: String) {
    writer.value(value.uppercase())
  }
}

/** Priority-marker adapters for test 12 (factory registration order). */
private class ATag(val v: String = "")
private class LiteralA : JsonAdapter<ATag>() {
  override fun fromJson(reader: JsonReader): ATag {
    reader.skipValue(); return ATag("A")
  }
  override fun toJson(writer: JsonWriter, value: ATag) { writer.value("A") }
}
private class LiteralB : JsonAdapter<ATag>() {
  override fun fromJson(reader: JsonReader): ATag {
    reader.skipValue(); return ATag("B")
  }
  override fun toJson(writer: JsonWriter, value: ATag) { writer.value("B") }
}

// ---------- Test class ----------

class MoshiTest {

  // Every Moshi.Builder in the test suite installs KotlinJsonAdapterFactory. moshi core's
  // ClassJsonAdapter refuses to reflect on Kotlin classes (throws IllegalArgumentException) — the
  // standard Kotlin-side entry point is the reflection factory from moshi-kotlin. This mirrors
  // how a real user of moshi + Kotlin builds a Moshi instance.
  private fun moshi(): Moshi = Moshi.Builder().add(KotlinJsonAdapterFactory()).build()

  // A. Reflection-based ClassJsonAdapter round-trips ----------------------------------

  @Test
  fun test01_simpleDataClassRoundTrip() {
    val adapter = moshi().adapter(Person::class.java)
    val json = adapter.toJson(Person("Alice", 30))
    assertEquals("""{"name":"Alice","age":30}""", json)
    val decoded = adapter.fromJson(json)!!
    assertEquals("Alice", decoded.name)
    assertEquals(30, decoded.age)
  }

  @Test
  fun test02_nestedClassRoundTrip() {
    val adapter = moshi().adapter(Employee::class.java)
    val input = Employee(Person("Bob", 25), Address("101 Main", "94103"))
    val json = adapter.toJson(input)
    val decoded = adapter.fromJson(json)!!
    assertEquals("Bob", decoded.person.name)
    assertEquals(25, decoded.person.age)
    assertEquals("101 Main", decoded.address.street)
    assertEquals("94103", decoded.address.zip)
  }

  @Test
  fun test03_nullableFieldRoundTrip() {
    val adapter = moshi().adapter(NullablePerson::class.java).serializeNulls()
    val json1 = adapter.toJson(NullablePerson("Carol", null))
    assertEquals("""{"name":"Carol","nickname":null}""", json1)
    val decoded1 = adapter.fromJson(json1)!!
    assertEquals("Carol", decoded1.name)
    assertNull(decoded1.nickname)

    val json2 = adapter.toJson(NullablePerson("Dan", "Danny"))
    assertEquals("""{"name":"Dan","nickname":"Danny"}""", json2)
    val decoded2 = adapter.fromJson(json2)!!
    assertEquals("Danny", decoded2.nickname)
  }

  @Test
  fun test04_jsonNameRenamedField() {
    val adapter = moshi().adapter(RenamedPerson::class.java)
    val json = adapter.toJson(RenamedPerson("erin_z", 22))
    assertEquals("""{"user_name":"erin_z","age":22}""", json)
    val decoded = adapter.fromJson(json)!!
    assertEquals("erin_z", decoded.userName)
    assertEquals(22, decoded.age)
  }

  // B. Built-in primitive adapters ----------------------------------------------------

  @Test
  fun test05_primitiveAdapters() {
    val m = moshi()
    assertEquals("42", m.adapter(Int::class.javaObjectType).toJson(42))
    assertEquals(42, m.adapter(Int::class.javaObjectType).fromJson("42"))
    assertEquals("9223372036854775807", m.adapter(Long::class.javaObjectType).toJson(Long.MAX_VALUE))
    assertEquals(Long.MAX_VALUE, m.adapter(Long::class.javaObjectType).fromJson("9223372036854775807"))
    assertEquals("3.14", m.adapter(Double::class.javaObjectType).toJson(3.14))
    assertEquals(3.14, m.adapter(Double::class.javaObjectType).fromJson("3.14"))
    assertEquals("true", m.adapter(Boolean::class.javaObjectType).toJson(true))
    assertEquals(true, m.adapter(Boolean::class.javaObjectType).fromJson("true"))
  }

  @Test
  fun test06_stringSpecialChars() {
    val adapter = moshi().adapter(String::class.java)
    val s = "quote\"backslash\\newline\ntab\tunicodeé"
    val json = adapter.toJson(s)
    assertEquals(s, adapter.fromJson(json))
    // Verify JSON-escape actually escaped the special chars, not passed them through raw:
    assertTrue(json.contains("\\\""), "quote should be escaped: $json")
    assertTrue(json.contains("\\\\"), "backslash should be escaped: $json")
  }

  @Test
  fun test07_enumAdapter() {
    val adapter = moshi().adapter(Color::class.java)
    assertEquals("\"GREEN\"", adapter.toJson(Color.GREEN))
    assertEquals(Color.BLUE, adapter.fromJson("\"BLUE\""))
    // Enum inside a class round-trips:
    val enclaveAdapter = moshi().adapter(Enclave::class.java)
    val json = enclaveAdapter.toJson(Enclave(Color.RED, 7))
    assertEquals("""{"color":"RED","size":7}""", json)
    assertEquals(Color.RED, enclaveAdapter.fromJson(json)!!.color)
  }

  // C. Collections / maps / arrays ----------------------------------------------------

  @Test
  fun test08_listAdapterViaTypes() {
    val listType: Type = Types.newParameterizedType(List::class.java, String::class.java)
    val adapter = moshi().adapter<List<String>>(listType)
    val json = adapter.toJson(listOf("a", "b", "c"))
    assertEquals("""["a","b","c"]""", json)
    assertEquals(listOf("a", "b", "c"), adapter.fromJson(json))
  }

  @Test
  fun test09_mapAdapter() {
    val mapType: Type = Types.newParameterizedType(
      Map::class.java, String::class.java, Int::class.javaObjectType
    )
    val adapter = moshi().adapter<Map<String, Int>>(mapType)
    val json = adapter.toJson(linkedMapOf("a" to 1, "b" to 2))
    assertEquals("""{"a":1,"b":2}""", json)
    val decoded = adapter.fromJson(json)!!
    assertEquals(1, decoded["a"])
    assertEquals(2, decoded["b"])
  }

  @Test
  fun test10_arrayAdapter() {
    val arrayType: Type = Types.arrayOf(String::class.java)
    val adapter = moshi().adapter<Array<String>>(arrayType)
    val json = adapter.toJson(arrayOf("x", "y"))
    assertEquals("""["x","y"]""", json)
    val decoded = adapter.fromJson(json)!!
    assertEquals(2, decoded.size)
    assertEquals("x", decoded[0])
    assertEquals("y", decoded[1])
  }

  // D. Custom adapters ---------------------------------------------------------------

  @Test
  fun test11_customJsonAdapterSubclass() {
    val m = Moshi.Builder().add(String::class.java, UppercaseStringAdapter()).build()
    val adapter = m.adapter(String::class.java)
    assertEquals("\"HELLO\"", adapter.toJson("hello"))
    assertEquals("world", adapter.fromJson("\"WORLD\""))
  }

  @Test
  fun test12_factoryRegistrationOrder() {
    // A factory added first (via `add`) is consulted first (LIFO after built-ins). LiteralA is
    // registered first, so it should win over LiteralB for ATag.
    val m1 = Moshi.Builder()
      .add(ATag::class.java, LiteralA())
      .add(ATag::class.java, LiteralB())
      .build()
    assertEquals("\"A\"", m1.adapter(ATag::class.java).toJson(ATag()))
    // Reversed order: LiteralB wins.
    val m2 = Moshi.Builder()
      .add(ATag::class.java, LiteralB())
      .add(ATag::class.java, LiteralA())
      .build()
    assertEquals("\"B\"", m2.adapter(ATag::class.java).toJson(ATag()))
  }

  @Test
  fun test13_toJsonFromJsonMethods() {
    // Add an "adapter object" with @ToJson/@FromJson methods: Moshi discovers them via reflection
    // and builds a JsonAdapter<Point> from them.
    val m = Moshi.Builder().add(PointTupleAdapter()).build()
    val adapter = m.adapter(Point::class.java)
    assertEquals("[3,4]", adapter.toJson(Point(3, 4)))
    val decoded = adapter.fromJson("[7,8]")!!
    assertEquals(7, decoded.x)
    assertEquals(8, decoded.y)
  }

  // E. Qualifiers --------------------------------------------------------------------

  @Test
  fun test14_qualifierAnnotationDispatch() {
    // The @Hex-qualified Int field uses the hex adapter; the unqualified Int field uses the
    // built-in decimal adapter. KotlinJsonAdapterFactory adapts the outer Widget itself (a Kotlin
    // class).
    val m = Moshi.Builder().add(HexAdapter()).add(KotlinJsonAdapterFactory()).build()
    val adapter = m.adapter(Widget::class.java)
    val json = adapter.toJson(Widget(id = 7, color = 0xFF00AA))
    // id is decimal, color is hex-encoded string
    assertEquals("""{"id":7,"color":"0xff00aa"}""", json)
    val decoded = adapter.fromJson(json)!!
    assertEquals(7, decoded.id)
    assertEquals(0xFF00AA, decoded.color)
  }

  @Test
  fun test15_distinctQualifiersDispatchIndependently() {
    // Two DISTINCT @JsonQualifier annotations on sibling fields must each dispatch to their own
    // registered adapter, keyed on the qualifier TYPE: @Hex Int -> HexAdapter (hex string),
    // @Reversed String -> ReverseAdapter (reversed string). Neither qualifier leaks onto the
    // other's field. (test14 registers a single qualifier; this proves qualifier identity — the
    // (type, annotation) pair — is what selects the adapter, not merely "a qualifier is present".)
    val m = Moshi.Builder()
      .add(HexAdapter())
      .add(ReverseAdapter())
      .add(KotlinJsonAdapterFactory())
      .build()
    val adapter = m.adapter(Tagged::class.java)
    val json = adapter.toJson(Tagged(code = 0xFF00AA, label = "abc"))
    assertEquals("""{"code":"0xff00aa","label":"cba"}""", json)
    val decoded = adapter.fromJson(json)!!
    assertEquals(0xFF00AA, decoded.code)
    assertEquals("abc", decoded.label)
  }

  // F. Nullability wrappers ----------------------------------------------------------

  @Test
  fun test16_nullSafeReadsAndWritesNull() {
    val adapter = moshi().adapter(String::class.java).nullSafe()
    assertEquals("null", adapter.toJson(null))
    assertNull(adapter.fromJson("null"))
    assertEquals("\"hi\"", adapter.toJson("hi"))
    assertEquals("hi", adapter.fromJson("\"hi\""))
  }

  @Test
  fun test17_nonNullThrowsOnJsonNull() {
    // A nonNull() adapter refuses to READ a JSON `null` — it throws JsonDataException instead of
    // returning Kotlin `null`. (Writing null is a compile-time impossibility because JsonAdapter
    // parameterizes on non-null T at the low-level toJson signature.)
    val adapter = moshi().adapter(String::class.java).nonNull()
    assertThrows(JsonDataException::class.java) { adapter.fromJson("null") }
    // And a valid value still round-trips through nonNull:
    assertEquals("\"hi\"", adapter.toJson("hi"))
    assertEquals("hi", adapter.fromJson("\"hi\""))
  }

  // G. JsonReader streaming ----------------------------------------------------------

  @Test
  fun test18_streamingReaderNestedObject() {
    val json = """{"name":"Alice","age":30}"""
    val reader = JsonReader.of(Buffer().writeUtf8(json))
    reader.beginObject()
    assertEquals("name", reader.nextName())
    assertEquals("Alice", reader.nextString())
    assertEquals("age", reader.nextName())
    assertEquals(30, reader.nextInt())
    reader.endObject()
  }

  @Test
  fun test19_skipValueSkipsUnknown() {
    val json = """{"a":1,"complex":{"nested":[1,2,3]},"b":2}"""
    val reader = JsonReader.of(Buffer().writeUtf8(json))
    reader.beginObject()
    assertEquals("a", reader.nextName()); assertEquals(1, reader.nextInt())
    assertEquals("complex", reader.nextName()); reader.skipValue()
    assertEquals("b", reader.nextName()); assertEquals(2, reader.nextInt())
    reader.endObject()
  }

  @Test
  fun test20_peekJsonReturnsIndependentReader() {
    val json = """{"k":42}"""
    val reader = JsonReader.of(Buffer().writeUtf8(json))
    reader.beginObject()
    reader.nextName()  // "k"
    val peek = reader.peekJson()
    // Peek reads value without advancing the original.
    assertEquals(42, peek.nextInt())
    peek.close()
    // Original still positioned before the value:
    assertEquals(42, reader.nextInt())
    reader.endObject()
  }

  // H. JsonWriter streaming ----------------------------------------------------------

  @Test
  fun test21_streamingWriterNestedObject() {
    val buffer = Buffer()
    JsonWriter.of(buffer).use { w ->
      w.beginObject()
      w.name("k").value(1)
      w.name("nested").beginObject()
      w.name("inner").value("v")
      w.endObject()
      w.endObject()
    }
    assertEquals("""{"k":1,"nested":{"inner":"v"}}""", buffer.readUtf8())
  }

  @Test
  fun test22_indentProducesPrettyPrint() {
    val listType: Type = Types.newParameterizedType(List::class.java, Int::class.javaObjectType)
    val adapter = moshi().adapter<List<Int>>(listType).indent("  ")
    val json = adapter.toJson(listOf(1, 2))
    // Pretty-printed form has newlines between elements; compact form has none.
    assertEquals("[\n  1,\n  2\n]", json)
  }

  // I. Reader modes ------------------------------------------------------------------

  @Test
  fun test23_lenientAcceptsUnquotedNames() {
    val reader = JsonReader.of(Buffer().writeUtf8("{key:1}"))
    reader.lenient = true
    reader.beginObject()
    assertEquals("key", reader.nextName())
    assertEquals(1, reader.nextInt())
    reader.endObject()
  }

  @Test
  fun test24_failOnUnknownThrows() {
    val reader = JsonReader.of(Buffer().writeUtf8("""{"known":1,"unknown":2}"""))
    reader.failOnUnknown = true
    reader.beginObject()
    assertEquals("known", reader.nextName())
    assertEquals(1, reader.nextInt())
    reader.nextName()  // "unknown" — reading the name is fine
    assertThrows(JsonDataException::class.java) { reader.skipValue() }
  }

  // J. Options / selectName ----------------------------------------------------------

  @Test
  fun test25_selectNameReturnsIndex() {
    val options = JsonReader.Options.of("foo", "bar", "baz")
    val reader = JsonReader.of(Buffer().writeUtf8("""{"bar":1,"foo":2,"zzz":3}"""))
    reader.beginObject()
    assertEquals(1, reader.selectName(options))  // "bar" -> index 1
    reader.skipValue()
    assertEquals(0, reader.selectName(options))  // "foo" -> index 0
    reader.skipValue()
    assertEquals(-1, reader.selectName(options)) // "zzz" not in options
    reader.skipName()
    reader.skipValue()
    reader.endObject()
  }

  // K. Reentrant/cyclic adapter resolution (LookupChain + deferred) ------------------

  @Test
  fun test26_reentrantCyclicNodeRoundTrip() {
    val adapter = moshi().adapter(Node::class.java)
    val tree = Node().apply {
      name = "root"
      children = listOf(
        Node().apply {
          name = "left"
          children = listOf(Node().apply { name = "left.a" })
        },
        Node().apply { name = "right" },
      )
    }
    val json = adapter.toJson(tree)
    val decoded = adapter.fromJson(json)!!
    assertEquals("root", decoded.name)
    assertEquals(2, decoded.children.size)
    assertEquals("left", decoded.children[0].name)
    assertEquals(1, decoded.children[0].children.size)
    assertEquals("left.a", decoded.children[0].children[0].name)
    assertEquals("right", decoded.children[1].name)
    assertEquals(0, decoded.children[1].children.size)
  }

  // L. Adapter cache -----------------------------------------------------------------

  @Test
  fun test27_adapterCacheReusesInstance() {
    val m = moshi()
    val a1 = m.adapter(Person::class.java)
    val a2 = m.adapter(Person::class.java)
    // Second lookup for the same (type, annotations) key must return the cached instance.
    assertSame(a1, a2)
  }

  // M. Composite generic types (map of list, list of map) ----------------------------

  @Test
  fun test28_mapOfLists() {
    val innerListType = Types.newParameterizedType(List::class.java, Int::class.javaObjectType)
    val mapType = Types.newParameterizedType(Map::class.java, String::class.java, innerListType)
    val adapter = moshi().adapter<Map<String, List<Int>>>(mapType)
    val input = linkedMapOf("evens" to listOf(2, 4), "odds" to listOf(1, 3))
    val json = adapter.toJson(input)
    assertEquals("""{"evens":[2,4],"odds":[1,3]}""", json)
    val decoded = adapter.fromJson(json)!!
    assertEquals(listOf(2, 4), decoded["evens"])
    assertEquals(listOf(1, 3), decoded["odds"])
  }

  @Test
  fun test29_listOfMaps() {
    val innerMapType = Types.newParameterizedType(
      Map::class.java, String::class.java, String::class.java
    )
    val listType = Types.newParameterizedType(List::class.java, innerMapType)
    val adapter = moshi().adapter<List<Map<String, String>>>(listType)
    val input = listOf(mapOf("a" to "1"), mapOf("b" to "2"))
    val json = adapter.toJson(input)
    assertEquals("""[{"a":"1"},{"b":"2"}]""", json)
    val decoded = adapter.fromJson(json)!!
    assertEquals(2, decoded.size)
    assertEquals("1", decoded[0]["a"])
    assertEquals("2", decoded[1]["b"])
  }

  // N. Exceptions --------------------------------------------------------------------

  @Test
  fun test30_jsonDataExceptionOnTypeMismatch() {
    // Reading a JSON string where an Int is expected must throw JsonDataException (not IOException,
    // and not silently coerce). This is a semantic contract: JsonDataException signals bad-shape
    // input at the value level, JsonEncodingException signals malformed JSON at the token level.
    val adapter = moshi().adapter(Int::class.javaObjectType)
    assertThrows(JsonDataException::class.java) { adapter.fromJson("\"forty-two\"") }
  }

  // O. Harder corners ----------------------------------------------------------------

  @Test
  fun test31_setDeduplicatesOnRead() {
    // Set<String> reads a JSON array with duplicate elements and returns a Set with each element
    // exactly once, preserving first-seen insertion order (LinkedHashSet semantics).
    val setType: Type = Types.newParameterizedType(Set::class.java, String::class.java)
    val adapter = moshi().adapter<Set<String>>(setType)
    val decoded = adapter.fromJson("""["a","b","a","c","b"]""")!!
    assertEquals(3, decoded.size)
    assertEquals(listOf("a", "b", "c"), decoded.toList())  // insertion order preserved
  }

  @Test
  fun test32_strictRejectsMalformedJson() {
    // A truncated / malformed token stream MUST throw at the JSON *encoding* level (upstream: an
    // IOException subclass; either JsonEncodingException or a plain IOException are accepted).
    // Different from JsonDataException — malformed tokens are not "bad shape at the value level"
    // but "not valid JSON at all". Reading past the end of `{"a":1,` (trailing comma, no close)
    // is a token-level error.
    val listType: Type = Types.newParameterizedType(
      Map::class.java, String::class.java, Int::class.javaObjectType
    )
    val adapter = moshi().adapter<Map<String, Int>>(listType)
    val thrown = assertThrows(IOException::class.java) { adapter.fromJson("""{"a":1,""") }
    // The exception type is either JsonEncodingException or IOException — the test's
    // assertThrows(IOException) accepts both because JsonEncodingException extends IOException.
    assertNotNull(thrown)
  }

  @Test
  fun test33_readerPathTracks() {
    // JsonReader.path reports a JSONPath-style location string during parsing: `$` at the
    // document root, `$.foo` inside object field `foo`, `$.foo[2]` at array index 2 inside `foo`.
    // Upstream contract: property `val path: String` (Kotlin) / `getPath()` (Java) — no arguments.
    val reader = JsonReader.of(Buffer().writeUtf8("""{"foo":[10,20,30]}"""))
    assertEquals("$", reader.path)
    reader.beginObject()
    reader.nextName()           // now "positioned at" foo
    assertEquals("$.foo", reader.path)
    reader.beginArray()
    reader.nextInt()            // consumed [0]
    assertEquals("$.foo[1]", reader.path)
    reader.nextInt()            // consumed [1]
    assertEquals("$.foo[2]", reader.path)
    reader.nextInt()            // consumed [2]
    reader.endArray()
    reader.endObject()
  }

  @Test
  fun test34_defaultValueFillsMissingKey() {
    // KotlinJsonAdapterFactory contract: if a constructor parameter has a default AND the JSON is
    // missing the corresponding key, the adapter must use the default rather than throwing.
    // A parameter WITHOUT a default whose JSON key is missing must throw JsonDataException.
    //
    // ⭐ HARD CASE: Kotlin defaults are implemented on the JVM as a SYNTHETIC constructor
    // taking a bitmask parameter (`<init>(..., mask: Int, marker: DefaultConstructorMarker)`)
    // rather than JVM-standard defaults. The adapter must invoke this synthetic constructor
    // with the correct bitmask indicating which arguments are missing. Naïve implementations
    // that Unsafe-allocate + reflectively assign (like the Java-side ClassJsonAdapter) will
    // fail on Kotlin data classes: field reflection either skips the default entirely (leaving
    // the field at its JVM zero-value like null / 0) or throws InstantiationException.
    //
    // This test uses THREE parameters (1 required, 2 defaulted) and omits BOTH defaulted keys
    // in the JSON — forcing the bitmask to encode two absent arguments at once, which is what
    // the $default synthetic constructor's bit layout requires.
    val adapter = moshi().adapter(ServerConfig::class.java)
    // Both `port` and `ssl` are missing — both defaults must fill in (bitmask marks two bits):
    val decoded = adapter.fromJson("""{"host":"api.example.com"}""")!!
    assertEquals("api.example.com", decoded.host)
    assertEquals(8080, decoded.port)
    assertEquals(false, decoded.ssl)
    // host has NO default — missing from JSON — must throw JsonDataException:
    assertThrows(JsonDataException::class.java) { adapter.fromJson("""{}""") }
    // BOTH POLARITIES OF THE SAME LITERAL INPUT: the throw above is caused by `host` being
    // mandatory, NOT by the object being empty. A class in which EVERY parameter is defaulted
    // must therefore decode `{}` successfully and yield all its defaults. This rejects the
    // short-circuit "no bound key was supplied -> throw" (which passes the assertion above
    // without ever consulting per-parameter optionality), and extends the absent-parameter set
    // beyond the primitives above to reference types (String, List).
    val allDefaults = moshi().adapter(AllDefaults::class.java).fromJson("""{}""")!!
    assertEquals(1, allDefaults.a)
    assertEquals("two", allDefaults.b)
    assertEquals(3.14, allDefaults.c)
    assertEquals(true, allDefaults.d)
    assertEquals(listOf("x", "y"), allDefaults.e)
  }

  @Test
  fun test35_jsonIgnoreExcludesField() {
    // A property annotated @field:Json(ignore = true) is invisible to both read and write paths:
    // toJson never emits it; fromJson does not consume it (and uses the Kotlin constructor default
    // if one exists — otherwise fails). Tests both directions.
    val adapter = moshi().adapter(Session::class.java)
    // Round-trip write: `secret` must NOT appear in output even though it has a value.
    val json = adapter.toJson(Session(userId = "u1", secret = "REDACTED"))
    assertEquals("""{"userId":"u1"}""", json)
    // Round-trip read: JSON has no `secret`; adapter fills from the default constructor value.
    val decoded = adapter.fromJson("""{"userId":"u2"}""")!!
    assertEquals("u2", decoded.userId)
    assertEquals("(default)", decoded.secret)
  }

  // P. Even-harder corners (36-40) ---------------------------------------------------

  @Test
  fun test36_polymorphicByTypeField() {
    // A custom Factory reads a "kind" discriminator field and dispatches to the correct
    // concrete adapter. Exercises: factory-level dispatch, JsonReader.peekJson() to sniff
    // without consuming, and factory-delegated adapter lookup via moshi.adapter().
    //
    // ⭐ HARD CASE: the discriminator "kind" is at the END of the object, not the beginning.
    // The factory MUST scan the entire object via peekJson() to find it, then hand the
    // original reader (still positioned at the start of the object) to the concrete adapter.
    // A common bug is corrupting the main reader's stream state while peeking, so when the
    // concrete adapter tries to read, it sees an empty/truncated object.
    val m = Moshi.Builder().add(ShapeFactory()).add(KotlinJsonAdapterFactory()).build()
    val adapter = m.adapter(Shape::class.java)
    // Type label AT END for the circle case (state-leak trap):
    val decoded1 = adapter.fromJson("""{"radius":2.5,"kind":"circle"}""")!!
    assertTrue(decoded1 is ShapeCircle, "expected ShapeCircle, got ${decoded1::class}")
    assertEquals(2.5, (decoded1 as ShapeCircle).radius)
    // Type label AT END for the square case, with an EXTRA unknown key mixed in the middle:
    val decoded2 = adapter.fromJson("""{"side":4.0,"extra":true,"kind":"square"}""")!!
    assertTrue(decoded2 is ShapeSquare)
    assertEquals(4.0, (decoded2 as ShapeSquare).side)
  }

  @Test
  fun test37_writerRejectsUnbalancedEnd() {
    // JsonWriter is a state machine: calling endObject() when the writer is at document root
    // (no matching beginObject) MUST throw. This asserts the primary invariant: endObject
    // without begin.
    val buffer = Buffer()
    val writer = JsonWriter.of(buffer)
    assertThrows(IllegalStateException::class.java) { writer.endObject() }
  }

  @Test
  fun test38_mutuallyRecursiveTypesRoundTrip() {
    // Extends the reentrant-cycles test to MUTUAL recursion: TreeA holds TreeB?, TreeB holds
    // TreeA?. Both adapters must resolve through the LookupChain / deferred() mechanism, and
    // a finite structure must serialize and deserialize with identity of the two adapters
    // cached correctly.
    val adapter = moshi().adapter(TreeA::class.java)
    val root = TreeA().apply {
      name = "root"
      b = TreeB().apply {
        label = "b1"
        a = TreeA().apply { name = "leaf" }
      }
    }
    val json = adapter.toJson(root)
    val decoded = adapter.fromJson(json)!!
    assertEquals("root", decoded.name)
    assertNotNull(decoded.b)
    assertEquals("b1", decoded.b!!.label)
    assertNotNull(decoded.b!!.a)
    assertEquals("leaf", decoded.b!!.a!!.name)
    assertNull(decoded.b!!.a!!.b)
  }

  @Test
  fun test39_selectStringForValues() {
    // JsonReader.selectString(options): while positioned at a string VALUE, returns the index
    // of the matching value in `options`, or -1 if not present. Consumes the value on a hit;
    // does NOT consume on -1 (caller must call nextString / skipValue). Symmetric to selectName
    // but for values, used by generated code to decode enum-like discriminators without
    // materializing the string.
    val options = JsonReader.Options.of("apple", "banana", "cherry")
    val reader = JsonReader.of(Buffer().writeUtf8("""["banana","cherry","durian","apple"]"""))
    reader.beginArray()
    assertEquals(1, reader.selectString(options))  // "banana" -> 1
    assertEquals(2, reader.selectString(options))  // "cherry" -> 2
    assertEquals(-1, reader.selectString(options)) // "durian" not in options
    reader.nextString()                             // caller drains
    assertEquals(0, reader.selectString(options))  // "apple" -> 0
    reader.endArray()
  }

  @Test
  fun test40_promoteValueToNameForIntKeys() {
    // JsonReader.promoteValueToName(): promotes the current VALUE position into a NAME
    // position, so the value can be consumed via nextName() / selectName() / skipName(). This
    // is how moshi supports Map<Int, V> — the JSON object's keys are strings, but the reader
    // treats each key as a value to parse into an Int. Exercised by asking for the adapter for
    // Map<Int, String>: the map reader calls promoteValueToName + nextInt for each key.
    val mapType: Type = Types.newParameterizedType(
      Map::class.java, Int::class.javaObjectType, String::class.java
    )
    val adapter = moshi().adapter<Map<Int, String>>(mapType)
    val decoded = adapter.fromJson("""{"7":"seven","42":"answer"}""")!!
    assertEquals("seven", decoded[7])
    assertEquals("answer", decoded[42])
    assertEquals(2, decoded.size)
  }

  // Q. Hard corners: state machine + concurrency + numbers + types (41-48) -----------

  @Test
  fun test41_readerRejectsNestingMismatch() {
    // beginObject() then endArray() must fail — the reader's state stack must reject a mismatched
    // close bracket, not silently accept it. Either JsonEncodingException or IllegalStateException
    // is acceptable (both signal a container-shape violation).
    val reader = JsonReader.of(Buffer().writeUtf8("""{"k":1}"""))
    reader.beginObject()
    reader.nextName()
    reader.nextInt()
    assertThrows(Exception::class.java) { reader.endArray() }
  }

  @Test
  fun test42_writerRejectsUnnamedValueInObject() {
    // Inside an object context, value(...) without a preceding name() is a state violation:
    // objects require key-value pairs, not bare values. The writer must throw.
    val buffer = Buffer()
    val writer = JsonWriter.of(buffer)
    writer.beginObject()
    assertThrows(IllegalStateException::class.java) { writer.value(1) }
  }

  @Test
  fun test44_readerAcceptsScientificNotationAsLong() {
    // Upstream JsonUtf8Reader.nextLong accepts scientific notation for integer values that fit
    // in Long. `1e10` = 10^10 = 10_000_000_000L. A naïve implementation only accepts a strict
    // decimal-integer form and throws on the 'e', failing this test.
    val reader = JsonReader.of(Buffer().writeUtf8("1e10"))
    assertEquals(10_000_000_000L, reader.nextLong())
  }

  @Test
  fun test45_readerLongOverflowThrows() {
    // Long.MAX_VALUE + 1 as decimal in JSON must throw JsonDataException on nextLong() (overflow
    // is a value-level shape violation, not malformed JSON). Silently wrapping around or
    // truncating is wrong.
    val overflow = "9223372036854775808"  // Long.MAX_VALUE + 1
    val reader = JsonReader.of(Buffer().writeUtf8(overflow))
    assertThrows(JsonDataException::class.java) { reader.nextLong() }
  }

  @Test
  fun test46_negativeZeroPreservedInRoundtrip() {
    // -0.0 has a different IEEE 754 bit pattern than 0.0 (sign bit set). The writer must emit
    // "-0.0" (or an equivalent representation that preserves sign), and the reader must decode
    // back to a Double whose raw bits equal -0.0's raw bits.
    val adapter = moshi().adapter(Double::class.javaObjectType)
    val negZero = -0.0
    val json = adapter.toJson(negZero)
    val decoded = adapter.fromJson(json)!!
    assertEquals(
      java.lang.Double.doubleToRawLongBits(negZero),
      java.lang.Double.doubleToRawLongBits(decoded),
      "-0.0 raw bits must be preserved through round-trip; got json=$json decoded=$decoded",
    )
  }

  @Test
  fun test47_typesSubtypeOfProducesWildcard() {
    // Types.subtypeOf(T::class.java) returns a WildcardType representing `? extends T` — used
    // to build parameterized types with wildcards (e.g. `List<? extends Number>`).
    val wildcard = Types.subtypeOf(Number::class.java)
    assertTrue(wildcard is java.lang.reflect.WildcardType)
    val wt = wildcard as java.lang.reflect.WildcardType
    assertEquals(1, wt.upperBounds.size)
    assertEquals(Number::class.java, wt.upperBounds[0])
    assertEquals(0, wt.lowerBounds.size)
  }

  @Test
  fun test48_typesSupertypeOfProducesWildcard() {
    // Types.supertypeOf(T::class.java) returns a WildcardType representing `? super T` — used
    // to build parameterized types with lower-bounded wildcards (e.g. `Consumer<? super Integer>`).
    // The default upper bound for a lower-bounded wildcard is Object; the lower bound is T.
    val wildcard = Types.supertypeOf(Integer::class.java)
    assertTrue(wildcard is java.lang.reflect.WildcardType)
    val wt = wildcard as java.lang.reflect.WildcardType
    assertEquals(1, wt.lowerBounds.size)
    assertEquals(Integer::class.java, wt.lowerBounds[0])
    // Upper bound defaults to Object for a `? super X` wildcard:
    assertEquals(1, wt.upperBounds.size)
    assertEquals(Any::class.java, wt.upperBounds[0])
  }

  // R. Deep escape and cycle stress (49-53) ------------------------------------------

  @Test
  fun test49_surrogatePairEmojiRoundtrip() {
    // 😀 (U+1F600) is a supplementary-plane character encoded as a UTF-16 surrogate pair.
    // The reader/writer must handle this either by emitting the raw 4-byte UTF-8 or by using
    // two \uXXXX escapes (`😀`). Either output form must round-trip losslessly.
    // A common bug: reader consumes only one half of the surrogate pair, corrupting the string.
    val adapter = moshi().adapter(String::class.java)
    val emoji = "hello 😀 world"  // grinning face
    val json = adapter.toJson(emoji)
    val decoded = adapter.fromJson(json)!!
    assertEquals(emoji, decoded)
  }

  @Test
  fun test50_controlCharsAreEscaped() {
    // JSON forbids raw control chars (U+0000 through U+001F) inside strings — the writer MUST
    // escape them as \u00XX. A naïve writer that emits the raw byte produces invalid JSON.
    // We verify BOTH that the JSON output contains the escape (not the raw byte) AND that a
    // round-trip preserves the character.
    val adapter = moshi().adapter(String::class.java)
    val input = "beforeafter"  // U+0001 START OF HEADING
    val json = adapter.toJson(input)
    assertTrue(json.contains("\\u0001"), "control char must be escaped as \\u0001; got: $json")
    assertEquals(input, adapter.fromJson(json))
  }

  @Test
  fun test51_allJsonEscapeSequencesRoundtrip() {
    // The 8 JSON-standard escape sequences must all round-trip: \" \\ \/ \b \f \n \r \t
    // The reader must decode each escape to its target character; the writer must emit escapes
    // for at least: \" \\ \n \r \t (others may be emitted as raw or escaped — both accepted).
    val adapter = moshi().adapter(String::class.java)
    val s = "\"" + "\\" + "/" + "\b" + "" + "\n" + "\r" + "\t"
    val json = adapter.toJson(s)
    assertEquals(s, adapter.fromJson(json))
  }

  @Test
  fun test52_selfReferentialClassRoundtrip() {
    // Distinct from test26 (Node containing List<Node>) and test38 (mutually recursive TreeA/B):
    // a class field that directly references its OWN type as an Optional field.
    // Requires LookupChain to correctly handle type == self at the leaf (not via a wrapper).
    val adapter = moshi().adapter(SelfRef::class.java)
    val chain = SelfRef().apply {
      payload = "outer"
      next = SelfRef().apply {
        payload = "middle"
        next = SelfRef().apply { payload = "inner" }
      }
    }
    val json = adapter.toJson(chain)
    val decoded = adapter.fromJson(json)!!
    assertEquals("outer", decoded.payload)
    assertNotNull(decoded.next)
    assertEquals("middle", decoded.next!!.payload)
    assertNotNull(decoded.next!!.next)
    assertEquals("inner", decoded.next!!.next!!.payload)
    assertNull(decoded.next!!.next!!.next)
  }
}

// ---------- Data classes for tests 31-35 ----------

private class ServerConfig(val host: String, val port: Int = 8080, val ssl: Boolean = false)

// For test34's second polarity: every parameter defaulted, mixing primitives with reference
// types, so decoding `{}` must succeed and fill all five defaults.
private class AllDefaults(
  val a: Int = 1,
  val b: String = "two",
  val c: Double = 3.14,
  val d: Boolean = true,
  val e: List<String> = listOf("x", "y"),
)

private class Session(
  val userId: String = "",
  @field:Json(ignore = true) val secret: String = "(default)",
)

// For test52: a class whose field type is itself.
private class SelfRef {
  var payload: String = ""
  var next: SelfRef? = null
}


// ---------- Additional harder tests (36-40) ----------

// Polymorphic hierarchy for test36
private open class Shape { open val kind: String get() = "shape" }
private class ShapeCircle(val radius: Double = 0.0) : Shape() { override val kind = "circle" }
private class ShapeSquare(val side: Double = 0.0) : Shape() { override val kind = "square" }

// Custom polymorphic factory that reads a "kind" discriminator and dispatches to the right
// subtype adapter. Tests exercise the factory's ability to consume the discriminator, then
// use peekJson to snapshot the payload, hand it to the delegate adapter, and skip the outer
// payload on the primary reader.
private class ShapeFactory : JsonAdapter.Factory {
  override fun create(
    type: Type,
    annotations: Set<out Annotation>,
    moshi: Moshi,
  ): JsonAdapter<*>? {
    if (type !== Shape::class.java) return null
    val circleAdapter = moshi.adapter(ShapeCircle::class.java)
    val squareAdapter = moshi.adapter(ShapeSquare::class.java)
    return object : JsonAdapter<Shape>() {
      override fun fromJson(reader: JsonReader): Shape {
        // Peek to discover the kind without consuming the object.
        val peek = reader.peekJson()
        peek.beginObject()
        var kind: String? = null
        while (peek.hasNext()) {
          if (peek.nextName() == "kind") kind = peek.nextString() else peek.skipValue()
        }
        peek.endObject(); peek.close()
        return when (kind) {
          "circle" -> circleAdapter.fromJson(reader)!!
          "square" -> squareAdapter.fromJson(reader)!!
          else -> throw JsonDataException("unknown shape kind: $kind")
        }
      }
      override fun toJson(writer: JsonWriter, value: Shape) {
        when (value) {
          is ShapeCircle -> circleAdapter.toJson(writer, value)
          is ShapeSquare -> squareAdapter.toJson(writer, value)
        }
      }
    }
  }
}

// Mutually recursive types for test38
private class TreeA {
  var name: String = ""
  var b: TreeB? = null
}
private class TreeB {
  var label: String = ""
  var a: TreeA? = null
}
