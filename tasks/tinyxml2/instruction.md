# tinyxml2

Build `tinyxml2`, a small, self-contained C++ XML parser and serializer.
It exposes a DOM-style API: an XML document is parsed into a tree of
nodes (elements, text, comments, declarations) that can be navigated,
mutated, and written back out.

The library lives in a single header/source pair
(`tinyxml2.h` / `tinyxml2.cpp`) and depends only on the C++ standard
library — no STL containers, no exceptions, no RTTI required at the
library boundary.

## Dependencies

- A C++17-capable compiler (`g++` is available).
- CMake is available if your build system uses it. Any build system is
  acceptable as long as the install contract below is met.

## Build contract

After your `/app/setup.sh` is run, a freshly written driver must
build and run with:

```
g++ -std=c++17 driver.cpp -ltinyxml2 -o driver
./driver
```

`setup.sh` may run `apt-get install` for any extra build tools.

## Namespace

All public types live in `namespace tinyxml2`. Tests will write
`using namespace tinyxml2;`.

## Public API surface

Below is the full API the test suite relies on. Every symbol listed
here must exist with the documented signature; anything not listed is
unspecified and you are free to organise internally however you like.

### `enum XMLError`

```cpp
enum XMLError {
    XML_SUCCESS = 0,
    XML_NO_ATTRIBUTE,
    XML_WRONG_ATTRIBUTE_TYPE,
    XML_ERROR_PARSING_ATTRIBUTE,
    XML_ERROR_EMPTY_DOCUMENT,
    XML_ERROR_MISMATCHED_ELEMENT,
    XML_CAN_NOT_CONVERT_TEXT,
    XML_NO_TEXT_NODE,
    XML_ELEMENT_DEPTH_EXCEEDED
};
```

The enumerator names — including their exact spelling — are part of
the public contract; `XMLDocument::ErrorIDToName(err)` returns the
string form of the enumerator.

### `class XMLDocument`

The root of every document tree. Owns the memory for all nodes it
contains; deleting the document deletes the tree.

```cpp
XMLDocument(bool processEntities = true, /* Whitespace mode */ ... );

XMLError Parse(const char* xml, size_t nBytes = static_cast<size_t>(-1));
XMLError LoadFile(const char* filename);
XMLError SaveFile(const char* filename, bool compact = false);

// Factories — every node must be allocated through these.
XMLElement*     NewElement(const char* name);
XMLComment*     NewComment(const char* text);
XMLDeclaration* NewDeclaration(const char* text = nullptr);

XMLElement*       RootElement();
const XMLElement* RootElement() const;

// BOM control.
bool HasBOM() const;
void SetBOM(bool useBOM);

// Streaming output. If `streamer` is null, prints to stdout.
void Print(XMLPrinter* streamer = nullptr) const;

// Error reporting.
bool        Error() const;
XMLError    ErrorID() const;
const char* ErrorName() const;
static const char* ErrorIDToName(XMLError errorID);
int         ErrorLineNum() const;
```

`Parse` reports the first error encountered and stops; subsequent
queries (`Error`, `ErrorID`, `ErrorName`, `ErrorLineNum`) reflect that
error. A subsequent successful `Parse` on the same document resets
`Error()` to `false` and `ErrorID()` to `XML_SUCCESS`.

### `class XMLNode` (base)

Every node in the tree derives from `XMLNode`. The base type exposes:

