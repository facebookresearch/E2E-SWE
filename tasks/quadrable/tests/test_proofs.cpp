// quadrable WRG task -- gtest suite, module: proofs.
// Exercises the merkle-proof pipeline: export a proof for a subset of keys,
// serialize + deserialize via `quadrable::transport`, import into a fresh
// empty head, verify presence/absence contracts, exercise the range-proof
// variant, and confirm proofs can drive further updates.
//
// Tests:
//   Proofs.ExportImportRoundtripPreservesRootAndValues
//   Proofs.UnprovenKeyThrowsIncompleteTree
//   Proofs.RangeProofYieldsRangeAccessOnly
//   Proofs.ApplyUpdateOnImportedProofMatchesGroundTruth
//   Proofs.SingleIntegerKeyProofIsCompact

#include "quadrable_fixture.h"

#include <quadrable/transport.h>

#include <string>
#include <vector>

using quadrable_test::QuadrableFixture;

class Proofs : public QuadrableFixture {};


static quadrable::Proof roundtrip(const quadrable::Proof& p) {
    // encode -> decode should be an identity on the semantic contents.
    return quadrable::transport::decodeProof(quadrable::transport::encodeProof(p));
}


TEST_F(Proofs, ExportImportRoundtripPreservesRootAndValues) {
    auto txn = beginTxn();

    // Build a moderately-sized tree.
    auto c = db.change();
    for (int i = 0; i < 100; i++) {
        std::string s = std::to_string(i);
        c.put(s, s + "-val");
    }
    // Include a "long" value to exercise the varint length encoding branch.
    c.put("long", std::string(789, 'A'));
    c.apply(txn);

    std::string orig_root = db.root(txn);

    // Export a proof for a subset, serialize+deserialize, import into empty.
    auto proof = roundtrip(db.exportProof(txn, {"5", "42", "long"}));

    db.checkout();  // detached empty head
    db.importProof(txn, proof, orig_root);

    // Root of the imported partial tree equals the original tree's root.
    EXPECT_EQ(db.root(txn), orig_root);

    // Proven keys return their exact values.
    std::string_view val;
    ASSERT_TRUE(db.get(txn, "5", val));
    EXPECT_EQ(val, "5-val");
    ASSERT_TRUE(db.get(txn, "42", val));
    EXPECT_EQ(val, "42-val");
    ASSERT_TRUE(db.get(txn, "long", val));
    EXPECT_EQ(val, std::string(789, 'A'));

    // Importing a proof whose expectedRoot mismatches MUST throw.
    db.checkout();
    std::string wrong_root(32, '\xEE');
    EXPECT_THROW(db.importProof(txn, proof, wrong_root), std::runtime_error);

    // A second attempt to import into an already-populated head throws.
    db.checkout();
    db.importProof(txn, proof, orig_root);
    auto proof2 = roundtrip(db.exportProof(txn, {"5"}));
    // Second import on non-empty head is disallowed.
    EXPECT_THROW(db.importProof(txn, proof2, orig_root), std::runtime_error);

    txn.commit();
}


TEST_F(Proofs, UnprovenKeyThrowsIncompleteTree) {
    auto txn = beginTxn();

    // Build a tree with a few keys that all live at shallow depths.
    auto c = db.change();
    for (int i = 0; i < 30; i++) {
        std::string s = std::to_string(i);
        c.put(s, s + "-val");
    }
    c.apply(txn);

    std::string orig_root = db.root(txn);

    // Prove ONLY key "5". Every other key in the tree lives under a
    // witness node in the resulting partial tree.
    auto proof = roundtrip(db.exportProof(txn, {"5"}));

    db.checkout();
    db.importProof(txn, proof, orig_root);

    // Proven key: get() returns its exact value.
    std::string_view val;
    ASSERT_TRUE(db.get(txn, "5", val));
    EXPECT_EQ(val, "5-val");

    // Unproven-key contract:
    // * Some unproven keys resolve to "incomplete tree" (they collide with
    //   a witness leaf in the partial tree).
    // * Others resolve to false (the walk lands in a WitnessEmpty region --
    //   proven-absent territory).
    // At least ONE unproven pre-existing key MUST throw. This is the load
    // -bearing contract: you can't fabricate a value for an unproven key.
    int throw_count = 0;
    for (int i = 0; i < 30; i++) {
        if (i == 5) continue;
        std::string k = std::to_string(i);
        try {
            (void)db.get(txn, k, val);
        } catch (const std::runtime_error&) {
            throw_count++;
        }
    }
    EXPECT_GT(throw_count, 0);

    txn.commit();
}


TEST_F(Proofs, RangeProofYieldsRangeAccessOnly) {
    // exportProofRange(begin_key, end_key) produces a proof that permits
    // access to every key whose hash lies in [begin_key, end_key], and denies
    // (via "incomplete tree") access to keys with hashes outside the range.
    auto txn = beginTxn();

    // Populate with integer keys 1..999 -- the fromInteger scheme puts them in
    // a well-defined order in hash space.
    {
        auto c = db.change();
        for (uint64_t i = 1; i < 1000; i++) {
            c.put(quadrable::Key::fromInteger(i), std::to_string(i));
        }
        c.apply(txn);
    }

    std::string orig_root = db.root(txn);
    uint64_t orig_head = db.getHeadNodeId(txn);

    auto proof = roundtrip(db.exportProofRange(
        txn, orig_head,
        quadrable::Key::fromInteger(500),
        quadrable::Key::fromInteger(510)));

    db.checkout();
    db.importProof(txn, proof, orig_root);
    EXPECT_EQ(db.root(txn), orig_root);

    // Keys inside the range: getRaw() (by raw key) returns the exact value.
    std::string_view val;
    for (uint64_t i = 500; i < 510; i++) {
        ASSERT_TRUE(db.getRaw(txn, quadrable::Key::fromInteger(i).sv(), val))
            << " missing i=" << i;
        EXPECT_EQ(val, std::to_string(i)) << " wrong value at i=" << i;
    }

    // Keys OUTSIDE the range: must throw "incomplete tree" (witness node
    // in the partial tree covers them).
    EXPECT_THROW(db.getRaw(txn, quadrable::Key::fromInteger(1).sv(), val),
                 std::runtime_error);
    EXPECT_THROW(db.getRaw(txn, quadrable::Key::fromInteger(499).sv(), val),
                 std::runtime_error);
    EXPECT_THROW(db.getRaw(txn, quadrable::Key::fromInteger(511).sv(), val),
                 std::runtime_error);
    EXPECT_THROW(db.getRaw(txn, quadrable::Key::fromInteger(999).sv(), val),
                 std::runtime_error);

    txn.commit();
}


