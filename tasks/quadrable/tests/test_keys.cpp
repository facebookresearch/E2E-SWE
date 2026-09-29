// quadrable WRG task -- gtest suite, module: keys.
// Exercises the standalone `quadrable::Key` type: 32-byte hash construction,
// the compact 64-bit integer encoding into a 32-byte Key (fromInteger /
// toInteger round-trip), ordering comparisons, and per-bit access.
//
// Tests:
//   Keys.IntegerRoundTripSmallAndLargeAndPowersOfTwo
//   Keys.NullAndMaxAndOrdering
//   Keys.BitGetSetAndKeepPrefix

#include <gtest/gtest.h>
#include <quadrable.h>

#include <cstdint>
#include <limits>


TEST(Keys, IntegerRoundTripSmallAndLargeAndPowersOfTwo) {
    using quadrable::Key;

    // Small values: exhaustive round-trip.
    for (uint64_t i = 0; i < 10000; i++) {
        EXPECT_EQ(Key::fromInteger(i).toInteger(), i) << " at i=" << i;
    }

    // Powers-of-two boundary values -- Key uses a variable-length prefix
    // encoding whose branches change at power-of-two boundaries.
    for (uint64_t bits = 10; bits <= 62; bits++) {
        uint64_t n = (1ULL << bits) - 5ULL;
        EXPECT_EQ(Key::fromInteger(n).toInteger(), n) << " at bits=" << bits;
    }

    // Large-value range just under the encoding limit.
    for (uint64_t i = std::numeric_limits<uint64_t>::max() - 1000;
         i <= std::numeric_limits<uint64_t>::max() - 2; i++) {
        EXPECT_EQ(Key::fromInteger(i).toInteger(), i) << " at i=" << i;
    }

    // Two values above the documented representable range MUST throw.
    EXPECT_THROW(Key::fromInteger(std::numeric_limits<uint64_t>::max() - 1),
                 std::runtime_error);
    EXPECT_THROW(Key::fromInteger(std::numeric_limits<uint64_t>::max()),
                 std::runtime_error);
}


TEST(Keys, NullAndMaxAndOrdering) {
    using quadrable::Key;

    Key nul = Key::null();
    Key mx  = Key::max();

    // null() is 32 zero bytes; max() is 32 0xFF bytes.
    for (int i = 0; i < 32; i++) {
        EXPECT_EQ(nul.data[i], 0x00) << " byte " << i;
        EXPECT_EQ(mx.data[i], 0xFF) << " byte " << i;
    }

    // Ordering: null < anything non-null; max > anything non-max.
    EXPECT_TRUE(nul < mx);
    EXPECT_TRUE(mx > nul);
    EXPECT_TRUE(nul <= nul);
    EXPECT_TRUE(mx >= mx);
    EXPECT_TRUE(nul == nul);
    EXPECT_TRUE(nul != mx);

    // hash() of a string produces a 32-byte value strictly between null and max.
    Key h = Key::hash("some-key");
    EXPECT_TRUE(nul < h);
    EXPECT_TRUE(h < mx);

    // Two different string inputs must produce different hashes.
    Key h2 = Key::hash("some-other-key");
    EXPECT_TRUE(h != h2);

    // Same string input must produce the same hash (determinism).
    Key h_again = Key::hash("some-key");
    EXPECT_TRUE(h == h_again);

    // existing() copies raw 32-byte payload (accepts a string_view of length 32).
    std::string raw(32, '\xAB');
    Key k = Key::existing(raw);
    for (int i = 0; i < 32; i++) EXPECT_EQ(k.data[i], 0xAB) << " byte " << i;

    // existing() with wrong-sized input must throw.
    std::string too_short(10, '\xAB');
    EXPECT_THROW(Key::existing(too_short), std::runtime_error);
}


TEST(Keys, BitGetSetAndKeepPrefix) {
    using quadrable::Key;

    Key k = Key::null();

    // All bits initially 0.
    for (size_t i = 0; i < 256; i++) {
        EXPECT_FALSE(k.getBit(i)) << " bit " << i;
    }

    // Set a scattered subset of bits, read them back individually.
    k.setBit(0, 1);
    k.setBit(7, 1);
    k.setBit(8, 1);
    k.setBit(63, 1);
    k.setBit(200, 1);
    k.setBit(255, 1);

    EXPECT_TRUE(k.getBit(0));
    EXPECT_TRUE(k.getBit(7));
    EXPECT_TRUE(k.getBit(8));
    EXPECT_TRUE(k.getBit(63));
    EXPECT_TRUE(k.getBit(200));
    EXPECT_TRUE(k.getBit(255));

    // Neighbouring bits are still unset.
    EXPECT_FALSE(k.getBit(1));
    EXPECT_FALSE(k.getBit(9));
    EXPECT_FALSE(k.getBit(64));
    EXPECT_FALSE(k.getBit(199));
    EXPECT_FALSE(k.getBit(254));

    // setBit(idx, 0) clears an individual bit.
    k.setBit(7, 0);
    EXPECT_FALSE(k.getBit(7));
    EXPECT_TRUE(k.getBit(0));   // untouched
    EXPECT_TRUE(k.getBit(8));   // untouched

    // Out-of-range setBit MUST throw.
    EXPECT_THROW(k.setBit(256, 1), std::runtime_error);
    EXPECT_THROW(k.setBit(500, 1), std::runtime_error);

    // keepPrefixBits(n): zero every bit at index >= n.
    Key allOnes = Key::max();
    allOnes.keepPrefixBits(10);
    for (size_t i = 0; i < 10; i++) EXPECT_TRUE(allOnes.getBit(i)) << " bit " << i;
    for (size_t i = 10; i < 256; i++) EXPECT_FALSE(allOnes.getBit(i)) << " bit " << i;

    Key allOnes2 = Key::max();
    allOnes2.keepPrefixBits(256);
    // Truncating at 256 is a no-op: nothing to zero.
    for (size_t i = 0; i < 256; i++) EXPECT_TRUE(allOnes2.getBit(i)) << " bit " << i;
}
