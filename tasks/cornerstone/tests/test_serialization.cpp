// Higher-level serialization tests: srv_config, cluster_config, snapshot,
// snapshot_sync_req, log_entry. Every one of these is a bufptr in/out
// contract that the raft server RPC and fs_log_store on-disk formats depend
// on; a round-trip mismatch here shows up as either a wire-format regression
// or a persistence corruption.

#include <gtest/gtest.h>

#include <cornerstone/cornerstone.hxx>

#include <string>
#include <vector>

using namespace cornerstone;

// TEST 6 — srv_config carries (id, endpoint). Serialize + deserialize must
// yield an equivalent (id, endpoint) pair.
TEST(Serialization, SrvConfigRoundTrip)
{
    auto orig = cs_new<srv_config>(7, std::string("tcp://192.168.1.1:9000"));
    bufptr b = orig->serialize();
    b->pos(0);

    ptr<srv_config> back = srv_config::deserialize(*b);

    EXPECT_EQ(back->get_id(), 7);
    EXPECT_EQ(back->get_endpoint(), std::string("tcp://192.168.1.1:9000"));
}

// TEST 7 — cluster_config carries (log_idx, prev_log_idx, list<srv_config>).
// Deserialize must reconstruct all three; the srv_config list must preserve
// insertion order and every (id, endpoint) pair.
TEST(Serialization, ClusterConfigRoundTrip)
{
    ptr<cluster_config> orig = cs_new<cluster_config>(100, 42);
    orig->get_servers().push_back(cs_new<srv_config>(1, std::string("a")));
    orig->get_servers().push_back(cs_new<srv_config>(2, std::string("bb")));
    orig->get_servers().push_back(cs_new<srv_config>(3, std::string("ccc")));

    bufptr b = orig->serialize();
    b->pos(0);
    ptr<cluster_config> back = cluster_config::deserialize(*b);

    EXPECT_EQ(back->get_log_idx(), static_cast<ulong>(100));
    EXPECT_EQ(back->get_prev_log_idx(), static_cast<ulong>(42));
    ASSERT_EQ(back->get_servers().size(), static_cast<size_t>(3));

    auto it_orig = orig->get_servers().begin();
    auto it_back = back->get_servers().begin();
    for (; it_orig != orig->get_servers().end(); ++it_orig, ++it_back)
    {
        EXPECT_EQ((*it_orig)->get_id(), (*it_back)->get_id());
        EXPECT_EQ((*it_orig)->get_endpoint(), (*it_back)->get_endpoint());
    }
}

// TEST 8 — snapshot carries (last_log_idx, last_log_term, size,
// cluster_config). Round-trip must preserve all four including the nested
// cluster_config's servers.
TEST(Serialization, SnapshotRoundTrip)
{
    ptr<cluster_config> conf = cs_new<cluster_config>(50, 10);
    conf->get_servers().push_back(cs_new<srv_config>(1, std::string("x")));
    conf->get_servers().push_back(cs_new<srv_config>(2, std::string("y")));

    ptr<snapshot> orig = cs_new<snapshot>(500, 3, conf, 12345);
    bufptr b = orig->serialize();
    b->pos(0);
    ptr<snapshot> back = snapshot::deserialize(*b);

    EXPECT_EQ(back->get_last_log_idx(), static_cast<ulong>(500));
    EXPECT_EQ(back->get_last_log_term(), static_cast<ulong>(3));
    EXPECT_EQ(back->size(), static_cast<ulong>(12345));
    ASSERT_EQ(back->get_last_config()->get_servers().size(), static_cast<size_t>(2));
}

// TEST 9 — snapshot_sync_req wraps (snapshot, offset, data, done). The
// nested snapshot round-trips as in the previous test; the data buffer's
// remaining bytes must survive verbatim; the done flag round-trips as a byte.
TEST(Serialization, SnapshotSyncReqRoundTrip)
{
    ptr<cluster_config> conf = cs_new<cluster_config>(1, 0);
    conf->get_servers().push_back(cs_new<srv_config>(1, std::string("x")));
    ptr<snapshot> snp = cs_new<snapshot>(42, 2, conf, 999);

    const size_t payload_size = 128;
    bufptr payload = buffer::alloc(payload_size);
    for (size_t i = 0; i < payload_size; ++i)
    {
        payload->put(static_cast<byte>(i & 0xff));
    }
    payload->pos(0);
    bufptr expected_payload = buffer::copy(*payload);
    payload->pos(0);

    ptr<snapshot_sync_req> orig = cs_new<snapshot_sync_req>(
        snp, /*offset=*/17, std::move(payload), /*done=*/true);
    bufptr b = orig->serialize();
    b->pos(0);
    ptr<snapshot_sync_req> back = snapshot_sync_req::deserialize(*b);

    EXPECT_EQ(back->get_offset(), static_cast<ulong>(17));
    EXPECT_TRUE(back->is_done());
    EXPECT_EQ(back->get_snapshot().get_last_log_idx(), static_cast<ulong>(42));
    EXPECT_EQ(back->get_snapshot().get_last_log_term(), static_cast<ulong>(2));

    buffer& back_payload = back->get_data();
    ASSERT_EQ(back_payload.size(), payload_size);
    for (size_t i = 0; i < payload_size; ++i)
    {
        EXPECT_EQ(back_payload.data()[i], expected_payload->data()[i]) << "byte " << i;
    }
}

// TEST 10 — log_entry carries (term, log_val_type, data). Serialize prepends
// term + type as a byte, then the payload. Deserialize must reconstruct all
// three, with the payload bytes preserved verbatim (through get_byte
// iteration to exercise the buffer read side too).
TEST(Serialization, LogEntryRoundTrip)
{
    bufptr data = buffer::alloc(16);
    for (byte i = 0; i < 16; ++i) data->put(static_cast<byte>(i * 3));
    data->pos(0);
    bufptr expected = buffer::copy(*data);
    data->pos(0);

    ptr<log_entry> orig = cs_new<log_entry>(
        /*term=*/99, std::move(data), log_val_type::conf);
    bufptr b = orig->serialize();
    b->pos(0);
    ptr<log_entry> back = log_entry::deserialize(*b);

    EXPECT_EQ(back->get_term(), static_cast<ulong>(99));
    EXPECT_EQ(back->get_val_type(), log_val_type::conf);
    ASSERT_EQ(back->get_buf().size(), expected->size());
    expected->pos(0);
    buffer& back_buf = back->get_buf();
    back_buf.pos(0);
    for (size_t i = 0; i < expected->size(); ++i)
    {
        EXPECT_EQ(back_buf.get_byte(), expected->get_byte()) << "byte " << i;
    }

    // Companion: term_in_buffer must peek the term without advancing pos.
    bufptr peek_buf = orig->serialize();
    peek_buf->pos(0);
    // Recreate — the previous serialize/deserialize consumed the buffer.
    bufptr peek_data = buffer::alloc(4);
    peek_data->put(static_cast<byte>(1));
    peek_data->put(static_cast<byte>(2));
    peek_data->put(static_cast<byte>(3));
    peek_data->put(static_cast<byte>(4));
    peek_data->pos(0);
    ptr<log_entry> peek_entry = cs_new<log_entry>(
        static_cast<ulong>(0x0badf00d), std::move(peek_data), log_val_type::app_log);
    bufptr peek_serialized = peek_entry->serialize();
    peek_serialized->pos(0);
    EXPECT_EQ(log_entry::term_in_buffer(*peek_serialized), static_cast<ulong>(0x0badf00d));
    EXPECT_EQ(peek_serialized->pos(), static_cast<size_t>(0));
}