```cpp
const char* Value() const;
void        SetValue(const char* val, bool staticMem = false);
int         GetLineNum() const;

XMLNode*       Parent();
const XMLNode* Parent() const;
bool           NoChildren() const;

XMLNode*       FirstChild();        const XMLNode* FirstChild() const;
XMLNode*       LastChild();         const XMLNode* LastChild() const;
XMLNode*       PreviousSibling();   const XMLNode* PreviousSibling() const;
XMLNode*       NextSibling();       const XMLNode* NextSibling() const;

XMLElement*       FirstChildElement(const char* name = nullptr);
const XMLElement* FirstChildElement(const char* name = nullptr) const;
XMLElement*       LastChildElement(const char* name = nullptr);
const XMLElement* LastChildElement(const char* name = nullptr) const;
XMLElement*       NextSiblingElement(const char* name = nullptr);
const XMLElement* NextSiblingElement(const char* name = nullptr) const;
XMLElement*       PreviousSiblingElement(const char* name = nullptr);
const XMLElement* PreviousSiblingElement(const char* name = nullptr) const;

// Insertion / deletion. Inserting a node that already belongs to the
// document moves it to its new location.
XMLNode* InsertEndChild(XMLNode* addThis);
XMLNode* InsertFirstChild(XMLNode* addThis);
XMLNode* InsertAfterChild(XMLNode* afterThis, XMLNode* addThis);
void     DeleteChildren();
void     DeleteChild(XMLNode* node);

// Type-safe downcasts; return nullptr if the node is a different type.
virtual XMLElement*       ToElement();         virtual const XMLElement*       ToElement() const;
virtual XMLText*          ToText();            virtual const XMLText*          ToText() const;
virtual XMLComment*       ToComment();         virtual const XMLComment*       ToComment() const;
virtual XMLDeclaration*   ToDeclaration();     virtual const XMLDeclaration*   ToDeclaration() const;

// Deep copy into a target document. All allocations live in `target`,
// so the clone outlives the source document.
XMLNode* DeepClone(XMLDocument* target) const;

// Visitor walk; see XMLVisitor below.
virtual bool Accept(XMLVisitor* visitor) const = 0;
```

The `Value()` of a node is type-specific: element name for `XMLElement`,
text content for `XMLText`, comment text for `XMLComment`, etc.

### `class XMLElement : public XMLNode`

```cpp
const char* Name() const;  // alias for Value()
void        SetName(const char* str, bool staticMem = false);

// Text-child convenience accessors.
const char* GetText() const;   // text of first child if it's an XMLText, else nullptr
void        SetText(const char* inText);
void        SetText(int value);
void        SetText(bool value);
void        SetText(double value);

// Numeric overloads format with `%g`; bool yields `true`/`false`.

// Typed text queries on the element's first text child.
// Return XML_SUCCESS, XML_CAN_NOT_CONVERT_TEXT, or XML_NO_TEXT_NODE.
XMLError QueryIntText(int* ival)     const;
XMLError QueryBoolText(bool* bval)   const;
XMLError QueryDoubleText(double* dval) const;

// Attribute lookup. `Attribute(name)` returns nullptr if missing.
// `Attribute(name, value)` returns the attribute pointer only when the
// stored value string-equals `value`, else nullptr.
const char* Attribute(const char* name, const char* value = nullptr) const;

// Typed attribute convenience accessors. Return the default on missing
// or unconvertible attribute.
int    IntAttribute(const char* name, int defaultValue = 0)       const;
bool   BoolAttribute(const char* name, bool defaultValue = false) const;
double DoubleAttribute(const char* name, double defaultValue = 0) const;

// Typed attribute query with explicit error reporting.
// Returns XML_SUCCESS, XML_NO_ATTRIBUTE, or XML_WRONG_ATTRIBUTE_TYPE.
XMLError QueryIntAttribute(const char* name, int* value) const;

// Setters create the attribute if absent. Preserve insertion order:
// the first call to SetAttribute("foo", ...) makes "foo" appear at the
// end of the existing attribute list, and subsequent calls update its
// value in place without changing its position.
void SetAttribute(const char* name, const char* value);
void SetAttribute(const char* name, int value);
void SetAttribute(const char* name, bool value);

// Removes the named attribute and preserves the relative order of the rest.
void DeleteAttribute(const char* name);

const XMLAttribute* FirstAttribute() const;
const XMLAttribute* FindAttribute(const char* name) const;
```

### `class XMLAttribute`

Attributes form a singly-linked list in document order, owned by their
element. They are not `XMLNode`s.

```cpp
const char* Name() const;
const char* Value() const;
int         GetLineNum() const;
const XMLAttribute* Next() const;
```

### `class XMLText : public XMLNode`

Holds text-node content. Distinguishes CDATA from normal text via
`CData()`. CDATA preserves raw markup characters (`<`, `&`, etc.)
verbatim; normal text decodes/encodes XML entities.

```cpp
bool CData() const;
void SetCData(bool isCData);
```

### `class XMLComment : public XMLNode`

XML comment node; `Value()` returns the comment text without the
surrounding `<!--` / `-->`.

### `class XMLDeclaration : public XMLNode`

