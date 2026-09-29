# dnspython — DNS Protocol Library

Implement **dns**, a pure Python DNS protocol library.

## Dependencies and Environment

This library uses **only the Python standard library** — it has no third-party runtime
dependencies. (TSIG message authentication is implemented with the stdlib `hmac`/`hashlib`
modules; no cryptography package is required.)

The environment is **offline**: there is no network access, and all tooling you need is already
installed. **Do not install anything** (`pip install`, `apt-get`, etc. will fail and are
unnecessary). The project is built and installed for grading by a `setup.sh` that runs offline,
so simply organize your implementation as an installable Python package named `dnspython` that
exposes the `dns` package below.

## Package Structure

```python
import dns.name
import dns.message
import dns.rdata
import dns.rdatatype
import dns.rdataclass
import dns.rdataset
import dns.rrset
import dns.flags
import dns.opcode
import dns.rcode
import dns.exception
import dns.renderer
import dns.serial
import dns.reversename
import dns.tsig
import dns.tsigkeyring
import dns.update
import dns.namedict
import dns.zone
```

## 1. DNS Names — `dns.name`

### `dns.name.Name(labels)`

A DNS name's total wire length must not exceed **255 octets** (each label contributes its
length plus one). Attempting to use an over-length name — at construction and when serializing
via `to_wire()` — raises `dns.name.NameTooLong`, a `dns.exception.FormError` subclass. (A single
label is likewise limited to 63 octets.)

**Key properties and methods:**
- `labels` — `tuple[bytes, ...]` of labels
- `is_absolute()` — `True` if name ends with the root label `b""`
- `to_text(omit_final_dot=False)` — the name in the standard DNS presentation (master-file) text
  form of RFC 1035 §5.1: a label byte that is a printable graphic character appears as-is, except
  `.`, which is escaped as `\.` (so it is not mistaken for a label separator); any other byte is
  written using that format's numeric escape.
- `to_wire(file=None, compress=None, origin=None, canonicalize=False)` — DNS wire format
- `is_subdomain(other)` / `is_superdomain(other)` — Subdomain checks
- `parent()` — Remove the leftmost label
- `__add__(other)` — Concatenate names
- `__len__()` — Number of labels
- `__eq__` / `__hash__` — Case-insensitive
- `__lt__` / `__gt__` — Canonical DNS name ordering: labels compared right-to-left, case-insensitively as lowercase bytes
- `__getitem__(index)` — Access individual labels

**Module-level functions:**
- `dns.name.from_text(text, origin=dns.name.root, idna_codec=None)` — Parse text to `Name`. Relative names get `origin` appended. `origin=None` keeps relative. Backslash escaping is the inverse of `to_text()` (`\.` embeds a literal dot within a label), so `from_text(name.to_text())` round-trips back to the original `Name`.
- `dns.name.from_wire_parser(parser)` — Parse from wire format with compression pointers.

**Constants:** `dns.name.root` (the root `.`), `dns.name.empty` (empty name)

## 2. DNS Messages — `dns.message`

### `dns.message.Message(id=None)`

A DNS message with header, question section, and three data sections.

**Attributes:**
- `id` — 16-bit message ID (random if None)
- `flags` — `dns.flags.Flag` bitfield (QR, AA, TC, RD, RA, AD, CD)
- `question` — List of `RRset` objects (question section)
- `answer` — List of `RRset` objects (answer section)
- `authority` — List of `RRset` objects (authority section)
- `additional` — List of `RRset` objects (additional section)
- `edns` — EDNS version (-1 if not present, 0 for EDNS0)
- `payload` — EDNS requestor UDP payload size advertised by the OPT record (the value set via
  `use_edns(payload=...)`); populated when an EDNS OPT record is present after `from_wire()`.

**Key methods:**
- `to_wire(origin=None, max_size=0, ...)` — Serialize to DNS wire format bytes. Supports name compression across sections.
- `opcode()` — Get opcode from flags
- `set_opcode(opcode)` — Set opcode in flags
- `rcode()` — Get response code. For rcodes > 15, the value is split: low 4 bits in the flags field, high bits in the EDNS OPT record's extended rcode field.
- `set_rcode(rcode)` — Set response code (handles the flags/EDNS split automatically)
- `use_edns(edns=0, ednsflags=0, payload=1232, ...)` — Configure EDNS

**Module-level functions:**
- `dns.message.from_wire(wire, ...)` — Parse wire-format bytes into a `Message`.
- `dns.message.make_query(qname, rdtype, use_edns=None, ...)` — Create a query message with one
  question. Sets the RD (Recursion Desired) flag by default (`flags = dns.flags.RD`). The
  `use_edns` keyword configures EDNS on the resulting message: pass an EDNS version int (e.g.
  `use_edns=0` for EDNS0) to attach an OPT record, equivalent to calling
  `Message.use_edns(edns=use_edns)` on the query, so the message's `edns` attribute becomes that
  version. The default `None` leaves EDNS off (`edns == -1`).
