# gtirb — GrammaTech Intermediate Representation for Binaries (C++ API)

Build `gtirb`, the C++ library implementing an intermediate representation for
machine-code analysis and rewriting tools. GTIRB is a language-neutral IR
loosely modeled on LLVM-IR: it lets a disassembler emit a data structure that
downstream analysis, transformation, and pretty-printing tools can read,
modify, and serialize. The IR does **not** represent instruction semantics —
it stores raw machine-code bytes plus symbolic operand information, control
flow, and side-channel analysis results.

The entire IR is round-trippable through a Google Protocol Buffers schema, so
tools written in different languages can exchange GTIRB files on disk.

## Build contract

Place your sources under `/app` (organize them however you like). Write
`/app/setup.sh` that builds and installs the library **offline** using CMake.
After running `/app/setup.sh`, a freshly written driver must build and run
with:

```
g++ -std=c++17 -DGTIRB_WRAP_UTILS_IN_NAMESPACE driver.cpp -lgtirb -lprotobuf -o driver
./driver
```

Client translation units that use `gtirb::isa`, `gtirb::cast`,
`gtirb::dyn_cast`, or `gtirb::dyn_cast_or_null` MUST be compiled with
`-DGTIRB_WRAP_UTILS_IN_NAMESPACE`. Without it, those names are only
available in the global namespace (and marked deprecated).

That requires:

1. Headers installed under `/usr/local/include/gtirb/`, e.g.
   `#include <gtirb/gtirb.hpp>` resolves the umbrella header, and
   `#include <gtirb/IR.hpp>`, `#include <gtirb/Module.hpp>`, etc. resolve
   each public header directly.
2. Generated protobuf headers installed under `/usr/local/include/gtirb/proto/`,
   so that gtirb's own headers can transitively `#include <gtirb/proto/*.pb.h>`
   without further -I flags.
3. The shared library `libgtirb.so` installed under `/usr/local/lib/` and
   picked up by `ldconfig` so the loader finds it at runtime.
4. All symbolic dependencies (libprotobuf's runtime, boost's compiled bits
   where used) already available system-wide — no manual `-L` needed.

The build must succeed offline; there is no network at evaluation time.

## Namespace and includes

All public symbols live in `namespace gtirb`. Tests will write
`using namespace gtirb;` and access every class listed below by its bare name.

The umbrella header `<gtirb/gtirb.hpp>` transitively includes every public
API header (`Addr`, `AuxData`, `AuxDataContainer`, `AuxDataSchema`,
`ByteInterval`, `Casting`, `CFG`, `CfgNode`, `CodeBlock`, `Context`,
`DataBlock`, `DecodeMode`, `ErrorOr`, `IR`, `Module`, `Node`, `Offset`,
`ProxyBlock`, `Section`, `Symbol`, `SymbolicExpression`, `Utility`). Tests
may rely on this single-include contract.

Standard AuxData schemas live in `namespace gtirb::schema` and are declared
in `<gtirb/AuxDataSchema.hpp>`.

The generated protobuf messages live in `namespace gtirb::proto` (from
`<gtirb/proto/*.pb.h>`); the tests do NOT construct these directly, they go
through `IR::save` / `IR::load` (see Serialization below).

---

# Public API

## Addresses — `<gtirb/Addr.hpp>`

`Addr` is a strong-typed wrapper around a `uint64_t` effective address. It
supports full unsigned integer arithmetic (`+`, `-`, `++`, `--`, compound
assignment) and all comparison operators, plus a `std::hash` specialization.
Bare integers do NOT implicitly convert to `Addr`; construction is explicit.

```cpp
class Addr {
public:
    using value_type = uint64_t;
    using difference_type = int64_t;

    constexpr Addr() noexcept;                          // zero
    constexpr explicit Addr(value_type X) noexcept;
    constexpr explicit operator value_type() const noexcept;

    // Arithmetic
    friend constexpr Addr operator+(const Addr&, value_type) noexcept;
    friend constexpr Addr operator+(value_type, const Addr&) noexcept;
    friend constexpr Addr operator-(const Addr&, value_type) noexcept;
    friend constexpr difference_type operator-(const Addr&, const Addr&) noexcept;
};

// Hex-formatted stream output: prints "0x1234"-style.
std::ostream& operator<<(std::ostream&, Addr);
std::ostream& operator<<(std::ostream&, std::optional<Addr>);  // "<none>" for empty
```

`AddrRange` is `[lower, upper)` (half-open):

```cpp
class AddrRange {
public:
    constexpr explicit AddrRange(Addr Lower, Addr Upper) noexcept; // clamps if Upper < Lower
    constexpr explicit AddrRange(Addr Lower, uint64_t Count) noexcept;
    constexpr Addr lower() const noexcept;   // inclusive
    constexpr Addr upper() const noexcept;   // exclusive
    constexpr uint64_t size() const noexcept;
    bool operator==(const AddrRange&) const noexcept;
    bool operator!=(const AddrRange&) const noexcept;
};

// Free-function utilities that use getAddress() / getSize() duck typing:
template <typename T> std::optional<AddrRange> addressRange(const T& Object);
template <typename T> std::optional<Addr>      addressLimit(const T& Object);
template <typename T> bool                     containsAddr(const T& Object, Addr Ea);
```

