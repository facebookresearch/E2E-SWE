# Implement `ediflow`: a streaming EDI reader and validator (EDIFACT + X12)

## What you are building

You are implementing a Java library that reads and validates **Electronic Data Interchange (EDI)**
documents in the two dominant dialects — **ASC X12** and **UN/EDIFACT** — using a streaming,
pull-parser API modeled on StAX (`javax.xml.stream`). The library tokenizes a raw EDI byte stream
into an ordered event stream (interchange / group / transaction / loop / segment / composite /
element), and — when given a **schema** — validates structure and element content, reporting typed
errors as events in-line.

The library has three layers, and you must implement all three:

1. **Tokenizer / dialect layer.** Turn the raw characters of an EDI interchange into events. This
   includes inferring the delimiters from the dialect's service characters (X12's fixed-width `ISA`
   header; EDIFACT's optional `UNA`), and emitting composites, repetitions and released characters.
2. **Schema model + loader.** Parse a compact XML "EDISchema" describing interchanges, transactions,
   segments, composites, elements, loops, occurrence bounds, enumerations and data types.
3. **Validation engine.** Given a control schema and/or a transaction schema, validate segment
   sequence and occurrence (mandatory/optional, min/max, loops), and element content (data type,
   length, enumerated code values), surfacing each violation as an error event with a typed code.

Most of the difficulty is in implementing the exact tokenizer state transitions and the validation
semantics; EDI is an irregular format with many interacting special cases. The public types, package
names, method signatures, enum constant names, and string constants below are relied upon by a hidden
Java test suite that is compiled against your classes, so they must match **exactly**.

## Environment: where your code goes and how it is built

- Put your Java source under **`/app/src`**, in the package tree **`io/ediflow/...`**. The public API
  lives in `io.ediflow.stream` and `io.ediflow.schema`; you may place internal classes in any
  sub-packages you like (e.g. `io.ediflow.internal.*`) — only the public types below are relied upon.
- Create **`/app/setup.sh`** that compiles your code offline against the baked jars:
  ```bash
  LIB=/opt/staedi/lib
  CP=$(ls $LIB/*.jar | paste -sd:)
  mkdir -p /app/out
  find /app/src -name '*.java' -print0 | xargs -0 javac -cp "$CP" -d /app/out
  ```
  There is no internet during evaluation. The only external dependencies available (baked under
  `/opt/staedi/lib`) are the optional JSON-P APIs `jakarta.json-api`, `javax.json-api`, and
  `jackson-core` — you do **not** need them for the reader/validator/schema surface tested here (they
  matter only if you implement the optional JSON-output feature). Everything else you need is the JDK,
  including the StAX API in `javax.xml.stream` (module `java.xml`), which you should use to parse the
  EDISchema XML.

The grader compiles a test program against your compiled classes plus the baked jars, so your public
types, package names, method signatures, enum constant names, and string constant values must match
those described below exactly.

## Package `io.ediflow.stream` — the streaming reader API

### `EDIInputFactory` (abstract class)
```java
public abstract class EDIInputFactory {
    public static EDIInputFactory newFactory();                 // returns a working factory instance
    public abstract EDIStreamReader createEDIStreamReader(java.io.InputStream stream);
    public abstract EDIStreamReader createEDIStreamReader(java.io.InputStream stream, io.ediflow.schema.Schema schema);
    public abstract void setProperty(String name, Object value);
    public abstract Object getProperty(String name);
    // Feature toggle key (exact string value matters):
    public static final String EDI_VALIDATE_CONTROL_STRUCTURE = "io.ediflow.stream.EDI_VALIDATE_CONTROL_STRUCTURE";
}
```
- `createEDIStreamReader(stream)` yields a reader that tokenizes without validation unless a schema is
  later supplied. `createEDIStreamReader(stream, schema)` uses `schema` as the **control schema**
  (interchange/group/transaction envelope) and validates the envelope as it reads.
- `EDI_VALIDATE_CONTROL_STRUCTURE` defaults to `true`. Setting it to `"false"` disables automatic
  control-structure validation, so a reader created without a schema performs a pure structural parse.

