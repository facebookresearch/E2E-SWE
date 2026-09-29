package com.akuleshov7.ktoml.hidden

import com.akuleshov7.ktoml.Toml
import com.akuleshov7.ktoml.TomlInputConfig
import com.akuleshov7.ktoml.TomlOutputConfig
import com.akuleshov7.ktoml.annotations.TomlComments
import com.akuleshov7.ktoml.annotations.TomlInteger
import com.akuleshov7.ktoml.annotations.TomlLiteral
import com.akuleshov7.ktoml.exceptions.TomlDecodingException
import com.akuleshov7.ktoml.exceptions.TomlEncodingException
import com.akuleshov7.ktoml.writers.IntegerRepresentation.BINARY
import com.akuleshov7.ktoml.writers.IntegerRepresentation.GROUPED
import com.akuleshov7.ktoml.writers.IntegerRepresentation.HEX
import com.akuleshov7.ktoml.writers.IntegerRepresentation.OCTAL
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.decodeFromString
import kotlinx.serialization.encodeToString
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertThrows
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class KtomlTest {

    // ---------------------------------------------------------------------
    // Decoding: basic tables, nesting, ordering, primitives
    // ---------------------------------------------------------------------

    enum class Color { A, B }

    @Serializable
    data class Table1(val a: Long, val b: Long)

    @Serializable
    data class Table2(val c: Long, val e: Long, val d: Long)

    @Serializable
    data class TwoTables(val table1: Table1, val table2: Table2)

    @Test
    fun decodeMultipleTables() {
        val toml = "[table1]\n b = 6  \n a = 5  \n [table2] \n c = 7 \n d = 8 \n e = 9 \n"
        assertEquals(
            TwoTables(Table1(5, 6), Table2(7, 9, 8)),
            Toml.decodeFromString<TwoTables>(toml)
        )
    }

    @Serializable
    data class Nested4(val c: Long, val e: Long, val d: Long, val table1: Table1)

    @Serializable
    data class Nested(val c: Long, val table1: Table1, val table4: Nested4)

    @Test
    fun decodeNestedTables() {
        val toml = ("c = 5 \n" +
                "[table1] \n b = 6 \n a = 5 \n" +
                "[table4] \n c = 7 \n d = 8 \n e = 9 \n" +
                " [table4.table1] \n b = 6 \n a = 5 \n")
        assertEquals(
            Nested(c = 5, Table1(5, 6), Nested4(7, 9, 8, Table1(5, 6))),
            Toml.decodeFromString<Nested>(toml)
        )
    }

    @Serializable
    data class ChildBeforeParent(val a: AParent)
    @Serializable
    data class AParent(val b: BChild, val a: Boolean)
    @Serializable
    data class BChild(val c: Long)

    @Test
    fun decodeChildTableBeforeParent() {
        val toml = "[a.b]\n c = 5\n [a]\n a = true\n"
        assertEquals(ChildBeforeParent(AParent(BChild(5), true)), Toml.decodeFromString<ChildBeforeParent>(toml))
    }

    @Serializable
    data class WithEnum(val a: Boolean, val e: String = "default", val d: Long, val b: Color)

    @Test
    fun decodeEnumAndDefault() {
        // 'e' uses its default; enum 'b' matches by constant name
        val toml = "[t3] \n a = true \n b = \"A\" \n d = 5"
        @Serializable
        data class Holder(val t3: WithEnum)
        assertEquals(Holder(WithEnum(a = true, d = 5, b = Color.A)), Toml.decodeFromString<Holder>(toml))
    }

    @Test
    fun decodeEnumInvalidValueThrows() {
        val toml = "a = true \n b = \"F\" \n e = \"x\" \n d = 5"
        assertThrows(TomlDecodingException::class.java) {
            Toml.decodeFromString<WithEnum>(toml)
        }
    }

    // ---------------------------------------------------------------------
    // Decoding: config-driven behavior (unknown names, missing, null, defaults)
    // ---------------------------------------------------------------------

    @Serializable
    data class Simple(val a: Long, val b: String)

    @Test
    fun unknownKeyThrowsButIsSkippedWhenIgnored() {
        val toml = "a = 1 \n b = \"x\" \n c = 2"
        assertThrows(TomlDecodingException::class.java) {
            Toml.decodeFromString<Simple>(toml)
        }
        assertEquals(
            Simple(1, "x"),
            Toml(TomlInputConfig(ignoreUnknownNames = true)).decodeFromString<Simple>(toml)
        )
    }

    @Test
    fun missingRequiredFieldThrowsAndNamesField() {
        val toml = "a = 1"
        val ex = assertThrows(TomlDecodingException::class.java) {
            Toml.decodeFromString<Simple>(toml)
        }
        assertTrue(ex.message!!.contains("<b>"), "message should name missing field <b>: ${ex.message}")
    }

    @Serializable
    data class Nullables(val a: Long?, val b: String?, val c: String?, val d: String?, val e: String?)

    @Test
    fun nullExtensionValuesDecodeToNull() {
        // null / NULL / nil / empty value / NIL all map to null
        val toml = "a = null \n b = NULL \n c = nil \n d = # hi \n e = NIL\n"
        assertEquals(Nullables(null, null, null, null, null), Toml.decodeFromString<Nullables>(toml))
        assertThrows(TomlDecodingException::class.java) {
            Toml(TomlInputConfig(allowNullValues = false)).decodeFromString<Nullables>(toml)
        }
    }

    @Serializable
    data class WithDefault(val a: Long = 1)

    @Test
    fun ignoreDefaultValuesMakesPropertyRequired() {
        assertEquals(WithDefault(1), Toml.decodeFromString<WithDefault>(""))
        assertThrows(TomlDecodingException::class.java) {
            Toml(TomlInputConfig(ignoreDefaultValues = true)).decodeFromString<WithDefault>("")
        }
    }

    // ---------------------------------------------------------------------
    // Decoding: numbers, ranges, radixes
    // ---------------------------------------------------------------------

    @Serializable
    data class Ints(val s: Short, val b: Byte, val i: Int, val l: Long)

    @Test
    fun decodeSignedIntegersWithSigns() {
        val toml = "s = 32767 \n b = -128 \n i = +5 \n l = 5"
        assertEquals(Ints(32767, -128, 5, 5), Toml.decodeFromString<Ints>(toml))
    }

    @Test
    fun integerRangeOverflowThrows() {
        assertThrows(TomlDecodingException::class.java) {
            Toml.decodeFromString<Ints>("s = 32768 \n b = 1 \n i = 1 \n l = 1")
        }
        @Serializable
        data class OneByte(val value: Byte)
        assertThrows(TomlDecodingException::class.java) {
            Toml.decodeFromString<OneByte>("value = 128")
        }
    }

    @Serializable
    data class Unsigned(val b: UByte, val l: ULong)

    @Test
    fun decodeUnsignedAndRejectNegative() {
        assertEquals(
            Unsigned(128u, (Long.MAX_VALUE + 1).toULong()),
            Toml.decodeFromString<Unsigned>("b = 128 \n l = 9_223_372_036_854_775_808")
        )
        assertThrows(TomlDecodingException::class.java) {
            Toml.decodeFromString<Unsigned>("b = -1 \n l = 1")
        }
    }

    @Serializable
    data class Radixes(val h: Long, val o: Int, val bin: Long, val grp: Long)

    @Test
    fun decodeHexOctalBinaryAndUnderscores() {
        val toml = "h = 0xdead_c0de \n o = 0o777 \n bin = 0b1010 \n grp = 1_000_000"
        assertEquals(Radixes(0xdeadc0deL, 511, 10L, 1000000L), Toml.decodeFromString<Radixes>(toml))
    }

    @Serializable
    data class Floats(val a: Double, val b: Double, val c: Double, val d: Float)

    @Test
    fun decodeFloatsInfinityAndNan() {
        val decoded = Toml.decodeFromString<Floats>("a = -inf \n b = +inf \n c = 1.5 \n d = nan")
        assertEquals(Double.NEGATIVE_INFINITY, decoded.a)
        assertEquals(Double.POSITIVE_INFINITY, decoded.b)
        assertEquals(1.5, decoded.c)
        assertTrue(decoded.d.isNaN())
    }

    // ---------------------------------------------------------------------
    // Decoding: strings, escapes, comments
    // ---------------------------------------------------------------------

    @Serializable
    data class Str(val a: String)

    @Test
    fun decodeBasicStringEscapes() {
        assertEquals(Str("hello\tworld"), Toml.decodeFromString<Str>("a = \"hello\\tworld\""))
        assertEquals(Str("hello\nworld"), Toml.decodeFromString<Str>("a = \"hello\\nworld\""))
        assertEquals(Str("hello\\world"), Toml.decodeFromString<Str>("a = \"hello\\\\world\""))
        // \u and \U unicode escapes
        assertEquals(Str("Ɣ is greek"), Toml.decodeFromString<Str>("a = \"\\u0194 is greek\""))
        assertEquals(Str("😕 is emoji"), Toml.decodeFromString<Str>("a = \"\\U0001F615 is emoji\""))
    }

    @Test
    fun rejectUnknownEscapeSequences() {
        // An unknown escape (\h, \x) is a parse error.
        assertThrows(TomlDecodingException::class.java) { Toml.decodeFromString<Str>("a = \"hello\\world\"") }
        assertThrows(TomlDecodingException::class.java) { Toml.decodeFromString<Str>("a = \"\\x33\"") }
    }

    @Serializable
    data class StrInt(val a: String?, val b: Long)

    @Test
    fun commentsAreStrippedOutsideStringsButLiteralInside() {
        // '#' inside a quoted value is literal; trailing '#' starts a comment
        assertEquals(
            StrInt("dgf # f # hi", 2),
            Toml.decodeFromString<StrInt>("a = \"dgf # f # hi\" \n b = 2 # trailing comment")
        )
        // value-less key with only a comment -> null
        assertEquals(StrInt(null, 3), Toml.decodeFromString<StrInt>("a = # hello \n b = 3"))
    }

    @Test
    fun decodeMalformedLineThrows() {
        assertThrows(TomlDecodingException::class.java) {
            Toml.decodeFromString<Table1>("[table1] \n b = 6 = 7 \n a = 5")
        }
    }

    // ---------------------------------------------------------------------
    // Decoding: multi-line strings (basic + literal)
    // ---------------------------------------------------------------------

    @Test
    fun decodeMultilineBasicString() {
        // leading newline after opening delimiter is trimmed; embedded newlines kept
        assertEquals(
            Str("first line\nsecond line"),
            Toml.decodeFromString<Str>("a = \"\"\"first line\nsecond line\"\"\"")
        )
        // line-ending backslash joins lines and trims following whitespace
        assertEquals(
            Str("The quick brown fox jumps over the lazy dog."),
            Toml.decodeFromString<Str>(
                "a = \"\"\"\nThe quick brown \\\n\n  fox jumps over \\\n     the lazy dog.\"\"\""
            )
        )
    }

    @Test
    fun multilineStringHashIsNotComment() {
        assertEquals(
            Str("Roses are red # Not a comment\nViolets are blue"),
            Toml.decodeFromString<Str>("a = \"\"\"\nRoses are red # Not a comment\nViolets are blue\"\"\"")
        )
    }

    @Test
    fun decodeMultilineLiteralString() {
        // literal multi-line: no escape processing, leading newline trimmed
        assertEquals(
            Str("    Lorem ipsum dolor sit amet\n"),
            Toml.decodeFromString<Str>("a = '''\n    Lorem ipsum dolor sit amet\n'''")
        )
    }

    @Test
    fun unterminatedMultilineStringThrows() {
        assertThrows(TomlDecodingException::class.java) {
            Toml.decodeFromString<Str>("a = \"\"\"Test String \n")
        }
    }

    // ---------------------------------------------------------------------
    // Decoding: dotted keys, quoted keys
    // ---------------------------------------------------------------------

    @Serializable
    data class Fruit(val name: FruitName)
    @Serializable
    data class FruitName(val value: String)

    @Test
    fun dottedKeysWithWhitespace() {
        assertEquals(Fruit(FruitName("banana")), Toml.decodeFromString<Fruit>("name.value = \"banana\""))
        assertEquals(Fruit(FruitName("banana")), Toml.decodeFromString<Fruit>("name .  value = \"banana\""))
    }

    @Serializable
    data class QKeyA(val a: QKeyB)
    @Serializable
    data class QKeyB(@SerialName("a.b.c") val b: QKeyC)
    @Serializable
    data class QKeyC(@SerialName("b") val b: QKeyD)
    @Serializable
    data class QKeyD(val d: Long)

    @Test
    fun quotedDottedKeySegment() {
        assertEquals(
            QKeyA(QKeyB(QKeyC(QKeyD(123)))),
            Toml.decodeFromString<QKeyA>("a.\"a.b.c\".b.d = 123")
        )
    }

    // ---------------------------------------------------------------------
    // Decoding: arrays, arrays of tables, inline tables, maps
    // ---------------------------------------------------------------------

    @Serializable
    data class IntList(val a: List<Long>)
    @Serializable
    data class NestedList(val a: List<List<Long>>)

    @Test
    fun decodeArraysIncludingNestedAndEmpty() {
        assertEquals(IntList(listOf(1, 2, 3)), Toml.decodeFromString<IntList>("a = [1, 2, 3, ]"))
        assertEquals(IntList(emptyList()), Toml.decodeFromString<IntList>("a = []"))
        assertEquals(NestedList(listOf(listOf(1, 2), listOf(3))), Toml.decodeFromString<NestedList>("a = [[1, 2], [3]]"))
    }

    @Serializable
    data class Variety(val name: String)
    @Serializable
    data class Physical(val color: String, val shape: String)
    @Serializable
    data class FruitTbl(val name: String, val physical: Physical? = null, val varieties: List<Variety>)
    @Serializable
    data class Fruits(val fruits: List<FruitTbl>)

    @Test
    fun decodeArrayOfTablesMixedWithSubtables() {
        val toml = """
            [[fruits]]
            name = "apple"
            [fruits.physical]
            color = "red"
            shape = "round"
            [[fruits.varieties]]
            name = "red delicious"
            [[fruits.varieties]]
            name = "granny smith"
            [[fruits]]
            name = "banana"
            [[fruits.varieties]]
            name = "plantain"
        """.trimIndent()
        assertEquals(
            Fruits(
                listOf(
                    FruitTbl("apple", Physical("red", "round"), listOf(Variety("red delicious"), Variety("granny smith"))),
                    FruitTbl("banana", null, listOf(Variety("plantain")))
                )
            ),
            Toml.decodeFromString<Fruits>(toml)
        )
    }

    @Serializable
    data class Plugin(val id: String, val version: Version)
    @Serializable
    data class Version(val ref: String)
    @Serializable
    data class Plugins(@SerialName("gradle-plugin") val plugin: Plugin)

    @Test
    fun decodeInlineTableWithDottedKey() {
        // inline table whose body contains a dotted key (version.ref) creating a nested table
        val toml = "gradle-plugin = { id = \"org.jetbrains.kotlin.jvm\", version.ref = \"kotlin\" }"
        assertEquals(
            Plugins(Plugin("org.jetbrains.kotlin.jvm", Version("kotlin"))),
            Toml.decodeFromString<Plugins>(toml)
        )
    }

    @Serializable
    data class InlineWrapper(val table: IntList)

    @Test
    fun inlineTableTrailingCommaThrows() {
        assertThrows(TomlDecodingException::class.java) {
            Toml.decodeFromString<InlineWrapper>("table = { a = [1], }")
        }
    }

    @Serializable
    data class MapHolder(val myMap: Map<String, String>)

    @Test
    fun decodeMap() {
        val toml = "[myMap]\n a = \"b\"\n c = \"d\"\n"
        assertEquals(MapHolder(mapOf("a" to "b", "c" to "d")), Toml.decodeFromString<MapHolder>(toml))
    }

    // ---------------------------------------------------------------------
    // partiallyDecodeFromString
    // ---------------------------------------------------------------------

    @Test
    fun partiallyDecodeNamedTable() {
        val toml = "[a.b]\n a = 5 \n b = 6\n [other]\n z = 1"
        assertEquals(Table1(5, 6), Toml.partiallyDecodeFromString<Table1>(Table1.serializer(), toml, "a.b"))
        assertThrows(TomlDecodingException::class.java) {
            Toml.partiallyDecodeFromString<Table1>(Table1.serializer(), toml, "a.missing")
        }
    }

    // ---------------------------------------------------------------------
    // Encoding
    // ---------------------------------------------------------------------

    @Serializable
    data class EncTable(val c: String = "value", val d: Boolean = false)
    @Serializable
    data class EncFile(val a: Long = 0, val table: EncTable = EncTable(), val b: List<Long> = listOf(1, 2, 3))

    @Serializable
    object Empty
    @Serializable
    data class WithEmptyObj(val obj: Empty = Empty)

    @Serializable
    data class NullDefaults(
        val present: Double = Double.NaN,
        val omitted: Double? = null
    )

    @Test
    fun encodeDocumentStructure() {
        // Core encoder layout contract, exercised together because a structural encoder
        // either lays a document out correctly or not. Each assertion isolates a facet so
        // a partial implementation still reveals which facet broke.

        // (1) scalars first, then [table] sections; scalar arrays inline as [ 1, 2, 3 ];
        //     table body indented four spaces; blank line before the header.
        val expected = """
            a = 0
            b = [ 1, 2, 3 ]

            [table]
                c = "value"
                d = false
        """.trimIndent()
        assertEquals(expected, Toml.encodeToString(EncFile()))

        // (2) an empty @Serializable object emits just its header, no body.
        assertEquals("[obj]", Toml.encodeToString(WithEmptyObj()))

        // (3) null-valued properties are omitted (ignoreNullValues default); NaN -> nan.
        assertEquals("present = nan", Toml.encodeToString(NullDefaults()))

        // (4) the emitted document round-trips back to an equal object.
        val original = EncFile(a = 42, table = EncTable(c = "hi", d = true), b = listOf(7, 8))
        assertEquals(original, Toml.decodeFromString<EncFile>(Toml.encodeToString(original)))
    }

    @Serializable
    data class DefaultOmit(val omitted: Boolean = false, val present: Boolean)

    @Test
    fun encodeIgnoreDefaultValues() {
        assertEquals(
            "present = true",
            Toml(outputConfig = TomlOutputConfig(ignoreDefaultValues = true)).encodeToString(DefaultOmit(present = true))
        )
    }

    @Serializable
    data class Radix(
        @TomlInteger(BINARY) val bin: Long = 2,
        @TomlInteger(GROUPED) val gro: Long = 9_999_099_009,
        @TomlInteger(HEX) val hex: Long = 4,
        @TomlInteger(OCTAL) val oct: Long = 6
    )

    @Test
    fun encodeIntegerRepresentations() {
        val expected = """
            bin = 0b10
            gro = 9_999_099_009
            hex = 0x4
            oct = 0o6
        """.trimIndent()
        assertEquals(expected, Toml.encodeToString(Radix()))
    }

    @Serializable
    data class Commented(
        @TomlComments("Single comment", inline = "")
        val a: Long = 3,
        @TomlComments(inline = "Inline comment")
        val c: Boolean = true
    )

    @Serializable
    data class LiteralStr(@TomlLiteral val a: String = "literal\tstring")

    @Test
    fun encodeCommentAndLiteralAnnotations() {
        // @TomlComments and @TomlLiteral are distinct annotation contracts; asserted
        // separately so an implementation handling one but not the other is visible.

        // (1) @TomlComments emits leading '# ' comment lines and/or a trailing inline comment.
        val expectedComments = """
            # Single comment
            a = 3
            c = true # Inline comment
        """.trimIndent()
        assertEquals(expectedComments, Toml.encodeToString(Commented()))

        // (2) @TomlLiteral emits the string as a single-quoted literal (no escaping).
        assertEquals("a = 'literal\tstring'", Toml.encodeToString(LiteralStr()))
    }

    @Test
    fun encodeRejectsControlCharInLiteralString() {
        @Serializable
        data class Bad(@TomlLiteral val a: String = "control \u0000 char")
        assertThrows(TomlEncodingException::class.java) {
            Toml.encodeToString(Bad())
        }
    }
}
