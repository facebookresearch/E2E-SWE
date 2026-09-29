// Capability: at-rules — nesting, preludes, and blockless at-rules. These exercise the parser's
// at-rule handling and the generator's round-trip on nested structures a real stylesheet contains.
import * as css from 'stylesheet-tree';
import { assert, assertEqual, assertDeepEqual } from './assert.mjs';

export default [
    {
        name: 'atrule: nested @media / @supports round-trips with correct structure',
        run: () => {
            const source = '@media screen{@supports (display:grid){.a{color:red}}}';
            const ast = css.parse(source);
            const media = ast.children.first;
            assertEqual(media.type, 'Atrule');
            assertEqual(media.name, 'media');
            const supports = media.block.children.first;
            assertEqual(supports.type, 'Atrule');
            assertEqual(supports.name, 'supports');
            assertEqual(supports.block.children.first.type, 'Rule');
            assertEqual(css.generate(ast), source);
        },
    },
    {
        name: 'atrule: a blockless at-rule (@import) parses with a prelude and null block',
        run: () => {
            const ast = css.parse('@import url(base.css);');
            const atrule = ast.children.first;
            assertEqual(atrule.name, 'import');
            assertEqual(atrule.block, null);
            assert(atrule.prelude !== null, 'prelude should be present');
            assertEqual(css.generate(ast), '@import url(base.css);');
        },
    },
    {
        name: 'atrule: @font-face descriptors parse as a declaration block',
        run: () => {
            const ast = css.parse('@font-face { font-family: "X"; src: url(x.woff2) }');
            const atrule = ast.children.first;
            assertEqual(atrule.name, 'font-face');
            assertEqual(atrule.block.type, 'Block');
            const decls = atrule.block.children.toArray().filter((n) => n.type === 'Decl');
            assertDeepEqual(decls.map((d) => d.property), ['font-family', 'src']);
        },
    },
    {
        name: 'atrule: @keyframes with percentage-keyed rules round-trips',
        run: () => {
            const source = '@keyframes spin{0%{transform:rotate(0)}100%{transform:rotate(360deg)}}';
            const ast = css.parse(source);
            const kf = ast.children.first;
            assertEqual(kf.name, 'keyframes');
            assertEqual(css.generate(ast), source);
        },
    },
    {
        name: 'atrule: an exclamation comment is preserved through parse+generate',
        run: () => {
            assertEqual(css.generate(css.parse('/*! keep */ .a{color:red}')), '/*! keep */.a{color:red}');
        },
    },
];
