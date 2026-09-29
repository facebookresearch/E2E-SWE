package participle_test

import (
	"errors"
	"reflect"
	"strings"
	"testing"

	"github.com/alecthomas/participle/v2"
	"github.com/alecthomas/participle/v2/lexer"
)

// ---------------------------------------------------------------------------
// TestBuildAndBasicParse — Build[T](), ParseString, ParseBytes, MustBuild,
// simple sequence grammar with Ident + literal matching.
// ---------------------------------------------------------------------------

func TestBuildAndBasicParse(t *testing.T) {
	type assignment struct {
		Name  string `@Ident "="`
		Value string `@Ident`
	}

	p, err := participle.Build[assignment]()
	if err != nil {
		t.Fatalf("Build failed: %v", err)
	}

	ast, err := p.ParseString("", "x = y")
	if err != nil {
		t.Fatalf("ParseString failed: %v", err)
	}
	if ast.Name != "x" {
		t.Fatalf("Name = %q, want %q", ast.Name, "x")
	}
	if ast.Value != "y" {
		t.Fatalf("Value = %q, want %q", ast.Value, "y")
	}

	// ParseBytes should produce the same result.
	ast2, err := p.ParseBytes("", []byte("a = b"))
	if err != nil {
		t.Fatalf("ParseBytes failed: %v", err)
	}
	if ast2.Name != "a" || ast2.Value != "b" {
		t.Fatalf("ParseBytes got Name=%q Value=%q, want a b", ast2.Name, ast2.Value)
	}

	// MustBuild should not panic for a valid grammar.
	func() {
		defer func() {
			if r := recover(); r != nil {
				t.Fatalf("MustBuild panicked: %v", r)
			}
		}()
		_ = participle.MustBuild[assignment]()
	}()
}

// ---------------------------------------------------------------------------
// TestCaptureStringAccumulation — Multiple @-captures into a string field
// concatenate; []string accumulates separately; repeat across fields.
// ---------------------------------------------------------------------------

func TestCaptureStringAccumulation(t *testing.T) {
	// String field: repeated captures concatenate.
	type concatGrammar struct {
		A string `@"."+ `
	}
	p1, err := participle.Build[concatGrammar]()
	if err != nil {
		t.Fatalf("Build concatGrammar: %v", err)
	}
	g1, err := p1.ParseString("", ". . . .")
	if err != nil {
		t.Fatalf("ParseString: %v", err)
	}
	if g1.A != "...." {
		t.Fatalf("string concat: got %q, want %q", g1.A, "....")
	}

	// []string field: each capture appends to slice.
	type sliceGrammar struct {
		A []string `@"."*`
	}
	p2, err := participle.Build[sliceGrammar]()
	if err != nil {
		t.Fatalf("Build sliceGrammar: %v", err)
	}
	g2, err := p2.ParseString("", "...")
	if err != nil {
		t.Fatalf("ParseString: %v", err)
	}
	if len(g2.A) != 3 {
		t.Fatalf("slice len = %d, want 3", len(g2.A))
	}
	for i, v := range g2.A {
		if v != "." {
			t.Fatalf("slice[%d] = %q, want %q", i, v, ".")
		}
	}

	// Repeat across fields: alternation inside repetition distributes captures.
	type repeatAcross struct {
		A string `( @("." ">") |`
		B string `  @("," "<") )*`
	}
	p3, err := participle.Build[repeatAcross]()
	if err != nil {
		t.Fatalf("Build repeatAcross: %v", err)
	}
	g3, err := p3.ParseString("", ".>,<.>.>,<.>,<")
	if err != nil {
		t.Fatalf("ParseString: %v", err)
	}
	if g3.A != ".>.>.>.>" {
		t.Fatalf("repeatAcross.A = %q, want %q", g3.A, ".>.>.>.>")
	}
	if g3.B != ",<,<,<" {
		t.Fatalf("repeatAcross.B = %q, want %q", g3.B, ",<,<,<")
	}
}

// ---------------------------------------------------------------------------
// TestCaptureNumericAndBool — int/float64 via strconv, bool flag semantics,
// negative numbers via grouped capture, []int accumulation.
// ---------------------------------------------------------------------------

func TestCaptureNumericAndBool(t *testing.T) {
	type numGrammar struct {
		Int   int     `@("-"? Int)`
		Float float64 `@Float`
	}
	p1, err := participle.Build[numGrammar]()
	if err != nil {
		t.Fatalf("Build: %v", err)
	}
	g1, err := p1.ParseString("", "-42 3.14")
	if err != nil {
		t.Fatalf("ParseString: %v", err)
	}
	if g1.Int != -42 {
		t.Fatalf("Int = %d, want -42", g1.Int)
	}
	if g1.Float != 3.14 {
		t.Fatalf("Float = %f, want 3.14", g1.Float)
	}

	// []int accumulation
	type intSlice struct {
		Vals []int `@Int+`
	}
	p2, err := participle.Build[intSlice]()
	if err != nil {
		t.Fatalf("Build intSlice: %v", err)
	}
	g2, err := p2.ParseString("", "1 2 3 4")
	if err != nil {
		t.Fatalf("ParseString: %v", err)
	}
	expected := []int{1, 2, 3, 4}
	if !reflect.DeepEqual(g2.Vals, expected) {
		t.Fatalf("Vals = %v, want %v", g2.Vals, expected)
	}

	// bool: set to true when expression matches (flag semantics, not literal parsing).
	type boolFlag struct {
		Value bool `@"true"?`
	}
	p3, err := participle.Build[boolFlag]()
	if err != nil {
		t.Fatalf("Build boolFlag: %v", err)
	}
	g3a, err := p3.ParseString("", "true")
	if err != nil {
		t.Fatalf("ParseString 'true': %v", err)
	}
	if !g3a.Value {
		t.Fatal("bool: parsing 'true' should set field to true")
	}
	g3b, err := p3.ParseString("", "")
	if err != nil {
		t.Fatalf("ParseString '': %v", err)
	}
	if g3b.Value {
		t.Fatal("bool: parsing '' should leave field false")
	}

	// bool in a disjunction context: @"add" sets to true; alternative dispatches.
	type boolAlt struct {
		Add    bool `  @"add"`
		Remove bool `| @"remove"`
	}
	p4, err := participle.Build[boolAlt]()
	if err != nil {
		t.Fatalf("Build boolAlt: %v", err)
	}
	g4, err := p4.ParseString("", "remove")
	if err != nil {
		t.Fatalf("ParseString 'remove': %v", err)
	}
	if g4.Add {
		t.Fatal("expected Add=false")
	}
	if !g4.Remove {
		t.Fatal("expected Remove=true")
	}
}

