# pySMT -- Solver-Agnostic SMT Formula Library

Build the core formula-manipulation layer of pySMT: a pure-Python library for constructing, analyzing, simplifying, and serializing SMT (Satisfiability Modulo Theories) formulas. No solver backends, no CLI tools, no factory module, no configuration module. Zero runtime dependencies beyond the Python standard library.

## Installation

The package must be installable via `pip install -e .` using a `pyproject.toml` (or `setup.py`). Package name `PySMT`, importable as `pysmt`. Provide `pysmt/__init__.py` that exposes a `__version__` string derived from a `VERSION` tuple `(0, 9, 6)`.

**The environment is offline. All dependencies are already installed — do NOT install anything (there is no network).** pySMT has zero runtime dependencies beyond the Python standard library, and the build backend (`setuptools` + `wheel`) plus the test harness are pre-installed in the image. The project is installed for you by a `setup.sh` that runs offline (`pip install -e . --no-build-isolation`); you only need to author the package's `pyproject.toml`/`setup.py` and source so that editable install succeeds.

## 1. Package Layout

The package is importable as `pysmt` with subpackages `pysmt.walkers` and `pysmt.smtlib` (including `pysmt.smtlib.parser`).

## 2. Operators (`operators.py`)

Define 66 integer operator IDs, sequentially assigned starting at 0:

    FORALL=0, EXISTS=1, AND=2, OR=3, NOT=4, IMPLIES=5, IFF=6,
    SYMBOL=7, FUNCTION=8,
    REAL_CONSTANT=9, BOOL_CONSTANT=10, INT_CONSTANT=11, STR_CONSTANT=12,
    PLUS=13, MINUS=14, TIMES=15,
    LE=16, LT=17, EQUALS=18,
    ITE=19, TOREAL=20,
    BV_CONSTANT=21,
    BV_NOT=22, BV_AND=23, BV_OR=24, BV_XOR=25,
    BV_CONCAT=26, BV_EXTRACT=27,
    BV_ULT=28, BV_ULE=29,
    BV_NEG=30, BV_ADD=31, BV_SUB=32,
    BV_MUL=33, BV_UDIV=34, BV_UREM=35,
    BV_LSHL=36, BV_LSHR=37,
    BV_ROL=38, BV_ROR=39,
    BV_ZEXT=40, BV_SEXT=41,
    BV_SLT=42, BV_SLE=43,
    BV_COMP=44,
    BV_SDIV=45, BV_SREM=46, BV_ASHR=47,
    STR_LENGTH=48, STR_CONCAT=49, STR_CONTAINS=50, STR_INDEXOF=51,
    STR_REPLACE=52, STR_SUBSTR=53, STR_PREFIXOF=54, STR_SUFFIXOF=55,
    STR_TO_INT=56, INT_TO_STR=57, STR_CHARAT=58,
    ARRAY_SELECT=59, ARRAY_STORE=60, ARRAY_VALUE=61,
    DIV=62, POW=63, ALGEBRAIC_CONSTANT=64, BV_TONATURAL=65

`ALL_TYPES = list(range(0, 66))`

Classification frozensets:

- `QUANTIFIERS`: FORALL, EXISTS
- `BOOL_CONNECTIVES`: AND, OR, NOT, IMPLIES, IFF
- `BOOL_OPERATORS`: QUANTIFIERS | BOOL_CONNECTIVES
- `CONSTANTS`: BOOL_CONSTANT, REAL_CONSTANT, INT_CONSTANT, BV_CONSTANT, STR_CONSTANT, ALGEBRAIC_CONSTANT
- `BV_RELATIONS`: BV_ULE, BV_ULT, BV_SLT, BV_SLE
- `IRA_RELATIONS`: LE, LT
- `STR_RELATIONS`: STR_CONTAINS, STR_PREFIXOF, STR_SUFFIXOF
- `RELATIONS`: frozenset({EQUALS}) | BV_RELATIONS | IRA_RELATIONS | STR_RELATIONS
- `BV_OPERATORS`: BV_NOT, BV_AND, BV_OR, BV_XOR, BV_CONCAT, BV_EXTRACT, BV_NEG, BV_ADD, BV_SUB, BV_MUL, BV_UDIV, BV_UREM, BV_LSHL, BV_LSHR, BV_ROL, BV_ROR, BV_ZEXT, BV_SEXT, BV_COMP, BV_SDIV, BV_SREM, BV_ASHR
- `STR_OPERATORS`: STR_LENGTH, STR_CONCAT, STR_INDEXOF, STR_REPLACE, STR_SUBSTR, STR_CHARAT, STR_TO_INT, INT_TO_STR
- `IRA_OPERATORS`: PLUS, MINUS, TIMES, TOREAL, DIV, POW, BV_TONATURAL
- `ARRAY_OPERATORS`: ARRAY_SELECT, ARRAY_STORE, ARRAY_VALUE
- `THEORY_OPERATORS`: IRA_OPERATORS | BV_OPERATORS | ARRAY_OPERATORS | STR_OPERATORS

