# Build `claripy`: a symbolic-expression and constraint-reasoning engine

Implement a Python library called **claripy** — the abstract expression engine used
by the angr binary-analysis platform. claripy lets you build symbolic and concrete
expressions over bit-vectors, booleans, and floating-point values; evaluate concrete
expressions; simplify expressions algebraically; reason about ranges of values via
**Value-Set Analysis (strided intervals)**; and solve constraints with a backend SMT
solver.

## Dependencies

The environment is **offline** — there is no network, and you must **not** install anything.
Everything you need is already installed:

- `z3-solver` (the SMT solver backend) and `cachetools` are pre-installed and importable.
- The Python toolchain (build backend, test runner) is pre-installed.

Structure your project so it is importable as `claripy` and installable offline by a `setup.sh`
that runs `pip install -e . --no-build-isolation` (a `pyproject.toml` / `setup.py` is fine; the
build backend is pre-baked). The bulk of the library — the AST layer, the concrete backend, the
simplifier, and the entire VSA/strided-interval backend — is pure Python and does not depend on the
solver; only the solver frontend needs `z3-solver`.

This is a large library. The sections below specify the public surface and the
behavioral contracts the hidden tests assert; the algorithms and internal organization
are yours to design.

---

## 1. The AST model

Expressions are immutable AST nodes. The base type is `claripy.ast.Base`, with subtypes
`claripy.ast.BV` (bit-vectors), `claripy.ast.Bool`, and `claripy.ast.FP`. Every node
exposes:

- `.op` — a `str` naming the operation (e.g. `"BVV"`, `"BVS"`, `"__add__"`, `"Concat"`,
  `"Extract"`, `"If"`, `"And"`, `"ULT"`, `"SLT"`, `"LShR"`).
- `.args` — a tuple of the operands (child ASTs or primitives).
- `.length` / `.size()` / `len(node)` — the bit width for a `BV` (a `Bool` has
  `size() == 1`); `.length` is `None` for non-sized nodes.
- `.depth` — `1` for a leaf; otherwise `max(child.depth) + 1`.
- `.symbolic` (bool), `.variables` (frozenset of symbol names), `.is_leaf()`.

**Hash-consing.** ASTs are interned: building the same expression twice returns the
**same object** (`a is b`). Two `BVS` with the same explicit name collapse to one
object; symbols created without an explicit name are always distinct. This identity is
how simplification results are checked, so structurally-equal results must share one
object.

### Leaf builders

- `claripy.BVV(value, size)` — concrete bit-vector. `op == "BVV"`, `args == (masked, size)`
  where `value` is reduced modulo `2**size`; bytes are accepted and read big-endian
  (`BVV(b"AAAA") is BVV(0x41414141, 32)`). `BVV(bytes, size)` with a contradictory size
  raises `claripy.errors.ClaripyValueError`.
- `claripy.BVS(name, size, explicit_name=False)` — symbolic bit-vector. `op == "BVS"`,
  `args == (name, size)` (the resolved/generated-or-explicit name and the bit width),
  `symbolic`, `depth 1`, `variables == {generated_or_explicit_name}`.
- `claripy.BoolV(b)` — concrete bool (`op == "BoolV"`, `args == (b,)`, `size() == 1`).
  `claripy.BoolS(name)` — symbolic bool. `claripy.true()` / `claripy.false()`.
- `claripy.FPV(value, sort)` — concrete FP (`op == "FPV"`), with sorts
  `claripy.FSORT_FLOAT` / `claripy.FSORT_DOUBLE`; rounding modes under `claripy.fp.RM`
  (e.g. `claripy.fp.RM.RM_NearestTiesEven`, also `claripy.RM`).

### Operators and named operations (on `BV`)

