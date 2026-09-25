# Implement the `ldaptor` pure LDAP codec / parser core

You are implementing the pure (non-networked) wire-codec and text-parser layer of an
LDAP toolkit. There is **no live LDAP server** involved: every behavior is a pure
function of its inputs — BER byte encoding/decoding, RFC2254 search-filter
parsing/serialization, RFC2253 distinguished-name handling, LDAP protocol-message
(PDU) assembly, and LDIF read/write.

Implement enough of the package so the public API described below behaves exactly as
specified. The grader imports your code as the installable package `ldaptor`.

## Runtime dependencies

**The environment is fully offline and every dependency is already installed — do NOT
install anything (no `pip install`, no network access is available).** A `setup.sh` in the
project root installs your package in editable mode offline; it is run for you before the
tests. Just implement the package against the pre-installed libraries below.

The package depends on **Twisted** (the LDIF parser is a Twisted `LineReceiver` subclass, so
`twisted.protocols.basic.LineReceiver` must be importable). **pyparsing** is also available
should you choose to build the RFC2254 filter-text grammar with it (you may instead hand-roll
the parser — either approach is fine). `passlib`, `six`, and `zope.interface` are present as
well (pulled in transitively by Twisted), but the pure codec/parser surface specified below
does not require you to use them directly.

## Import layout (must match exactly)

The grader imports these modules by these exact dotted paths. Keep this layout 1:1:

- `ldaptor.protocols.pureber` — pure BER codec primitives.
- `ldaptor.protocols.pureldap` — LDAP filter classes, PDU classes, escapers, decoder contexts.
- `ldaptor.ldapfilter` — RFC2254 filter text parser.
- `ldaptor.protocols.ldap.distinguishedname` — DN / RDN / ATV.
- `ldaptor.protocols.ldap.ldif` — LDIF writer (module-level functions).
- `ldaptor.protocols.ldap.ldifprotocol` — streaming LDIF parser + its error hierarchy.

---

## Pillar 1 — BER codec (`ldaptor.protocols.pureber`)

BER here is restricted per RFC2251: **definite-form lengths only**, primitive octet
strings, booleans whose true value is `0xFF`, and absent-when-default fields.

### Integer encode/decode (signed two's-complement, big-endian, minimal length)

- `int2ber(i, signed=True) -> bytes`: encode an integer as a minimal-length
  big-endian two's-complement byte string (the canonical BER integer content
  encoding). Use the fewest octets that still represent the value unambiguously —
  this means a leading zero octet is required for a positive value whose top bit
  would otherwise read as negative. With `signed=False` encode the value as a
  plain unsigned big-endian integer instead.
- `ber2int(e, signed=True) -> int`: the exact inverse, including correct sign
  extension for signed input and a plain unsigned interpretation when `signed=0`.
  Negative values must round-trip exactly. It needs at least one byte, so an empty
  buffer fails the insufficient-data guard (`BERExceptionInsufficientData` with a
  deficit of `1`).

### Length encode/decode (short + long definite form)

- `int2berlen(i) -> bytes`: emit a BER definite-form length per RFC2251 — the
  single-byte short form for small lengths, and the long form (a lead octet that
  records how many length octets follow, followed by the minimal big-endian
  unsigned length) once the length no longer fits the short form.
- `berDecodeLength(m, offset=0) -> (length, lengthLength)` where `lengthLength` is the
  total number of header bytes consumed (including the lead byte). It must read both
  short and long definite forms. If a long-form header promises more octets than the
  buffer holds, raise `BERExceptionInsufficientData`.

### Insufficient-data guard

- `need(buf, n) -> None`: returns `None` when `len(buf) >= n`; otherwise raises
  `BERExceptionInsufficientData` whose `.args` is the single-element tuple `(deficit,)`
  where `deficit = n - len(buf)` (e.g. `need(b"abc", 5)` raises with args `(2,)`).

### BER value objects