The union of BOOL_OPERATORS, THEORY_OPERATORS, RELATIONS, CONSTANTS, and {SYMBOL, FUNCTION, ITE} equals exactly ALL_TYPES, and these sets are pairwise disjoint (excluding SYMBOL/FUNCTION/ITE).

Provide `op_to_str(node_id)` returning the string name (e.g., `op_to_str(0)` returns `"FORALL"`), and `all_types()` returning an iterator over ALL_TYPES plus any CUSTOM_NODE_TYPES. Provide `new_node_type(node_id=None, node_str=None)` for extensibility. The `__OP_STR__` dict maps every operator ID to its string name.

## 3. Type System (`typing.py`)

Base class `PySMTType` with methods `is_bool_type()`, `is_real_type()`, `is_int_type()`, `is_bv_type(width=None)`, `is_array_type()`, `is_string_type()`, `is_function_type()`, `is_custom_type()`. Equality uses `basename` and `args`. Hashing uses `self.name`. Provide `as_smtlib(funstyle=True)` for SMT-LIB type rendering.

Singleton types created as private subclasses: `_BoolType`, `_IntType`, `_RealType`, `_StringType`. Module-level constants: `BOOL`, `INT`, `REAL`, `STRING`.

`_BVType(width)` represents bitvector types. Has a `width` property. Equality compares widths. `as_smtlib` produces `(_ BitVec <width>)`.

`_ArrayType(index_type, elem_type)` with `index_type` and `elem_type` properties.

`_FunctionType(return_type, param_types)` with `return_type` and `param_types` properties. `args` is `(return_type,) + param_types`. 0-arity function types collapse to the return type.

`_TypeDecl(name, arity)` for sort declarations (like SMT-LIB `declare-sort`).

`PartialType(name, definition)` for `define-sort` style aliases.

`TypeManager` class (instantiated per Environment) manages singleton BV types, function types, array types, and custom types via caching dicts. Methods: `BVType(width)`, `FunctionType(return_type, param_types)`, `ArrayType(index_type, elem_type)`, `Type(name, arity)`, `normalize(type_)`. It pre-loads global singletons for common widths (1, 8, 16, 32, 64, 128).

Module-level factory functions `BVType(width=32)`, `FunctionType(return_type, param_types)`, `ArrayType(index_type, elem_type)`, `Type(name, arity=0)` delegate to the global environment's TypeManager. These are importable from `pysmt.typing`.

## 4. FNode (`fnode.py`)

`FNodeContent = namedtuple("FNodeContent", ["node_type", "args", "payload"])` -- the structural identity of a formula node.

`FNode` class wraps an `FNodeContent` and a `node_id` (integer). Uses `__slots__ = ["_content", "_node_id"]`. `__hash__` returns `node_id`. Default `__eq__` is identity comparison. Created only through FormulaManager.

Accessors: `node_type()`, `args()`, `arg(idx)`, `node_id()`.

Type introspection follows the pattern `is_<lowercase_opname>()` for each operator type (e.g., `is_and()`, `is_symbol()`, `is_bv_add()`), plus category predicates: `is_constant()`, `is_literal()`, `is_quantifier()`, `is_term()`, `is_bool_op()`, `is_theory_relation()`, `is_theory_op()`, `is_ira_op()`, `is_bv_op()`, `is_array_op()`, `is_str_op()`. Also provide the boolean-constant convenience predicates `is_true()` and `is_false()`, which return `True` only when the node is the `TRUE()` / `FALSE()` boolean constant respectively (and `False` for any other node).

Value accessors: `symbol_name()`, `symbol_type()`, `constant_value()` (for BV constants returns the unsigned integer, not the tuple), `constant_type()`, `bv_width()`, `bv_extract_start()`, `bv_extract_end()`, `bv_rotation_step()`, `bv_extend_step()`, `bv_unsigned_value()`, `bv_signed_value()`, `bv_bin_str(reverse=False)`, `bv_str(fmt='b')`, `function_name()`, `quantifier_vars()`, `array_value_index_type()`, `array_value_default()`, `array_value_assigned_values_map()`, `array_value_get(index)`.

Convenience methods delegating to the global environment: `get_free_variables()`, `get_atoms()`, `simplify()`, `substitute(subs)`, `size(measure=None)`, `get_type()`, `serialize(threshold=None)`, `to_smtlib(daggify=True)`.

Infix operators (guarded by `enable_infix_notation` on the environment):
- `+` maps to Plus/BVAdd, `-` to Minus/BVSub, `*` to Times/BVMul, `/` to Div/BVUDiv
- `<`, `<=`, `>`, `>=` map to LT/LE/GT/GE or BVULT/BVULE/BVUGT/BVUGE
- `&` to And/BVAnd, `|` to Or/BVOr, `^` to Xor/BVXor
- `~` (invert) to Not/BVNot, unary `-` to Times(-1,...)/BVNeg
- `<<` to BVLShl, `>>` to BVLShr, `%` to BVURem
- `[idx]` and `[start:end]` to BVExtract
- `()` (call) on function-typed symbols to Function application
- Method-style: `.Implies()`, `.Iff()`, `.Equals()`, `.NotEquals()`, `.And()`, `.Or()`, `.Ite()`, and all BV methods.