- Python operators map to dunder op-names and **preserve width**, growing depth by one:
  `+ - * & | ^ ~ << >>` → `__add__/__sub__/__mul__/__and__/__or__/__xor__/__invert__/
  __lshift__/__rshift__` (here `-` is binary subtraction `__sub__`); raw `/` and `%` are
  integral (`__floordiv__`, `__mod__`). The Python **unary** minus on a BV is also supported,
  mapping to op `__neg__`: `-bv` is width-preserving and evaluates to the two's-complement
  negation modulo `2**bits` (`-x == (~x) + 1`), so concretely `-BVV(1, 8) == BVV(0xFF, 8)` and
  `-BVV(0, 8) == BVV(0, 8)`. Non-AST operands (int, str) coerce to a same-width concrete BV
  (str = big-endian bytes).
- **Comparison operators are UNSIGNED**: `< <= > >=` → `ULT/ULE/UGT/UGE`; with
  `== !=` → `__eq__/__ne__`. All comparisons return a 1-bit `Bool`. Named comparisons:
  unsigned `claripy.ULT/ULE/UGT/UGE`, signed `claripy.SLT/SLE/SGT/SGE`.
- Named BV ops: `claripy.LShR(bv, n)` (logical right shift), `claripy.RotateLeft`/
  `claripy.RotateRight`, `bv.SDiv(o)` / `bv.SMod(o)` (signed division/remainder; also
  `claripy.SDiv`/`SMod`).
- Width-changing: `claripy.Concat(*bvs)` (width = sum), `claripy.Extract(hi, lo, bv)`
  (width `hi+1-lo`, `args == (hi, lo, bv)`), `claripy.ZeroExt(n, bv)` /
  `claripy.SignExt(n, bv)` (width `bv.size()+n`, `args == (n, bv)`), `claripy.Reverse(bv)`
  (byte-swap, width preserved; also `bv.reversed`).
- Slicing: `bv[hi:lo] == Extract(hi, lo, bv)`; `bv[i] == Extract(i, i, bv)`; omitted
  endpoints default to MSB/0; negative indices wrap. Full-width and consecutive-range
  reconstructions collapse to the original (`bv[size-1:0] is bv`,
  `Concat(bv[31:8], bv[7:0]) is bv`, `Reverse(Reverse(bv)) is bv`).
- Chaining a commutative op (`+ * | ^ &`) **flattens** into a single n-ary node
  (`x+x+x+x` is one `__add__` with four args).
- The width/shift operations are also available as **methods** on a BV, in addition
  to the free functions: `bv.concat(*others)`, `bv.zero_extend(n)`, `bv.sign_extend(n)`,
  `bv.LShR(n)`, `bv.RotateLeft(n)`, `bv.RotateRight(n)`, `bv.SDiv(o)`, `bv.SMod(o)`, and
  the `bv.reversed` property.

### Booleans and `If`

`claripy.And(*bools)`, `claripy.Or(*bools)`, `claripy.Not(b)` (op `"And"/"Or"/"Not"`).
The Python bitwise-not operator on a `Bool` is logical negation: `~b` on a `Bool` yields
`Not(b)` (op `"Not"`), mirroring `claripy.Not(b)`.
`claripy.If(cond, t, f)` (op `"If"`, `args == (cond, t, f)`), coercing int/bool branches.
A raw Python `bool` (or `int`) passed as the **condition** is likewise coerced to a concrete
`BoolV`; a concrete condition then folds to the selected branch at construction time, so
`If(True, t, f) is t` and `If(False, t, f) is f`.

### Errors

`claripy.errors` provides `ClaripyOperationError`, `ClaripyValueError`,
`ClaripyTypeError`, `ClaripyZeroDivisionError`. Operating on mismatched-width
bit-vectors, or an `Extract` with `hi >= size` or `lo > hi`, raises
`ClaripyOperationError` (these structural checks are active by default).

---

## 2. Concrete evaluation backend

`claripy.backends.concrete` evaluates fully-concrete expressions:

- `backends.concrete.eval(expr, n)` → a tuple of concrete primitive value(s) (a
  fully-concrete expression has one solution: a 1-tuple).
- `backends.concrete.convert(expr)` → a backend value comparing equal to the expected
  primitive (BV by numeric value, Bool as a Python `bool`).