## Nodes, casting, context — `<gtirb/Node.hpp>`, `<gtirb/Casting.hpp>`, `<gtirb/Context.hpp>`

Every first-class IR element is a `Node`. Each `Node` carries a Boost-UUID
identifier and is owned by a `Context` (an arena that allocates every
IR-owned object and releases them together when the `Context` is destroyed).
Nodes are not copyable or moveable; they are always accessed via pointer.

```cpp
using UUID = boost::uuids::uuid;

class Context {
public:
    Context();                                  // default-construct a fresh arena
    Node* findNode(const UUID& Uuid);           // O(1) UUID lookup, nullptr if absent
    const Node* findNode(const UUID& Uuid) const;
    // Node::Create / Symbol::Create / etc. all take a Context& and register
    // the new node into the arena. Never call `new` on a Node subclass
    // directly; always use Create.
};

class Node {
public:
    static Node* Create(Context& C);
    static Node* getByUUID(Context& C, const UUID& Uuid);
    static const Node* getByUUID(const Context& C, const UUID& Uuid);
    const UUID& getUUID() const;

    // Node is not copyable or moveable.
};
```

LLVM-style RTTI is provided by `<gtirb/Casting.hpp>`:

```cpp
template <typename To, typename From> bool isa(const From* Val);
template <typename To, typename From> To* cast(From* Val);              // asserts non-null match
template <typename To, typename From> To* cast_or_null(From* Val);      // allows null
template <typename To, typename From> To* dyn_cast(From* Val);          // returns null on mismatch
template <typename To, typename From> To* dyn_cast_or_null(From* Val);  // null-safe dyn_cast
```

The Node type hierarchy (which drives `isa`/`dyn_cast`):

```
Node
├── CfgNode
│   ├── CodeBlock
│   └── ProxyBlock
├── DataBlock
├── IR                     (also AuxDataContainer)
├── Module                 (also AuxDataContainer)
├── Section
├── Symbol
└── ByteInterval
```

## IR — `<gtirb/IR.hpp>`

`IR` is the root container. An `IR` owns zero or more `Module`s and a single
inter-procedural control-flow graph (`CFG`) shared across all modules.

```cpp
class IR : public AuxDataContainer {
public:
    static IR* Create(Context& C);

    // Modules — iteration is in module-name order.
    Module* addModule(Module* M);         // takes ownership; returns the same pointer
    bool removeModule(Module* M);         // returns whether M was in this IR

    // Range-based access. The exact iterator/range types are library-chosen,
    // but every range's iterator must satisfy at least LegacyInputIterator
    // (expose the standard iterator_traits typedefs: difference_type,
    // value_type, iterator_category, pointer, reference) so std::distance
    // and other STL algorithms work.
    auto modules();          // yields Module& in name order
    auto modules() const;    // yields const Module&

    // Module lookup by name (multiple modules may share a name).
    auto findModules(const std::string& Name);              // yields Module&
    auto findModules(const std::string& Name) const;        // yields const Module&

    // Aggregated iteration across every child module — these accessors
    // concatenate the same-named accessors on each Module in modules()
    // order. Useful for whole-IR walks without a nested loop.
    auto symbols();          auto symbols() const;         // yields Symbol&
    auto proxy_blocks();     auto proxy_blocks() const;    // yields ProxyBlock&
    auto code_blocks();      auto code_blocks() const;     // yields CodeBlock&
    auto data_blocks();      auto data_blocks() const;     // yields DataBlock&

    // CFG — shared across all modules.
    CFG& getCFG();
    const CFG& getCFG() const;

    // Serialization — see the Serialization section below.
    void save(std::ostream& Out) const;
    static ErrorOr<IR*> load(Context& C, std::istream& In);

    // Protobuf schema-version stamp; defaults to library's built-in constant.
    uint32_t getVersion() const;
    void setVersion(uint32_t V);
};
```

Example:

```cpp
Context ctx;
IR* ir = IR::Create(ctx);
Module* m = ir->addModule(Module::Create(ctx, "hello"));
for (auto& mod : ir->modules()) { /* ... */ }
```

## ChangeStatus — shared enum

Several mutation operations (add/remove Section, add/remove ByteInterval,
add/remove Block, add/remove ProxyBlock, and their observer callbacks)
return a `ChangeStatus` result indicating whether the change took effect.

```cpp
enum class ChangeStatus {
    Rejected,   // an observer refused the change; state is unchanged
    Accepted,   // the change was applied
    NoChange    // the operation was a no-op (e.g. reparenting to same parent)
};
```

Callers may treat `Accepted` as success and `Rejected` / `NoChange` as
"no side effect" for the specific semantics of that call.

