// gtirb WRG task — subsystem: module_section (IR/Module lifecycle, Module
// metadata, Section flags + aggregation, Section address queries).

#include "test_common.hpp"

// ============================================================================
// 4. IR / Module lifecycle: create, add, iterate, remove
// ============================================================================
TEST(GtirbIrModule, LifecycleAddIterateRemove) {
    Context ctx;
    IR* ir = IR::Create(ctx);

    Module* m1 = ir->addModule(Module::Create(ctx, "alpha"));
    Module* m2 = ir->addModule(Module::Create(ctx, "beta"));
    ir->addModule(Module::Create(ctx, "gamma"));

    std::vector<std::string> names;
    for (auto* mp : ptrs_of(ir->modules())) {
        names.push_back(mp->getName());
    }
    ASSERT_EQ(names.size(), 3u);
    EXPECT_EQ(names[0], "alpha");
    EXPECT_EQ(names[1], "beta");
    EXPECT_EQ(names[2], "gamma");

    EXPECT_EQ(m1->getIR(), ir);
    EXPECT_EQ(m2->getIR(), ir);

    EXPECT_TRUE(ir->removeModule(m2));
    EXPECT_FALSE(ir->removeModule(m2));

    std::vector<std::string> after;
    for (auto* mp : ptrs_of(ir->modules())) {
        after.push_back(mp->getName());
    }
    ASSERT_EQ(after.size(), 2u);
    EXPECT_EQ(after[0], "alpha");
    EXPECT_EQ(after[1], "gamma");
}

// ============================================================================
// 5. Module metadata: FileFormat, ISA, ByteOrder, entry point, addresses
// ============================================================================
TEST(GtirbModule, MetadataFileFormatIsaByteOrderAndEntryPoint) {
    Context ctx;
    IR* ir = IR::Create(ctx);
    Module* m = ir->addModule(Module::Create(ctx, "prog"));

    EXPECT_EQ(m->getFileFormat(), FileFormat::Undefined);
    EXPECT_EQ(m->getISA(), ISA::Undefined);
    EXPECT_EQ(m->getByteOrder(), ByteOrder::Undefined);
    EXPECT_EQ(m->getEntryPoint(), nullptr);  // no entry set

    m->setFileFormat(FileFormat::ELF);
    m->setISA(ISA::X64);
    m->setByteOrder(ByteOrder::Little);
    m->setPreferredAddr(Addr(0x400000));
    m->setRebaseDelta(0x1000);
    m->setBinaryPath("/usr/bin/prog");

    EXPECT_EQ(m->getFileFormat(), FileFormat::ELF);
    EXPECT_EQ(m->getISA(), ISA::X64);
    EXPECT_EQ(m->getByteOrder(), ByteOrder::Little);
    EXPECT_EQ(static_cast<uint64_t>(m->getPreferredAddr()), 0x400000u);
    EXPECT_EQ(m->getRebaseDelta(), 0x1000);
    EXPECT_EQ(m->getBinaryPath(), "/usr/bin/prog");

    // Entry point: setEntryPoint(CodeBlock*), getEntryPoint() returns CodeBlock*.
    // The block's address is 0x401020 (interval addr 0x401000 + offset 0x20).
    Section* text = m->addSection(ctx, ".text");
    ByteInterval* bi = text->addByteInterval(ctx, Addr(0x401000), 0x100);
    CodeBlock* entry = bi->addBlock<CodeBlock>(ctx, 0x20, 4);
    m->setEntryPoint(entry);

    CodeBlock* ep = m->getEntryPoint();
    ASSERT_NE(ep, nullptr);
    EXPECT_EQ(ep, entry);
    ASSERT_TRUE(ep->getAddress().has_value());
    EXPECT_EQ(static_cast<uint64_t>(*ep->getAddress()), 0x401020u);
}

