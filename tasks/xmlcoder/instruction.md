# XMLCoder

Implement **XMLCoder**, a Swift library that encodes and decodes XML using Swift's standard
`Codable` protocols. It mirrors the design of Foundation's `JSONEncoder` / `JSONDecoder`: users
make their types `Encodable` / `Decodable` and convert to/from XML `Data` through two top-level
types, `XMLEncoder` and `XMLDecoder`, tuning behavior through strategy properties.

## Requirements

- Pure Swift, building with SwiftPM as a single library module named **`XMLCoder`** (importable as
  `import XMLCoder`). Depends only on `Foundation` (and `FoundationXML` on Linux, where XML parsing
  lives in a separate module — guard it with `#if canImport(FoundationXML)`).
- All types listed below are `public`. Lay your sources under `Sources/XMLCoder/`.
- Parsing is built on Foundation's event-driven `XMLParser`.

```swift
import XMLCoder
import Foundation

struct Note: Codable {
    let to: String
    let from: String
    let heading: String
    let body: String
}

let note = try XMLDecoder().decode(Note.self, from: Data(sourceXML.utf8))
let xml  = try XMLEncoder().encode(note, withRootKey: "note")
```

---

## XMLEncoder

`open class XMLEncoder` with a public `init()` and:

```swift
open func encode<T: Encodable>(_ value: T,
                               withRootKey rootKey: String? = nil,
                               rootAttributes: [String: String]? = nil,
                               header: XMLHeader? = nil,
                               doctype: XMLDocumentType? = nil) throws -> Data
```

- The result is UTF-8 `Data`.
- When `rootKey` is `nil`, the root element name is the encoded **type's name** (`"\(T.self)"`),
  after applying `keyEncodingStrategy`. E.g. encoding a `TopContainer` value yields `<TopContainer>…`.
- A non-`nil` `rootKey` is used as the root element name verbatim: `keyEncodingStrategy` rewrites
  coding keys and the type-derived root name above, never a caller-supplied `rootKey`.
- `rootAttributes` are extra attributes written on the root element (see *Root attributes* below).
- `header` / `doctype`, when non-nil, are emitted before the root element.

### Encoder options (properties)

The encoder's option and strategy enums below are **nested member types of `XMLEncoder`**: each is
written unqualified here, as it reads from inside the class, and is spelled `XMLEncoder.<Name>` from
outside it.

- `outputFormatting: OutputFormatting` — an `OptionSet` (default `[]`) with:
  - `.prettyPrinted` — human-readable indented output.
  - `.sortedKeys` — element/attribute keys emitted in ascending lexicographic order. Since Swift
    dictionaries have no stable order, this option is what makes dictionary and multi-attribute
    output deterministic.
  - `.noEmptyElements` — write `<x></x>` instead of the self-closing `<x />` for empty elements.
- `prettyPrintIndentation: PrettyPrintIndentation` — default `.spaces(4)`. The enum has
  `case spaces(Int)` and `case tabs(Int)`; the indentation unit is repeated once per nesting depth.
- `charactersEscapedInElements: [(String, String)]` and
  `charactersEscapedInAttributes: [(String, String)]` — ordered (find, replace) pairs applied to
  text in elements and attribute values respectively. Both default to escaping, in this order:
  `&`→`&amp;`, `<`→`&lt;`, `>`→`&gt;`, `'`→`&apos;`, `"`→`&quot;`. Assigning `[]` disables escaping;
  users may append pairs (e.g. `("\n", "&#10;")`).
- `keyEncodingStrategy: KeyEncodingStrategy` — see *Key strategies*.
- `nodeEncodingStrategy: NodeEncodingStrategy` — see *Node coding*.
- `dateEncodingStrategy`, `dataEncodingStrategy`, `nonConformingFloatEncodingStrategy`,
  `stringEncodingStrategy` — see *Value strategies*.
- `userInfo: [CodingUserInfoKey: Any]`.

### Output shape

- A struct/class is encoded as an element whose children are its properties (element children by
  default). A scalar property `x` with value `v` becomes `<x>v</x>`.
- An **empty element** (a value with no children/text) is self-closing: `<container />`. A property
  whose string value is empty renders as `<value></value>` (open/close, not self-closing).
- Arrays repeat the element: `[String]` under key `value` → `<value>…</value><value>…</value>`.
- `Data` defaults to Base64 text; `Bool` renders as `true`/`false`.
- A `URL` codes as its absolute string — a single text value, `<link>http://example.com</link>` (or
  `link="http://example.com"` in attribute form) — and decodes back via `URL(string:)`.