## Module — `<gtirb/Module.hpp>`

A `Module` represents a single loadable object (executable, library, object
file). Modules own sections, symbols, and proxy blocks, and hold binary-format
metadata (file format, ISA, byte order, entry point, preferred address,
rebase delta).

```cpp
enum class FileFormat : uint8_t {
    Undefined, COFF, ELF, PE, IdaProDb32, IdaProDb64, XCOFF, MACHO, RAW
};

enum class ISA : uint8_t {
    Undefined, IA32, PPC32, X64, ARM, ValidButUnsupported,
    PPC64, ARM64, MIPS32, MIPS64, RISCV32, RISCV64
};

enum class ByteOrder : uint8_t {
    Undefined, Big, Little
};

class Module : public AuxDataContainer {
public:
    // Construct with a name; other metadata set via setters.
    static Module* Create(Context& C, const std::string& Name);

    // Metadata.
    const std::string& getName() const;   void setName(const std::string&);
    const std::string& getBinaryPath() const;  void setBinaryPath(const std::string&);
    FileFormat  getFileFormat() const;    void setFileFormat(FileFormat);
    ISA         getISA()        const;    void setISA(ISA);
    ByteOrder   getByteOrder()  const;    void setByteOrder(ByteOrder);
    Addr        getPreferredAddr() const; void setPreferredAddr(Addr);
    int64_t     getRebaseDelta()   const; void setRebaseDelta(int64_t);
    CodeBlock*       getEntryPoint();
    const CodeBlock* getEntryPoint() const;       // nullptr if no entry set
    void             setEntryPoint(CodeBlock* B);
    IR* getIR();  const IR* getIR() const;        // parent (or nullptr if not attached)

    // Sections (child nodes). The primary form creates + parents a new
    // Section in one call and returns the pointer; the reparent form
    // takes an existing Section and returns a ChangeStatus.
    template <typename... Args>
    Section* addSection(Context& C, Args&&... A);          // create + attach
    ChangeStatus addSection(Section* S);                   // reparent existing
    ChangeStatus removeSection(Section* S);
    auto     sections();       // yields Section&; ordered by address then by name
    auto     sections() const;                     // yields const Section&
    // Aggregated byte-interval lookup across all sections. Same
    // half-open-interval semantics as Section::findByteIntervalsOn:
    // an interval at [Addr, Addr+Size) matches X iff X is at least
    // Addr and strictly less than Addr+Size.
    auto     findByteIntervalsOn(Addr X);              // yields ByteInterval&
    auto     findByteIntervalsOn(Addr X) const;        // yields const ByteInterval&

    // Block lookup by address. Two families:
    //   *On(A):  blocks whose address range covers A (half-open semantics —
    //            block spanning [addr, addr+size) matches A iff A is at least
    //            addr and strictly less than addr+size).
    //   *At(A):  blocks whose START address equals A exactly.
    // The unqualified `findBlocks*` families return both CodeBlock and
    // DataBlock as Node&; the typed families filter to one concrete kind.
    auto     findBlocksOn(Addr A);            auto findBlocksOn(Addr A) const;         // yields Node&
    auto     findBlocksAt(Addr A);            auto findBlocksAt(Addr A) const;         // yields Node&
    auto     findCodeBlocksOn(Addr A);        auto findCodeBlocksOn(Addr A) const;     // yields CodeBlock&
    auto     findCodeBlocksAt(Addr A);        auto findCodeBlocksAt(Addr A) const;     // yields CodeBlock&
    auto     findDataBlocksOn(Addr A);        auto findDataBlocksOn(Addr A) const;     // yields DataBlock&
    auto     findDataBlocksAt(Addr A);        auto findDataBlocksAt(Addr A) const;     // yields DataBlock&

    // Symbols (child nodes). Symbols use a Symbol*-returning add.
    Symbol* addSymbol(Symbol* S);
    bool    removeSymbol(Symbol* S);
    auto    symbols();                             // yields Symbol&
    auto    symbols() const;                       // yields const Symbol&
    // Symbol lookup by name and by address (both may return multiple results).
    auto    findSymbols(const std::string& Name);        // yields Symbol&
    auto    findSymbols(const std::string& Name) const;  // yields const Symbol&
    auto    findSymbols(Addr X);                         // yields Symbol&
    auto    findSymbols(Addr X) const;                   // yields const Symbol&
    // Symbols whose referent is a specific Node (CodeBlock/DataBlock/ProxyBlock).
    auto    findSymbols(const Node& Referent);           // yields Symbol&
    auto    findSymbols(const Node& Referent) const;     // yields const Symbol&

    // Proxy blocks (child nodes) — see ProxyBlock below. Same two-form
    // pattern as sections.
    template <typename... Args>
    ProxyBlock* addProxyBlock(Context& C, Args&&... A);    // create + attach
    ChangeStatus addProxyBlock(ProxyBlock* PB);            // reparent existing
    ChangeStatus removeProxyBlock(ProxyBlock* PB);
    auto        proxy_blocks();                   // yields ProxyBlock&
    auto        proxy_blocks() const;             // yields const ProxyBlock&
};
```

