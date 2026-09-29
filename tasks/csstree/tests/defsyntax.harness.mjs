// Capability: definitionSyntax — parse/walk/generate the CSS Value Definition Syntax grammar.
import * as css from 'stylesheet-tree';
import { assert, assertEqual, assertDeepEqual } from './assert.mjs';

const ds = css.definitionSyntax;

export default [
    {
        name: 'definitionSyntax.parse: a "|" group yields the expected AST shape',
        run: () => {
            const ast = ds.parse('foo | bar');
            assertEqual(ast.type, 'Group');
            assertEqual(ast.combinator, '|');
            assertDeepEqual(ast.terms.map((t) => t.type), ['Keyword', 'Keyword']);
            assertDeepEqual(ast.terms.map((t) => t.name), ['foo', 'bar']);
        },
    },
    {
        name: 'definitionSyntax.parse: multiplier notation is captured as min/max/comma',
        run: () => {
            const hash = ds.parse('<number>#').terms[0];
            assertEqual(hash.type, 'Multiplier');
            assertEqual(hash.comma, true);
            assertEqual(hash.min, 1);
            assertEqual(hash.max, 0);
            assertEqual(hash.term.type, 'Type');
            assertEqual(hash.term.name, 'number');

            const range = ds.parse('<number>{2,4}').terms[0];
            assertEqual(range.type, 'Multiplier');
            assertEqual(range.comma, false);
            assertEqual(range.min, 2);
            assertEqual(range.max, 4);
        },
    },
    {
        name: 'definitionSyntax.walk: visits group and term nodes in order',
        run: () => {
            const ast = ds.parse('foo | bar');
            const visited = [];
            ds.walk(ast, (node) => visited.push(`${node.type}:${node.combinator || node.name || ''}`));
            assertDeepEqual(visited, ['Group:|', 'Keyword:foo', 'Keyword:bar']);
        },
    },
    {
        name: 'definitionSyntax.generate: serializes an AST back to its canonical definition string',
        run: () => {
            const ast = ds.parse('foo && bar || [ baz | qux ]');
            assertEqual(ds.generate(ast), 'foo && bar || [ baz | qux ]');
        },
    },
    {
        name: 'definitionSyntax.generate: forceBraces makes implicit groups explicit; compact strips spaces',
        run: () => {
            assertEqual(ds.generate(ds.parse('a b'), { forceBraces: true }), '[ a b ]');
            assertEqual(ds.generate(ds.parse('foo && bar || baz'), { compact: true }), 'foo&&bar||baz');
        },
    },
];