Pretty-printed example — `TopContainer(nested: NestedContainer(values: ["foor", "bar"]))` with
`.prettyPrinted` and default indentation:

```xml
<TopContainer>
    <nested>
        <values>foor</values>
        <values>bar</values>
    </nested>
</TopContainer>
```

Pretty-printed output has no trailing newline and no header unless one is supplied.

---

## XMLDecoder

`open class XMLDecoder` with:

```swift
public init(trimValueWhitespaces: Bool = true, removeWhitespaceElements: Bool = false)
open func decode<T: Decodable>(_ type: T.Type, from data: Data) throws -> T
```

Decoding invalid/malformed XML throws.

When decoding a `[T]` array or `[String: T]` dictionary property, an element that contains no
matching child elements decodes to an **empty collection** (`[]` / `[:]`) rather than throwing —
e.g. `<container/>` decodes a `value: [String]` / `value: [String: Int]` property to `[]` / `[:]`,
and a key whose name matches nothing present (for instance because `shouldProcessNamespaces` renamed
the elements) likewise yields an empty collection. An optional value with no source decodes to `nil`.
A required scalar with no source throws. Within a repeated-element list, an **empty element**
`<value/>` contributes an empty string `""` (not `nil`) — e.g. `<container><value>a</value><value/>
<value>b</value></container>` decodes a `value: [String?]` property to `["a", "", "b"]`.

### Decoder options (properties)

The decoder's option and strategy enums are likewise **nested member types of `XMLDecoder`**.

- `dateDecodingStrategy` — **default `.secondsSince1970`** (note this differs from the encoder's
  `.deferredToDate` default). Other cases mirror the encoder (see *Value strategies*).
- `dataDecodingStrategy` — default `.base64`.
- `nonConformingFloatDecodingStrategy` — default `.throw`.
- `keyDecodingStrategy: KeyDecodingStrategy` — see *Key strategies*.
- `nodeDecodingStrategy: NodeDecodingStrategy` — see *Node coding*.
- `shouldProcessNamespaces: Bool` — default `false`. When `true`, the parser strips namespace
  prefixes, so `<h:td>` matches the coding key `td`. When `false`, the qualified name is used
  literally, so a key must be declared as `"h:td"` to match. Toggling it flips which of two models
  (prefix-stripped vs. prefixed coding keys) successfully decodes a namespaced document.
- `trimValueWhitespaces: Bool` — default `true`. When `true`, leading/trailing whitespace is
  trimmed from decoded text (a whitespace-only element decodes to `""`). Set `false` to preserve
  all whitespace exactly. XML entities (`&amp;` etc.) are always unescaped regardless.
- `removeWhitespaceElements: Bool` — default `false`. When `true`, pure-whitespace elements that
  sit beside non-whitespace siblings are dropped (useful for pretty-printed input).
- `errorContextLength: UInt` — default `0`. See *Error context*.
- `userInfo: [CodingUserInfoKey: Any]`.

---

## Node coding: attributes vs. elements

By default a property is **encoded** as a child **element**, and **decoded** from a child element
*or* a same-named attribute (elements take priority). A value can instead be pinned to live in an
**attribute**. Three mechanisms select this, in order of precedence handled by the coder.

### `NodeEncoding` / `NodeDecoding`

```swift
extension XMLEncoder {
    public enum NodeEncoding { case attribute, element, both
                               public static let `default`: NodeEncoding = .element }
}
extension XMLDecoder {
    public enum NodeDecoding { case attribute, element, elementOrAttribute }
}
```

- Encoding `.attribute` writes `name="value"` on the parent tag; `.element` writes `<name>value</name>`;
  `.both` writes the value as *both* an attribute and a child element.
- Decoding `.element` reads only from a child element, `.attribute` only from an attribute, and
  `.elementOrAttribute` from either, **preferring the element**. If the required source is absent,
  decoding throws `DecodingError.keyNotFound`. A property with **no** explicit node coding (no
  `DynamicNodeDecoding`, no property wrapper, no `.custom` strategy) decodes as if
  `.elementOrAttribute` — reading a child element or a same-named attribute — even though the
  matching **encode** default is `.element`.

### `DynamicNodeEncoding` / `DynamicNodeDecoding`

Conform a type to customize its node coding per key:

```swift
public protocol DynamicNodeEncoding: Encodable {
    static func nodeEncoding(for key: CodingKey) -> XMLEncoder.NodeEncoding
}
public protocol DynamicNodeDecoding: Decodable {
    static func nodeDecoding(for key: CodingKey) -> XMLDecoder.NodeDecoding
}
```