## 5. FormulaManager (`formula.py`)

Central formula factory. Hash-conses formulas via `FNodeContent` as dictionary key. `create_node(node_type, args, payload=None)` creates or retrieves the memoized FNode. Each node gets a unique incrementing `node_id`. FormulaManager maintains a public `symbols` dict (attribute name `symbols`) mapping symbol name strings to their corresponding FNode objects, used for symbol lookup and membership checks.

Every constructor eagerly type-checks the node it creates against the environment's SimpleTypeChecker and raises `PysmtTypeError` immediately at call time (not only when `get_type()` is later invoked) whenever the operands are ill-typed, i.e. whenever they violate the typing rules of Section 12. A well-typed constructor call returns the node; an ill-typed one raises before the node is handed back.

Constructors:

**Boolean**: `Symbol(name, typename=BOOL)`, `FreshSymbol(typename=BOOL, template=None)`, `TRUE()`, `FALSE()`, `Bool(value)`, `And(*args)`, `Or(*args)`, `Not(formula)`, `Implies(left, right)`, `Iff(left, right)`, `Xor(left, right)`.

Polymorphic args: `And`, `Or`, `Plus`, `Times` accept both `f(a, b, c)` and `f([a, b, c])` -- a single iterable of the operands is treated identically to passing them as separate arguments.

Empty-arg behavior: `And()` returns TRUE, `Or()` returns FALSE, single-arg And/Or returns the argument itself.

**Operator rewrites during construction** (no separate operator IDs exist for these):
- `GE(a,b)` becomes `LE(b,a)` (args swapped)
- `GT(a,b)` becomes `LT(b,a)` (args swapped)
- `NotEquals(a,b)` becomes `Not(Equals(a,b))`
- `Xor(a,b)` becomes `Not(Iff(a,b))`
- `Not(Not(x))` collapses to `x` during construction
- `BVUGE(a,b)` becomes `BV_ULE(b,a)`, `BVUGT(a,b)` becomes `BV_ULT(b,a)`
- `BVSGE(a,b)` becomes `BV_SLE(b,a)`, `BVSGT(a,b)` becomes `BV_SLT(b,a)`
- `BVNand(a,b)` becomes `BVNot(BVAnd(a,b))`, `BVNor(a,b)` becomes `BVNot(BVOr(a,b))`, `BVXnor(a,b)` becomes `BVNot(BVXor(a,b))`

**Arithmetic**: `Int(value)`, `Real(value)`, `Plus(*args)`, `Minus(left, right)`, `Times(*args)`, `Div(left, right)`, `Pow(base, exponent)`, `Equals(left, right)`, `LE(left, right)`, `LT(left, right)`, `Ite(cond, then, else)`, `ToReal(formula)`.

For `Div`: if the right operand is a real constant, rewrite as `Times(left, Real(1/right))`.

For `Pow`: if the base is a constant, evaluate immediately.

For `ForAll`/`Exists`: if variables list is empty, return the body formula unchanged. The variables are stored as payload (tuple), body as single arg.

**Bitvector**: `BV(value, width)`, `SBV(value, width)`, `BVOne(width)`, `BVZero(width)`, `BVNot(f)`, `BVAnd(*args)`, `BVOr(*args)`, `BVXor(l,r)`, `BVConcat(*args)`, `BVExtract(f, start=0, end=None)`, `BVULT(l,r)`, `BVULE(l,r)`, `BVNeg(f)`, `BVAdd(*args)`, `BVSub(l,r)`, `BVMul(*args)`, `BVUDiv(l,r)`, `BVURem(l,r)`, `BVLShl(l,r)`, `BVLShr(l,r)`, `BVAShr(l,r)`, `BVRol(f, steps)`, `BVRor(f, steps)`, `BVZExt(f, increase)`, `BVSExt(f, increase)`, `BVSLT(l,r)`, `BVSLE(l,r)`, `BVComp(l,r)`, `BVSDiv(l,r)`, `BVSRem(l,r)`, `BVToNatural(f)`, `BVSMod(l,r)`, `BVRepeat(f, count)`.

`BV(value, width)` accepts integer values (0 to 2^width-1) or binary strings (e.g., `"101"` or `"#b101"`).

`SBV(value, width)` handles signed integers using 2's complement.

BV operations that accept integer shift/rotate amounts: `BVLShl`, `BVLShr`, `BVAShr` auto-convert Python int to BV constant of matching width.

Multi-arg BV ops (`BVAnd`, `BVOr`, `BVAdd`, `BVMul`, `BVConcat`) build left-associative binary trees.

BV operator payload conventions: most BV operators carry a payload tuple whose first element is the result width.

**String**: `String(value)`, `StrLength(f)`, `StrConcat(*args)`, `StrContains(s,t)`, `StrIndexOf(s,t,i)`, `StrReplace(s,t1,t2)`, `StrSubstr(s,i,j)`, `StrPrefixOf(s,t)`, `StrSuffixOf(s,t)`, `StrToInt(s)`, `IntToStr(x)`, `StrCharAt(s,i)`.

