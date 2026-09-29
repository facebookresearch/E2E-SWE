// gtirb WRG task — subsystem: core (Addr / Casting / Context / UUID lookup).
//
// One TEST per distinct behavioral contract. Every assertion checks a
// documented spec property (see /app/instruction.md); no shallow "len > 0"
// or isinstance-style asserts. Each TEST builds its own Context so tests are
// independent.

#include "test_common.hpp"

// ============================================================================
// 1. Addr arithmetic, AddrRange, and address utilities
// ============================================================================
TEST(GtirbAddr, AddrArithmeticAndRangeAndUtilities) {
    // Basic arithmetic.
    Addr a(0x1000);
    Addr b = a + 0x100;
    EXPECT_EQ(static_cast<uint64_t>(b), 0x1100u);
    EXPECT_EQ(static_cast<uint64_t>(b - 0x50), 0x10B0u);
    Addr::difference_type diff = b - a;
    EXPECT_EQ(diff, 0x100);
    ++a;
    EXPECT_EQ(static_cast<uint64_t>(a), 0x1001u);

    // Comparisons + hash.
    EXPECT_TRUE(Addr(5) < Addr(10));
    EXPECT_TRUE(Addr(10) == Addr(10));
    EXPECT_EQ(std::hash<Addr>{}(Addr(0x1234)), std::hash<uint64_t>{}(0x1234));

    // AddrRange half-open [lower, upper).
    AddrRange r(Addr(0x1000), Addr(0x1100));
    EXPECT_EQ(static_cast<uint64_t>(r.lower()), 0x1000u);
    EXPECT_EQ(static_cast<uint64_t>(r.upper()), 0x1100u);
    EXPECT_EQ(r.size(), 0x100u);

    // Ctor clamps if Upper < Lower.
    AddrRange clamped(Addr(0x20), Addr(0x10));
    EXPECT_EQ(clamped.size(), 0u);

    // Count-form ctor.
    AddrRange counted(Addr(0x2000), uint64_t{64});
    EXPECT_EQ(static_cast<uint64_t>(counted.upper()), 0x2040u);

    // Free-function utilities via a Node that has getAddress()/getSize().
    Context ctx;
    ByteInterval* bi = ByteInterval::Create(ctx, Addr(0x3000), 0x50);
    auto rng = addressRange(*bi);
    ASSERT_TRUE(rng.has_value());
    EXPECT_EQ(static_cast<uint64_t>(rng->lower()), 0x3000u);
    EXPECT_EQ(rng->size(), 0x50u);

    auto limit = addressLimit(*bi);
    ASSERT_TRUE(limit.has_value());
    EXPECT_EQ(static_cast<uint64_t>(*limit), 0x3050u);

    EXPECT_TRUE(containsAddr(*bi, Addr(0x3020)));
    EXPECT_FALSE(containsAddr(*bi, Addr(0x3050)));  // upper is exclusive
    EXPECT_FALSE(containsAddr(*bi, Addr(0x2FFF)));  // below lower
}

// ============================================================================
// 2. LLVM-style isa/dyn_cast on the Node hierarchy
// ============================================================================
TEST(GtirbCasting, IsaAndDynCastOnNodeHierarchy) {
    Context ctx;
    CodeBlock* cb = CodeBlock::Create(ctx, 4);
    DataBlock* db = DataBlock::Create(ctx, 8);
    ProxyBlock* pb = ProxyBlock::Create(ctx);

    Node* n_cb = cb;
    Node* n_db = db;
    Node* n_pb = pb;

    EXPECT_TRUE(gtirb::isa<CodeBlock>(n_cb));
    EXPECT_TRUE(gtirb::isa<DataBlock>(n_db));
    EXPECT_TRUE(gtirb::isa<ProxyBlock>(n_pb));

    EXPECT_FALSE(gtirb::isa<CodeBlock>(n_db));
    EXPECT_FALSE(gtirb::isa<DataBlock>(n_pb));

    EXPECT_TRUE(gtirb::isa<CfgNode>(n_cb));
    EXPECT_TRUE(gtirb::isa<CfgNode>(n_pb));
    EXPECT_FALSE(gtirb::isa<CfgNode>(n_db));

    CodeBlock* back = gtirb::dyn_cast<CodeBlock>(n_cb);
    EXPECT_EQ(back, cb);

    EXPECT_EQ(gtirb::dyn_cast<DataBlock>(n_cb), nullptr);

    Node* null_node = nullptr;
    EXPECT_EQ(gtirb::dyn_cast_or_null<CodeBlock>(null_node), nullptr);
}

// ============================================================================
// 3. Context ownership + UUID lookup across node types
// ============================================================================
TEST(GtirbContext, UuidLookupAcrossNodeTypes) {
    Context ctx;
    IR* ir = IR::Create(ctx);
    Module* m = ir->addModule(Module::Create(ctx, "example"));
    Section* s = m->addSection(ctx, ".text");
    Symbol* sym = m->addSymbol(Symbol::Create(ctx, Addr(0x400), "main"));

    UUID u_ir = ir->getUUID();
    UUID u_m  = m->getUUID();
    UUID u_s  = s->getUUID();
    UUID u_sym = sym->getUUID();

    EXPECT_NE(u_ir, u_m);
    EXPECT_NE(u_m, u_s);
    EXPECT_NE(u_s, u_sym);
    EXPECT_NE(u_ir, u_sym);

    EXPECT_EQ(Node::getByUUID(ctx, u_ir),  static_cast<Node*>(ir));
    EXPECT_EQ(Node::getByUUID(ctx, u_m),   static_cast<Node*>(m));
    EXPECT_EQ(Node::getByUUID(ctx, u_s),   static_cast<Node*>(s));
    EXPECT_EQ(Node::getByUUID(ctx, u_sym), static_cast<Node*>(sym));

    UUID unknown{};
    for (auto& byte : unknown) { byte = 0xEE; }
    EXPECT_EQ(Node::getByUUID(ctx, unknown), nullptr);
}
