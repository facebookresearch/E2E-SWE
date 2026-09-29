// quadrable WRG task -- gtest suite, module: basic_kv.
// Exercises the core key-value contracts of the persistent merkle tree:
// put/get, delete + sibling-bubbling, batch semantics, deterministic root
// under insert-order permutation, and the multi-key get() convenience.
//
// Tests:
//   BasicKV.PutGetRoundtripAndStats
//   BasicKV.EmptyKeyThrowsOnPutAndDel
//   BasicKV.DeterministicRootAcrossInsertOrder
//   BasicKV.GetMultiPopulatesExistsAndVal
//   BasicKV.DelBubblesToLoneSurvivor

#include "quadrable_fixture.h"

#include <set>
#include <string>

using quadrable_test::QuadrableFixture;

class BasicKV : public QuadrableFixture {};


TEST_F(BasicKV, PutGetRoundtripAndStats) {
    auto txn = beginTxn();

    // Empty tree contract: root hash equals 32 null bytes (Key::null()).
    EXPECT_EQ(db.root(txn), quadrable::Key::null().str());
    {
        auto s = db.stats(txn);
        EXPECT_EQ(s.numLeafNodes, 0u);
        EXPECT_EQ(s.numBranchNodes, 0u);
        EXPECT_EQ(s.numNodes, 0u);
    }

    // Insert a single leaf, root should change away from null.
    db.change().put("hello", "world").apply(txn);
    EXPECT_NE(db.root(txn), quadrable::Key::null().str());

    std::string_view val;
    ASSERT_TRUE(db.get(txn, "hello", val));
    EXPECT_EQ(val, "world");

    // Missing key: get() returns false, val untouched.
    EXPECT_FALSE(db.get(txn, "missing", val));

    // stats() reflects the single leaf, one branchless tree.
    auto s = db.stats(txn);
    EXPECT_EQ(s.numLeafNodes, 1u);
    EXPECT_EQ(s.numBranchNodes, 0u);

    // Deleting the sole key returns root to null (empty).
    db.change().del("hello").apply(txn);
    EXPECT_EQ(db.root(txn), quadrable::Key::null().str());

    auto s2 = db.stats(txn);
    EXPECT_EQ(s2.numLeafNodes, 0u);

    txn.commit();
}


TEST_F(BasicKV, EmptyKeyThrowsOnPutAndDel) {
    auto txn = beginTxn();

    // Zero-length keys are explicitly rejected by the update pipeline.
    EXPECT_THROW(db.change().put("", "value").apply(txn), std::runtime_error);
    EXPECT_THROW(db.change().del("").apply(txn), std::runtime_error);

    // The rejection happens on the change() side, so the tree stays untouched.
    EXPECT_EQ(db.root(txn), quadrable::Key::null().str());

    txn.commit();
}


TEST_F(BasicKV, DeterministicRootAcrossInsertOrder) {
    // The merkle tree's root hash is a pure function of the {key -> value}
    // map, independent of the order in which keys were inserted, whether
    // they were applied as one batch or many one-at-a-time updates.
    auto txn = beginTxn();

    // Reference: insert 200 kv pairs in a single batch (natural order).
    {
        auto c = db.change();
        for (int i = 0; i < 200; i++) {
            std::string s = std::to_string(i);
            c.put(s, s + "-val");
        }
        c.apply(txn);
    }
    std::string ref_root = db.root(txn);
    EXPECT_NE(ref_root, quadrable::Key::null().str());

    auto ref_stats = db.stats(txn);
    EXPECT_EQ(ref_stats.numLeafNodes, 200u);

    // Reset to empty tree via checkout() (detached, empty).
    db.checkout();

    // Same set, but each key applied one-at-a-time in reverse order.
    for (int i = 199; i >= 0; i--) {
        std::string s = std::to_string(i);
        db.change().put(s, s + "-val").apply(txn);
    }
    EXPECT_EQ(db.root(txn), ref_root);
    EXPECT_EQ(db.stats(txn).numLeafNodes, 200u);

    // Now try a wildly different order: hash-of-index scramble.
    db.checkout();
    std::vector<int> shuffled(200);
    for (int i = 0; i < 200; i++) shuffled[i] = i;
    // Deterministic pseudo-shuffle: swap i with (i * 1103515245 + 12345) % 200.
    for (int i = 0; i < 200; i++) {
        int j = static_cast<int>((static_cast<unsigned>(i) * 1103515245u + 12345u) % 200u);
        std::swap(shuffled[i], shuffled[j]);
    }
    for (int i : shuffled) {
        std::string s = std::to_string(i);
        db.change().put(s, s + "-val").apply(txn);
    }
    EXPECT_EQ(db.root(txn), ref_root);

    txn.commit();
}