- `dns.message.make_response(query, ...)` — Create a response skeleton for a query. Sets QR flag, copies ID and question.

**Canonical wire round-trip.** The central usage flow is to build a message, serialize it with
`to_wire()`, and parse it back with `from_wire()`; the parsed message reproduces the original's
header fields and section contents:

```python
q = dns.message.make_query("example.com.", "A")
wire = q.to_wire()
q2 = dns.message.from_wire(wire)            # q2.id == q.id, same question

resp = dns.message.make_response(q)         # QR set, id/question copied from q
resp.answer.append(dns.rrset.from_text("example.com.", 300, "IN", "A", "192.0.2.1"))
resp.authority.append(dns.rrset.from_text("example.com.", 3600, "IN", "NS", "ns1.example.com."))
wire = resp.to_wire()
resp2 = dns.message.from_wire(wire)         # answer/authority rrsets recovered
```

The low-level `dns.renderer.Renderer` (section 8) builds the same wire via
`add_question(...)` / `add_rdataset(section, name, rdataset)` / `write_header()` / `get_wire()`,
and its output parses back through `dns.message.from_wire()` identically.

## 3. Record Data — `dns.rdata`

### `dns.rdata.Rdata(rdclass, rdtype)`

`Rdata` instances are **immutable**: their fields are set at construction and assigning to an
attribute afterwards (e.g. `rd.address = ...`) raises (`TypeError` or `AttributeError`).

**Key methods:**
- `to_text(origin=None, relativize=True)` — Text representation
- `__str__()` — Returns `self.to_text()`
- `to_wire(file=None, compress=None, origin=None, canonicalize=False)` — Wire format bytes
- `rdclass` / `rdtype` — Record class and type as IntEnums

`Rdata` instances of the same class/type are comparable: `__eq__` compares by value, and
`__lt__` / `__gt__` order by canonical wire-format byte ordering (RFC 4034) — for example, two A
records sort by their packed 4-byte address.

**Module-level functions:**
- `dns.rdata.from_text(rdclass, rdtype, text, ...)` — Parse text into the appropriate Rdata subclass.
- `dns.rdata.from_wire(rdclass, rdtype, wire, current, rdlen)` — Parse rdata of the given class/type from `rdlen` bytes of `wire` starting at offset `current`, returning the appropriate Rdata subclass (inverse of `Rdata.to_wire`).

**Generic (unknown-type) rdata.** A type with no dedicated implementation (e.g. the
`"TYPE12345"` spelling from section 7) is still parsed and rendered rather than rejected: its
rdata content is given to `dns.rdata.from_text` — and produced by `to_text()` — in the standard
generic presentation format RFC 3597 defines for unknown types, and `to_wire()` returns exactly
the rdata octets that text encodes (the inverse round-trip).

## 4. Record Types

Supported types: A, AAAA, NS, CNAME, PTR, MX, SOA, TXT, SRV. Standard DNS fields and wire/text encoding per RFCs. TXT `strings` attribute is a `tuple[bytes, ...]`.

The `to_text()` (and hence `str()`) presentation forms follow the standard zone-file
presentation:
- **MX** renders as `"<preference> <exchange>"` with a single space.
- **TXT** renders each string as a double-quoted token, separated by spaces.

The single-name record types **NS, CNAME, and PTR** expose their target domain name through a `.target` attribute (a `dns.name.Name`) — i.e. `ns_rd.target`, `cname_rd.target`, `ptr_rd.target`. (`SRV` likewise exposes its target host as `.target`, alongside `.priority`, `.weight`, `.port`.)

The remaining types expose their RFC fields as lowercase attributes too:
- **A**: `.address` (`str`, dotted-quad IPv4).
- **MX**: `.preference` (`int`), `.exchange` (`dns.name.Name`).
- **SOA**: `.mname`, `.rname` (`dns.name.Name`); `.serial`, `.refresh`, `.retry`, `.expire`, `.minimum` (`int`).

## 5. Rdataset — `dns.rdataset`

### `dns.rdataset.Rdataset(rdclass, rdtype, covers=NONE, ttl=0)`

**Key attributes:** `rdclass`, `rdtype`, `covers`, `ttl`

**Key methods:**
- `add(rd, ttl=None)` — Add rdata; enforces type/class match; TTL minimization
- `update_ttl(ttl)` — Set TTL to minimum of current and given
- `to_text(name=None, ...)` — Zone file text format
- `to_wire(name, file, compress=None, ...)` — Wire format with owner name
- `__getitem__(index)` — Indexed access into the set's elements (order is iteration order). Supports integer indices and slices.
- `__len__()` — Number of rdata records in the set
- `__iter__()` — Iterate over rdata records

