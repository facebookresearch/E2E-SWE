// quadrable WRG task -- gtest suite, module: heads.
// Exercises the version-control layer: named head switching, detached-head
// mode, forking a head into a new detached branch, and re-entering an older
// state by checkout(nodeId).
//
// Tests:
//   Heads.NamedCheckoutIsolatesState
//   Heads.ForkDetachesAndBranches
//   Heads.CheckoutByNodeIdRestoresOldTree

#include "quadrable_fixture.h"

using quadrable_test::QuadrableFixture;

class Heads : public QuadrableFixture {};


TEST_F(Heads, NamedCheckoutIsolatesState) {
    // Two named heads share the same underlying node storage but each keeps
    // its own root node id. Puts on one head do not affect the other.
    auto txn = beginTxn();

    // Default head is "master". Put a key there.
    db.change().put("shared", "v-master").apply(txn);
    std::string master_root = db.root(txn);
    EXPECT_NE(master_root, quadrable::Key::null().str());

    // Switch to a named head "feature" -- initially empty.
    db.checkout("feature");
    EXPECT_EQ(db.root(txn), quadrable::Key::null().str());

    // Put a different value under the same key on "feature".
    db.change().put("shared", "v-feature").apply(txn);
    std::string feature_root = db.root(txn);
    EXPECT_NE(feature_root, master_root);

    // Switch back to "master" -- state is preserved.
    db.checkout("master");
    EXPECT_EQ(db.root(txn), master_root);
    std::string_view val;
    ASSERT_TRUE(db.get(txn, "shared", val));
    EXPECT_EQ(val, "v-master");

    // And back to feature -- also preserved.
    db.checkout("feature");
    EXPECT_EQ(db.root(txn), feature_root);
    ASSERT_TRUE(db.get(txn, "shared", val));
    EXPECT_EQ(val, "v-feature");

    txn.commit();
}


TEST_F(Heads, ForkDetachesAndBranches) {
    // fork(txn) snapshots the current head into a fresh detached head; further
    // changes on the fork do not affect the original head.
    auto txn = beginTxn();

    db.change().put("a", "A").put("b", "B").put("c", "C").apply(txn);
    std::string orig_root = db.root(txn);
    uint64_t orig_node_id = db.getHeadNodeId(txn);

    // Fork -- detach the head, but still see the same tree state initially.
    db.fork(txn);
    EXPECT_TRUE(db.isDetachedHead());
    EXPECT_EQ(db.root(txn), orig_root);
    EXPECT_EQ(db.getHeadNodeId(txn), orig_node_id);

    // Modify the fork: root diverges.
    db.change().put("d", "D").apply(txn);
    std::string fork_root = db.root(txn);
    EXPECT_NE(fork_root, orig_root);

    std::string_view val;
    ASSERT_TRUE(db.get(txn, "d", val));
    EXPECT_EQ(val, "D");

    // Return to the original named head -- state is untouched.
    db.checkout("master");
    EXPECT_FALSE(db.isDetachedHead());
    EXPECT_EQ(db.root(txn), orig_root);
    EXPECT_FALSE(db.get(txn, "d", val));  // fork's addition invisible
    ASSERT_TRUE(db.get(txn, "a", val));
    EXPECT_EQ(val, "A");

    txn.commit();
}


TEST_F(Heads, CheckoutByNodeIdRestoresOldTree) {
    // checkout(nodeId) is the "detached HEAD at commit X" primitive: it
    // repositions the head to any node id that still exists in storage.
    auto txn = beginTxn();

    // Build v1 of the tree.
    db.change().put("k", "v1").put("other", "z").apply(txn);
    uint64_t v1_id = db.getHeadNodeId(txn);
    std::string v1_root = db.root(txn);

    // Build v2: update "k".
    db.change().put("k", "v2").apply(txn);
    uint64_t v2_id = db.getHeadNodeId(txn);
    std::string v2_root = db.root(txn);
    EXPECT_NE(v1_id, v2_id);
    EXPECT_NE(v1_root, v2_root);

    // Build v3: delete "other".
    db.change().del("other").apply(txn);
    uint64_t v3_id = db.getHeadNodeId(txn);
    std::string v3_root = db.root(txn);
    EXPECT_NE(v3_id, v2_id);

    // Currently at v3: "other" gone, "k" = "v2".
    std::string_view val;
    EXPECT_FALSE(db.get(txn, "other", val));
    ASSERT_TRUE(db.get(txn, "k", val));
    EXPECT_EQ(val, "v2");

    // Rewind to v1 by nodeId: get() returns v1's values.
    db.checkout(v1_id);
    EXPECT_TRUE(db.isDetachedHead());
    EXPECT_EQ(db.root(txn), v1_root);
    ASSERT_TRUE(db.get(txn, "k", val));
    EXPECT_EQ(val, "v1");
    ASSERT_TRUE(db.get(txn, "other", val));
    EXPECT_EQ(val, "z");

    // Jump forward to v2 by nodeId.
    db.checkout(v2_id);
    ASSERT_TRUE(db.get(txn, "k", val));
    EXPECT_EQ(val, "v2");
    ASSERT_TRUE(db.get(txn, "other", val));  // still there in v2

    // Jump forward to v3 by nodeId.
    db.checkout(v3_id);
    ASSERT_TRUE(db.get(txn, "k", val));
    EXPECT_EQ(val, "v2");
    EXPECT_FALSE(db.get(txn, "other", val));

    txn.commit();
}