// ============================================================================
// 6. Section flags + aggregate address / size
// ============================================================================
TEST(GtirbSection, FlagsAddRemoveQueryAndAggregateAddress) {
    Context ctx;
    IR* ir = IR::Create(ctx);
    Module* m = ir->addModule(Module::Create(ctx, "prog"));
    Section* s = m->addSection(ctx, ".text");

    EXPECT_FALSE(s->isFlagSet(SectionFlag::Readable));
    s->addFlag(SectionFlag::Readable);
    s->addFlag(SectionFlag::Executable);
    s->addFlag(SectionFlag::Loaded);
    EXPECT_TRUE(s->isFlagSet(SectionFlag::Readable));
    EXPECT_TRUE(s->isFlagSet(SectionFlag::Executable));
    EXPECT_TRUE(s->isFlagSet(SectionFlag::Loaded));
    EXPECT_FALSE(s->isFlagSet(SectionFlag::Writable));

    s->addFlag(SectionFlag::Readable);  // dup: no-op
    EXPECT_EQ(range_size(s->flags()), 3u);

    s->removeFlag(SectionFlag::Loaded);
    EXPECT_FALSE(s->isFlagSet(SectionFlag::Loaded));

    EXPECT_FALSE(s->getAddress().has_value());
    EXPECT_FALSE(s->getSize().has_value());

    s->addByteInterval(ctx, Addr(0x1000), 0x100);
    s->addByteInterval(ctx, Addr(0x1200), 0x50);

    auto addr = s->getAddress();
    auto size = s->getSize();
    ASSERT_TRUE(addr.has_value());
    ASSERT_TRUE(size.has_value());
    EXPECT_EQ(static_cast<uint64_t>(*addr), 0x1000u);
    EXPECT_EQ(*size, 0x250u);  // 0x1250 - 0x1000
}

// ============================================================================
// 25. Section::findByteIntervalsOn address query
// ============================================================================
TEST(GtirbSection, FindByteIntervalsOnAddressQuery) {
    Context ctx;
    IR* ir = IR::Create(ctx);
    Module* m = ir->addModule(Module::Create(ctx, "prog"));
    Section* s = m->addSection(ctx, ".data");

    ByteInterval* bi_a = s->addByteInterval(ctx, Addr(0x1000), 0x100);
    ByteInterval* bi_b = s->addByteInterval(ctx, Addr(0x1200), 0x50);
    // A third interval with no fixed address — should never match.
    s->addByteInterval(ctx, std::nullopt, uint64_t{0x20});

    std::set<const ByteInterval*> hits_a;
    for (auto* bip : ptrs_of(s->findByteIntervalsOn(Addr(0x1050)))) {
        hits_a.insert(bip);
    }
    EXPECT_EQ(hits_a.size(), 1u);
    EXPECT_EQ(hits_a.count(bi_a), 1u);

    std::set<const ByteInterval*> hits_b;
    for (auto* bip : ptrs_of(s->findByteIntervalsOn(Addr(0x1220)))) {
        hits_b.insert(bip);
    }
    EXPECT_EQ(hits_b.size(), 1u);
    EXPECT_EQ(hits_b.count(bi_b), 1u);

    EXPECT_EQ(range_size(s->findByteIntervalsOn(Addr(0x2000))), 0u);
}

