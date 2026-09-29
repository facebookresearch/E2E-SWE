# `trie` — Ethereum trie data structures

Implement the `trie` package: a `HexaryTrie` (the Ethereum Modified Merkle Patricia Trie), a `BinaryTrie` (a binary radix trie), a `SparseMerkleTree`, and an ordered `NodeIterator`, plus their shared types, exceptions, and constants. The trie roots produced by your implementation must be byte-for-byte identical to the canonical Ethereum trie roots.

**Dependencies.** The environment is **offline**: every dependency is already installed and you **must not install anything** (there is no network). The project is installed for you by a `setup.sh` that runs offline (an editable install of your package). The following libraries are pre-installed and available to `import`: `eth-hash` (with the `pycryptodome` keccak backend), `eth-utils`, `hexbytes`, `rlp`, and `sortedcontainers`. Node hashing uses **keccak-256 — the Ethereum/pre-NIST Keccak, NOT NIST SHA3-256** — and nodes are **RLP-encoded**; use `eth-hash` for keccak (e.g. `from eth_hash.auto import keccak`) and `rlp` for RLP encoding/decoding.

All keys and values are `bytes`. A database `db` is any mutable mapping (a `dict` is the common case) used as a content-addressed node store.

## HexaryTrie

```python
from trie import HexaryTrie
```

`HexaryTrie` is an **Ethereum-compatible Modified Merkle Patricia Trie**. Its `root_hash` is the 32-byte Ethereum trie root: the **keccak-256 hash of the RLP-encoded trie nodes, matching Ethereum's canonical trie test vectors**. Reproducing those canonical roots exactly is the core correctness requirement.

```python
HexaryTrie(db, root_hash=BLANK_NODE_HASH, prune=False)
```

The `root_hash` attribute always reflects the current state and starts at `BLANK_NODE_HASH` for an empty trie. The class also exposes `BLANK_NODE_HASH` and `BLANK_NODE` as class attributes.

With `prune=True` the trie reclaims storage as it mutates: a node that a `set` or `delete` leaves unreachable from the new root is removed from `db`.

Mapping operations:

- `get(key) -> bytes` — the stored value, or `b''` if the key is absent.
- `set(key, value) -> None` — store `value` under `key`. Setting a key to `b''` **deletes** it (equivalent to `delete`).
- `delete(key) -> None`.
- `exists(key) -> bool` — equivalent to `get(key) != b''`.
- The dict interface `trie[key]`, `trie[key] = value`, `del trie[key]`, and `key in trie` delegate to the above.

A non-`bytes` key or value raises `ValidationError`. Roots are **order-independent**: the same set of key/value pairs yields the same `root_hash` regardless of insertion order, and deleting every key returns the root to `BLANK_NODE_HASH`. If an operation needs a node that is absent from `db`, raise `MissingTrieNode`.

### Proofs

- `get_proof(key) -> tuple` — the tuple of trie nodes along the path to `key`, each a **decoded node body** (a list, or `b''` — the same form as `HexaryTrieNode.raw`), not RLP-encoded bytes. Works for present keys (proof of inclusion) and absent keys (proof of exclusion); the exclusion proof is non-empty.
- `get_from_proof(root_hash, key, proof) -> bytes` *(classmethod)* — the value for `key` reconstructed from `proof` under `root_hash`, or `b''` if the proof demonstrates the key is absent. Raise `BadTrieProof` if the proof is empty or does not contain every node needed to authenticate `key` against `root_hash` (i.e. an incomplete or tampered proof).

Round-trip: `HexaryTrie.get_from_proof(trie.root_hash, key, trie.get_proof(key))` returns the key's value.

### Traversal and nodes

These expose the trie's node structure and return `HexaryTrieNode` (see Shared types).