Adding rdata of the wrong type raises `dns.rdataset.IncompatibleTypes`.

**Module-level functions:**
- `dns.rdataset.from_text(rdclass, rdtype, ttl, *text_rdatas)` — Create from text strings
- `dns.rdataset.from_rdata(ttl, *rdatas)` — Create from rdata objects

## 6. RRset — `dns.rrset`

`Rdataset` with an owner `name` attribute (`dns.name.Name`).

- `dns.rrset.from_text(name, ttl, rdclass, rdtype, *text_rdatas)`
- `dns.rrset.from_rdata(name, ttl, *rdatas)`

## 7. Enums — types, classes, flags, opcodes, rcodes

**`dns.rdatatype.RdataType`** (IntEnum): `A`, `NS`, `CNAME`, `SOA`, `PTR`, `MX`, `TXT`, `AAAA`, `SRV`, `ANY`, etc. `from_text(text)`, `to_text(value)`. Also accepts `"TYPE65"` format; unknown types render as `"TYPE123"`. Module-level constants: `dns.rdatatype.A`, etc.

**`dns.rdataclass.RdataClass`** (IntEnum): `IN`, `CH`, `HS`, `NONE`, `ANY`. `from_text(text)`, `to_text(value)`. Module-level constants: `dns.rdataclass.IN`, etc.

**`dns.flags.Flag`** (IntFlag): `QR`, `AA`, `TC`, `RD`, `RA`, `AD`, `CD`. `dns.flags.from_text("QR AA RD")`, `dns.flags.to_text(flags)`.

**`dns.opcode.Opcode`** (IntEnum): `QUERY`, `IQUERY`, `STATUS`, `NOTIFY`, `UPDATE`. `from_text(text)`, `to_text(value)`.

**`dns.rcode.Rcode`** (IntEnum): `NOERROR`, `FORMERR`, `SERVFAIL`, `NXDOMAIN`, `NOTIMP`, `REFUSED`, `BADVERS` (the extended rcode 16; values > 15 use the flags/EDNS split described in section 2), etc. `from_text(text)`, `to_text(value)`. Module-level constants: `dns.rcode.NOERROR`, `dns.rcode.BADVERS`, etc.

## 8. Wire Format Support

### `dns.renderer.Renderer(id=None, flags=0, max_size=65535, origin=None)`

Low-level wire format builder for DNS messages.

- `add_question(qname, rdtype, rdclass=IN)` — Add question record
- `add_rrset(section, rrset)` — Add RRset to a section
- `add_rdataset(section, name, rdataset)` — Add by name + rdataset
- `add_edns(edns=0, ednsflags=0, payload=4096, options=None)` — Append an EDNS0 OPT pseudo-record to the additional section
- `write_header()` — Write 12-byte header after sections
- `get_wire()` — Return completed wire bytes

The `max_size` cap is enforced **incrementally**: each `add_question` / `add_rrset` /
`add_rdataset` raises `dns.exception.TooBig` as soon as appending that record would push the wire
size past `max_size` (the partial record is rolled back). The check happens at append time, not
deferred to `get_wire()`.

Section constants: `QUESTION=0, ANSWER=1, AUTHORITY=2, ADDITIONAL=3`.


## 9. Exceptions — `dns.exception`

`dns.exception.DNSException` (base), `dns.exception.FormError`, `dns.exception.SyntaxError`, `dns.exception.TooBig`. Also: `dns.rdatatype.UnknownRdatatype` and `dns.name.NameTooLong` (a `FormError` subclass, raised for a name exceeding 255 octets — see section 1).

## 10. TSIG — `dns.tsig`

HMAC-based transaction signature authentication for DNS messages.

### `dns.tsig.Key(name, secret, algorithm="hmac-sha256")`

- `name` — key name (string or `dns.name.Name`)
- `secret` — base64-encoded secret
- `algorithm` — HMAC algorithm name

Algorithm names are represented as absolute DNS names and stringify with a trailing dot, e.g. `str(dns.tsig.HMAC_SHA256) == "hmac-sha256."` and `Key.algorithm` renders likewise (so `str(Key(..., algorithm="hmac-sha256").algorithm) == "hmac-sha256."`).

**Algorithm constants:** `dns.tsig.HMAC_SHA256`, `dns.tsig.HMAC_SHA512`, `dns.tsig.HMAC_SHA1`, `dns.tsig.HMAC_MD5`

### Signing and verification

