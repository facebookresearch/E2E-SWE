// quadrable WRG task -- gtest suite, module: iterator.
// Exercises the in-order Iterator over the merkle tree: forward + reverse
// direction, seek-to-key positioning, and the atEnd() sentinel that marks
// exhaustion in either direction.
//
// Tests:
//   Iterator.ForwardOrderSeekAndTraverse
//   Iterator.ReverseOrderSeekAndTraverse
//   Iterator.SeekPastEndAndBeforeStart

#include "quadrable_fixture.h"

#include <string>

using quadrable_test::QuadrableFixture;

class IteratorTest : public QuadrableFixture {};


// Helper: populate the tree with integer-encoded keys at even positions
// 2, 4, 6, ..., 18 (nine leaves). The integer-encoding keeps them in a
// well-defined hash-space order so an in-order walk visits leafVal() ==
// "2", "4", ..., "18" ascending.
static void populate_even_2_to_18(quadrable::Quadrable& db, lmdb::txn& txn) {
    auto c = db.change();
    for (uint64_t i = 2; i <= 18; i += 2) {
        c.put(quadrable::Key::fromInteger(i), std::to_string(i));
    }
    c.apply(txn);
}


TEST_F(IteratorTest, ForwardOrderSeekAndTraverse) {
    auto txn = beginTxn();
    populate_even_2_to_18(db, txn);

    // Seek to Key::null() -- starts at the leftmost (smallest) leaf.
    auto it = db.iterate(txn, quadrable::Key::null());
    ASSERT_FALSE(it.atEnd());
    EXPECT_EQ(it.get().leafVal(), "2");

    // Traverse forward through the full set: "2", "4", ..., "18".
    std::vector<std::string> seen;
    for (; !it.atEnd(); it.next()) {
        seen.emplace_back(it.get().leafVal());
    }
    ASSERT_EQ(seen.size(), 9u);
    for (size_t i = 0; i < 9; i++) {
        EXPECT_EQ(seen[i], std::to_string(2 + 2 * i)) << " index " << i;
    }
}


TEST_F(IteratorTest, ReverseOrderSeekAndTraverse) {
    auto txn = beginTxn();
    populate_even_2_to_18(db, txn);

    // Seek to Key::max() in reverse -- starts at the rightmost (largest) leaf.
    auto it = db.iterate(txn, quadrable::Key::max(), /*reverse=*/true);
    ASSERT_FALSE(it.atEnd());
    EXPECT_EQ(it.get().leafVal(), "18");

    // Traverse backwards through the full set: "18", "16", ..., "2".
    std::vector<std::string> seen;
    for (; !it.atEnd(); it.next()) {
        seen.emplace_back(it.get().leafVal());
    }
    ASSERT_EQ(seen.size(), 9u);
    for (size_t i = 0; i < 9; i++) {
        EXPECT_EQ(seen[i], std::to_string(18 - 2 * i)) << " index " << i;
    }
}


TEST_F(IteratorTest, SeekPastEndAndBeforeStart) {
    auto txn = beginTxn();
    populate_even_2_to_18(db, txn);

    // Seek to fromInteger(19) forward -- larger than the largest key (18);
    // the iterator MUST land in atEnd() state (nothing left to visit forward).
    {
        auto it = db.iterate(txn, quadrable::Key::fromInteger(19));
        EXPECT_TRUE(it.atEnd());
    }

    // Seek to fromInteger(1) reverse -- smaller than the smallest key (2);
    // the iterator MUST land in atEnd() state (nothing left to visit backward).
    {
        auto it = db.iterate(txn, quadrable::Key::fromInteger(1), /*reverse=*/true);
        EXPECT_TRUE(it.atEnd());
    }

    // Seek to an odd non-present key forward -- lands on the next larger leaf.
    // fromInteger(11) is between 10 and 12; forward should give "12".
    {
        auto it = db.iterate(txn, quadrable::Key::fromInteger(11));
        ASSERT_FALSE(it.atEnd());
        EXPECT_EQ(it.get().leafVal(), "12");
    }

    // Seek to an odd non-present key reverse -- lands on the next smaller leaf.
    // fromInteger(11) reverse should give "10".
    {
        auto it = db.iterate(txn, quadrable::Key::fromInteger(11), /*reverse=*/true);
        ASSERT_FALSE(it.atEnd());
        EXPECT_EQ(it.get().leafVal(), "10");
    }

    // An iterator on an empty tree is immediately atEnd() regardless of
    // direction.
    db.checkout();  // empty detached
    {
        auto it = db.iterate(txn, quadrable::Key::null());
        EXPECT_TRUE(it.atEnd());
    }
    {
        auto it = db.iterate(txn, quadrable::Key::max(), /*reverse=*/true);
        EXPECT_TRUE(it.atEnd());
    }
}
