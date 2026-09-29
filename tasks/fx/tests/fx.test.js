// Hidden e2e suite for the fx task (Excel-formula tokenizer/parser/reference toolkit). Drives the
// public API and asserts EXACT outputs (token arrays, AST objects, reference objects, strings). All
// expected values were captured from the reference @borgar/fx v5.0.5. Uses Node's built-in runner.
//
// Structural results (tokens, AST nodes, reference objects) are compared by their JSON-normalized
// shape — the structure a user observes — so a valid implementation may use any internal object
// representation (plain objects, class instances, etc.). Strings/numbers/booleans compare directly.
const { test } = require("node:test");
const assert = require("node:assert");
const fx = require("/app/fx.js");

const norm = (x) => (x === undefined ? undefined : JSON.parse(JSON.stringify(x)));
const tk = (s, o) => fx.tokenize(s, o);            // raw tokens (also fed into other fns)
const ntk = (s, o) => norm(fx.tokenize(s, o));     // normalized token list
const ast = (s, o) => norm(fx.parse(fx.tokenize(s), o));
const P = (s, o) => fx.parse(fx.tokenize(s), o);   // raw node (for type guards)

// ---------------------------------------------------------------- tokenize
test("tokenize splits a formula into bare {type,value} tokens", () => {
  assert.deepStrictEqual(ntk("=SUM(A1:B2)"), [
    { type: "fx_prefix", value: "=" }, { type: "func", value: "SUM" },
    { type: "operator", value: "(" }, { type: "range", value: "A1:B2" },
    { type: "operator", value: ")" }]);
});

test("tokenize withLocation adds [start,end] loc arrays", () => {
  assert.deepStrictEqual(ntk("=A1+2", { withLocation: true }), [
    { type: "fx_prefix", value: "=", loc: [0, 1] }, { type: "range", value: "A1", loc: [1, 3] },
    { type: "operator", value: "+", loc: [3, 4] }, { type: "number", value: "2", loc: [4, 5] }]);
});

test("tokenize mergeRefs:false keeps context/range parts separate", () => {
  assert.deepStrictEqual(ntk("=Sheet1!A1:B2", { mergeRefs: false }), [
    { type: "fx_prefix", value: "=" }, { type: "context", value: "Sheet1" },
    { type: "operator", value: "!" }, { type: "range", value: "A1" },
    { type: "operator", value: ":" }, { type: "range", value: "B2" }]);
});

test("tokenize folds a leading minus into a number, but keeps binary minus separate", () => {
  assert.deepStrictEqual(ntk("=-1"), [{ type: "fx_prefix", value: "=" }, { type: "number", value: "-1" }]);
  assert.deepStrictEqual(ntk("=1-1"), [
    { type: "fx_prefix", value: "=" }, { type: "number", value: "1" },
    { type: "operator", value: "-" }, { type: "number", value: "1" }]);
});

test("tokenize marks an unterminated string", () => {
  assert.deepStrictEqual(ntk('="Hello'), [
    { type: "fx_prefix", value: "=" }, { type: "string", value: '"Hello', unterminated: true }]);
});

test("tokenize recognizes booleans and error literals", () => {
  assert.deepStrictEqual(ntk("=TRUE+#REF!"), [
    { type: "fx_prefix", value: "=" }, { type: "bool", value: "TRUE" },
    { type: "operator", value: "+" }, { type: "error", value: "#REF!" }]);
});

test("tokenize captures a structured reference as one token", () => {
  assert.deepStrictEqual(ntk("=Table1[[#Data],[Col]]"), [
    { type: "fx_prefix", value: "=" }, { type: "structured", value: "Table1[[#Data],[Col]]" }]);
});

test("tokenize with r1c1 reads an R1C1 range token", () => {
  assert.deepStrictEqual(ntk("=R[-1]C", { r1c1: true }), [
    { type: "fx_prefix", value: "=" }, { type: "range", value: "R[-1]C" }]);
});

test("tokenize keeps a doubled-quote escape verbatim in the string token", () => {
  assert.deepStrictEqual(ntk('="a""b"'), [
    { type: "fx_prefix", value: "=" }, { type: "string", value: '"a""b"' }]);
});

test("tokenize distinguishes a named range token", () => {
  assert.deepStrictEqual(ntk("=income*2"), [
    { type: "fx_prefix", value: "=" }, { type: "range_named", value: "income" },
    { type: "operator", value: "*" }, { type: "number", value: "2" }]);
});