- `message.use_tsig(keyring, keyname=...)` — attach TSIG to a message before `to_wire()`
- `dns.message.from_wire(wire, keyring=kr)` — parse a message and verify its TSIG signature.
  Verification is **mandatory** for a TSIG-signed wire: if the wire carries a TSIG record, a
  keyring must be supplied. Three cases raise (a `dns.exception` error):
  - the `keyring` argument is **omitted or `None`** while the wire is TSIG-signed — the key needed
    to verify is absent, so parsing raises (an omitted keyring is an error, not a way to skip
    verification);
  - a keyring **is** supplied but does not contain the message's named key;
  - the signature is bad (the key's secret does not match the signature).

  `Message.had_tsig` is `True` **only** after a TSIG-signed message has been successfully parsed
  *and* verified, and `False` otherwise (e.g. a message that carried no TSIG record). Parsing a
  wire with no TSIG record (the ordinary `from_wire(wire)` round-trip) never requires a keyring
  and does not raise.

### `dns.tsigkeyring`

- `dns.tsigkeyring.from_text(dict)` — create keyring from `{"keyname.": "base64secret"}` mapping

## 11. DNS UPDATE — `dns.update`

DNS dynamic update messages.

### `dns.update.UpdateMessage(zone, rdclass="IN")`

Creates an UPDATE message with opcode 5 (UPDATE).

**Section properties:** `zone` (list), `prerequisite` (list), `update` (list)

**Key methods:**
- `add(name, ttl, rdtype, *rdatas)` — add record to update section
- `delete(name, rdtype_or_rdata)` — delete record
- `replace(name, ttl, rdtype, *rdatas)` — replace record (delete + add, produces 2 entries)
- `present(name, rdtype)` — prerequisite: name/type must exist
- `absent(name)` — prerequisite: name must not exist
- `to_wire()` / parsed via `dns.message.from_wire()`

## 12. Name Dictionary — `dns.namedict`

### `dns.namedict.NameDict()`

`MutableMapping` keyed by `dns.name.Name`.

- `get_deepest_match(name)` — returns `(name, value)` for the deepest ancestor key.

## 13. Serial Number Arithmetic — `dns.serial`

### `dns.serial.Serial(value, bits=32)`

DNS serial number arithmetic with unsigned wraparound semantics.

- `value` — stored modulo `2^bits`
- Supports comparison with other `Serial` instances and with `int`
- `__add__(other)` — returns a new `Serial` with wrapped addition
- Wraparound comparison: `Serial(0xFFFFFFFF) < Serial(0)` is `True`

## 14. Reverse DNS — `dns.reversename`

- `dns.reversename.from_address(text)` — IP address to reverse lookup name
- `dns.reversename.to_address(name)` — reverse name back to address string

## 15. IPv4/IPv6 — `dns.ipv4`, `dns.ipv6`

`inet_aton(text)` → bytes, `inet_ntoa(bytes)` → text. For both IPv4 (4 bytes) and IPv6 (16 bytes).


## 16. Zone Files — `dns.zone`

### `dns.zone.from_text(text, origin=None, ...)`

Parse zone file text — the standard DNS master-file format of RFC 1035 §5.1 — into a `Zone`
object. Supports:
- `$ORIGIN` directive — sets the default domain used to qualify subsequent relative owner names.
  A relative owner name is first resolved to its absolute name by appending the active `$ORIGIN`.
  Regardless of which `$ORIGIN` was active, every node is then stored, keyed, and iterated under
  its name **relative to the zone's origin** (`Zone.origin`, the `origin=` passed to `from_text`).
- `$TTL` directive — sets the default TTL for subsequent records
- Multi-line records using parentheses `(` ... `)` with `;` comments
- Standard record types (SOA, NS, A, AAAA, MX, TXT, CNAME, etc.)
- The `@` owner-name convention — in a zone file, `@` denotes the zone origin (the apex).
  Correspondingly, `dns.name.from_text("@", None)` parses to the **empty relative name** (a
  `Name` with no labels), and the apex node is keyed/looked-up in the zone under that empty
  relative origin name (i.e. `zone[dns.name.from_text("@", None)]`).

### `dns.zone.Zone`

**Key attributes:**
- `origin` — `dns.name.Name`, the zone's origin domain

**Key methods and operations:**
- `zone[name]` — look up a node by relative `dns.name.Name`
- `find_node(name)` — look up a node, raises `KeyError` if not found
- Iteration yields relative `dns.name.Name` objects for each node. The apex/origin node is the
  empty relative name, which renders in text (and thus in iteration via `str(name)`) as `"@"`.
- `to_text()` — serialize zone back to text; round-trips via `from_text()`
- `__eq__` — zones are equal if same origin and identical nodes/rdatasets

Nodes (returned by `zone[name]`) have `find_rdataset(rdclass, rdtype)` and are iterable over rdatasets.