TEST_F(Proofs, ApplyUpdateOnImportedProofMatchesGroundTruth) {
    // After importing a proof, applying an update to a PROVEN leaf must
    // produce the same root the same update would produce on the full tree.
    // Applying an update to a fully-opaque WITNESS slot must throw.
    auto txn = beginTxn();

    // Phase 1 -- build the reference tree, capture proofs + roots.
    db.change()
      .put("apple",  "A")
      .put("banana", "B")
      .put("cherry", "C")
      .put("date",   "D")
      .apply(txn);
    uint64_t orig_head_id = db.getHeadNodeId(txn);
    std::string orig_root = db.root(txn);

    auto proof_apple_v1 = roundtrip(db.exportProof(txn, {"apple"}));
    auto proof_apple_v2 = roundtrip(db.exportProof(txn, {"apple"}));

    // Apply the reference update to the full tree, capture the target root.
    db.change().put("apple", "APPLE-2").apply(txn);
    std::string ref_root_after_update = db.root(txn);
    EXPECT_NE(ref_root_after_update, orig_root);

    // Phase 2 -- import the proof into a fresh detached empty head, apply the
    // same update, verify the resulting root matches the reference.
    db.checkout();  // detached empty
    db.importProof(txn, proof_apple_v1, orig_root);
    EXPECT_EQ(db.root(txn), orig_root);

    db.change().put("apple", "APPLE-2").apply(txn);
    EXPECT_EQ(db.root(txn), ref_root_after_update);

    // Phase 3 -- fresh import, this time try to update an UNPROVEN key
    // (`banana` is only a witness in a proof of `apple`); must throw.
    db.checkout();
    db.importProof(txn, proof_apple_v2, orig_root);
    EXPECT_THROW(db.change().put("banana", "BANANA-2").apply(txn),
                 std::runtime_error);

    // Sanity: the original master head still has orig_root at orig_head_id.
    db.checkout(orig_head_id);
    EXPECT_EQ(db.root(txn), orig_root);

    txn.commit();
}


TEST_F(Proofs, SingleIntegerKeyProofIsCompact) {
    // Compactness property: a proof for a single integer-encoded key stays
    // compact regardless of how large the integer is. The exact byte budget
    // depends on the (unspecified) proof wire layout, so this asserts the
    // user-observable contracts instead: a lone-key proof is far smaller than a
    // proof covering the whole tree, it fits in fewer bytes than the 32-byte
    // keyHash it proves (so the keyHash cannot be shipped verbatim), and its
    // size stays essentially independent of the integer's magnitude.
    auto txn = beginTxn();

    // Baseline: a proof covering many keys of a populated tree is large.
    {
        auto c = db.change();
        for (uint64_t i = 1; i <= 100; i++) {
            c.put(quadrable::Key::fromInteger(i), std::to_string(i));
        }
        c.apply(txn);
    }
    std::vector<quadrable::Key> allKeys;
    for (uint64_t i = 1; i <= 100; i++) allKeys.push_back(quadrable::Key::fromInteger(i));
    size_t fullProofLen =
        quadrable::transport::encodeProof(db.exportProofRaw(txn, allKeys)).length();

    size_t minLen = 0, maxLen = 0;
    bool first = true;
    for (uint64_t i = 1; i <= 1'000'000'000ULL; i *= 10) {
        db.checkout();  // detached empty head: build a lone-key tree

        db.change().put(quadrable::Key::fromInteger(i), "A").apply(txn);

        auto proof = db.exportProofRaw(txn, {quadrable::Key::fromInteger(i)});
        auto encoded = quadrable::transport::encodeProof(proof);

        // Compact: a lone-key proof is a small fraction of a whole-tree proof.
        EXPECT_LT(encoded.length(), fullProofLen) << " i=" << i;

        // ...and it fits in fewer bytes than the single 32-byte keyHash it
        // proves, so a wire format that ships keyHashes verbatim cannot pass.
        EXPECT_LT(encoded.length(), 32u) << " i=" << i << " proof len=" << encoded.length();

        if (first) {
            minLen = maxLen = encoded.length();
            first = false;
        } else {
            if (encoded.length() < minLen) minLen = encoded.length();
            if (encoded.length() > maxLen) maxLen = encoded.length();
        }

        // Round-tripping the encoding must also be identity-preserving.
        auto decoded = quadrable::transport::decodeProof(encoded);
        EXPECT_EQ(decoded.strands.size(), proof.strands.size());
        EXPECT_EQ(decoded.cmds.size(), proof.cmds.size());
    }

    // Scale-independence: raising the integer by nine orders of magnitude adds
    // only a handful of bytes (its extra significant bytes), never the
    // 32-byte-per-key blow-up of a naive full-keyHash encoding.
    EXPECT_LE(maxLen - minLen, 16u);

    txn.commit();
}