## Section — `<gtirb/Section.hpp>`

A `Section` is a named region within a `Module`, characterized by a set of
flags and containing zero or more `ByteInterval`s.

```cpp
enum class SectionFlag : uint8_t {
    Undefined, Readable, Writable, Executable, Loaded, Initialized,
    ThreadLocal
};

class Section : public Node {
public:
    static Section* Create(Context& C, const std::string& Name);

    const std::string& getName() const;   void setName(const std::string&);
    Module* getModule();  const Module* getModule() const;

    // Section flags — add / remove / query.
    void addFlag(SectionFlag F);
    void removeFlag(SectionFlag F);
    bool isFlagSet(SectionFlag F) const;
    auto flags();                    // yields SectionFlag (or wrapper)
    auto flags() const;

    // Address / size aggregated across the section's byte intervals. Both
    // return std::nullopt if the section has no byte intervals, or if any
    // interval lacks a fixed address / size. Aggregation semantics:
    // `getAddress()` is the min lower bound across intervals; `getSize()`
    // is the ADDRESS EXTENT (max upper bound − min lower bound), NOT the
    // sum of interval sizes. Gaps between intervals count toward getSize().
    std::optional<Addr>     getAddress() const;
    std::optional<uint64_t> getSize()    const;

    // ByteInterval children. Same two-form pattern as Module::addSection —
    // the primary Context-taking form creates + attaches and returns
    // ByteInterval*; the reparent form takes an existing pointer and
    // returns ChangeStatus.
    template <typename... Args>
    ByteInterval* addByteInterval(Context& C, Args&&... A);   // forwards to ByteInterval::Create(C, args...) then attaches
    ChangeStatus  addByteInterval(ByteInterval* BI);          // reparent existing
    ChangeStatus  removeByteInterval(ByteInterval* BI);
    auto          byte_intervals();               // yields ByteInterval&
    auto          byte_intervals() const;         // yields const ByteInterval&
    // Address query — intervals whose byte range covers X. Half-open
    // interval semantics: an interval at [Addr, Addr+Size) matches X iff
    // X is at least Addr and strictly less than Addr+Size (start is
    // inclusive, end is exclusive).
    auto          findByteIntervalsOn(Addr X);         // yields ByteInterval&
    auto          findByteIntervalsOn(Addr X) const;   // yields const ByteInterval&

    // Aggregated block iteration across the section's byte intervals.
    auto code_blocks();       auto code_blocks() const;   // yield CodeBlock& / const CodeBlock&
    auto data_blocks();       auto data_blocks() const;   // yield DataBlock& / const DataBlock&
};
```

## ByteInterval — `<gtirb/ByteInterval.hpp>`

A `ByteInterval` is a contiguous, addressable region of raw bytes containing
zero or more `CodeBlock` / `DataBlock` children at offsets within the
interval. The bytes and the child blocks are the two payloads.

