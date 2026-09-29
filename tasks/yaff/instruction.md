# YaFF — a zero-copy flat serialization runtime (C++)

Implement the runtime library of **YaFF** ("Yet another Flat Format"): a high-performance,
zero-copy binary serialization format in the spirit of FlatBuffers. A message is written once
into a contiguous byte buffer and then read back **without any parsing step** — readers are thin
views that compute field locations directly from the bytes. The same wire bytes can be produced
and consumed across three physical layouts (*fixed*, *flat*, *sparse*) plus arrays and strings,
all sharing one relative-offset addressing scheme.

You are implementing the header-only runtime only. There is no `.proto` compiler, no protobuf
dependency, and no code generation in scope — the schema of each message is supplied at compile
time as a small **meta-trait** struct (described below), exactly as generated code would supply it.

## Environment & deliverable

- **Language:** C++20. The project is **header-only**.
- **Layout (required — the grader compiles tests against these paths):**
  - Put the project at the **root of your working directory** — do not nest it in a sub-folder.
    Public headers go under `include/yaff/` (i.e. `./include/yaff/…`), namespace `yaff`.
  - The umbrella header `include/yaff/yaff.h` must be includable, and each of the headers below
    must be includable directly by its own path (e.g. `#include <yaff/serializer.h>`), where the
    compiler is given `./include` as an include directory.
- `include/yaff/base.h` may `#include <yaff/version.h>`; **the build provides `yaff/version.h`**, so
  you do not need to create it.
- The environment is **offline**: do not fetch anything; the project builds from your sources alone.
- Recommended header set (you may split further, but keep these include paths working):
  `base.h`, `buffer.h`, `array.h`, `message.h`, `serializer.h`, `util.h`, `yaff.h`.

## Core addressing model

- All cross-object references are stored as **32-bit relative offsets** (`using Offset = uint32_t`),
  i.e. the byte distance between the referencing location and the target. This makes a buffer
  position-independent (memcpy/mmap friendly). An `Offset` of `0` denotes *null / absent*.
- Reads and writes are **unaligned** (use `memcpy`-style access); do not assume natural alignment.
- The buffer is built with a **dual-ended buffer**: one cursor grows up from the start (scratch /
  bookkeeping), the other grows down from the end (the message payload). **The finished message is
  the right/down segment**, and `Serializer::Data()` points at its start.
- `Serializer::Finish(root_offset)` writes a leading 4-byte start `Offset` so the buffer begins with
  a pointer to the root object. `yaff::ReadMessage<T>(buf)` reads that start offset and returns a
  reference to the root `T` (and returns `T::Default()` when `buf == nullptr`).

## `base.h` — wire primitives (namespace `yaff`)

Provide at least:

- Types: `Offset` (`uint32_t`), `SignedOffset` (`int32_t`), `FieldId` (`uint16_t`),
  `FieldOffset` (`uint16_t`), and the byte aliases used by the buffer.
- `template<class T> T ReadValue(const void* p)` — unaligned load of a `T`.
- `template<class T> T ReadValue(const void* p, const void** next)` — same, and sets `*next` to
  `p + sizeof(T)`.
- `template<class T> void WriteValue(void* p, T v)` — unaligned store.
- `template<class T> T XorDef(T v, T d)` — returns `v ^ d`, with float/double specializations that
  xor the bit patterns (so `XorDef` is its own inverse for every supported `T`). This is the
  **default encoding**: a scalar is stored as `value XOR default`, so a value equal to its default
  stores as all-zero bits.
- `template<class T> bool IsEqual(T a, T b)` — equality, with float/double specializations using an
  epsilon tolerance.
- `Offset ToCheckedOffset(uint64_t v)` — narrow to `Offset`, throwing `std::runtime_error` if `v`
  does not fit in a non-negative 31-bit value (`v > 2^31 - 1`).
- `SignedOffset ToCheckedSignedOffset(int64_t v)` — narrow to `SignedOffset`, throwing
  `std::runtime_error` if `v` is outside `int32_t` range.