// ============================================================================
// 27. Module::sections() iterates in address-ascending order (spec:
//     "ordered by address then by name").
// ============================================================================
TEST(GtirbModule, SectionsIterateInAddressOrder) {
    Context ctx;
    IR* ir = IR::Create(ctx);
    Module* m = ir->addModule(Module::Create(ctx, "prog"));

    // Insert in a NON-address order to prove iteration isn't just insertion
    // order. Names chosen so alphabetical order differs from address order.
    Section* s_gamma = m->addSection(ctx, "gamma");
    Section* s_beta  = m->addSection(ctx, "beta");
    Section* s_alpha = m->addSection(ctx, "alpha");

    // Assign addresses: beta @ 0x1000, alpha @ 0x2000, gamma @ 0x3000.
    s_gamma->addByteInterval(ctx, Addr(0x3000), 0x100);
    s_beta ->addByteInterval(ctx, Addr(0x1000), 0x100);
    s_alpha->addByteInterval(ctx, Addr(0x2000), 0x100);

    auto secs = ptrs_of(m->sections());
    ASSERT_EQ(secs.size(), 3u);
    EXPECT_EQ(secs[0], s_beta)  << "first by address (0x1000)";
    EXPECT_EQ(secs[1], s_alpha) << "second by address (0x2000)";
    EXPECT_EQ(secs[2], s_gamma) << "third by address (0x3000)";
}

// ============================================================================
// 28. Module::findByteIntervalsOn: half-open interval semantics at exact
//     boundaries and empty result across gaps between sections.
// ============================================================================
TEST(GtirbModule, FindByteIntervalsOnBoundaryAndGap) {
    Context ctx;
    IR* ir = IR::Create(ctx);
    Module* m = ir->addModule(Module::Create(ctx, "prog"));

    // Two non-overlapping intervals in two separate sections; gap between them.
    Section* s1 = m->addSection(ctx, ".text");
    ByteInterval* bi1 = s1->addByteInterval(ctx, Addr(0x1000), 0x100);

    Section* s2 = m->addSection(ctx, ".data");
    ByteInterval* bi2 = s2->addByteInterval(ctx, Addr(0x2000), 0x100);

    // Exact-start hit (inclusive lower bound).
    {
        auto hits = ptrs_of(m->findByteIntervalsOn(Addr(0x1000)));
        std::set<const ByteInterval*> s(hits.begin(), hits.end());
        EXPECT_EQ(s.size(), 1u);
        EXPECT_EQ(s.count(bi1), 1u);
    }

    // Last-byte hit (Addr + Size - 1 is still within [Addr, Addr+Size)).
    {
        auto hits = ptrs_of(m->findByteIntervalsOn(Addr(0x10FF)));
        std::set<const ByteInterval*> s(hits.begin(), hits.end());
        EXPECT_EQ(s.size(), 1u);
        EXPECT_EQ(s.count(bi1), 1u);
    }

    // Exact-end miss (Addr + Size is EXCLUSIVE upper bound).
    EXPECT_EQ(range_size(m->findByteIntervalsOn(Addr(0x1100))), 0u);

    // Mid-gap between two intervals — miss.
    EXPECT_EQ(range_size(m->findByteIntervalsOn(Addr(0x1500))), 0u);

    // Address inside the second interval hits only bi2 (not bi1).
    {
        auto hits = ptrs_of(m->findByteIntervalsOn(Addr(0x2050)));
        std::set<const ByteInterval*> s(hits.begin(), hits.end());
        EXPECT_EQ(s.size(), 1u);
        EXPECT_EQ(s.count(bi2), 1u);
    }
}