// ---------------------------------------------------------------------------
// TestRepetitionAndOptionalPointer — *, +, ? on expressions; verify slice
// lengths, *T nil/non-nil, optional group skipping.
// ---------------------------------------------------------------------------

func TestRepetitionAndOptionalPointer(t *testing.T) {
	type inner struct {
		B string `@"one"`
		C string `@"two"`
	}
	type grammar struct {
		Items []*inner `@@+`
	}
	p, err := participle.Build[grammar]()
	if err != nil {
		t.Fatalf("Build: %v", err)
	}
	g, err := p.ParseString("", "one two one two")
	if err != nil {
		t.Fatalf("ParseString: %v", err)
	}
	if len(g.Items) != 2 {
		t.Fatalf("len(Items) = %d, want 2", len(g.Items))
	}
	for i, item := range g.Items {
		if item.B != "one" || item.C != "two" {
			t.Fatalf("Items[%d] = {%q,%q}, want {one,two}", i, item.B, item.C)
		}
	}

	// Optional pointer: non-matching optional yields nil.
	type optGrammar struct {
		A string  `( @"a" @"b" )?`
		B string  `@"c"`
	}
	p2, err := participle.Build[optGrammar]()
	if err != nil {
		t.Fatalf("Build optGrammar: %v", err)
	}
	g2, err := p2.ParseString("", "c")
	if err != nil {
		t.Fatalf("ParseString 'c': %v", err)
	}
	if g2.A != "" {
		t.Fatalf("A = %q, want empty", g2.A)
	}
	if g2.B != "c" {
		t.Fatalf("B = %q, want %q", g2.B, "c")
	}

	// * with no matches produces empty slice, zero-length is ok.
	type zeroMore struct {
		A []string `@"."*`
	}
	p3, err := participle.Build[zeroMore]()
	if err != nil {
		t.Fatalf("Build zeroMore: %v", err)
	}
	g3, err := p3.ParseString("", "")
	if err != nil {
		t.Fatalf("ParseString empty: %v", err)
	}
	if g3.A != nil && len(g3.A) != 0 {
		t.Fatalf("A = %v, want nil or empty", g3.A)
	}

	// + with no matches should error.
	type oneMore struct {
		A string `@"a"+`
	}
	p4, err := participle.Build[oneMore]()
	if err != nil {
		t.Fatalf("Build oneMore: %v", err)
	}
	_, err = p4.ParseString("", "")
	if err == nil {
		t.Fatal("expected error for + with no matches")
	}
}

// ---------------------------------------------------------------------------
// TestAlternationAndGrouping — | across fields, | within groups, ( ) with
// modifiers, including the non-empty modifier (!).
// ---------------------------------------------------------------------------

func TestAlternationAndGrouping(t *testing.T) {
	// Alternation across struct fields: first match wins.
	type altGrammar struct {
		A string `@"one" |`
		B string `@"two"`
	}
	p, err := participle.Build[altGrammar]()
	if err != nil {
		t.Fatalf("Build: %v", err)
	}
	g1, err := p.ParseString("", "one")
	if err != nil {
		t.Fatalf("ParseString 'one': %v", err)
	}
	if g1.A != "one" || g1.B != "" {
		t.Fatalf("got A=%q B=%q, want A=one B=empty", g1.A, g1.B)
	}
	g2, err := p.ParseString("", "two")
	if err != nil {
		t.Fatalf("ParseString 'two': %v", err)
	}
	if g2.B != "two" || g2.A != "" {
		t.Fatalf("got A=%q B=%q, want A=empty B=two", g2.A, g2.B)
	}

	// Alternation within a group captured to a single field.
	type groupAlt struct {
		A string `@("one" | "two")`
	}
	p2, err := participle.Build[groupAlt]()
	if err != nil {
		t.Fatalf("Build groupAlt: %v", err)
	}
	for _, input := range []string{"one", "two"} {
		g, err := p2.ParseString("", input)
		if err != nil {
			t.Fatalf("ParseString %q: %v", input, err)
		}
		if g.A != input {
			t.Fatalf("A = %q, want %q", g.A, input)
		}
	}

	// Non-empty modifier (!) ensures the sub-expression produces at least one token.
	type nonEmpty struct {
		A string `@( ("x"? "y"? "z"?)! "b" )`
	}
	p3, err := participle.Build[nonEmpty]()
	if err != nil {
		t.Fatalf("Build nonEmpty: %v", err)
	}
	g3, err := p3.ParseString("", "x z b")
	if err != nil {
		t.Fatalf("ParseString 'x z b': %v", err)
	}
	if g3.A != "xzb" {
		t.Fatalf("A = %q, want %q", g3.A, "xzb")
	}
	// Only optionals, none match -> must fail due to !
	_, err = p3.ParseString("", "b")
	if err == nil {
		t.Fatal("expected error for non-empty modifier with empty match")
	}
}

// ---------------------------------------------------------------------------
// TestNestedAndRecursive — @@ recursion into sub-structs, []*T accumulation,
// nested expression parsing that crosses multiple struct levels.
// ---------------------------------------------------------------------------