Example — `Book` marks `id`/`author`/`gender` as `.both` and `Category` marks `main` as
`.attribute`; encoding a library (pretty-printed, with an XML header) yields:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<library>
    <count>2</count>
    <book id="123" author="Jack" gender="novel">
        <id>123</id>
        <author>Jack</author>
        <gender>novel</gender>
        <title>Cat in the Hat</title>
        <category main="true">
            <value>Kids</value>
        </category>
        <category main="false">
            <value>Wildlife</value>
        </category>
    </book>
    …
</library>
```

Placing an attribute-node property on the root type writes it on the root element (e.g. a `Policy`
with `name` as `.attribute` encodes as `<policy name="generic"> … </policy>`).

### `NodeEncodingStrategy` / `NodeDecodingStrategy`

Encoder/decoder-wide overrides:

```swift
extension XMLEncoder {
    public enum NodeEncodingStrategy {
        case deferredToEncoder                       // default: honour DynamicNodeEncoding, else .element
        case custom((Encodable.Type, Encoder) -> ((CodingKey) -> NodeEncoding?))
    }
}
extension XMLDecoder {
    public enum NodeDecodingStrategy {
        case deferredToDecoder                       // default
        case custom((Decodable.Type, Decoder) -> ((CodingKey) -> NodeDecoding))
    }
}
```

A `.custom` closure returning `.attribute` for a key forces that key to encode as an attribute even
without `DynamicNodeEncoding`.

### Property wrappers

Ergonomic alternatives to `DynamicNodeEncoding`, each generic over the wrapped `Codable` value and
initializable with `init(_ wrappedValue:)`:

- `@Attribute` — the property is coded as an attribute.
- `@Element` — the property is coded as an element (the default form, made explicit).
- `@ElementAndAttribute` — coded as *both*, and decodes from either form.

```swift
struct Book: Codable, Equatable {
    @Attribute var id: Int
    @Element var name: String
    @ElementAndAttribute var authorID: Int
}
// Book(id: 42, name: "The Book", authorID: 24), pretty-printed:
// <Book id="42" authorID="24">
//     <name>The Book</name>
//     <authorID>24</authorID>
// </Book>
```

Wrapped values are `Equatable`/`Hashable` when the underlying value is; optional wrapped values
(e.g. `@Attribute var ref: String?`) are supported.

---

## Intrinsic value keys (text content)

A `CodingKey` whose string value is the empty string `""` binds to the element's **text content**,
letting a type mix an attribute (or child elements) with the element's own text. Given

```swift
struct Foo: Codable {
    @Attribute var id: String
    var value: String
    enum CodingKeys: String, CodingKey { case id; case value = "" }
}
```

`Foo(id: "123", value: "456")` encodes to `<foo id="123">456</foo>` and decodes back. An element
with no text decodes its intrinsic value to `""`.

---

## Choice coding (enums with associated values)

To code a Swift `enum` with associated values as a *choice* of XML elements (the element name picks
the case), make its `CodingKeys` conform to the marker protocol:

```swift
public protocol XMLChoiceCodingKey: CodingKey {}
```

Each enum case corresponds to an element named after its coding key; the case's associated value is
that element's content. Arrays of such enums preserve document order (so heterogeneous, interleaved
elements round-trip):

```xml
<container>
    <int>1</int>
    <string>two</string>
    <int>4</int>
