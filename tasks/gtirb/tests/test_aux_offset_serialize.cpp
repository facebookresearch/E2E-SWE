// gtirb WRG task — subsystem: aux_offset_serialize (AuxData schemas
// UUID-keyed + Offset-keyed, Offset comparison + map key, IR save/load
// round-trip preserving structure and UUIDs, round-trip with AuxData,
// ErrorOr-based failure path for load).

#include "test_common.hpp"

// ============================================================================
// 19. AuxData registration + add + get for UUID-keyed schemas
// ============================================================================
TEST(GtirbAuxData, RegisterAddGetForUuidKeyedSchemas) {
    AuxDataContainer::registerAuxDataType<schema::FunctionNames>();
    AuxDataContainer::registerAuxDataType<schema::Alignment>();

    Context ctx;
    IR* ir = IR::Create(ctx);
    Module* m = ir->addModule(Module::Create(ctx, "prog"));

    Symbol* main_sym = m->addSymbol(Symbol::Create(ctx, Addr(0x1000), "main"));

    UUID fake_fn_uuid{};
    for (auto& byte : fake_fn_uuid) byte = 0x42;

    std::map<UUID, UUID> names{{fake_fn_uuid, main_sym->getUUID()}};
    m->addAuxData<schema::FunctionNames>(std::move(names));

    auto* got = m->getAuxData<schema::FunctionNames>();
    ASSERT_NE(got, nullptr);
    ASSERT_EQ(got->size(), 1u);
    auto it = got->find(fake_fn_uuid);
    ASSERT_NE(it, got->end());
    EXPECT_EQ(it->second, main_sym->getUUID());

    UUID node_uuid = m->getUUID();
    std::map<UUID, uint64_t> aligns{{node_uuid, 16}};
    m->addAuxData<schema::Alignment>(std::move(aligns));

    auto* aligns_got = m->getAuxData<schema::Alignment>();
    ASSERT_NE(aligns_got, nullptr);
    EXPECT_EQ((*aligns_got)[node_uuid], 16u);

    Module* m2 = ir->addModule(Module::Create(ctx, "second"));
    EXPECT_EQ(m2->getAuxData<schema::FunctionNames>(), nullptr);
    EXPECT_EQ(m2->getAuxData<schema::Alignment>(), nullptr);
}

// ============================================================================
// 20. AuxData: Offset-keyed schemas (Comments, Padding) + removeAuxData
// ============================================================================
TEST(GtirbAuxData, OffsetKeyedSchemasAndRemoveAuxData) {
    AuxDataContainer::registerAuxDataType<schema::Comments>();
    AuxDataContainer::registerAuxDataType<schema::Padding>();

    Context ctx;
    IR* ir = IR::Create(ctx);
    Module* m = ir->addModule(Module::Create(ctx, "prog"));
    Section* s = m->addSection(ctx, ".text");
    ByteInterval* bi = s->addByteInterval(ctx, Addr(0x1000), 0x100);
    CodeBlock* cb = bi->addBlock<CodeBlock>(ctx, 0x10, 4);

    Offset o1(cb->getUUID(), 0);
    Offset o2(cb->getUUID(), 2);
    std::map<Offset, std::string> comments{
        {o1, "start of block"},
        {o2, "after prologue"},
    };
    m->addAuxData<schema::Comments>(std::move(comments));

    auto* got = m->getAuxData<schema::Comments>();
    ASSERT_NE(got, nullptr);
    ASSERT_EQ(got->size(), 2u);
    EXPECT_EQ(got->at(o1), "start of block");
    EXPECT_EQ(got->at(o2), "after prologue");

    std::map<Offset, uint64_t> padding{{o1, 8}, {o2, 16}};
    m->addAuxData<schema::Padding>(std::move(padding));

    auto* pad_got = m->getAuxData<schema::Padding>();
    ASSERT_NE(pad_got, nullptr);
    EXPECT_EQ(pad_got->at(o1), 8u);
    EXPECT_EQ(pad_got->at(o2), 16u);

    EXPECT_TRUE(m->removeAuxData<schema::Comments>());
    EXPECT_EQ(m->getAuxData<schema::Comments>(), nullptr);
    EXPECT_NE(m->getAuxData<schema::Padding>(), nullptr);

    EXPECT_FALSE(m->removeAuxData<schema::Comments>());
}

