// Capability: value component parsing — the typed nodes a declaration value decomposes into
// (functions, url, unicode-range, dimensions/percentages/numbers) and their round-trip.
import * as css from 'stylesheet-tree';
import { assertEqual, assertDeepEqual } from './assert.mjs';

export default [
    {
        name: 'value: a function call parses as a Function node with name and argument children',
        run: () => {
            const value = css.parse('calc(1px + 2px)', { context: 'value' });
            const fn = value.children.first;
            assertEqual(fn.type, 'Function');
            assertEqual(fn.name, 'calc');
            assertEqual(css.generate(value), 'calc(1px + 2px)');
        },
    },
    {
        name: 'value: a url() with a quoted argument parses as a Url node with the inner string',
        run: () => {
            const value = css.parse('url("http://x.com/a.png")', { context: 'value' });
            const url = value.children.first;
            assertEqual(url.type, 'Url');
            assertEqual(url.value, 'http://x.com/a.png');
        },
    },
    {
        name: 'value: a unicode-range token parses as a UnicodeRange node',
        run: () => {
            const value = css.parse('U+0-7F', { context: 'value' });
            const ur = value.children.first;
            assertEqual(ur.type, 'UnicodeRange');
            assertEqual(ur.value, 'U+0-7F');
        },
    },
    {
        name: 'value: numeric component types are distinguished (Percentage / Dimension / Number)',
        run: () => {
            const value = css.parse('50% 10px 3', { context: 'value' });
            assertDeepEqual(value.children.toArray().map((n) => n.type), ['Percentage', 'Dimension', 'Number']);
            const dim = value.children.toArray()[1];
            assertEqual(dim.value, '10');
            assertEqual(dim.unit, 'px');
        },
    },
    {
        name: 'value: a hex color parses as a Hash node whose value excludes the leading #',
        run: () => {
            const value = css.parse('#ff8800', { context: 'value' });
            const hash = value.children.first;
            assertEqual(hash.type, 'Hash');
            assertEqual(hash.value, 'ff8800');
        },
    },
];