### `EDIStreamReader` (interface, extends `java.io.Closeable`)
```java
public interface EDIStreamReader extends java.io.Closeable {
    boolean         hasNext();
    EDIStreamEvent  next();
    EDIStreamEvent  getEventType();
    String          getText();                          // segment tag / element value / offending text
    java.util.Map<String, Character> getDelimiters();   // valid only from START_INTERCHANGE onward
    String          getStandard();                      // "X12" | "EDIFACT"
    String[]        getVersion();
    EDIStreamValidationError getErrorType();            // valid only on *_ERROR events
    void            setControlSchema(io.ediflow.schema.Schema schema);      // valid at START_INTERCHANGE
    void            setTransactionSchema(io.ediflow.schema.Schema schema);  // valid from START_TRANSACTION
    void            close();
}
```
- Iterate with `while (reader.hasNext()) { EDIStreamEvent e = reader.next(); ... }`.
- Calling `getDelimiters()`, `getStandard()`, or `getVersion()` **before** the first event
  (`START_INTERCHANGE`) must throw `java.lang.IllegalStateException`.
- `getStandard()` returns exactly `"X12"` or `"EDIFACT"`. `getVersion()` returns the dialect version
  tokens: for X12 a single-element array of the `ISA12` interchange-version (e.g. `["00501"]`); for
  EDIFACT the `UNB` syntax identifier + version (e.g. `["UNOA", "1"]`).
- `getText()` returns the segment tag on `START_SEGMENT`, the element value on `ELEMENT_DATA`, and the
  offending token on the three `*_ERROR` events.
- On an `*_ERROR` event, `getErrorType()` returns the specific `EDIStreamValidationError`.
- `getDelimiters()` returns a map keyed by these **exact** strings (values are the actual delimiter
  characters discovered in the input):
  ```
  io.ediflow.stream.delim.segment
  io.ediflow.stream.delim.dataElement
  io.ediflow.stream.delim.componentElement
  io.ediflow.stream.delim.repetition
  io.ediflow.stream.delim.release
  io.ediflow.stream.delim.decimal
  ```
  Include only the keys that apply to the dialect/version (e.g. X12 has `repetition` from version
  00402+ and no `release`; EDIFACT has `release` and no `repetition` below syntax version 4). All
  dialects report `decimal` (`.` by default).

