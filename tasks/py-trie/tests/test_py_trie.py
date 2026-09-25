"""
Hidden WRG test suite for a from-scratch reimplementation of ethereum/py-trie
v3.1.0 (PyPI ``trie``).

Covers HexaryTrie (core/proofs/squash/at_root/traverse), BinaryTrie,
SparseMerkleTree (+calc_root) and NodeIterator. Canonical Ethereum MPT root
hashes are hardcoded hex-string literals verified byte-exact against
trie==3.1.0; the real published library is never imported here.
"""
import copy

import pytest

from trie import HexaryTrie, BinaryTrie
from trie.smt import SparseMerkleTree, SparseMerkleProof, calc_root
from trie.iter import NodeIterator
from trie.exceptions import (
    BadTrieProof,
    MissingTraversalNode,
    MissingTrieNode,
    NodeOverrideError,
    TraversedPartialPath,
    ValidationError,
)
from trie.typing import HexaryTrieNode, NodeType


# ---------------------------------------------------------------------------
# Canonical anchors (0x-stripped hex of root_hash). DO NOT recompute via trie.
# ---------------------------------------------------------------------------
BLANK_NODE_HASH_HEX = (
    "56e81f171bcc55a6ff8345e692c0f86e5b48e01b996cadc001622fb5e363b421"
)
SINGLE_SMALL_KEY_HEX = (
    "82c8fd36022fbc91bd6b51580cfd941d3d9994017d59ab2e8293ae9c94c3ab6e"
)
FOUR_ENTRY_HEX = (  # trieanyorder "puppy" — primary anchor
    "5991bb8c6514148a29db676a14ac506cd2cd5775ace63c30a4fe457715e9ac84"
)
DOGS_HEX = "8aad789dff2f538bca5d8ea56e8abe10f4c7ba3a5dea95fea4cd6e7c3a1168d3"
FOO_HEX = "17beaa1648bafa633cda809c90c04af50fc8aed3cb40d16efbddee6fdf63c4c3"
BRANCH_VALUE_UPDATE_HEX = (
    "7a320748f780ad9ad5b0837302075ce0eeba6c26e3d8562c67ccc0f1b273298a"
)
INSERT_MIDDLE_LEAF_HEX = (
    "cb65032e2f76c48b82b5c24b3db8f670ce73982869d38cd39a624f23d62a9e89"
)
HEX_KEYS_HEX = "285505fcabe84badc8aa310e2aae17eddc7d120aabec8a476902c8184b3a3503"


# Canonical key/value sets (inlined fixture entries)
FOUR_ENTRY = [
    (b"do", b"verb"),
    (b"horse", b"stallion"),
    (b"doge", b"coin"),
    (b"dog", b"puppy"),
]
DOGS = [
    (b"doe", b"reindeer"),
    (b"dog", b"puppy"),
    (b"dogglesworth", b"cat"),
]
INSERT_MIDDLE_LEAF = [
    (b"key1aa", b"0123456789012345678901234567890123456789xxx"),
    (b"key1", b"0123456789012345678901234567890123456789Very_Long"),
    (b"key2bb", b"aval3"),
    (b"key2", b"short"),
    (b"key3cc", b"aval3"),
    (b"key3", b"1234567890123456789012345678901"),
]
# trietest "emptyValues": insert + null(=delete) stream; final root == FOUR_ENTRY
EMPTY_VALUES_STREAM = [
    (b"do", b"verb"),
    (b"ether", b"wookiedoo"),
    (b"horse", b"stallion"),
    (b"shaman", b"horse"),
    (b"doge", b"coin"),
    (b"ether", None),  # null -> delete
    (b"dog", b"puppy"),
    (b"shaman", None),  # null -> delete
]


def fixture_bytes(token):
    """Decode a fixture token: 0x-prefixed -> hex bytes, else utf-8 bytes."""
    if isinstance(token, bytes):
        return token
    if token.startswith("0x"):
        return bytes.fromhex(token[2:])
    return token.encode("utf-8")


@pytest.fixture
def db():
    return {}


def build(db, entries):
    """Build a trie from (key, value) pairs; None value means delete."""
    trie = HexaryTrie(db)
    for key, value in entries:
        if value is None:
            trie[key] = b""
        else:
            trie[key] = value
    return trie