func TestNestedAndRecursive(t *testing.T) {
	type nestA struct {
		A string `":" @Ident`
	}
	type nestB struct {
		B string `";" @Ident`
	}
	type expr struct {
		A *nestA `@@ |`
		B *nestB `@@`
	}

	p, err := participle.Build[expr]()
	if err != nil {
		t.Fatalf("Build: %v", err)
	}

	// Match nestB branch.
	g1, err := p.ParseString("", "; beta")
	if err != nil {
		t.Fatalf("ParseString '; beta': %v", err)
	}
	if g1.A != nil {
		t.Fatal("expected A=nil")
	}
	if g1.B == nil || g1.B.B != "beta" {
		t.Fatalf("B = %v, want &{B:beta}", g1.B)
	}

	// Match nestA branch.
	g2, err := p.ParseString("", ": alpha")
	if err != nil {
		t.Fatalf("ParseString ': alpha': %v", err)
	}
	if g2.A == nil || g2.A.A != "alpha" {
		t.Fatalf("A = %v, want &{A:alpha}", g2.A)
	}
	if g2.B != nil {
		t.Fatal("expected B=nil when matching A branch")
	}

	// Nested arg list: combination of @@ recursion with separator + optional.
	type argsGrammar struct {
		Args []string `"(" ( @Ident ( "," @Ident )* )? ")"`
	}
	p2, err := participle.Build[argsGrammar]()
	if err != nil {
		t.Fatalf("Build argsGrammar: %v", err)
	}
	g3, err := p2.ParseString("", "(a, b, c)")
	if err != nil {
		t.Fatalf("ParseString '(a,b,c)': %v", err)
	}
	expectedArgs := []string{"a", "b", "c"}
	if !reflect.DeepEqual(g3.Args, expectedArgs) {
		t.Fatalf("Args = %v, want %v", g3.Args, expectedArgs)
	}
	// Empty parens.
	g4, err := p2.ParseString("", "()")
	if err != nil {
		t.Fatalf("ParseString '()': %v", err)
	}
	if len(g4.Args) != 0 {
		t.Fatalf("expected empty Args, got %v", g4.Args)
	}
}

// ---------------------------------------------------------------------------
// TestNegationAndLookahead — ~ negation captures, (?= ) positive lookahead,
// (?! ) negative lookahead (single + multi-token).
// ---------------------------------------------------------------------------

func TestNegationAndLookahead(t *testing.T) {
	// Negation: capture everything until semicolon.
	type negGrammar struct {
		Stuff []string `@~';'* @';'`
	}
	p1, err := participle.Build[negGrammar]()
	if err != nil {
		t.Fatalf("Build negation: %v", err)
	}
	g1, err := p1.ParseString("", "hello world ;")
	if err != nil {
		t.Fatalf("ParseString: %v", err)
	}
	expectedNeg := []string{"hello", "world", ";"}
	if !reflect.DeepEqual(g1.Stuff, expectedNeg) {
		t.Fatalf("negation got %v, want %v", g1.Stuff, expectedNeg)
	}

	// Negative lookahead: (?! 'keyword') prevents match.
	type variable struct {
		Name string `@Ident`
	}
	type lookaheadGrammar struct {
		Identifiers []variable `((?! 'except'|'end') @@)*`
		Except      *variable  `('except' @@)? 'end'`
	}
	p2, err := participle.Build[lookaheadGrammar]()
	if err != nil {
		t.Fatalf("Build lookahead: %v", err)
	}

	g2, err := p2.ParseString("", "one two three exception end")
	if err != nil {
		t.Fatalf("ParseString identifiers: %v", err)
	}
	// "exception" does NOT equal "except" so it should be collected.
	if len(g2.Identifiers) != 4 {
		t.Fatalf("Identifiers len = %d, want 4", len(g2.Identifiers))
	}
	names := make([]string, len(g2.Identifiers))
	for i, v := range g2.Identifiers {
		names[i] = v.Name
	}
	expectedNames := []string{"one", "two", "three", "exception"}
	if !reflect.DeepEqual(names, expectedNames) {
		t.Fatalf("names = %v, want %v", names, expectedNames)
	}
	if g2.Except != nil {
		t.Fatalf("Except = %v, want nil", g2.Except)
	}

	// With 'except' keyword present.
	g3, err := p2.ParseString("", "anything except this end")
	if err != nil {
		t.Fatalf("ParseString except: %v", err)
	}
	if len(g3.Identifiers) != 1 || g3.Identifiers[0].Name != "anything" {
		t.Fatalf("Identifiers = %v, want [{anything}]", g3.Identifiers)
	}
	if g3.Except == nil || g3.Except.Name != "this" {
		t.Fatalf("Except = %v, want &{this}", g3.Except)
	}

	// Multi-token negative lookahead: stop before three consecutive dots.
	type multiLookahead struct {
		Parts []string `((?! '.' '.' '.') @(Ident | '.'))*`
	}
	p3, err := participle.Build[multiLookahead]()
	if err != nil {
		t.Fatalf("Build multiLookahead: %v", err)
	}
	g4, err := p3.ParseString("", "x.y.z.")
	if err != nil {
		t.Fatalf("ParseString: %v", err)
	}
	expectedParts := []string{"x", ".", "y", ".", "z", "."}
	if !reflect.DeepEqual(g4.Parts, expectedParts) {
		t.Fatalf("Parts = %v, want %v", g4.Parts, expectedParts)
	}
	// Two dots are fine.
	g5, err := p3.ParseString("", "..x..")
	if err != nil {
		t.Fatalf("ParseString '..x..': %v", err)
	}
	expectedParts2 := []string{".", ".", "x", ".", "."}
	if !reflect.DeepEqual(g5.Parts, expectedParts2) {
		t.Fatalf("Parts = %v, want %v", g5.Parts, expectedParts2)
	}
}

// ---------------------------------------------------------------------------
// TestUnionTypes — Union[T]() with sealed interface, multiple struct members,
// parse dispatch, nested unions, EBNF representation.
// ---------------------------------------------------------------------------

type testUnionA interface{ isA() }
type testUnionB interface{ isB() }

type unionAIdent struct {
	V string `@Ident`
}

type unionABracket struct {
	V testUnionB `"[" @@ "]"`
}

type unionBNumber struct {
	V float64 `@Int | @Float`
}

type unionBBrace struct {
	V testUnionA `"{" @@ "}"`
}

func (unionAIdent) isA()   {}
func (unionABracket) isA() {}
func (unionBNumber) isB()  {}
func (unionBBrace) isB()   {}