- `template<class T> const T* ResolveOffset(const void* obj, Offset off)` — `obj + off` as `const T*`.
- `template<class T> const T* ResolveNullableOffset(const void* obj, Offset off, const T* def)` —
  as above, but returns `def` when `off == 0`.
- `template<class T> const T& ReadMessage(const void* buf)` — resolve the root object (see above).
- Offset wrapper templates used to type references while building:
  - `template<class T=void> struct InternalOffset { Offset O; InternalOffset(); InternalOffset(Offset);
    bool IsNull() const; };` — an offset still relative to the buffer's right cursor (used while
    building / as `AddField`/`Finish` arguments and as array element storage).
  - `template<class T=void> struct InlineOffset { Offset O; ... };` — an offset to an *inline* object
    (used for arrays of fixed messages); `InternalOffset` is convertible to `InlineOffset`.
  - Both expose `.O` and `.IsNull()`; a default-constructed / zero offset is null.

## `buffer.h` — `DualBuffer` (namespace `yaff`)

A growable dual-ended byte buffer. Required surface (used directly by tests):

- `explicit DualBuffer(size_t initialSize = 0)`; move-only.
- Left side (grows up from offset 0): `LeftAllocate`, `template<class T> void LeftPushSmall(const T&)`,
  `void LeftFill(size_t)` (zero-fills), `void LeftPop(size_t)`, `size_t LeftSize() const`,
  `std::byte* LeftData() const`, `std::byte* LeftDataAt(size_t) const`,
  `size_t LeftOffsetAt(const std::byte*) const`, `LeftClear`.
- Right side (grows down from the end): `RightAllocate`, `template<class T> void RightPushSmall(const T&)`,
  `RightFill`, `RightPop`, `size_t RightSize() const`, `std::byte* RightData() const`,
  `std::byte* RightDataAt(size_t) const`, `RightClear`.
- Reallocation must **preserve both sides' contents and their relative positions**.
- `DetachedSegment RightDetach()` / `LeftDetach()` — hand the underlying allocation to an owning
  `DetachedSegment { const std::byte* Data() const; size_t Size() const; }` and reset the buffer.
  For the right side, `Data()` points at the start of the right region and is readable forward for
  `Size()` bytes.

## Message layouts (`message.h`) and their meta-traits

Every message reader is a zero-size view (`reinterpret_cast<const Reader*>(bytes)`). All readers
share this interface (templated on the C++ field type `T`):

- `T ReadValue<T>(FieldId id, T defaultVal) const` — value of field `id`, or `defaultVal` if absent.
- `const T* ReadLayout<T>(FieldId id, const T* defaultPtr = nullptr) const` — pointer to a referenced
  sub-object (nested message / array / string), or `defaultPtr` if absent.
- `bool ReadPresence<T>(FieldId id) const` — whether field `id` is explicitly present.
- `static const Reader& Default()` — a shared all-defaults instance.

Field ids are 1-based. In the **fixed** and **flat** layouts a scalar is stored XOR-encoded against
the field default (so reading applies `XorDef` again). The **sparse** layout instead stores scalars
raw (see its section below). A referenced sub-object field stores a relative `Offset` (0 ⇒ absent).

### Schema meta-traits — exact interface (the tests supply these)

Each message type is parameterized by a schema struct `M` passed as the template argument. The
tests construct these structs and pass them in, so **your readers and serializer must consume
exactly the members below and must not require any additional member** (e.g. there is no separate
field-count member — derive counts from the array sizes). All members are `static constexpr`, field
ids are 1-based, and the arrays are `std::array` (access with `operator[]` / `.data()`, *not* as raw
pointers):

```cpp
// For FixedMessage<M>: N fields, inline record of LIMIT bytes.
struct M {
    static constexpr size_t LIMIT;                                  // inline byte size
    static constexpr std::array<yaff::FieldOffset, N + 1> FLAT_OFFSETS; // [id-1]=offset; [N]=LIMIT (sentinel)
};

// For FlatMessage<M> / DynamicMessage<M>: N fields.
struct M {
    static constexpr std::array<yaff::FieldOffset, N + 1> FLAT_OFFSETS; // [id-1]=inline offset; [N]=inline size
    static constexpr std::array<yaff::FieldId,    D>      DELETED_IDS;  // sorted; ids removed by a later schema (may be empty)
    static constexpr std::array<bool,             N>      STATIC_FLAGS; // [id-1]=true if this field's offset never shifts
};

// SparseMessage takes no meta-trait (it is self-describing on the wire).
```