Provide value classes whose `toWire()` emits `identification-byte + length + contents`
using the standard BER universal tag for each type:

- `BERInteger`: an integer carried as a BER integer (the `int2ber`/`ber2int` content).
- `BEROctetString`: contents are the raw bytes given to it.
- `BERNull`: zero-length contents.
- `BEREnumerated`: integer-like value but carried under its own ENUMERATED tag.
- `BERBoolean`: **any truthy constructor value is normalized to the BER true octet
  `0xFF`** and stored on `.value`; a falsey value stays `0`. (So `BERBoolean(5).value
  == 0xFF`.)
- `BERSequence`: a list of child BER objects, encoded under the universal (structured)
  SEQUENCE tag; `toWire()` is the concatenation of the child encodings wrapped in the
  sequence header. It behaves like a list (it carries its children).
- `BERSequenceOf` — a `BERSequence` alias/subclass.
- `BERSet`: like a sequence but under the universal (structured) SET tag.

Cross-cutting object behavior:

- Constructing any of these with an explicit `tag=` keyword overrides the class default
  in the emitted identification byte (`BERInteger(7, tag=0x42)` encodes under tag
  `0x42`). For structured types the structured bit handling must keep the round-trip
  consistent.
- Equality is **by wire encoding**: two objects are `==` iff their `toWire()` bytes
  match (`BERInteger(5) == BERInteger(5)`, `!= BERInteger(6)`). Make them hashable by
  their wire bytes.

### Decoder context + object decode

- `BERDecoderContext(fallback=None, inherit=None)`: a tag→class registry. It exposes a
  class-level `Identities` mapping (tag byte → BER class) covering the universal types
  above, a `lookup_id(tag)` that consults `Identities` then delegates to `fallback` if
  present (returning `None` if nothing matches), and an `inherit()` method returning the
  `inherit` context if one was supplied else `self`. The `fallback` and `inherit`
  constructor keywords are load-bearing: higher layers build nested contexts out of
  them (see Pillar 4).
- `berDecodeObject(context, m) -> (obj_or_None, bytesUsed)`: reads one TLV from the
  front of `m`. Resolves the class via `context.lookup_id(tag)`; if found, reconstructs
  it via that class's `fromBER(tag, content, berdecoder=context.inherit())` and returns
  `(obj, totalBytesConsumed)`. **If the tag is unknown, it does NOT raise** — it
  swallows the object and returns `(None, bytesUsed)` (it may print a diagnostic). If
  the declared content length exceeds the available bytes, raise
  `BERExceptionInsufficientData`. The `tag` matched is the masked identification byte
  (class + tag-number bits). Round-trip: `berDecodeObject(BERDecoderContext(),
  BERInteger(42).toWire())` yields `(BERInteger(42), 3)`. An IA5String blob (tag `0x16`,
  unmapped in the universal context) decodes to `(None, 4)` for a 2-byte payload. With
  no bytes to read at all (an empty buffer) it returns `(None, 0)` rather than raising.
- `berDecodeMultiple(content, berdecoder) -> [obj]`: repeatedly decodes whole objects
  until `content` is exhausted, skipping `None` results, asserting each step consumes a
  positive non-overrunning amount.

Each BER class must therefore implement a `fromBER(tag, content, berdecoder=None)`
classmethod that reconstructs an equal object (sequences recurse through
`berDecodeMultiple`).

Exceptions to expose from this module: `BERException`, `BERExceptionInsufficientData`,
`UnknownBERTag`.

---

## Pillar 2 — RFC2254 search filters

### Filter classes (`ldaptor.protocols.pureldap`)

Each filter class is a BER object (has `toWire()`/`fromBER()`/wire-equality) AND has an
`asText() -> str` that re-emits canonical RFC2254 text. Provide:

- `LDAPFilter_equalityMatch` — `asText() == "(attr=value)"`. Exposes `.attributeDesc`
  and `.assertionValue` (the latter has a `.value` that is the decoded assertion text).