# ===========================================================================
# HexaryTrie core (CANON-anchored)
# ===========================================================================
class TestHexaryCore:
    def test_blank_root(self, db):
        """A brand-new empty trie has the canonical blank-node root hash."""
        trie = HexaryTrie(db)
        assert trie.root_hash.hex() == BLANK_NODE_HASH_HEX
        assert trie.root_hash == HexaryTrie.BLANK_NODE_HASH

    def test_single_small_key(self, db):
        """Insert one small key; root matches the non-fixture canonical anchor."""
        trie = HexaryTrie(db)
        trie[b"\x01\x02\x03"] = b"hello"
        assert trie.root_hash.hex() == SINGLE_SMALL_KEY_HEX
        assert trie[b"\x01\x02\x03"] == b"hello"

    def test_four_entry_canonical_root(self, db):
        """The canonical 4-entry do/dog/doge/horse set reproduces the puppy root."""
        trie = build(db, FOUR_ENTRY)
        assert trie.root_hash.hex() == FOUR_ENTRY_HEX
        assert trie[b"do"] == b"verb"
        assert trie[b"dog"] == b"puppy"
        assert trie[b"doge"] == b"coin"
        assert trie[b"horse"] == b"stallion"

    def test_dogs_root(self, db):
        """doe/dog/dogglesworth set (shared-prefix extension+branch) -> dogs root."""
        trie = build(db, DOGS)
        assert trie.root_hash.hex() == DOGS_HEX
        for key, value in DOGS:
            assert trie[key] == value

    def test_extension_and_branch_value_root(self):
        """
        foo/food yields an extension->branch-with-value layout; and the
        abc/abcd/abc-overwrite stream lands a value on a branch node.
        """
        foo_trie = HexaryTrie({})
        foo_trie[b"foo"] = b"bar"
        foo_trie[b"food"] = b"bass"
        assert foo_trie.root_hash.hex() == FOO_HEX

        bvu_trie = HexaryTrie({})
        bvu_trie[b"abc"] = b"123"
        bvu_trie[b"abcd"] = b"abcd"
        bvu_trie[b"abc"] = b"abc"  # overwrite branch value
        assert bvu_trie.root_hash.hex() == BRANCH_VALUE_UPDATE_HEX
        assert bvu_trie[b"abc"] == b"abc"
        assert bvu_trie[b"abcd"] == b"abcd"

    def test_insert_middle_leaf_root(self, db):
        """The 6-key insert-middle-leaf set reproduces its canonical root."""
        trie = build(db, INSERT_MIDDLE_LEAF)
        assert trie.root_hash.hex() == INSERT_MIDDLE_LEAF_HEX
        for key, value in INSERT_MIDDLE_LEAF:
            assert trie[key] == value

    def test_hex_byte_keys_root(self, db):
        """Hex-decoded binary keys/values reproduce the canonical hex root."""
        trie = HexaryTrie(db)
        trie[fixture_bytes("0x0045")] = fixture_bytes("0x0123456789")
        trie[fixture_bytes("0x4500")] = fixture_bytes("0x9876543210")
        assert trie.root_hash.hex() == HEX_KEYS_HEX
        assert trie[fixture_bytes("0x0045")] == fixture_bytes("0x0123456789")
        assert trie[fixture_bytes("0x4500")] == fixture_bytes("0x9876543210")

    def test_order_independence(self):
        """The same key set inserted in two different orders yields one root."""
        forward = build({}, FOUR_ENTRY)
        reversed_trie = build({}, list(reversed(FOUR_ENTRY)))
        assert forward.root_hash == reversed_trie.root_hash
        assert forward.root_hash.hex() == FOUR_ENTRY_HEX

    def test_set_empty_value_deletes(self):
        """Setting a key to b'' is equivalent to deleting it."""
        via_empty = HexaryTrie({})
        via_empty[b"dog"] = b"puppy"
        via_empty[b"cat"] = b"meow"
        via_empty[b"cat"] = b""  # delete via empty value

        via_del = HexaryTrie({})
        via_del[b"dog"] = b"puppy"
        via_del[b"cat"] = b"meow"
        del via_del[b"cat"]

        assert via_empty.root_hash == via_del.root_hash
        assert via_empty[b"cat"] == b""
        assert b"cat" not in via_empty

    def test_delete_to_blank(self, db):
        """Inserting then deleting every key returns to the blank-node root."""
        trie = build(db, FOUR_ENTRY)
        assert trie.root_hash.hex() == FOUR_ENTRY_HEX
        for key, _ in FOUR_ENTRY:
            del trie[key]
        assert trie.root_hash.hex() == BLANK_NODE_HASH_HEX

    def test_empty_values_with_deletes_fixture(self, db):
        """
        The emptyValues stream (inserts interleaved with null-deletes) reproduces
        the same root as the plain 4-entry set, proving delete-via-b'' is exact.
        """
        trie = build(db, EMPTY_VALUES_STREAM)
        assert trie.root_hash.hex() == FOUR_ENTRY_HEX
        assert trie[b"ether"] == b""
        assert trie[b"shaman"] == b""
        assert trie[b"do"] == b"verb"

    def test_get_and_exists(self):
        """Present keys return their value / True; absent return b'' / False."""
        trie = build({}, FOUR_ENTRY)
        assert trie.get(b"dog") == b"puppy"
        assert trie.exists(b"dog") is True
        assert b"dog" in trie

        assert trie.get(b"missing") == b""
        assert trie.exists(b"missing") is False
        assert b"missing" not in trie

        # A non-bytes key/value is a usage error (ValidationError).
        with pytest.raises(ValidationError):
            trie.set("not-bytes", b"value")

    def test_overwrite_value(self):
        """Re-setting an existing key changes both the stored value and the root."""
        trie = HexaryTrie({})
        trie[b"dog"] = b"puppy"
        first_root = trie.root_hash
        trie[b"dog"] = b"grownup"
        assert trie[b"dog"] == b"grownup"
        assert trie.root_hash != first_root