**Array**: `Select(arr, idx)`, `Store(arr, idx, val)`, `Array(idx_type, default, assigned_values=None)`.

**Combinators**: `AtMostOne(*args)` (quadratic encoding), `ExactlyOne(*args)`, `AllDifferent(*args)`, `EqualsOrIff(l,r)`, `Min(*args)`, `Max(*args)`.

`Function(vname, params)`: 0-arity application returns vname itself.

`normalize(formula)`: re-creates a formula built in another FormulaManager as an equivalent formula owned by this one, preserving its structure while producing this manager's own (distinct) FNode objects.

`__contains__(node)` checks membership by FNodeContent lookup.

## 6. Constants (`constants.py`)

Provides `Fraction` (from `fractions.Fraction` or optionally `gmpy2.mpq`) and `Integer` (int or optionally `gmpy2.mpz`). Predicate functions: `is_pysmt_fraction`, `is_pysmt_integer`, `is_python_integer`, `is_python_rational`, `is_python_boolean`, `is_python_string`, `pysmt_integer_from_integer`, `pysmt_fraction_from_rational`.

Uses environment variable `PYSMT_GMPY` to control whether GMPY2 is attempted. Default: use GMPY2 if available, else fall back to pure Python.

## 7. Walker Infrastructure (`walkers/`)

### `generic.py`

`handles` decorator class: registers the decorated function to handle one or more operator types, stored as a `nodetypes` attribute on the decorated function. It accepts **either** several operator IDs as separate positional arguments (e.g. `@handles(op.AND, op.OR)`) **or** a single collection/iterable of operator IDs (a list, set, or frozenset — e.g. `@handles(op.BV_OPERATORS)`, `@handles(set(op.ALL_TYPES) - op.BV_OPERATORS)`, or the catch-all `@handles(op.ALL_TYPES)`, since `ALL_TYPES` is a list); a lone iterable argument is unpacked into its element IDs.

`MetaNodeTypeHandler` metaclass: on class creation, inspects all methods for `nodetypes` attributes and calls `cls.set_handler(method, *nodetypes)`.

`Walker` base class (uses `MetaNodeTypeHandler` metaclass):
- `__init__(env=None)`: builds `self.functions` dict mapping each operator ID to the corresponding `walk_<opname>` method (looked up via `nt_to_fun(op_id)` which returns `"walk_<lowercase_opname>"`). Missing methods map to `walk_error`.
- `set_handler(cls, function, *node_types)`: class method, sets `walk_<opname>` on the class.
- `walk_error(self, formula, **kwargs)`: checks environment's `dwf` (dynamic walker functions) for fallback, otherwise raises `UnsupportedOperatorError`.
- `super(cls, self, formula, *args, **kwargs)`: classmethod that calls the correct `walk_*` function of `cls` for the given formula. Enables subclass overrides to call the parent class's handler for a specific operator.

`nt_to_fun(o)` returns `"walk_%s" % op.op_to_str(o).lower()`.

### `tree.py`

`TreeWalker(Walker)`: generator-based non-memoized traversal. `walk(formula, threshold=None)` drives the iteration: each `walk_*` method is a generator that yields child formulas to recurse into. If threshold is reached, `walk_threshold` is called instead.

### `dag.py`

`DagWalker(Walker)`: iterative, memoized DAG traversal. `walk(formula)` visits each structurally-distinct subformula exactly once and returns the handler result computed for the root: a node's handler is called only after its children have been walked, and the result computed for any shared (hash-consed) subformula is reused rather than recomputed, so a formula with N distinct nodes triggers exactly N handler invocations. By default the cache persists for the walker's lifetime; an optional `invalidate_memoization` construction flag clears the cache after each top-level `walk` completes.

**Handler calling contract.** When a `DagWalker` (or `IdentityDagWalker`) reaches a node, it invokes that node's `walk_<opname>` handler as `handler(formula, args=<child_results>, **kwargs)`, where `args` is the list of results already computed for the node's children (`formula.args()`), in child order. Custom handlers — including `@handles`-decorated ones — therefore have the signature `walk_<opname>(self, formula, args, **kwargs)` and read each child's result from `args` (not by re-walking children). To delegate to a parent class's handler, an override calls `.super` **on the parent class it wants to invoke**, passing only the walker instance and the formula plus the child-result `args`: `<ParentClass>.super(self, formula, args=..., **kwargs)` (the receiver class is `cls`; see Section 7 generic.py). This forwards the same `args` to that class's handler, so the override can compute the parent result and adjust it. The utility walk functions take the same `(self, formula, args, **kwargs)` shape (`walk_true`/`walk_false`/`walk_none` ignore `args`; `walk_any` returns `any(args)`, `walk_all` returns `all(args)`), except `walk_identity(self, formula, **kwargs)` which takes no `args`. `walk_error` and all `TreeWalker` handlers (which are generators that yield children) take `(self, formula, **kwargs)` with no `args`.