// ============================================================================
// 21. Offset: comparison and use as a std::map key
// ============================================================================
TEST(GtirbOffset, ComparisonAndMapKey) {
    UUID u1{}; for (auto& b : u1) b = 0x11;
    UUID u2{}; for (auto& b : u2) b = 0x22;

    Offset a(u1, 10);
    Offset b(u1, 20);
    Offset c(u2, 5);

    EXPECT_TRUE(Offset(u1, 10) == a);
    EXPECT_FALSE(a == b);
    EXPECT_TRUE(a != b);

    EXPECT_TRUE(a < b);
    // ElementId is the primary sort key (lex order over (ElementId,
    // Displacement)): u1 (all 0x11) orders before u2 (all 0x22), so a (u1,*)
    // precedes c (u2,*) regardless of displacement. A Displacement-only
    // comparator would instead order c < a (5 < 10), so this pins the
    // ElementId dimension of operator<.
    EXPECT_TRUE(a < c);
    EXPECT_FALSE(c < a);
    EXPECT_FALSE(a == c);

    // A key that shares a's displacement but differs only in ElementId must
    // still be unequal and ordered by ElementId — rejecting a
    // Displacement-only operator== / operator<.
    Offset d(u2, 10);
    EXPECT_TRUE(a != d);
    EXPECT_FALSE(a == d);
    EXPECT_TRUE(a < d);

    std::map<Offset, int> m;
    m[a] = 1;
    m[b] = 2;
    m[c] = 3;
    EXPECT_EQ(m.size(), 3u);
    EXPECT_EQ(m[a], 1);
    EXPECT_EQ(m[b], 2);
    EXPECT_EQ(m[c], 3);
}

// ============================================================================
// 22. IR round-trip via save/load preserves structure and UUIDs
// ============================================================================
TEST(GtirbSerialization, SaveLoadRoundTripPreservesStructureAndUuids) {
    Context ctx1;
    IR* ir1 = IR::Create(ctx1);
    // Note: getVersion()/setVersion() carry the on-disk protobuf schema
    // version. The default (matching the library's built-in schema) is what
    // save/load expect; overriding it here would trigger a load failure.

    Module* m1 = ir1->addModule(Module::Create(ctx1, "prog"));
    m1->setFileFormat(FileFormat::ELF);
    m1->setISA(ISA::X64);
    m1->setByteOrder(ByteOrder::Little);

    Section* sec1 = m1->addSection(ctx1, ".text");
    sec1->addFlag(SectionFlag::Readable);
    sec1->addFlag(SectionFlag::Executable);

    ByteInterval* bi1 = sec1->addByteInterval(ctx1, Addr(0x1000), 0x40);
    CodeBlock* cb1 = bi1->addBlock<CodeBlock>(ctx1, 0x10, 4);

    Symbol* sym1 = m1->addSymbol(Symbol::Create(ctx1, cb1, "main"));

    UUID u_ir  = ir1->getUUID();
    UUID u_m   = m1->getUUID();
    UUID u_sec = sec1->getUUID();
    UUID u_bi  = bi1->getUUID();
    UUID u_cb  = cb1->getUUID();
    UUID u_sym = sym1->getUUID();

    std::stringstream buffer;
    ir1->save(buffer);

    Context ctx2;
    ErrorOr<IR*> loaded = IR::load(ctx2, buffer);
    ASSERT_TRUE(static_cast<bool>(loaded));
    IR* ir2 = *loaded;

    EXPECT_EQ(ir2->getUUID(), u_ir);
    // Version is preserved across save/load and matches the source IR.
    EXPECT_EQ(ir2->getVersion(), ir1->getVersion());

    auto mods = ptrs_of(ir2->modules());
    ASSERT_EQ(mods.size(), 1u);
    Module* m2 = mods[0];
    EXPECT_EQ(m2->getUUID(), u_m);
    EXPECT_EQ(m2->getName(), "prog");
    EXPECT_EQ(m2->getFileFormat(), FileFormat::ELF);
    EXPECT_EQ(m2->getISA(), ISA::X64);
    EXPECT_EQ(m2->getByteOrder(), ByteOrder::Little);

    auto secs = ptrs_of(m2->sections());
    ASSERT_EQ(secs.size(), 1u);
    Section* sec2 = secs[0];
    EXPECT_EQ(sec2->getUUID(), u_sec);
    EXPECT_EQ(sec2->getName(), ".text");
    EXPECT_TRUE(sec2->isFlagSet(SectionFlag::Readable));
    EXPECT_TRUE(sec2->isFlagSet(SectionFlag::Executable));

    auto bis = ptrs_of(sec2->byte_intervals());
    ASSERT_EQ(bis.size(), 1u);
    ByteInterval* bi2 = bis[0];
    EXPECT_EQ(bi2->getUUID(), u_bi);
    ASSERT_TRUE(bi2->getAddress().has_value());
    EXPECT_EQ(static_cast<uint64_t>(*bi2->getAddress()), 0x1000u);

    auto cbs = ptrs_of(bi2->code_blocks());
    ASSERT_EQ(cbs.size(), 1u);
    CodeBlock* cb2 = cbs[0];
    EXPECT_EQ(cb2->getUUID(), u_cb);
    EXPECT_EQ(cb2->getSize(), 4u);
    EXPECT_EQ(cb2->getOffset(), 0x10u);

    auto syms = ptrs_of(m2->symbols());
    ASSERT_EQ(syms.size(), 1u);
    Symbol* sym2 = syms[0];
    EXPECT_EQ(sym2->getUUID(), u_sym);
    EXPECT_EQ(sym2->getName(), "main");
    EXPECT_EQ(sym2->getReferent<CodeBlock>(), cb2);
}

