// Capability: find / findLast / findAll — locating nodes in an AST by predicate.
import * as css from 'stylesheet-tree';
import { assertEqual, assertDeepEqual } from './assert.mjs';

export default [
    {
        name: 'find: returns the first node in natural order matching the predicate',
        run: () => {
            const ast = css.parse('.a { color: red } .b { color: green }');
            const node = css.find(ast, (n) => n.type === 'Decl' && n.property === 'color');
            assertEqual(css.generate(node), 'color:red');
        },
    },
    {
        name: 'findLast: returns the first match in reverse order',
        run: () => {
            const ast = css.parse('.a { color: red } .b { color: green }');
            const node = css.findLast(ast, (n) => n.type === 'Decl' && n.property === 'color');
            assertEqual(css.generate(node), 'color:green');
        },
    },
    {
        name: 'findAll: returns every matching node in natural order',
        run: () => {
            const ast = css.parse('.a { color: red } .b { color: green }');
            const nodes = css.findAll(ast, (n) => n.type === 'Decl' && n.property === 'color');
            assertEqual(nodes.length, 2);
            assertDeepEqual(nodes.map((d) => css.generate(d)), ['color:red', 'color:green']);
        },
    },
];