// ---------------------------------------------------------------- parse (AST)
test("parse a number literal coerces value and keeps raw", () => {
  assert.deepStrictEqual(ast("=1.5e3"), { type: "Literal", value: 1500, raw: "1.5e3" });
});

test("parse a string literal unescapes doubled quotes", () => {
  assert.deepStrictEqual(ast('="foo""bar"'), { type: "Literal", value: 'foo"bar', raw: '"foo""bar"' });
});

test("parse boolean and error literals", () => {
  assert.deepStrictEqual(ast("=TRUE"), { type: "Literal", value: true, raw: "TRUE" });
  assert.deepStrictEqual(ast("=#REF!"), { type: "ErrorLiteral", value: "#REF!", raw: "#REF!" });
});

test("parse reference identifiers carry the right kind", () => {
  assert.deepStrictEqual(ast("=A1"), { type: "ReferenceIdentifier", value: "A1", kind: "range" });
  assert.deepStrictEqual(ast("=A:B"), { type: "ReferenceIdentifier", value: "A:B", kind: "beam" });
  assert.deepStrictEqual(ast("=income"), { type: "ReferenceIdentifier", value: "income", kind: "name" });
  assert.deepStrictEqual(ast("=Table1[Col]"), { type: "ReferenceIdentifier", value: "Table1[Col]", kind: "table" });
});

test("parse a call expression with a missing (null) argument", () => {
  assert.deepStrictEqual(ast("=SUM(1,,3)"), {
    type: "CallExpression", callee: { type: "Identifier", name: "SUM" },
    arguments: [{ type: "Literal", value: 1, raw: "1" }, null, { type: "Literal", value: 3, raw: "3" }] });
});

test("parse unary and binary operators with precedence", () => {
  assert.deepStrictEqual(ast("=-A1+2%"), {
    type: "BinaryExpression", operator: "+", arguments: [
      { type: "UnaryExpression", operator: "-", arguments: [{ type: "ReferenceIdentifier", value: "A1", kind: "range" }] },
      { type: "UnaryExpression", operator: "%", arguments: [{ type: "Literal", value: 2, raw: "2" }] }] });
});

test("parse an array expression into rows of columns", () => {
  assert.deepStrictEqual(ast("={1,2;3,4}"), {
    type: "ArrayExpression", elements: [
      [{ type: "Literal", value: 1, raw: "1" }, { type: "Literal", value: 2, raw: "2" }],
      [{ type: "Literal", value: 3, raw: "3" }, { type: "Literal", value: 4, raw: "4" }]] });
});

test("parse the whitespace intersection operator as a single-space binary op", () => {
  assert.deepStrictEqual(ast("=A1:A10 B1:B10"), {
    type: "BinaryExpression", operator: " ", arguments: [
      { type: "ReferenceIdentifier", value: "A1:A10", kind: "range" },
      { type: "ReferenceIdentifier", value: "B1:B10", kind: "range" }] });
});

test("parse a nested call with a comparison argument", () => {
  assert.deepStrictEqual(ast('=IF(A1>2,"y","n")'), {
    type: "CallExpression", callee: { type: "Identifier", name: "IF" }, arguments: [
      { type: "BinaryExpression", operator: ">", arguments: [
        { type: "ReferenceIdentifier", value: "A1", kind: "range" }, { type: "Literal", value: 2, raw: "2" }] },
      { type: "Literal", value: "y", raw: '"y"' }, { type: "Literal", value: "n", raw: '"n"' }] });
});

test("parse a LAMBDA expression", () => {
  assert.deepStrictEqual(ast("=LAMBDA(x,x+1)"), {
    type: "LambdaExpression", params: [{ type: "Identifier", name: "x" }],
    body: { type: "BinaryExpression", operator: "+", arguments: [
      { type: "ReferenceIdentifier", value: "x", kind: "name" }, { type: "Literal", value: 1, raw: "1" }] } });
});

// ---------------------------------------------------------------- stringifyTokens
test("stringifyTokens concatenates token values back to the source", () => {
  assert.strictEqual(fx.stringifyTokens(tk("=SUM( A1 )")), "=SUM( A1 )");
});