Contracts: BV arithmetic wraps modulo `2**bits`; `//` and `%` are **unsigned** while
`SDiv`/`SMod` are signed (round-toward-zero / C remainder); division by zero raises
`ClaripyZeroDivisionError`; `>>` is arithmetic (sign-filling) while `LShR` is logical
(zero-filling); `Concat`/`Extract`/`ZeroExt`/`SignExt`/`RotateLeft`/`RotateRight`/
`Reverse` produce the exact value and width; `And`/`Or`/`Not`/`If` behave logically;
unsigned vs signed comparisons differ on sign-straddling values (e.g. 8-bit `0xFF` is
`255` unsigned, `-1` signed). Concrete FP supports `claripy.fpAdd/fpSub/fpMul/fpDiv`
(with a rounding mode), `fpLT/fpGT/fpEQ`, and `fpToUBV(rm, fp, size)` (round-half-to-even).

For a fully-concrete division or modulo by zero (`//`, `%`, `SDiv`, `SMod`), the
`ClaripyZeroDivisionError` is raised **eagerly when the expression is constructed** — building
`claripy.BVV(1, 32) // claripy.BVV(0, 32)` (or the `%`, `SDiv`, `SMod` forms) raises immediately,
before any explicit `backends.concrete.eval`/`convert` call.

---

## 3. Simplification

claripy simplifies expressions **at construction time**: building an operation whose
simplified form is a canonical node returns that node (so `Concat(x, y)[hi:lo]` may
already be `x`). `claripy.simplify(expr)` additionally applies backend simplification,
and `claripy.is_true(b)` / `claripy.is_false(b)` test concrete booleans.

Required simplifications (results checked by structural identity):

- Boolean: `And(True, x) is x`, `And(False, x)` is false, `Or(False, x) is x`,
  `Or(True, x)` is true, `Not(Not(x)) is x`, `Not(x==y)` is `x!=y` (and vice-versa);
  `simplify(And(a, Not(a)))` is false, `simplify(Or(a, Not(a)))` is true.
- Equality: `x == x` is true, `x != x` is false; for a Bool `a`, `a == True` is `a` and
  `a == False` is `Not(a)`; `(expr - c1 == c2)` becomes `expr == (c1+c2)`.
- Arithmetic: `x+0`/`x-0` is `x`; `x-x` is the zero bit-vector; chained concrete
  add/sub folds (`10 + (a+10) is a+20`). (Note: `x*1` and `x*0` are **not** simplified.)
- Bitwise: `x&x`/`x|x` is `x`; `x & allones` is `x`; `x&0` and `x^x` are zero; `x|0`
  and `x^0` are `x`.
- Concat/Extract: extracting a Concat-aligned piece returns the operand; full-width
  extract returns the value; a spanning extract rebuilds the sub-Concat; nested extracts
  fold; extracting bits known to be zero yields zero.
- Reverse/Extract: a byte-aligned `Extract` nested between two `Reverse`s collapses to a
  single `Extract` on the underlying value over the mirrored byte range, leaving **no**
  `Reverse` node.
- `If`: a concrete condition selects its branch; identical branches fold; `Extract`
  distributes into both branches; inverting a boolean-flag `If` negates the condition
  (`~If(c, 1, 0)` is `If(Not(c), 1, 0)`); flag idioms like `1 ^ If(c,1,0) == 0` reduce to
  `c` and `If(c0,1,0) & If(c1,1,0)` reduces to `If(c0 & c1, 1, 0)`.
- Comparison conjunction: a redundant unsigned bound combined with a disequality on the
  same operand merges into the tighter strict comparison — `And(UGE(x,c), NE(x,c))`
  simplifies to `UGT(x,c)` (and symmetrically `And(ULE(x,c), NE(x,c))` to `ULT(x,c)`).

---

## 4. Value-Set Analysis: strided intervals