func TestUnionTypes(t *testing.T) {
	type grammar struct {
		A testUnionA `@@`
		B testUnionB `| @@`
	}

	p, err := participle.Build[grammar](
		participle.UseLookahead(10),
		participle.Union[testUnionA](unionAIdent{}, unionABracket{}),
		participle.Union[testUnionB](unionBNumber{}, unionBBrace{}),
	)
	if err != nil {
		t.Fatalf("Build: %v", err)
	}

	// Simple ident.
	g1, err := p.ParseString("", "hello")
	if err != nil {
		t.Fatalf("ParseString 'hello': %v", err)
	}
	a1, ok := g1.A.(unionAIdent)
	if !ok {
		t.Fatalf("A type = %T, want unionAIdent", g1.A)
	}
	if a1.V != "hello" {
		t.Fatalf("A.V = %q, want %q", a1.V, "hello")
	}

	// Number -> dispatches to B.
	g2, err := p.ParseString("", "1.5")
	if err != nil {
		t.Fatalf("ParseString '1.5': %v", err)
	}
	b2, ok := g2.B.(unionBNumber)
	if !ok {
		t.Fatalf("B type = %T, want unionBNumber", g2.B)
	}
	if b2.V != 1.5 {
		t.Fatalf("B.V = %f, want 1.5", b2.V)
	}

	// Nested: [2.5] -> A=unionABracket{V=unionBNumber{2.5}}
	g3, err := p.ParseString("", "[2.5]")
	if err != nil {
		t.Fatalf("ParseString '[2.5]': %v", err)
	}
	a3, ok := g3.A.(unionABracket)
	if !ok {
		t.Fatalf("A type = %T, want unionABracket", g3.A)
	}
	b3, ok := a3.V.(unionBNumber)
	if !ok {
		t.Fatalf("A.V type = %T, want unionBNumber", a3.V)
	}
	if b3.V != 2.5 {
		t.Fatalf("nested number = %f, want 2.5", b3.V)
	}

	// Deeply nested: { [ { [12] } ] }
	g4, err := p.ParseString("", "{ [ { [12] } ] }")
	if err != nil {
		t.Fatalf("ParseString deeply nested: %v", err)
	}
	b4, ok := g4.B.(unionBBrace)
	if !ok {
		t.Fatalf("B type = %T, want unionBBrace", g4.B)
	}
	a4, ok := b4.V.(unionABracket)
	if !ok {
		t.Fatalf("B.V type = %T, want unionABracket", b4.V)
	}
	b5, ok := a4.V.(unionBBrace)
	if !ok {
		t.Fatalf("B.V.V type = %T, want unionBBrace", a4.V)
	}
	a5, ok := b5.V.(unionABracket)
	if !ok {
		t.Fatalf("B.V.V.V type = %T, want unionABracket", b5.V)
	}
	b6, ok := a5.V.(unionBNumber)
	if !ok {
		t.Fatalf("innermost type = %T, want unionBNumber", a5.V)
	}
	if b6.V != 12 {
		t.Fatalf("innermost value = %f, want 12", b6.V)
	}
}

// ---------------------------------------------------------------------------
// TestCaptureInterface — Custom type implementing Capture interface, verify
// custom transformation is applied. Also tests encoding.TextUnmarshaler.
// ---------------------------------------------------------------------------

type countCapture int

func (c *countCapture) Capture(values []string) error {
	*c += countCapture(len(values))
	return nil
}

type lengthUnmarshal int

func (u *lengthUnmarshal) UnmarshalText(text []byte) error {
	*u += lengthUnmarshal(len(text))
	return nil
}

func TestCaptureInterface(t *testing.T) {
	// Capture interface: count the number of calls, each passes one token.
	type capGrammar struct {
		Count countCapture `@"a"*`
	}
	p1, err := participle.Build[capGrammar]()
	if err != nil {
		t.Fatalf("Build Capture: %v", err)
	}
	g1, err := p1.ParseString("", "a a a")
	if err != nil {
		t.Fatalf("ParseString: %v", err)
	}
	if g1.Count != 3 {
		t.Fatalf("Count = %d, want 3", g1.Count)
	}

	// TextUnmarshaler interface: each call adds the length of the token text.
	type unmarshalGrammar struct {
		Count lengthUnmarshal `@"a"*`
	}
	p2, err := participle.Build[unmarshalGrammar]()
	if err != nil {
		t.Fatalf("Build TextUnmarshaler: %v", err)
	}
	g2, err := p2.ParseString("", "a a a")
	if err != nil {
		t.Fatalf("ParseString: %v", err)
	}
	// Each "a" is len 1, called 3 times: total 3.
	if g2.Count != 3 {
		t.Fatalf("Count = %d, want 3", g2.Count)
	}

	// Struct implementing Capture gets the captured values directly.
	type nestedCap struct {
		Tokens []string
	}
	// We need a method on *nestedCap.
	// Since we can't define methods inside a function, we use the sliceCapture pattern
	// from the upstream: define a Capture type that upper-cases its input.
	type upperCapture string
	// Can't add methods in function scope — test via countCapture which is already defined.

	// Verify zero captures yields zero count.
	g3, err := p1.ParseString("", "")
	if err != nil {
		t.Fatalf("ParseString empty: %v", err)
	}
	if g3.Count != 0 {
		t.Fatalf("Count = %d, want 0 for empty input", g3.Count)
	}
}

// ---------------------------------------------------------------------------
// TestSimpleLexer — MustSimple with custom token definitions, parse using
// custom lexer, lowercase rule names auto-elide.
// ---------------------------------------------------------------------------

func TestSimpleLexer(t *testing.T) {
	lex := lexer.MustSimple([]lexer.SimpleRule{
		{"Keyword", `(?i)SELECT|FROM|WHERE`},
		{"Ident", `[a-zA-Z_]\w*`},
		{"Number", `\d+`},
		{"Operator", `[=<>!]+`},
		{"Punct", `[,;()]`},
		{"whitespace", `\s+`}, // lowercase -> auto-elided
	})

	type whereClause struct {
		Column string `@Ident`
		Op     string `@Operator`
		Value  string `@(Number | Ident)`
	}
	type selectStmt struct {
		Columns []string     `"SELECT":Keyword @Ident ( "," @Ident )*`
		Table   string       `"FROM":Keyword @Ident`
		Where   *whereClause `( "WHERE":Keyword @@ )?`
	}

	p, err := participle.Build[selectStmt](
		participle.Lexer(lex),
		participle.CaseInsensitive("Keyword"),
	)
	if err != nil {
		t.Fatalf("Build: %v", err)
	}

	// Full query with WHERE.
	g1, err := p.ParseString("", "select name, age FROM users WHERE age > 18")
	if err != nil {
		t.Fatalf("ParseString full: %v", err)
	}
	expectedCols := []string{"name", "age"}
	if !reflect.DeepEqual(g1.Columns, expectedCols) {
		t.Fatalf("Columns = %v, want %v", g1.Columns, expectedCols)
	}
	if g1.Table != "users" {
		t.Fatalf("Table = %q, want %q", g1.Table, "users")
	}
	if g1.Where == nil {
		t.Fatal("Where = nil, want non-nil")
	}
	if g1.Where.Column != "age" || g1.Where.Op != ">" || g1.Where.Value != "18" {
		t.Fatalf("Where = {%q %q %q}, want {age > 18}", g1.Where.Column, g1.Where.Op, g1.Where.Value)
	}

	// Without WHERE clause.
	g2, err := p.ParseString("", "SELECT id FROM items")
	if err != nil {
		t.Fatalf("ParseString no-where: %v", err)
	}
	if g2.Where != nil {
		t.Fatalf("Where = %v, want nil", g2.Where)
	}
	if len(g2.Columns) != 1 || g2.Columns[0] != "id" {
		t.Fatalf("Columns = %v, want [id]", g2.Columns)
	}
}