# ===========================================================================
# Proofs
# ===========================================================================
class TestProofs:
    def test_proof_inclusion_roundtrip(self):
        """get_from_proof recovers the value for every included key."""
        trie = build({}, FOUR_ENTRY)
        root = trie.root_hash
        for key, value in FOUR_ENTRY:
            proof = trie.get_proof(key)
            assert HexaryTrie.get_from_proof(root, key, proof) == value

    def test_proof_exclusion(self):
        """Absent keys produce non-empty exclusion proofs that resolve to b'',
        across divergence shapes (shared-prefix, mid-extension, empty branch slot)."""
        trie = build({}, INSERT_MIDDLE_LEAF)  # extension-heavy structure
        root = trie.root_hash
        for absent in (b"doe", b"key1ZZ", b"key9", b"zzz"):
            proof = trie.get_proof(absent)
            assert len(proof) > 0
            assert HexaryTrie.get_from_proof(root, absent, proof) == b""

    def test_proof_empty_raises(self):
        """An empty proof list cannot satisfy a lookup -> BadTrieProof."""
        trie = build({}, FOUR_ENTRY)
        with pytest.raises(BadTrieProof):
            HexaryTrie.get_from_proof(trie.root_hash, b"dog", [])

    def test_proof_tampered_raises(self):
        """
        Corrupting a referenced child hash inside a proof branch node breaks the
        hash chain, so the missing real node surfaces as BadTrieProof.
        """
        trie = build({}, FOUR_ENTRY)
        root = trie.root_hash
        proof = [copy.deepcopy(node) for node in trie.get_proof(b"horse")]
        for node in proof:
            if isinstance(node, list) and len(node) == 17:
                for idx in range(16):
                    child = node[idx]
                    if isinstance(child, bytes) and len(child) == 32:
                        node[idx] = b"\x11" * 32
        with pytest.raises(BadTrieProof):
            HexaryTrie.get_from_proof(root, b"horse", proof)


# ===========================================================================
# squash / at_root / pruning-edge
# ===========================================================================
class TestSquashAndSnapshots:
    def test_squash_equivalent_root(self):
        """A trie built inside squash_changes has the same root as a naive build."""
        squashed_db = {}
        trie = HexaryTrie(squashed_db)
        with trie.squash_changes() as scratch:
            for key, value in FOUR_ENTRY:
                scratch[key] = value
        assert trie.root_hash.hex() == FOUR_ENTRY_HEX
        # Values still resolve from the squashed db after the context exits.
        assert trie[b"horse"] == b"stallion"

    def test_squash_compacts_db(self):
        """squash_changes persists strictly fewer db entries than a naive build."""
        naive_db = {}
        build(naive_db, FOUR_ENTRY)

        squashed_db = {}
        trie = HexaryTrie(squashed_db)
        with trie.squash_changes() as scratch:
            for key, value in FOUR_ENTRY:
                scratch[key] = value

        assert len(squashed_db) < len(naive_db)

    def test_at_root_snapshot(self):
        """at_root yields a read-only view of historical state; main is unchanged."""
        trie = HexaryTrie({})
        trie[b"dog"] = b"puppy"
        old_root = trie.root_hash
        trie[b"cat"] = b"meow"

        with trie.at_root(old_root) as snapshot:
            assert snapshot[b"dog"] == b"puppy"
            assert snapshot[b"cat"] == b""  # cat did not exist at old_root

        # Main trie still reflects the newer state.
        assert trie[b"cat"] == b"meow"
        assert trie.root_hash != old_root

    def test_at_root_under_pruning_raises(self):
        """Calling at_root on a pruning trie raises ValidationError."""
        trie = HexaryTrie({}, prune=True)
        with pytest.raises(ValidationError):
            with trie.at_root(trie.root_hash):
                pass

    def test_prune_roundtrip(self):
        """A prune=True trie reaches the same canonical root and resolves all
        values, while storing strictly fewer nodes than a non-pruning trie that
        underwent the same overwrites (orphaned nodes are reclaimed)."""
        # Non-pruning trie: overwrites leave orphaned nodes in the db.
        naive_db = {}
        naive = HexaryTrie(naive_db)
        for key, value in FOUR_ENTRY:
            naive[key] = value
        for tmp in (b"x", b"y", b"puppy"):
            naive[b"dog"] = tmp

        # Pruning trie: identical operations, but orphans are reclaimed.
        pruned_db = {}
        pruned = HexaryTrie(pruned_db, prune=True)
        for key, value in FOUR_ENTRY:
            pruned[key] = value
        for tmp in (b"x", b"y", b"puppy"):
            pruned[b"dog"] = tmp

        assert pruned.root_hash.hex() == FOUR_ENTRY_HEX
        assert naive.root_hash.hex() == FOUR_ENTRY_HEX
        for key, value in FOUR_ENTRY:
            assert pruned[key] == value
        # Pruning reclaimed the orphaned nodes left by the overwrites.
        assert len(pruned_db) < len(naive_db)


