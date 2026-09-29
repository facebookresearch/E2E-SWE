# FIX Message Codec & Session Engine

Implement a Java library that **encodes, decodes, validates**, and **runs a FIX
session** for the FIX (Financial Information eXchange) protocol. Your code must
live in the Java package **`io.fix`** — an automated integration-test suite
compiles against this package and constructs the classes named in §6 by name.

Target Java 11+. You may use only the JDK standard library (XML parsing via
`javax.xml.parsers` / `org.w3c.dom` is available and expected). The SLF4J API
(`org.slf4j.*`, `slf4j-api.jar`) is pre-staged on the compile + runtime classpath
at `/opt/deps/*.jar`, with a no-op `slf4j-simple` backend. No other third-party
JARs are allowed.

Organised as: (§1) the FIX wire format; (§2–§5) the four capabilities the
library provides, described via usage examples; (§6) a spec-style contract
reference naming the surface the integration suite binds to; (§7) the build
deliverable.

---

## 1. The FIX wire format

A FIX message is a flat sequence of `tag=value` pairs. Each pair is terminated by
a single **SOH** byte (ASCII `0x01`, written below as `|`). Tags are positive
integers; values are strings.

```
8=FIX.4.4|9=130|35=D|49=SENDER|56=TARGET|34=1|52=20240101-10:00:00.000|11=ORDER1|55=AAPL|54=1|60=20240101-10:00:00.000|38=100|40=2|44=150.50|59=0|10=201|
```

A message has three ordered sections:

- **Header** — always begins with tag `8` (BeginString), then `9` (BodyLength),
  then `35` (MsgType), followed by any other header fields.
- **Body** — the application fields.
- **Trailer** — always ends with tag `10` (CheckSum). Any other trailer fields
  come before `10`; where a trailer field carries a length prefix (e.g.
  `93 SignatureLength` for `89 Signature`) the length precedes its value.

**BodyLength (tag 9)** counts bytes in the message body — everything between the
SOH that terminates BodyLength and the SOH before the CheckSum field, in the
configured charset. **CheckSum (tag 10)** is the sum of every byte before `10=`,
modulo 256, formatted as **exactly three zero-padded ASCII digits** (e.g.
`10=026|`, not `10=26|`). Both are (re)computed by the library on every encode;
callers never set them by hand.

### Repeating groups
A repeating group is a *count* field whose value is the number of repetitions,
immediately followed by that many repetitions. Every repetition begins with a
designated **delimiter** field (the first field of the group). Example — `268`
counts entries, each delimited by `269`:

```
...|268=2|269=0|270=150.10|269=1|270=150.20|...
```

### Length-prefixed data fields
Some fields carry free-form data whose value **may itself contain the SOH byte**
(e.g. `RawData`, tag 96). In the dictionary such a field has type `DATA` and is
**always immediately preceded by its length field** (type `LENGTH`), whose value
is the exact number of bytes in the data value:

```
...|95=3|96=a?b|...        (95=RawDataLength, 96=RawData; the value "a?b" is 3 bytes, the middle one an SOH)
```

When decoding, on reaching a `DATA` field you must consume **exactly** the number
of bytes given by the preceding `LENGTH` field as the value (SOH bytes included),
then expect the terminating SOH.

---

## 2. Encoding and decoding messages

### Building a message

A caller assembles a message by setting header fields, body fields, and (where
needed) trailer fields, then serialising to the wire. Serialisation orders
fields canonically: `8`, `9`, `35` first in the header, ascending tag order
otherwise (in both header tail and body), `10` last. Within a repeating-group
entry the delimiter comes first, then the entry's remaining fields in
ascending tag order. BodyLength and CheckSum are recomputed on every call.

```java
Message m = new Message();
m.getHeader().setString(8, "FIX.4.4");
m.getHeader().setString(35, "0");                          // Heartbeat
m.getHeader().setInt(34, 42);
m.getHeader().setString(49, "CLIENT");
m.getHeader().setString(56, "SERVER");
m.getHeader().setString(52, "20240101-10:00:00.000");
String wire = m.toString();
// wire == "8=FIX.4.4|9=56|35=0|34=42|49=CLIENT|52=...|56=SERVER|10=125|" (SOH shown as |)
```

