#!/usr/bin/env python3
"""
Transform the upstream multiplatform ktoml-core sources (commonMain + jvmMain,
flattened into one JVM source tree) into a JVM-only tree that builds OFFLINE with
kotlinc directly, with no kotlinx-datetime dependency.

This is the ground-truth solution's offline adaptation. It is exactly the kind of
adaptation the task asks the agent to perform (JVM-only, no kotlinx-datetime
datetime decoding; datetimes are recognized at the grammar level and stored as
strings). It does NOT change parsing/decoding/encoding behavior for any value
type the hidden tests exercise.

Usage: python3 patch_offline.py <src_root>
  <src_root> contains com/akuleshov7/ktoml/...
"""
import os
import re
import sys

ROOT = sys.argv[1]


def read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def write(p, s):
    with open(p, "w", encoding="utf-8") as f:
        f.write(s)


def path(*parts):
    return os.path.join(ROOT, "com", "akuleshov7", "ktoml", *parts)


# ---------------------------------------------------------------------------
# 1. Fold the two expect/actual declarations into plain JVM functions.
#    - Remove the `expect` decls in Utils.kt / SpecialCharacters.kt and the
#      `actual` impls in UtilsJvm.kt; provide concrete JVM bodies in-place.
# ---------------------------------------------------------------------------

# Utils.kt: replace `internal expect fun StringBuilder.appendCodePointCompat(...)`
utils = read(path("utils", "Utils.kt"))
utils = utils.replace(
    "@Throws(IllegalArgumentException::class)\n"
    "internal expect fun StringBuilder.appendCodePointCompat(codePoint: Int): StringBuilder",
    "@Throws(IllegalArgumentException::class)\n"
    "internal fun StringBuilder.appendCodePointCompat(codePoint: Int): StringBuilder = appendCodePoint(codePoint)",
)
write(path("utils", "Utils.kt"), utils)

# SpecialCharacters.kt: replace the trailing `public expect fun newLineChar(): Char`
sc = read(path("utils", "SpecialCharacters.kt"))
sc = sc.replace(
    "public expect fun newLineChar(): Char",
    "public fun newLineChar(): Char = '\\n'",
)
write(path("utils", "SpecialCharacters.kt"), sc)

# Drop the JVM actuals file (its definitions now live in the common files).
jvm_utils = path("utils", "UtilsJvm.kt")
if os.path.exists(jvm_utils):
    os.remove(jvm_utils)

# Toml.kt: @ThreadLocal is a Kotlin/Native-only caching annotation; drop it for JVM.
toml = read(path("Toml.kt"))
toml = toml.replace("import kotlin.native.concurrent.ThreadLocal\n", "")
toml = toml.replace("    @ThreadLocal\n", "")
write(path("Toml.kt"), toml)


# ---------------------------------------------------------------------------
# 2. Remove the kotlinx-datetime dependency.
#    TomlDateTime stores the raw datetime text (String) after validating its
#    grammar. The decoder/encoder datetime-type branches are removed (datetime
#    decoding into concrete date types is out of scope). The emitter emits the
#    stored string.
# ---------------------------------------------------------------------------

# TomlDateTime.kt — full rewrite: grammar-validating, String-backed value node.
toml_datetime = '''package com.akuleshov7.ktoml.tree.nodes.pairs.values

import com.akuleshov7.ktoml.TomlOutputConfig
import com.akuleshov7.ktoml.writers.TomlEmitter

/**
 * TOML AST node for date-time values (offset date-time, local date-time, local
 * date, local time). The raw text is validated against the TOML datetime grammar
 * and stored as a String. (Decoding into concrete date/time types is out of scope
 * for this JVM-only, offline build.)
 *
 * @property content the validated raw datetime text
 */
public class TomlDateTime
internal constructor(
    override var content: Any
) : TomlValue() {
    public constructor(content: String, lineNo: Int) : this(content.trim().validateDateTime())

    override fun write(
        emitter: TomlEmitter,
        config: TomlOutputConfig
    ) {
        emitter.emitValue(content as String)
    }

    public companion object {
        // RFC3339-style grammar fragments
        private const val DATE = "\\\\d{4}-\\\\d{2}-\\\\d{2}"
        private const val TIME = "\\\\d{2}:\\\\d{2}:\\\\d{2}(\\\\.\\\\d+)?"
        private const val OFFSET = "(Z|[+-]\\\\d{2}:\\\\d{2})"
        private val OFFSET_DATE_TIME = Regex("$DATE[T ]$TIME$OFFSET")
        private val LOCAL_DATE_TIME = Regex("$DATE[T ]$TIME")
        private val LOCAL_DATE = Regex(DATE)
        private val LOCAL_TIME = Regex(TIME)

        private fun String.validateDateTime(): String {
            if (OFFSET_DATE_TIME.matches(this) ||
                LOCAL_DATE_TIME.matches(this) ||
                LOCAL_DATE.matches(this) ||
                LOCAL_TIME.matches(this)
            ) {
                return this
            }
            // Not a valid datetime grammar: signal via IllegalArgumentException so the
            // value-parsing factory falls back to its next candidate (basic string).
            throw IllegalArgumentException("Not a valid TOML datetime: <$this>")
        }
    }
}
'''
write(path("tree", "nodes", "pairs", "values", "TomlDateTime.kt"), toml_datetime)

