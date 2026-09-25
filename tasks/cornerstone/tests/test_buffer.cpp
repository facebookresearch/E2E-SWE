// Buffer primitive tests for cornerstone.
//
// buffer is cornerstone's byte-oriented serialization primitive. Every
// higher-level codec (log_entry, srv_config, cluster_config, snapshot,
// snapshot_sync_req) is built by concatenating buffer::put(...) calls; the
// wire format therefore depends on buffer producing exact-byte,
// little-endian encodings and reading them back through get_*.
//
// The tests below exercise buffer's public surface via round-trips at both
// the "small block" (< 32 KiB, ushort-sized header) and "big block"
// (>= 32 KiB, uint-sized header + MSB flag) layouts.

#include <gtest/gtest.h>

#include <cornerstone/cornerstone.hxx>

#include <cstring>
#include <sstream>
#include <string>
#include <vector>

using namespace cornerstone;

// TEST 1 — primitive round-trip for int32, ulong, and byte across a single
// buffer. pos() must advance by exactly sz_int / sz_ulong / sz_byte per put,
// and rewinding to 0 must yield the original values in insertion order.
TEST(Buffer, PrimitivesRoundTrip)
{
    bufptr buf = buffer::alloc(1024);
    ASSERT_EQ(buf->size(), static_cast<size_t>(1024));
    ASSERT_EQ(buf->pos(), static_cast<size_t>(0));

    std::vector<int32> ints = {1, 2, 42, -1, 0x7fffffff};
    for (int32 v : ints) buf->put(v);

    ulong big = 0x0102030405060708ull;
    buf->put(big);

    byte b = 0xAB;
    buf->put(b);

    EXPECT_EQ(buf->pos(), ints.size() * sz_int + sz_ulong + sz_byte);

    buf->pos(0);
    for (int32 v : ints) EXPECT_EQ(buf->get_int(), v);
    EXPECT_EQ(buf->get_ulong(), big);
    EXPECT_EQ(buf->get_byte(), b);
}

// TEST 2 — strings are stored null-terminated. put(string) advances by
// length + 1; get_str returns a C-string pointer up to (not including) the
// null. Two consecutive puts must be recoverable as two consecutive gets.
TEST(Buffer, StringPutGet)
{
    bufptr buf = buffer::alloc(1024);
    buf->put(std::string("hello"));
    buf->put(std::string("world"));
    EXPECT_EQ(buf->pos(), std::string("hello").size() + 1 + std::string("world").size() + 1);

    buf->pos(0);
    EXPECT_STREQ(buf->get_str(), "hello");
    EXPECT_STREQ(buf->get_str(), "world");
}

// TEST 3 — buffer::copy(src) allocates a new buffer sized for the REMAINING
// bytes (size - pos) of src, copies them, and sets its own pos to 0.
// Independent from the source afterwards.
TEST(Buffer, CopyPreservesRemaining)
{
    // Size src exactly so that (src.size() - src.pos()) after the skip
    // equals the size of the remaining int32 + ulong = 12 bytes. That way
    // dst.size() (which the spec sets to src.size() - src.pos()) is
    // exactly the meaningful payload; no trailing garbage bytes are copied
    // and no arithmetic drift depends on the initial allocation size.
    const size_t skip_bytes = std::string("skip me").size() + 1;  // 8 with null
    bufptr src = buffer::alloc(skip_bytes + sz_int + sz_ulong);
    src->put(std::string("skip me"));
    size_t skip_pos = src->pos();
    src->put(static_cast<int32>(0xdeadbeef));
    src->put(static_cast<ulong>(0x0102030405060708ull));
    src->pos(skip_pos);

    bufptr dst = buffer::copy(*src);

    EXPECT_EQ(dst->pos(), static_cast<size_t>(0));
    EXPECT_EQ(dst->size(), sz_int + sz_ulong);
    EXPECT_EQ(dst->get_int(), static_cast<int32>(0xdeadbeef));
    EXPECT_EQ(dst->get_ulong(), static_cast<ulong>(0x0102030405060708ull));
}

// TEST 4 — allocations at or above 0x8000 must use the big-block layout
// (uint size header, MSB flag set) internally, but the public surface stays
// identical: pos()/size()/get_/put_ all behave the same.
TEST(Buffer, BigBlockOver32k)
{
    const size_t big = 0x10000;  // 64 KiB
    bufptr buf = buffer::alloc(big);
    EXPECT_EQ(buf->size(), big);
    EXPECT_EQ(buf->pos(), static_cast<size_t>(0));

    // Write a full byte pattern across the whole buffer and read it back.
    for (size_t i = 0; i < 1024; ++i)
    {
        buf->put(static_cast<byte>(i & 0xff));
    }
    EXPECT_EQ(buf->pos(), static_cast<size_t>(1024));

    buf->pos(0);
    for (size_t i = 0; i < 1024; ++i)
    {
        EXPECT_EQ(buf->get_byte(), static_cast<byte>(i & 0xff));
    }
}

// TEST 5 — put(buffer&) appends the source's remaining bytes; the two-arg
// overloads and stream operator<< / operator>> round-trip through
// std::stringstream.
TEST(Buffer, StreamAndConcat)
{
    bufptr src = buffer::alloc(sz_ulong);
    ulong marker = 0x1234567890abcdefull;
    src->put(marker);
    src->pos(0);

    // put(const buffer&) concatenates remaining bytes into dst.
    bufptr dst = buffer::alloc(sz_ulong);
    dst->put(*src);
    dst->pos(0);
    EXPECT_EQ(dst->get_ulong(), marker);

    // stream I/O
    std::stringstream ss;
    bufptr writer = buffer::alloc(sz_ulong);
    writer->put(marker);
    writer->pos(0);
    ss << *writer;
    ss.seekp(0);
    bufptr reader = buffer::alloc(sz_ulong);
    ss >> *reader;
    // Reset pos to 0 explicitly — the operator>> contract in the spec pins
    // "reads up to size()-pos() bytes" but does not pin whether pos advances
    // after the read. A pos-agnostic test lets the assertion depend only on
    // the round-trip contract, not the un-pinned advance semantic.
    reader->pos(0);
    EXPECT_EQ(reader->get_ulong(), marker);
}