// ---------------------------------------------------------------- A1 references
test("parseA1Ref of a plain cell (0-based coords, all flags false)", () => {
  assert.deepStrictEqual(norm(fx.parseA1Ref("A1")), {
    context: [], range: { top: 0, left: 0, bottom: 0, right: 0, $top: false, $left: false, $bottom: false, $right: false } });
});

test("parseA1Ref with sheet and absolute $ flags", () => {
  assert.deepStrictEqual(norm(fx.parseA1Ref("Sheet1!A$1:$B2")), {
    context: ["Sheet1"], range: { top: 0, left: 0, bottom: 1, right: 1, $top: true, $left: false, $bottom: false, $right: true } });
});

test("parseA1Ref of a whole-column beam leaves row bounds null", () => {
  assert.deepStrictEqual(norm(fx.parseA1Ref("A:A")), {
    context: [], range: { top: null, left: 0, bottom: null, right: 0, $top: false, $left: false, $bottom: false, $right: false } });
});

test("parseA1Ref unwraps a quoted sheet name with an escaped apostrophe", () => {
  assert.deepStrictEqual(norm(fx.parseA1Ref("'Sheet1''s'!A1")), {
    context: ["Sheet1's"], range: { top: 0, left: 0, bottom: 0, right: 0, $top: false, $left: false, $bottom: false, $right: false } });
});

test("parseA1Ref of a defined name returns a name reference", () => {
  assert.deepStrictEqual(norm(fx.parseA1Ref("income")), { context: [], name: "income" });
});

test("stringifyA1Ref round-trips a parsed reference", () => {
  assert.strictEqual(fx.stringifyA1Ref(fx.parseA1Ref("Sheet1!A$1:$B2")), "Sheet1!A$1:$B2");
});

// ---------------------------------------------------------------- R1C1 references
test("parseR1C1Ref: relative rows are offsets, absolute cols are 0-based", () => {
  assert.deepStrictEqual(norm(fx.parseR1C1Ref("Sheet1!R[9]C9")), {
    context: ["Sheet1"], range: { r0: 9, c0: 8, r1: 9, c1: 8, $r0: false, $c0: true, $r1: false, $c1: true } });
});

test("parseR1C1Ref of an all-absolute reference", () => {
  assert.deepStrictEqual(norm(fx.parseR1C1Ref("R1C1")), {
    context: [], range: { r0: 0, c0: 0, r1: 0, c1: 0, $r0: true, $c0: true, $r1: true, $c1: true } });
});

test("parseR1C1Ref treats R0 as a name, not a range", () => {
  assert.deepStrictEqual(norm(fx.parseR1C1Ref("R0")), { context: [], name: "R0" });
});

test("stringifyR1C1Ref round-trips a parsed reference", () => {
  assert.strictEqual(fx.stringifyR1C1Ref(fx.parseR1C1Ref("Sheet1!R[9]C9")), "Sheet1!R[9]C9");
});

// ---------------------------------------------------------------- structured references
test("parseStructRef of table[col]", () => {
  assert.deepStrictEqual(norm(fx.parseStructRef("table[col]")), { context: [], table: "table", columns: ["col"], sections: [] });
});

test("parseStructRef of a section-only reference", () => {
  assert.deepStrictEqual(norm(fx.parseStructRef("[#All]")), { context: [], table: "", columns: [], sections: ["all"] });
});

test("parseStructRef with a section and a column range", () => {
  assert.deepStrictEqual(norm(fx.parseStructRef("[[#Data],[my column]:otherColumn]")), {
    context: [], table: "", columns: ["my column", "otherColumn"], sections: ["data"] });
});

test("stringifyStructRef round-trips (and supports the this-row shorthand)", () => {
  assert.strictEqual(
    fx.stringifyStructRef(fx.parseStructRef("workbook.xlsx!tableName[[#Data],[my column]:[fo'@o]]")),
    "workbook.xlsx!tableName[[#Data],[my column]:[fo'@o]]");
  assert.strictEqual(
    fx.stringifyStructRef({ table: "Table2", columns: ["col1"], sections: ["this row"] }, { thisRow: true }),
    "Table2[[#This row],[col1]]");
});

// ---------------------------------------------------------------- column conversion
test("toCol maps a 0-based index to letters (incl. the max column)", () => {
  assert.deepStrictEqual([0, 26, 701, 18277, 16383].map(fx.toCol), ["A", "AA", "ZZ", "ZZZ", "XFD"]);
});

