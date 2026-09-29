// =============================================================================
// Hidden grading suite for the "koto-mini" WRG task — a bounded subset of the koto
// language (koto-lang/koto v0.16.1, SHA 0de8f08762a8643215d7aa8eb7c89ceef4765117).
//
//   *** GT-VERIFIED against real koto. Narrowed from koto-lite (2026-07-18): the
//       full subset exceeded the WRG single-shot generation budget (~47k output
//       tokens → agent truncated at Step 0, 0%). koto-mini focuses on the highest-
//       value koto-specific discriminators so a correct impl fits one generation. ***
//
// SCOPE: the agent builds a SMALL from-scratch interpreter (tree-walk) for koto-mini.
// Grading is BLACK-BOX on script output via the public `koto` API. GROUND TRUTH is
// the REAL koto crate (a superset), so every test passes on GT by construction;
// discrimination is on the AGENT's interpreter. Difficulty = koto's tricky SEMANTICS
// (the @meta-map protocol incl. derived comparisons, capture-by-COPY closures, and
// reference-shared-vs-copied collection identity), plus exact quoted Display.
//
// IN scope: values (int/float/bool/null/string/list/tuple/map), arithmetic/comparison/
// logic ops, truthiness (only false/null falsy), bindings + compound assign, closures
// with capture-by-copy, `if/then/else`, indexing + range slicing, single-quoted string
// interpolation, the @meta-map protocol (@+ @- @* @== @< + derived, @index @size @call
// @type @display @meta), and koto.type / size.
// OUT: iterators/adaptors, ranges-as-iterables/reversed, match/switch, error handling,
// generators, modules, format specifiers, variadic.
//
// API binding (GT-verified): compile_and_run(impl Into<CompileArgs>) -> Result<KValue>;
// value_to_string(KValue) -> Result<String> (BY VALUE) renders via @display. Strings
// render QUOTED inside tuples/lists; @+= is NOT derived from @+ (explicit, returns self).
// One `#[test] fn` == one graded CTRF entry.
// =============================================================================

use koto::prelude::*;

fn run(script: &str) -> String {
    let mut koto = Koto::default();
    let result = koto
        .compile_and_run(script)
        .unwrap_or_else(|e| panic!("koto error running script:\n{script}\n---\n{e}"));
    koto.value_to_string(result)
        .unwrap_or_else(|e| panic!("value_to_string failed:\n{e}"))
}

// =============================================================================
// A. Meta-map protocol — the crown-jewel koto-specific discriminator.
// =============================================================================

#[test]
fn a01_meta_binary_ops() {
    // @+, @-, @* each dispatch to their own distinct meta key (differing only in the
    // metakey looked up), so one object defining all three verifies every route in a
    // single graded slot. Handlers return plain ints to keep the rendering unambiguous.
    let script = r#"
foo = |n|
  data: n
  @+: |other| self.data + other.data
  @-: |other| self.data - other.data
  @*: |other| self.data * other.data
(foo(10) + foo(4), foo(10) - foo(4), foo(10) * foo(4))
"#;
    assert_eq!(run(script), "(14, 6, 40)");
}

#[test]
fn a04_compound_assign() {
    // koto does NOT derive @+= from @+ — it must be defined explicitly and return self.
    let script = r#"
foo = |n|
  data: n
  @+=: |other|
    self.data += other
    self
  @call: || self.data
x = foo 10
x += 20
x()
"#;
    assert_eq!(run(script), "30");
}

#[test]
fn a05_derived_comparisons() {
    // Define only @< and @==; >, >=, <=, != must be derived automatically.
    let script = r#"
foo = |n|
  data: n
  @<: |other| self.data < other.data
  @==: |other| self.data == other.data
(foo(5) > foo(4), foo(5) >= foo(5), foo(5) != foo(6))
"#;
    assert_eq!(run(script), "(true, true, true)");
}

#[test]
fn a06_index_and_size() {
    let script = r#"
foo = |n|
  data: n
  @index: |i| i * 2
  @size: || self.data
(foo(10)[5], size foo(10))
"#;
    assert_eq!(run(script), "(10, 10)");
}

#[test]
fn a07_call() {
    let script = r#"
foo = |n|
  data: n
  @call: || self.data
foo(99)()
"#;
    assert_eq!(run(script), "99");
}

#[test]
fn a08_display() {
    let script = r#"
foo = |n|
  data: n
  @display: || 'Foo ({self.data})'
'{foo(-1)}'
"#;
    assert_eq!(run(script), "Foo (-1)");
}

#[test]
fn a09_type() {
    let script = r#"
foo = |n|
  data: n
  @type: 'Foo'
koto.type (foo 0)
"#;
    assert_eq!(run(script), "Foo");
}

#[test]
fn a10_meta_named_entry_accessible() {
    // @meta named entries are accessible as fields alongside normal keys.
    let script = r#"
f =
  x: 1
  @meta hello: 'Hello'
  @meta say_hello: |name| 'Hello, {name}!'
(f.hello, f.say_hello('you'), f.x)
"#;
    assert_eq!(run(script), "('Hello', 'Hello, you!', 1)");
}