XML declaration node (e.g. `<?xml version="1.0"?>`), created via
`XMLDocument::NewDeclaration()` (a `nullptr` argument yields a default
declaration) and downcast from a parsed node with `XMLNode::ToDeclaration()`.

### `class XMLHandle`

Navigation wrapper; missing steps absorb to null.

```cpp
explicit XMLHandle(XMLNode* node);
explicit XMLHandle(XMLNode& node);

XMLHandle FirstChildElement(const char* name = nullptr);

XMLElement* ToElement();
```

### `class XMLVisitor`

Implement this to receive callbacks during `XMLNode::Accept`. Default
implementations return `true` (continue visiting); override only the
methods you care about. Return `false` from a `VisitEnter` to skip
the subtree.

```cpp
virtual ~XMLVisitor();
virtual bool VisitEnter(const XMLDocument& doc);
virtual bool VisitExit (const XMLDocument& doc);
virtual bool VisitEnter(const XMLElement& element, const XMLAttribute* firstAttribute);
virtual bool VisitExit (const XMLElement& element);
virtual bool Visit(const XMLText& text);
virtual bool Visit(const XMLComment& comment);
```

The walk is depth-first in document order: `VisitEnter` for a node,
then recursively for its children, then `VisitExit`.

### `class XMLPrinter : public XMLVisitor`

Serializes an `XMLDocument` when driven via `XMLDocument::Print(printer)`
(the printer is a visitor). Output is buffered in memory; `CStr()`
returns the buffered XML. Passing a `FILE*` to the constructor also
writes the output directly to that file as `Print` walks the tree.

```cpp
XMLPrinter(FILE* file = nullptr, bool compact = false, int depth = 0);
const char* CStr() const;  // buffered output
```

When `compact` is `true`, the document is written without indentation
or newlines between tags. Output for `<bool>` values uses the strings
`"true"` and `"false"`.

In non-compact (pretty) mode, an element whose direct content is a
single text node is serialized on one line (`<elt>text</elt>`) — the
printer suppresses the indent and newline that would otherwise precede
the close tag, so that text content round-trips intact through
`SaveFile` / `LoadFile`.

Empty elements are serialized self-closing as `<elt/>`. Attribute
values are written wrapped in double quotes (`name="value"`),
regardless of the quote style they were parsed with.

## Parser semantics

- **Whitespace.** With the default `XMLDocument` whitespace mode,
  text-node content is captured verbatim — including any leading or
  trailing whitespace inside the element. (Surrounding-whitespace
  collapse is an opt-in mode controlled by the constructor's
  whitespace-mode argument; documenting that opt-in mode is out of
  scope for this task.)
- **UTF-8.** All XML input is treated as UTF-8 and round-trips
  byte-for-byte through `Parse` / `Print`.
- **Entities.** The five XML named entities (`&amp;`, `&lt;`, `&gt;`,
  `&quot;`, `&apos;`) decode on parse and re-encode on print.
  Numeric (`&#65;`) and hex (`&#x42;`) character references decode to
  their Unicode code points on parse.
- **CDATA.** Inside `<![CDATA[ ... ]]>`, markup characters are kept
  verbatim; the resulting `XMLText` reports `CData() == true`.
- **Element depth limit.** The parser caps recursion at a fixed depth
  (around 500 levels) to prevent stack overflow on adversarial input.
  Exceeding the limit yields `XML_ELEMENT_DEPTH_EXCEEDED`.
- **Mismatched closing tags** yield `XML_ERROR_MISMATCHED_ELEMENT`.
- **Empty input** to `Parse("")` yields `XML_ERROR_EMPTY_DOCUMENT`.
- **Malformed attributes** yield `XML_ERROR_PARSING_ATTRIBUTE`.
- **Line numbers.** Every node and attribute records the source line
  number it was parsed from (`GetLineNum()`); on parse failure,
  `XMLDocument::ErrorLineNum()` returns the line where parsing stopped.
- **Attribute order.** Attributes are kept in the order they appear in
  the source (and the order they were set); iteration via
  `FirstAttribute()` / `Next()` walks them in that order.
- **Save / load round-trip.** A document built in memory and written to
  disk via `SaveFile` can be read back via `LoadFile` with all
  declarations, BOM, attributes, text, and structure intact.