test("fromCol maps letters to a 0-based index (case-insensitive)", () => {
  assert.deepStrictEqual(["A", "AA", "zz", "ZZZ", "XFD"].map(fx.fromCol), [0, 26, 701, 18277, 16383]);
});

// ---------------------------------------------------------------- range utilities
test("addA1RangeBounds fills missing bounds to the sheet extents", () => {
  assert.deepStrictEqual(norm(fx.addA1RangeBounds({ top: 0, left: 0, $top: false, $left: false })), {
    top: 0, left: 0, $top: false, $left: false, bottom: 1048575, $bottom: false, right: 16383, $right: false });
});

test("fixFormulaRanges normalizes a reversed range to top-left order", () => {
  assert.strictEqual(fx.fixFormulaRanges("=B2:A1"), "=A1:B2");
});

test("fixFormulaRanges quotes a sheet prefix that needs it", () => {
  assert.strictEqual(fx.fixFormulaRanges("=Sch1!B2"), "='Sch1'!B2");
  assert.strictEqual(fx.fixFormulaRanges("=C!B2"), "='C'!B2");
});

test("mergeRefTokens collapses split reference parts into one token", () => {
  assert.deepStrictEqual(norm(fx.mergeRefTokens(tk("=Sheet1!A1:B2", { mergeRefs: false }))), [
    { type: "fx_prefix", value: "=" }, { type: "range", value: "Sheet1!A1:B2" }]);
});

// ---------------------------------------------------------------- A1 <-> R1C1 translation
test("translateFormulaToR1C1 converts absolute and relative refs against an anchor", () => {
  assert.strictEqual(fx.translateFormulaToR1C1("=$A$1", "B2"), "=R1C1");
  assert.strictEqual(fx.translateFormulaToR1C1("=SUM(E10,$E$2,Sheet!$E$3)", "D10"), "=SUM(RC[1],R2C5,Sheet!R3C5)");
});

test("translateFormulaToA1 wraps edges by default and emits #REF! when disabled", () => {
  assert.strictEqual(fx.translateFormulaToA1("=R[-1]C[-1]", "A1"), "=XFD1048576");
  assert.strictEqual(fx.translateFormulaToA1("=R[-1]C[-1]", "A1", { wrapEdges: false }), "=#REF!");
});

test("translateTokensToR1C1 operates on a token list", () => {
  assert.deepStrictEqual(norm(fx.translateTokensToR1C1(tk("=A1"), "B2")), [
    { type: "fx_prefix", value: "=" }, { type: "range", value: "R[-1]C[-1]" }]);
});

// ---------------------------------------------------------------- type guards & constants
test("token type guards classify tokens", () => {
  assert.deepStrictEqual(
    [fx.isRange(tk("=A1")[1]), fx.isFunction(tk("=SUM(1)")[1]), fx.isError(tk("=#REF!")[1]), fx.isWhitespace(tk("=A1 A1")[2])],
    [true, true, true, true]);
  // each guard must also REJECT a non-matching token (a constant-true stub would fail here)
  assert.deepStrictEqual(
    [fx.isRange(tk("=1")[1]), fx.isFunction(tk("=A1")[1]), fx.isError(tk("=1")[1]), fx.isWhitespace(tk("=A1")[1])],
    [false, false, false, false]);
});

test("AST node guards classify nodes", () => {
  assert.deepStrictEqual([fx.isLiteralNode(P("=1")), fx.isCallNode(P("=SUM(1)")), fx.isReferenceNode(P("=A1"))], [true, true, true]);
  assert.deepStrictEqual([fx.isLiteralNode(P("=SUM(1)")), fx.isCallNode(P("=1")), fx.isReferenceNode(P("=1"))], [false, false, false]);
});

test("stringifyStructRef uses the @ this-row shorthand by default", () => {
  assert.strictEqual(
    fx.stringifyStructRef({ table: "Table2", columns: ["col1"], sections: ["this row"] }),
    "Table2[@col1]");
});