```cpp
class ByteInterval : public Node {
public:
    // Construct empty (no address, zero size), or with an initial byte range
    // via an iterator pair, or with a fixed address, or all of the above.
    static ByteInterval* Create(Context& C,
                                std::optional<Addr> Address = std::nullopt,
                                uint64_t Size = 0,
                                uint64_t InitSize = 0);
    // Iterator-pair form: when Size / InitSize are not provided, both
    // default to `std::distance(Begin, End)` — the interval's byte count
    // matches the number of input bytes and every byte is considered
    // initialized. Passing an explicit Size larger than the input range
    // leaves the trailing bytes uninitialized.
    template <typename InputIt>
    static ByteInterval* Create(Context& C,
                                std::optional<Addr> Address,
                                InputIt Begin, InputIt End,
                                std::optional<uint64_t> Size = std::nullopt,
                                std::optional<uint64_t> InitSize = std::nullopt);

    Section* getSection();  const Section* getSection() const;

    // Fixed-address handling.
    std::optional<Addr> getAddress() const;
    void                setAddress(std::optional<Addr> A);

    // Byte / initialized-byte counts.
    uint64_t getSize() const;       void setSize(uint64_t);
    uint64_t getInitializedSize() const;   void setInitializedSize(uint64_t);

    // Storage invariant: the internal byte-storage always covers positions
    // [0, Size). Positions in [InitSize, Size) read back as zero. setSize()
    // grows/shrinks the storage; getInitializedSize() is a separate counter
    // that may be less than Size but never exceeds it.

    // Byte contents. bytes_begin<T>() / bytes_end<T>() yield random-access
    // iterators over the raw bytes reinterpreted as T (e.g. uint8_t,
    // uint16_t, uint32_t). Endianness of multi-byte T follows the
    // containing Module's ByteOrder (little-endian by default); explicit
    // endian overloads take a boost::endian::order argument.
    template <typename T> auto bytes_begin();
    template <typename T> auto bytes_end();
    template <typename T> auto bytes_begin(boost::endian::order Order);
    template <typename T> auto bytes_end(boost::endian::order Order);

    // Inserting bytes. insertBytes takes an ITERATOR position (typed on
    // T); callers position with `bytes_begin<uint8_t>() + offset` for a
    // byte-offset insert. Byte insertion grows the byte vector; it does
    // NOT auto-update child block offsets or symbolic-expression offsets.
    template <typename T, typename InputIt>
    auto insertBytes(auto Pos, InputIt Begin, InputIt End);   // Pos is a bytes_iterator<T>

    // Erasing bytes. eraseBytes takes a [Begin, End) iterator pair
    // (typed on T) into the byte vector, removes those bytes, and
    // decrements the interval's Size by (End - Begin) counted in T
    // elements. Byte erasure does NOT auto-update child block offsets
    // or symbolic-expression offsets.
    template <typename T>
    auto eraseBytes(auto Begin, auto End);            // Begin/End are const_bytes_iterator<T>

    // Block children (CodeBlock or DataBlock) at an offset in the interval.
    // Primary form: create + attach in one call, returning the new block.
    // Reparent form: take an existing block and its offset, returns
    // ChangeStatus.
    template <typename BlockType, typename... Args>
    BlockType* addBlock(Context& C, uint64_t Offset, Args&&... A);   // create + attach
    ChangeStatus addBlock(uint64_t Offset, CodeBlock* B);            // reparent existing
    ChangeStatus addBlock(uint64_t Offset, DataBlock* B);            // reparent existing
    ChangeStatus removeBlock(CodeBlock* B);
    ChangeStatus removeBlock(DataBlock* B);
    auto    blocks();       auto blocks() const;      // yield Node& (both CodeBlock and DataBlock)
    auto    code_blocks();  auto code_blocks() const;  // yield CodeBlock& / const CodeBlock&
    auto    data_blocks();  auto data_blocks() const;  // yield DataBlock& / const DataBlock&

    // Symbolic expressions at specific offsets. See SymbolicExpression below.
    void addSymbolicExpression(uint64_t Offset, const SymbolicExpression& SE);
    void removeSymbolicExpression(uint64_t Offset);
    SymbolicExpression* getSymbolicExpression(uint64_t Offset);
    const SymbolicExpression* getSymbolicExpression(uint64_t Offset) const;
    auto symbolic_expressions();          auto symbolic_expressions() const;
};
```

## Blocks — `<gtirb/CodeBlock.hpp>`, `<gtirb/DataBlock.hpp>`, `<gtirb/ProxyBlock.hpp>`, `<gtirb/CfgNode.hpp>`, `<gtirb/DecodeMode.hpp>`

Three concrete block types live in the IR. `CodeBlock` and `ProxyBlock` are
CFG nodes (subclasses of `CfgNode`); `DataBlock` is not.

```cpp
enum class DecodeMode : uint8_t {
    Default,
    // Architecture-specific decoding modes exist for the ISAs GTIRB
    // supports (e.g. ARM Thumb, RISC-V compressed). Enumerator names
    // are architecture-conventional.
};

class CfgNode : public Node { /* abstract base for CodeBlock and ProxyBlock */ };

class CodeBlock : public CfgNode {
public:
    static CodeBlock* Create(Context& C, uint64_t Size = 0,
                             DecodeMode DM = DecodeMode::Default);

    ByteInterval* getByteInterval();    const ByteInterval* getByteInterval() const;

    uint64_t getSize() const;   void setSize(uint64_t);
    DecodeMode getDecodeMode() const;   void setDecodeMode(DecodeMode);

    // Address may be nullopt if the parent ByteInterval has no fixed
    // address. The offset within the parent ByteInterval is always a
    // definite uint64_t (a block always has a defined position in its
    // interval, whether or not the interval itself has a fixed address).
    std::optional<Addr> getAddress() const;
    uint64_t            getOffset()  const;

    // View of the bytes making up this block, as a random-access range.
    template <typename T> auto bytes();
    template <typename T> auto bytes() const;
};

class DataBlock : public Node {
public:
    static DataBlock* Create(Context& C, uint64_t Size = 0);

    ByteInterval* getByteInterval();  const ByteInterval* getByteInterval() const;

    uint64_t getSize() const;   void setSize(uint64_t);
    std::optional<Addr> getAddress() const;
    uint64_t            getOffset()  const;

    template <typename T> auto bytes();
    template <typename T> auto bytes() const;
};

class ProxyBlock : public CfgNode {
public:
    // A ProxyBlock is a stand-in for a code block that exists outside this
    // module — typically an external symbol's entry point. It carries no
    // address of its own; its purpose is to serve as a target for CFG edges.
    static ProxyBlock* Create(Context& C);

    Module* getModule();  const Module* getModule() const;
};
```

## Symbol — `<gtirb/Symbol.hpp>`

A `Symbol` maps a name to either an address or a Node referent. Referents may
be `CodeBlock`, `DataBlock`, or `ProxyBlock`.

