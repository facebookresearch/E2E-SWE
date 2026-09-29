// Capability: parse (CSS text -> AST). Exercises the parser as a real user would: full stylesheets,
// context-scoped fragments, adjustable detail level, source positions, and tolerant error recovery.
// Each case bundles the assertions that describe ONE distinct parsing behavior.
import * as css from 'stylesheet-tree';
import { assert, assertEqual, assertDeepEqual } from './assert.mjs';

const types = (list) => list.toArray().map((n) => n.type);

export default [
    {
        name: 'parse: a full stylesheet builds the expected top-level node structure',
        run: () => {
            const ast = css.parse('.a { color: red; }');
            assertEqual(ast.type, 'Rootsheet');
            const rule = ast.children.first;
            assertEqual(rule.type, 'Rule');
            assertEqual(rule.prelude.type, 'MatchGroup');
            assertEqual(rule.block.type, 'Block');
            const selector = rule.prelude.children.first;
            assertEqual(selector.type, 'MatchSeq');
            assertEqual(selector.children.first.type, 'ClassMatch');
            assertEqual(selector.children.first.name, 'a');
            const decl = rule.block.children.first;
            assertEqual(decl.type, 'Decl');
            assertEqual(decl.property, 'color');
            assertEqual(decl.important, false);
            assertEqual(decl.value.type, 'Value');
            assertEqual(decl.value.children.first.type, 'Identifier');
            assertEqual(decl.value.children.first.name, 'red');
        },
    },
    {
        name: 'parse: context "selector" parses a compound selector into ordered simple selectors',
        run: () => {
            const ast = css.parse('.foo.bar', { context: 'selector' });
            assertEqual(ast.type, 'MatchSeq');
            assertDeepEqual(types(ast.children), ['ClassMatch', 'ClassMatch']);
            assertEqual(ast.children.first.name, 'foo');
            assertEqual(ast.children.last.name, 'bar');
        },
    },
    {
        name: 'parse: context "declaration" splits property/value and detects !important',
        run: () => {
            const decl = css.parse('color: #aabbcc !important', { context: 'declaration' });
            assertEqual(decl.type, 'Decl');
            assertEqual(decl.property, 'color');
            assertEqual(decl.important, true);
            assertEqual(decl.value.type, 'Value');
            assertEqual(decl.value.children.first.type, 'Hash');
            assertEqual(decl.value.children.first.value, 'aabbcc');
        },
    },
    {
        name: 'parse: context "value" parses a multi-token value into typed nodes',
        run: () => {
            const value = css.parse('1px solid black', { context: 'value' });
            assertEqual(value.type, 'Value');
            assertDeepEqual(types(value.children), ['Dimension', 'Identifier', 'Identifier']);
            assertEqual(value.children.first.value, '1');
            assertEqual(value.children.first.unit, 'px');
        },
    },
    {
        name: 'parse: an at-rule with prelude and block is parsed in detail by default',
        run: () => {
            const ast = css.parse('@media screen and (min-width: 100px) { .a { color: red } }');
            const atrule = ast.children.first;
            assertEqual(atrule.type, 'Atrule');
            assertEqual(atrule.name, 'media');
            assertEqual(atrule.prelude.type, 'AtruleHead');
            assertEqual(atrule.block.type, 'Block');
            // the block contains the nested rule
            assertEqual(atrule.block.children.first.type, 'Rule');
        },
    },
    {
        name: 'parse: parseValue:false leaves the declaration value as a Raw node',
        run: () => {
            const decl = css.parse('color:#aabbcc', { context: 'declaration', parseValue: false });
            assertEqual(decl.value.type, 'Raw');
            assertEqual(decl.value.value, '#aabbcc');
        },
    },
    {
        name: 'parse: parseRulePrelude:false leaves the selector as a Raw node',
        run: () => {
            const ast = css.parse('.foo {}', { parseRulePrelude: false });
            const rule = ast.children.first;
            assertEqual(rule.prelude.type, 'Raw');
            assertEqual(rule.prelude.value, '.foo');
            assertEqual(rule.block.type, 'Block');
        },
    },
    {
        name: 'parse: parseAtrulePrelude:false leaves the at-rule prelude as a Raw node',
        run: () => {
            const ast = css.parse('@example 1 2;', { parseAtrulePrelude: false });
            const atrule = ast.children.first;
            assertEqual(atrule.name, 'example');
            assertEqual(atrule.prelude.type, 'Raw');
            assertEqual(atrule.prelude.value, '1 2');
        },
    },
    {
        name: 'parse: parseCustomProperty toggles detailed parsing of custom-property values',
        run: () => {
            const raw = css.parse('--custom: #aabbcc', { context: 'declaration' });
            assertEqual(raw.value.type, 'Raw', 'custom property value is Raw by default');

            const detailed = css.parse('--custom: #aabbcc', { context: 'declaration', parseCustomProperty: true });
            assertEqual(detailed.value.type, 'Value');
            assertEqual(detailed.value.children.first.type, 'Hash');
            assertEqual(detailed.value.children.first.value, 'aabbcc');
        },
    },
    {
        name: 'parse: positions:true records source location offsets on nodes',
        run: () => {
            const ast = css.parse('.a{}', { positions: true });
            const rule = ast.children.first;
            assert(rule.loc !== null, 'loc should be populated when positions:true');
            assertEqual(rule.loc.start.offset, 0);
            assertEqual(rule.loc.start.line, 1);
            assertEqual(rule.loc.start.column, 1);
            // and null by default
            const ast2 = css.parse('.a{}');
            assertEqual(ast2.children.first.loc, null);
        },
    },
    {
        name: 'parse: tolerant recovery wraps bad content in Raw and reports each error via onParseError',
        run: () => {
            const errors = [];
            const ast = css.parse('example { foo; bar: 1! }', {
                onParseError(e) { errors.push(e.rawMessage || e.message); },
            });
            assertEqual(ast.type, 'Rootsheet', 'parser must not throw on malformed input');
            assertDeepEqual(errors, ['Colon is expected', 'Identifier is expected']);
        },
    },
    {
        name: 'parse: onComment receives comment values in source order',
        run: () => {
            const comments = [];
            css.parse('/* a */ .x { /* b */ color: red }', {
                onComment(value) { comments.push(value.trim()); },
            });
            assertDeepEqual(comments, ['a', 'b']);
        },
    },
];
