// quadrable WRG task -- gtest suite, module: sync.
// Exercises the incremental tree-sync protocol: the local `Sync` client walks
// its shadow tree, asking the server (via `handleSyncRequests`) for the
// witness slots it doesn't yet know; the server produces proof fragments; the
// client applies them and reissues requests until convergence. After
// convergence, the reconstructed shadow's root hash MUST match the source
// tree's root hash byte-for-byte.
//
// Tests:
//   Sync.MultiRoundReconstructsRoot
//   Sync.BytesBudgetForcesAdditionalRounds
//   Sync.DiffEmitsAddedChangedDeleted

#include "quadrable_fixture.h"

#include <quadrable/transport.h>

#include <string>
#include <unordered_map>

using quadrable_test::QuadrableFixture;

class SyncTest : public QuadrableFixture {};


// Helper: seed the tree at the current head with N integer-keyed leaves,
// value = std::to_string(i).
static void seed_integer_leaves(quadrable::Quadrable& db, lmdb::txn& txn,
                                uint64_t n_start, uint64_t n_end) {
    auto c = db.change();
    for (uint64_t i = n_start; i < n_end; i++) {
        c.put(quadrable::Key::fromInteger(i), std::to_string(i));
    }
    c.apply(txn);
}


TEST_F(SyncTest, MultiRoundReconstructsRoot) {
    // Build source tree at master, capture its root and nodeId. Then use Sync
    // to reconstruct it into a MemStore-backed shadow. After the round-trip
    // loop, the shadow's root MUST equal the source's root.
    auto txn = beginTxn();

    seed_integer_leaves(db, txn, /*from=*/1, /*to=*/200);
    uint64_t source_node_id = db.getHeadNodeId(txn);
    std::string source_root = db.root(txn);

    // Attach a MemStore so the shadow lives in RAM (doesn't collide with
    // the source tree in LMDB).
    db.addMemStore();
    db.writeToMemStore = true;

    quadrable::Quadrable::Sync sync(&db);
    // init(nodeIdLocal_) tells Sync where the LOCAL client's tree currently
    // is -- pass 0 to say "the local client starts with the empty tree".
    sync.init(txn, 0);

    // Sync loop: getReqs -> handleSyncRequests -> addResps until reqs empty.
    // Round-trip through transport encoding so we exercise the serialization
    // path the way a real over-network sync would.
    int rounds = 0;
    while (true) {
        auto reqs = quadrable::transport::decodeSyncRequests(
            quadrable::transport::encodeSyncRequests(sync.getReqs(txn)));
        if (reqs.empty()) break;

        auto resps = quadrable::transport::decodeSyncResponses(
            quadrable::transport::encodeSyncResponses(
                db.handleSyncRequests(txn, source_node_id, reqs)));

        sync.addResps(txn, reqs, resps);
        rounds++;
        ASSERT_LT(rounds, 100) << "sync did not converge in 100 rounds";
    }

    // After convergence, the shadow tree's root must equal the source.
    db.writeToMemStore = false;
    db.checkout(sync.nodeIdShadow);
    EXPECT_EQ(db.root(txn), source_root);

    db.removeMemStore();

    txn.commit();
}


TEST_F(SyncTest, BytesBudgetForcesAdditionalRounds) {
    // With a very small bytesBudget on getReqs, the client should still be
    // able to converge -- it just takes more rounds. This exercises the
    // budget-partial-progress path.
    auto txn = beginTxn();

    seed_integer_leaves(db, txn, /*from=*/1, /*to=*/500);
    uint64_t source_node_id = db.getHeadNodeId(txn);
    std::string source_root = db.root(txn);

    db.addMemStore();
    db.writeToMemStore = true;

    quadrable::Quadrable::Sync sync(&db);
    sync.init(txn, 0);

    int rounds = 0;
    while (true) {
        // Tiny per-round budget forces the sync into many small requests.
        auto reqs = sync.getReqs(txn, /*bytesBudget=*/128);
        if (reqs.empty()) break;

        auto resps = db.handleSyncRequests(txn, source_node_id, reqs,
                                           /*bytesBudget=*/1024);
        sync.addResps(txn, reqs, resps);

        rounds++;
        ASSERT_LT(rounds, 500) << "sync did not converge in 500 rounds";
    }

    db.writeToMemStore = false;
    db.checkout(sync.nodeIdShadow);
    EXPECT_EQ(db.root(txn), source_root);
    // Small budgets require MORE than 1 round on a 500-leaf tree.
    EXPECT_GT(rounds, 1);

    db.removeMemStore();

    txn.commit();
}


TEST_F(SyncTest, DiffEmitsAddedChangedDeleted) {
    // Build tree v1, fork it, mutate it to v2 (some added, some changed,
    // some deleted). Then use Sync::diff to walk the difference and
    // categorize each leaf. Counts must match the mutations applied.
    auto txn = beginTxn();

    // v1: fromInteger(1..20)
    seed_integer_leaves(db, txn, /*from=*/1, /*to=*/21);
    uint64_t v1_id = db.getHeadNodeId(txn);

    db.fork(txn);

    // v2 mutations (from v1 base):
    //   - CHANGE keys 5, 10, 15 (put with new value)
    //   - DELETE keys 3, 7, 12
    //   - ADD    keys 100, 101, 102
    {
        auto c = db.change();
        c.put(quadrable::Key::fromInteger(5),  "5-changed");
        c.put(quadrable::Key::fromInteger(10), "10-changed");
        c.put(quadrable::Key::fromInteger(15), "15-changed");
        c.del(quadrable::Key::fromInteger(3));
        c.del(quadrable::Key::fromInteger(7));
        c.del(quadrable::Key::fromInteger(12));
        c.put(quadrable::Key::fromInteger(100), "100");
        c.put(quadrable::Key::fromInteger(101), "101");
        c.put(quadrable::Key::fromInteger(102), "102");
        c.apply(txn);
    }
    uint64_t v2_id = db.getHeadNodeId(txn);
    ASSERT_NE(v1_id, v2_id);

    // Diff v1 -> v2 via Sync::diff. Categorize each callback invocation.
    quadrable::Quadrable::Sync sync(&db);
    int n_added = 0, n_changed = 0, n_deleted = 0;

    sync.diff(txn, v1_id, v2_id,
              [&](quadrable::Quadrable::DiffType dt,
                  const quadrable::Quadrable::ParsedNode&) {
                  if (dt == quadrable::Quadrable::DiffType::Added) n_added++;
                  else if (dt == quadrable::Quadrable::DiffType::Changed) n_changed++;
                  else if (dt == quadrable::Quadrable::DiffType::Deleted) n_deleted++;
              });

    EXPECT_EQ(n_added, 3)   << "3 keys added (100, 101, 102)";
    EXPECT_EQ(n_changed, 3) << "3 keys changed (5, 10, 15)";
    EXPECT_EQ(n_deleted, 3) << "3 keys deleted (3, 7, 12)";

    txn.commit();
}
