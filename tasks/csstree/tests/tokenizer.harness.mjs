// Capability: tokenize (CSS text -> token stream) and the exported token type tables.
import * as css from 'stylesheet-tree';
import { assert, assertEqual, assertDeepEqual } from './assert.mjs';

export default [
    {
        name: 'tokenize: emits typed tokens with correct source slices in order',
        run: () => {
            const source = '.a { color: red }';
            const tokens = [];
            css.tokenize(source, (type, start, end) => {
                tokens.push({ name: css.tokenNames[type], text: source.slice(start, end) });
            });
            // first six tokens describe the selector + block opening
            assertDeepEqual(tokens.slice(0, 6).map((t) => t.name), [
                'delim-token', 'ident-token', 'whitespace-token', '{-token', 'whitespace-token', 'ident-token',
            ]);
            assertEqual(tokens[0].text, '.');
            assertEqual(tokens[1].text, 'a');
            assertEqual(tokens[5].text, 'color');
        },
    },
    {
        name: 'tokenize: distinguishes dimension, number, and hash tokens in a value',
        run: () => {
            const source = '10px #fff 42';
            const tokens = [];
            css.tokenize(source, (type, start, end) => {
                tokens.push({ name: css.tokenNames[type], text: source.slice(start, end) });
            });
            // full ordered stream: 10px -> dimension, #fff -> hash, 42 -> number,
            // each pair separated by a single whitespace-token
            assertDeepEqual(tokens.map((t) => t.name), [
                'dimension-token', 'whitespace-token', 'hash-token', 'whitespace-token', 'number-token',
            ]);
            assertEqual(tokens[0].text, '10px');
            assertEqual(tokens[2].text, '#fff');
            assertEqual(tokens[4].text, '42');
        },
    },
    {
        name: 'tokenize: token type tables round-trip name <-> numeric code',
        run: () => {
            const identCode = css.tokenTypes.Ident;
            assertEqual(css.tokenNames[identCode], 'ident-token');
            const hashCode = css.tokenTypes.Hash;
            assertEqual(css.tokenNames[hashCode], 'hash-token');
        },
    },
];
