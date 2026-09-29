# quadrable

Build `quadrable`, a header-only C++17 library that implements an **authenticated,
persistent, versioned key/value store** backed by LMDB (a memory-mapped B-tree
database). Every version of the tree has a 32-byte cryptographic root hash that
uniquely identifies its full contents; a snapshot of that root plus a compact
merkle **proof** is enough for a caller who has never seen the underlying store to
verify presence or absence of individual keys. Concurrent named heads (`master`,
`feature-x`, ...) can share storage while maintaining independent roots, and an
incremental sync protocol lets two parties bring one tree into agreement with
another by exchanging proof fragments over any byte-stream transport.

Domain glossary:

- **Merkle tree** — a tree whose every interior node's hash is a function of its
  children's hashes. A proof for a leaf is the sibling hashes along the path from
  that leaf to the root; anyone with the root hash can verify the proof
  independently.
- **LMDB** — the [Lightning Memory-Mapped Database](http://www.lmdb.tech/), a
  compact embedded B-tree store used as the on-disk backend. Applications talk to
  it via a C API (`liblmdb`) and, in this project, a thin C++ RAII wrapper header
  `lmdb++.h` that lives under the include directory `lmdbxx/`.
- **BLAKE2s** — the 256-bit variant of the [BLAKE2](https://www.blake2.net/) hash
  family, exposed as `blake2s_init`/`update`/`final` in the system C library
  `libb2` (`-lb2`, header `<blake2.h>`). It is the hash function used at every
  interior and leaf node.

## Dependencies

- A C++17-capable compiler (`g++` is available).
- `liblmdb-dev` — LMDB development headers and shared library. The library
  transitively `#include`s `lmdb.h` and links `-llmdb`.
- `libb2-dev` — BLAKE2 development headers and shared library. The library
  transitively `#include`s `blake2.h` and links `-lb2`.
- `lmdbxx/lmdb++.h` — the C++ RAII wrapper over LMDB. Must be installed at the
  path `lmdbxx/lmdb++.h` on the system include path (see **Install contract**).
  The wrapper must expose the hoytech/lmdbxx API surface, at minimum:
    - `lmdb::env` with `create()`, `set_max_dbs(unsigned)`, `set_mapsize(size_t)`,
      `open(const char *path, unsigned flags, mdb_mode_t mode)`.
    - `lmdb::txn` with `begin(lmdb::env &env, MDB_txn *parent, unsigned flags)` —
      passing `parent = nullptr` starts a top-level transaction — plus `commit()`
      and `abort()`.
    - `lmdb::dbi` with `open(lmdb::txn &txn, const char *name, unsigned flags)`.
- `hoytech/hex.h` — a small single-header hex encoder used by the optional
  debug renderer `quadrable/debug.h`. Must be installed at `hoytech/hex.h` on
  the system include path.

## Install contract

After your `/app/setup.sh` is run, a freshly written driver must build and
run with:

```
g++ -std=c++17 driver.cpp -llmdb -lb2 -lpthread -o driver
./driver
```

That requires:

1. `liblmdb-dev` and `libb2-dev` installed (`apt-get install -y liblmdb-dev
   libb2-dev`). These are pre-installed at the image level; `setup.sh` need not
   re-install them.
2. The primary header installed at `/usr/local/include/quadrable.h`.
3. The sub-header directory installed at `/usr/local/include/quadrable/` so that
   `#include "quadrable/transport.h"`, `#include "quadrable/Key.h"`, etc. resolve.
4. The LMDB C++ wrapper header installed at
   `/usr/local/include/lmdbxx/lmdb++.h` — the primary header does
   `#include "lmdbxx/lmdb++.h"` transitively.
5. The hex helper installed at `/usr/local/include/hoytech/hex.h` — the optional
   debug header `quadrable/debug.h` does `#include "hoytech/hex.h"`.
6. No quadrable library to link — every public symbol lives in headers. Only
   `-llmdb -lb2 -lpthread` is needed for link.

## Namespace

All public symbols live in `namespace quadrable`. Transport encoders live in the
nested `namespace quadrable::transport`.

## Includes

The single `#include <quadrable.h>` is enough to reach the entire public API used
below. All of these names are declared at the top level of `namespace quadrable`
(NOT as inner classes of `class Quadrable`) — a downstream driver refers to them
as `quadrable::Proof`, `quadrable::SyncRequests`, etc.:

- Classes: `Quadrable`, `Key`, `MemStore`, `Sync`.
- Structs / typedefs: `Update`, `GetMultiResult`, `GetMultiQuery`, `Proof`,
  `ProofStrand`, `ProofCmd`, `SyncRequest`, `SyncRequests`, `SyncResponses`,
  `Stats`.
- Values / operators: `firstMemStoreNodeId` and every operator overload on `Key`.

To reach the byte-level wire encoders you additionally
`#include <quadrable/transport.h>`; those functions live in the nested
`namespace quadrable::transport` (see below).

# Public API surface

## `class Key`

A 32-byte hash value that addresses every leaf and interior node in the tree.
Public data member:

```cpp
uint8_t data[32];
```

Constructors and static factories:

```cpp
Key();                                          // uninitialized; call one of the factories

static Key hash(std::string_view s);            // Key = BLAKE2s(s) (32-byte output)
static Key existing(std::string_view raw);      // copy 32 bytes verbatim; raw.size() must == 32,
                                                //   otherwise throws std::runtime_error
static Key null();                              // all 32 bytes = 0x00
static Key max();                               // all 32 bytes = 0xFF
static Key fromInteger(uint64_t n);             // pack a 64-bit integer into a 32-byte key
                                                //   in a way that preserves ordering. Values
                                                //   above std::numeric_limits<uint64_t>::max() - 2
                                                //   are outside the representable range and throw.
static Key fromIntegerAndHash(uint64_t n,
                              std::string_view h); // fromInteger(n) with the trailing 23..31 bytes
                                                //   replaced by `h`. h.size() must be in 23..31.
```

Instance methods:

```cpp
uint64_t         toInteger() const;             // inverse of fromInteger; throws if this Key is
                                                //   not a fromInteger-shaped value.
std::string      str() const;                   // 32-byte std::string copy of data
std::string_view sv() const;                    // 32-byte std::string_view over data
bool             getBit(size_t n) const;        // read bit n (0 = MSB of byte 0, 255 = LSB of byte 31)
void             setBit(size_t n, uint64_t b);  // write bit n to 0 or 1; n > 255 throws
void             keepPrefixBits(size_t n);      // zero every bit at index >= n; n > 256 throws;
                                                //   n == 256 is a no-op
```

Comparison operators are defined for `Key vs Key` (`<`, `<=`, `>`, `>=`, `==`,
`!=`) and, as a convenience for interoperating with raw 32-byte strings,
`Key == std::string_view` and `Key != std::string_view`. Ordering is
byte-lexicographic over `data[0..31]`, so `Key::null()` is the minimum,
`Key::max()` the maximum, and every `Key::hash(x)` result lies strictly between
them.

Example:

```cpp
quadrable::Key k1 = quadrable::Key::hash("apple");
quadrable::Key k2 = quadrable::Key::hash("apple");
assert(k1 == k2);
assert(quadrable::Key::null() < k1);
assert(k1 < quadrable::Key::max());

quadrable::Key kn = quadrable::Key::fromInteger(42);
assert(kn.toInteger() == 42);
```

## `class Quadrable`

The primary object. Public interface:

```cpp
class Quadrable {
public:
    bool trackKeys       = false; // if set BEFORE init(), original keys (not just their hashes)
                                  //   are stored alongside leaves, and exportProof() can produce
                                  //   proofs whose Leaf strands carry the original key.
    bool writeToMemStore = false; // when true, new interior/leaf nodes go into the attached MemStore
                                  //   instead of LMDB (see MemStore section below).

    Quadrable();
    ~Quadrable();                 // frees an owning MemStore attached via addMemStore()

    // Must be called once per Quadrable-per-lmdb::env inside a write transaction
    // before any other operation.
    void init(lmdb::txn &txn);
    // ... every method below is a member function of this class ...
};
```

### Heads

A **head** is a named pointer to a root nodeId. The current head starts as
`"master"`. Consumers can switch between named heads, enter a "detached" mode
where the current head is an ephemeral nodeId, or fork the current head into a
fresh detached branch.

```cpp
void        checkout(std::string_view newHead);   // switch to a named head (creates if new)
void        checkout(uint64_t nodeId = 0);        // enter detached mode at nodeId (0 = empty tree)
bool        isDetachedHead();
std::string getHead();                            // returns current head name; throws if detached
uint64_t    getHeadNodeId(lmdb::txn &txn);        // root nodeId of the current head
uint64_t    getHeadNodeId(lmdb::txn &txn,
                          std::string_view h);    // root nodeId of a named head
void        setHeadNodeId(lmdb::txn &txn,
                          uint64_t nodeId);       // reposition the current head; storing a MemStore
                                                  //   nodeId into a NON-detached head throws
void        fork(lmdb::txn &txn);                 // detach the current head at its current nodeId
void        fork(lmdb::txn &txn, std::string h);  // fork into a new NAMED head
```

Example:

```cpp
db.checkout("master");
db.change().put("k", "v-master").apply(txn);

db.checkout("feature");           // fresh empty head
db.change().put("k", "v-feature").apply(txn);

db.checkout("master");            // v-master reappears
db.fork(txn);                     // now detached at master's current nodeId
db.change().put("k", "v-fork").apply(txn);   // divergent, master unchanged
```

### Root hashes

```cpp
std::string root(lmdb::txn &txn);                       // 32-byte hash of the current head's root
std::string root(lmdb::txn &txn, uint64_t nodeId);      // 32-byte hash of an arbitrary root
Key         rootKey(lmdb::txn &txn);                    // same, but wrapped as a Key
Key         rootKey(lmdb::txn &txn, uint64_t nodeId);
```

The empty tree's root is `Key::null().str()` — 32 zero bytes. Two trees with
identical `{key -> value}` mappings MUST have byte-identical root hashes,
independent of insertion order, batch boundaries, or intermediate mutations.
This is the load-bearing "authenticated" property that makes the library useful
as a merkle backing store: the root hash is a canonical function of the current
key set.

### Puts, deletes, and change sets

Updates go through an inner `UpdateSet` builder returned by `db.change()`. Each
mutation is buffered into the set; the whole set is applied atomically by
`.apply(txn)`. Within a single set, ordering of `put`/`del` calls is
semantically equivalent to "last write wins" per key.

```cpp
class Quadrable::UpdateSet {
public:
    UpdateSet& put(std::string_view key, std::string_view val,
                   uint64_t *outputNodeId = nullptr);
    UpdateSet& put(const Key &keyHash, std::string_view val,
                   uint64_t *outputNodeId = nullptr);
    UpdateSet& putReuse(const Key &keyHash, uint64_t nodeId,
                        uint64_t *outputNodeId = nullptr);
    UpdateSet& putReuse(lmdb::txn &txn, uint64_t nodeId,
                        uint64_t *outputNodeId = nullptr);
    UpdateSet& del(std::string_view key, uint64_t *outputNodeId = nullptr);
    UpdateSet& del(const Key &keyHash, uint64_t *outputNodeId = nullptr);
    void       apply(lmdb::txn &txn);
};

UpdateSet Quadrable::change();

// Sugar for change().put(...).apply(txn) / change().del(...).apply(txn):
void Quadrable::put(lmdb::txn &txn, std::string_view key, std::string_view val);
void Quadrable::del(lmdb::txn &txn, std::string_view key);
```

Rules:

- Zero-length keys are rejected — `.put("", v)` and `.del("")` throw
  `std::runtime_error`. Zero-length VALUES are allowed.
- `.del(k)` on a key not in the tree is a no-op (does not throw); the resulting
  tree state is identical to never having touched `k`.
- After a delete, the resulting root hash is byte-identical to a tree that
  only ever contained the surviving keys. This is what makes root hashes
  canonical: two trees hold the same `{key -> value}` map iff they have the
  same root hash.
- The optional `outputNodeId` argument, if non-null, receives the freshly
  written leaf's nodeId (for `put`) or the deleted leaf's nodeId (for `del`);
  it is written to `0` if the operation was a no-op (identical put, delete of
  absent key). If `outputNodeId` is not needed, pass `nullptr` (the default).

### Reads

```cpp
struct GetMultiResult {
    bool             exists;
    std::string_view val;
    uint64_t         nodeId;
};

using GetMultiQuery = std::map<std::string, GetMultiResult>;

// Single-key: returns true on hit and fills val (+ optional nodeId).
bool get(lmdb::txn &txn, std::string_view key,
         std::string_view &val, uint64_t *outputNodeId = nullptr);

// Single-key by raw 32-byte key hash (skips hashing).
bool getRaw(lmdb::txn &txn, std::string_view rawKeyHash,
            std::string_view &val, uint64_t *outputNodeId = nullptr);

// Multi-key by a set of string keys. Returns a fresh GetMultiQuery whose
// values reflect each key's presence and value.
GetMultiQuery get(lmdb::txn &txn, std::set<std::string> keys);

// In-place variants for callers assembling a query map by hand.
void getMulti(lmdb::txn &txn, GetMultiQuery &query);      // hashes each key first
void getMultiRaw(lmdb::txn &txn, GetMultiQuery &query);   // keys are ALREADY raw 32-byte hashes
```

If any traversal walks into a **witness** node (a node whose contents are
opaque under the current partial tree — see **Proofs** below), the read throws
`std::runtime_error` with a message containing `"incomplete tree"`. This is
distinct from "not present" (which returns `exists == false`).

### Stats

```cpp
struct Quadrable::Stats {
    uint64_t numNodes         = 0;
    uint64_t numLeafNodes     = 0;
    uint64_t numBranchNodes   = 0;
    uint64_t numWitnessNodes  = 0;
    uint64_t maxDepth         = 0;
    uint64_t numBytes         = 0;
};

Stats Quadrable::stats(lmdb::txn &txn);
```

`stats(txn)` walks the current head's tree and counts nodes by kind, tree
maximum depth, and total raw storage bytes.

### Iterator

An in-order iterator over the leaves of the current head. Ordering is by
`leafKeyHash()` (i.e., by 32-byte hash lexicographic order), NOT by original
key. Constructing an iterator seeks it to a target key; subsequent `.next()`
advances toward `Key::max()` in forward mode or toward `Key::null()` in reverse.

```cpp
struct Quadrable::Iterator {
    // Constructed by db.iterate(...); do not instantiate directly.
    void         next();
    ParsedNode   get();     // current node; empty node (nodeId == 0) if atEnd()
    bool         atEnd();
    // save()/restore(...) let a caller stash and resume an iteration position:
    SavedIterator save();
    bool          restore(lmdb::txn &txn, const SavedIterator &s);
};

Quadrable::Iterator Quadrable::iterate(lmdb::txn &txn,
                                       const Key &target,
                                       bool reverse = false);
```

Seek semantics:

- Forward (`reverse == false`): seek to the smallest leaf whose keyHash `>= target`.
  If no such leaf exists, the iterator lands in `atEnd()` state.
- Reverse (`reverse == true`): seek to the largest leaf whose keyHash `<= target`.
  If no such leaf exists, `atEnd()`.
- On an empty tree, `atEnd()` is immediately true in either direction.

The `ParsedNode` returned by `it.get()` exposes:

```cpp
struct Quadrable::ParsedNode {
    bool             isEmpty() const;
    bool             isLeaf() const;       // true for Leaf OR WitnessLeaf
    std::string_view leafKeyHash() const;  // 32-byte keyHash; throws if not a leaf
    Key              key() const;          // Key::existing(leafKeyHash())
    std::string_view leafVal() const;      // throws if not a Leaf (WitnessLeaf has no value)
    // Additional accessors (nodeType / nodeId / branch child ids / node
    // hash / value hash) are implementation-defined; not part of the
    // load-bearing public API for this task.
};
```

Example:

```cpp
auto it = db.iterate(txn, quadrable::Key::null());
for (; !it.atEnd(); it.next()) {
    std::cout << it.get().leafVal() << "\n";
}
```

## Proofs

A **proof** is a compact structure that lets a party who does not have the full
tree verify presence, absence, and values of a specific set of keys against a
known root hash. It is composed of:

- **Strands** — one per key of interest, carrying the key hash, depth, and one
  of: the leaf value (`Leaf`), a hash of the value (`WitnessLeaf`), a witness of
  emptiness (`WitnessEmpty`), or an opaque subtree hash (`Witness`).
- **Cmds** — a byte-code stream that describes how to reduce the strands to a
  single root hash by successively merging sibling strands or hashing them
  against an empty or provided hash.

```cpp
struct Quadrable::ProofStrand {
    enum class Type {
        Leaf = 0, Invalid = 1, WitnessLeaf = 2, WitnessEmpty = 3, Witness = 4,
    } strandType;
    uint64_t    depth;
    std::string keyHash;
    std::string val;   // Leaf: value; WitnessLeaf: hash(value); Witness: nodeHash; WitnessEmpty: unused
    std::string key;   // Leaf: original key (if available); else unused
};

struct Quadrable::ProofCmd {
    enum class Op { HashProvided = 0, HashEmpty = 1, Merge = 2 } op;
    uint64_t    nodeOffset;
    std::string hash;  // HashProvided only
};

struct Quadrable::Proof {
    std::vector<ProofStrand> strands;
    std::vector<ProofCmd>    cmds;
};
```

### Exporting proofs

```cpp
// Prove a set of keys (passed as strings; hashed internally to keyHashes).
Proof Quadrable::exportProof(lmdb::txn &txn,
                             const std::vector<std::string> &keys);

// Prove a set of pre-hashed keys (Key values, skips the hash step).
Proof Quadrable::exportProofRaw(lmdb::txn &txn,
                                const std::vector<Key> &keys);

// Prove every leaf whose keyHash lies in [begin, end] (with their values);
// leaves outside the range are not disclosed by the proof.
Proof Quadrable::exportProofRange(lmdb::txn &txn,
                                  const Key &begin, const Key &end);
Proof Quadrable::exportProofRange(lmdb::txn &txn, uint64_t nodeId,
                                  const Key &begin, const Key &end);
```

### Importing and merging proofs

```cpp
// Import a proof into the CURRENT head, which MUST be empty (detached at
// nodeId 0). Sets the current head to the reconstructed partial-tree root.
// If expectedRoot is non-empty, the reconstructed root must equal it; otherwise
// throws.
Quadrable::BuiltNode Quadrable::importProof(lmdb::txn &txn, Proof &proof,
                                            std::string expectedRoot = "");

// Merge a proof INTO a non-empty head that shares the same root. Fills in
// witness slots the caller learned about; leaves everything else alone.
// Throws if the roots don't match.
Quadrable::BuiltNode Quadrable::mergeProof(lmdb::txn &txn, Proof &proof);
```

### Proof queries and updates

After `importProof`, the current head is a **partial tree** — some regions are
opaque witnesses. Reads work as usual:

- Proven-present keys: `get()` returns their exact stored value.
- Proven-absent keys (covered by a `WitnessEmpty` strand): `get()` returns
  `exists = false`.
- Unproven keys that land in a `Witness` region: `get()` throws
  `std::runtime_error` with a message containing `"incomplete tree"`.

Updates against a partial tree:

- `.put(k, v)` / `.del(k)` on a **proven leaf** produces the same root hash
  that the same mutation would produce against the full tree — this is what
  makes proofs actionable: a party who has only the proof can still apply an
  update and report the new root back to a full-tree holder.
- `.put(k, v)` on a **Witness** slot throws (`"encountered witness"` or similar
  — the exact message is not load-bearing).
- `.del(k)` that would need to bubble past a `Witness` node throws (`"can't
  bubble a witness node"` or similar).

### Encoding compactness

Proofs are compact partial-tree structures, not full-tree dumps: a proof for a
single `Key::fromInteger(n)` key encodes to far fewer bytes than a proof
covering the whole tree — in fact to fewer bytes than the 32-byte keyHash it
proves, for every `n` up to 10^9 — and its encoded size stays small and
essentially independent of how large `n` is.

## Sync protocol

`Quadrable::Sync` is a stateful client that reconstructs a remote tree into a
local storage attachment (typically a `MemStore`) by exchanging proof fragments
with a server that holds the target tree. It is designed for over-the-wire
transports: requests and responses are just byte strings routed through
`quadrable::transport::encodeSyncRequests` / `encodeSyncResponses` on the wire.

```cpp
enum class Quadrable::DiffType { Added = 0, Deleted = 1, Changed = 2 };

using Quadrable::SyncedDiffCb =
    std::function<void(DiffType, const ParsedNode &)>;

class Quadrable::Sync {
public:
    Quadrable *db;
    uint64_t   nodeIdLocal  = std::numeric_limits<uint64_t>::max();
    uint64_t   nodeIdShadow;        // reconstructed tree root nodeId
    uint64_t   initialDepthLimit = 4;  // depth of the first request
    uint64_t   laterDepthLimit   = 4;  // depth of subsequent requests

    Sync(Quadrable *db);

    void          init(lmdb::txn &txn, uint64_t nodeIdLocal);
    SyncRequests  getReqs(lmdb::txn &txn,
                          uint64_t bytesBudget = std::numeric_limits<uint64_t>::max(),
                          std::optional<SyncedDiffCb> cb = std::nullopt);
    void          addResps(lmdb::txn &txn,
                           SyncRequests &reqs, SyncResponses &resps);
    void          diffReset();
    void          diff(lmdb::txn &txn,
                       uint64_t nodeIdOurs, uint64_t nodeIdTheirs,
                       const SyncedDiffCb &cb);
};

// Server side: given a set of sync requests coming from a peer, produce
// proof fragments for the paths they asked about. bytesBudget caps the
// aggregate response size; the fragment set may be partial if the budget
// is exhausted (the requester will re-request in a subsequent round).
Quadrable::SyncResponses Quadrable::handleSyncRequests(
    lmdb::txn &txn, uint64_t nodeId, SyncRequests &reqs,
    uint64_t bytesBudget = std::numeric_limits<uint64_t>::max());
```

`SyncRequest` and its container:

```cpp
struct Quadrable::SyncRequest {
    Key      path;
    uint64_t startDepth;
    uint64_t depthLimit;
    bool     expandLeaves;
};

using Quadrable::SyncRequests  = std::vector<SyncRequest>;
using Quadrable::SyncResponses = std::vector<Proof>;
```

Client loop (idealized):

```cpp
Quadrable::Sync sync(&db);
sync.init(txn, /*nodeIdLocal=*/0);  // 0 = "we start empty"

while (true) {
    auto reqs = sync.getReqs(txn, /*bytesBudget=*/1024);
    if (reqs.empty()) break;              // converged

    auto resps = server.handleSyncRequests(txn, server_root, reqs);
    sync.addResps(txn, reqs, resps);
}
// sync.nodeIdShadow now points at the reconstructed tree.
```

Contracts:

- After convergence, `db.root(txn, sync.nodeIdShadow)` MUST equal the source
  tree's root byte-for-byte.
- Convergence occurs regardless of `bytesBudget` size: a small budget just
  requires more rounds. `bytesBudget == 0` on either `getReqs` or
  `handleSyncRequests` throws.
- `Sync::diff(txn, oursId, theirsId, cb)` walks the two trees and emits one
  callback per differing leaf: `DiffType::Added` (in `theirs` but not `ours`),
  `DiffType::Deleted` (in `ours` but not `theirs`), or `DiffType::Changed`
  (same keyHash, different value). `diffReset()` clears the internal
  "already visited" set between diff runs.

## `db.diff()` — bare vector diff

A simpler, non-Sync-aware diff surfaces the full leaf-level delta between two
tree revisions as a `std::vector`:

```cpp
struct Quadrable::Diff {
    std::string keyHash;
    std::string key;       // present only if trackKeys was on when the leaf was written
    std::string val;       // NEW value for insertions; OLD value for deletions
    bool        deletion = false;
};

std::vector<Diff> Quadrable::diff(lmdb::txn &txn,
                                  uint64_t nodeIdA, uint64_t nodeIdB);
```

An update to a key surfaces as a `deletion == true` entry (the OLD value)
followed by a `deletion == false` entry (the NEW value) for the same keyHash.
An update to a leaf that was neither present in A nor in B is impossible.
Diffing a nodeId against itself yields an empty vector.

## MemStore — RAM-backed shadow storage

MemStore is a `std::map<uint64_t, std::string>` that holds transient nodes off
of LMDB. Its primary use is during sync (to reconstruct a partial shadow tree
without polluting LMDB storage), but any caller can attach one to a `Quadrable`
to buffer ephemeral work.

```cpp
struct quadrable::MemStore {
    std::map<uint64_t, std::string> nodes;
    uint64_t                        headNodeId = 0;
};

// Node id boundaries reserved for MemStore (2^59) and for interior LMDB nodes
// (2^58). A node id above firstMemStoreNodeId lives in RAM; between
// firstInteriorNodeId and firstMemStoreNodeId, it lives in dbi_nodesInterior;
// below firstInteriorNodeId, in dbi_nodesLeaf.
constexpr uint64_t quadrable::firstInteriorNodeId = 288230376151711744ULL; // 2^58
constexpr uint64_t quadrable::firstMemStoreNodeId = 576460752303423488ULL; // 2^59
```

Attach modes:

```cpp
// (a) SCOPED via callback. m is attached for the duration of the callback,
//     then detached. Preferred when the ephemeral tree is a within-function
//     concern.
void Quadrable::withMemStore(MemStore &m, std::function<void()> cb);

// (b) LONG-LIVED via internally-owned MemStore. addMemStore() creates a fresh
//     MemStore and attaches it; removeMemStore() detaches and frees it. Calling
//     removeMemStore() when no owning MemStore is attached throws.
void Quadrable::addMemStore(bool writeToMemStore_default = true);
void Quadrable::removeMemStore();
```

Rules:

- While a MemStore is attached and `writeToMemStore == true`, freshly written
  nodes are assigned ids from the MemStore range (`>= firstMemStoreNodeId`).
- Storing a MemStore-range nodeId into a NON-detached (named) head throws:
  the head lives in LMDB and cannot reference RAM nodes. Callers that want to
  build on top of a named head from a MemStore scope must first `fork(txn)` to
  detach.
- `trackKeys` is incompatible with MemStore attachment. The scoped attach
  guard throws if `trackKeys` was set at attach time.
- After a MemStore is detached (either by leaving `withMemStore`'s scope or by
  calling `removeMemStore()`), MemStore-only node ids are no longer resolvable;
  attempts to load them throw.

Example:

```cpp
quadrable::MemStore m;
db.withMemStore(m, [&]{
    db.checkout();                    // detached empty
    db.writeToMemStore = true;
    db.change().put("k", "v").apply(txn);
    // ... run a reconstruction, verify a proof, etc.
});
db.writeToMemStore = false;
```

## GarbageCollector

When a head advances from v1 to v2, the v1 tree's interior nodes are typically
still in LMDB storage but no longer reachable from any named head. The
`GarbageCollector` sweeps those out.

```cpp
template <typename Set = std::set<uint64_t>>
class Quadrable::GarbageCollector {
public:
    struct GCStats { uint64_t total = 0; uint64_t garbage = 0; };

    GarbageCollector(Quadrable &db);

    void markAllHeads(lmdb::txn &txn);                     // mark reachable from every head
    void markTree(lmdb::txn &txn, uint64_t rootNodeId);    // mark reachable from a specific root
    GCStats sweep(lmdb::txn &txn,
                  std::optional<std::function<bool(uint64_t)>> extra_pred
                    = std::nullopt);                        // enumerate garbage; predicate lets
                                                            //   caller exclude specific ids
    void deleteNodes(lmdb::txn &txn);                       // actually delete the swept-out garbage
};
```

Usage:

```cpp
quadrable::Quadrable::GarbageCollector<> gc(db);
gc.markAllHeads(txn);
auto stats = gc.sweep(txn);
gc.deleteNodes(txn);
```

Contracts:

- After `markAllHeads(txn)` + `sweep(txn)`, `GCStats::total` is the total
  count of stored interior + leaf nodes; `GCStats::garbage` is the count of
  nodes not reachable from any named head.
- Immediately after every leaf and interior node has been assigned to at least
  one head (typical case: build tree, no removals), `sweep()` reports
  `garbage == 0`.
- After a subsequent full overwrite of the tree (e.g. `put("k", "v2")` for
  every `k`), the previous version's nodes are orphaned and `sweep()`
  reports non-zero garbage.
- `deleteNodes(txn)` frees the identified garbage; a second `mark + sweep`
  pass reports `garbage == 0` again.

## `namespace quadrable::transport` — wire encoding

The byte-level encoders and decoders for Proof, SyncRequests, and
SyncResponses:

```cpp
enum class transport::EncodingType {
    HashedKeys = 0,   // Leaf strands carry only the 32-byte keyHash (default)
    FullKeys   = 1,   // Leaf strands carry the original key too (requires trackKeys)
};

std::string  transport::encodeProof(const Proof &p,
                                    EncodingType t = EncodingType::HashedKeys);
Proof        transport::decodeProof(std::string_view encoded);

std::string  transport::encodeSyncRequests(const SyncRequests &reqs);
SyncRequests transport::decodeSyncRequests(std::string_view encoded);

std::string  transport::encodeSyncResponses(const SyncResponses &resps,
                                            EncodingType t = EncodingType::HashedKeys);
SyncResponses transport::decodeSyncResponses(std::string_view encoded);
```

Contract: `decode(encode(x))` MUST produce a value deep-equal to `x` in every
field the encoding covers, for all three (Proof, SyncRequests, SyncResponses).

# Behaviour notes

- **Determinism.** The library uses only deterministic operations (BLAKE2s
  hashing, integer arithmetic, byte concatenation). Two callers running the
  same sequence of `.put`/`.del` on trees with the same starting root MUST
  produce byte-identical root hashes.
- **Exception discipline.** All error conditions surface as `std::runtime_error`
  or a subclass. Error messages contain a distinguishing substring where
  documented above (`"zero-length keys not allowed"`, `"incomplete tree"`,
  `"int range exceeded"`, `"attempted to store MemStore node into LMDB"`,
  `"can't bubble a witness node"`, `"can't importProof into non-empty head"`,
  `"proof invalid"`, `"encountered witness during update"`).
- **Transaction scope.** Every read + write API takes an `lmdb::txn` reference;
  the caller opens and commits/aborts the txn. Multiple heads and multiple
  mutations within one txn share the same node id space.
