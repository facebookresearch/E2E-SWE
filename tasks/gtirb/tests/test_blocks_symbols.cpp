// gtirb WRG task — subsystem: blocks_symbols (ProxyBlock, Symbol referent
// variants, Symbol::visit dispatch, Module::findSymbols, SymbolicExpression
// variants).

#include "test_common.hpp"

// ============================================================================
// 11. ProxyBlock as a Module's external stand-in
// ============================================================================
TEST(GtirbProxyBlock, ExternalStandInHasNoAddressAndLivesInModule) {
    Context ctx;
    IR* ir = IR::Create(ctx);
    Module* m = ir->addModule(Module::Create(ctx, "caller"));

    ProxyBlock* pb = m->addProxyBlock(ctx);

    EXPECT_EQ(pb->getModule(), m);

    EXPECT_EQ(range_size(m->proxy_blocks()), 1u);

    // removeProxyBlock returns ChangeStatus in the actual API; we just check
    // that removal succeeds by iterating after.
    m->removeProxyBlock(pb);
    EXPECT_EQ(range_size(m->proxy_blocks()), 0u);
}

// ============================================================================
// 12. Symbol referent variants: Addr / CodeBlock / DataBlock / ProxyBlock
// ============================================================================
TEST(GtirbSymbol, ReferentVariantsAddrCodeDataProxy) {
    Context ctx;
    IR* ir = IR::Create(ctx);
    Module* m = ir->addModule(Module::Create(ctx, "prog"));
    Section* s = m->addSection(ctx, ".text");
    ByteInterval* bi = s->addByteInterval(ctx, Addr(0x1000), 0x100);
    CodeBlock* code = bi->addBlock<CodeBlock>(ctx, 0x00, 4);
    DataBlock* data = bi->addBlock<DataBlock>(ctx, 0x40, 4);
    ProxyBlock* proxy = m->addProxyBlock(ctx);

    // Addr symbol.
    Symbol* s_addr = m->addSymbol(Symbol::Create(ctx, Addr(0xABCD), "at_addr"));
    ASSERT_TRUE(s_addr->getAddress().has_value());
    EXPECT_EQ(static_cast<uint64_t>(*s_addr->getAddress()), 0xABCDu);
    EXPECT_FALSE(s_addr->hasReferent());

    // CodeBlock symbol.
    Symbol* s_code = m->addSymbol(Symbol::Create(ctx, code, "code_sym"));
    EXPECT_TRUE(s_code->hasReferent());
    EXPECT_EQ(s_code->getReferent<CodeBlock>(), code);
    EXPECT_EQ(s_code->getReferent<DataBlock>(), nullptr);
    ASSERT_TRUE(s_code->getAddress().has_value());
    EXPECT_EQ(static_cast<uint64_t>(*s_code->getAddress()), 0x1000u);

    // DataBlock symbol.
    Symbol* s_data = m->addSymbol(Symbol::Create(ctx, data, "data_sym"));
    EXPECT_EQ(s_data->getReferent<DataBlock>(), data);
    ASSERT_TRUE(s_data->getAddress().has_value());
    EXPECT_EQ(static_cast<uint64_t>(*s_data->getAddress()), 0x1040u);

    // ProxyBlock symbol has no address.
    Symbol* s_proxy = m->addSymbol(Symbol::Create(ctx, proxy, "proxy_sym"));
    EXPECT_EQ(s_proxy->getReferent<ProxyBlock>(), proxy);
    EXPECT_FALSE(s_proxy->getAddress().has_value());

    // Empty symbol.
    Symbol* s_empty = m->addSymbol(Symbol::Create(ctx));
    EXPECT_FALSE(s_empty->hasReferent());
    EXPECT_FALSE(s_empty->getAddress().has_value());
    EXPECT_EQ(s_empty->getName(), "");
}

// ============================================================================
// 13. Symbol::visit dispatches to the right overload by concrete type
// ============================================================================
TEST(GtirbSymbol, VisitDispatchesByConcreteReferentType) {
    Context ctx;
    IR* ir = IR::Create(ctx);
    Module* m = ir->addModule(Module::Create(ctx, "prog"));
    Section* s = m->addSection(ctx, ".text");
    ByteInterval* bi = s->addByteInterval(ctx, Addr(0x1000), 0x100);
    CodeBlock* code = bi->addBlock<CodeBlock>(ctx, 0x00, 4);
    DataBlock* data = bi->addBlock<DataBlock>(ctx, 0x10, 4);
    ProxyBlock* proxy = m->addProxyBlock(ctx);

    // Void-returning visitor that records which overload fired via a
    // captured reference. This decouples the test from visit's return-type
    // contract (agents may implement visit as returning optional<T>, void,
    // or raw T — this test cares only about dispatch, not return type).
    // A '0' recorded value means no overload fired (correct for Addr /
    // empty symbols).
    int fired;
    struct RecordingVisitor {
        int& fired;
        void operator()(const CodeBlock*)  const { fired = 1; }
        void operator()(const DataBlock*)  const { fired = 2; }
        void operator()(const ProxyBlock*) const { fired = 3; }
    };

    Symbol* s_code  = Symbol::Create(ctx, code,  "c");
    Symbol* s_data  = Symbol::Create(ctx, data,  "d");
    Symbol* s_proxy = Symbol::Create(ctx, proxy, "p");
    Symbol* s_addr  = Symbol::Create(ctx, Addr(0x1000), "a");
    Symbol* s_empty = Symbol::Create(ctx);

    fired = 0; s_code->visit(RecordingVisitor{fired});
    EXPECT_EQ(fired, 1);
    fired = 0; s_data->visit(RecordingVisitor{fired});
    EXPECT_EQ(fired, 2);
    fired = 0; s_proxy->visit(RecordingVisitor{fired});
    EXPECT_EQ(fired, 3);
    // Symbols without a Node referent (Addr or empty) must not invoke any
    // overload — fired stays at the pre-visit sentinel.
    fired = 0; s_addr->visit(RecordingVisitor{fired});
    EXPECT_EQ(fired, 0);
    fired = 0; s_empty->visit(RecordingVisitor{fired});
    EXPECT_EQ(fired, 0);
}

