// quadrable WRG task -- gtest suite, module: transport.
// Exercises the byte-level wire encoding under `quadrable::transport::*`:
// proof serialization + deserialization is an identity (deep equality on the
// decoded value), and the sync-request/response encoders round-trip the
// SyncRequests/SyncResponses vectors likewise.
//
// Tests:
//   Transport.ProofEncodeDecodeIsIdentity
//   Transport.SyncRequestsAndResponsesEncoding

#include "quadrable_fixture.h"

#include <quadrable/transport.h>

using quadrable_test::QuadrableFixture;

class Transport : public QuadrableFixture {};


TEST_F(Transport, ProofEncodeDecodeIsIdentity) {
    // Build a tree, export a proof for a few keys, encode -> decode. The
    // decoded Proof must have byte-identical strands (types, depths,
    // keyHashes, values) and byte-identical cmds (ops, offsets, hashes).
    auto txn = beginTxn();

    auto c = db.change();
    for (int i = 0; i < 50; i++) {
        std::string s = std::to_string(i);
        c.put(s, s + "-val");
    }
    c.apply(txn);

    auto orig_proof = db.exportProof(txn, {"3", "17", "42"});

    auto encoded = quadrable::transport::encodeProof(orig_proof);
    ASSERT_GT(encoded.size(), 0u);

    auto decoded = quadrable::transport::decodeProof(encoded);

    // Strand count must match.
    ASSERT_EQ(decoded.strands.size(), orig_proof.strands.size());
    for (size_t i = 0; i < orig_proof.strands.size(); i++) {
        const auto& a = orig_proof.strands[i];
        const auto& b = decoded.strands[i];
        EXPECT_EQ(static_cast<int>(a.strandType), static_cast<int>(b.strandType))
            << " strand " << i;
        EXPECT_EQ(a.depth, b.depth)                << " strand " << i;
        EXPECT_EQ(a.keyHash, b.keyHash)            << " strand " << i;
        EXPECT_EQ(a.val, b.val)                    << " strand " << i;
    }

    // Cmd count must match.
    ASSERT_EQ(decoded.cmds.size(), orig_proof.cmds.size());
    for (size_t i = 0; i < orig_proof.cmds.size(); i++) {
        const auto& a = orig_proof.cmds[i];
        const auto& b = decoded.cmds[i];
        EXPECT_EQ(static_cast<int>(a.op), static_cast<int>(b.op)) << " cmd " << i;
        EXPECT_EQ(a.nodeOffset, b.nodeOffset)                     << " cmd " << i;
        EXPECT_EQ(a.hash, b.hash)                                 << " cmd " << i;
    }

    txn.commit();
}


TEST_F(Transport, SyncRequestsAndResponsesEncoding) {
    // The sync-protocol encoders must round-trip both SyncRequests and
    // SyncResponses vectors. Assemble a small SyncRequests by hand, encode
    // -> decode, verify fields. Then generate a real SyncResponses via
    // handleSyncRequests, encode -> decode, verify the resulting proof
    // strands match one-for-one.
    auto txn = beginTxn();

    // Populate a small tree so handleSyncRequests has data to answer over.
    {
        auto c = db.change();
        for (uint64_t i = 1; i < 40; i++) {
            c.put(quadrable::Key::fromInteger(i), std::to_string(i));
        }
        c.apply(txn);
    }
    uint64_t node_id = db.getHeadNodeId(txn);

    // --- Round-trip a hand-built SyncRequests ---
    quadrable::SyncRequests reqs = {
        quadrable::SyncRequest{quadrable::Key::null(), /*startDepth=*/0,
                               /*depthLimit=*/4, /*expandLeaves=*/false},
    };
    auto encoded_reqs = quadrable::transport::encodeSyncRequests(reqs);
    ASSERT_GT(encoded_reqs.size(), 0u);
    auto decoded_reqs = quadrable::transport::decodeSyncRequests(encoded_reqs);
    ASSERT_EQ(decoded_reqs.size(), reqs.size());
    for (size_t i = 0; i < reqs.size(); i++) {
        EXPECT_EQ(decoded_reqs[i].path.str(),  reqs[i].path.str())   << " req " << i;
        EXPECT_EQ(decoded_reqs[i].startDepth,  reqs[i].startDepth)   << " req " << i;
        EXPECT_EQ(decoded_reqs[i].depthLimit,  reqs[i].depthLimit)   << " req " << i;
        EXPECT_EQ(decoded_reqs[i].expandLeaves,reqs[i].expandLeaves) << " req " << i;
    }

    // --- Round-trip real SyncResponses from handleSyncRequests ---
    auto resps = db.handleSyncRequests(txn, node_id, decoded_reqs);
    ASSERT_GT(resps.size(), 0u);

    auto encoded_resps = quadrable::transport::encodeSyncResponses(resps);
    ASSERT_GT(encoded_resps.size(), 0u);
    auto decoded_resps = quadrable::transport::decodeSyncResponses(encoded_resps);
    ASSERT_EQ(decoded_resps.size(), resps.size());
    for (size_t i = 0; i < resps.size(); i++) {
        const auto& orig = resps[i];
        const auto& got = decoded_resps[i];

        // Response proofs must round-trip field-by-field, not merely by count
        // (same deep-equality the Proof and SyncRequests halves assert).
        ASSERT_EQ(got.strands.size(), orig.strands.size())
            << " response proof " << i << " strand count differs";
        for (size_t j = 0; j < orig.strands.size(); j++) {
            const auto& a = orig.strands[j];
            const auto& b = got.strands[j];
            EXPECT_EQ(static_cast<int>(a.strandType), static_cast<int>(b.strandType))
                << " response " << i << " strand " << j;
            EXPECT_EQ(a.depth, b.depth)     << " response " << i << " strand " << j;
            EXPECT_EQ(a.keyHash, b.keyHash) << " response " << i << " strand " << j;
            EXPECT_EQ(a.val, b.val)         << " response " << i << " strand " << j;
        }

        ASSERT_EQ(got.cmds.size(), orig.cmds.size())
            << " response proof " << i << " cmd count differs";
        for (size_t j = 0; j < orig.cmds.size(); j++) {
            const auto& a = orig.cmds[j];
            const auto& b = got.cmds[j];
            EXPECT_EQ(static_cast<int>(a.op), static_cast<int>(b.op))
                << " response " << i << " cmd " << j;
            EXPECT_EQ(a.nodeOffset, b.nodeOffset) << " response " << i << " cmd " << j;
            EXPECT_EQ(a.hash, b.hash)             << " response " << i << " cmd " << j;
        }
    }

    txn.commit();
}