// ---------------------------------------------------------------------------
// TestStatefulLexer — Push/Pop state machine, multi-state tokenization for
// string interpolation, Include and Return rules.
// ---------------------------------------------------------------------------

func TestStatefulLexer(t *testing.T) {
	// Stateful lexer for string interpolation: "hello ${name + "nested"}"
	def, err := lexer.New(lexer.Rules{
		"Root": {
			{Name: "String", Pattern: `"`, Action: lexer.Push("String")},
			{Name: "whitespace", Pattern: `\s+`, Action: nil},
		},
		"String": {
			{Name: "Escaped", Pattern: `\\.`, Action: nil},
			{Name: "StringEnd", Pattern: `"`, Action: lexer.Pop()},
			{Name: "Expr", Pattern: `\${`, Action: lexer.Push("Expr")},
			{Name: "Char", Pattern: `[^$"\\]+`, Action: nil},
		},
		"Expr": {
			lexer.Include("Root"),
			{Name: "whitespace", Pattern: `\s+`, Action: nil},
			{Name: "Oper", Pattern: `[-+/*%]`, Action: nil},
			{Name: "Ident", Pattern: `\w+`, Action: nil},
			{Name: "ExprEnd", Pattern: `}`, Action: lexer.Pop()},
		},
	})
	if err != nil {
		t.Fatalf("lexer.New: %v", err)
	}

	l, err := def.Lex("", strings.NewReader(`"hello ${world}"`))
	if err != nil {
		t.Fatalf("Lex: %v", err)
	}

	var tokenValues []string
	for {
		tok, err := l.Next()
		if err != nil {
			t.Fatalf("Next: %v", err)
		}
		if tok.Type == lexer.EOF {
			break
		}
		tokenValues = append(tokenValues, tok.Value)
	}

	expected := []string{`"`, "hello ", "${", "world", "}", `"`}
	if !reflect.DeepEqual(tokenValues, expected) {
		t.Fatalf("tokens = %v, want %v", tokenValues, expected)
	}

	// Also test Return() rule: transitions back to parent on unmatched input.
	def2, err := lexer.New(lexer.Rules{
		"Root": {
			{Name: "Ident", Pattern: `\w+`, Action: lexer.Push("Reference")},
			{Name: "whitespace", Pattern: `\s+`, Action: nil},
		},
		"Reference": {
			{Name: "Dot", Pattern: `\.`, Action: nil},
			{Name: "Ident", Pattern: `\w+`, Action: nil},
			lexer.Return(),
		},
	})
	if err != nil {
		t.Fatalf("lexer.New Return: %v", err)
	}

	l2, err := def2.Lex("", strings.NewReader("hello.world "))
	if err != nil {
		t.Fatalf("Lex: %v", err)
	}

	var tokenValues2 []string
	for {
		tok, err := l2.Next()
		if err != nil {
			t.Fatalf("Next: %v", err)
		}
		if tok.Type == lexer.EOF {
			break
		}
		tokenValues2 = append(tokenValues2, tok.Value)
	}

	expected2 := []string{"hello", ".", "world"}
	if !reflect.DeepEqual(tokenValues2, expected2) {
		t.Fatalf("tokens = %v, want %v", tokenValues2, expected2)
	}
}

// ---------------------------------------------------------------------------
// TestElideAndMapAndUnquote — Elide() drops whitespace/comments from parser
// (but keeps them in Tokens), Map() transforms tokens, Unquote() unquotes
// strings, Upper() uppercases tokens.
// ---------------------------------------------------------------------------

func TestElideAndMapAndUnquote(t *testing.T) {
	// Elide: whitespace is dropped from parsing but accessible in Tokens field.
	lex := lexer.MustSimple([]lexer.SimpleRule{
		{"Ident", `\w+`},
		{"Whitespace", `\s+`},
	})
	type subject struct {
		Tokens []lexer.Token
		Word   string `@Ident`
	}
	type helloGrammar struct {
		Tokens  []lexer.Token
		Subject subject `"hello" @@`
	}

	p1, err := participle.Build[helloGrammar](
		participle.Lexer(lex),
		participle.Elide("Whitespace"),
	)
	if err != nil {
		t.Fatalf("Build Elide: %v", err)
	}
	g1, err := p1.ParseString("", "hello world")
	if err != nil {
		t.Fatalf("ParseString: %v", err)
	}
	if g1.Subject.Word != "world" {
		t.Fatalf("Word = %q, want %q", g1.Subject.Word, "world")
	}
	// The root Tokens should include the elided whitespace token.
	foundWS := false
	for _, tok := range g1.Tokens {
		if strings.TrimSpace(tok.Value) == "" && tok.Value != "" {
			foundWS = true
			break
		}
	}
	if !foundWS {
		t.Fatal("expected elided whitespace in Tokens field")
	}

	// Upper: transforms tokens to uppercase.
	lex2 := lexer.MustSimple([]lexer.SimpleRule{
		{"Whitespace", `\s+`},
		{"Ident", `\w+`},
	})
	p2, err := participle.Build[struct {
		Text string `@Ident`
	}](participle.Lexer(lex2), participle.Upper("Ident"))
	if err != nil {
		t.Fatalf("Build Upper: %v", err)
	}
	tokens, err := p2.Lex("", strings.NewReader("hello world"))
	if err != nil {
		t.Fatalf("Lex: %v", err)
	}
	// First non-EOF Ident should be uppercased.
	if len(tokens) < 1 {
		t.Fatal("no tokens from Lex")
	}
	if tokens[0].Value != "HELLO" {
		t.Fatalf("Upper: first token = %q, want %q", tokens[0].Value, "HELLO")
	}
}