#[test]
fn a11_eq_override_ignores_field() {
    let script = r#"
make = |x, y|
  x: x
  y: y
  @==: |other| self.x == other.x
make(1, 2) == make(1, 99)
"#;
    assert_eq!(run(script), "true");
}

#[test]
fn a12_meta_op_returns_object_and_chains() {
    // Distinct axis from a01 (int-returning dispatch) and a08 (@display via interpolation):
    // @+ returns a freshly-constructed same-type object, chaining re-dispatches @+ on that
    // returned object, and the top-level value renders through @display in value_to_string.
    let script = r#"
foo = |n|
  data: n
  @+: |other| foo self.data + other.data
  @display: || 'foo {self.data}'
foo(1) + foo(2) + foo(3)
"#;
    assert_eq!(run(script), "foo 6");
}

// =============================================================================
// C. Capture-by-COPY closures (distinctive: NOT capture-by-reference).
// =============================================================================

#[test]
fn c12_capture_is_copy_at_creation() {
    let script = r#"
x = 1
f = |n| n + x
x = 100
f 2
"#;
    assert_eq!(run(script), "3");
}

#[test]
fn c13_captured_scalar_reassignment_is_local() {
    let script = r#"
x = 99
f = ||
  x += 1
  x
(f(), f(), f())
"#;
    assert_eq!(run(script), "(100, 100, 100)");
}

#[test]
fn c14_mutable_container_capture_persists() {
    let script = r#"
data = {x: 99}
f = ||
  data.x += 1
  data.x
(f(), f(), f())
"#;
    assert_eq!(run(script), "(100, 101, 102)");
}

#[test]
fn c15_nested_closure_captures_own_copy() {
    let script = r#"
make_adder = |base| |n| n + base
add10 = make_adder 10
add100 = make_adder 100
(add10(1), add100(1))
"#;
    assert_eq!(run(script), "(11, 101)");
}

// =============================================================================
// D. List / Tuple / Map shared-vs-copied data semantics.
// =============================================================================

#[test]
fn d16_list_aliasing() {
    let script = r#"
x = [1, 2, 3]
y = x
y[0] = 99
x[0]
"#;
    assert_eq!(run(script), "99");
}

#[test]
fn d17_map_aliasing() {
    let script = r#"
a = {x: 1}
z = a
z.x = 9
a.x
"#;
    assert_eq!(run(script), "9");
}

#[test]
fn d18_list_slice_copies() {
    let script = r#"
a = [1, 2, 3]
b = a[0..2]
b[0] = 42
a[0]
"#;
    assert_eq!(run(script), "1");
}

#[test]
fn d19_tuple_holds_shared_inner_list() {
    let script = r#"
inner = [1, 2]
t = (inner, 3)
inner[0] = 9
t[0][0]
"#;
    assert_eq!(run(script), "9");
}

#[test]
fn d20_string_slice_shares() {
    assert_eq!(run(r#"'abcdef'[3..6]"#), "def");
}

// =============================================================================
// J. String interpolation (single-quoted '{expr}'): a bare variable AND an
//    arbitrary expression, with interleaved literal text in a single string.
// =============================================================================

#[test]
fn j21_interpolation() {
    let script = r#"
name = 'World'
a = 3
b = 4
'{name}: {a + b}!'
"#;
    assert_eq!(run(script), "World: 7!");
}

// =============================================================================
// K. Truthiness (koto-specific: only false/null falsy).
// =============================================================================

#[test]
fn k23_truthiness_only_false_and_null_falsy() {
    let script = r#"
t = |v| if v then 't' else 'f'
(t(0), t(''), t([]), t(false), t(null))
"#;
    assert_eq!(run(script), "('t', 't', 't', 'f', 'f')");
}

// =============================================================================
// H. Additional documented-feature coverage: logical operators, and a harder
//    meta-map compound-assign edge case.
// =============================================================================


#[test]
fn h25_logical_ops() {
    // `and`/`or`/`not` plus plain-number comparisons — documented operators that are
    // otherwise only exercised through meta-object overloads. Operands and results are
    // booleans, so the rendering is independent of any operand-return convention.
    let script = r#"
(true and false, false or true, not (1 == 2), (3 < 4) and (5 > 2))
"#;
    assert_eq!(run(script), "(false, true, true, true)");
}


#[test]
fn h27_compound_assign_via_map_field() {
    let script = r#"
foo = |n|
  data: n
  @+=: |o|
    self.data += o
    self
  @call: || self.data
m = {acc: foo(10)}
m.acc += 5
m.acc()
"#;
    assert_eq!(run(script), "15");
}


#[test]
fn h28_float_arithmetic_and_division() {
    // Floats are an in-scope value type otherwise untouched by the suite. `/` is true
    // division and ALWAYS yields a float (10 / 5 is 2.0, not the integer 2); whole
    // floats still render with a trailing `.0`.
    let script = r#"
(9 / 2, 10 / 5, 1.5 + 2.5)
"#;
    assert_eq!(run(script), "(4.5, 2.0, 4.0)");
}

