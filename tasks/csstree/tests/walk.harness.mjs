// Capability: walk (AST traversal). Exercises enter/leave ordering, the visit fast-path, reverse
// order, break/skip control, the ancestor-context `this`, and list mutation during traversal.
import * as css from 'stylesheet-tree';
import { assert, assertEqual, assertDeepEqual } from './assert.mjs';

export default [
    {
        name: 'walk: enter visits every node in natural (document) order',
        run: () => {
            const ast = css.parse('.a { color: red; }');
            const order = [];
            css.walk(ast, (node) => order.push(node.type));
            assertDeepEqual(order, [
                'Rootsheet', 'Rule', 'MatchGroup', 'MatchSeq', 'ClassMatch',
                'Block', 'Decl', 'Value', 'Identifier',
            ]);
        },
    },
    {
        name: 'walk: leave fires after a node\'s children, yielding post-order',
        run: () => {
            const ast = css.parse('.a { color: red; }');
            const order = [];
            css.walk(ast, { leave: (node) => order.push(node.type) });
            assertDeepEqual(order, [
                'ClassMatch', 'MatchSeq', 'MatchGroup', 'Identifier', 'Value',
                'Decl', 'Block', 'Rule', 'Rootsheet',
            ]);
        },
    },
    {
        name: 'walk: the visit option restricts the handler to one node type',
        run: () => {
            const ast = css.parse('.a { color: red; } .b { color: green; }');
            const names = [];
            css.walk(ast, { visit: 'ClassMatch', enter: (node) => names.push(node.name) });
            assertDeepEqual(names, ['a', 'b']);
        },
    },
    {
        name: 'walk: this.skip prevents descent into a node\'s subtree',
        run: () => {
            const ast = css.parse('.a { color: red; }');
            const seen = [];
            css.walk(ast, {
                enter(node) {
                    seen.push(node.type);
                    if (node.type === 'Block') { return this.skip; }
                },
            });
            // Block is visited, but its Decl/Value/Identifier children are skipped
            assert(seen.includes('Block'), 'Block should be visited');
            assert(!seen.includes('Decl'), 'Decl under skipped Block must not be visited');
        },
    },
    {
        name: 'walk: this.break halts traversal entirely',
        run: () => {
            const ast = css.parse('.a { color: red; } .b { color: green; }');
            const seen = [];
            css.walk(ast, {
                enter(node) {
                    seen.push(node.type);
                    if (node.type === 'ClassMatch') { return this.break; }
                },
            });
            assertEqual(seen[seen.length - 1], 'ClassMatch', 'traversal stops at first ClassMatch');
            // only one ClassMatch reached
            assertEqual(seen.filter((t) => t === 'ClassMatch').length, 1);
        },
    },
    {
        name: 'walk: reverse:true iterates children last-to-first',
        run: () => {
            const ast = css.parse('.a { color: red; }');
            const order = [];
            css.walk(ast, {
                reverse: true,
                enter: (node) => order.push(node.type),
            });
            // Block subtree is entered before MatchGroup in reverse order
            assertEqual(order[0], 'Rootsheet');
            assertEqual(order[1], 'Rule');
            assertEqual(order[2], 'Block', 'reverse visits Block before MatchGroup');
        },
    },
    {
        name: 'walk: handler context exposes closest ancestors (declaration + type filter)',
        run: () => {
            const ast = css.parse('@import url(x.css); .foo { background: url(foo.jpg); }');
            const urlsInDeclarations = [];
            css.walk(ast, function (node) {
                if (this.declaration !== null && node.type === 'Url') {
                    urlsInDeclarations.push(node.value);
                }
            });
            // the @import url is NOT inside a declaration; only the background url is
            assertDeepEqual(urlsInDeclarations, ['foo.jpg']);
        },
    },
    {
        name: 'walk: list.remove during traversal deletes nodes and reserializes correctly',
        run: () => {
            const ast = css.parse('.a { foo: 1; bar: 2; } .b { bar: 3; baz: 4; }');
            css.walk(ast, (node, item, list) => {
                if (node.type === 'Decl' && node.property === 'bar' && list) {
                    list.remove(item);
                }
            });
            assertEqual(css.generate(ast), '.a{foo:1}.b{baz:4}');
        },
    },
];