- `LDAPFilter_greaterOrEqual` — `"(attr>=value)"`.
- `LDAPFilter_lessOrEqual` — `"(attr<=value)"`.
- `LDAPFilter_approxMatch` — `"(attr~=value)"`.
- `LDAPFilter_present` — `"(attr=*)"`.
- `LDAPFilter_substrings` — holds an ordered `.substrings` list (see below);
  `asText()` joins segment values with `*`.
- `LDAPFilter_substrings_initial`, `_any`, `_final` — substring segment types, each
  carrying a `.value`.
- `LDAPFilter_and`, `LDAPFilter_or` — boolean filter **sets** over child filters;
  `asText()` is `"(&...)"` / `"(|...)"` with children in text order. Each is a list-like
  container of its child filters: iterating the filter object (`for child in and_filter`,
  `list(and_filter)`) yields the member filters in text order.
- `LDAPFilter_not` — wraps exactly one child; `asText()` is `"(!child)"`.
- `LDAPFilter_extensibleMatch` — exposes `.type` (an attribute-desc object or `None`),
  `.matchingRule` (object or `None`), `.matchValue` (object with `.value`), and
  `.dnAttributes` (a boolean-like; when the `:dn` flag is present its `.value == 0xFF`).

Boolean-set equality (`LDAPFilter_and` / `LDAPFilter_or`) is **order-insensitive**:
`(&(a=1)(b=2)) == (&(b=2)(a=1))`, but unequal when the member sets differ.

### Substring decomposition rules

Implement RFC2254 substring decomposition for an `(attr=...)` value that contains one
or more `*`: split the value on the stars into the standard *initial / any / final*
segment model. A non-empty leading fragment is the `initial` segment, a non-empty
trailing fragment is the `final` segment, and every interior fragment is an `any`
segment, in order. A leading or trailing `*` therefore means there is no initial or no
final segment respectively. The segment classes are
`LDAPFilter_substrings_initial`, `LDAPFilter_substrings_any`, and
`LDAPFilter_substrings_final`, each carrying its fragment on `.value`. `asText()` must
reproduce the original star-joined text.

### Extensible-match grammar

The filter text grammar recognizes the RFC2254 extensible-match forms directly (you do
**not** need a standalone helper — if you expose a `parseExtensible`, it may remain
unimplemented/raising, because the live grammar path is what is exercised). Implement
the extensible grammar so that all four RFC2254 shapes parse and round-trip via
`asText()`: an attribute with a matching rule, the `:dn` flag with or without an
attribute type, a bare matching rule (numeric OID or named rule), and the combined
form with both an attribute type and a matching rule. The parsed object's `.type`,
`.matchingRule`, `.matchValue`, and `.dnAttributes` components must reflect which parts
were present (an absent component is `None`; the `:dn` flag sets the boolean-like
`dnAttributes` to its true value).

All text components exposed via `.value` — substring segments
(`LDAPFilter_substrings_initial`/`_any`/`_final`), and the extensible-match
`.type`, `.matchingRule`, `.matchValue`, plus `assertionValue.value` — are the
**decoded `str`** (the filter text parser builds them from `str` tokens), not
bytes.

### Filter text parser (`ldaptor.ldapfilter`)

- `parseFilter(s) -> <LDAPFilter_*>`: parse a complete parenthesized RFC2254 filter.
  Accepts `str` or `bytes` (bytes are decoded as UTF-8). Raises
  `ldapfilter.InvalidLDAPFilter` for malformed input — including an unterminated filter
  (`"(cn=foo"`), the empty string `""`, and `"()"`.
- `parseMaybeSubstring(attrType, s) -> filter`: builds a filter from an attribute name
  and a **bare value** (no surrounding parens): a value containing `*` →
  `LDAPFilter_substrings` (`parseMaybeSubstring("cn", "a*b").asText() == "(cn=a*b)"`); a
  lone `"*"` → `LDAPFilter_present`; any other value → `LDAPFilter_equalityMatch`.