- `root_node` *(property)* `-> HexaryTrieNode` — the root node; raises `MissingTraversalNode` if the root body is absent from `db`.
- `traverse(nibbles) -> HexaryTrieNode` — the node reached by following the given sequence of nibbles (ints 0–15) from the root. `traverse(())` returns the root node and equals `root_node`. Raises `MissingTraversalNode` if a needed node body is absent. Raises `TraversedPartialPath` if the path does not land exactly on a node's prefix. Fully consuming an extension node's compressed segment advances to and **returns** the extension's child node (an extension always leads to a further node): so a path whose remaining nibbles exactly equal an extension segment lands on the node beyond it, and if that child is a branch carrying a value the branch is returned (`node_type == BRANCH`, with its `value`). `TraversedPartialPath` is raised only when the path stops *inside* a segment without reaching a node at the requested prefix — i.e. it descends part-way into a leaf or extension segment, **or** it consumes a leaf's terminal suffix (a leaf has no node beyond its suffix, so a full-suffix match on a leaf is partial and `.node` is that leaf), even where the remaining nibbles exactly match that suffix.

`TraversedPartialPath` carries `.node` (the reached node, e.g. the leaf) and a `simulated_node` attribute: a `HexaryTrieNode` reconstructed as though a node existed exactly at the requested prefix. (How the partial step is split between `nibbles_traversed` and `untraversed_tail`, and how the node's remaining `suffix`/`sub_segments` are trimmed, are left to the implementation.)

### Squashing and snapshots

- `squash_changes()` *(context manager)* — yields a temporary trie; on exit, writes only the minimal set of nodes needed for the resulting root into `self.db` and updates `self.root_hash`. The final root is identical to performing the same mutations directly, but the database ends up with fewer stored nodes.
- `at_root(root_hash)` *(context manager)* — yields a read-only snapshot of the trie at a historical `root_hash`, leaving the main trie unchanged. The snapshot supports the read-only API against that root — `get`, `exists`, `get_proof`, `traverse`, `root_node`. Raises `ValidationError` if called on a pruning (`prune=True`) trie.

## BinaryTrie

```python
from trie import BinaryTrie
```

`BinaryTrie` is a **binary radix trie**; its `root_hash` is the keccak-256 hash of its serialized nodes. Keys are consumed bit by bit, so binary-trie roots differ from hexary roots. The empty-trie root is `BLANK_HASH` (note: **not** `BLANK_NODE_HASH`).

```python
BinaryTrie(db, root_hash=BLANK_HASH)
```

- `get(key) -> bytes` — the stored value, or **`None`** if absent (note the difference from `HexaryTrie`, which returns `b''`).
- `set(key, value) -> None` — store `value`; updates `root_hash`.
- `delete(key) -> None` — equivalent to setting the value to `b''`.
- `delete_subtrie(key) -> None` — delete the entire subtrie rooted at the `key` prefix: if `key` is a prefix of (or equal to) one or more stored keys, the whole matching subtrie is removed and the call **succeeds** — this is its normal operation (so deleting the common prefix of several keys empties those keys). A `key` that cleanly diverges from every stored key (matches no subtrie) is a **no-op**.
- `exists(key) -> bool` — equivalent to `get(key) is not None`.
- The dict interface (`[]`, `[]=`, `del`, `in`) delegates to the above.

Roots are order-independent. A non-`bytes` argument raises `ValidationError`. The binary trie forbids a key that is a strict prefix of, or has as a strict prefix, an already-stored key. For `set` and `delete`, **both** directions of such a prefix conflict raise `NodeOverrideError`. For `delete_subtrie`, only the **over-run** direction raises — a key that has a stored key as a strict prefix raises `NodeOverrideError`; the other direction, where `key` is itself a prefix of stored keys, is `delete_subtrie`'s normal success path and does **not** raise. Deleting a key that is simply absent (and is not a prefix conflict) is a no-op, leaving `root_hash` unchanged.

## SparseMerkleTree

```python
from trie.smt import SparseMerkleTree, SparseMerkleProof, calc_root
```

A `SparseMerkleTree` is a **fixed-depth binary Merkle tree** of depth `key_size * 8`. Unset leaves take the `default` value, so absent keys still yield a well-defined root.

```python
SparseMerkleTree(key_size=32, default=b'')              # note: NO db argument
```

The constructor builds an empty tree with its own internal store and sets `root_hash`. `key_size` must be in `[1, 32]`, else `ValidationError`. The tree exposes a `depth` attribute equal to `key_size * 8`.

- `get(key) -> bytes` — the value at `key`, or `default` if it was never set. Raises **`KeyError`** only when the resolved value is blank (`b''`). So with `default=b''` an unset key raises `KeyError`, but with a non-blank `default` every key reads as present and `get` returns that default.
- `set(key, value) -> Tuple[bytes, ...]` — store `value`; returns a tuple of the node hashes updated along the path, ordered **root → leaf** (index `0` is the node nearest the root; the last entry is the leaf). The tuple length equals `depth`. A wrong-length key raises `ValidationError`. `branch(key)` uses the same root → leaf ordering.
- `delete(key) -> Tuple[bytes, ...]` — equivalent to setting the value to `default`; restores the empty-tree root once all keys are removed.
- `exists(key) -> bool` — `True` iff the value is non-blank (so with a non-blank `default`, every key exists).
- `branch(key) -> Tuple[bytes, ...]` — the sibling hashes along the path. Like `get`, it raises `KeyError` when the resolved value is blank (`b''`); with a non-blank `default` it never raises.
- The dict interface (`[]`, `[]=`, `del`, `in`) delegates to the above.

`calc_root(key, value, branch) -> bytes` is a pure function recomputing the root from a key, its value, and the `branch` sibling hashes. It raises `ValidationError` if `branch` is not exactly `key_size * 8` entries long. The defining invariant: `smt.root_hash == calc_root(key, value, smt.branch(key))`.

`SparseMerkleProof(key, value, branch)` tracks one key's value and proof branch so they stay consistent as the tree is mutated elsewhere — without re-querying the tree. Properties: `key`, `value`, `branch`, and `root_hash` (= `calc_root(key, value, branch)`). Method `update(key, value, node_updates)` merges another update **in place** (returns `None`), where `node_updates` is exactly the root → leaf tuple that the tree's `set(key, value)` returned for that change. After applying each remote update this way, the proof stays synchronized: `proof.root_hash == smt.root_hash` and `proof.branch == smt.branch(tracked_key)`; an update to the tracked key itself updates `proof.value`. The *branch point* is the depth of the first bit at which the updated `key` differs from the tracked key, counting from the root (the most-significant bit is depth `0`); a divergence at the deepest bit therefore sits at depth `depth - 1`. Because `node_updates` is in root → leaf order, `update` needs it to extend at least past that branch-point depth and raises `ValidationError` if it does not.

## NodeIterator

```python
from trie.iter import NodeIterator
```

`NodeIterator(trie)` walks a `HexaryTrie` in **ascending key order**.

- `next(key=None) -> Optional[bytes]` — the smallest key strictly greater than `key` (or the first key when `key is None`); returns `None` when there is no key to the right.
- `keys()`, `values()`, `items()` — iterators over keys, values, and `(key, value)` pairs in ascending key order.

If a node body needed during iteration is absent from the underlying `db`, iteration raises `MissingTraversalNode`.

## Shared types

```python
from trie.typing import HexaryTrieNode, NodeType
```

`HexaryTrieNode` is a `NamedTuple` with fields, in order: `(sub_segments, value, suffix, raw, node_type)`.

- `sub_segments` — the child sub-keys reachable from this node (each a tuple of nibbles); empty for a leaf.
- `value` — the value at this node (`b''` if none).
- `suffix` — a leaf's remaining nibbles (empty for a branch).
- `raw` — the raw node body (a list, or `b''`).
- `node_type` — a `NodeType`.

`NodeType` is an `IntEnum`: `BLANK = 0`, `LEAF = 1`, `EXTENSION = 2`, `BRANCH = 3`.

## Exceptions

```python
from trie.exceptions import (
    ValidationError,
    BadTrieProof,
    NodeOverrideError,
    MissingTrieNode,
    MissingTraversalNode,
    TraversedPartialPath,
)
```

The **type** raised is the contract (messages are not asserted). `MissingTraversalNode` exposes `missing_node_hash` and `nibbles_traversed`; `TraversedPartialPath` exposes `nibbles_traversed`, `node`, `untraversed_tail`, and `simulated_node`; `MissingTrieNode` exposes `missing_node_hash`, `root_hash`, and `requested_key`.

## Constants

```python
from trie.constants import BLANK_NODE_HASH, BLANK_HASH, BLANK_NODE
```

- `BLANK_NODE` is `b''`.
- `BLANK_NODE_HASH` is `keccak(rlp.encode(b''))` — the empty `HexaryTrie` root.
- `BLANK_HASH` is `keccak(b'')` — the empty `BinaryTrie` root.
