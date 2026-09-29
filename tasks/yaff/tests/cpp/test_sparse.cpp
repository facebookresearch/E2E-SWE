// End-to-end coverage of the sparse layout: the self-describing SparseMessage reader and
// the sparse serializer path — tiny (id < 32, 1-byte) vs wide (id >= 32, 2-byte) offset
// metas, scalar and nested-offset fields, implicit default dropping, and reading the same
// wire through DynamicMessage.
#include "doctest.h"
#include "yaff_test_meta.h"

#include <yaff/serializer.h>
#include <yaff/message.h>

#include <stdexcept>

using namespace yaffmeta;

TEST_CASE("sparse message - scalar fields across tiny and wide id ranges round-trip") {
    yaff::Serializer ys;
    ys.StartSparseMessage();  // explicit: stores even default-valued fields
    ys.AddField<uint64_t>(40, 0xABCD, 0);  // id >= 32 -> wide 2-byte offset slot
    ys.AddField<uint32_t>(5, 55, 0);
    ys.AddField<int32_t>(1, -7, 0);        // id < 32 -> tiny 1-byte offset slot
    ys.Finish(yaff::InternalOffset<>{ys.FinishSparseMessage()});

    const auto& msg = yaff::ReadMessage<yaff::SparseMessage>(ys.Data());
    CHECK(msg.ReadValue<int32_t>(1, 0) == -7);
    CHECK(msg.ReadValue<uint32_t>(5, 0) == 55U);
    CHECK(msg.ReadValue<uint64_t>(40, 0) == 0xABCDULL);
    CHECK(msg.ReadPresence<int32_t>(1));
    CHECK(msg.ReadPresence<uint64_t>(40));
    // A field id that was never written reads its default and is absent.
    CHECK(msg.ReadValue<uint32_t>(9, 0x1234) == 0x1234U);
    CHECK_FALSE(msg.ReadPresence<uint32_t>(9));
}

TEST_CASE("sparse message - implicit mode drops default-valued fields") {
    yaff::Serializer ys;
    ys.StartSparseMessage(/*implicit*/ true);
    ys.AddField<uint64_t>(3, 0x3333, 0x6789);
    ys.AddField<uint32_t>(2, 0xAF, 0xAF);  // equals default -> dropped on the wire
    ys.AddField<int32_t>(1, -0x10, 0);
    ys.Finish(yaff::InternalOffset<>{ys.FinishSparseMessage()});

    const auto& msg = yaff::ReadMessage<yaff::SparseMessage>(ys.Data());
    CHECK(msg.ReadValue<int32_t>(1, 0) == -0x10);
    CHECK(msg.ReadValue<uint64_t>(3, 0) == 0x3333ULL);
    CHECK(msg.ReadValue<uint32_t>(2, 0xAF) == 0xAFU);   // dropped -> default
    CHECK(msg.ReadPresence<int32_t>(1));
    CHECK_FALSE(msg.ReadPresence<uint32_t>(2));          // dropped -> absent
}

TEST_CASE("sparse message - nested fixed message resolves through an offset field") {
    yaff::Serializer ys;

    // Build the nested fixed pair first, then reference it by offset from the sparse parent.
    ys.StartFixedMessage<FixedPair>();
    ys.AddField<uint64_t>(2, 0x22, 0x0);
    ys.AddField<uint64_t>(1, 0x11, 0x0);
    const auto nested = ys.FinishFixedMessage();

    ys.StartSparseMessage();
    ys.AddField(2, yaff::InternalOffset<void>(nested));
    ys.AddField<uint64_t>(1, 0x99, 0);
    ys.Finish(yaff::InternalOffset<>{ys.FinishSparseMessage()});

    const auto& msg = yaff::ReadMessage<yaff::SparseMessage>(ys.Data());
    CHECK(msg.ReadValue<uint64_t>(1, 0) == 0x99ULL);
    const auto& inner =
        *msg.ReadLayout<yaff::FixedMessage<FixedPair>>(2, &yaff::FixedMessage<FixedPair>::Default());
    CHECK(inner.ReadValue<uint64_t>(1, 0) == 0x11ULL);
    CHECK(inner.ReadValue<uint64_t>(2, 0) == 0x22ULL);
    CHECK(msg.ReadPresence<yaff::FixedMessage<FixedPair>>(2));
}

TEST_CASE("sparse message - same wire is also readable through DynamicMessage") {
    yaff::Serializer ys;
    ys.StartSparseMessage();
    ys.AddField<uint64_t>(5, 500, 0);
    ys.AddField<uint64_t>(1, 100, 0);
    ys.Finish(yaff::InternalOffset<>{ys.FinishSparseMessage()});

    // DynamicMessage<M> sees the sparse typed-limit on the wire and dispatches to the
    // sparse reader even though M describes a flat layout.
    const auto& msg = yaff::ReadMessage<yaff::DynamicMessage<RecordV1>>(ys.Data());
    CHECK(msg.ReadValue<uint64_t>(1, 0) == 100ULL);
    CHECK(msg.ReadValue<uint64_t>(5, 0) == 500ULL);
    CHECK(msg.ReadPresence<uint64_t>(1));
    CHECK_FALSE(msg.ReadPresence<uint64_t>(3));
}

TEST_CASE("sparse message - rejects id 0 and ascending fill order") {
    yaff::Serializer ys1;
    ys1.StartSparseMessage();
    CHECK_THROWS_AS(ys1.AddField<int32_t>(0, 1, 0), std::runtime_error);  // id must be > 0

    yaff::Serializer ys2;
    ys2.StartSparseMessage();
    ys2.AddField<uint32_t>(2, 5, 0);
    // Ids must be added strictly descending; a higher id afterwards is rejected.
    CHECK_THROWS_AS(ys2.AddField<uint64_t>(4, 9, 0), std::runtime_error);
}