- Value escaping in filter text: a `\\XX` hex escape in an assertion value decodes to the
  literal byte/char, e.g. `parseFilter("(cn=foo\\2abar)").assertionValue.value ==
  "foo*bar"`.
- `InvalidLDAPFilter` is an exception class exported from this module.

### Filter escapers (`ldaptor.protocols.pureldap`)

- `escape(s) -> str`: backslash-hex-escapes the RFC2254 special set `*`, `(`, `)`, `\`,
  and NUL. `escape("a*b(c)\\d\x00") == "a\\2ab\\28c\\29\\5cd\\00"`.
- `binary_escape(s) -> str`: emits a `\\xx` lowercase-hex pair for **every** character —
  `binary_escape("AB") == "\\41\\42"`.
- `smart_escape(s, threshold=0.30) -> str`: counts the fraction of "binary" (would-be-
  escaped) characters; if that fraction is at or below `threshold` it uses light
  `escape`, otherwise it falls back to full `binary_escape`. `smart_escape("hello*") ==
  "hello\\2a"`; `smart_escape("\x01\x02\x03ab") == "\\01\\02\\03\\61\\62"`.

### Filter wire round-trip

Filters serialize to BER via `toWire()` and decode back via `berDecodeObject` using a
filter-capable decoder context (see Pillar 4). A nested
`(&(cn=foo)(!(sn=bar))(|(a=1)(b=2)))` must survive text→object→wire→object: the decoded
object is an `LDAPFilter_and`, `decoded.toWire() == wire`, and `decoded == orig`. A
substrings filter preserves its 3 segments through the round trip; an extensibleMatch
filter likewise round-trips.

---

## Pillar 3 — DN / RDN / ATV (`ldaptor.protocols.ldap.distinguishedname`)

### Module-level escaping (RFC2253)

- `escape(s) -> str`:
  - A **leading** space is escaped: `escape(" foo") == "\\ foo"`.
  - A **trailing** space is escaped: `escape("foo ") == "foo\\ "`.
  - A **leading** `#` is escaped: `escape("#foo") == "\\#foo"`.
  - The special set `,+"\<>;=` is each backslash-escaped:
    `escape('a,b+c"d\\e<f>g;h=i') == 'a\\,b\\+c\\"d\\\\e\\<f\\>g\\;h\\=i'`.
  - A control character below `0x20` becomes `\\XX` **uppercase** hex:
    `escape("a" + chr(31) + "b") == "a\\1Fb"`.
- `unescape(s) -> str`: inverse. `\\01` → the control char `\x01`
  (`unescape("a\\01b") == "a\x01b"`); a `\\,` → a literal comma
  (`unescape("a\\,b") == "a,b"`).
- Separator handling when parsing a DN or RDN: only an **unescaped** separator is a
  boundary — an escaped `\\,` (in a DN) or `\\+` (in an RDN) does **not** start a new
  RDN/ATV, and whitespace immediately following a separator is dropped. So
  `DistinguishedName("cn=a\\,b,dc=x").split()` yields 2 RDNs (round-tripping to
  `"cn=a\\,b,dc=x"`), and `DistinguishedName("cn=a, dc=b, dc=c").getText() ==
  "cn=a,dc=b,dc=c"`.

### Classes

- `LDAPAttributeTypeAndValue(stringValue)` — parses one `type=value`. Exposes
  `.getText()`. Equality is **case-insensitive on both type and value**
  (`LDAPAttributeTypeAndValue("CN=Foo") == LDAPAttributeTypeAndValue("cn=foo")`). A
  string lacking `=` raises `InvalidRelativeDistinguishedName`.
- `RelativeDistinguishedName(stringValue)` — one RDN, possibly multi-valued (ATVs joined
  by unescaped `+`). `RelativeDistinguishedName("cn=a+sn=b").count() == 2`,
  `.getText() == "cn=a+sn=b"`. Two RDNs with identical components compare equal.