// ============================================================================
// 29. Module::findBlocksOn / findCodeBlocksOn / findDataBlocksOn — address
//     is INSIDE a block's byte range (half-open [addr, addr+size)).
// ============================================================================
TEST(GtirbModule, FindBlocksOnByAddress) {
    Context ctx;
    IR* ir = IR::Create(ctx);
    Module* m = ir->addModule(Module::Create(ctx, "prog"));
    Section* s = m->addSection(ctx, ".text");
    ByteInterval* bi = s->addByteInterval(ctx, Addr(0x1000), 0x100);

    CodeBlock* cb = bi->addBlock<CodeBlock>(ctx, 0x00, 0x20);   // 0x1000..0x1020
    DataBlock* db = bi->addBlock<DataBlock>(ctx, 0x40, 0x10);   // 0x1040..0x1050

    // Mixed range (both kinds) — probes an address inside cb.
    {
        auto hits = ptrs_of(m->findBlocksOn(Addr(0x1010)));
        std::set<const Node*> s2(hits.begin(), hits.end());
        EXPECT_EQ(s2.size(), 1u);
        EXPECT_EQ(s2.count(cb), 1u);
    }
    // Typed find restricted to CodeBlock.
    {
        auto hits = ptrs_of(m->findCodeBlocksOn(Addr(0x1010)));
        std::set<const CodeBlock*> s2(hits.begin(), hits.end());
        EXPECT_EQ(s2.size(), 1u);
        EXPECT_EQ(s2.count(cb), 1u);
    }
    // Typed find restricted to DataBlock — no hit at 0x1010 (that's inside cb).
    EXPECT_EQ(range_size(m->findDataBlocksOn(Addr(0x1010))), 0u);

    // Address inside db.
    {
        auto hits = ptrs_of(m->findDataBlocksOn(Addr(0x1044)));
        std::set<const DataBlock*> s2(hits.begin(), hits.end());
        EXPECT_EQ(s2.size(), 1u);
        EXPECT_EQ(s2.count(db), 1u);
    }
    // Gap between the two blocks — no hit for either kind.
    EXPECT_EQ(range_size(m->findBlocksOn(Addr(0x1030))), 0u);
    EXPECT_EQ(range_size(m->findCodeBlocksOn(Addr(0x1030))), 0u);
    EXPECT_EQ(range_size(m->findDataBlocksOn(Addr(0x1030))), 0u);
}

// ============================================================================
// 30. Module::findBlocksAt / findCodeBlocksAt / findDataBlocksAt — address
//     equals a block's START address exactly.
// ============================================================================
TEST(GtirbModule, FindBlocksAtStartAddress) {
    Context ctx;
    IR* ir = IR::Create(ctx);
    Module* m = ir->addModule(Module::Create(ctx, "prog"));
    Section* s = m->addSection(ctx, ".text");
    ByteInterval* bi = s->addByteInterval(ctx, Addr(0x2000), 0x100);

    CodeBlock* cb = bi->addBlock<CodeBlock>(ctx, 0x00, 0x20);   // starts at 0x2000
    DataBlock* db = bi->addBlock<DataBlock>(ctx, 0x40, 0x10);   // starts at 0x2040

    // Hit at exact start of cb.
    {
        auto hits = ptrs_of(m->findBlocksAt(Addr(0x2000)));
        std::set<const Node*> s2(hits.begin(), hits.end());
        EXPECT_EQ(s2.size(), 1u);
        EXPECT_EQ(s2.count(cb), 1u);
    }
    {
        auto hits = ptrs_of(m->findCodeBlocksAt(Addr(0x2000)));
        std::set<const CodeBlock*> s2(hits.begin(), hits.end());
        EXPECT_EQ(s2.size(), 1u);
        EXPECT_EQ(s2.count(cb), 1u);
    }
    EXPECT_EQ(range_size(m->findDataBlocksAt(Addr(0x2000))), 0u);

    // Hit at exact start of db.
    {
        auto hits = ptrs_of(m->findDataBlocksAt(Addr(0x2040)));
        std::set<const DataBlock*> s2(hits.begin(), hits.end());
        EXPECT_EQ(s2.size(), 1u);
        EXPECT_EQ(s2.count(db), 1u);
    }

    // Miss at an INTERIOR address (findBlocksAt uses exact-start match,
    // not interval-cover — that's what findBlocksOn is for).
    EXPECT_EQ(range_size(m->findBlocksAt(Addr(0x2010))), 0u);
    EXPECT_EQ(range_size(m->findCodeBlocksAt(Addr(0x2010))), 0u);
}