Utility walk functions: `walk_true`, `walk_false`, `walk_none`, `walk_identity`, `walk_any`, `walk_all`.

### `identitydag.py`

`IdentityDagWalker(DagWalker)`: reconstructs formulas through the FormulaManager. Has a `walk_*` method for every operator that rebuilds the node from walked children. Used as base class for Substituter, FormulaContextualizer, etc.

### `__init__.py`

Re-exports `DagWalker`, `TreeWalker`, `IdentityDagWalker`, and `handles`.

## 8. Environment (`environment.py`)

`Environment` class: singleton container wiring together:
- `formula_manager` (FormulaManager)
- `type_manager` (TypeManager)
- `stc` (SimpleTypeChecker)
- `simplifier` (Simplifier)
- `substituter` (MGSubstituter)
- `serializer` (HRSerializer)
- `qfo` (QuantifierOracle)
- `theoryo` (TheoryOracle)
- `fvo` (FreeVarsOracle)
- `sizeo` (SizeOracle)
- `ao` (AtomsOracle)
- `typeso` (TypesOracle)

Configuration flags: `enable_infix_notation` (default False), `enable_div_by_0` (default True), `allow_empty_var_names` (default False).

`dwf` dict for dynamic walker function registration: `add_dynamic_walker_function(nodetype, walker, function)`.

Context manager support: `__enter__` pushes env, `__exit__` pops.

Global stack: `ENVIRONMENTS_STACK` list. `get_env()` returns top. `push_env(env=None)` pushes (creates new if None). `pop_env()` pops. `reset_env()` pops + pushes fresh, returns new env.

A default environment is pushed at module import time.

## 9. Exceptions (`exceptions.py`)

Base: `PysmtException(Exception)`. Key subclasses: `PysmtTypeError(PysmtException, TypeError)`, `PysmtValueError(PysmtException, ValueError)`, `PysmtSyntaxError(PysmtException, SyntaxError)` with `pos_info` and `message`, `PysmtModeError`, `UnsupportedOperatorError(message, node_type, expression)`, `UndefinedSymbolError(name)`, `ConvertExpressionError(message, expression)`. Solver-related exceptions are not needed for the core formula layer.

## 10. Decorators (`decorators.py`)

`deprecated(alternative=None)`: emits DeprecationWarning.

`assert_infix_enabled`: raises `PysmtModeError` if `enable_infix_notation` is False.

`clear_pending_pop`, `catch_conversion_error`, `typecheck_result`.

## 11. Utilities (`utils.py`)

`set_bit(v, index, x)`: sets bit at position index to x, returns new value.

`twos_complement(val, bits)`: returns signed value from unsigned BV.

`quote(name, style='|')`: quotes a symbol name if needed (not a simple SMT-LIB symbol or is a keyword). Simple symbol regex: `^[~!@\$%\^&\*_\-+=<>\.\?\/A-Za-z][~!@\$%\^&\*_\-+=<>\.\?\/A-Za-z0-9]*$`. Keywords: `{"Int", "Real", "Bool"}`.

`all_assignments(bool_variables, env)`, `powerset(elements)`.

## 12. Type Checker (`type_checker.py`)

`SimpleTypeChecker(DagWalker)`: walks formulas to compute types. `get_type(formula)` returns the `PySMTType` or raises `PysmtTypeError` if ill-formed.

Rules: boolean connectives require BOOL args and return BOOL. Arithmetic ops (PLUS, MINUS, TIMES, DIV) accept either all-INT or all-REAL. TOREAL: INT->REAL. BV ops: all args must be same BV width, return same width. Relations (LE, LT): both args same numeric type, return BOOL. EQUALS: both args same type, return BOOL. BV relations: both args same BV width, return BOOL. ITE: condition BOOL, branches same type, returns that type. Symbols return their declared type. Constants return their intrinsic type. FUNCTION: return type from function symbol's declaration. ARRAY_SELECT: returns elem_type. ARRAY_STORE: returns same array type. ARRAY_VALUE: returns ArrayType(payload_idx_type, elem_type_of_default).

## 13. Simplifier (`simplifier.py`)

`Simplifier(DagWalker)` provides `simplify(formula)`.

The simplifier performs constant folding and algebraic simplification for all supported theories (Boolean, Arithmetic, BV, ITE, Quantifiers, String, Array). When all operands are constants, the operation is evaluated to produce a constant result. Identity elements are removed, absorbing elements short-circuit, and complementary/duplicate terms are handled. Symbols and constants are returned unchanged.

Constant folding follows the standard SMT-LIB semantics of each operator, including for the String and Array theories: an operation whose operands are all constants is evaluated to the constant that operator's standard semantics prescribes.

## 14. Substituter (`substituter.py`)

`Substituter(IdentityDagWalker)`: abstract base. `substitute(formula, subs, interpretations=None)` applies a dict mapping FNode->FNode.

`MGSubstituter` (Most General): checks if formula matches a substitution key before recursing. This is the default.

`MSSubstituter` (Most Specific): recurses first, then checks the rebuilt formula against the substitution map.

Both handle quantifiers by removing bound variables from the substitution map within the quantifier body.