// ============================================================================
// 23. IR round-trip with registered AuxData
// ============================================================================
TEST(GtirbSerialization, SaveLoadRoundTripWithAuxData) {
    AuxDataContainer::registerAuxDataType<schema::Alignment>();
    AuxDataContainer::registerAuxDataType<schema::Comments>();

    Context ctx1;
    IR* ir1 = IR::Create(ctx1);
    Module* m1 = ir1->addModule(Module::Create(ctx1, "prog"));

    std::map<UUID, uint64_t> aligns{{m1->getUUID(), 32}};
    m1->addAuxData<schema::Alignment>(std::move(aligns));

    Offset o1(m1->getUUID(), 8);
    std::map<Offset, std::string> comments{{o1, "hello"}};
    m1->addAuxData<schema::Comments>(std::move(comments));

    std::stringstream buffer;
    ir1->save(buffer);

    Context ctx2;
    ErrorOr<IR*> loaded = IR::load(ctx2, buffer);
    ASSERT_TRUE(static_cast<bool>(loaded));
    IR* ir2 = *loaded;

    auto mods = ptrs_of(ir2->modules());
    ASSERT_EQ(mods.size(), 1u);
    Module* m2 = mods[0];
    auto* a_back = m2->getAuxData<schema::Alignment>();
    ASSERT_NE(a_back, nullptr);
    ASSERT_EQ(a_back->size(), 1u);
    EXPECT_EQ(a_back->at(m2->getUUID()), 32u);

    auto* c_back = m2->getAuxData<schema::Comments>();
    ASSERT_NE(c_back, nullptr);
    ASSERT_EQ(c_back->size(), 1u);
    Offset o2(m2->getUUID(), 8);
    EXPECT_EQ(c_back->at(o2), "hello");
}

// ============================================================================
// 24. IR::load rejects malformed input via ErrorOr
// ============================================================================
TEST(GtirbSerialization, LoadRejectsBadMagicViaErrorOr) {
    Context ctx;

    std::string garbage("NOTGTIRB\x00\x01\x02\x03\x04", 13);
    std::stringstream ss(garbage);

    ErrorOr<IR*> result = IR::load(ctx, ss);
    EXPECT_FALSE(static_cast<bool>(result));
}

// ============================================================================
// 26. AuxData: std::variant<> payload round-trips through save/load, and
//     the active alternative is preserved.
// ============================================================================
namespace gtirb_wrg_test_schemas {
    struct VariantPayload {
        static constexpr const char* Name = "wrgVariantPayload";
        typedef std::variant<uint64_t, std::string, gtirb::Addr> Type;
    };
}

TEST(GtirbAuxData, VariantPayloadRoundTrip) {
    AuxDataContainer::registerAuxDataType<
        gtirb_wrg_test_schemas::VariantPayload>();

    // --- alt 1: std::string ---
    {
        Context ctx1;
        IR* ir1 = IR::Create(ctx1);
        Module* m1 = ir1->addModule(Module::Create(ctx1, "prog"));
        gtirb_wrg_test_schemas::VariantPayload::Type val{std::string("hi")};
        m1->addAuxData<gtirb_wrg_test_schemas::VariantPayload>(std::move(val));

        std::stringstream buffer;
        ir1->save(buffer);

        Context ctx2;
        ErrorOr<IR*> loaded = IR::load(ctx2, buffer);
        ASSERT_TRUE(static_cast<bool>(loaded));
        auto mods = ptrs_of((*loaded)->modules());
        ASSERT_EQ(mods.size(), 1u);
        auto* got =
            mods[0]->getAuxData<gtirb_wrg_test_schemas::VariantPayload>();
        ASSERT_NE(got, nullptr);
        ASSERT_EQ(got->index(), 1u);
        EXPECT_EQ(std::get<std::string>(*got), "hi");
    }

    // --- alt 0: uint64_t ---
    {
        Context ctx1;
        IR* ir1 = IR::Create(ctx1);
        Module* m1 = ir1->addModule(Module::Create(ctx1, "prog"));
        gtirb_wrg_test_schemas::VariantPayload::Type val{uint64_t{0xdeadbeef}};
        m1->addAuxData<gtirb_wrg_test_schemas::VariantPayload>(std::move(val));

        std::stringstream buffer;
        ir1->save(buffer);

        Context ctx2;
        ErrorOr<IR*> loaded = IR::load(ctx2, buffer);
        ASSERT_TRUE(static_cast<bool>(loaded));
        auto mods = ptrs_of((*loaded)->modules());
        ASSERT_EQ(mods.size(), 1u);
        auto* got =
            mods[0]->getAuxData<gtirb_wrg_test_schemas::VariantPayload>();
        ASSERT_NE(got, nullptr);
        ASSERT_EQ(got->index(), 0u);
        EXPECT_EQ(std::get<uint64_t>(*got), 0xdeadbeefu);
    }
}