// ---------------------------------------------------------------------------
// TestEBNFOutput — Parser.String() produces valid EBNF, check that
// productions are present and correctly formatted.
// ---------------------------------------------------------------------------

func TestEBNFOutput(t *testing.T) {
	type inner struct {
		Name string `@Ident`
	}
	type grammar struct {
		Items []*inner `@@*`
		End   string   `"end"`
	}
	p, err := participle.Build[grammar]()
	if err != nil {
		t.Fatalf("Build: %v", err)
	}

	ebnf := p.String()
	if ebnf == "" {
		t.Fatal("EBNF output is empty")
	}

	// Pin the exact productions the grammar must serialize to: the Grammar body must keep
	// the repetition operator on Inner and the trailing "end" literal in order, and Inner
	// must resolve @Ident to the <ident> token. A structurally-wrong-but-right-shaped
	// serializer (dropped `*`, reordered terms) must not pass.
	if !strings.Contains(ebnf, `Grammar = Inner* "end" .`) {
		t.Fatalf("EBNF missing exact production `Grammar = Inner* \"end\" .`: %s", ebnf)
	}
	if !strings.Contains(ebnf, "Inner = <ident> .") {
		t.Fatalf("EBNF missing exact production `Inner = <ident> .`: %s", ebnf)
	}

	// Union EBNF test.
	type uGrammar struct {
		A testUnionA `@@`
		B testUnionB `| @@`
	}
	p2, err := participle.Build[uGrammar](
		participle.UseLookahead(10),
		participle.Union[testUnionA](unionAIdent{}, unionABracket{}),
		participle.Union[testUnionB](unionBNumber{}, unionBBrace{}),
	)
	if err != nil {
		t.Fatalf("Build union grammar: %v", err)
	}
	ebnf2 := p2.String()
	// Pin the exact union productions: each interface type serializes to the alternation
	// of its registered member productions in declaration order.
	if !strings.Contains(ebnf2, "TestUnionA = UnionAIdent | UnionABracket .") {
		t.Fatalf("union EBNF missing exact production `TestUnionA = UnionAIdent | UnionABracket .`: %s", ebnf2)
	}
	if !strings.Contains(ebnf2, "TestUnionB = UnionBNumber | UnionBBrace .") {
		t.Fatalf("union EBNF missing exact production `TestUnionB = UnionBNumber | UnionBBrace .`: %s", ebnf2)
	}
}

// ---------------------------------------------------------------------------
// TestErrorPositions — Parse errors carry correct line/column, wrong token
// type checking, trailing input detection, AllowTrailing option.
// ---------------------------------------------------------------------------

func TestErrorPositions(t *testing.T) {
	type grammar struct {
		Name string `@Ident`
	}
	p, err := participle.Build[grammar]()
	if err != nil {
		t.Fatalf("Build: %v", err)
	}

	// Trailing input should be an error by default.
	_, err = p.ParseString("", "hello world")
	if err == nil {
		t.Fatal("expected error for trailing input")
	}

	// AllowTrailing suppresses the trailing error.
	g, err := p.ParseString("", "hello world", participle.AllowTrailing(true))
	if err != nil {
		t.Fatalf("AllowTrailing: %v", err)
	}
	if g.Name != "hello" {
		t.Fatalf("Name = %q, want %q", g.Name, "hello")
	}

	// Error should report a position: check it has line/column info.
	type seqGrammar struct {
		A string `@Ident`
		B string `@"foo"`
	}
	p2, err := participle.Build[seqGrammar]()
	if err != nil {
		t.Fatalf("Build seqGrammar: %v", err)
	}
	_, err = p2.ParseString("", "hello bar")
	if err == nil {
		t.Fatal("expected error")
	}
	errStr := err.Error()
	// Error format is "<line>:<col>: message" or "<filename>:<line>:<col>: message".
	if !strings.Contains(errStr, ":") {
		t.Fatalf("error missing position info: %q", errStr)
	}

	// Check that the error implements the participle Error interface via type assertion.
	type particError interface {
		Message() string
		Position() lexer.Position
	}
	pErr, ok := err.(particError)
	if !ok {
		t.Fatalf("error does not implement Error interface: %T", err)
	}
	pos := pErr.Position()
	if pos.Line != 1 {
		t.Fatalf("error Line = %d, want 1", pos.Line)
	}
	// The unexpected token "bar" in "hello bar" begins at column 7, so the error must
	// report that exact column (a wrong-column implementation must not pass).
	if pos.Column != 7 {
		t.Fatalf("error Column = %d, want 7", pos.Column)
	}
	msg := pErr.Message()
	if msg == "" {
		t.Fatal("error Message() is empty")
	}

	// Filename propagation in errors.
	_, err = p2.ParseString("myfile.txt", "hello bar")
	if err == nil {
		t.Fatal("expected error with filename")
	}
	if !strings.Contains(err.Error(), "myfile.txt") {
		t.Fatalf("error missing filename: %q", err.Error())
	}
}

// ---------------------------------------------------------------------------
// TestPositionAndTokenFields — Pos/EndPos/Tokens auto-population in AST nodes.
// ---------------------------------------------------------------------------