# ===========================================================================
# traverse / traverse_from / nodes
# ===========================================================================
class TestTraversal:
    def test_traverse_root_shape(self):
        """
        traverse(()) returns the annotated root node: it equals root_node and
        reports the correct NodeType (comparable to its int value).
        """
        trie = HexaryTrie({})
        trie[b"foo"] = b"bar"
        trie[b"food"] = b"bass"

        root = trie.traverse(())
        assert isinstance(root, HexaryTrieNode)
        assert root == trie.root_node
        # foo/food share a 6-nibble prefix -> root is an extension node.
        assert root.node_type == NodeType.EXTENSION
        assert int(root.node_type) == 2

    def test_traverse_to_leaf(self):
        """
        Traversing to the exact prefix where a leaf begins returns that leaf with
        the correct value, remaining suffix, and node_type==LEAF.
        """
        trie = HexaryTrie({})
        trie[b"foo"] = b"bar"
        trie[b"food"] = b"bass"

        # 'food' nibbles = (6,6,6,15,6,15,6,4); the leaf for 'food' begins after
        # the branch at prefix (6,6,6,15,6,15,6) with the single suffix nibble 4.
        leaf = trie.traverse((6, 6, 6, 0xF, 6, 0xF, 6))
        assert leaf.node_type == NodeType.LEAF
        assert leaf.value == b"bass"
        assert leaf.suffix == (4,)
        assert leaf.sub_segments == ()

    def test_traverse_missing_node(self):
        """Traversing a trie opened at a non-blank root over an empty db raises."""
        source = HexaryTrie({})
        source[b"dog"] = b"puppy"
        root = source.root_hash

        empty = HexaryTrie({}, root_hash=root)
        with pytest.raises(MissingTraversalNode) as exc_info:
            empty.traverse((6,))
        assert exc_info.value.missing_node_hash == root
        assert exc_info.value.nibbles_traversed == ()

    def test_traverse_partial_path(self):
        """
        Traversing one nibble *into* a leaf raises TraversedPartialPath, which
        exposes the diverged leaf node.
        """
        trie = HexaryTrie({})
        trie[b"foo"] = b"bar"
        trie[b"food"] = b"bass"

        with pytest.raises(TraversedPartialPath) as exc_info:
            # one nibble past the leaf start -> partial descent into the leaf
            trie.traverse((6, 6, 6, 0xF, 6, 0xF, 6, 4))

        # The diverged node is the 'food' leaf. Its type and value are
        # well-defined regardless of exactly how the implementation splits the
        # partial step between nibbles_traversed and untraversed_tail (the spec
        # documents the attributes but not that boundary convention).
        err = exc_info.value
        assert err.node.node_type == NodeType.LEAF
        assert err.node.value == b"bass"
        assert isinstance(err.simulated_node, HexaryTrieNode)
        assert err.simulated_node.node_type == NodeType.LEAF
        assert err.simulated_node.value == b"bass"

        # Descending partway into an EXTENSION segment also raises (distinct
        # branch of the same contract): the root extension spans 6 nibbles.
        with pytest.raises(TraversedPartialPath) as ext_info:
            trie.traverse((6,))
        assert ext_info.value.node.node_type == NodeType.EXTENSION

    def test_missing_trie_node_on_get(self):
        """get() on a non-blank root with an empty db raises MissingTrieNode."""
        source = HexaryTrie({})
        source[b"dog"] = b"puppy"
        root = source.root_hash

        empty = HexaryTrie({}, root_hash=root)
        with pytest.raises(MissingTrieNode) as exc_info:
            empty.get(b"dog")
        err = exc_info.value
        assert err.missing_node_hash == root
        assert err.root_hash == root
        assert err.requested_key == b"dog"


# Empty BinaryTrie root == keccak(b'') (CONTRACT §6). Vendored literal anchor.
BLANK_HASH = bytes.fromhex(
    "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"
)


# ---------------------------------------------------------------------------
# BinaryTrie (scenarios 28-32)
# ---------------------------------------------------------------------------


def test_binary_set_get_exists():
    """28: set/get/exists round-trip; absent get() is None (not b''); `in`."""
    trie = BinaryTrie(db={})

    # Absent key before any insert.
    assert trie.get(b"missing") is None
    assert trie.exists(b"missing") is False
    assert (b"missing" in trie) is False

    trie.set(b"\x12\x34\x56\x78", b"78")
    trie.set(b"\x12\x34\x56\x79", b"79")

    assert trie.get(b"\x12\x34\x56\x78") == b"78"
    assert trie.get(b"\x12\x34\x56\x79") == b"79"
    assert trie.exists(b"\x12\x34\x56\x78") is True
    assert (b"\x12\x34\x56\x78" in trie) is True

    # A sibling/absent key still returns the None sentinel, not b''.
    assert trie.get(b"\x12\x34\x56\x7a") is None
    assert trie.exists(b"\x12\x34\x56\x7a") is False

    # Dict-API sugar agrees with the explicit methods.
    assert trie[b"\x12\x34\x56\x78"] == b"78"
    trie[b"\xab\xcd\xef\x00"] = b"new"
    assert trie.get(b"\xab\xcd\xef\x00") == b"new"


def test_binary_order_independence():
    """29: empty root == BLANK_HASH; shuffled insert orders -> equal root."""
    empty = BinaryTrie(db={})
    assert empty.root_hash == BLANK_HASH

    pairs = [
        (b"\x00\x01", b"a"),
        (b"\x00\x02", b"b"),
        (b"\xff\x00", b"c"),
        (b"\x10\x20", b"d"),
        (b"\x10\x21", b"e"),
    ]

    trie1 = BinaryTrie(db={})
    for k, v in pairs:
        trie1.set(k, v)

    trie2 = BinaryTrie(db={})
    for k, v in reversed(pairs):
        trie2.set(k, v)

    # Order-independent root over a fixed key/value set.
    assert trie1.root_hash == trie2.root_hash
    # A non-empty trie's root must differ from the blank constant.
    assert trie1.root_hash != BLANK_HASH

    # Deleting every key returns the root to the blank constant.
    for k, _ in pairs:
        trie1.delete(k)
    assert trie1.root_hash == BLANK_HASH


def test_binary_update_value():
    """30: re-setting the SAME value leaves root unchanged; a NEW value changes it."""
    trie = BinaryTrie(db={})
    keys = [b"\x00\x00", b"\x00\x01", b"\xff\xff", b"\x80\x00"]
    for k in keys:
        trie.set(k, b"old")

    current_root = trie.root_hash
    for k in keys:
        # Setting the identical value is a no-op on the root.
        trie.set(k, b"old")
        assert trie.root_hash == current_root

        # Setting a different value must change the root and the stored value.
        trie.set(k, b"new")
        assert trie.root_hash != current_root
        assert trie.get(k) == b"new"
        current_root = trie.root_hash