</container>
```

decodes to `[.int(1), .string("two"), .int(4)]`. Associated values may be scalars *or* nested
structs (whose own properties become child elements/attributes). To decode a heterogeneous ordered
list into a wrapper type, decode `[Choice].self` through a `singleValueContainer`. A coding key may
remap the element name (e.g. `case body = "chapter"`), and choice cases combine with intrinsic value
keys and attribute nodes on the associated value.

A choice case's own coding key may also be the empty string `""`: like an intrinsic value key, such a
case binds to the element's **bare text content** rather than to a named child element. In a
mixed-content list (free text interleaved with named child elements), each maximal run of bare text
decodes to its own `""`-keyed case and each child element to its named case, all kept in document
order; encoding reverses this exactly. For a choice enum with `case italic = "i"` and `case text = ""`,
`<container>alpha<i>mid</i>omega</container>` round-trips as
`[.text("alpha"), .italic("mid"), .text("omega")]`.

Choice values may sit alongside ordinary (non-choice) siblings in the same element; the order of the
emitted children follows the order in which the type's `encode(to:)` writes them.

---

## Value strategies

Mirror Foundation's coder strategies. `enum` cases:

- **Date** — `DateEncodingStrategy` / `DateDecodingStrategy`:
  `deferredToDate` (encoder default), `secondsSince1970` (decoder default), `millisecondsSince1970`,
  `iso8601`, `formatted(DateFormatter)`, `custom(closure)`. `secondsSince1970` codes a `Date` as its
  numeric epoch seconds (e.g. `Date(timeIntervalSince1970: 0)` ↔ `0.0`); `.formatted` uses the
  supplied `DateFormatter` (e.g. `"yyyy-MM-dd"` in GMT ↔ `2000-10-01`).
- **Data** — `DataEncodingStrategy` (`deferredToData`, `base64` default, `custom`) /
  `DataDecodingStrategy` (`deferredToData`, `base64` default, `custom`).
- **Non-conforming floats** — `NonConformingFloatEncodingStrategy` /
  `NonConformingFloatDecodingStrategy`: `throw` (default) rejects IEEE infinity/NaN with an
  `EncodingError`; `convertToString(positiveInfinity:negativeInfinity:nan:)` /
  `convertFromString(positiveInfinity:negativeInfinity:nan:)` map them to/from the given literals.
- **Strings** — `StringEncodingStrategy`: `deferredToString` (default) or `cdata`. With `.cdata`,
  encoded `String` values are wrapped as `<x><![CDATA[…]]></x>`, while non-string scalars are not.
  Decoding always reads `<![CDATA[…]]>` content transparently.

---

## Key strategies

`KeyEncodingStrategy` and `KeyDecodingStrategy` transform coding-key names. Encoding cases:
`useDefaultKeys` (default), `convertToSnakeCase`, `convertToKebabCase`, `capitalized`, `uppercased`,
`lowercased`, `custom(([CodingKey]) -> CodingKey)`. Decoding cases: `useDefaultKeys` (default),
`convertFromSnakeCase`, `convertFromKebabCase`, `convertFromCapitalized`, `convertFromUppercase`,
`custom(([CodingKey]) -> CodingKey)`.

Conversions (leading/trailing separators preserved throughout):

- snake case: `oneTwoThree` ↔ `one_two_three`, `myURLProperty` → `my_url_property`,
  `_oneTwoThree_` → `_one_two_three_`.
- kebab case: `oneTwoThree` ↔ `one-two-three`.
- `capitalized` / `convertFromCapitalized`: capitalize only the first letter — `tagName` → `TagName`,
  and back `T` → `t`.
- `uppercased`: `oneTwoThree` → `ONETWOTHREE`.
- `lowercased`: `oneTwoThree` → `onetwothree`.
- `convertFromUppercase`: lower-case then de-snake — `TAG_NAME` → `tagName`.

---

## XML header and DOCTYPE

```swift
public struct XMLHeader {
    public init(version: Double? = nil, encoding: String? = nil, standalone: String? = nil)
}
```

Renders the fields that are present, e.g. `XMLHeader(version: 1.0, encoding: "UTF-8")` →
`<?xml version="1.0" encoding="UTF-8"?>` followed by a newline. An all-nil header emits nothing.

```swift
public struct XMLDocumentType {
    public static func system(rootElement: String, dtdLocation: String) -> XMLDocumentType
    public static func `public`(rootElement: String, dtdName: String, dtdLocation: String) -> XMLDocumentType
}
```

Rendered (each followed by a newline):

```
<!DOCTYPE si SYSTEM "http://example.com/myService_v1.dtd">
<!DOCTYPE si PUBLIC "-//Domain//DTD MyService v1//EN" "http://example.com/myService_v1.dtd">
```

## Root attributes

The `rootAttributes` argument adds attributes to the root element after any attribute-node
properties of the value, e.g. (with `keyEncodingStrategy = .lowercased`,
`outputFormatting = [.prettyPrinted, .sortedKeys]`):

```xml
<policy name="test" xmlns="http://www.nrf-arts.org/IXRetail/namespace" xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
    <initial>extra root attributes</initial>
</policy>
```

---

## Classes and inheritance

Encoding a class that calls `superEncoder()` / `superDecoder()` nests the superclass's state inside a
`<super>` child element, recursively for deeper hierarchies. Such a value round-trips through encode
and decode.

## Error context

When `errorContextLength > 0`, a parser error is repackaged as
`DecodingError.dataCorrupted(context)` where `context.underlyingError` holds the original parser
error and `context.debugDescription` has the form:

```
<underlying description> at line <L>, column <C>:
`<slice>`
```

The back-quoted slice is up to `errorContextLength` characters of source around the error location
(clamped to available content, and spanning line breaks when needed). With the default
`errorContextLength == 0`, the underlying parser error is thrown without this repackaging.