- `DistinguishedName(stringValue)` — a DN built from comma-separated RDNs:
  - `.split() -> tuple/list of RDNs`; a 3-component DN splits into 3.
  - `.getText() -> str` returns the **normalized** DN text: the RDNs as split from the
    input, rejoined with a comma and **no** separator whitespace. For an already-normalized
    input it round-trips verbatim (`"cn=foo,dc=example,dc=com".getText() == "cn=foo,dc=example,dc=com"`);
    whitespace following an RDN separator in the input is dropped, consistent with `.split()`
    (`DistinguishedName("cn=a, dc=b, dc=c").getText() == "cn=a,dc=b,dc=c"`).
  - `.up() -> DistinguishedName` drops the leftmost (most specific) RDN
    (`"cn=foo,dc=example,dc=com".up().getText() == "dc=example,dc=com"`); `.up()` of a
    single-RDN DN yields an empty DN (`getText() == ""`).
  - `__eq__` compares equal against a `DistinguishedName`, against the equivalent `str`,
    and against the equivalent UTF-8 `bytes`.
  - `.contains(other) -> bool`: True iff `other` is the DN itself or a descendant
    (subtree) of it; coerces a `str` argument into a DN. A parent contains a child; a
    child does **not** contain its parent.
  - `.getDomainName() -> str | None`: take the **trailing run** of single-valued RDNs
    whose attribute type is `dc` and join their values with `.`. `cn=foo,dc=example,
    dc=com` → `"example.com"`. Returns `None` when there is no trailing `dc` run
    (`cn=foo`). A **multi-valued** `dc` RDN breaks the run, so only the suffix after it
    is returned (`dc=a+dc=b,dc=com` → `"com"`).
- `InvalidRelativeDistinguishedName` — exception exported from this module.

---

## LDAP PDU encode/decode (`ldaptor.protocols.pureldap`)

LDAP protocol operations are BER objects (application-class tags). Each operation carries
the `[APPLICATION n]` tag number that RFC2251's ASN.1 definition of that `protocolOp`
alternative gives it (RFC2251 section 4, "Elements of Protocol"), combined with the BER
application class, plus the constructed bit for the structured/sequence-bodied ops.
Provide at minimum:

- `LDAPMessage(value=<op>, id=<int>, controls=<list|None>)`: the envelope. `toWire()`
  encodes a sequence of `[messageID, protocolOp, optional controls]`. When decoded
  through the top-level context it reconstructs an `LDAPMessage` whose `.value` is the
  correct op subclass (tag dispatch), whose `.id` is preserved, and whose `.controls`
  round-trips. Controls are supplied as a list of `(controlType, criticality,
  controlValue)` tuples; after a round trip they come back as the same tuple shape with
  bytes for the OID (e.g. input `[("1.2.3", None, None)]` decodes to
  `[(b"1.2.3", None, None)]`). `decoded.toWire() == original wire`.
- `LDAPSearchRequest(baseObject=..., filter=..., attributes=[...])`: round-trips; after
  decode `baseObject` and each `attributes` element are bytes (e.g.
  `b"dc=example,dc=com"`, `[b"cn", b"sn"]`).
- `LDAPBindRequest(version=3, dn=..., auth=...)`: round-trips; decoded `dn`/`auth` are
  bytes. The LDAP protocol `version` is a **mandatory** integer that is **always**
  serialized as the first element of the BindRequest body — even at its default value of
  `3` (it is a plain required field, not an ASN.1 DEFAULT/OPTIONAL field, so the
  default-omission rule below does NOT apply to it). A **default** bind
  (`LDAPBindRequest()`) therefore encodes version `3` (`\x02\x01\x03`), then the empty DN
  as a zero-length octet string (`\x04\x00`), then the empty simple-auth credential under
  its context-class tag (per RFC2251) — so a default bind is short only because the DN and
  the context-tagged auth are empty, not because any field was omitted.
