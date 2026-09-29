// End-to-end coverage of the flat layout: the FlatMessage / DynamicMessage readers and
// the flat serializer path — explicit vs implicit presence, sized fields, default/tail/skip
// optimizations, nested messages, and forward/backward schema evolution (deleted-field
// correction read through an evolved meta).
#include "doctest.h"
#include "yaff_test_meta.h"

#include <yaff/serializer.h>
#include <yaff/message.h>

#include <stdexcept>

using namespace yaffmeta;

TEST_CASE("flat message - full record round-trips every field with presence (explicit+sized)") {
    yaff::Serializer ys;
    ys.StartFlatMessage<RecordV1>(/*implicit*/ false, /*sized*/ true);
    ys.AddField<uint64_t>(5, 500, 0);   // fields added high id -> low id
    ys.AddField<bool>(4, true, false);
    ys.AddField<uint64_t>(3, 300, 0);
    ys.AddField<uint32_t>(2, 200, 0);
    ys.AddField<uint64_t>(1, 100, 0);
    ys.Finish(yaff::InternalOffset<>{ys.FinishFlatMessage()});

    const auto& msg = yaff::ReadMessage<yaff::DynamicMessage<RecordV1>>(ys.Data());
    CHECK(msg.ReadValue<uint64_t>(1, 0) == 100ULL);
    CHECK(msg.ReadValue<uint32_t>(2, 0) == 200U);
    CHECK(msg.ReadValue<uint64_t>(3, 0) == 300ULL);
    CHECK(msg.ReadValue<bool>(4, false) == true);
    CHECK(msg.ReadValue<uint64_t>(5, 0) == 500ULL);
    CHECK(msg.ReadPresence<uint64_t>(1));
    CHECK(msg.ReadPresence<bool>(4));
    CHECK(msg.ReadPresence<uint64_t>(5));
}

TEST_CASE("flat message - default skipped and tail-trimmed fields read back as defaults") {
    // Only id1 and id3 set; id2/id4/id5 left out entirely. Absent fields must read their
    // supplied default, and presence must be false for them.
    yaff::Serializer ys;
    ys.StartFlatMessage<RecordV1>(/*implicit*/ false, /*sized*/ true);
    ys.AddField<uint64_t>(3, 0x3333, 0);
    ys.AddField<uint64_t>(1, 0x11, 0);
    ys.Finish(yaff::InternalOffset<>{ys.FinishFlatMessage()});

    const auto& msg = yaff::ReadMessage<yaff::DynamicMessage<RecordV1>>(ys.Data());
    CHECK(msg.ReadValue<uint64_t>(1, 0) == 0x11ULL);
    CHECK(msg.ReadValue<uint64_t>(3, 0) == 0x3333ULL);
    CHECK(msg.ReadValue<uint32_t>(2, 0xABCD) == 0xABCDU);    // unset -> default
    CHECK(msg.ReadValue<bool>(4, true) == true);             // unset -> default
    CHECK(msg.ReadValue<uint64_t>(5, 0x9999) == 0x9999ULL);  // tail-trimmed -> default
    CHECK(msg.ReadPresence<uint64_t>(1));
    CHECK_FALSE(msg.ReadPresence<uint32_t>(2));
    CHECK_FALSE(msg.ReadPresence<uint64_t>(5));

    // Tail/skip: the stored region only spans up to the highest present field, so leaving the id5
    // tail unset must yield a strictly smaller buffer than the same message that stores it. Only
    // the relation is asserted — the metadata header encoding fixes no exact byte count.
    yaff::Serializer withTail;
    withTail.StartFlatMessage<RecordV1>(/*implicit*/ false, /*sized*/ true);
    withTail.AddField<uint64_t>(5, 0x5555, 0);
    withTail.AddField<uint64_t>(3, 0x3333, 0);
    withTail.AddField<uint64_t>(1, 0x11, 0);
    withTail.Finish(yaff::InternalOffset<>{withTail.FinishFlatMessage()});
    CHECK(ys.Size() < withTail.Size());
}