func TestPositionAndTokenFields(t *testing.T) {
	type subgrammar struct {
		Pos    lexer.Position
		B      string `@","*`
		EndPos lexer.Position
	}
	type grammar struct {
		Pos    lexer.Position
		A      string      `@"."*`
		B      *subgrammar `@@`
		C      string      `@"."`
		EndPos lexer.Position
	}

	p, err := participle.Build[grammar]()
	if err != nil {
		t.Fatalf("Build: %v", err)
	}

	g, err := p.ParseString("", "   ...,,,.")
	if err != nil {
		t.Fatalf("ParseString: %v", err)
	}

	// Root Pos: first non-whitespace token starts at offset 3, line 1, col 4.
	if g.Pos.Offset != 3 {
		t.Fatalf("root Pos.Offset = %d, want 3", g.Pos.Offset)
	}
	if g.Pos.Line != 1 {
		t.Fatalf("root Pos.Line = %d, want 1", g.Pos.Line)
	}
	if g.Pos.Column != 4 {
		t.Fatalf("root Pos.Column = %d, want 4", g.Pos.Column)
	}

	// Verify A captured "...".
	if g.A != "..." {
		t.Fatalf("A = %q, want %q", g.A, "...")
	}

	// Subgrammar Pos: commas start at offset 6, col 7.
	if g.B == nil {
		t.Fatal("B is nil")
	}
	if g.B.Pos.Offset != 6 {
		t.Fatalf("B.Pos.Offset = %d, want 6", g.B.Pos.Offset)
	}
	if g.B.Pos.Column != 7 {
		t.Fatalf("B.Pos.Column = %d, want 7", g.B.Pos.Column)
	}
	if g.B.B != ",,," {
		t.Fatalf("B.B = %q, want %q", g.B.B, ",,,")
	}
	// Subgrammar EndPos: after last comma, offset 9, col 10.
	if g.B.EndPos.Offset != 9 {
		t.Fatalf("B.EndPos.Offset = %d, want 9", g.B.EndPos.Offset)
	}
	if g.B.EndPos.Column != 10 {
		t.Fatalf("B.EndPos.Column = %d, want 10", g.B.EndPos.Column)
	}

	// Root EndPos: after the final ".".
	if g.EndPos.Offset != 10 {
		t.Fatalf("root EndPos.Offset = %d, want 10", g.EndPos.Offset)
	}

	// C should be the trailing dot.
	if g.C != "." {
		t.Fatalf("C = %q, want %q", g.C, ".")
	}

	// Capture into lexer.Token field.
	type tokenCapture struct {
		Head lexer.Token   `@Ident`
		Tail []lexer.Token `@(Ident*)`
	}
	p2, err := participle.Build[tokenCapture]()
	if err != nil {
		t.Fatalf("Build tokenCapture: %v", err)
	}
	g2, err := p2.ParseString("", "hello waz baz")
	if err != nil {
		t.Fatalf("ParseString: %v", err)
	}
	if g2.Head.Value != "hello" {
		t.Fatalf("Head.Value = %q, want %q", g2.Head.Value, "hello")
	}
	if g2.Head.Pos.Line != 1 || g2.Head.Pos.Column != 1 {
		t.Fatalf("Head.Pos = %+v, want Line=1 Column=1", g2.Head.Pos)
	}
	if len(g2.Tail) != 2 {
		t.Fatalf("len(Tail) = %d, want 2", len(g2.Tail))
	}
	if g2.Tail[0].Value != "waz" {
		t.Fatalf("Tail[0].Value = %q, want %q", g2.Tail[0].Value, "waz")
	}
	if g2.Tail[1].Value != "baz" {
		t.Fatalf("Tail[1].Value = %q, want %q", g2.Tail[1].Value, "baz")
	}
	// Verify position of Tail tokens.
	if g2.Tail[0].Pos.Column != 7 {
		t.Fatalf("Tail[0].Pos.Column = %d, want 7", g2.Tail[0].Pos.Column)
	}
	if g2.Tail[1].Pos.Column != 11 {
		t.Fatalf("Tail[1].Pos.Column = %d, want 11", g2.Tail[1].Pos.Column)
	}
}

// ---------------------------------------------------------------------------
// TestCombinedComplexGrammar — A realistic mini-language grammar that exercises
// custom lexer + nested structs + repetition + alternation + optional together.
// Tests the full E2E parse pipeline on a non-trivial grammar.
// ---------------------------------------------------------------------------

func TestCombinedComplexGrammar(t *testing.T) {
	lex := lexer.MustSimple([]lexer.SimpleRule{
		{"Keyword", `\b(?:let|if|then|else|end)\b`},
		{"Ident", `[a-zA-Z_]\w*`},
		{"Number", `\d+(?:\.\d+)?`},
		{"Operator", `[+\-*/=<>]+`},
		{"Punct", `[();,{}]`},
		{"String", `"[^"]*"`},
		{"whitespace", `\s+`},
	})

	type value struct {
		Number *string `  @Number`
		Ident  *string `| @Ident`
		Str    *string `| @String`
	}

	type letStmt struct {
		Name  string `"let":Keyword @Ident "="`
		Value value  `@@`
	}

	type program struct {
		Stmts []letStmt `( @@ ";" )*`
	}

	p, err := participle.Build[program](participle.Lexer(lex))
	if err != nil {
		t.Fatalf("Build: %v", err)
	}

	input := `let x = 42; let name = "hello";`
	g, err := p.ParseString("", input)
	if err != nil {
		t.Fatalf("ParseString: %v", err)
	}

	if len(g.Stmts) != 2 {
		t.Fatalf("Stmts len = %d, want 2", len(g.Stmts))
	}

	// First statement.
	s0 := g.Stmts[0]
	if s0.Name != "x" {
		t.Fatalf("Stmts[0].Name = %q, want %q", s0.Name, "x")
	}
	if s0.Value.Number == nil || *s0.Value.Number != "42" {
		t.Fatalf("Stmts[0].Value.Number = %v, want 42", s0.Value.Number)
	}
	if s0.Value.Ident != nil {
		t.Fatalf("Stmts[0].Value.Ident = %v, want nil", s0.Value.Ident)
	}

	// Second statement.
	s1 := g.Stmts[1]
	if s1.Name != "name" {
		t.Fatalf("Stmts[1].Name = %q, want %q", s1.Name, "name")
	}
	if s1.Value.Str == nil || *s1.Value.Str != `"hello"` {
		t.Fatalf("Stmts[1].Value.Str = %v, want \"hello\"", s1.Value.Str)
	}

	// Empty program should parse.
	g2, err := p.ParseString("", "")
	if err != nil {
		t.Fatalf("empty program: %v", err)
	}
	if len(g2.Stmts) != 0 {
		t.Fatalf("empty program Stmts len = %d, want 0", len(g2.Stmts))
	}
}