TEST_F(BasicKV, GetMultiPopulatesExistsAndVal) {
    // The set-of-string overload of get() returns a `GetMultiQuery` map
    // populated with per-key {exists, val, nodeId} tuples.
    auto txn = beginTxn();

    auto c = db.change();
    for (int i = 0; i < 100; i++) {
        std::string s = std::to_string(i);
        c.put(s, "N=" + s);
    }
    c.apply(txn);

    std::set<std::string> keys{"5", "17", "42", "99", "not-in-tree"};
    auto query = db.get(txn, keys);

    // Present keys carry their exact stored value.
    ASSERT_TRUE(query.count("5"));
    EXPECT_TRUE(query["5"].exists);
    EXPECT_EQ(query["5"].val, "N=5");

    ASSERT_TRUE(query.count("17"));
    EXPECT_TRUE(query["17"].exists);
    EXPECT_EQ(query["17"].val, "N=17");

    ASSERT_TRUE(query.count("42"));
    EXPECT_TRUE(query["42"].exists);
    EXPECT_EQ(query["42"].val, "N=42");

    ASSERT_TRUE(query.count("99"));
    EXPECT_TRUE(query["99"].exists);
    EXPECT_EQ(query["99"].val, "N=99");

    // Missing key: exists=false and val is empty/default.
    ASSERT_TRUE(query.count("not-in-tree"));
    EXPECT_FALSE(query["not-in-tree"].exists);

    // Single-value get() should still work and give the same value.
    std::string_view sv_val;
    ASSERT_TRUE(db.get(txn, "42", sv_val));
    EXPECT_EQ(sv_val, "N=42");

    txn.commit();
}


TEST_F(BasicKV, DelBubblesToLoneSurvivor) {
    // When one of two sibling leaves is deleted, the survivor bubbles up so
    // the resulting tree is byte-identical to a tree that only ever contained
    // the survivor. This is the canonical merkle-tree cleanliness property
    // that makes the root hash a canonical function of the current key set.
    auto txn = beginTxn();

    // Reference tree: only "b" was ever inserted.
    db.change().put("b", "2").apply(txn);
    std::string ref_root = db.root(txn);

    // Rebuild in a fresh detached head: insert "a" AND "b", then delete "a".
    db.checkout();
    db.change().put("a", "1").put("b", "2").apply(txn);
    EXPECT_NE(db.root(txn), ref_root);  // sanity: two-leaf tree has a different root.

    db.change().del("a").apply(txn);

    // After the deletion, root must match the "b only" reference tree.
    EXPECT_EQ(db.root(txn), ref_root);

    // Also verify the surviving leaf is still readable via get().
    std::string_view val;
    ASSERT_TRUE(db.get(txn, "b", val));
    EXPECT_EQ(val, "2");
    EXPECT_FALSE(db.get(txn, "a", val));

    // Deleting a non-existent key on an empty tree is a no-op (does not throw).
    db.checkout();
    db.change().del("nothing-here").apply(txn);
    EXPECT_EQ(db.root(txn), quadrable::Key::null().str());

    txn.commit();
}