```cpp
class Symbol : public Node {
public:
    using supported_referent_types = /* TypeList<CodeBlock, DataBlock, ProxyBlock> */;

    // Four Create overloads.
    static Symbol* Create(Context& C);                                          // empty
    static Symbol* Create(Context& C, const std::string& Name,
                          bool AtEnd = false);                                  // just a name
    static Symbol* Create(Context& C, Addr X, const std::string& Name,
                          bool AtEnd = false);                                  // address
    template <typename NodeTy>
    static Symbol* Create(Context& C, NodeTy* Referent, const std::string& Name,
                          bool AtEnd = false);                                  // referent

    Module* getModule();  const Module* getModule() const;
    const std::string& getName() const;
    void setName(const std::string& N);

    // Address / referent access.
    std::optional<Addr> getAddress() const;
    bool                hasReferent() const;
    template <typename NodeTy> NodeTy* getReferent();
    template <typename NodeTy> const NodeTy* getReferent() const;

    // Referent-type dispatch: calls Visitor with the referent typed as the
    // concrete supported type (CodeBlock*, DataBlock*, or ProxyBlock*). Only
    // one overload fires; if the referent is Addr or empty, no overload is
    // invoked. Return type is a std::optional<common return type of Visitor's
    // overloads>, or void if every overload returns void.
    template <typename Callable> auto visit(Callable&& Visitor) const;
};
```

## SymbolicExpression — `<gtirb/SymbolicExpression.hpp>`

Symbolic operand information attached to a `ByteInterval` at an offset. Two
variants:

- **`SymAddrConst`** — a base symbol plus a constant offset. Represents
  `Symbol + offset`.
- **`SymAddrAddr`** — two symbols, scale, and offset. Represents
  `(Symbol1 - Symbol2) * scale + offset`.

```cpp
struct SymAddrConst {
    int64_t Offset;
    Symbol* Sym;

    bool operator==(const SymAddrConst&) const;
    bool operator!=(const SymAddrConst&) const;
};

struct SymAddrAddr {
    int64_t Scale;
    int64_t Offset;
    Symbol* Sym1;
    Symbol* Sym2;

    bool operator==(const SymAddrAddr&) const;
    bool operator!=(const SymAddrAddr&) const;
};

using SymbolicExpression = std::variant<SymAddrConst, SymAddrAddr>;
```

`ByteInterval::addSymbolicExpression(offset, expr)` attaches an expression at
the given offset; `getSymbolicExpression(offset)` retrieves it (returning
`nullptr` when absent).

## Control-flow graph — `<gtirb/CFG.hpp>`

The CFG lives on an `IR` (`ir->getCFG()`) and is a directed graph whose
vertices are `CfgNode*` (either `CodeBlock*` or `ProxyBlock*`) and whose edges
are labelled with edge metadata.

```cpp
enum class ConditionalEdge : bool {
    OnFalse,   // unconditional or fires when condition is false
    OnTrue
};
enum class DirectEdge : bool {
    IsIndirect,
    IsDirect
};
enum class EdgeType {
    Branch, Call, Fallthrough, Return, Syscall, Sysret
};

// Optional so an unlabeled edge is representable.
using EdgeLabel = std::optional<std::tuple<ConditionalEdge, DirectEdge, EdgeType>>;

class CFG;   // opaque graph type — tests use the free functions below;
             // implementation is the agent's choice as long as the
             // traversal contracts hold.

// Vertex membership. addVertex returns (opaque-vertex-handle, added-now?);
// getVertex returns std::nullopt if the node is not in the graph.
auto addVertex(CfgNode* N, CFG& G);                     // -> pair<vertex-handle, bool>
auto getVertex(const CfgNode* N, const CFG& G);         // -> optional<vertex-handle>

// Edge management. addEdge returns an opaque optional edge handle. Edge
// labels are attached to the returned handle by bracket assignment:
// `G[handle] = label;`. Endpoints should already have been added to the
// graph with addVertex; the exact behavior if not is
// implementation-defined and callers should not rely on it.
auto addEdge(const CfgNode* From, const CfgNode* To, CFG& G);   // -> optional<edge-handle>
bool removeEdge(const CfgNode* From, const CfgNode* To, CFG& G);              // remove all edges From->To
bool removeEdge(const CfgNode* From, const CfgNode* To,
                EdgeLabel Label, CFG& G);                                     // remove only edges with this label

// Iteration.
auto nodes(CFG& G);           auto nodes(const CFG& G);       // yields CfgNode& (any kind)
auto blocks(CFG& G);          auto blocks(const CFG& G);      // yields CodeBlock& only

// Predecessor / successor iteration for a given node. Each element is a
// std::pair<CfgNode*, EdgeLabel>.
auto cfgPredecessors(CFG& G, const CfgNode* N);
auto cfgPredecessors(const CFG& G, const CfgNode* N);
auto cfgSuccessors  (CFG& G, const CfgNode* N);
auto cfgSuccessors  (const CFG& G, const CfgNode* N);
```

