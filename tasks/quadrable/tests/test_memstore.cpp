// quadrable WRG task -- gtest suite, module: memstore.
// Exercises the RAM-backed shadow storage layer. MemStore lets the caller
// stash transient nodes without persisting them to LMDB: useful for tree
// reconstruction during sync (see test_sync.cpp) and for building ephemeral
// forks of an LMDB-backed head.
//
// Tests:
//   MemStore.WithMemStoreScopedIsolation
//   MemStore.MemStoreForkFromLmdbHead
//   MemStore.AddMemStoreEnablesMemStoreWrites

#include "quadrable_fixture.h"

#include <string>

using quadrable_test::QuadrableFixture;

class MemStore : public QuadrableFixture {};


TEST_F(MemStore, WithMemStoreScopedIsolation) {
    // Inside `db.withMemStore(m, cb)`, writes go to `m`, not to LMDB.
    // Node ids assigned during the memstore scope are >= firstMemStoreNodeId,
    // giving the caller a way to observe that the write path went to RAM.
    auto txn = beginTxn();

    quadrable::MemStore m;

    db.withMemStore(m, [&]() {
        db.checkout();              // detached empty
        db.writeToMemStore = true;

        db.change().put("A", "res1").put("B", "res2").apply(txn);

        // Head nodeId should be a memstore id (above the boundary).
        EXPECT_GE(db.getHeadNodeId(txn), quadrable::firstMemStoreNodeId);

        // Reads see the memstore-resident values.
        std::string_view val;
        ASSERT_TRUE(db.get(txn, "A", val));
        EXPECT_EQ(val, "res1");
        ASSERT_TRUE(db.get(txn, "B", val));
        EXPECT_EQ(val, "res2");

        // Stats reflect the two leaves inserted into the memstore tree.
        auto s = db.stats(txn);
        EXPECT_EQ(s.numLeafNodes, 2u);
    });

    db.writeToMemStore = false;

    // After the memstore scope ends, the LMDB master head is untouched.
    db.checkout("master");
    EXPECT_EQ(db.root(txn), quadrable::Key::null().str());

    txn.commit();
}


TEST_F(MemStore, MemStoreForkFromLmdbHead) {
    // A memstore scope can start by checking out an existing LMDB-backed
    // named head. Attempting to WRITE directly to that head from memstore
    // mode throws (an LMDB-attached head can't accept memstore nodeIds).
    // fork(txn) detaches, after which writes flow to memstore correctly.
    auto txn = beginTxn();

    // Seed an LMDB-backed named head.
    db.checkout("base");
    db.change().put("A", "res1").put("B", "res2").apply(txn);
    uint64_t base_head_id = db.getHeadNodeId(txn);
    std::string base_root = db.root(txn);

    quadrable::MemStore m;

    db.withMemStore(m, [&]() {
        db.checkout("base");         // load the LMDB-backed head
        db.writeToMemStore = true;

        // Attempting to persist a memstore write into the LMDB "base" head
        // must throw -- the storage boundary is enforced.
        EXPECT_THROW(db.change().put("C", "res3").apply(txn), std::runtime_error);

        // Detach via fork, then the same put goes to memstore.
        db.fork(txn);
        db.change().put("C", "res3").apply(txn);

        EXPECT_GE(db.getHeadNodeId(txn), quadrable::firstMemStoreNodeId);

        // All three keys should be readable (A/B from LMDB base, C from memstore).
        std::string_view val;
        ASSERT_TRUE(db.get(txn, "A", val));
        EXPECT_EQ(val, "res1");
        ASSERT_TRUE(db.get(txn, "B", val));
        EXPECT_EQ(val, "res2");
        ASSERT_TRUE(db.get(txn, "C", val));
        EXPECT_EQ(val, "res3");
    });

    db.writeToMemStore = false;

    // Back to LMDB-only: the memstore-only write of "C" is invisible.
    db.checkout("base");
    EXPECT_EQ(db.root(txn), base_root);
    EXPECT_EQ(db.getHeadNodeId(txn), base_head_id);
    std::string_view val;
    EXPECT_FALSE(db.get(txn, "C", val));
    ASSERT_TRUE(db.get(txn, "A", val));
    EXPECT_EQ(val, "res1");

    txn.commit();
}


TEST_F(MemStore, AddMemStoreEnablesMemStoreWrites) {
    // addMemStore()/removeMemStore() is the long-lived-attachment variant of
    // withMemStore. Between add and remove, memstore-mode writes succeed and
    // land in the attached MemStore.
    auto txn = beginTxn();

    db.addMemStore();
    db.writeToMemStore = true;

    db.checkout();  // detached empty
    db.change().put("k1", "v1").put("k2", "v2").put("k3", "v3").apply(txn);

    // Head is in memstore-id range.
    EXPECT_GE(db.getHeadNodeId(txn), quadrable::firstMemStoreNodeId);

    // Reads succeed while memstore is attached.
    std::string_view val;
    ASSERT_TRUE(db.get(txn, "k1", val));
    EXPECT_EQ(val, "v1");
    ASSERT_TRUE(db.get(txn, "k2", val));
    EXPECT_EQ(val, "v2");
    ASSERT_TRUE(db.get(txn, "k3", val));
    EXPECT_EQ(val, "v3");

    auto s = db.stats(txn);
    EXPECT_EQ(s.numLeafNodes, 3u);

    db.writeToMemStore = false;
    db.removeMemStore();

    // Trying to remove a MemStore that isn't attached must throw.
    EXPECT_THROW(db.removeMemStore(), std::runtime_error);

    txn.commit();
}