def test_binary_delete_subtrie():
    """31: delete_subtrie removes a whole subtrie; non-matching prefix is a no-op;
    a key that over-runs a leaf raises NodeOverrideError."""
    # Deleting the common prefix of both keys empties the trie.
    trie = BinaryTrie(db={})
    trie.set(b"\x12\x34\x56\x78", b"78")
    trie.set(b"\x12\x34\x56\x79", b"79")
    assert trie.get(b"\x12\x34\x56\x78") == b"78"
    assert trie.get(b"\x12\x34\x56\x79") == b"79"

    trie.delete_subtrie(b"\x12\x34\x56")
    assert trie.get(b"\x12\x34\x56\x78") is None
    assert trie.get(b"\x12\x34\x56\x79") is None
    assert trie.root_hash == BLANK_HASH

    # A prefix that matches no subtrie is a no-op (root unchanged, keys intact).
    trie2 = BinaryTrie(db={})
    trie2.set(b"\x12\x34\x56\x78", b"78")
    trie2.set(b"\x12\x34\x56\x79", b"79")
    root_before = trie2.root_hash
    trie2.delete_subtrie(b"\x12\x34\x57")
    assert trie2.root_hash == root_before
    assert trie2.get(b"\x12\x34\x56\x78") == b"78"
    assert trie2.get(b"\x12\x34\x56\x79") == b"79"

    # A key that extends past an existing leaf raises NodeOverrideError.
    trie3 = BinaryTrie(db={})
    trie3.set(b"\x12\x34\x56\x78", b"78")
    trie3.set(b"\x12\x34\x56\x79", b"79")
    with pytest.raises(NodeOverrideError):
        trie3.delete_subtrie(b"\x12\x34\x56\x78\x9a")


def test_binary_prefix_conflict_raises():
    """32: delete/set of a key that over-runs an existing leaf -> NodeOverrideError."""
    trie = BinaryTrie(db={})
    trie.set(b"\x12\x34\x56\x78", b"78")
    trie.set(b"\x12\x34\x56\x79", b"79")

    # A key extending past a stored leaf is not present...
    assert trie.get(b"\x12\x34\x56\x78\x9a") is None
    # ...and deleting it raises NodeOverrideError.
    with pytest.raises(NodeOverrideError):
        trie.delete(b"\x12\x34\x56\x78\x9a")
    with pytest.raises(NodeOverrideError):
        trie.delete(b"\x12\x34\x56\x79\xab")

    # Likewise, SETTING a value at a key that over-runs a leaf raises.
    with pytest.raises(NodeOverrideError):
        trie.set(b"\x12\x34\x56\x78\x9a", b"deep")


# ---------------------------------------------------------------------------
# SparseMerkleTree (scenarios 33-35)
# ---------------------------------------------------------------------------


def test_smt_set_get_delete():
    """33: set->get; exists; delete restores empty root & exists False;
    a missing key raises KeyError."""
    smt = SparseMerkleTree(key_size=4, default=b"")
    empty_root = smt.root_hash

    key = b"\x00\x01\x02\x03"
    value = b"hello world"

    # Nothing set yet: not present, and get() raises KeyError.
    assert smt.exists(key) is False
    with pytest.raises(KeyError):
        smt.get(key)

    smt.set(key, value)
    assert smt.get(key) == value
    assert smt.exists(key) is True
    # Adding data changes the root away from empty.
    assert smt.root_hash != empty_root

    # Dict sugar agrees.
    assert smt[key] == value
    assert (key in smt) is True

    # Deleting restores the empty root and clears existence.
    smt.delete(key)
    assert smt.exists(key) is False
    assert smt.root_hash == empty_root
    with pytest.raises(KeyError):
        smt.get(key)


def test_smt_calc_root_invariant():
    """34: smt.root_hash == calc_root(key, value, smt.branch(key)) after a set."""
    smt = SparseMerkleTree(key_size=2, default=b"")

    key = b"\x12\x34"
    value = b"the-value"
    updated = smt.set(key, value)

    # set returns a tuple of the node hashes updated along the path. The exact
    # count is an implementation detail (whether the leaf/root endpoints are
    # included), so we don't pin it here.
    assert isinstance(updated, tuple)
    assert len(updated) >= 1

    # The core relational invariant: the live root is reproducible from the
    # key, the value, and the sibling branch.
    branch = smt.branch(key)
    assert smt.root_hash == calc_root(key, value, branch)

    # A second independent key must keep the invariant for BOTH keys.
    key2 = b"\xab\xcd"
    value2 = b"second"
    smt.set(key2, value2)
    assert smt.root_hash == calc_root(key2, value2, smt.branch(key2))
    assert smt.root_hash == calc_root(key, value, smt.branch(key))


def test_smt_keysize_validation():
    """35: key_size outside [1, 32] raises ValidationError; the bounds are valid."""
    with pytest.raises(ValidationError):
        SparseMerkleTree(key_size=0)
    with pytest.raises(ValidationError):
        SparseMerkleTree(key_size=33)

    # Boundary values are accepted.
    assert SparseMerkleTree(key_size=1).depth == 8
    assert SparseMerkleTree(key_size=32).depth == 32 * 8