// ============================================================================
// 14. Module::findSymbols by name / address / referent
// ============================================================================
TEST(GtirbModule, FindSymbolsByNameAddressAndReferent) {
    Context ctx;
    IR* ir = IR::Create(ctx);
    Module* m = ir->addModule(Module::Create(ctx, "prog"));
    Section* s = m->addSection(ctx, ".text");
    ByteInterval* bi = s->addByteInterval(ctx, Addr(0x1000), 0x100);
    CodeBlock* code = bi->addBlock<CodeBlock>(ctx, 0x20, 4);

    Symbol* main1 = m->addSymbol(Symbol::Create(ctx, code, "main"));
    Symbol* main2 = m->addSymbol(Symbol::Create(ctx, Addr(0x1020), "main"));
    Symbol* other = m->addSymbol(Symbol::Create(ctx, Addr(0x2000), "other"));

    // Find by name -> both mains.
    std::set<Symbol*> by_name;
    for (auto* sp : ptrs_of(m->findSymbols("main"))) {
        by_name.insert(sp);
    }
    EXPECT_EQ(by_name.size(), 2u);
    EXPECT_EQ(by_name.count(main1), 1u);
    EXPECT_EQ(by_name.count(main2), 1u);

    // Find by address 0x1020 -> both mains.
    std::set<Symbol*> by_addr;
    for (auto* sp : ptrs_of(m->findSymbols(Addr(0x1020)))) {
        by_addr.insert(sp);
    }
    EXPECT_EQ(by_addr.count(main1), 1u);
    EXPECT_EQ(by_addr.count(main2), 1u);
    EXPECT_EQ(by_addr.count(other), 0u);

    // Find by referent -> only main1 (the one with the CodeBlock referent).
    std::set<Symbol*> by_ref;
    for (auto* sp : ptrs_of(m->findSymbols(*code))) {
        by_ref.insert(sp);
    }
    EXPECT_EQ(by_ref.size(), 1u);
    EXPECT_EQ(by_ref.count(main1), 1u);

    EXPECT_EQ(range_size(m->findSymbols("does_not_exist")), 0u);
}

// ============================================================================
// 15. SymbolicExpression: both SymAddrConst and SymAddrAddr variants
// ============================================================================
TEST(GtirbSymbolicExpression, SymAddrConstAndSymAddrAddrVariants) {
    Context ctx;
    IR* ir = IR::Create(ctx);
    Module* m = ir->addModule(Module::Create(ctx, "prog"));
    Section* s = m->addSection(ctx, ".text");
    ByteInterval* bi = s->addByteInterval(ctx, Addr(0x1000), 0x100);

    Symbol* sym_a = m->addSymbol(Symbol::Create(ctx, Addr(0x8000), "a"));
    Symbol* sym_b = m->addSymbol(Symbol::Create(ctx, Addr(0x9000), "b"));

    SymAddrConst sac;
    sac.Offset = 0x40;
    sac.Sym = sym_a;
    bi->addSymbolicExpression(0x08, SymbolicExpression(sac));

    SymAddrAddr saa;
    saa.Scale = 2;
    saa.Offset = 0x10;
    saa.Sym1 = sym_a;
    saa.Sym2 = sym_b;
    bi->addSymbolicExpression(0x10, SymbolicExpression(saa));

    SymbolicExpression* e1 = bi->getSymbolicExpression(0x08);
    ASSERT_NE(e1, nullptr);
    ASSERT_TRUE(std::holds_alternative<SymAddrConst>(*e1));
    const SymAddrConst& back1 = std::get<SymAddrConst>(*e1);
    EXPECT_EQ(back1.Offset, 0x40);
    EXPECT_EQ(back1.Sym, sym_a);

    SymbolicExpression* e2 = bi->getSymbolicExpression(0x10);
    ASSERT_NE(e2, nullptr);
    ASSERT_TRUE(std::holds_alternative<SymAddrAddr>(*e2));
    const SymAddrAddr& back2 = std::get<SymAddrAddr>(*e2);
    EXPECT_EQ(back2.Scale, 2);
    EXPECT_EQ(back2.Offset, 0x10);
    EXPECT_EQ(back2.Sym1, sym_a);
    EXPECT_EQ(back2.Sym2, sym_b);

    size_t total = 0;
    for (auto kv : bi->symbolic_expressions()) {
        (void)kv;
        ++total;
    }
    EXPECT_EQ(total, 2u);
}