Header, body, and trailer are separately accessible: `m.getHeader()` returns
the header FieldMap, `m.getTrailer()` returns the trailer. Body fields are set
directly on the Message. `isEmpty()` returns `true` iff no field is set in any
of the three sections (any `setString`/`setInt`/... flips it to `false`).
`toString()` on a freshly-constructed empty Message is deterministic and emits
just the recomputed BodyLength/CheckSum framing around an empty body — only the
`9` and `10` fields, with no BeginString, no MsgType and nothing between them;
both values follow from the §1 rules. Two independently-constructed empty
messages produce the same output.

### Field storage: `FieldMap`

Header, body, trailer, and repeating-group entries all share a common
field-storage abstraction (a **FieldMap**) offering typed accessors keyed by
integer tag. Setters exist for every primitive FIX type: **String, int, double,
char, boolean**, plus **BigDecimal** (for exact-precision monetary values where
`double` would introduce floating-point drift), **byte[]**, and the three
UTC-time types (**timestamp, time-only, date-only**). Getters mirror the setter
family and raise `FieldNotFound` when the tag is absent. Booleans are encoded on
the wire as `Y` / `N` — a `getBoolean` call on a value that isn't exactly `Y` or
`N` raises `FieldException`. The typed getters likewise reject values that don't
parse (e.g. `getInt` on `"100.5"`, `getChar` on `"AB"`) rather than silently
truncating.

`setDouble` and `setDecimal` each have a **padding overload** taking an extra
`int` — the number of **trailing decimal digits** the value is emitted with.
`setDouble(44, 150.5, 4)` and `setDecimal(44, new BigDecimal("150.5"), 4)` both
produce the wire string `"150.5000"`.

The primitive API is what a first-time user reaches for. The library
additionally exposes a **typed `Field<T>` subclass per FIX base data type** —
an integration point for code that generates FIX-message classes from a
dictionary (including **User-Defined Fields**, whose custom tag numbers extend
one of the base types). A caller wraps a `(tag,value)` pair in the appropriate
subclass and hands it to `setField`; the mirror `getField` takes a template
instance (whose tag identifies the slot) and returns a populated field of the
same subclass. Each subclass carries `getValue` / `setValue` for its type. The
value type for each subclass is:

| Subclass | Value type |
|---|---|
| `StringField` | `String` |
| `IntField` | `Integer` (int primitive overloads too) |
| `DoubleField` | `Double` |
| `CharField` | `Character` |
| `BooleanField` | `Boolean` |
| `DecimalField` | `BigDecimal` |
| `BytesField` | `byte[]` |
| `UtcTimeStampField` | `java.time.LocalDateTime` |
| `UtcTimeOnlyField` | `java.time.LocalTime` |
| `UtcDateOnlyField` | `java.time.LocalDate` |

```java
Message m = new Message();
m.setField(new IntField(34, 42));
IntField got = m.getField(new IntField(34));   // template carries the tag
assert got.getValue() == 42;
```

### Repeating groups

Repeating groups are stored as a list of **Group** entries keyed by count-tag.
Each Group is itself a FieldMap, so nested groups are just Groups added to
Groups. Group indices are 1-based.

```java
Message m = new Message();
m.getHeader().setString(8, "FIX.4.4");
m.getHeader().setString(35, "W");                          // MarketDataSnapshot
// ... other header fields ...
m.setString(55, "AAPL");
for (int i = 0; i < 2; i++) {
    Group entry = new Group(268, 269);                      // countTag=268, delimTag=269
    entry.setChar(269, i == 0 ? '0' : '1');
    entry.setDouble(270, 150.10 + i * 0.10);
    m.addGroup(entry);
}
// m.getGroupCount(268) == 2; m.getGroup(1, 268) returns the first entry
```

