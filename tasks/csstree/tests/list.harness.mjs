// Capability: List — the doubly-linked list used for AST children. Exercises the Array-like query
// API and the mutation API a user relies on for tree transforms.
import * as css from 'stylesheet-tree';
import { assert, assertEqual, assertDeepEqual } from './assert.mjs';

export default [
    {
        name: 'List: appendData builds a list with correct size/first/last/toArray',
        run: () => {
            const list = new css.List();
            list.appendData('a');
            list.appendData('b');
            list.appendData('c');
            assertEqual(list.size, 3);
            assertEqual(list.isEmpty, false);
            assertEqual(list.first, 'a');
            assertEqual(list.last, 'c');
            assertDeepEqual(list.toArray(), ['a', 'b', 'c']);
        },
    },
    {
        name: 'List: fromArray/toArray convert between a plain array and a List',
        run: () => {
            const list = new css.List().fromArray(['x', 'y', 'z']);
            assertEqual(list.size, 3);
            assertDeepEqual(list.toArray(), ['x', 'y', 'z']);
        },
    },
    {
        name: 'List: map/filter/reduce/some/forEach behave like their Array counterparts',
        run: () => {
            const list = new css.List().fromArray(['a', 'b', 'c']);
            assertDeepEqual(list.map((x) => x.toUpperCase()).toArray(), ['A', 'B', 'C']);
            assertDeepEqual(list.filter((x) => x !== 'b').toArray(), ['a', 'c']);
            assertEqual(list.reduce((acc, x) => acc + x, ''), 'abc');
            assertEqual(list.some((x) => x === 'b'), true);
            assertEqual(list.some((x) => x === 'z'), false);
            const order = [];
            list.forEach((x) => order.push(x));
            assertDeepEqual(order, ['a', 'b', 'c']);
        },
    },
    {
        name: 'List: shift/pop remove and return the end items as list wrappers',
        run: () => {
            const list = new css.List().fromArray(['x', 'y', 'z']);
            const shifted = list.shift();
            assertEqual(shifted.data, 'x');
            assertDeepEqual(list.toArray(), ['y', 'z']);
            const popped = list.pop();
            assertEqual(popped.data, 'z');
            assertDeepEqual(list.toArray(), ['y']);
        },
    },
    {
        name: 'List: prependData/unshift add to the front',
        run: () => {
            const list = new css.List().fromArray(['b', 'c']);
            list.prependData('a');
            assertDeepEqual(list.toArray(), ['a', 'b', 'c']);
            list.unshift('start');
            assertEqual(list.first, 'start');
            assertEqual(list.size, 4);
        },
    },
];