# TomlEmitter.kt — drop kotlinx-datetime imports and the four datetime emit overloads;
# keep a single emitValue(String) used for datetime text (already exists for strings).
emitter = read(path("writers", "TomlEmitter.kt"))
emitter = re.sub(r"import kotlin\.time\.ExperimentalTime\n", "", emitter)
emitter = re.sub(r"import kotlin\.time\.Instant\n", "", emitter)
emitter = re.sub(r"import kotlinx\.datetime\.LocalDate\n", "", emitter)
emitter = re.sub(r"import kotlinx\.datetime\.LocalDateTime\n", "", emitter)
emitter = re.sub(r"import kotlinx\.datetime\.LocalTime\n", "", emitter)
# Remove the four datetime emitValue overloads (Instant/LocalDateTime/LocalDate/LocalTime).
for typ, arg in [
    ("Instant", "instant"),
    ("LocalDateTime", "dateTime"),
    ("LocalDate", "date"),
    ("LocalTime", "time"),
]:
    emitter = re.sub(
        r"\n[ \t]*/\*\*[^/]*?\*/\n[ \t]*@OptIn\(ExperimentalTime::class\)[ \t]*\n"
        r"[ \t]*public fun emitValue\(\w+: " + typ + r"\): TomlEmitter = emit\([^\n]*\)\n",
        "\n",
        emitter,
    )
    # Fallback: handle overloads without the @OptIn line.
    emitter = re.sub(
        r"\n[ \t]*/\*\*[^/]*?\*/\n"
        r"[ \t]*public fun emitValue\(\w+: " + typ + r"\): TomlEmitter = emit\([^\n]*\)\n",
        "\n",
        emitter,
    )
write(path("writers", "TomlEmitter.kt"), emitter)

# TomlAbstractDecoder.kt — drop datetime imports, serializers, isDateTime branch usage.
dec = read(path("decoders", "TomlAbstractDecoder.kt"))
dec = re.sub(r"import kotlin\.time\.ExperimentalTime\n", "", dec)
dec = re.sub(r"[ \t]*@OptIn\(ExperimentalTime::class\)\n", "", dec)
dec = re.sub(r"import kotlin\.time\.Instant\n", "", dec)
dec = re.sub(r"import kotlinx\.datetime\.LocalDate\n", "", dec)
dec = re.sub(r"import kotlinx\.datetime\.LocalDateTime\n", "", dec)
dec = re.sub(r"import kotlinx\.datetime\.LocalTime\n", "", dec)
dec = dec.replace("    private val instantSerializer = Instant.serializer()\n", "")
dec = dec.replace("    private val localDateTimeSerializer = LocalDateTime.serializer()\n", "")
dec = dec.replace("    private val localDateSerializer = LocalDate.serializer()\n", "")
dec = dec.replace("    private val localTimeSerializer = LocalTime.serializer()\n", "")
# isDateTime() now always false (no datetime-typed decoding in scope).
# (The class-level @OptIn(ExperimentalTime::class) lines were already stripped above.)
dec = dec.replace(
    "    protected fun DeserializationStrategy<*>.isDateTime(): Boolean =\n"
    "        descriptor == instantSerializer.descriptor ||\n"
    "                descriptor == localDateTimeSerializer.descriptor ||\n"
    "                descriptor == localDateSerializer.descriptor ||\n"
    "                descriptor == localTimeSerializer.descriptor\n",
    "    protected fun DeserializationStrategy<*>.isDateTime(): Boolean = false\n",
)
# Drop the four datetime cases in decodeSerializableValue.
dec = dec.replace(
    "            instantSerializer.descriptor -> decodePrimitiveType<Instant>() as T\n"
    "            localDateTimeSerializer.descriptor -> decodePrimitiveType<LocalDateTime>() as T\n"
    "            localDateSerializer.descriptor -> decodePrimitiveType<LocalDate>() as T\n"
    "            localTimeSerializer.descriptor -> decodePrimitiveType<LocalTime>() as T\n\n",
    "",
)
write(path("decoders", "TomlAbstractDecoder.kt"), dec)

# TomlAbstractEncoder.kt — drop datetime imports/descriptors and the datetime appendValue branch.
enc = read(path("encoders", "TomlAbstractEncoder.kt"))
enc = re.sub(r"import kotlin\.time\.ExperimentalTime\n", "", enc)
enc = re.sub(r"[ \t]*@OptIn\(ExperimentalTime::class\)\n", "", enc)
enc = re.sub(r"import kotlin\.time\.Instant\n", "", enc)
enc = re.sub(r"import kotlinx\.datetime\.LocalDate\n", "", enc)
enc = re.sub(r"import kotlinx\.datetime\.LocalDateTime\n", "", enc)
enc = re.sub(r"import kotlinx\.datetime\.LocalTime\n", "", enc)
enc = enc.replace("    private val instantDescriptor = Instant.serializer().descriptor\n", "")
enc = enc.replace("    private val localDateTimeDescriptor = LocalDateTime.serializer().descriptor\n", "")
enc = enc.replace("    private val localDateDescriptor = LocalDate.serializer().descriptor\n", "")
enc = enc.replace("    private val localTimeDescriptor = LocalTime.serializer().descriptor\n", "")
# Drop the datetime branch in encodeSerializableValue's when().
enc = enc.replace(
    "            instantDescriptor,\n"
    "            localDateTimeDescriptor,\n"
    "            localDateDescriptor,\n"
    "            localTimeDescriptor -> if (!encodeAsKey(value as Any, desc.serialName)) {\n"
    "                appendValue(TomlDateTime(value))\n"
    "            }\n",
    "",
)
write(path("encoders", "TomlAbstractEncoder.kt"), enc)

print("patch_offline.py: done")