- `LDAPDelRequest(dn)`: encodes as an **application-class primitive** octet string
  (the DelRequest operation tag). Round-trips and dispatches by tag (an `LDAPMessage`
  wrapping it with `id=42` decodes back to an `LDAPDelRequest` with `decoded.id == 42`).
- `LDAPUnbindRequest()`: the UnbindRequest operation tag with empty contents.
- `LDAPModifyRequest(object=..., modification=[...])`: round-trips (empty modification
  list allowed).
- `LDAPCompareRequest(entry=..., ava=LDAPAttributeValueAssertion(attributeDesc=
  LDAPAttributeDescription("cn"), assertionValue=LDAPAssertionValue("x")))`: round-trips.
  Also expose `LDAPAttributeValueAssertion`, `LDAPAttributeDescription`,
  `LDAPAssertionValue`.
- `LDAPControl(controlType=..., criticality=..., controlValue=...)`: a control TLV.
  Decoding (via a controls context, below) yields `.controlType` (bytes),
  `.criticality` normalized to `0xFF` when true, and `.controlValue` (bytes).

### Response / result PDUs (server → client decode)

A client reads a server reply by decoding the wire bytes back through the top-level
context (build the typed object → wrap in `LDAPMessage` → `toWire()` → decode the bytes
through `LDAPBERDecoderContext_TopLevel`); the envelope reconstructs the correct op
subclass by tag dispatch, with `.id`/`.controls` preserved and
`decoded.toWire() == wire`. Provide these response/result classes, each its own
application-class operation tag, all round-tripping through the envelope:

- `LDAPResult` — the common result body shared by most responses: fields
  `resultCode` (an integer status code, e.g. `0` success or `32` no-such-object,
  carried as a BER enumerated), `matchedDN`, and `errorMessage` (both octet strings,
  bytes after decode). Constructor:
  `LDAPResult(resultCode=..., matchedDN=..., errorMessage=...)`; `resultCode` is
  required. It can also carry an optional `serverSaslCreds` and `referral` (referral
  encoding is not required — leave it unset/`None`).
- The following are `LDAPResult` subclasses (same three fields, distinct operation
  tags) and must decode back to an `LDAPResult`-shaped object preserving the fields:
  `LDAPSearchResultDone`, `LDAPModifyResponse`, `LDAPAddResponse`, `LDAPDelResponse`,
  `LDAPModifyDNResponse`, `LDAPCompareResponse`.
- `LDAPBindResponse` — an `LDAPResult` with an additional optional
  `serverSaslCreds=` field (context-class tagged). When present it round-trips back as
  bytes on `.serverSaslCreds`; when absent `.serverSaslCreds` decodes to `None`.
- `LDAPSearchResultEntry(objectName=..., attributes=[...])` — one returned entry:
  `objectName` (the entry DN, bytes after decode) and `attributes` as a list of
  `(attributeType, [value, ...])` pairs (bytes after decode), order and multi-valued
  sets preserved.
- `LDAPSearchResultReference(uris=[...])` — a continuation reference carrying a list of
  referral URIs (supply them as BER octet-string objects). It decodes back (via the
  general LDAP context, not the message envelope) to an `LDAPSearchResultReference`
  whose `.uris` entries expose their bytes via `.value`, with `decoded.toWire() == wire`.
- `LDAPExtendedResponse(resultCode=..., matchedDN=..., errorMessage=...,
  responseName=..., response=...)` — an `LDAPResult` plus an optional context-tagged
  `responseName` (an OID) and `response` value; both round-trip back as bytes.

Also expose `LDAPBindResponse_serverSaslCreds` (the context-tagged creds field) and
`LDAPReferral`.

### Less-common request operations

These request ops are also BER objects with application-class operation tags that
round-trip through the `LDAPMessage` envelope:

- `LDAPAddRequest(entry=..., attributes=[...])` — add a new entry; `entry` is the new
  DN (bytes after decode) and `attributes` is a list of `(LDAPAttributeDescription,
  BERSet([LDAPAttributeValue, ...]))` sequences.