// ================================================================ enrichment: harder surface
test("parse a LET expression (declarations + body)", () => {
  assert.deepStrictEqual(ast("=LET(x,1,x+1)"), {
    type: "LetExpression",
    declarations: [{ type: "LetDeclarator", id: { type: "Identifier", name: "x" }, init: { type: "Literal", value: 1, raw: "1" } }],
    body: { type: "BinaryExpression", operator: "+", arguments: [
      { type: "ReferenceIdentifier", value: "x", kind: "name" }, { type: "Literal", value: 1, raw: "1" }] } });
});

test("parse respects operator precedence (^ over * over +)", () => {
  assert.deepStrictEqual(ast("=1+2*3^2"), {
    type: "BinaryExpression", operator: "+", arguments: [
      { type: "Literal", value: 1, raw: "1" },
      { type: "BinaryExpression", operator: "*", arguments: [
        { type: "Literal", value: 2, raw: "2" },
        { type: "BinaryExpression", operator: "^", arguments: [
          { type: "Literal", value: 3, raw: "3" }, { type: "Literal", value: 2, raw: "2" }] }] }] });
});

test("parse string concatenation & and inequality <>", () => {
  assert.deepStrictEqual(ast('="a"&"b"<>"c"'), {
    type: "BinaryExpression", operator: "<>", arguments: [
      { type: "BinaryExpression", operator: "&", arguments: [
        { type: "Literal", value: "a", raw: '"a"' }, { type: "Literal", value: "b", raw: '"b"' }] },
      { type: "Literal", value: "c", raw: '"c"' }] });
});

test("parse a negative scientific-notation literal", () => {
  assert.deepStrictEqual(ast("=-1.5e-2"), { type: "Literal", value: -0.015, raw: "-1.5e-2" });
});

test("parse a nested array of mixed literal types", () => {
  assert.deepStrictEqual(ast('={1,"a";TRUE,#REF!}'), {
    type: "ArrayExpression", elements: [
      [{ type: "Literal", value: 1, raw: "1" }, { type: "Literal", value: "a", raw: '"a"' }],
      [{ type: "Literal", value: true, raw: "TRUE" }, { type: "ErrorLiteral", value: "#REF!", raw: "#REF!" }]] });
});

test("parse a call whose arguments include ranges", () => {
  assert.deepStrictEqual(ast("=SUM(A1:A5,B1)"), {
    type: "CallExpression", callee: { type: "Identifier", name: "SUM" }, arguments: [
      { type: "ReferenceIdentifier", value: "A1:A5", kind: "range" },
      { type: "ReferenceIdentifier", value: "B1", kind: "range" }] });
});

test("tokenize a scientific number, percent operator, and error literal", () => {
  assert.deepStrictEqual(ntk("=1.5e-3%+#DIV/0!"), [
    { type: "fx_prefix", value: "=" }, { type: "number", value: "1.5e-3" }, { type: "operator", value: "%" },
    { type: "operator", value: "+" }, { type: "error", value: "#DIV/0!" }]);
});

test("tokenize an R1C1 range as one token", () => {
  assert.deepStrictEqual(ntk("=R1C1:R2C2", { r1c1: true }), [
    { type: "fx_prefix", value: "=" }, { type: "range", value: "R1C1:R2C2" }]);
});

test("tokenize emits a whitespace token for the intersection operator", () => {
  assert.deepStrictEqual(ntk("=A1 B1"), [
    { type: "fx_prefix", value: "=" }, { type: "range", value: "A1" },
    { type: "whitespace", value: " " }, { type: "range", value: "B1" }]);
});

test("tokenize merges a workbook+sheet reference into one range token", () => {
  assert.deepStrictEqual(ntk("=[Book1]Sheet1!A1"), [
    { type: "fx_prefix", value: "=" }, { type: "range", value: "[Book1]Sheet1!A1" }]);
});

test("tokenize the @ implicit-intersection operator", () => {
  assert.deepStrictEqual(ntk("=@A1:A5"), [
    { type: "fx_prefix", value: "=" }, { type: "operator", value: "@" }, { type: "range", value: "A1:A5" }]);
});

test("parseA1Ref of a mixed-absolute range", () => {
  assert.deepStrictEqual(norm(fx.parseA1Ref("$A1:B$2")), {
    context: [], range: { top: 0, left: 0, bottom: 1, right: 1, $top: false, $left: true, $bottom: true, $right: false } });
});