# ---------------------------------------------------------------------------
# NodeIterator (scenarios 36-38)
# ---------------------------------------------------------------------------


def _build_trie(keys):
    trie = HexaryTrie(db={})
    for k in keys:
        trie[k] = k
    return trie


def test_iter_keys_sorted():
    """36: keys()/items()/values() are emitted in ascending key order, and chained
    next() descends/ascends correctly across a shared-prefix (extension+branch)
    structure."""
    keys = [b"wallace", b"cat", b"doge", b"dog", b"do"]
    trie = _build_trie(keys)
    it = NodeIterator(trie)

    expected_keys = sorted(keys)
    assert list(it.keys()) == expected_keys
    assert list(it.items()) == [(k, k) for k in expected_keys]
    assert list(it.values()) == expected_keys

    # Walking with chained next() over the shared do/dog/doge prefixes (which
    # form an extension->branch-with-value layout) reproduces the same order.
    walk = []
    point = b""
    while True:
        nxt = it.next(point)
        if nxt is None:
            break
        walk.append(nxt)
        point = nxt
    assert walk == expected_keys


def test_iter_next_prev_fixture():
    """37: drive next(point) across the canonical trietestnextprev.json:basic cases.
    Walks left->right; empty-string `next` means None (past the end)."""
    # Inlined from TrieTests/trietestnextprev.json:basic.
    fixture_in = ["cat", "doge", "wallace"]
    # (point, next) pairs; "" in the next column means None.
    cases = [
        ("", "cat"),
        ("bobo", "cat"),
        ("c", "cat"),
        ("car", "cat"),
        ("cat", "doge"),
        ("catering", "doge"),
        ("d", "doge"),
        ("doge", "wallace"),
        ("dogerton", "wallace"),
        ("w", "wallace"),
        ("wallace", ""),
        ("wallace123", ""),
    ]

    trie = HexaryTrie(db={})
    for k in fixture_in:
        kb = k.encode("utf-8")
        trie[kb] = kb

    it = NodeIterator(trie)
    for point, nxt in cases:
        expected = None if nxt == "" else nxt.encode("utf-8")
        assert it.next(point.encode("utf-8")) == expected

    # next(None) returns the first key.
    assert it.next() == b"cat"


def test_iter_missing_node_raises():
    """38: deleting an interior node from the db mid-iteration -> MissingTraversalNode."""
    # Hold our own reference to the node store we pass in, so we can remove a
    # node without relying on any particular internal attribute name.
    db = {}
    trie = HexaryTrie(db)
    trie[b"cat"] = b"cat"
    trie[b"dog"] = b"dog"
    trie[b"bird"] = b"bird"

    # The root is an extension node; remove the (hashed) node it references.
    node_to_remove = trie.root_node.raw[1]
    db.pop(node_to_remove)

    iterator = NodeIterator(trie)
    with pytest.raises(MissingTraversalNode):
        key = b""
        while key is not None:
            key = iterator.next(key)


# ---------------------------------------------------------------------------
# Iteration 1 — complex feature / edge-case E2E tests
# ---------------------------------------------------------------------------


def test_traverse_branch_with_value():
    """39: traversing exactly to a branch node that also carries a value returns
    that BRANCH node (with its value), not a TraversedPartialPath."""
    trie = HexaryTrie({})
    for key, value in FOUR_ENTRY:
        trie[key] = value
    # 'do' (nibbles 6,4,6,15) terminates on a branch node that also holds a value.
    node = trie.traverse((6, 4, 6, 0xF))
    assert node.node_type == NodeType.BRANCH
    assert node.value == b"verb"


def test_at_root_read_api():
    """40: an at_root snapshot supports the full read-only API (get_proof,
    traverse, root_node), not just get/exists."""
    trie = HexaryTrie({})
    trie[b"dog"] = b"puppy"
    old_root = trie.root_hash
    trie[b"cat"] = b"meow"

    with trie.at_root(old_root) as snapshot:
        # Proof generated through the historical snapshot round-trips under old_root.
        proof = snapshot.get_proof(b"dog")
        assert HexaryTrie.get_from_proof(old_root, b"dog", proof) == b"puppy"
        # Node-structure introspection works against the historical root.
        assert snapshot.traverse(()).node_type == NodeType.LEAF
        assert snapshot.root_node.node_type == NodeType.LEAF
        # cat did not exist at old_root.
        assert snapshot.get(b"cat") == b""


def test_smt_nonblank_default():
    """41: with a non-blank default, never-set keys read as present (get returns
    the default, exists is True); with a blank default they raise KeyError."""
    smt = SparseMerkleTree(key_size=1, default=b"\x00")
    assert smt.get(b"\x05") == b"\x00"
    assert smt.exists(b"\x05") is True
    # A real value still overrides the default and reads back.
    smt.set(b"\x05", b"\x07")
    assert smt.get(b"\x05") == b"\x07"

    blank = SparseMerkleTree(key_size=1, default=b"")
    assert blank.exists(b"\x05") is False
    with pytest.raises(KeyError):
        blank.get(b"\x05")