`FunctionInterpretation(formal_params, function_body)`: represents a function interpretation for substitution. `interpret(env, actual_params)` substitutes formal parameters with actual values.

## 15. Rewritings (`rewritings.py`)

`NNFizer(DagWalker)`: converts formula to Negation Normal Form via its `convert(formula)` method (which returns the NNF formula; the module-level `nnf(formula)` convenience delegates to it). Pushes negations inward via De Morgan's laws. `Not(And(...))` -> `Or(Not(...))`, `Not(Or(...))` -> `And(Not(...))`. Rewrites Implies as `Or(Not(a), b)`. Rewrites Iff as `And(Or(Not(a),b), Or(Not(b),a))`. Quantifier duals: `Not(ForAll(v,f))` -> `Exists(v, Not(f))` and vice versa.

`CNFizer(DagWalker)`: Tseitin-style CNF conversion. `convert(formula)` returns a frozenset of frozensets of literals (clauses): the empty clause set (no clauses) denotes the always-true CNF and a clause set containing the empty clause denotes the always-false CNF. `convert_as_formula(formula)` returns the And of Or of those clauses. It introduces a fresh boolean variable for each compound subformula (so the converted formula's free-variable set is a strict superset of the input's), keeping the output size polynomial rather than exponential; the conversion is equisatisfiable over the original variables, not canonical.

`PrenexNormalizer(DagWalker)`: pulls quantifiers to the outermost position. `normalize(formula)` returns a formula in prenex normal form. Uses alpha-renaming (fresh symbols) to avoid variable capture when merging quantifier blocks from different branches.

`AIGer(DagWalker)`: converts to And-Inverter Graph (only And and Not as connectives). `Or(args)` -> `Not(And(Not(a) for a in args))`. `Implies(a,b)` -> `Not(And(a, Not(b)))`.

`TimesDistributor(IdentityDagWalker)`: distributes multiplication over addition.

Module-level convenience functions: `nnf(formula)`, `cnf(formula)`, `cnf_as_set(formula)`, `prenex_normal_form(formula)`, `aig(formula)`, `conjunctive_partition(formula)`, `disjunctive_partition(formula)`.

## 16. Oracles (`oracles.py`)

`SizeOracle(DagWalker)`: `get_size(formula, measure=None)`. Measures: MEASURE_TREE_NODES (default, counts tree nodes), MEASURE_DAG_NODES, MEASURE_LEAVES, MEASURE_DEPTH, MEASURE_SYMBOLS, MEASURE_BOOL_DAG. DAG/SYMBOLS/BOOL_DAG measures return frozenset sizes; TREE_NODES/LEAVES/DEPTH return integers.

`QuantifierOracle(DagWalker)`: `is_qf(formula)` returns True if quantifier-free.

`TheoryOracle(DagWalker)`: `get_theory(formula)` returns a Theory object describing which theories are used. Detects arithmetic linearity, difference logic, LIRA, arrays, bitvectors, strings, uninterpreted functions.

Difference-logic detection contract (the observable rule, not the walk): an integer/real arithmetic formula stays in the *difference* fragment (its Theory keeps `integer_difference`/`real_difference` set, so `get_logic` reports `QF_IDL`/`QF_RDL`) only while every arithmetic atom is a bare variable/constant or a **difference of two terms compared to a constant** — the shape `x - y <cmp> c` or `x <cmp> c` with unit coefficients, i.e. built with `Minus` (a subtraction), constants, and comparisons. As soon as the arithmetic contains a `Plus` of two non-constant terms or a `Times` with a non-unit/variable coefficient, the formula leaves the difference fragment and is plain **linear** arithmetic (`integer_difference`/`real_difference` cleared, so `get_logic` reports `QF_LIA`/`QF_LRA`). (`Theory.combine` intersects the difference flag across children, so a difference-logic subterm combined with a non-difference one yields non-difference.)

`FreeVarsOracle(DagWalker)`: `get_free_variables(formula)` returns frozenset of free Symbol FNodes. Quantifier-bound variables are excluded. Function application includes the function name symbol.

`AtomsOracle(DagWalker)`: `get_atoms(formula)` returns frozenset of boolean atoms (boolean symbols and theory relations). Theory operators return None (not atoms).

`TypesOracle(DagWalker)`: `get_types(formula, custom_only=False)` returns list of types appearing in the formula.

`get_logic(formula, env=None)`: determines the logic of a formula by combining QuantifierOracle and TheoryOracle results, returns closest pySMT-supported Logic. Difference logic is a strict fragment of the corresponding linear logic (`QF_IDL <= QF_LIA`, `QF_RDL <= QF_LRA`), so when a formula's arithmetic is entirely within the difference fragment `get_logic` returns the tighter difference logic; only a formula whose difference flag has been cleared (per the rule above) falls back to the linear logic.

## 17. Logics (`logics.py`)

