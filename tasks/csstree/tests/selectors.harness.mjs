// Capability: selector parsing — the full range of simple selectors, combinators, attribute
// selectors, and structural pseudo-classes a user writes. These exercise the selector grammar and
// its round-trip serialization (a subsystem the basic parse cases only touch lightly).
import * as css from 'stylesheet-tree';
import { assert, assertEqual, assertDeepEqual } from './assert.mjs';

const types = (list) => list.toArray().map((n) => n.type);

export default [
    {
        name: 'selector: a compound selector splits into type, id, and class simple selectors',
        run: () => {
            const sel = css.parse('a#main.active', { context: 'selector' });
            assertDeepEqual(types(sel.children), ['TypeMatch', 'IdMatch', 'ClassMatch']);
            assertEqual(sel.children.first.name, 'a');
        },
    },
    {
        name: 'selector: descendant/child/sibling combinators appear as Joiner nodes',
        run: () => {
            const sel = css.parse('.a > .b + .c ~ .d', { context: 'selector' });
            const combinators = sel.children.toArray()
                .filter((n) => n.type === 'Joiner')
                .map((n) => n.name);
            assertDeepEqual(combinators, ['>', '+', '~']);
            assertEqual(css.generate(sel), '.a>.b+.c~.d');
        },
    },
    {
        name: 'selector: an attribute selector captures name, matcher, and value',
        run: () => {
            const sel = css.parse('[href^="http"]', { context: 'selector' });
            const attr = sel.children.first;
            assertEqual(attr.type, 'AttrMatch');
            assertEqual(attr.name.name, 'href');
            assertEqual(attr.matcher, '^=');
            assertEqual(attr.value.type, 'String');
            assertEqual(attr.value.value, 'http');
            assertEqual(css.generate(sel), '[href^="http"]');
        },
    },
    {
        name: 'selector: a structural pseudo-class parses its An+B argument as an Nth/AnPlusB node',
        run: () => {
            const sel = css.parse(':nth-child(2n+1)', { context: 'selector' });
            const pseudo = sel.children.first;
            assertEqual(pseudo.type, 'PseudoClassMatch');
            assertEqual(pseudo.name, 'nth-child');
            const nth = pseudo.children.first;
            assertEqual(nth.type, 'Nth');
            assertEqual(nth.nth.type, 'AnPlusB');
            assertEqual(nth.nth.a, '2');
            assertEqual(nth.nth.b, '1');
            assertEqual(css.generate(sel), ':nth-child(2n+1)');
        },
    },
    {
        name: 'selector: a functional pseudo-class (:not) holds a nested selector and round-trips',
        run: () => {
            const source = 'a:not(.b):hover::before';
            const sel = css.parse(source, { context: 'selector' });
            const not = sel.children.toArray().find((n) => n.type === 'PseudoClassMatch' && n.name === 'not');
            assert(not, ':not should be a PseudoClassMatch');
            assertEqual(css.generate(sel), source);
        },
    },
    {
        name: 'selector: a pseudo-element uses "::" and parses as PseudoElemMatch',
        run: () => {
            const sel = css.parse('::before', { context: 'selector' });
            const pseudo = sel.children.first;
            assertEqual(pseudo.type, 'PseudoElemMatch');
            assertEqual(pseudo.name, 'before');
            assertEqual(css.generate(sel), '::before');
        },
    },
    {
        name: 'selector: a selector list preserves each complex selector as its own MatchSeq node',
        run: () => {
            const list = css.parse('.a:hover, #b > .c', { context: 'selectorList' });
            assertEqual(list.type, 'MatchGroup');
            assertEqual(list.children.size, 2);
            assertDeepEqual(list.children.toArray().map((s) => s.type), ['MatchSeq', 'MatchSeq']);
            assertEqual(css.generate(list), '.a:hover,#b>.c');
        },
    },
];