test("parseA1Ref of a full-row beam and of a workbook-qualified cell", () => {
  assert.deepStrictEqual(norm(fx.parseA1Ref("1:1")), {
    context: [], range: { top: 0, left: null, bottom: 0, right: null, $top: false, $left: false, $bottom: false, $right: false } });
  assert.deepStrictEqual(norm(fx.parseA1Ref("[Book1]Sheet1!A1")), {
    context: ["Book1", "Sheet1"], range: { top: 0, left: 0, bottom: 0, right: 0, $top: false, $left: false, $bottom: false, $right: false } });
});

test("parseA1Range parses just the range portion", () => {
  assert.deepStrictEqual(norm(fx.parseA1Range("A1:B2")), {
    top: 0, left: 0, bottom: 1, right: 1, $top: false, $left: false, $bottom: false, $right: false });
});

test("parseR1C1Ref of a mixed relative/absolute range round-trips", () => {
  assert.deepStrictEqual(norm(fx.parseR1C1Ref("R[-2]C3:R[-1]C4")), {
    context: [], range: { r0: -2, $r0: false, r1: -1, $r1: false, c0: 2, $c0: true, c1: 3, $c1: true } });
  assert.strictEqual(fx.stringifyR1C1Ref(fx.parseR1C1Ref("R[-2]C3:R[-1]C4")), "R[-2]C3:R[-1]C4");
});

test("parseR1C1Ref of a whole-row beam (columns null)", () => {
  assert.deepStrictEqual(norm(fx.parseR1C1Ref("R1:R3")), {
    context: [], range: { r0: 0, $r0: true, r1: 2, $r1: true, c0: null, $c0: false, c1: null, $c1: false } });
});

test("parseStructRef of a headers+data section combo round-trips", () => {
  assert.deepStrictEqual(norm(fx.parseStructRef("Tbl[[#Headers],[#Data]]")), {
    context: [], table: "Tbl", columns: [], sections: ["headers", "data"] });
  assert.strictEqual(fx.stringifyStructRef(fx.parseStructRef("Tbl[[#Headers],[#Data]]")), "Tbl[[#Headers],[#Data]]");
});

test("parseStructRef of the @column this-row shorthand", () => {
  assert.deepStrictEqual(norm(fx.parseStructRef("Tbl[@Col]")), {
    context: [], table: "Tbl", columns: ["Col"], sections: ["this row"] });
});

test("translation of ranges and round-trips (formula and token forms)", () => {
  assert.strictEqual(fx.translateFormulaToR1C1("=SUM(A1:B2)", "C3"), "=SUM(R[-2]C[-2]:R[-1]C[-1])");
  assert.strictEqual(fx.translateFormulaToA1("=R[-2]C[-2]", "C3"), "=A1");
  assert.deepStrictEqual(norm(fx.translateTokensToA1(tk("=R[-1]C", { r1c1: true }), "B2")), [
    { type: "fx_prefix", value: "=" }, { type: "range", value: "B1" }]);
});

test("more token and node type guards", () => {
  assert.deepStrictEqual(
    [fx.isReference(tk("=A1")[1]), fx.isOperator(tk("=1+1")[2]), fx.isLiteral(tk("=1")[1]),
     fx.isBinaryNode(P("=1+1")), fx.isUnaryNode(P("=-A1")), fx.isArrayNode(P("={1}")), fx.isLambdaNode(P("=LAMBDA(x,x)"))],
    [true, true, true, true, true, true, true]);
  // isReference also accepts a named reference and a structured reference
  assert.deepStrictEqual(
    [fx.isReference(tk("=income*2")[1]), fx.isReference(tk("=Table1[[#Data],[Col]]")[1])], [true, true]);
  // and every guard rejects a non-matching input
  assert.deepStrictEqual(
    [fx.isReference(tk("=1")[1]), fx.isOperator(tk("=1")[1]), fx.isLiteral(tk("=1+1")[2]),
     fx.isBinaryNode(P("=1")), fx.isUnaryNode(P("=1")), fx.isArrayNode(P("=1")), fx.isLambdaNode(P("=1"))],
    [false, false, false, false, false, false, false]);
});

test("fixFormulaRanges normalizes structured refs and lowercases cell refs", () => {
  assert.strictEqual(fx.fixFormulaRanges("=tbl[ [#data] , [col] ]"), "=tbl[[#Data],[col]]");
  assert.strictEqual(fx.fixFormulaRanges("=a1:b2"), "=A1:B2");
});