`Theory` class with boolean attributes: `arrays`, `arrays_const`, `bit_vectors`, `floating_point`, `integer_arithmetic`, `real_arithmetic`, `integer_difference`, `real_difference`, `linear` (default True), `uninterpreted`, `custom_type`, `strings`. Methods: `copy()`, `combine(other)`, `set_lira()`, `set_linear(value)`, `set_difference_logic(value)`, `set_arrays()`, `set_arrays_const()`, `set_strings()`. Supports `==`, `!=`, `<=`.

`Logic` class with `name`, `description`, `quantifier_free`, `theory`. Supports `==`, `!=`, `<`, `<=`, `>=`, `>`. `__hash__` uses name, and `str()`/`repr()` return the SMT-LIB name (e.g. `str(QF_LIA) == "QF_LIA"`).

Pre-defined logics follow standard SMT-LIB naming conventions. Key logics: `QF_BOOL`, `QF_LIA`, `QF_LRA`, `QF_LIRA`, `QF_BV`, `QF_IDL`, `QF_RDL`, `QF_UF`, and their quantified variants (without QF_ prefix). Combined logics: `QF_UFLIA`, `QF_UFLRA`, `QF_ALIA`, `QF_ABV`, `QF_AUFBV`, `QF_SLIA`, `QF_AUFBVLIRA`, etc. Non-linear variants use N prefix (e.g., `QF_NIA`, `QF_NRA`). An `AUTO` logic is provided for automatic detection.

Collections: `SMTLIB2_LOGICS`, `LOGICS`, `PYSMT_LOGICS`, `QF_LOGICS`, `PYSMT_QF_LOGICS`, `BV_LOGICS`, `ARRAYS_LOGICS`.

Extended logics are auto-generated: variants with `custom_type=True` (name suffix 't') and for array logics variants with `arrays_const=True` (name suffix '*').

Functions: `get_logic_by_name(name)`, `get_logic(**kwargs)`, `get_closer_pysmt_logic(target)`, `get_closer_smtlib_logic(target)`, `most_generic_logic(logics)`, `get_closer_logic(supported, logic)`.

## 18. Human-Readable Serialization (`printers.py`)

`HRPrinter(TreeWalker)`: writes to a stream. Operators rendered as infix: `&` for And, `|` for Or, `->` for Implies, `<->` for Iff, `+` for Plus, `-` for Minus, `*` for Times, `/` for Div, `^` for Pow, `=` for Equals, `<=` for LE, `<` for LT. Not: `(! x)`. BV constants: `value_width` (e.g., `42_8`). Real constants: `n/d` or `n.0`. Booleans: `True`/`False`. Symbols are quoted with `'` style when needed. Quantifiers: `(forall x, y . body)`. ITE: `(c ? t : e)`. BV extract: `x[start:end]`. Arrays: `a[i]` for select, `a[i := v]` for store.

`HRSerializer`: wraps HRPrinter, `serialize(formula, threshold=None)` returns string.

## 19. HR Parsing (`parsing.py`)

`HRParser(env=None)` returns a Pratt parser for the human-readable format. `parse(string)` is the convenience function.

Built on a `PrattParser` with `Lexer` (regex-based tokenizer) and `GrammarSymbol` tokens with `nud` (null denotation, prefix) and `led` (left denotation, infix) methods implementing operator precedence.

A bare identifier in the input is resolved against the active environment's already-declared symbols (the symbol must exist, so its declared type is known; an unknown name raises `UndefinedSymbolError`). The HR format renders an arithmetic and a bitvector operator with the **same** surface token (e.g. both `Plus` and `BVAdd` print as `+`, both `And` and `BVAnd` as `&`, both `Or` and `BVOr` as `|`), so the parser disambiguates such a polymorphic operator **by the type of its operands**: when the left operand is bitvector-typed it builds the bitvector constructor, otherwise the arithmetic/boolean one. This applies to `+` (Plus vs BVAdd), `-` (Minus vs BVSub), `*` (Times vs BVMul), `&` (And vs BVAnd), `|` (Or vs BVOr), and unary `~`/`-` (Not/Times(-1) vs BVNot/BVNeg). As a result, `parse(serialize(f)) == f` round-trips a bitvector formula **provided its symbols are already declared in the active environment** (so the parser can recover their bitvector type).

## 20. SMT-LIB Commands (`smtlib/commands.py`)

String constants for all SMT-LIB 2.0/2.5 commands: ASSERT, CHECK_SAT, DECLARE_FUN, DECLARE_CONST, DEFINE_FUN, SET_LOGIC, SET_OPTION, SET_INFO, PUSH, POP, GET_VALUE, GET_MODEL, EXIT, etc.

`SMT_LIB_2_0` and `SMT_LIB_2_5` lists of supported commands.

## 21. SMT-LIB Script (`smtlib/script.py`)