### `EDIStreamEvent` (enum)
Constant names must be exactly:
```java
public enum EDIStreamEvent {
    START_INTERCHANGE, END_INTERCHANGE, START_GROUP, END_GROUP,
    START_TRANSACTION, END_TRANSACTION, START_LOOP, END_LOOP,
    START_SEGMENT, END_SEGMENT, START_COMPOSITE, END_COMPOSITE,
    ELEMENT_DATA, ELEMENT_DATA_BINARY,
    SEGMENT_ERROR, ELEMENT_DATA_ERROR, ELEMENT_OCCURRENCE_ERROR;
    public boolean isError();   // true for the three *_ERROR constants
}
```
Event ordering for a well-formed document: `START_INTERCHANGE`; for each segment `START_SEGMENT`,
then its elements (`ELEMENT_DATA`, with `START_COMPOSITE`/`END_COMPOSITE` around a composite's
components), then `END_SEGMENT`; `START_GROUP`/`END_GROUP` around an X12 functional group (GS/GE);
`START_TRANSACTION`/`END_TRANSACTION` around a transaction (by default ST/SE, or UNH/UNT — see the
control schema's `header`/`trailer` attributes); `START_LOOP`/`END_LOOP` around a schema-defined
loop; finally `END_INTERCHANGE`. (EDIFACT has no group unless `UNG`/`UNE`
appear.) A validation violation is reported as the corresponding `*_ERROR` event, emitted in stream
order at the point of the offending segment/element.

### `EDIStreamValidationError` (enum)
Constant names must be exactly (at least these, used by the tests):
```
MANDATORY_SEGMENT_MISSING, UNEXPECTED_SEGMENT, SEGMENT_EXCEEDS_MAXIMUM_USE,
SEGMENT_NOT_IN_DEFINED_TRANSACTION_SET, LOOP_OCCURS_OVER_MAXIMUM_TIMES,
REQUIRED_DATA_ELEMENT_MISSING, TOO_MANY_DATA_ELEMENTS,
DATA_ELEMENT_TOO_LONG, DATA_ELEMENT_TOO_SHORT, INVALID_CHARACTER_DATA,
INVALID_CODE_VALUE, INVALID_DATE, INVALID_TIME,
CONTROL_REFERENCE_MISMATCH, CONTROL_COUNT_DOES_NOT_MATCH_ACTUAL_COUNT,
CONDITIONAL_REQUIRED_DATA_ELEMENT_MISSING, EXCLUSION_CONDITION_VIOLATED
```
The segment-level errors (`MANDATORY_SEGMENT_MISSING`, `UNEXPECTED_SEGMENT`,
`SEGMENT_EXCEEDS_MAXIMUM_USE`, `SEGMENT_NOT_IN_DEFINED_TRANSACTION_SET`, `LOOP_OCCURS_OVER_MAXIMUM_TIMES`)
surface as `SEGMENT_ERROR` events; the element-content errors (`DATA_ELEMENT_TOO_LONG`,
`DATA_ELEMENT_TOO_SHORT`, `INVALID_CHARACTER_DATA`, `INVALID_CODE_VALUE`, `INVALID_DATE`,
`INVALID_TIME`) and the control-structure errors (`CONTROL_REFERENCE_MISMATCH`,
`CONTROL_COUNT_DOES_NOT_MATCH_ACTUAL_COUNT`) surface as `ELEMENT_DATA_ERROR`; occurrence errors
(`REQUIRED_DATA_ELEMENT_MISSING`, `TOO_MANY_DATA_ELEMENTS`) and the syntax-rule errors
(`CONDITIONAL_REQUIRED_DATA_ELEMENT_MISSING`, `EXCLUSION_CONDITION_VIOLATED`) surface as
`ELEMENT_OCCURRENCE_ERROR`.

## Package `io.ediflow.stream` — the streaming writer API

The library must also **produce** EDI, mirroring the reader. Writing is a fluent, StAX-style push API.

### `EDIOutputFactory` (abstract class)
```java
public abstract class EDIOutputFactory {
    public static EDIOutputFactory newFactory();                             // returns a working factory instance
    public abstract EDIStreamWriter createEDIStreamWriter(java.io.OutputStream stream);              // UTF-8
    public abstract EDIStreamWriter createEDIStreamWriter(java.io.OutputStream stream, String encoding);
    // Feature toggle key (exact string value matters):
    public static final String PRETTY_PRINT = "io.ediflow.stream.PRETTY_PRINT";
}
```
- `createEDIStreamWriter(stream)` writes UTF-8 to the given `OutputStream`.
- `PRETTY_PRINT` defaults to `false`: **no** line separator is written after each segment terminator, so
  the output of a well-formed interchange is a single unbroken line of segments.

### `EDIStreamWriter` (interface, extends `java.lang.AutoCloseable`)
```java
public interface EDIStreamWriter extends AutoCloseable {
    EDIStreamWriter startInterchange();               // enter the initial interchange-writing state
    EDIStreamWriter endInterchange();                 // finish the interchange; flushes pending output
    EDIStreamWriter writeStartSegment(String name);   // begin a segment and write its tag
    EDIStreamWriter writeEndSegment();                // write the segment terminator
    EDIStreamWriter writeStartElement();              // begin a (simple or composite) element
    EDIStreamWriter endElement();                     // end the current element
    EDIStreamWriter writeElement(CharSequence text);  // = writeStartElement + writeElementData + endElement
    EDIStreamWriter writeElementData(CharSequence text); // append text to the element currently open
    EDIStreamWriter writeEmptyElement();              // = writeStartElement + endElement (no data)
    EDIStreamWriter writeRepeatElement();             // write the repetition separator, ready for more data
    EDIStreamWriter startComponent();                 // begin a component inside the open element
    EDIStreamWriter endComponent();                   // end the current component
    EDIStreamWriter writeComponent(CharSequence text);// = startComponent + writeElementData + endComponent
    EDIStreamWriter writeEmptyComponent();            // = startComponent + endComponent (no data)
    String          getStandard();                    // "X12" | "EDIFACT" once the header is fully written
    java.util.Map<String, Character> getDelimiters(); // valid once the standard is determined
    void            flush();                          // flush pending output to the stream
    void            close();                          // flush + free resources; does NOT close the stream
}
```
Each mutating method returns the same `EDIStreamWriter` so calls chain fluently. Methods must be called
in a valid sequence for the writer's state; an out-of-sequence call throws `IllegalStateException`, and
`getStandard()`/`getDelimiters()` before the header is written throw `IllegalStateException`.

- **Delimiters** are the same defaults as the reader. For **X12** they are inferred from the fixed-width
  106-char `ISA` you write (element `*`, component `:`, repetition `^`, segment terminator `~`), which
  match the defaults; the first segment written must be a complete, well-formed `ISA` (16 elements). For
  **EDIFACT** the first segment written is `UNB`, whose first element is the composite syntax identifier
  `UNOA:4` (`writeStartElement().writeComponent("UNOA").writeComponent("4").endElement()`); with no
  delimiter properties set, the `UNOA` defaults apply (element `+`, component `:`, segment terminator `'`).
- The dialect is chosen from the first segment tag (`ISA` → X12, `UNB` → EDIFACT).
- The **trailing segment terminator is always emitted** (X12 output ends with `~`, EDIFACT with `'`).
- A composite element is written as `writeStartElement()`, one or more `writeComponent(...)`
  (or `writeEmptyComponent()`), then `endElement()`; its components are joined by the component separator.
- `close()` flushes buffered output but must leave the underlying `OutputStream` open.

## Package `io.ediflow.schema` — the schema model + loader

```java
public interface SchemaFactory {
    static SchemaFactory newFactory();
    Schema createSchema(java.io.InputStream stream) throws EDISchemaException;
}
public interface Schema extends Iterable<EDIType> {
    EDIType getType(String name);      // the named segment/element/composite type, or null
}
public interface EDIType {
    enum Type { INTERCHANGE, GROUP, TRANSACTION, LOOP, SEGMENT, COMPOSITE, ELEMENT }
    String getId();
    Type getType();
}
public class EDISchemaException extends Exception { /* thrown on malformed / unrecognized schema XML */ }
```
`EDISchemaException` must be named exactly `io.ediflow.schema.EDISchemaException` (its simple name is
compared by the tests).

### The EDISchema XML format your loader must accept

`createSchema` reads XML (use the JDK StAX `javax.xml.stream.XMLInputFactory`). The root element is
`<schema>` in one of these namespaces, which select the attribute dialect for references:

- **v4**: `xmlns="http://ediflow.io/EDISchema/v4"` — references use the **`type`** attribute.
- **v3**: `xmlns="http://ediflow.io/EDISchema/v3"` — references use the **`ref`** attribute.

Vocabulary (a `<schema>` contains reusable type definitions plus at most one `<interchange>` and/or
one `<transaction>`):

- `<interchange header="ISA" trailer="IEA" headerRefPosition=".." trailerRefPosition=".." trailerCountPosition=".." countType="controls|segments">` `<sequence>` … `</sequence>` `</interchange>` — the
  control envelope; its `<sequence>` holds `<transaction header="S01" trailer="S09" use="required"/>`
  and/or `<group header="GS" trailer="GE" headerRefPosition=".." trailerRefPosition=".." trailerCountPosition=".." countType="..">` `<transaction .../>` `</group>` — a `<group>` holds its
  `<transaction>` **directly** (unlike the `<interchange>`, a `<group>` has no nested `<sequence>`).
  On any of these three control structures the `header`/`trailer` attributes name the envelope's
  boundary **segments**, and they are what the reader matches while a control schema is in effect: a
  segment whose tag equals a declared `header` opens that envelope (emitting `START_INTERCHANGE` /
  `START_GROUP` / `START_TRANSACTION`) and one equal to its `trailer` closes it (`END_*`), whatever
  that tag is; the dialect's conventional envelope segments are only the fallback used when no
  control schema names them. The `*RefPosition` attributes are the 1-based element positions of the
  control number in the header vs trailer segment (unequal → `CONTROL_REFERENCE_MISMATCH`);
  `trailerCountPosition` is the trailer element holding the count and `countType` is whether it
  counts child envelopes (`controls`) or all segments incl. header+trailer (`segments`) (mismatch vs
  actual → `CONTROL_COUNT_DOES_NOT_MATCH_ACTUAL_COUNT`).
  These control checks run when `EDI_VALIDATE_CONTROL_STRUCTURE` is true (default) and a control
  schema is set; the offending trailer value is `getText()`.
- `<transaction>` `<sequence>` … `</sequence>` `</transaction>` — the business structure; its
  `<sequence>` holds `<segment ref="S11" minOccurs=".." maxOccurs=".."/>` (v3) or
  `<segment type="S11" .../>` (v4), and `<loop code="L0000" minOccurs=".." maxOccurs="..">`
  `<sequence>…</sequence>` `</loop>`.
- `<segmentType name="S11">` `<sequence>` `<element ref="E999" minOccurs=".."/>` (or `type=` in v4),
  `<composite ref="C1" .../>` … `</sequence>` `</segmentType>`.
- `<compositeType name="C1">` `<sequence>` `<element .../>` … `</sequence>` `</compositeType>`.
- `<elementType name="E1" base="string" minLength="1" maxLength="5">` with optional
  `<enumeration><value>AA</value><value>BB</value></enumeration>` `</elementType>`. The `base` is one
  of: `string`, `numeric`, `decimal`, `date`, `time`, `binary`, `identifier`.
- `<segmentType>` and `<compositeType>` may carry positional **syntax rules** *after* their
  `<sequence>`: `<syntax type="paired|required|exclusion|conditional|single|list|firstonly">`
  `<position>N</position>…</syntax>`, where each `<position>` is a 1-based index into the enclosing
  sequence's elements (the first listed position is the "anchor").

Defaults: a `<segment>`/`<element>`/`<loop>` reference has `minOccurs="0"` (optional) and
`maxOccurs="1"` unless stated; `<elementType>` `minLength`/`maxLength` default to `1`. Malformed XML,
an unrecognized root namespace, or an unknown element must cause `createSchema` to throw
`EDISchemaException`.

## Validation semantics

When a control schema is set (via `createEDIStreamReader(stream, schema)` or `setControlSchema`) and
a transaction schema via `setTransactionSchema(schema)` (call it upon receiving `START_TRANSACTION`),
validate as you read:

- **Segment sequence & occurrence** (against the transaction schema): a segment appearing where the
  schema does not allow it → `UNEXPECTED_SEGMENT`; a segment tag not defined anywhere in the
  transaction → `SEGMENT_NOT_IN_DEFINED_TRANSACTION_SET`; a mandatory segment (minOccurs ≥ 1) not
  present when its position is passed → `MANDATORY_SEGMENT_MISSING`; a segment used more than its
  `maxOccurs` → `SEGMENT_EXCEEDS_MAXIMUM_USE`; a loop entered more than its `maxOccurs` →
  `LOOP_OCCURS_OVER_MAXIMUM_TIMES`. `getText()` is the offending (or missing) segment tag.
  A segment reported `UNEXPECTED_SEGMENT` is discarded and does not satisfy any schema position, so
  a mandatory segment with the same tag reached later in the sequence is still reported
  `MANDATORY_SEGMENT_MISSING`.
- **Element occurrence** (checked against the segment's `segmentType` element sequence): a segment
  carrying more data elements than its `segmentType` defines → `TOO_MANY_DATA_ELEMENTS`; a required
  element (`minOccurs` ≥ 1) that is absent → `REQUIRED_DATA_ELEMENT_MISSING`.
- **Element content** (against the element's type): value longer than `maxLength` →
  `DATA_ELEMENT_TOO_LONG`; shorter than `minLength` → `DATA_ELEMENT_TOO_SHORT`; a `numeric` element
  containing a non-digit → `INVALID_CHARACTER_DATA`; an `identifier`/coded element whose value is not
  in its `<enumeration>` → `INVALID_CODE_VALUE`; a `date` value that is not a valid calendar date
  (correct length, month 1–12, day valid for month incl. leap years) → `INVALID_DATE`; a `time` value that
  is not a valid clock time — it contains a non-digit character, or its hour > 23, minute > 59, or
  (when seconds are present) second > 59 → `INVALID_TIME`. `getText()` is the offending value. When one segment's
  data has several bad elements, emit one `ELEMENT_DATA_ERROR` per bad element, in element order.
- **Control structure** (against the control schema's interchange/group/transaction `*RefPosition` +
  count attributes): a trailer control number that differs from its header value →
  `CONTROL_REFERENCE_MISMATCH`; a trailer count that differs from the actual count (`countType="controls"`
  = number of child envelopes; `"segments"` = all segments incl. header+trailer) →
  `CONTROL_COUNT_DOES_NOT_MATCH_ACTUAL_COUNT`. Both surface as `ELEMENT_DATA_ERROR` on the offending
  trailer element (`getText()` = its value); leading zeros are ignored when comparing counts.
- **Element syntax rules** (a segment/composite `<syntax>`, over its listed 1-based positions; used =
  the element at that position is present): `paired` → if some-but-not-all listed positions are used;
  `required` → if none are used; `conditional` → if the anchor (first position) is used but not all of
  the rest; each emits `CONDITIONAL_REQUIRED_DATA_ELEMENT_MISSING` once per unused listed position.
  `exclusion` → if more than one listed position is used, emitting `EXCLUSION_CONDITION_VIOLATED` once
  per used position beyond the first. `list` → if the anchor (first position) is used, at least one of
  the other listed positions must also be used; when only the anchor is used, emit
  `CONDITIONAL_REQUIRED_DATA_ELEMENT_MISSING` once per unused listed position. `single` → exactly one
  listed position may be used: more than one errors like `exclusion`, none used emits
  `CONDITIONAL_REQUIRED_DATA_ELEMENT_MISSING` once per unused listed position. `firstonly` → if the
  anchor is used, none of the other listed positions may be, emitting `EXCLUSION_CONDITION_VIOLATED`
  once per used position beyond the first. All surface as `ELEMENT_OCCURRENCE_ERROR`; `getText()`
  may be empty (a missing element has no data) — the location's segment tag + element position
  identify it.
- **Element content** for a `decimal` element with non-decimal characters → `INVALID_CHARACTER_DATA`.

## Dialect / tokenizer specifics

- **X12**: the interchange begins with a fixed-width `ISA` segment exactly 106 characters long
  (including the segment terminator). Element separator = the char at index 3; the repetition
  separator = `ISA11`; the component separator = `ISA16`; the segment terminator = the character
  immediately after `ISA16`. By default `GS`/`GE` bound a functional group and `ST`/`SE` bound a
  transaction (a control schema's declared `header`/`trailer` tags take precedence).
- **EDIFACT**: an optional `UNA` service-string-advice segment (`UNA` + 6 chars: component, element,
  decimal, release, reserved-space, segment terminator) sets the delimiters; without it the defaults
  for the `UNOA` syntax apply (component `:`, element `+`, decimal `.`, release `?`, segment `'`).
  When present, `UNA` is itself surfaced to the reader as a segment: a `START_SEGMENT` with tag
  `UNA`, then a single `ELEMENT_DATA` whose text is the two service-advice characters that are not
  themselves delimiters — the decimal-notation character followed by the reserved (spacing) character
  — then `END_SEGMENT`. By default `UNB`/`UNZ` bound the interchange and `UNH`/`UNT` a message
  (transaction). The release character escapes the following delimiter so it is treated as data.

## Scope

Implement the complete public surface above — the streaming reader (tokenizer + dialects for X12 and
EDIFACT), the EDISchema loader (v3 and v4), the schema-driven validation engine (segment/element
occurrence, element data-types, positional **syntax rules**, **and control-structure reference/count**),
and the streaming writer (`EDIOutputFactory` / `EDIStreamWriter`, producing X12 and EDIFACT) — plus the supporting
classes they require. You may organize internal classes however you like; only the public
types, packages, method signatures, enum constant names, and string constants named here are relied
upon by the tests. Behavior must follow the ASC X12 and UN/EDIFACT interchange conventions described
above.