TEST_CASE("flat message - empty message reads all defaults and has no present fields") {
    yaff::Serializer ys;
    ys.StartFlatMessage<RecordV1>(/*implicit*/ false, /*sized*/ true);
    ys.Finish(yaff::InternalOffset<>{ys.FinishFlatMessage()});

    const auto& msg = yaff::ReadMessage<yaff::DynamicMessage<RecordV1>>(ys.Data());
    CHECK(msg.ReadValue<uint64_t>(1, 0xDEAD) == 0xDEADULL);
    CHECK(msg.ReadValue<uint64_t>(5, 0xBEEF) == 0xBEEFULL);
    CHECK_FALSE(msg.ReadPresence<uint64_t>(1));
    CHECK_FALSE(msg.ReadPresence<uint64_t>(5));
}

TEST_CASE("flat message - schema evolution: V1 wire read through V2 meta with deleted ids") {
    // Write a dense V1 record; read it through V2 where ids 2 and 3 were removed and id6
    // added. The reader applies deleted-field offset correction.
    yaff::Serializer ys;
    ys.StartFlatMessage<RecordV1>(/*implicit*/ false, /*sized*/ true);
    ys.AddField<uint64_t>(5, 10, 10);
    ys.AddField<bool>(4, true, false);
    ys.AddField<uint64_t>(3, 15, 10);
    ys.AddField<uint32_t>(2, 0, 0);
    ys.AddField<uint64_t>(1, 20, 0);
    ys.Finish(yaff::InternalOffset<>{ys.FinishFlatMessage()});

    const auto& msg = yaff::ReadMessage<yaff::DynamicMessage<RecordV2>>(ys.Data());
    CHECK(msg.ReadPresence<uint64_t>(1));
    CHECK(msg.ReadValue<uint64_t>(1, 0) == 20ULL);
    CHECK(msg.ReadPresence<bool>(4));
    CHECK(msg.ReadValue<bool>(4, false) == true);
    CHECK(msg.ReadPresence<uint64_t>(5));
    CHECK(msg.ReadValue<uint64_t>(5, 10) == 10ULL);
    CHECK_FALSE(msg.ReadPresence<uint32_t>(6));            // added field, absent on V1 wire
    CHECK(msg.ReadValue<uint32_t>(6, 1337) == 1337U);
}

TEST_CASE("flat message - implicit presence with sized correction across schema evolution") {
    yaff::Serializer ys;
    ys.StartFlatMessage<FlagsV1>(/*implicit*/ true, /*sized*/ true);
    ys.AddField<uint64_t>(4, 10, 0);
    ys.AddField<uint32_t>(3, 8, 8);   // equals default -> implicit drop
    ys.AddField<uint32_t>(2, 1, 2);
    ys.AddField<bool>(1, false, false);
    ys.Finish(yaff::InternalOffset<>{ys.FinishFlatMessage()});

    const auto& msg = yaff::ReadMessage<yaff::DynamicMessage<FlagsV2>>(ys.Data());
    CHECK(msg.ReadPresence<uint64_t>(2));
    CHECK(msg.ReadValue<uint32_t>(2, 1) == 2U);
    // id3 was written value == default in implicit mode -> dropped on the wire, so it reads back as
    // the supplied default and is not present (read at the field's own uint32 width).
    CHECK(msg.ReadValue<uint32_t>(3, 8) == 8U);
    CHECK_FALSE(msg.ReadPresence<uint32_t>(3));
}

TEST_CASE("flat message - fields added out of order are rejected") {
    yaff::Serializer ys;
    ys.StartFlatMessage<RecordV1>(/*implicit*/ false, /*sized*/ true);
    ys.AddField<uint64_t>(1, 100, 0);  // low id first
    // Adding a higher id afterwards violates the reverse-declaration-order rule.
    CHECK_THROWS_AS(ys.AddField<uint64_t>(5, 500, 0), std::runtime_error);
}

TEST_CASE("flat message - default reader instance returns defaults") {
    const auto& def = yaff::DynamicMessage<RecordV1>::Default();
    CHECK(def.ReadValue<uint64_t>(1, 0x42) == 0x42ULL);
    CHECK_FALSE(def.ReadPresence<uint64_t>(1));
}