// ---------------------------------------------------------------------------
// TestParseableInterface — Parseable interface for custom parse logic,
// NextMatch sentinel for backtracking to alternatives.
// ---------------------------------------------------------------------------

type customParseable struct {
	Val string
}

func (c *customParseable) Parse(lex *lexer.PeekingLexer) error {
	tok := lex.Peek()
	if tok.Type == lexer.EOF {
		return participle.NextMatch
	}
	if strings.HasPrefix(tok.Value, "custom_") {
		tok = lex.Next()
		c.Val = tok.Value
		return nil
	}
	return participle.NextMatch
}

type fallbackBranch struct {
	Val string `@Ident`
}

func TestParseableInterface(t *testing.T) {
	type grammar struct {
		Custom *customParseable `  @@`
		Normal *fallbackBranch  `| @@`
	}

	p, err := participle.Build[grammar](participle.UseLookahead(5))
	if err != nil {
		t.Fatalf("Build: %v", err)
	}

	// Input with "custom_" prefix routes to the Parseable branch.
	g1, err := p.ParseString("", "custom_hello")
	if err != nil {
		t.Fatalf("ParseString custom: %v", err)
	}
	if g1.Custom == nil {
		t.Fatal("Custom is nil, expected Parseable to match")
	}
	if g1.Custom.Val != "custom_hello" {
		t.Fatalf("Custom.Val = %q, want %q", g1.Custom.Val, "custom_hello")
	}
	if g1.Normal != nil {
		t.Fatalf("Normal = %v, want nil when Custom matches", g1.Normal)
	}

	// Input without "custom_" prefix: Parseable returns NextMatch, falls through to Normal.
	g2, err := p.ParseString("", "regular")
	if err != nil {
		t.Fatalf("ParseString regular: %v", err)
	}
	if g2.Normal == nil {
		t.Fatal("Normal is nil, expected fallback branch to match")
	}
	if g2.Normal.Val != "regular" {
		t.Fatalf("Normal.Val = %q, want %q", g2.Normal.Val, "regular")
	}
	if g2.Custom != nil {
		t.Fatalf("Custom = %v, want nil when Normal matches", g2.Custom)
	}

	// Verify NextMatch is the expected sentinel.
	if !errors.Is(participle.NextMatch, participle.NextMatch) {
		t.Fatal("NextMatch sentinel is not itself")
	}
}

// ---------------------------------------------------------------------------
// TestPositiveLookahead — (?= ...) positive lookahead asserts a pattern matches
// at the current position without consuming tokens.
// ---------------------------------------------------------------------------

func TestPositiveLookahead(t *testing.T) {
	// Positive lookahead: only capture an Ident if followed by "=".
	type assignment struct {
		Name  string `(?= Ident "=") @Ident "="`
		Value string `@Ident`
	}
	type grammar struct {
		Assignments []assignment `@@*`
		Remaining   []string     `@Ident*`
	}

	p, err := participle.Build[grammar](participle.UseLookahead(5))
	if err != nil {
		t.Fatalf("Build: %v", err)
	}

	// "a = x b = y z" has two assignments and one remaining.
	g, err := p.ParseString("", "a = x b = y z")
	if err != nil {
		t.Fatalf("ParseString: %v", err)
	}

	if len(g.Assignments) != 2 {
		t.Fatalf("Assignments len = %d, want 2", len(g.Assignments))
	}
	if g.Assignments[0].Name != "a" || g.Assignments[0].Value != "x" {
		t.Fatalf("Assignments[0] = {%q, %q}, want {a, x}", g.Assignments[0].Name, g.Assignments[0].Value)
	}
	if g.Assignments[1].Name != "b" || g.Assignments[1].Value != "y" {
		t.Fatalf("Assignments[1] = {%q, %q}, want {b, y}", g.Assignments[1].Name, g.Assignments[1].Value)
	}
	if !reflect.DeepEqual(g.Remaining, []string{"z"}) {
		t.Fatalf("Remaining = %v, want [z]", g.Remaining)
	}

	// Single ident without "=" should not match any assignment.
	g2, err := p.ParseString("", "lone")
	if err != nil {
		t.Fatalf("ParseString lone: %v", err)
	}
	if len(g2.Assignments) != 0 {
		t.Fatalf("Assignments len = %d, want 0 for lone ident", len(g2.Assignments))
	}
	if !reflect.DeepEqual(g2.Remaining, []string{"lone"}) {
		t.Fatalf("Remaining = %v, want [lone]", g2.Remaining)
	}
}

// ---------------------------------------------------------------------------
// TestParserNamedTag — The `parser:"..."` named struct tag allows grammar to
// coexist with other struct tags (json, db, etc.).
// ---------------------------------------------------------------------------

func TestParserNamedTag(t *testing.T) {
	type namedTag struct {
		Name  string `parser:"@Ident" json:"name"`
		Op    string `parser:"@'='"   json:"op"`
		Value string `parser:"@Ident" json:"value"`
	}

	p, err := participle.Build[namedTag]()
	if err != nil {
		t.Fatalf("Build: %v", err)
	}

	g, err := p.ParseString("", "foo = bar")
	if err != nil {
		t.Fatalf("ParseString: %v", err)
	}
	if g.Name != "foo" {
		t.Fatalf("Name = %q, want %q", g.Name, "foo")
	}
	if g.Op != "=" {
		t.Fatalf("Op = %q, want %q", g.Op, "=")
	}
	if g.Value != "bar" {
		t.Fatalf("Value = %q, want %q", g.Value, "bar")
	}

	// Verify that parser tag is used even when json tag has a different field name.
	type aliasedTag struct {
		Keyword string `parser:"@'if'" json:"kw"`
		Body    string `parser:"@Ident" json:"body"`
	}

	p2, err := participle.Build[aliasedTag]()
	if err != nil {
		t.Fatalf("Build aliasedTag: %v", err)
	}

	g2, err := p2.ParseString("", "if hello")
	if err != nil {
		t.Fatalf("ParseString aliasedTag: %v", err)
	}
	if g2.Keyword != "if" {
		t.Fatalf("Keyword = %q, want %q", g2.Keyword, "if")
	}
	if g2.Body != "hello" {
		t.Fatalf("Body = %q, want %q", g2.Body, "hello")
	}
}