// ============================================================================
// 31. IR::findModules — multiple modules may share a name.
// ============================================================================
TEST(GtirbIr, FindModulesByName) {
    Context ctx;
    IR* ir = IR::Create(ctx);
    Module* m1 = ir->addModule(Module::Create(ctx, "libc"));
    Module* m2 = ir->addModule(Module::Create(ctx, "libm"));
    Module* m3 = ir->addModule(Module::Create(ctx, "libc"));   // duplicate name

    {
        auto found = ptrs_of(ir->findModules("libc"));
        std::set<const Module*> s(found.begin(), found.end());
        EXPECT_EQ(s.size(), 2u);
        EXPECT_EQ(s.count(m1), 1u);
        EXPECT_EQ(s.count(m3), 1u);
    }
    {
        auto found = ptrs_of(ir->findModules("libm"));
        std::set<const Module*> s(found.begin(), found.end());
        EXPECT_EQ(s.size(), 1u);
        EXPECT_EQ(s.count(m2), 1u);
    }
    EXPECT_EQ(range_size(ir->findModules("nonexistent")), 0u);
}

// ============================================================================
// 32. IR aggregated iteration — IR::symbols / proxy_blocks / code_blocks
//     concatenate across every child module.
// ============================================================================
TEST(GtirbIr, AggregatedIterationAcrossModules) {
    Context ctx;
    IR* ir = IR::Create(ctx);
    Module* m1 = ir->addModule(Module::Create(ctx, "alpha"));
    Module* m2 = ir->addModule(Module::Create(ctx, "beta"));

    // m1: 1 symbol (Addr referent), 1 proxy_block, 1 CodeBlock.
    Symbol* sym1 = m1->addSymbol(Symbol::Create(ctx, Addr(0x100), "s1"));
    ProxyBlock* pb1 = m1->addProxyBlock(ctx);
    Section* sec1 = m1->addSection(ctx, ".text");
    ByteInterval* bi1 = sec1->addByteInterval(ctx, Addr(0x1000), 0x100);
    CodeBlock* cb1 = bi1->addBlock<CodeBlock>(ctx, 0x00, 0x10);

    // m2: 2 symbols, 0 proxy_blocks, 1 DataBlock.
    Symbol* sym2a = m2->addSymbol(Symbol::Create(ctx, Addr(0x200), "s2a"));
    Symbol* sym2b = m2->addSymbol(Symbol::Create(ctx, Addr(0x300), "s2b"));
    Section* sec2 = m2->addSection(ctx, ".data");
    ByteInterval* bi2 = sec2->addByteInterval(ctx, Addr(0x2000), 0x100);
    DataBlock* db2 = bi2->addBlock<DataBlock>(ctx, 0x00, 0x08);

    // Aggregated symbols: sym1 + sym2a + sym2b = 3.
    {
        auto all = ptrs_of(ir->symbols());
        std::set<const Symbol*> s(all.begin(), all.end());
        EXPECT_EQ(s.size(), 3u);
        EXPECT_EQ(s.count(sym1), 1u);
        EXPECT_EQ(s.count(sym2a), 1u);
        EXPECT_EQ(s.count(sym2b), 1u);
    }
    // Aggregated proxy_blocks: pb1 only.
    {
        auto all = ptrs_of(ir->proxy_blocks());
        std::set<const ProxyBlock*> s(all.begin(), all.end());
        EXPECT_EQ(s.size(), 1u);
        EXPECT_EQ(s.count(pb1), 1u);
    }
    // Aggregated code_blocks: cb1 only.
    {
        auto all = ptrs_of(ir->code_blocks());
        std::set<const CodeBlock*> s(all.begin(), all.end());
        EXPECT_EQ(s.size(), 1u);
        EXPECT_EQ(s.count(cb1), 1u);
    }
    // Aggregated data_blocks: db2 only.
    {
        auto all = ptrs_of(ir->data_blocks());
        std::set<const DataBlock*> s(all.begin(), all.end());
        EXPECT_EQ(s.size(), 1u);
        EXPECT_EQ(s.count(db2), 1u);
    }
}
