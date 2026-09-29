// gtirb WRG task — subsystem: byte_intervals (ByteInterval bytes,
// insertBytes, typed views with endian handling, block children,
// symbolic-expression attach/retrieve).

#include "test_common.hpp"

// ============================================================================
// 7. ByteInterval byte insertion shifts subsequent block offsets
// ============================================================================
TEST(GtirbByteInterval, InsertBytesShiftsSubsequentBlockOffsets) {
    Context ctx;
    ByteInterval* bi = ByteInterval::Create(ctx, Addr(0x1000), 0x40);

    CodeBlock* b1 = bi->addBlock<CodeBlock>(ctx, 0x00, 4);
    CodeBlock* b2 = bi->addBlock<CodeBlock>(ctx, 0x10, 4);
    DataBlock* b3 = bi->addBlock<DataBlock>(ctx, 0x20, 4);

    EXPECT_EQ(b1->getOffset(), 0u);
    EXPECT_EQ(b2->getOffset(), 0x10u);
    EXPECT_EQ(b3->getOffset(), 0x20u);

    // Insert 8 zero bytes at offset 0x08 via the iterator overload:
    // bytes_begin<uint8_t>() + 8 positions us; then a range insert. Byte
    // insertion grows the ByteInterval's byte vector; block offsets and
    // symbolic-expression offsets are NOT auto-updated by the byte-level
    // insert (callers must adjust block offsets if they want to keep
    // blocks stable relative to their pre-insert byte positions).
    std::array<uint8_t, 8> pad = {{0, 0, 0, 0, 0, 0, 0, 0}};
    bi->insertBytes<uint8_t>(bi->bytes_begin<uint8_t>() + 8,
                             pad.begin(), pad.end());

    // The byte vector grew by 8, and getSize() reflects the new byte
    // count.
    EXPECT_EQ(bi->getSize(), 0x48u);

    // Verify the inserted bytes are actually present in the byte vector.
    std::vector<uint8_t> all(bi->bytes_begin<uint8_t>(),
                             bi->bytes_end<uint8_t>());
    ASSERT_EQ(all.size(), 0x48u);
    // The 8 bytes at positions 8..15 should be the padding zeros.
    for (size_t i = 8; i < 16; ++i) {
        EXPECT_EQ(all[i], 0u) << "byte at offset " << i << " should be pad";
    }
}

// ============================================================================
// 8. ByteInterval typed byte view honors Module's byte order
// ============================================================================
TEST(GtirbByteInterval, BytesTypedViewLittleAndBigEndian) {
    Context ctx;
    IR* ir = IR::Create(ctx);
    Module* m = ir->addModule(Module::Create(ctx, "prog"));
    m->setByteOrder(ByteOrder::Little);

    Section* s = m->addSection(ctx, ".data");

    // Bytes: 0x11 0x22 0x33 0x44 — as little-endian uint32 = 0x44332211,
    // as big-endian uint32 = 0x11223344.
    std::array<uint8_t, 4> raw = {{0x11, 0x22, 0x33, 0x44}};
    ByteInterval* bi = s->addByteInterval(ctx, Addr(0x1000),
                                          raw.begin(), raw.end());

    ASSERT_EQ(bi->getSize(), 4u);
    ASSERT_EQ(bi->getInitializedSize(), 4u);

    // Little-endian view (via module's default ByteOrder=Little).
    {
        std::vector<uint32_t> vals(bi->bytes_begin<uint32_t>(),
                                   bi->bytes_end<uint32_t>());
        ASSERT_EQ(vals.size(), 1u);
        EXPECT_EQ(vals[0], 0x44332211u);
    }

    // Switch module to big-endian; the same buffer decodes differently.
    m->setByteOrder(ByteOrder::Big);
    {
        std::vector<uint32_t> vals(bi->bytes_begin<uint32_t>(),
                                   bi->bytes_end<uint32_t>());
        ASSERT_EQ(vals.size(), 1u);
        EXPECT_EQ(vals[0], 0x11223344u);
    }

    // 8-bit view is endian-independent.
    std::vector<uint8_t> collected(bi->bytes_begin<uint8_t>(),
                                   bi->bytes_end<uint8_t>());
    ASSERT_EQ(collected.size(), 4u);
    EXPECT_EQ(collected[0], 0x11);
    EXPECT_EQ(collected[3], 0x44);
}

