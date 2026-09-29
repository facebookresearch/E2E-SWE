// Capability: util functions — property/keyword name analysis, ident/string/url codecs, clone, and
// List<->array AST conversion.
import * as css from 'stylesheet-tree';
import { assert, assertEqual, assertDeepEqual } from './assert.mjs';

export default [
    {
        name: 'property(): decomposes vendor prefix and hack for a declaration property name',
        run: () => {
            const info = css.property('*-vendor-property');
            assertEqual(info.basename, 'property');
            assertEqual(info.name, '-vendor-property');
            assertEqual(info.hack, '*');
            assertEqual(info.vendor, '-vendor-');
            assertEqual(info.prefix, '*-vendor-');
            assertEqual(info.custom, false);
        },
    },
    {
        name: 'property(): recognizes custom properties and is case-insensitive for standard names',
        run: () => {
            const custom = css.property('--test-var');
            assertEqual(custom.name, '--test-var');
            assertEqual(custom.custom, true);
            // standard names normalize to lower case and return the same frozen instance
            assert(css.property('name') === css.property('NAME'), 'same normalized name -> same instance');
            assertEqual(css.property('NAME').name, 'name');
            // custom property names are case-sensitive
            assert(css.property('--custom') !== css.property('--Custom'), 'custom names are case-sensitive');
        },
    },
    {
        name: 'keyword(): analyzes an identifier without hack detection',
        run: () => {
            const info = css.keyword('-vendor-keyword');
            assertEqual(info.basename, 'keyword');
            assertEqual(info.name, '-vendor-keyword');
            assertEqual(info.vendor, '-vendor-');
            assertEqual(info.custom, false);
        },
    },
    {
        name: 'ident codec: decode and encode are inverse for escaped identifiers',
        run: () => {
            assertEqual(css.ident.decode('hello\\9 \\ world'), 'hello\t world');
            assertEqual(css.ident.encode('hello\t world'), 'hello\\9 \\ world');
        },
    },
    {
        name: 'string codec: decode strips quotes/escapes; encode quotes and escapes',
        run: () => {
            assertEqual(css.string.decode('"hello\\9  \\"world\\""'), 'hello\t "world"');
            assertEqual(css.string.encode('hello\t "world"'), '"hello\\9  \\"world\\""');
            // apostrophe mode uses single quotes
            assertEqual(css.string.encode('hello\t "world"', true), "'hello\\9  \"world\"'");
        },
    },
    {
        name: 'url codec: decode and encode handle escaped parentheses and spaces',
        run: () => {
            assertEqual(css.url.decode('url(file\\ \\(1\\).ext)'), 'file (1).ext');
            assertEqual(css.url.encode('file (1).ext'), 'url(file\\ \\(1\\).ext)');
        },
    },
    {
        name: 'clone(): produces an independent deep copy that can be mutated in isolation',
        run: () => {
            const orig = css.parse('.test { color: red }');
            const copy = css.clone(orig);
            css.walk(copy, (node) => {
                if (node.type === 'ClassMatch') { node.name = 'replaced'; }
            });
            assertEqual(css.generate(orig), '.test{color:red}', 'original must be untouched');
            assertEqual(css.generate(copy), '.replaced{color:red}', 'copy reflects mutation');
        },
    },
    {
        name: 'fromPlainObject/toPlainObject: convert children between List and Array',
        run: () => {
            // toPlainObject must recursively turn every List `children` into a plain Array,
            // preserving node content at every level (not just re-wrapping the top container).
            const plain = css.toPlainObject(css.parse('.a{color:red}'));
            assert(Array.isArray(plain.children), 'top-level children should be an Array after toPlainObject');
            const rule = plain.children[0];
            assert(Array.isArray(rule.block.children), 'nested block children should be an Array (recursion required)');
            assertEqual(rule.block.children[0].property, 'color', 'node content must survive the conversion');

            // fromPlainObject is the inverse: every Array `children` becomes a List, again at every
            // level, and the reconstructed AST round-trips back to the original CSS.
            const ast = css.fromPlainObject(plain);
            assert(ast.children instanceof css.List, 'top-level children should be a List after fromPlainObject');
            assert(
                ast.children.first.block.children instanceof css.List,
                'nested block children should be a List (recursion required)',
            );
            assertEqual(css.generate(ast), '.a{color:red}', 'content preserved through the List<->Array round-trip');
        },
    },
];