- `LDAPModifyDNRequest(entry=..., newrdn=..., deleteoldrdn=..., newSuperior=None)` —
  rename/move; `entry`/`newrdn` are strings (bytes after decode), `deleteoldrdn` is a
  boolean (normalized to `0xFF` when true), and `newSuperior` is an optional new-parent
  DN (bytes after decode, `None` when absent).
- `LDAPAbandonRequest(id=...)` — an application-class integer naming the message id to
  abandon; decodes back with that id on `.value`.
- `LDAPExtendedRequest(requestName=..., requestValue=None)` — an extended operation:
  `requestName` (an OID) plus an optional `requestValue`; both round-trip as bytes, and
  an absent `requestValue` decodes to `None`.
- `LDAPPasswordModifyRequest(userIdentity=None, oldPasswd=None, newPasswd=None)` and
  `LDAPStartTLSRequest()` — both subclasses of `LDAPExtendedRequest` that pin a fixed
  `requestName` OID (`b"1.3.6.1.4.1.4203.1.11.1"` and `b"1.3.6.1.4.1.1466.20037"`
  respectively, also exposed as a class attribute `oid`). Password-modify packs its
  fields into the extended `requestValue`; StartTLS carries no `requestValue`. Both
  decode through the envelope as extended requests carrying their OID.
- `LDAPBindRequest` also supports **SASL** auth: with `sasl=True` the `auth` argument is
  a `(mechanism, credentials)` tuple carried under a context-class sequence (rather than
  the simple-auth octet string). It round-trips back as a `(mechanism, credentials)`
  bytes tuple with `.sasl` True; a credential-less SASL bind passes `credentials=None`
  and decodes to `(mechanism, None)`.

Honor RFC2251 default-value omission: only genuinely ASN.1 DEFAULT/OPTIONAL fields are
dropped from the wire when they equal their default — e.g. `ModifyDNRequest.deleteoldrdn`
and control criticality (omitted when at their boolean default), and absent optional
context-tagged fields. This does **not** cover plain mandatory fields such as the
BindRequest `version` integer, which is always serialized even at its default `3` (see
the default-bind wire above).

---

## Pillar 4 — Decoder contexts (load-bearing, must be constructible exactly as shown)

The grader builds nested decoder contexts and relies on the `fallback` / `inherit`
constructor keywords threading through them. Provide these classes in
`ldaptor.protocols.pureldap`, each a `BERDecoderContext` subclass with the appropriate
`Identities` registry:

- `LDAPBERDecoderContext` — registry of the LDAP filter + op classes (the general LDAP
  layer), constructed with a `fallback` (typically a `pureber.BERDecoderContext()`).
- `LDAPBERDecoderContext_Filter` — registry that can decode any filter PDU; constructed
  with both `fallback` and `inherit`.
- `LDAPBERDecoderContext_LDAPMessage` — registry including controls and search-result
  references; constructed with `fallback` and `inherit`.
- `LDAPBERDecoderContext_TopLevel` — maps the universal sequence tag to `LDAPMessage` so
  a raw sequence at the top level decodes as a message envelope.
- `LDAPBERDecoderContext_LDAPControls` — registry mapping the control tag to
  `LDAPControl`; constructed with `fallback`.

The grader constructs these contexts by nesting them through the `fallback` and
`inherit` keywords — e.g. a filter-decoding context whose `fallback` is the general
LDAP layer (itself falling back to a base `BERDecoderContext`) and whose `inherit` is a
base context; a top-level context whose `inherit` is an `LDAPMessage` context wired with
both fallback and inherit chains; and a controls context with a base-context fallback.
Your constructors must accept exactly the `fallback` / `inherit` keyword shape so this
nesting composes. The way `lookup_id` cascades to `fallback`, and `inherit()` returns
the inner context for recursive child decoding, is what lets nested filters and message
bodies decode through these layered registries.