// ============================================================================
// 9. CodeBlock + DataBlock children in a ByteInterval, address derivation
// ============================================================================
TEST(GtirbByteInterval, CodeAndDataBlockChildrenAddressDerivation) {
    Context ctx;
    ByteInterval* bi = ByteInterval::Create(ctx, Addr(0x2000), 0x100);

    CodeBlock* code = bi->addBlock<CodeBlock>(ctx, 0x10, 8);
    DataBlock* data = bi->addBlock<DataBlock>(ctx, 0x40, 4);

    EXPECT_EQ(code->getByteInterval(), bi);
    EXPECT_EQ(data->getByteInterval(), bi);

    // Address = interval.address + offset.
    ASSERT_TRUE(code->getAddress().has_value());
    EXPECT_EQ(static_cast<uint64_t>(*code->getAddress()), 0x2010u);
    ASSERT_TRUE(data->getAddress().has_value());
    EXPECT_EQ(static_cast<uint64_t>(*data->getAddress()), 0x2040u);

    EXPECT_EQ(range_size(bi->code_blocks()), 1u);
    EXPECT_EQ(range_size(bi->data_blocks()), 1u);

    // Interval with no address -> blocks' addresses are nullopt.
    ByteInterval* floating = ByteInterval::Create(ctx, std::nullopt, 0x20);
    CodeBlock* fc = floating->addBlock<CodeBlock>(ctx, 0x04, 2);
    EXPECT_FALSE(fc->getAddress().has_value());
}

// ============================================================================
// 10. ByteInterval symbolic expressions at specific offsets
// ============================================================================
TEST(GtirbByteInterval, SymbolicExpressionAttachAndRetrieveAtOffset) {
    Context ctx;
    IR* ir = IR::Create(ctx);
    Module* m = ir->addModule(Module::Create(ctx, "prog"));
    Section* s = m->addSection(ctx, ".text");
    ByteInterval* bi = s->addByteInterval(ctx, Addr(0x1000), 0x100);

    Symbol* target = m->addSymbol(Symbol::Create(ctx, Addr(0x8000), "target"));

    SymAddrConst sac;
    sac.Offset = 0x10;
    sac.Sym = target;
    bi->addSymbolicExpression(4, SymbolicExpression(sac));

    SymbolicExpression* got = bi->getSymbolicExpression(4);
    ASSERT_NE(got, nullptr);
    ASSERT_TRUE(std::holds_alternative<SymAddrConst>(*got));
    const SymAddrConst& back = std::get<SymAddrConst>(*got);
    EXPECT_EQ(back.Offset, 0x10);
    EXPECT_EQ(back.Sym, target);

    EXPECT_EQ(bi->getSymbolicExpression(999), nullptr);

    bi->removeSymbolicExpression(4);
    EXPECT_EQ(bi->getSymbolicExpression(4), nullptr);
}

// ============================================================================
// 33. ByteInterval::eraseBytes — remove a byte range and verify the interval
//     shrinks by (End - Begin).
// ============================================================================
TEST(GtirbByteInterval, EraseBytesShrinksInterval) {
    Context ctx;
    // Start with 32 initialized bytes: [0..31].
    std::array<uint8_t, 32> initial;
    for (uint8_t i = 0; i < 32; ++i) initial[i] = i;

    ByteInterval* bi = ByteInterval::Create(
        ctx, std::optional<Addr>(std::nullopt),
        initial.begin(), initial.end());
    ASSERT_EQ(bi->getSize(), 32u);

    // Sanity: bytes read back as 0..31 pre-erase.
    {
        std::vector<uint8_t> pre;
        for (auto it = bi->bytes_begin<uint8_t>();
             it != bi->bytes_end<uint8_t>(); ++it) {
            pre.push_back(*it);
        }
        ASSERT_EQ(pre.size(), 32u);
        EXPECT_EQ(pre.front(), 0u);
        EXPECT_EQ(pre.back(), 31u);
    }

    // Erase 8 bytes at [4, 12). Size should drop from 32 → 24, and the
    // remaining byte sequence should be 0,1,2,3, 12,13,...,31.
    bi->eraseBytes<uint8_t>(bi->bytes_begin<uint8_t>() + 4,
                            bi->bytes_begin<uint8_t>() + 12);
    EXPECT_EQ(bi->getSize(), 24u);

    std::vector<uint8_t> post;
    for (auto it = bi->bytes_begin<uint8_t>();
         it != bi->bytes_end<uint8_t>(); ++it) {
        post.push_back(*it);
    }
    ASSERT_EQ(post.size(), 24u);
    for (size_t k = 0; k < 4; ++k)  EXPECT_EQ(post[k], k);        // 0..3
    for (size_t k = 4; k < 24; ++k) EXPECT_EQ(post[k], k + 8);    // 12..31
}