`SmtLibCommand(name, args)` namedtuple with `serialize(outstream, printer, daggify)` method. `args` is a list whose layout is fixed per command `name`. In particular, a `DECLARE_FUN` (and `DECLARE_CONST`) command carries a **single** element — the already-declared symbol FNode being declared: `SmtLibCommand(DECLARE_FUN, [symbol])` / `script.add(DECLARE_FUN, [symbol])`. `serialize` derives the printed name and sort from that symbol alone (`symbol_name()` and `symbol_type()`), rendering `(declare-fun <name> <type>)` — a plain (0-arity) symbol prints as `(declare-fun name () Type)`, a function-typed symbol as `(declare-fun name (<param sorts>) <return sort>)`. (An `ASSERT`/`CHECK_SAT` command's `args` is the asserted formula / empty, as elsewhere; `SET_LOGIC` carries the logic name.)

`SmtLibScript` class: ordered collection of SmtLibCommands. Methods: `add_command(cmd)`, `add(name, args)`, `serialize(outstream, daggify=True)`. Provides `get_strict_formula()`, which returns the conjunction of all asserted formulas, and `get_last_formula()`, which returns the conjunction of the asserted formulas at the current (last) assertion level; with no intervening `push`/`pop` both methods return the same conjunction over all assertions.

`smtlibscript_from_formula(formula)`: creates a script that declares all symbols, sets the logic, asserts the formula, and issues check-sat.

## 22. SMT-LIB Printers (`smtlib/printers.py`)

`SmtPrinter(TreeWalker)`: tree-based SMT-LIB 2.0 printer using standard SMT-LIB operator names. Indexed operators use `(_ op param)` syntax for extract, rotate, extend. BV constants use `#b` binary prefix. Quantifiers use `(forall ((var Type)) body)` syntax. Array values use nested store with `(as const ArrayType)`. Symbols quoted with `|` style when needed. Bool: `true`/`false`. Int negatives: `(- n)`. Real: `n.0` or `(/ n.0 d.0)`.

`SmtDagPrinter(DagWalker)`: DAG-based printer using `let` bindings for shared subformulas. Produces linear-size output.

`to_smtlib(formula, daggify=True)`: returns string. Uses SmtDagPrinter if daggify=True, SmtPrinter otherwise.

## 23. SMT-LIB Parser (`smtlib/parser/parser.py`)

`SmtLibParser(environment=None)`: parses SMT-LIB 2.0 format from streams or files.

Key methods:
- `get_script(stream)` returns an `SmtLibScript`
- `get_formula(stream)` returns the conjunction of assertions
- `get_command(tokens)` parses one SMT-LIB command

Supports: `declare-fun`, `declare-const`, `define-fun`, `declare-sort`, `define-sort`, `assert`, `check-sat`, `set-logic`, `set-info`, `set-option`, `push`, `pop`, `exit`, `get-value`, `get-model`, `get-assertions`, `get-info`, `get-option`, quantifiers (`forall`, `exists`), `let` bindings, `as const` for constant arrays, all standard sorts (Bool, Int, Real, `(_ BitVec n)`, Array, String), all standard operators.

BV literal formats: `#b01010` (binary), `#x1A` (hex), `(_ bvN W)` (decimal with width).

Module-level: `get_formula(stream)`, `get_formula_strict(stream)`, `get_formula_fname(fname)` (supports `.bz2` compressed files).

The parser uses a tokenizer (`Tokenizer` class) that handles S-expression tokenization with support for quoted symbols, string literals, and comments (`;`).

## 24. Shortcuts (`shortcuts.py`)

Module providing a flat convenience API. On import, sets `enable_infix_notation = True` on the global environment. Re-exports all FormulaManager constructors (Symbol, And, Or, Not, Plus, BV, etc.), all BV constructors, String constructors, Array constructors, analysis functions (`get_type`, `simplify`, `substitute`, `serialize`, `get_free_variables`, `get_atoms`, `get_formula_size`), SMT-LIB I/O (`read_smtlib`, `write_smtlib`, `to_smtlib`), environment functions (`get_env`, `reset_env`), and type constants (`INT`, `BOOL`, `REAL`, `BVType`, `FunctionType`, `ArrayType`, `Type`, `STRING`).

### Typical usage

The shortcuts module is the canonical entry point. A typical flow builds a formula, inspects/transforms it, renders it, and round-trips it through the SMT-LIB parser:

```python
from io import StringIO
from pysmt.shortcuts import Symbol, And, Or, TRUE, get_type, simplify, serialize, to_smtlib
from pysmt.typing import BOOL
from pysmt.smtlib.parser import SmtLibParser
import pysmt.smtlib.script as script_mod

x, y = Symbol("x", BOOL), Symbol("y", BOOL)
f = And(Or(x, y), TRUE())

get_type(f)                     # BOOL
g = simplify(f)                 # Or(x, y)  -- TRUE() is dropped by And
serialize(g)                    # human-readable: "(x | y)"
to_smtlib(g, daggify=False)     # SMT-LIB:        "(or x y)"

# Round-trip through SMT-LIB: serialize a script, then parse it back.
scr = script_mod.smtlibscript_from_formula(g)
buf = StringIO(); scr.serialize(buf)
parsed = SmtLibParser().get_script(StringIO(buf.getvalue())).get_strict_formula()
assert parsed == g
```

## 25. setup.sh

The environment is offline with the build backend pre-installed, so the project is installed in editable mode without build isolation:

```bash
pip install -e . --no-build-isolation
```