FieldMap supports: `addGroup`, `getGroups(countTag)`, `getGroup(index,
countTag)` and its overload `getGroup(index, template)`, `getGroupCount`,
`hasGroup(countTag)` and its 1-based-index overload `hasGroup(index, countTag)`,
`removeGroup(index, countTag)` (drops the indexed entry, shifts subsequent
entries down, and decrements the count reported by `getGroupCount`), and the
bulk operations `setFields(other)` and `setGroups(other)` — both of which
**replace** the receiver's contents (they are not a merge).

### Parsing wires

`new Message(wire)` parses a wire without a dictionary — it reads every field
and separates header from trailer from body, but does not reconstruct repeating
groups (a group appears as a count field followed by the raw delimiter/entry
fields, all in the body). The two- and three-arg overloads accept a
`DataDictionary` (or session-dict + application-dict pair for FIXT.1.1, see §4)
and use it to reconstruct groups (including nested groups) and to consume
length-prefixed DATA fields correctly. When a dict-aware parse meets a repeating
group whose declared count field disagrees with the number of delimiter-led
entries actually present, it neither raises `InvalidMessage` nor silently
normalises the count: the reconstructed entries and the wire-declared count are
both preserved, so the discrepancy stays visible to `validate()` (§3).

Parsing retains every field read off the wire, including the framing fields
BodyLength(9) and CheckSum(10): after any parse `getHeader().getInt(9)` returns
the wire's BodyLength and `getTrailer().getString(10)` returns its CheckSum. The
§1 rule that 9/10 are recomputed on every encode and never set by hand governs
the build/encode path only — a freshly-built empty message treats them as
computed framing (so they don't count toward `isEmpty()`), but a parse stores
the values present on the wire like any other field.

```java
Message parsed = new Message(wire);                        // no-dict parse
Message parsed2 = new Message(wire, dd);                   // dict-aware
```

The parser raises `InvalidMessage` when the wire is structurally malformed
(empty; wrong tag order for the mandatory prefix; missing BodyLength or
CheckSum; a pair with no `=` separator; a non-numeric tag) or when the embedded
CheckSum doesn't match the recomputed CheckSum. For any canonical input,
`new Message(s).toString().equals(s)` holds.

### Charset

BodyLength and CheckSum count **bytes**, not chars. Under UTF-8 a multibyte
character (`é`, etc.) contributes multiple bytes to both counts. The active
charset is managed via `CharsetSupport`: `setCharset(String)` selects a
charset, `getCharset()` returns the current one, `setDefaultCharset()` restores
the ISO-8859-1 default.

---

## 3. Validation

A `DataDictionary` loads the FIX XML dictionary from the classpath (e.g.
`new DataDictionary("FIX44.xml")`) and provides `validate(Message)` — an
integrity check against everything the dictionary declares about the message
type: required fields, allowed fields, enum values, data types, and group
counts.

`validate` raises the first violation it finds as **one of three typed
exceptions**:

- `IncorrectTagValue` — a field's value is not among the dictionary's declared
  enum values for that field. `getField()` returns the offending tag.
- `IncorrectDataFormat` — a field's value doesn't conform to its declared data
  type (e.g. `"not-a-timestamp"` in a `UTCTIMESTAMP` field). `getField()`
  returns the offending tag.
- `FieldException` — a structural / membership violation: `MsgType(35)` not
  defined in the dictionary; an unknown tag; a tag not allowed on this message
  type; a required field missing; a field present with empty value; a repeating
  group's count field disagreeing with the actual number of entries; group
  entry fields out of order. `getField()` returns the offending tag.

The three exception types let a caller distinguish "bad value in a known slot"
(the typed exceptions) from "wrong shape" (`FieldException`) without switching
on numeric codes.

```java
DataDictionary dd = new DataDictionary("FIX44.xml");
Message nos = /* ... build a NewOrderSingle ... */;
nos.setChar(54, 'X');                                       // Side='X' is not a legal enum value
nos.toString();                                             // populate 9/10
try { dd.validate(nos); }
catch (IncorrectTagValue e) { /* e.getField() == 54 */ }
```

A conforming message returns from `validate` without throwing.

### The dictionary's schema

The dictionary describes fields (tag number, name, data type, and any legal
`<value enum=...>` values), messages (each `<message msgtype=...>` with its
allowed and required fields, groups, and component references), header and
trailer sections, and reusable components. A `<component name="X" required="R"/>`
reference (inside a message, group, or another component) **expands in place**
into component X's fields and groups, recursively. The `<header>` and
`<trailer>` blocks may themselves contain `<group>` elements (e.g. `NoHops(627)`
in FIX 4.4's header); reconstruct these exactly as body groups.

### Data types

Field values must conform to their declared type — a violation raises
`IncorrectDataFormat`:

- `INT`, `SEQNUM`, `LENGTH`, `NUMINGROUP` — a base-10 integer.
- `FLOAT`, `QTY`, `PRICE`, `AMT`, `PRICEOFFSET`, `PERCENTAGE` — a decimal number.
- `BOOLEAN` — exactly `Y` or `N`.
- `UTCTIMESTAMP` — `YYYYMMDD-HH:MM:SS` with optional `.sss` (or finer) fraction.
- `UTCTIMEONLY` — `HH:MM:SS[.sss]`; `UTCDATEONLY` — `YYYYMMDD`.
- `CHAR` — a single character.
- `DATA` — length-prefixed bytes (see §1); no format constraint.
- other string-like types (`STRING`, `CURRENCY`, `COUNTRY`, `MONTHYEAR`, ...) —
  any non-empty value.

---

## 4. FIX 5.0 dual dictionaries (FIXT.1.1)

FIX 5.0 splits the protocol into a **transport/session** layer and an
**application** layer, each with its own dictionary:

- The **session dictionary** (`FIXT11.xml`, provided) defines the message
  header and trailer and the session/admin messages (Logon, Heartbeat, …). Its
  version is `FIXT.1.1`.
- The **application dictionary** (`FIX50SP2.xml`, provided) defines the
  application messages (NewOrderSingle, …) and their fields, components, and
  groups.

A FIX 5.0 message has `BeginString(8)=FIXT.1.1` and carries `ApplVerID(1128)`
in the header (a header field defined by the session dictionary; `9` =
FIX50SP2). When both dictionaries are supplied, parsing uses the session
dictionary for header/trailer groups and the application dictionary for body
groups; validation likewise routes header/trailer to the session dictionary
and the body (including the message-type check and required-field checks) to
the application dictionary.

```java
DataDictionary sess = new DataDictionary("FIXT11.xml");
DataDictionary app  = new DataDictionary("FIX50SP2.xml");
Message parsed = new Message(wire, sess, app);
DataDictionary.validate(parsed, sess, app);
```

---

## 5. Session layer

A **Session** manages one bidirectional FIX conversation: per-direction
sequence numbers, the Logon/Logout dance, heartbeat exchange, gap recovery, and
message routing. All user-visible session behaviour is delivered through the
**Application** callback interface — user code doesn't inspect internal state
flags or hand-parse Session-emitted wire messages.

### The Application interface

User code implements Application to plug into the Session. Each callback fires
**exactly once per matching event**. The callbacks:

- `onCreate(SessionID)` — lifecycle hook; required on the interface. The
  integration suite does not assert when it fires.
- `onLogon(SessionID)` — after a successful Logon exchange completes (this side
  just became logged on).
- `onLogout(SessionID)` — after Logout completes or the transport drops.
- `toAdmin(Message, SessionID)` — **before** an outbound admin message
  (Logon/Logout/Heartbeat/TestRequest/ResendRequest/SequenceReset/Reject) is
  written to the wire. The implementation may **mutate** the message — the
  most common use is adding `Username(553)` / `Password(554)` to an outbound
  Logon. Exceptions thrown from `toAdmin` are logged, not re-raised.
- `fromAdmin(Message, SessionID)` — after session-layer processing of an
  inbound admin message. Throwing `RejectLogon` from a Logon callback aborts
  the session; the interface also declares `FieldNotFound`,
  `IncorrectDataFormat`, and `IncorrectTagValue` in its `throws` clause.
- `toApp(Message, SessionID)` — before an outbound app message is written.
  Throwing `DoNotSend` cancels the send: `send()` returns `false` and the
  sender sequence does **not** advance.
- `fromApp(Message, SessionID)` — after sequence checks for an inbound app
  message. Throwing `UnsupportedMessageType` causes the Session to emit a
  `BusinessMessageReject(35=j)` back to the peer and continue. The interface
  also declares `FieldNotFound`, `IncorrectDataFormat`, and `IncorrectTagValue`.

Routing invariant: **every inbound message dispatches to exactly one of
`fromAdmin` / `fromApp`, never both, never neither**. Application code learns
whether a message was admin or app by which callback fires — it doesn't
inspect the message directly. Symmetrically every outbound message passes
through `toAdmin` or `toApp` before the wire is written.

### Wiring and driving the session

Construct a Session with `(Application, MessageStoreFactory, SessionID, int
heartbeatInterval)`. `MemoryStore` (via `MemoryStoreFactory`) is the reference
persistence layer; `heartbeatInterval` is in seconds (`0` disables heartbeats).
The transport is attached separately: `setResponder(Responder)` binds the wire,
`setResponder(null)` detaches it.

```java
Session session = new Session(myApp, new MemoryStoreFactory(),
    new SessionID("FIX.4.4", "SENDER", "TARGET"), /*heartbeatInterval=*/30);
session.setResponder(myTransport);
```

The Session runs on **manual ticks** — `next()` (no-arg) is a time-based tick
(emits a queued Logon/Logout, checks heartbeat timers, etc.); `next(Message)`
processes one inbound message. `send(Message)` sends an outbound app message
returning `true`/`false`. `disconnect(String, boolean)` tears down the
transport. Threading, I/O, timers, and session-time windows are the caller's
responsibility.

**Initiator-side Logon.** Call `logon()` to enable Logon state, then `next()`
to actually emit the outbound `Logon(35=A)` (this fires `toAdmin` with the
message, writes the wire via the Responder, and stamps `EncryptMethod(98)=0`
and the configured `HeartBtInt(108)`). The reply arrives via `next(inboundLogon)`
— which flips `isLoggedOn()` to `true` and fires `Application.onLogon`.

```java
session.logon();
session.next();                       // emits outbound Logon(A), fires toAdmin
Message reply = /* inbound Logon */;
session.next(reply);                  // fires onLogon, isLoggedOn() -> true
```

**Sending an app message.** `send(msg)` fires `toApp`, writes the wire, persists
the wire to the `MessageStore` for later replay, and advances the sender
sequence. If `toApp` throws `DoNotSend`, the send is aborted and the sender
sequence does not advance. If no Responder is attached, `send` returns `false`.
An application message can only be sent on an established (logged-on) session: if
the session is not currently logged on, `send` is a no-op that returns `false` —
nothing is written to the Responder and the sender sequence does not advance.

**Logout.** `logout()` enables outbound Logout; the next `next()` tick fires
`toAdmin` with `Logout(35=5)` and writes the wire. `logout(String reason)`
additionally writes `reason` to `Text(58)` on the outbound Logout.

**Auto-replies.** The framework handles inbound admin messages transparently:
`TestRequest(35=1)` triggers an outbound `Heartbeat(35=0)` echoing the
request's `TestReqID(112)`; `Logout(35=5)` triggers a reply Logout, fires
`Application.onLogout`, and clears `isLoggedOn()`.

**Sequence gap recovery.** If an inbound message's `MsgSeqNum(34)` is *greater*
than expected, the Session emits a `ResendRequest(35=2)`. The peer's
`ResendRequest(35=2)` triggers replay of persisted wires from the MessageStore
in the requested range, each re-emitted with `PossDupFlag(43)=Y`.
`EndSeqNo(16)=0` is the FIX convention for "everything from BeginSeqNo onward".

**Sequence reset.** Inbound `SequenceReset(35=4)` with `GapFillFlag(123)=Y`
advances the expected target sequence to `NewSeqNo(36)`; with `GapFillFlag=N`
(Reset mode) it forces the expected target sequence to `NewSeqNo` regardless
of the message's own `MsgSeqNum`.

A Logon exchange in which either side sets `ResetSeqNumFlag(141)=Y` resets
both sequence counters as part of establishing the session; after the reply
has been processed the next-target counter is `2` (the reply's own MsgSeqNum
was `1`) and the next-sender counter is `≤ 2` (implementation may or may not
have already emitted a message on the reset-numbered sender stream).

**Error responses.** An inbound message with `MsgSeqNum` *less* than expected
(and lacking `PossDupFlag=Y` + `OrigSendingTime`) tears down the transport
(`Responder.disconnect()` is called; `Application.onLogout` fires). A CompID
mismatch (inbound `SenderCompID(49)` doesn't match this session's expected
TargetCompID, or `TargetCompID(56)` doesn't match ours) causes the Session to
fire `toAdmin` with an outbound `Reject(35=3)` and then `toAdmin` with an
outbound `Logout(35=5)`; the actual transport teardown waits for the peer's
Logout reply.

### Optional: `SessionStateListener`

An optional lifecycle observer, supplemental to Application. Register with
`Session.addStateListener`, deregister with `removeStateListener`. Methods
(all first arg is `SessionID`):

- `onConnect`, `onDisconnect`, `onLogon`, `onLogout`, `onReset`, `onRefresh`,
  `onMissedHeartBeat`, `onHeartBeatTimeout` — all take just `SessionID`.
- `onConnectException(SessionID, Exception)`.
- `onResendRequestSent(SessionID, int beginSeqNo, int endSeqNo, int currentEndSeqNo)`.
- `onSequenceResetReceived(SessionID, int newSeqNo, boolean gapFill)`.
- `onResendRequestSatisfied(SessionID, int beginSeqNo, int endSeqNo)`.

Implementations may leave most methods empty; the framework guarantees
`onLogon` and `onLogout` fire alongside their Application counterparts.

---

## 6. Contract reference

The tests bind to the class names, constructors, and methods listed here. Every
entry maps back to behaviour described in §2–§5; the prose there is
authoritative on semantics — this section names the surface only. Where a
method is used only via a callback interface, only the interface signature is
listed here.

### Codec (§2)

- **`FieldMap`** — abstract; primitive setters `setString`/`setInt`/`setDouble`
  (+ 3-arg padding overload)/`setChar`/`setBoolean`, mirror getters (raise
  `FieldNotFound` if the tag is absent); BigDecimal API `setDecimal(tag,
  BigDecimal)`, `setDecimal(tag, BigDecimal, padding)`, `getDecimal`,
  `getOptionalDecimal` returning `Optional<BigDecimal>`; membership
  `isSetField(tag)`, `removeField(tag)`; groups `addGroup(Group)`,
  `getGroupCount(countTag)`, `getGroups(countTag)`, `getGroup(index, Group
  template)`, `getGroup(index, countTag)`, `hasGroup(countTag)`,
  `hasGroup(index, countTag)`, `removeGroup(index, countTag)`; bulk
  `setFields(FieldMap other)`, `setGroups(FieldMap other)`; typed-Field
  overloads `setField(f)` and `getField(template)` for each subclass listed
  in §2.

- **`Message extends FieldMap`** — constructors: no-arg (empty),
  `Message(String wire)`, `Message(String wire, DataDictionary dd)`,
  `Message(String wire, DataDictionary sessionDict, DataDictionary appDict)`.
  All three parse constructors raise `InvalidMessage`. Instance: `getHeader()`
  → `Header`, `getTrailer()` → `Trailer`, `isEmpty()`, `clear()` (wipes all
  three sections), `toString()`. `Header` and `Trailer` are nested subclasses
  of `FieldMap` (no additional members required).

- **`Group extends FieldMap`** — constructor `(int countTag, int
  delimiterTag)`, plus `getFieldTag()` (count tag) and `delim()` (delimiter
  tag).

- **`CharsetSupport`** — final utility. Static: `setCharset(String)` (may
  raise `UnsupportedEncodingException`), `getCharset()` returning the active
  charset's canonical name as a `String` (the same form `setCharset` accepts),
  `setDefaultCharset()`.

- **Typed `Field<T>` classes** — abstract base `Field<T>` implementing
  `java.io.Serializable`, holding a `(tag, value)` pair, exposing `getTag`
  / `getField` (alias) / `getObject` / `setTag(int)`, `toString`, and
  `equals`/`hashCode` by `(tag, value)`. One subclass per FIX base data
  type (see §2 table for the T binding). Each subclass exposes a `(int
  tag)` no-value constructor, a `(int tag, T value)` constructor, plus
  `getValue()` and `setValue(T)`.

### Validation (§3)

- **`DataDictionary`** — construct from a classpath resource or file path via
  `DataDictionary(String location)` (raises `ConfigError`). `getVersion()`
  returns the BeginString (`"FIX.4.4"`, `"FIXT.1.1"`, `"FIX.5.0"`, ...).
  `validate(Message)` raises `IncorrectTagValue`, `IncorrectDataFormat`, or
  `FieldException` on the first violation (also declares `FieldNotFound`).
  The static `DataDictionary.validate(Message, DataDictionary sessionDict,
  DataDictionary appDict)` performs the dual-dictionary validation of §4.

### Session (§5)

- **`Application`** — user-supplied interface, seven callbacks. All take
  `(Message, SessionID)` except the three lifecycle callbacks
  (`onCreate`/`onLogon`/`onLogout`) which take only `SessionID`. Checked
  exception clauses: `fromAdmin throws FieldNotFound, IncorrectDataFormat,
  IncorrectTagValue, RejectLogon`; `toApp throws DoNotSend`; `fromApp throws
  FieldNotFound, IncorrectDataFormat, IncorrectTagValue,
  UnsupportedMessageType`.

- **`Responder`** — user-supplied interface. `send(String)` returning
  `boolean`; `disconnect()`; `getRemoteAddress()` returning `String`.

- **`MessageStore`** — interface. `set(int seq, String wire)` returning
  `boolean`, `get(int start, int end, Collection<String> out)`,
  `getNextSenderMsgSeqNum` / `getNextTargetMsgSeqNum` /
  `setNextSenderMsgSeqNum(int)` / `setNextTargetMsgSeqNum(int)` /
  `incrNextSenderMsgSeqNum()` / `incrNextTargetMsgSeqNum()`, `reset()`
  (clear wires + reset both counters to 1), `refresh()` (reload from
  backing medium — no-op for in-memory stores). `set` and `get` may raise
  `IOException`.

- **`MessageStoreFactory`** — one method: `create(SessionID)` returning a
  `MessageStore`.

- **`Session`** — main entry point. Constructor: `(Application,
  MessageStoreFactory, SessionID, int heartbeatInterval)`. Accessors:
  `getSessionID`, `getStore`, `getResponder`, `setResponder(Responder)`
  (accepts `null` to detach), `hasResponder`, `isLoggedOn`. Sequence
  rewrite: `setNextSenderMsgSeqNum(int)` and `setNextTargetMsgSeqNum(int)`
  (may raise `IOException`). Lifecycle operations: `logon()`, `logout()`,
  `logout(String reason)`, `next()`, `next(Message)`, `send(Message)`
  returning `boolean`, `disconnect(String reason, boolean logError)`
  (may raise `IOException`). Listeners: `addStateListener`,
  `removeStateListener`.

- **`SessionStateListener`** — optional lifecycle observer with the twelve
  callbacks listed in §5. Signatures as given there.

- **`SessionID`** — value class implementing `java.io.Serializable`. Public
  static final `NOT_SET = ""`. Constructors: no-arg (all fields set to
  `NOT_SET`), three-arg `(beginString, senderCompID, targetCompID)`, four-arg
  `(beginString, senderCompID, targetCompID, qualifier)`. Getters for
  `BeginString`, `SenderCompID`, `TargetCompID`, `SenderSubID`,
  `TargetSubID`, `SenderLocationID`, `TargetLocationID`, `SessionQualifier`.
  `equals`/`hashCode` by content; `toString` in a human-readable form
  (e.g. `"FIX.4.4:CLIENT->SERVER"`).

- **Required concrete implementations** — must be shipped under `io.fix`;
  the integration suite constructs them by name:

  | Class | Implements | Notes |
  |-------|------------|-------|
  | `MemoryStore` | `MessageStore` | `MemoryStore()` and `MemoryStore(SessionID)`; `refresh()` no-op |
  | `MemoryStoreFactory` | `MessageStoreFactory` | no-arg; one fresh store per SessionID |

### Exceptions

- `FieldNotFound extends Exception` — constructor takes `int field`; public
  field `field` carries the offending tag.
- `InvalidMessage extends Exception` — raised by Message parse constructors.
- `ConfigError extends Exception` — raised by `DataDictionary(String)`.
- `IncorrectTagValue extends Exception` — enum-value violation; `getField()`
  returns the offending tag.
- `IncorrectDataFormat extends Exception` — data-type violation;
  `getField()` returns the offending tag.
- `FieldException extends RuntimeException` — structural / membership
  violation (from `validate` and from primitive getters on unparseable
  values). Constructor `(int sessionRejectReason, int field)`; `getField()`
  returns the offending tag.
- `RejectLogon extends Exception` — thrown by `fromAdmin` to abort a Logon.
  Four constructors — no-arg, `(String msg)`, `(String msg, int
  sessionStatus)`, `(String msg, boolean logoutBeforeDisconnect, int
  sessionStatus)`. Getters: `getSessionStatus` (returns `-1` if unset) and
  `isLogoutBeforeDisconnect` (defaults to `true`; only the four-arg
  constructor can set `false`).
- `DoNotSend extends Exception` — thrown by `toApp` to cancel a send.
- `UnsupportedMessageType extends Exception` — thrown by `fromApp` to make
  the framework emit a BusinessMessageReject to the peer.

---

## 7. Deliverable

A buildable Java project defining the `io.fix` package. Your source may live
anywhere convenient under `/app/`, but the following contracts are enforced:

- **`/app/setup.sh`** — a shell script that, run from `/app`, compiles your
  source and leaves the resulting `.class` files (or `.jar`s) in one of the
  accepted output locations below. No network is available; use only the JDK
  toolchain (`javac`, `jar`) and the pre-staged `/opt/deps/*.jar`.
- **Compiled output** must land at one of these locations:
  - `/app/out/` (bare `javac -d /app/out ...`)
  - `/app/build/classes/` (Gradle default)
  - `/app/target/classes/` (Maven default)
  - `/app/build/libs/*.jar` (Gradle assembled JARs)
  - `/app/target/*.jar` (Maven assembled JARs)

  Nested build layouts such as `/app/repo/target/classes/` are NOT on the
  search path. Keep your build's output at `/app/`-level, not one directory
  deeper.

- **Dictionaries** live at `/app/dictionaries/` at grade time and are also
  placed on the runtime classpath so `new DataDictionary("FIX44.xml")`
  resolves via the classloader.
- **SLF4J** (`slf4j-api.jar` + `slf4j-simple.jar`) is pre-staged at
  `/opt/deps/` and is on both the compile and runtime classpath.

The grading suite compiles + runs a set of Java test drivers against your
compiled classes; each driver exercises one aspect of the library (encode,
decode, round-trip, validate, session lifecycle).
