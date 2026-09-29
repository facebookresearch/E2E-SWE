// quadrable WRG task -- gtest suite, module: gc_and_diff.
// Exercises two orthogonal maintenance/inspection APIs:
//   * GarbageCollector -- mark-and-sweep over interior + leaf node storage.
//     Nodes not reachable from any HEAD or MemStore attachment get pruned.
//   * db.diff(txn, nodeIdA, nodeIdB) -- returns a std::vector<Diff> describing
//     leaf-level insertions/deletions/updates between two tree revisions.
//
// Tests:
//   GC.RetainsAllReachableFromHeads
//   GC.MarkAndSweepPrunesUnreachable
//   Diff.EmitsInsertUpdateDeleteEntries

#include "quadrable_fixture.h"

#include <string>
#include <unordered_map>

using quadrable_test::QuadrableFixture;

class GC : public QuadrableFixture {};
class Diff : public QuadrableFixture {};


TEST_F(GC, RetainsAllReachableFromHeads) {
    // With ONLY reachable-from-a-head nodes in storage, gc should find NO
    // garbage: markAllHeads + sweep produces zero unmarked candidates.
    auto txn = beginTxn();

    auto c = db.change();
    for (int i = 0; i < 50; i++) {
        std::string s = std::to_string(i);
        c.put(s, s + "-val");
    }
    c.apply(txn);

    quadrable::Quadrable::GarbageCollector<> gc(db);
    gc.markAllHeads(txn);

    auto stats = gc.sweep(txn);
    EXPECT_GT(stats.total, 0u);           // some nodes exist (a >=50-leaf tree)
    EXPECT_EQ(stats.garbage, 0u);         // all reachable -> no garbage

    txn.commit();
}


TEST_F(GC, MarkAndSweepPrunesUnreachable) {
    // Building v1 then v2 leaves v1's internal nodes still in storage but no
    // longer reachable from any named head. After markAllHeads(v2) + sweep,
    // the unreachable v1-only nodes must be identified as garbage. After
    // deleteNodes(), a fresh sweep must find no garbage.
    auto txn = beginTxn();

    // v1: 30 leaves.
    {
        auto c = db.change();
        for (int i = 0; i < 30; i++) {
            std::string s = std::to_string(i);
            c.put(s, s + "-v1");
        }
        c.apply(txn);
    }
    uint64_t total_after_v1;
    {
        quadrable::Quadrable::GarbageCollector<> gc(db);
        gc.markAllHeads(txn);
        total_after_v1 = gc.sweep(txn).total;
    }

    // v2: overwrite ALL 30 leaves with new values. This forces the tree to
    // rebuild almost every interior node (and every leaf), leaving the
    // v1-shaped structure orphaned in LMDB storage.
    {
        auto c = db.change();
        for (int i = 0; i < 30; i++) {
            std::string s = std::to_string(i);
            c.put(s, s + "-v2");
        }
        c.apply(txn);
    }

    // sweep now, ONLY the current head is marked (markAllHeads scans dbi_head).
    quadrable::Quadrable::GarbageCollector<> gc(db);
    gc.markAllHeads(txn);
    auto stats = gc.sweep(txn);

    EXPECT_GT(stats.total, total_after_v1);      // more nodes exist now (v1 + v2)
    EXPECT_GT(stats.garbage, 0u);                // v1 nodes are orphaned
    EXPECT_LT(stats.garbage, stats.total);       // some (v2) still reachable

    // Deleting the garbage frees storage; second sweep finds no new garbage.
    gc.deleteNodes(txn);

    quadrable::Quadrable::GarbageCollector<> gc2(db);
    gc2.markAllHeads(txn);
    auto stats2 = gc2.sweep(txn);
    EXPECT_EQ(stats2.garbage, 0u);
    EXPECT_LT(stats2.total, stats.total);        // total shrank after delete

    // The live tree is still fully accessible (all 30 v2 values readable).
    std::string_view val;
    for (int i = 0; i < 30; i++) {
        std::string s = std::to_string(i);
        ASSERT_TRUE(db.get(txn, s, val)) << " missing key " << s;
        EXPECT_EQ(val, s + "-v2")        << " wrong val for key " << s;
    }

    txn.commit();
}


TEST_F(Diff, EmitsInsertUpdateDeleteEntries) {
    // db.diff(txn, idA, idB) returns std::vector<Diff> describing the leaf
    // changes to go from A -> B: {keyHash, key, val, deletion}. Note "val"
    // holds the NEW value for insertions and the OLD value for deletions.
    // An update surfaces as a delete+insert pair for the same keyHash.
    auto txn = beginTxn();

    // A: 5 baseline leaves.
    db.change()
      .put("apple",  "A1")
      .put("banana", "B1")
      .put("cherry", "C1")
      .put("date",   "D1")
      .put("elder",  "E1")
      .apply(txn);
    uint64_t id_A = db.getHeadNodeId(txn);

    // B: from A, delete "apple", change "banana", insert "fig". "cherry",
    // "date", "elder" untouched.
    db.change()
      .del("apple")
      .put("banana", "B2")
      .put("fig", "F1")
      .apply(txn);
    uint64_t id_B = db.getHeadNodeId(txn);

    auto diffs = db.diff(txn, id_A, id_B);

    // Bucket by (keyHash, deletion) to count.
    int deletions = 0, insertions = 0;
    bool saw_apple_del = false;
    bool saw_banana_del = false, saw_banana_ins = false;
    bool saw_fig_ins = false;

    for (const auto& d : diffs) {
        if (d.deletion) {
            deletions++;
            if (d.keyHash == quadrable::Key::hash("apple").str()) {
                saw_apple_del = true;
                EXPECT_EQ(d.val, "A1") << "deletion carries OLD value";
            } else if (d.keyHash == quadrable::Key::hash("banana").str()) {
                saw_banana_del = true;
                EXPECT_EQ(d.val, "B1") << "deletion carries OLD value";
            }
        } else {
            insertions++;
            if (d.keyHash == quadrable::Key::hash("banana").str()) {
                saw_banana_ins = true;
                EXPECT_EQ(d.val, "B2") << "insertion carries NEW value";
            } else if (d.keyHash == quadrable::Key::hash("fig").str()) {
                saw_fig_ins = true;
                EXPECT_EQ(d.val, "F1") << "insertion carries NEW value";
            }
        }
    }

    // "apple" -> pure deletion; "banana" -> del+ins (update); "fig" -> pure insertion.
    EXPECT_EQ(deletions, 2)  << "apple + banana-old";
    EXPECT_EQ(insertions, 2) << "banana-new + fig";
    EXPECT_TRUE(saw_apple_del);
    EXPECT_TRUE(saw_banana_del);
    EXPECT_TRUE(saw_banana_ins);
    EXPECT_TRUE(saw_fig_ins);

    // Reverse diff (B -> A) inverts add/delete semantics.
    auto diffs_reverse = db.diff(txn, id_B, id_A);
    int rev_deletions = 0, rev_insertions = 0;
    for (const auto& d : diffs_reverse) {
        if (d.deletion) rev_deletions++;
        else rev_insertions++;
    }
    EXPECT_EQ(rev_deletions,  2) << "reverse: banana + fig removed";
    EXPECT_EQ(rev_insertions, 2) << "reverse: apple + banana(old) re-added";

    // diff() on identical node ids yields empty.
    auto no_diffs = db.diff(txn, id_A, id_A);
    EXPECT_TRUE(no_diffs.empty());

    txn.commit();
}