This is the heart of the library's range reasoning. A **strided interval** (SI)
represents an abstract bit-vector value as `<bits> stride[lower_bound, upper_bound]`:
the set `{lo, lo+stride, lo+2*stride, …, hi}` interpreted in a **signedness-agnostic,
wrap-around modular domain** of width `bits`. Bounds are stored **unsigned** (masked to
`bits`); when `lo == hi` the stride normalizes to `0` (a single integer); an interval
covering every value is the canonical **TOP** = `1[0, 2**bits-1]`; an empty interval is
**BOTTOM** (`is_empty`).

Public surface:

- `claripy.SI(name=None, bits=, lower_bound=, upper_bound=, stride=)` builds a
  strided-interval-backed BV; `claripy.ValueSet`/`claripy.VS(bits, region,
  region_base_addr, value)` builds a value-set.
- The VSA backend `claripy.backends.vsa`: `.convert(ast)` → the model
  (`StridedInterval` or `ValueSet`); `.eval(ast, n)` → `list[int]` (enumerated set);
  `.min(ast)` / `.max(ast)` → unsigned extrema; `.cardinality(ast)` (the number of concrete
  values in the interval's set), `.identical(a, b)`,
  `.is_true(b)`, and `.constraint_to_si(ast)` (returns `(sat, replacements)` like the
  Balancer). These accessors accept either an AST or a `StridedInterval` model directly
  (e.g. the strided interval returned by the `Balancer`).
  `constraint_to_si` also resolves the boolean-flag idiom and a standalone disequality on
  an SI, isolating **both** sides of the flag: for `If(cond, 1, 0) == 1` it isolates the
  branch where `cond` holds, and for `If(cond, 1, 0) != 1` it isolates the branch where
  `cond` fails. A disequality `x != c` on an SI narrows the interval by removing the single
  excluded value `c`; when `c` sits at an endpoint the bound advances by one stride (so the
  result stays a single SI).
- An SI-backed BV also exposes the combinators as **methods**: `bv.union(o)`,
  `bv.intersection(o)`, and `bv.widen(o)` (mirroring the `StridedInterval` model).
- `claripy.backends.vsa.convert(ast)` returns a model object (a strided interval or a
  value-set); on that returned object the observable members the contract fixes are
  `.eval(n)` (enumerate up to `n` concrete values of its set as a `list[int]`) and the
  boolean properties `.is_top` (the interval covers every value in the `bits`-wide domain)
  and `.is_empty` (the interval is BOTTOM). Build strided intervals only through the public
  `claripy.SI(...)` / `claripy.VS(...)` / `claripy.ValueSet(...)` factories, combine and
  inspect them through the `claripy.backends.vsa.*` accessors above and the `bv.union(o)` /
  `bv.intersection(o)` / `bv.widen(o)` methods, and compare results with
  `claripy.backends.vsa.identical`; the model class's internal name, constructor, and
  remaining methods and properties are an implementation detail you may design freely.

Behavioral contracts (implement the algorithms; representative results given):

- **Addition / subtraction** are wrap-aware; the result stride is the GCD of operand
  strides; if the combined cardinality exceeds the value space the result is TOP. E.g.
  `[1,7]+[2,6] = 1[3,13]`, `[1,7]+[-5,-1] = 1[12,6]`, `[1,7]-[2,6] = 1[11,5]`.
- **Multiplication** reasons per signed hemisphere; stride is `abs(stride*int)` (or GCD);
  overflow → TOP. E.g. `[1,3]*2 = 2[2,6]`.
- **Division** has distinct signed (`sdiv`) and unsigned (`udiv`) variants differing on
  sign-straddling operands; division by `{0}` is BOTTOM.
- **Bitwise** `& | ~` use bit-level (min/max-bit) reasoning exploiting known high bits;
  `~` flips to the signed complement.
- **Shifts**: `LShR` logical (zero-fill), `>>` arithmetic (sign-preserving), `<<`.
- **Union** is the smallest SI containing both operands (stride reduced to the GCD of
  element gaps, wrapping as needed); **intersection** is the exact overlap; **widening**
  keeps stable bounds and pushes an unstable bound to the stride-aligned representable
  extreme (`x.widen(empty) == x`, `empty.widen(y) == TOP`).
- **Comparisons** are three-valued (definite True/False for separated intervals);
  signed vs unsigned differ; `-1 == 0xff` (8-bit) is True.
- **Bounds**: `backends.vsa.max`/`backends.vsa.min` return the unsigned wrap-aware extrema
  of a strided interval (the largest/smallest value in its concrete set, each element
  interpreted unsigned over the `bits`-wide domain).
- **Extension/extraction**: `zero_extend` preserves bounds, `sign_extend` replicates the
  sign bit; byte extraction yields exact per-lane SIs.
- **ValueSet** maps regions → SIs and supports `.union(o)` and `.intersection(o)`:
  same-region offset union merges the SIs; intersecting disjoint singletons is empty;
  subtracting two same-region pointers collapses to a concrete SI offset.

---

## 5. Solver, balancer, and annotations

### Solver

`claripy.Solver()` is the default constraint solver: `.add(constraint)`,
`.satisfiable(extra_constraints=())`, `.eval(expr, n, extra_constraints=())` (up to `n`
solutions), `.min(x, signed=False)` / `.max(x, signed=False)`, `.batch_eval([exprs], n)`,
`.solution(expr, value)`, `.simplify()`, and `.constraints`. Contracts: after adding
equalities that uniquely pin a `BVS`, `satisfiable()` is True and `eval(expr, 1)[0]`
returns the expression's value; contradictory constraints (or adding `claripy.false()`)
make it unsatisfiable; `extra_constraints=` is a non-mutating what-if; for an
unconstrained 32-bit BV, unsigned `min/max` are `[0, 2**32-1]` and signed are
`[-0x80000000, 0x7fffffff]`; `simplify()` folds redundant/duplicate constraints but must
**not** drop a constraint carrying a `SimplificationAvoidanceAnnotation`. `batch_eval([exprs], n)`
returns up to `n` solution rows, where **each row is a tuple** holding one concrete value per
expression in the same order as the input list (a constant expression contributes its constant).
Adding a constraint that is structurally identical (same hash-consed AST) to one already present
is a no-op, so `.constraints` never holds duplicates of the same AST — independent of whether
`simplify()` has been called. Other solver variants exist (`SolverVSA`, etc.).

### Balancer

`claripy.backends.backend_vsa.Balancer(constraint).compat_ret` returns
`(sat: bool, replacements)` where each replacement is `(isolated_ast, strided_interval)`:
it isolates the symbolic sub-AST on one side of a comparison and computes the bounding
strided interval. E.g. `x <= 39` → interval min 0, max 39; `x + 1 <= 39` wraps;
`x0 + x1 + 1 < 99` isolates `(x0+x1)` with cardinality 99.

### Annotations

`claripy.Annotation` is the base; built-ins include
`claripy.SimplificationAvoidanceAnnotation` and
`claripy.annotation.StridedIntervalAnnotation`. Attach via `ast.annotate(*annos)`;
`.annotations` is an ordered tuple; `remove_annotation(anno)`, `remove_annotations(annos)`
(one iterable of annotations, e.g. a set), and `clear_annotations()` manage them immutably
(removing all annotations restores the original AST identity; annotating with an identical
set returns the same AST). Each annotation has `eliminatable` and `relocatable` properties
and a `relocate(src, dst)` hook governing simplification. A base `claripy.Annotation` is
eliminatable and non-relocatable by default (`eliminatable=True`, `relocatable=False`);
subclasses override these to block or relocate.
The three behaviors: an eliminatable annotation is dropped when its expression simplifies away
(e.g. `x ^ x`); a non-eliminatable, non-relocatable annotation blocks the simplification;
a relocatable one survives and has `relocate` invoked.

A relocatable annotation also **propagates from an operand up onto every newly-constructed
parent AST**, not only during simplification: building any op from an annotated child carries
that child's relocatable annotations onto the result, exactly once (no duplication). E.g.
`Concat(x.annotate(reloc), c)` yields a node whose `.annotations == (reloc,)`, and
`remove_annotation(reloc)` clears it.