Each message reader must also publish `using MetaType = M;`. Do not assume any other meta members,
types, or naming — code that references, say, an `M::FIELD_COUNT` or treats `FLAT_OFFSETS` as a
`const FieldOffset*` will fail to compile against the supplied traits.

### Fixed layout — `FixedMessage<M>`
A flat, fixed-size inline record of exactly `M::LIMIT` bytes. `M::FLAT_OFFSETS[id-1]` is the byte
offset of field `id` within the record; there is one trailing sentinel entry equal to `M::LIMIT`.
Every field always occupies its slot (implicit presence): a scalar's presence is "stored bits are
non-zero"; an embedded-message field's presence is "stored offset is non-zero". No per-message
metadata is written.

### Flat layout — `FlatMessage<M>` and `DynamicMessage<M>`
A compact record preceded by a small metadata header, sized to the highest set field. `M` provides:
`FLAT_OFFSETS` (inline byte offset per field, plus trailing sentinel = inline size),
`STATIC_FLAGS[id-1]` (`true` ⇒ the field's offset never shifts under schema evolution), and
`DELETED_IDS` (sorted ids removed by a later schema version). Behaviors to honor:

- **Presence modes:** *explicit* (default) records which fields were written, so a field set to its
  default value is still present; *implicit* drops any field whose value equals its default.
- **Sized metadata** records each field's inline width so a reader using an evolved schema can skip
  over fields it no longer knows (deleted-id **offset correction**).
- **Tail/skip optimization:** trailing default fields are not stored; the stored region only spans up
  to the highest present field.
- A reader with an **evolved** meta (`DELETED_IDS` non-empty, some `STATIC_FLAGS` false) must still
  read fields that existed in the writer's schema by applying the size-correction for deleted ids,
  and must report added (never-written) fields as absent.
- `DynamicMessage<M>` reads a buffer regardless of whether it was written *flat* or *sparse* (it
  inspects the on-wire tag and dispatches), returning defaults for fields not present.

### Sparse layout — `SparseMessage`
A self-describing record for sparse field sets: it stores only the fields actually written plus a
compact id→offset metadata table, and needs **no meta-trait to read**. Honor:

- Field ids below a small threshold (32) use a 1-byte offset slot; larger ids use a 2-byte slot.
- Scalars are stored **raw**, not XOR-encoded: with no meta-trait the reader has no per-field default
  to un-XOR, so a present scalar reads back as exactly the value written — **independent of the
  `defaultVal` passed to `ReadValue`** (that default is only returned when the field is absent).
- *implicit* construction drops a field whose written value equals its `def` (compared at
  serialization time); *explicit* keeps every written field.
- Identical metadata tables produced within one buffer are **deduplicated** (shared on the wire).

## Serializer (`serializer.h`) — `yaff::Serializer`

Builds a buffer. Move-disabled; `explicit Serializer(size_t initialSize = 0)`. Sub-objects are
serialized **innermost-first** (a nested object is finished before the field that references it is
added). Field-adding calls must occur between a `Start…`/`Finish…` pair, and **fields are added in
strictly descending id order**. Required surface:

- Fixed: `template<class M> void StartFixedMessage()`, `Offset FinishFixedMessage()`.
- Flat: `template<class M> void StartFlatMessage(bool implicit = false, bool sized = false)`,
  `Offset FinishFlatMessage()`.
- Sparse: `void StartSparseMessage(bool implicit = false)`, `Offset FinishSparseMessage()`.
- Fields:
  - `template<class T> void AddField(FieldId id, T value, T def)` — scalar (XOR-encoded against
    `def` in the fixed/flat layouts, stored raw in sparse; in implicit / sparse-implicit mode a value
    equal to `def` may be dropped).
  - `template<class T> void AddField(FieldId id, InternalOffset<T> offset)` — reference field
    (a null offset is a no-op / absent).
  - Adding `id == 0`, or adding ids out of descending order, must throw `std::runtime_error`.
- Arrays (each returns `InternalOffset<Array<…>>`; an empty input yields the **null** offset):
  - `template<class T> InternalOffset<Array<T>> SerializeArray(const std::vector<T>&)` — scalar array,
    elements stored in input order.
  - `InternalOffset<Array<bool>> SerializeArray(const std::vector<bool>&)`.
  - `template<class T> InternalOffset<Array<InternalOffset<T>>> SerializeArray(const std::vector<InternalOffset<T>>&)`
    — array of references (e.g. messages / strings), in input order.
  - `template<class T, class F> InternalOffset<Array<T>> SerializeArray(size_t len, F gen)` — generator
    `gen(i) -> T`, elements in index order.
  - `template<class E, class F> InternalOffset<Array<E>> SerializeArray(F produce)` — producer
    `produce(i) -> std::pair<E,bool>`, where the bool answers "call `produce` again?": every call
    contributes its element to the array, including the final call — the one returning `false`,
    after which `produce` is not invoked again. Used to build arrays of inline fixed
    messages where each element is serialized on demand. (Producer/deferred arrays are stored in the
    reverse of production order — see the array readers.)
- Strings: `template<class S> InternalOffset<String> SerializeString(const S&)` (anything convertible
  to `std::string_view`); an explicitly serialized empty string is still present (non-null offset).
- **Deduplication:** identical serialized arrays/strings within one buffer return the **same offset**
  (compared bytewise). Do **not** dedup reference arrays where it would break relative offsets.
- `template<class T> void Finish(InternalOffset<T> root)` — finalize with the root object; `root`
  must be non-null. `const std::byte* Data() const`, `size_t Size() const` (valid after `Finish`),
  `DetachedSegment Release()` (detach the finished buffer; the serializer can be reused afterwards).
- `Serializer` may not call `SerializeArray`/`SerializeString` while a message is open.

You must restrict layout sizes so produced buffers are minimal/canonical. `Serializer::Size()`
returns the finished buffer's byte length, but the exact byte-level encoding of the metadata
headers (flat/sparse on-wire tag, presence bitmap, sized-width table, array element-count prefix)
is an implementation detail this spec does not pin down — so no exact `Size()` value is fixed by
the contract. The size *relations* the rules above imply do hold, though: a message that leaves a
field out of the stored region must produce a strictly smaller buffer than the otherwise-identical
message that stores it.

## Arrays & strings (`array.h`)

The `Array` specializations below document only how each one *differs* from the base `Array`
surface; every member not mentioned carries over unchanged.

- `template<class T> class Array` (scalar elements): `size_type Size() const` / `size()`,
  `bool Empty()`/`empty()`, `T Get(size_type) const`, `T operator[](size_type) const`,
  `const T* Data() const`, random-access `begin()`/`end()` iterators, and (for sorted arrays)
  `find(key)`, `contains(key)`, `count(key)`, `equal_range(key)`, where `key` may be of any type
  the array's elements are comparable to. `static const Array& Default()` is an empty array. The
  element count is stored with the data so a view knows its `Size()`.
- `template<class T> class Array<InternalOffset<T>>` — element `Get(i)` resolves the stored relative
  offset and returns `const T&`; iterator is a struct iterator with `operator->`.
- `template<class T> class Array<InlineOffset<T>>` — elements are fixed-size inline objects laid out
  back-to-back (`Get(i)` resolves at `T::MetaType::LIMIT * i`).
- `class String : Array`-like: `Size()`, `Empty()`, `char Get(i)`/`operator[]`, `const char* Data()`,
  `std::string_view AsStringView()` and implicit conversion to `std::string_view`, `operator==` and
  `operator<=>` against anything convertible to `std::string_view`, range iteration, `Default()`.

## What is out of scope

Do **not** implement: the `.proto`/protoc plugin or any code generation, protobuf interop
(`ParseTo`/`ParseMessage`), reflection / visitors / `AnyMessage` / `AnyArray`, or the experimental
serializer. Only the runtime described above is required.
