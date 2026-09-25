// Capability: generate (AST -> CSS text). Exercises serialization round-trips, safe vs spec
// whitespace mode, source-map emission, auto-whitespace insertion, and the unknown-node-type error.
import * as css from 'stylesheet-tree';
import { assert, assertEqual, assertThrows } from './assert.mjs';

export default [
    {
        name: 'generate: serializes a stylesheet back to compact CSS',
        run: () => {
            const ast = css.parse('.a { color: red; background: blue }');
            assertEqual(css.generate(ast), '.a{color:red;background:blue}');
        },
    },
    {
        name: 'generate: round-trips a value with functions and hex colors (safe mode default)',
        run: () => {
            const ast = css.parse('a { border: calc(1px) solid #ff0000 }');
            // safe mode (default) keeps separating whitespace so older browsers still tokenize it
            assertEqual(css.generate(ast), 'a{border:calc(1px) solid #ff0000}');
        },
    },
    {
        name: 'generate: spec mode drops whitespace the spec deems unnecessary',
        run: () => {
            const ast = css.parse('a { border: calc(1px) solid #ff0000 }');
            assertEqual(css.generate(ast, { mode: 'spec' }), 'a{border:calc(1px)solid#ff0000}');
        },
    },
    {
        name: 'generate: auto-inserts whitespace to prevent unintended token merges',
        run: () => {
            const ast = css.parse('span#foo { border: 1%var(--a)#ff0000; }');
            assertEqual(css.generate(ast), 'span#foo{border:1% var(--a) #ff0000}');
        },
    },
    {
        name: 'generate: preserves raw values verbatim when the value was not parsed',
        run: () => {
            const ast = css.parse('span#foo { border: 1%var(--a)#ff0000; }', {
                parseRulePrelude: false,
                parseValue: false,
            });
            assertEqual(css.generate(ast), 'span#foo{border:1%var(--a)#ff0000}');
        },
    },
    {
        name: 'generate: with sourceMap returns { css, map } and the exact mapping',
        run: () => {
            const ast = css.parse('.a {\n  color: red;\n}\n', { filename: 'test.css', positions: true });
            const result = css.generate(ast, { sourceMap: true });
            assertEqual(result.css, '.a{color:red}');
            assertEqual(
                result.map.toString(),
                '{"version":3,"sources":["test.css"],"names":[],"mappings":"AAAA,E,CACE,S"}',
            );
        },
    },
    {
        name: 'generate: throws on an unknown node type',
        run: () => {
            const err = assertThrows(() => css.generate({ type: 'NotARealNode' }));
            assert(/Unknown node type/.test(err.message), `expected "Unknown node type", got: ${err.message}`);
        },
    },
    {
        name: 'generate: parse -> generate -> parse round-trips to an equivalent AST',
        run: () => {
            const source = '.a{color:#ff0000}.b{display:block;float:left}@media foo{.c{color:red}}';
            const ast1 = css.parse(source);
            const regenerated = css.generate(ast1);
            assertEqual(regenerated, source);
            // parsing the regenerated CSS yields the same serialization (stable round-trip)
            assertEqual(css.generate(css.parse(regenerated)), source);
        },
    },
];
