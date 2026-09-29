"use strict";
// Hidden test suite for the astring task (node:test). Drives the agent's module at /app/astring.js
// via its `generate(node)` API: for each fixture it renders an ESTree AST and asserts the exact
// generated JavaScript source string. One test() per fixture = one CTRF entry (partial credit).
// Fixtures (AST + expected output) were captured from the reference implementation (astring@1.9.0);
// each AST is a clean ESTree tree with `start`/`end` removed and, on `Literal` nodes, `raw` removed
// so the generator must format literals from their `value`.
const { test } = require("node:test");
const assert = require("node:assert");
const { generate } = require("/app/astring.js");
const fixtures = require("/tests/fixtures.json");

for (const f of fixtures) {
  test(f.name, () => {
    assert.strictEqual(generate(f.ast), f.expected);
  });
}
