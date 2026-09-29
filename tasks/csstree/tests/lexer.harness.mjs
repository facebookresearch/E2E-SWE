// Capability: lexer (W3C syntax validation & matching). This is the deepest subsystem. Tests split
// into two fair groups:
//   1. Standard properties/types backed by the bundled MDN CSS dictionaries (color, length, ...).
//   2. The value-definition MATCHING ENGINE, exercised through fork() with custom grammars defined
//      in-test — so correctness of the matcher (combinators, multipliers, comma-lists) is asserted
//      without depending on any specific bundled dictionary content.
import * as css from 'stylesheet-tree';
import { assert, assertEqual, assertDeepEqual } from './assert.mjs';

const matches = (m) => m.matched !== null && m.error === null;

export default [
    {
        name: 'lexer.matchProperty: a valid value matches and reports no error',
        run: () => {
            const m = css.lexer.matchProperty('color', 'red');
            assert(matches(m), 'color:red should match');
        },
    },
    {
        name: 'lexer.matchProperty: an invalid value fails with a SyntaxMatchError',
        run: () => {
            const m = css.lexer.matchProperty('color', '1px');
            assertEqual(m.matched, null, 'color:1px must not match');
            assertEqual(m.error.name, 'SyntaxMatchError');
            assertEqual(m.error.rawMessage, 'Mismatch');
        },
    },
    {
        name: 'lexer.matchProperty: custom properties are reported as not applicable',
        run: () => {
            const m = css.lexer.matchProperty('--foo', 'red');
            assertEqual(m.matched, null);
            assertEqual(m.error.message, "Lexer matching doesn't applicable for custom properties");
        },
    },
    {
        name: 'lexer.matchProperty: CSS-wide keywords match any property',
        run: () => {
            assert(matches(css.lexer.matchProperty('color', 'inherit')), 'inherit should match');
            assert(matches(css.lexer.matchProperty('color', 'initial')), 'initial should match');
            assert(matches(css.lexer.matchProperty('color', 'unset')), 'unset should match');
        },
    },
    {
        name: 'lexer.matchType: a known type validates values and rejects mismatches',
        run: () => {
            assert(matches(css.lexer.matchType('length', '10px')), 'length should accept 10px');
            assertEqual(css.lexer.matchType('length', 'red').matched, null, 'length should reject red');
        },
    },
    {
        name: 'lexer.matchType: an unknown type name yields a SyntaxReferenceError',
        run: () => {
            const m = css.lexer.matchType('definitelyNotAType', '1');
            assertEqual(m.matched, null);
            assertEqual(m.error.name, 'SyntaxReferenceError');
            assert(/Unknown type/.test(m.error.message), `got: ${m.error.message}`);
        },
    },
    {
        name: 'lexer.matchDeclaration: matches a parsed Decl node against its property grammar',
        run: () => {
            const decl = css.parse('color: red', { context: 'declaration' });
            assert(matches(css.lexer.matchDeclaration(decl)), 'color:red declaration should match');
            const badDecl = css.parse('color: 1px', { context: 'declaration' });
            assertEqual(css.lexer.matchDeclaration(badDecl).matched, null);
        },
    },
    {
        name: 'lexer engine: the "|" combinator accepts either alternative and rejects others',
        run: () => {
            const f = css.fork({ types: { 'my-len': '<length> | auto' } });
            assert(matches(f.lexer.matchType('my-len', '10px')), '10px should match <length>|auto');
            assert(matches(f.lexer.matchType('my-len', 'auto')), 'auto should match');
            assertEqual(f.lexer.matchType('my-len', 'red').matched, null, 'red should not match');
        },
    },
    {
        name: 'lexer engine: the "{min,max}" multiplier enforces occurrence bounds',
        run: () => {
            assertEqual(css.lexer.match('<number>{2,3}', '1').matched, null, 'too few');
            assert(matches(css.lexer.match('<number>{2,3}', '1 2')), 'in range');
            assert(matches(css.lexer.match('<number>{2,3}', '1 2 3')), 'at max');
            assertEqual(css.lexer.match('<number>{2,3}', '1 2 3 4').matched, null, 'too many');
        },
    },
    {
        name: 'lexer engine: the "#" comma-list multiplier requires comma separation and no trailing comma',
        run: () => {
            assert(matches(css.lexer.match('<number>#', '1, 2, 3')), 'comma-separated list matches');
            assertEqual(css.lexer.match('<number>#', '1, 2,').matched, null, 'trailing comma rejected');
        },
    },
    {
        name: 'lexer.fork: custom property definitions validate against the provided grammar',
        run: () => {
            const f = css.fork({ properties: { 'stack-count': '<integer>' } });
            assert(matches(f.lexer.matchProperty('stack-count', '42')), '42 should match <integer>');
            assertEqual(f.lexer.matchProperty('stack-count', 'red').matched, null, 'red should not match <integer>');
            // the fork does not leak into the base lexer
            assertEqual(css.lexer.getProperty('stack-count'), null, 'base lexer is unaffected by fork');
        },
    },
    {
        name: 'lexer engine: the "&&" combinator requires all terms in any order',
        run: () => {
            assert(matches(css.lexer.match('<number> && <length>', '1 2px')), 'both, order A');
            assert(matches(css.lexer.match('<number> && <length>', '2px 1')), 'both, order B');
            assertEqual(css.lexer.match('<number> && <length>', '1').matched, null, 'missing one term fails');
        },
    },
    {
        name: 'lexer engine: the "||" combinator requires at least one term in any order',
        run: () => {
            assert(matches(css.lexer.match('<number> || <length>', '1')), 'one term ok');
            assert(matches(css.lexer.match('<number> || <length>', '1 2px')), 'both ok');
            assertEqual(css.lexer.match('<number> || <length>', 'red').matched, null, 'neither term fails');
        },
    },
    {
        name: 'lexer engine: the "?" and "*" multipliers make terms optional / repeatable',
        run: () => {
            assert(matches(css.lexer.match('<number> <length>?', '1 2px')), 'optional present');
            assert(matches(css.lexer.match('<number> <length>?', '1')), 'optional absent');
            assert(matches(css.lexer.match('<number>*', '')), 'star matches empty');
            assert(matches(css.lexer.match('<number>*', '1 2 3')), 'star matches many');
        },
    },
    {
        name: 'lexer.checkStructure: reports no errors (false) for a well-formed AST',
        run: () => {
            const ast = css.parse('.a { color: red }');
            assertEqual(css.lexer.checkStructure(ast), false);
        },
    },
    {
        name: 'lexer.findAllFragments: locates every value fragment of a given type across a stylesheet',
        run: () => {
            const ast = css.parse('.a { color: red; background: url(x) #fff }');
            const fragments = css.lexer.findAllFragments(ast, 'Type', 'color');
            assertEqual(fragments.length, 2, 'red and #fff are both <color> fragments');
            const generated = fragments.map((f) => f.nodes.toArray().map((n) => css.generate(n)).join(''));
            assertDeepEqual(generated, ['red', '#fff']);
        },
    },
    {
        name: 'lexer.getType / getProperty: expose the resolved definition nodes for known names',
        run: () => {
            const lengthType = css.lexer.getType('length');
            assertEqual(lengthType.type, 'Type');
            const colorProp = css.lexer.getProperty('color');
            assertEqual(colorProp.type, 'Property');
            assertEqual(colorProp.name, 'color');
        },
    },
];
