// gtirb WRG task — subsystem: cfg (control-flow graph vertex/edge
// management, labeled edges, predecessor/successor iteration, removeEdge
// unlabeled and by-label).

#include "test_common.hpp"

// ============================================================================
// 16. CFG: add vertex + edge, label assignment via G[handle]
// ============================================================================
TEST(GtirbCfg, AddVertexEdgeAndLabelAssignment) {
    Context ctx;
    IR* ir = IR::Create(ctx);
    Module* m = ir->addModule(Module::Create(ctx, "prog"));
    Section* s = m->addSection(ctx, ".text");
    ByteInterval* bi = s->addByteInterval(ctx, Addr(0x1000), 0x100);

    CodeBlock* b1 = bi->addBlock<CodeBlock>(ctx, 0x00, 4);
    CodeBlock* b2 = bi->addBlock<CodeBlock>(ctx, 0x10, 4);
    CodeBlock* b3 = bi->addBlock<CodeBlock>(ctx, 0x20, 4);

    CFG& cfg = ir->getCFG();

    if (!getVertex(b1, cfg).has_value()) addVertex(b1, cfg);
    if (!getVertex(b2, cfg).has_value()) addVertex(b2, cfg);
    if (!getVertex(b3, cfg).has_value()) addVertex(b3, cfg);

    EXPECT_TRUE(getVertex(b1, cfg).has_value());
    EXPECT_TRUE(getVertex(b2, cfg).has_value());
    EXPECT_TRUE(getVertex(b3, cfg).has_value());

    auto e12 = addEdge(b1, b2, cfg);
    ASSERT_TRUE(e12.has_value());
    cfg[*e12] = std::make_tuple(ConditionalEdge::OnTrue, DirectEdge::IsDirect,
                                EdgeType::Branch);

    auto e13 = addEdge(b1, b3, cfg);
    ASSERT_TRUE(e13.has_value());
    cfg[*e13] = std::make_tuple(ConditionalEdge::OnFalse, DirectEdge::IsDirect,
                                EdgeType::Fallthrough);

    std::set<const CfgNode*> seen;
    for (auto* np : ptrs_of(nodes(cfg))) {
        seen.insert(np);
    }
    EXPECT_EQ(seen.count(b1), 1u);
    EXPECT_EQ(seen.count(b2), 1u);
    EXPECT_EQ(seen.count(b3), 1u);

    std::set<const CodeBlock*> code_seen;
    for (auto* bp : ptrs_of(blocks(cfg))) {
        code_seen.insert(bp);
    }
    EXPECT_EQ(code_seen.size(), 3u);
}

// ============================================================================
// 17. CFG: cfgPredecessors / cfgSuccessors return labeled edges
// ============================================================================
TEST(GtirbCfg, PredecessorsSuccessorsWithLabels) {
    Context ctx;
    IR* ir = IR::Create(ctx);
    Module* m = ir->addModule(Module::Create(ctx, "prog"));
    Section* s = m->addSection(ctx, ".text");
    ByteInterval* bi = s->addByteInterval(ctx, Addr(0x1000), 0x100);

    CodeBlock* a = bi->addBlock<CodeBlock>(ctx, 0x00, 4);
    CodeBlock* b = bi->addBlock<CodeBlock>(ctx, 0x10, 4);
    CodeBlock* c = bi->addBlock<CodeBlock>(ctx, 0x20, 4);

    CFG& cfg = ir->getCFG();
    if (!getVertex(a, cfg).has_value()) addVertex(a, cfg);
    if (!getVertex(b, cfg).has_value()) addVertex(b, cfg);
    if (!getVertex(c, cfg).has_value()) addVertex(c, cfg);

    auto e_ab = addEdge(a, b, cfg);
    ASSERT_TRUE(e_ab.has_value());
    cfg[*e_ab] = std::make_tuple(ConditionalEdge::OnFalse,
                                 DirectEdge::IsIndirect, EdgeType::Call);
    auto e_cb = addEdge(c, b, cfg);
    ASSERT_TRUE(e_cb.has_value());
    cfg[*e_cb] = std::make_tuple(ConditionalEdge::OnFalse, DirectEdge::IsDirect,
                                 EdgeType::Fallthrough);

    std::set<const CfgNode*> preds;
    for (auto p : cfgPredecessors(cfg, b)) {
        const CfgNode* pn = p.first;
        preds.insert(pn);
        ASSERT_TRUE(p.second.has_value());
        if (pn == a) {
            EXPECT_EQ(std::get<0>(*p.second), ConditionalEdge::OnFalse);
            EXPECT_EQ(std::get<1>(*p.second), DirectEdge::IsIndirect);
            EXPECT_EQ(std::get<2>(*p.second), EdgeType::Call);
        } else if (pn == c) {
            EXPECT_EQ(std::get<2>(*p.second), EdgeType::Fallthrough);
        }
    }
    EXPECT_EQ(preds.size(), 2u);
    EXPECT_EQ(preds.count(a), 1u);
    EXPECT_EQ(preds.count(c), 1u);

    std::set<const CfgNode*> succs;
    for (auto p : cfgSuccessors(cfg, a)) {
        succs.insert(p.first);
    }
    EXPECT_EQ(succs.size(), 1u);
    EXPECT_EQ(succs.count(b), 1u);
}