// ============================================================================
// 36. AuxData: nested container round-trip — map<UUID, set<UUID>>
//     (upstream calls this pattern FunctionEntries).
// ============================================================================
namespace gtirb_wrg_test_schemas {
    struct NestedUuidSets {
        static constexpr const char* Name = "wrgNestedUuidSets";
        typedef std::map<gtirb::UUID, std::set<gtirb::UUID>> Type;
    };
}

TEST(GtirbAuxData, NestedContainerRoundTrip) {
    AuxDataContainer::registerAuxDataType<
        gtirb_wrg_test_schemas::NestedUuidSets>();

    UUID k1{}; for (auto& b : k1) b = 0x11;
    UUID k2{}; for (auto& b : k2) b = 0x22;
    UUID v1{}; for (auto& b : v1) b = 0xa1;
    UUID v2{}; for (auto& b : v2) b = 0xa2;
    UUID v3{}; for (auto& b : v3) b = 0xa3;

    Context ctx1;
    IR* ir1 = IR::Create(ctx1);
    Module* m1 = ir1->addModule(Module::Create(ctx1, "prog"));

    gtirb_wrg_test_schemas::NestedUuidSets::Type payload{
        {k1, {v1, v2}},
        {k2, {v3}},
    };
    m1->addAuxData<gtirb_wrg_test_schemas::NestedUuidSets>(std::move(payload));

    std::stringstream buffer;
    ir1->save(buffer);

    Context ctx2;
    ErrorOr<IR*> loaded = IR::load(ctx2, buffer);
    ASSERT_TRUE(static_cast<bool>(loaded));
    auto mods = ptrs_of((*loaded)->modules());
    ASSERT_EQ(mods.size(), 1u);

    auto* got =
        mods[0]->getAuxData<gtirb_wrg_test_schemas::NestedUuidSets>();
    ASSERT_NE(got, nullptr);
    ASSERT_EQ(got->size(), 2u);

    ASSERT_EQ(got->count(k1), 1u);
    const auto& s1 = got->at(k1);
    EXPECT_EQ(s1.size(), 2u);
    EXPECT_EQ(s1.count(v1), 1u);
    EXPECT_EQ(s1.count(v2), 1u);

    ASSERT_EQ(got->count(k2), 1u);
    const auto& s2 = got->at(k2);
    EXPECT_EQ(s2.size(), 1u);
    EXPECT_EQ(s2.count(v3), 1u);
}

// ============================================================================
// 37. AuxData: std::tuple<> payload round-trip — the tuple's elements must
//     survive save/load in order.
// ============================================================================
namespace gtirb_wrg_test_schemas {
    struct TuplePayload {
        static constexpr const char* Name = "wrgTuplePayload";
        typedef std::tuple<uint64_t, std::string, gtirb::Addr> Type;
    };
}

TEST(GtirbAuxData, TuplePayloadRoundTrip) {
    AuxDataContainer::registerAuxDataType<
        gtirb_wrg_test_schemas::TuplePayload>();

    Context ctx1;
    IR* ir1 = IR::Create(ctx1);
    Module* m1 = ir1->addModule(Module::Create(ctx1, "prog"));

    gtirb_wrg_test_schemas::TuplePayload::Type payload{
        uint64_t{42},
        std::string("hello"),
        Addr(0xdeadbeef),
    };
    m1->addAuxData<gtirb_wrg_test_schemas::TuplePayload>(std::move(payload));

    std::stringstream buffer;
    ir1->save(buffer);

    Context ctx2;
    ErrorOr<IR*> loaded = IR::load(ctx2, buffer);
    ASSERT_TRUE(static_cast<bool>(loaded));
    auto mods = ptrs_of((*loaded)->modules());
    ASSERT_EQ(mods.size(), 1u);

    auto* got =
        mods[0]->getAuxData<gtirb_wrg_test_schemas::TuplePayload>();
    ASSERT_NE(got, nullptr);
    EXPECT_EQ(std::get<0>(*got), 42u);
    EXPECT_EQ(std::get<1>(*got), "hello");
    EXPECT_EQ(static_cast<uint64_t>(std::get<2>(*got)), 0xdeadbeefu);
}