---

## LDIF writer (`ldaptor.protocols.ldap.ldif`)

Module-level functions producing LDIF **bytes**:

- `attributeAsLDIF(attr, value) -> bytes`: a printable value writes `attr: value\n`
  (`attributeAsLDIF(b"cn", b"foo") == b"cn: foo\n"`). A value that needs protection is
  base64-encoded with a `::` separator: a **leading** space (`b" foo"` →
  `b"cn:: IGZvbw==\n"`), a **trailing** space (`b"foo "` → `b"cn:: Zm9vIA==\n"`), or a
  **non-printable** byte (`b"\xff"` → `b"cn:: /w==\n"`) all trigger base64. A value
  whose **first** character is `:` or `<` is likewise base64-protected (these are
  unsafe LDIF value-initial characters), so `b":foo"` and `b"<foo"` are emitted with
  the `::` separator. Do **not** 76-column-wrap the output.
- `asLDIF(dn, attributes) -> bytes`: emits a `dn:` line, then one line per attribute
  value, then a trailing blank line. `asLDIF(b"cn=foo", [(b"cn", [b"foo"]),
  (b"sn", [b"bar"])]) == b"dn: cn=foo\ncn: foo\nsn: bar\n\n"`.
- `containsNonprintable(value) -> bool`: True if the value contains a newline or a high
  byte (e.g. `b"a\nb"`, `b"\xff"`), False for plain printable ASCII (`b"abc"`).
- Also provide `manyAsLDIF` and `base64_encode` helpers. `base64_encode(value) ->
  bytes` returns the base64 of the bytes followed by a trailing newline
  (`base64_encode(b"foo") == b"Zm9v\n"`). `manyAsLDIF(entries) -> bytes` takes an
  iterable of `(dn, attributes)` pairs and emits a leading `version: 1` header (its
  own block, i.e. `b"version: 1\n\n"`) followed by each entry rendered as `asLDIF`
  would render it.

## LDIF parser (`ldaptor.protocols.ldap.ldifprotocol`)

- `LDIF` — a streaming line-oriented parser (a Twisted `LineReceiver` subclass). It is
  driven by feeding it physical lines via `lineReceived(line: bytes)`; a blank line
  terminates the current logical entry. On a completed entry it calls
  `gotEntry(entry)` (subclasses override this hook to collect results). It supports
  `super().__init__()` with no extra args.
- Recognized input structure:
  - An optional `version: N` header at the very start. The version must be numeric and
    `<= 1`. Like every logical line, the version line is processed one step behind
    (it is buffered until the next physical line arrives, so a following continuation
    line could fold into it); its validation therefore happens when that next line is
    delivered, not on the `version:` line itself.
  - A `dn: ...` line begins an entry; subsequent `attr: value` lines add values.
  - **Continuation folding**: a physical line beginning with a single space is appended
    (with the leading space stripped) to the previous logical line's value, so
    `description: hello \n world` yields the single value `b"hello world"`.
  - A `attr:: <base64>` line base64-decodes its value into the attribute set
    (`userPassword:: <b64 of "secret">` → value `b"secret"`).
  - A blank line separates / closes entries.
- The produced entry behaves like a mapping keyed by attribute name (bytes): `entry.dn`
  is the DN bytes, `entry[b"cn"]` is an iterable attribute-value set
  (`set(entry[b"cn"]) == {b"foo"}`).
- Error hierarchy (raise the specific subclass):
  - `LDIFEntryStartsWithSpaceError` — a continuation (leading-space) line appears before
    any logical line exists.
  - `LDIFEntryStartsWithNonDNError` — an entry's first logical line is not a `dn:` line
    (detected when the entry is closed by a blank line).
  - `LDIFVersionNotANumberError` — the `version:` header value is non-numeric.
  - `LDIFUnsupportedVersionError` — the version number is greater than 1.
  - All of the above derive from a common `LDIFParseError` base exported by the module.