Assigning `G[handle] = label` (bracket-indexed by the handle returned from
`addEdge`) attaches the label to that specific edge. Specifically,
`G[handle]` yields an lvalue reference to the edge's `EdgeLabel` (i.e.
`std::optional<std::tuple<ConditionalEdge, DirectEdge, EdgeType>>&`) —
directly assignable from a bare `std::tuple<...>` via `std::optional`'s
converting assignment. Both `cfgPredecessors` and `cfgSuccessors` must
iterate the labeled neighbors of a node, so the implementation must
support both in-edge and out-edge traversal.

Self-loops (an edge whose source and target are the same node) are
supported: `addEdge(N, N, G)` returns a valid handle, and the
resulting edge appears in both `cfgPredecessors(G, N)` and
`cfgSuccessors(G, N)` (a single self-loop contributes one entry to
each — not two — for that node).

Example — attach a label to a newly-added edge:

```cpp
auto handle = addEdge(from, to, cfg);
if (handle) {
    cfg[*handle] = std::make_tuple(ConditionalEdge::OnFalse,
                                    DirectEdge::IsDirect,
                                    EdgeType::Branch);
}
```

## Auxiliary data — `<gtirb/AuxData.hpp>`, `<gtirb/AuxDataContainer.hpp>`, `<gtirb/AuxDataSchema.hpp>`

`AuxData` lets clients attach arbitrary side-channel analysis results to an
`IR` or a `Module` (both are `AuxDataContainer`s). The wire format serializes
any of these payload types portably:

- All integral types, plus `Addr`, `Offset`, and `UUID`.
- Sequential containers (`std::vector`, `std::list`, `std::deque`).
- Mapping containers (`std::map`, `std::unordered_map` — no multimaps).
- `std::set`, `std::unordered_set` (no multisets).
- `std::tuple`.
- `std::variant` — each alternative type must itself be a supported
  payload type and default-constructible. The wire format records the
  active alternative index alongside the payload.
- `std::string`.
- Nesting of any of the above.

Support for a specific payload is declared with a **schema struct** — a named
compile-time descriptor:

```cpp
namespace gtirb::schema {
    struct FunctionEntries {
        static constexpr const char* Name = "functionEntries";
        typedef std::map<gtirb::UUID, std::set<gtirb::UUID>> Type;
    };
    // ... (see AuxDataSchema.hpp for the sanctioned schemas)
}
```

The AuxData API:

```cpp
class AuxDataContainer : public Node {
public:
    // Register a schema so this container will accept payloads of that type.
    // Static — registers globally. Must be called before addAuxData / getAuxData.
    template <typename Schema> static void registerAuxDataType();

    // Attach / read / remove a payload keyed by schema. getAuxData
    // returns nullptr if no payload is attached under Schema.
    template <typename Schema> void addAuxData(typename Schema::Type&& X);
    template <typename Schema> typename Schema::Type* getAuxData();
    template <typename Schema> const typename Schema::Type* getAuxData() const;
    template <typename Schema> bool removeAuxData();
};
```

Four sanctioned schemas in `namespace gtirb::schema` cover the payload
shapes tests will use (each schema fixes its payload type and its on-disk
name; both `IR` and `Module` are `AuxDataContainer`s and accept any
registered schema):

| Schema | Payload type | Purpose |
|---|---|---|
| `FunctionNames` | `std::map<gtirb::UUID, gtirb::UUID>`      | function UUID → name-symbol UUID |
| `Alignment`     | `std::map<gtirb::UUID, uint64_t>`         | node UUID → required alignment in bytes |
| `Comments`      | `std::map<gtirb::Offset, std::string>`    | offset → comment text |
| `Padding`       | `std::map<gtirb::Offset, uint64_t>`       | offset → padding size in bytes |

Each schema struct declares two members: `static constexpr const char* Name`
(the on-disk name — e.g. `"functionNames"`, `"alignment"`, `"comments"`,
`"padding"`) and a `typedef ... Type` alias for the payload type. The
schema struct itself is the compile-time key passed as the template
argument to `registerAuxDataType`, `addAuxData`, `getAuxData`, and
`removeAuxData`.

Example:

```cpp
AuxDataContainer::registerAuxDataType<schema::FunctionNames>();
Module* m = /* ... */;
std::map<UUID, UUID> data = /* ... */;
m->addAuxData<schema::FunctionNames>(std::move(data));
auto* out = m->getAuxData<schema::FunctionNames>();
```

## Offset — `<gtirb/Offset.hpp>`

`Offset` names a location inside a specific `Node` by that node's UUID plus a
byte displacement. Used as a key for `Comments` / `Padding` AuxData.

```cpp
struct Offset {
    UUID     ElementId;
    uint64_t Displacement;

    Offset() = default;
    Offset(const UUID& U, uint64_t D);
    bool operator==(const Offset&) const;
    bool operator!=(const Offset&) const;
    bool operator<(const Offset&)  const;   // lex order (ElementId, Displacement)
};
```