def test_smt_proof_tracking():
    """42: SparseMerkleProof stays synchronized through in-place update() as the
    tree is mutated elsewhere, without re-querying the tree."""
    smt = SparseMerkleTree(key_size=2, default=b"")
    tracked = b"\x12\x34"
    smt.set(tracked, b"valueA")
    proof = SparseMerkleProof(tracked, b"valueA", smt.branch(tracked))
    assert proof.root_hash == smt.root_hash

    # Each remote update is merged in place (update returns None) and keeps the
    # tracked proof consistent with the live tree.
    for other, value in [(b"\xab\xcd", b"vB"), (b"\x12\x99", b"vC"), (b"\x00\x00", b"vD")]:
        node_updates = smt.set(other, value)
        assert proof.update(other, value, node_updates) is None
        assert proof.root_hash == smt.root_hash
        assert proof.branch == smt.branch(tracked)

    # Updating the tracked key itself updates the tracked value.
    proof.update(tracked, b"newA", smt.set(tracked, b"newA"))
    assert proof.value == b"newA"
    assert proof.root_hash == smt.root_hash


def test_smt_many_keys_delete_subset():
    """43: on a populated SMT, deleting a subset leaves every remaining key
    consistent (calc_root invariant + exists) and the deleted keys absent."""
    smt = SparseMerkleTree(key_size=2, default=b"")
    keys = [bytes([i, (i * 7) % 256]) for i in range(12)]
    for i, k in enumerate(keys):
        smt.set(k, b"v%d" % i)
    for k in keys[:5]:
        smt.delete(k)

    for k in keys[5:]:
        assert smt.exists(k) is True
        assert smt.root_hash == calc_root(k, smt.get(k), smt.branch(k))
    for k in keys[:5]:
        assert smt.exists(k) is False


def test_proof_wrong_root_raises():
    """44: get_from_proof against a root the proof does not authenticate raises
    BadTrieProof."""
    trie = HexaryTrie({})
    for key, value in FOUR_ENTRY:
        trie[key] = value
    proof = trie.get_proof(b"dog")
    with pytest.raises(BadTrieProof):
        HexaryTrie.get_from_proof(b"\x00" * 32, b"dog", proof)


# ---------------------------------------------------------------------------
# Iteration 2 — distinct edge-case contracts that break near-correct impls
# ---------------------------------------------------------------------------


def test_smt_calc_root_validates_branch_length():
    """45: calc_root rejects a branch whose length != key_size*8."""
    smt = SparseMerkleTree(key_size=2, default=b"")
    smt.set(b"\x12\x34", b"A")
    branch = smt.branch(b"\x12\x34")
    with pytest.raises(ValidationError):
        calc_root(b"\x12\x34", b"A", tuple(branch)[:8])  # too short
    with pytest.raises(ValidationError):
        calc_root(b"\x12\x34", b"A", tuple(branch) + (b"\x00" * 32,))  # too long


def test_smt_branch_missing_key_raises():
    """46: branch() raises KeyError for an unset key (blank default); with a
    non-blank default it does not raise."""
    smt = SparseMerkleTree(key_size=2, default=b"")
    smt.set(b"\x12\x34", b"A")
    with pytest.raises(KeyError):
        smt.branch(b"\x00\x00")

    nonblank = SparseMerkleTree(key_size=1, default=b"\x00")
    # No exception for a never-set key when the default is non-blank.
    assert len(nonblank.branch(b"\x05")) == nonblank.depth


def test_binary_delete_absent_is_noop():
    """47: deleting an absent (non-conflicting) key from a BinaryTrie is a no-op;
    over-running an existing leaf is still a NodeOverrideError (contrast)."""
    trie = BinaryTrie(db={})
    trie.set(b"\x10\x00", b"a")
    trie.set(b"\x10\x01", b"b")
    root_before = trie.root_hash

    # Keys that diverge from everything stored -> simply absent -> no-op.
    trie.delete(b"\x20\x00")   # diverges at the first bit
    trie.delete(b"\x10\x02")   # absent sibling
    assert trie.root_hash == root_before
    assert trie.get(b"\x10\x00") == b"a"
    assert trie.get(b"\x10\x01") == b"b"

    # But a key that over-runs a stored leaf is a prefix conflict -> raises.
    with pytest.raises(NodeOverrideError):
        trie.delete(b"\x10\x00\x99")


def test_smt_proof_update_insufficient_raises():
    """48: SparseMerkleProof.update raises ValidationError when node_updates is
    too short to reach the branch point (deep divergence)."""
    smt = SparseMerkleTree(key_size=2, default=b"")
    tracked = b"\x12\x34"
    smt.set(tracked, b"A")
    proof = SparseMerkleProof(tracked, b"A", smt.branch(tracked))

    other = b"\x12\x35"  # differs from tracked only in the final bit (deepest branch point)
    node_updates = smt.set(other, b"B")
    with pytest.raises(ValidationError):
        proof.update(other, b"B", node_updates[:1])  # far too short for a last-bit divergence


# ---------------------------------------------------------------------------
# Iteration 3 — additional canonical-root fixtures (structurally diverse;
# stress Hex-Prefix/RLP encoding across more node arrangements)
# ---------------------------------------------------------------------------