// ============================================================================
// 18. CFG: removeEdge unlabeled and by label
// ============================================================================
TEST(GtirbCfg, RemoveEdgeUnlabeledAndByLabel) {
    Context ctx;
    IR* ir = IR::Create(ctx);
    Module* m = ir->addModule(Module::Create(ctx, "prog"));
    Section* s = m->addSection(ctx, ".text");
    ByteInterval* bi = s->addByteInterval(ctx, Addr(0x1000), 0x100);

    CodeBlock* a = bi->addBlock<CodeBlock>(ctx, 0x00, 4);
    CodeBlock* b = bi->addBlock<CodeBlock>(ctx, 0x10, 4);

    CFG& cfg = ir->getCFG();
    if (!getVertex(a, cfg).has_value()) addVertex(a, cfg);
    if (!getVertex(b, cfg).has_value()) addVertex(b, cfg);

    auto e1 = addEdge(a, b, cfg); ASSERT_TRUE(e1.has_value());
    cfg[*e1] = std::make_tuple(ConditionalEdge::OnFalse, DirectEdge::IsDirect,
                               EdgeType::Branch);
    auto e2 = addEdge(a, b, cfg); ASSERT_TRUE(e2.has_value());
    cfg[*e2] = std::make_tuple(ConditionalEdge::OnFalse, DirectEdge::IsDirect,
                               EdgeType::Call);
    auto e3 = addEdge(a, b, cfg); ASSERT_TRUE(e3.has_value());
    cfg[*e3] = std::make_tuple(ConditionalEdge::OnFalse, DirectEdge::IsDirect,
                               EdgeType::Fallthrough);

    size_t before = 0;
    for (auto p : cfgSuccessors(cfg, a)) {
        if (p.first == b) ++before;
    }
    EXPECT_EQ(before, 3u);

    EdgeLabel call_label = std::make_tuple(
        ConditionalEdge::OnFalse, DirectEdge::IsDirect, EdgeType::Call);
    EXPECT_TRUE(removeEdge(a, b, call_label, cfg));

    size_t after_call = 0;
    for (auto p : cfgSuccessors(cfg, a)) {
        if (p.first == b) ++after_call;
    }
    EXPECT_EQ(after_call, 2u);

    EXPECT_TRUE(removeEdge(a, b, cfg));
    size_t after_all = 0;
    for (auto p : cfgSuccessors(cfg, a)) {
        if (p.first == b) ++after_all;
    }
    EXPECT_EQ(after_all, 0u);
}

// ============================================================================
// 34. CFG: self-loop (edge whose source == target) — appears once in
//     predecessors and once in successors of that node.
// ============================================================================
TEST(GtirbCfg, SelfLoopAppearsInBothPredsAndSuccs) {
    Context ctx;
    IR* ir = IR::Create(ctx);
    Module* m = ir->addModule(Module::Create(ctx, "prog"));
    Section* s = m->addSection(ctx, ".text");
    ByteInterval* bi = s->addByteInterval(ctx, Addr(0x1000), 0x100);
    CodeBlock* n = bi->addBlock<CodeBlock>(ctx, 0x00, 4);

    CFG& cfg = ir->getCFG();
    if (!getVertex(n, cfg).has_value()) addVertex(n, cfg);

    auto e_self = addEdge(n, n, cfg);
    ASSERT_TRUE(e_self.has_value());
    cfg[*e_self] = std::make_tuple(ConditionalEdge::OnFalse, DirectEdge::IsDirect,
                                   EdgeType::Branch);

    size_t self_preds = 0;
    for (auto p : cfgPredecessors(cfg, n)) {
        if (p.first == n) ++self_preds;
    }
    size_t self_succs = 0;
    for (auto p : cfgSuccessors(cfg, n)) {
        if (p.first == n) ++self_succs;
    }
    EXPECT_EQ(self_preds, 1u) << "self-loop should appear once as a predecessor";
    EXPECT_EQ(self_succs, 1u) << "self-loop should appear once as a successor";
}