## Serialization — protobuf round-trip

The IR is round-trippable through Google Protocol Buffers. The agent must
provide the `.proto` schema files (matching gtirb's on-disk format) and the
build must run `protoc` to generate the C++ bindings that gtirb's own headers
`#include`. See `<gtirb/IR.hpp>`:

```cpp
class IR : public AuxDataContainer {
public:
    // Serialize / deserialize via std streams.
    void save(std::ostream& Out) const;                         // 8-byte "GTIRB" magic + version + protobuf payload
    static ErrorOr<IR*> load(Context& C, std::istream& In);     // error return via ErrorOr

    // Protobuf schema-version stamp; defaults to library's built-in constant.
    uint32_t getVersion() const;
    void setVersion(uint32_t V);
};

// <gtirb/ErrorOr.hpp>
template <class T> class ErrorOr {
public:
    // ErrorOr<T> holds either a valid T or a std::error_code. Convertible
    // to bool (true = has value); operator*() returns the value.
    operator bool() const;
    T& operator*();
    const T& operator*() const;
    std::error_code getError() const;
};
```

The saved format is: 8-byte magic signature (`"GTIRB"` + version bytes),
followed by the protobuf-serialized `proto::IR` message. Loading verifies the
magic bytes, checks a compatible version, and reconstructs the entire IR
(all Modules, Sections, ByteIntervals, Blocks, Symbols, SymbolicExpressions,
CFG, and any registered AuxData) into the supplied `Context`.

Loading an IR requires that every AuxData schema present in the file be
registered on the destination side before `load` runs; otherwise the schema
is silently skipped (the resulting IR is still valid, just missing those
tables).

The schema-version field carried inside the protobuf payload defaults to
the library's built-in schema constant. `IR::save` writes and `IR::load`
verifies this default; a serialized file with a non-default value fails
`IR::load` with an incompatible-version error. Round-tripping preserves
the version stamp: `getVersion()` on a loaded IR returns the same value
as on the source IR.

## Behavior notes

- **UUIDs are stable across save/load.** After `IR::save` / `IR::load`, every
  Node keeps the same UUID it had originally, so cross-references (e.g.
  `Symbol` referent, `Offset::ElementId`, AuxData UUIDs) remain valid.

- **Ownership discipline.** Every Node lives in its parent `Context`. Adding
  a Node to a container (`ir->addModule(m)`, `m->addSection(s)`, etc.)
  transfers parenting: the child's `getModule()` / `getSection()` / etc.
  starts returning the new parent, and the container gains ownership for
  iteration/removal purposes. The `Context` still ultimately owns every Node
  for lifetime.

- **CodeBlock/DataBlock addresses are derived.** A block's `getAddress()`
  returns its `ByteInterval`'s address plus its `getOffset()`; if the interval
  has no fixed address, the block's address is `std::nullopt`.

- **Symbol addresses resolve through the referent.** `Symbol::getAddress()`
  returns, for an address-constructed symbol, that address; for a symbol whose
  referent is a `CodeBlock` or `DataBlock`, the referent's derived address; and
  for a `ProxyBlock`-referent or an empty (no address, no referent) symbol,
  `std::nullopt`. Because a referent symbol's address tracks its referent,
  `Module::findSymbols(Addr X)` matches by this resolved address — it finds both
  address-constructed symbols at `X` and referent symbols whose referent's
  derived address is `X`.

- **Symbol lookups return ranges.** `Module::findSymbols(name)` /
  `findSymbols(addr)` / `findSymbols(referent)` may return multiple matches
  (name collision, address alias, or multiple symbols pointing at the same
  Node). Tests iterate the returned range.

- **CFG edges may exist between blocks in different modules.** The CFG is
  stored on `IR`, not on `Module`, so a call from one module to an external
  function (represented by a `ProxyBlock` in the callee module) is a normal
  edge in the shared CFG.

- **Section flag semantics.** `Section` stores an unordered set of
  `SectionFlag` values; adding the same flag twice is a no-op.

- **Endian handling.** `ByteInterval::bytes_begin<T>()` /
  `bytes_end<T>()` (and the deprecated `bytes<T>()` alias) reinterpret
  the raw byte buffer as a sequence of `T`. When `T` is multi-byte,
  byte order follows the containing `Module::getByteOrder()` (defaulting
  to little-endian if the module is unset or has `ByteOrder::Undefined`).
  The byte order is queried from the Module at every iterator
  dereference — calling `Module::setByteOrder()` after ByteInterval
  creation must be reflected in subsequent iteration, without
  invalidating existing iterators or requiring re-instantiation.

- **`std::optional<Addr>` printing.** The stream inserter for
  `std::optional<Addr>` prints the hex-formatted address if present, or
  the literal string `<none>` if empty.

- **`AuxData` registration is per-process, not per-container.**
  `registerAuxDataType<Schema>()` is a static call — it affects every
  `AuxDataContainer` in the process. Registration is idempotent.