_JEFF = [
    ("0x0000000000000000000000000000000000000000000000000000000000000045", "0x22b224a1420a802ab51d326e29fa98e34c4f24ea"),
    ("0x0000000000000000000000000000000000000000000000000000000000000046", "0x67706c2076330000000000000000000000000000000000000000000000000000"),
    ("0x0000000000000000000000000000000000000000000000000000001234567890", "0x697c7b8c961b56f675d570498424ac8de1a918f6"),
    ("0x000000000000000000000000697c7b8c961b56f675d570498424ac8de1a918f6", "0x1234567890"),
    ("0x0000000000000000000000007ef9e639e2733cb34e4dfc576d4b23f72db776b2", "0x4655474156000000000000000000000000000000000000000000000000000000"),
    ("0x000000000000000000000000ec4f34c97e43fbb2816cfd95e388353c7181dab1", "0x4e616d6552656700000000000000000000000000000000000000000000000000"),
    ("0x4655474156000000000000000000000000000000000000000000000000000000", "0x7ef9e639e2733cb34e4dfc576d4b23f72db776b2"),
    ("0x4e616d6552656700000000000000000000000000000000000000000000000000", "0xec4f34c97e43fbb2816cfd95e388353c7181dab1"),
    ("0x0000000000000000000000000000000000000000000000000000001234567890", None),
    ("0x000000000000000000000000697c7b8c961b56f675d570498424ac8de1a918f6", "0x6f6f6f6820736f2067726561742c207265616c6c6c793f000000000000000000"),
    ("0x6f6f6f6820736f2067726561742c207265616c6c6c793f000000000000000000", "0x697c7b8c961b56f675d570498424ac8de1a918f6"),
]
_JEFF_ROOT = "9f6221ebb8efe7cff60a716ecb886e67dd042014be444669f0159d8e68b42100"

_BRANCHING_ADDRS = [
    "0x04110d816c380812a427968ece99b1c963dfbce6", "0x095e7baea6a6c7c4c2dfeb977efac326af552d87",
    "0x0a517d755cebbf66312b30fff713666a9cb917e0", "0x24dd378f51adc67a50e339e8031fe9bd4aafab36",
    "0x293f982d000532a7861ab122bdc4bbfd26bf9030", "0x2cf5732f017b0cf1b1f13a1478e10239716bf6b5",
    "0x31c640b92c21a1f1465c91070b4b3b4d6854195f", "0x37f998764813b136ddf5a754f34063fd03065e36",
    "0x37fa399a749c121f8a15ce77e3d9f9bec8020d7a", "0x4f36659fa632310b6ec438dea4085b522a2dd077",
    "0x62c01474f089b07dae603491675dc5b5748f7049", "0x729af7294be595a0efd7d891c9e51f89c07950c7",
    "0x83e3e5a16d3b696a0314b30b2534804dd5e11197", "0x8703df2417e0d7c59d063caa9583cb10a4d20532",
    "0x8dffcd74e5b5923512916c6a64b502689cfa65e1", "0x95a4d7cccb5204733874fa87285a176fe1e9e240",
    "0x99b2fcba8120bedd048fe79f5262a6690ed38c39", "0xa4202b8b8afd5354e3e40a219bdc17f6001bf2cf",
    "0xa94f5374fce5edbc8e2a8697c15331677e6ebf0b", "0xa9647f4a0a14042d91dc33c0328030a7157c93ae",
    "0xaa6cffe5185732689c18f37a7f86170cb7304c2a", "0xaae4a2e3c51c04606dcb3723456e58f3ed214f45",
    "0xc37a43e940dfb5baf581a0b82b351d48305fc885", "0xd2571607e241ecf590ed94b12d87c94babe36db6",
    "0xf735071cbee190d76b704ce68384fc21e389fbe7",
]


def _canon_root(pairs):
    """Build a trie from (token, token|None) fixture pairs; None means delete."""
    trie = HexaryTrie({})
    for k, v in pairs:
        trie[fixture_bytes(k)] = b"" if v is None else fixture_bytes(v)
    return trie


def test_canonical_smallvalues_root():
    """49: small values are embedded inline (<32B), stressing the inline-node
    rule. {be:e, dog:puppy, bed:d} reproduces the canonical smallValues root."""
    trie = _canon_root([("be", "e"), ("dog", "puppy"), ("bed", "d")])
    assert trie.root_hash.hex() == (
        "3f67c7a47520f79faa29255d2d3c084a7a6df0453116ed7232ff10277a8be68b"
    )


def test_canonical_testy_root():
    """50: 'te' is a strict prefix of 'test' (extension -> branch-with-value)."""
    trie = _canon_root([("test", "test"), ("te", "testy")])
    assert trie.root_hash.hex() == (
        "8452568af70d8d140f58d941338542f645fcca50094b20f3c3d8c3df49337928"
    )


def test_canonical_single_long_value_root():
    """51: a single 50-byte value forces a hashed (not inline) leaf."""
    trie = _canon_root([("A", "a" * 50)])
    assert trie.root_hash.hex() == (
        "d23786fb4a010da3ce639d66d5e904a11dbc02746d1ce25029e53290cabf28ab"
    )


def test_canonical_jeff_root():
    """52: the 11-entry hex-keyed 'jeff' set (deep nodes + an interleaved delete)
    reproduces its canonical Ethereum root."""
    trie = _canon_root(_JEFF)
    assert trie.root_hash.hex() == _JEFF_ROOT


def test_canonical_branching_insert_delete_to_blank():
    """53: insert 25 distinct 20-byte address keys then delete them all; the wide
    branch structure must collapse exactly back to the blank-node root."""
    trie = HexaryTrie({})
    for addr in _BRANCHING_ADDRS:
        trie[fixture_bytes(addr)] = b"something"
    # All present.
    assert all(trie[fixture_bytes(a)] == b"something" for a in _BRANCHING_ADDRS)
    for addr in _BRANCHING_ADDRS:
        del trie[fixture_bytes(addr)]
    assert trie.root_hash.hex() == BLANK_NODE_HASH_HEX
