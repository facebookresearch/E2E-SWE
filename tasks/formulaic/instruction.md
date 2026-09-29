# Formulaic

Implement a Python library `formulaic` that compiles **Wilkinson formulas** (`y ~ x + z` DSL from R / statsmodels / patsy) into numeric model matrices over `pandas.DataFrame`. Categorical variables auto-encode into contrast columns; transforms (`log(x)`, `scale(x)`, `poly(x, 3)` etc.) evaluate in-line; encoding state (levels, training means, polynomial coefficients) is captured in a `ModelSpec` and can be reapplied to new data at prediction time.

## Dependencies

The environment is **offline** — there is no network access, and all dependencies are **already
installed**. Do **not** attempt to install anything (no `pip install`, no network calls); installs
will fail. The project is built and installed for you by a `setup.sh` that runs offline
(`pip install -e . --no-build-isolation` against the pre-installed packages).

The following runtime dependencies are pre-installed and available to import:

- `numpy` (>= 1.20), `pandas` (>= 1.3), `scipy` (>= 1.6), `wrapt`
- `interface-meta`, `narwhals`, `typing-extensions`

`sympy` is **not** installed, so `differentiate` must use the structural (no-sympy) fallback
described in §1.3.

## Public API

Importable from the top-level `formulaic` package:

```python
from formulaic import Formula, ModelSpec, model_matrix
```

Internal module layout is otherwise unconstrained.

---

## 1. `Formula`

`Formula(spec)` parses a spec into a formula object. The `spec` argument may be:
- A formula string (`"y ~ x + z"`).
- A list of term-string specifications (`["1", "x", "y:z"]`) — each entry is parsed as a single term, terms are combined into a single `SimpleFormula`.

Two Formulas constructed from equivalent specs compare equal via `==` (equality is by term content, not identity).

### 1.1 Materialization (`~` operator)

`.get_model_matrix(data)` produces the model matrix (or matrices) against a DataFrame.

- **Two-sided** (`"y ~ x + z"`): returns a pair (iterable of two elements) — LHS (response) and RHS (design). Both reachable by indexing AND by `.lhs` / `.rhs` attributes.
- **One-sided** (`"~ x + z"`): returns a single design matrix.

Materialized matrices are pandas-DataFrame-like by default: `.columns`, `.shape`, label indexing (`X["col"]`), positional indexing (`X.iloc[:, i]`), and any other standard `pandas.DataFrame` method or attribute (`.to_numpy()`, `.values`, `.iterrows()`, `.sum()`, etc.) — a wrapper class should pass through attribute access to the underlying DataFrame transparently, NOT enumerate a fixed allowlist of methods.

### 1.2 Intercept

Auto-inserted on the RHS of every formula as a column named `"Intercept"` containing `1.0` per row. Removed two equivalent ways:
- `"y ~ x - 1"` — subtract the `1` term
- `"y ~ 0 + x"` — a leading `0` on the RHS removes the intercept (equivalent to `- 1`)

### 1.3 Other Formula API

- `Formula(spec).required_variables` — set of data-column names the formula needs to materialize. Union of LHS and RHS variable references; excludes transform names from the evaluation namespace.
- `Formula(spec).differentiate(var)` — returns a new Formula whose terms are symbolically differentiated wrt `var`. Without `sympy`: constants → `0`, the bare variable → `1`, products containing the variable drop it (so `a:var` becomes `a`), terms not structurally containing `var` (including `I(var**2)` etc., whose interior the parser doesn't inspect) → `0`. Term ordering is preserved.
- `str(formula)` / `repr(formula)` — joins each Term's individual repr with ` + `. Two-sided formulas render LHS and RHS separately.

---

## 2. Formula operators

Binary operators over RHS terms; semantics are over *sets of terms*.

| Operator | Meaning |
|---|---|
| `+` | Union of term sets |
| `-` | Set difference (remove the named term) |
| `:` | Interaction only (no main effects) |
| `*` | Main effects + interaction: `a*b ≡ a + b + a:b` |
| `/` | Nesting: `a/b ≡ a + a:b` (parent + interaction, NOT standalone `b`) |
| `**`, `^` | Power expansion: `(terms)**k` yields all main effects + all interactions up to degree `k` |
| `\|` | Multi-part RHS split; each sub-formula gets its own intercept. After materialization, `.rhs` is an indexable sequence of independent design matrices in left-to-right order |
| `.` (postfix) | Auto-include all data-frame columns not already referenced elsewhere (excluding the LHS variable for two-sided formulas), in data-frame column order |

**Term ordering:** terms in the materialized matrix are sorted by **degree** (intercept first, then main effects, then 2-way interactions, etc.); within a degree level, original order is preserved.

**Literal validation:** numeric literals other than `1` may only be used as multiplicative scalars (e.g. `~ 2:x`), never as standalone terms (`~ x + 2` is invalid). String literals are never valid. Both raise a parse error.

---

## 3. Categorical encoding (contrasts)

Columns with non-numeric dtype (e.g. strings) are auto-treated as categorical. Default encoding is **treatment contrasts** with alphabetical level ordering.

### 3.1 Column-naming conventions

| Context | Column-name format | Notes |
|---|---|---|
| Reduced rank (intercept present), treatment | `<expr>[T.<level>]` | First alphabetical level dropped as reference; the `<level>` labels are the remaining levels (2..k) |
| Reduced rank, sum-to-zero | `<expr>[S.<level>]` | Last alphabetical level encoded as `-1`; the `<level>` labels are levels 1..k-1 |
| Reduced rank, Helmert | `<expr>[H.<level>]` | Like treatment, the first alphabetical level is the implicit baseline; the `<level>` labels are the remaining levels (2..k) |
| Reduced rank, polynomial | `<expr>[.<degree>]` where `<degree>` is `L`, `Q`, `C`, …  (linear, quadratic, cubic) | One contrast per polynomial degree up to k-1 for k levels |
| Full rank (no intercept) | `<expr>[<level>]` | All levels get a column |

`<expr>` is the variable name (when the column comes directly from data) or the function-call repr when wrapped (e.g. `C(x)` produces `C(x)[...]`, `C(x, contr.sum)` produces `C(x, contr.sum)[S....]`).

In **reduced-rank** form, values are one-hot indicators EXCEPT for the dropped/reference level, which is encoded per the contrast scheme: treatment → all zeros; sum-to-zero → all `-1`; Helmert → standard Helmert (each contrast compares a level against the mean of preceding levels), using the **unscaled integer** R `contr.helmert` convention — contrast column `j` (1-indexed, comparing the `(j+1)`-th level against the mean of the `j` preceding levels) assigns `+j` to that level, `-1` to each of the `j` preceding levels, and `0` to later levels, NOT normalized/divided by the group size; polynomial (`contr.poly`) → orthogonal polynomial contrasts (k-1 columns for k levels, pairwise orthogonal). In **full-rank** form, all schemes reduce to one-hot.

**Rank handling for interactions (avoiding redundant columns).** The "all levels get a column" full-rank rule above applies to a categorical that has no overlapping lower-order term competing for the same span. When several categorical factors interact AND lower-order terms overlap (e.g. `0 + a*b*c`, where the main effects and pairwise interactions are present alongside the three-way term), the encoder does NOT make every factor full-rank — that would be collinear. Instead it keeps just enough factors full-rank so that the combined design spans the saturated cell space exactly once, with no redundancy: lower-order terms keep their factor(s) full-rank, and each higher-order term reduces the already-spanned factors to one-fewer-than-full (dropping a reference level). The net effect is that a saturated `a*b*c` over `k1, k2, k3` levels with no intercept yields exactly `k1 * k2 * k3` columns total, not the naive sum of all per-cell counts. (A single interaction with no overlapping lower-order terms, such as `0 + a:b`, is unaffected: every Cartesian cell gets a column.)

### 3.2 `C(...)` — explicit categorical wrapping

`C(x)` marks `x` as categorical even when its dtype is numeric. Keyword arguments:
- `contrasts=` — contrast object (`contr.treatment` (default), `contr.sum`, `contr.helmert`, `contr.poly`).
- `levels=` — explicit list of valid levels; ALSO determines their order in the encoded output (overriding alphabetical default).

`C(x, contr.sum)` is shorthand for `C(x, contrasts=contr.sum)`.

---

## 4. Transforms

Available in the formula evaluation namespace. The materialized column name is the function-call expression as a Python `repr`.

| Transform | Semantics |
|---|---|
| `log`, `log10`, `log2`, `exp`, `exp2` | Numpy ufuncs, applied elementwise |
| `center(x)` | Subtract the column mean |
| `scale(x)` | Subtract mean, divide by sample std with **Bessel's correction (`ddof=1`, NOT `ddof=0`)** |
| `poly(x, degree, raw=False)` | Returns `degree`-column polynomial basis (constant degree-0 term NEVER returned). `raw=True` → pure powers, column `i` is `x ** i` for `i ∈ {1,…,degree}`. `raw=False` (default) → orthonormal basis (pairwise orthogonal, unit L2 norm); column names `poly(x, degree)[i]` for `i ∈ {1,…,degree}` |
| `I(expr)` | Evaluates `expr` as plain Python against the data namespace; escapes formula-operator interpretation (e.g. `I(x**2 + 1)` evaluates arithmetic rather than treating `**` as the power operator) |
| `bs(x, df=None, knots=None, degree=3, include_intercept=False, extrapolation='raise')` | B-spline basis. `df=k` (no explicit knots) → exactly `k` columns (knots auto-placed at quantiles). Explicit `knots=[…]` → `degree + len(knots)` columns (or one more if `include_intercept=True`). The boundary (exterior) knots default to the min and max of the training data — in **both** the `df=` and the explicit-`knots` cases — and these bounds become the captured training-domain bounds (see `extrapolation=`). All values non-negative. `include_intercept=True` → partition of unity (rows sum to 1); when `include_intercept=False` (default) the **first (leftmost)** basis function is dropped, so an input sitting exactly at the training-domain lower bound yields an all-zero basis row and one sitting exactly at the upper bound activates only the final basis column (to 1). `extrapolation=` controls behavior for values outside the training-domain bounds (captured as part of the spec's state at training time): `'raise'` (default — error), `'clip'` (clip the input to the boundary before basis evaluation), `'extend'` (continue the polynomial), `'na'` (return NaN), `'zero'` (return all-zero basis row). |
| `cr(x, df)` | Natural cubic regression spline basis with exactly `df` columns. The `df` knots are placed as for `bs`: the two boundary knots sit at the min and max of the data, and the remaining `df - 2` interior knots at equally-spaced interior quantiles. The basis is cardinal at the knots (the row whose value equals a knot activates exactly one column to 1, and the columns are ordered by ascending knot position) and partitions unity (each row sums to 1). Column-naming mirrors `poly` |
| `lag(x, n)` | Shifts a series forward by `n` positions (value originally at row `i` ends up at row `i + n`); rows where the lookback steps before the start are dropped from the output (output is shorter than input by `n` rows) |

---

## 5. `model_matrix` sugar

`model_matrix(spec, data, *, output=None, na_action="drop", cluster_by="none", context=0)` is a convenience wrapper around `Formula(spec).get_model_matrix(data)`. The `spec` may be a formula string, an existing `ModelSpec` (reuses encoding state), or a previously materialized result (reuses its attached `ModelSpec`). A materialized result is accepted whether it came from a one-sided formula (a single design matrix, whose spec is at `result.model_spec`) or a two-sided formula (the LHS/RHS pair, whose spec is at `result.rhs.model_spec` per §6); passing a two-sided pair re-materializes a two-sided result (LHS + RHS) on `data`. Captures the caller's local/global namespaces by default so user-defined functions resolve.

### 5.1 `output=` — matrix backend

| Value | Returns |
|---|---|
| `None` (default) | pandas-DataFrame-like result (`.columns`, `.shape`, label + positional indexing) |
| `"numpy"` | result whose underlying value is a `numpy.ndarray` (`numpy.asarray(result)` yields one) |
| `"sparse"` | result whose underlying value is a `scipy.sparse` matrix; supports `.toarray()` and `.shape` |

### 5.2 `na_action=` — missing data

| Value | Behavior |
|---|---|
| `"drop"` (default) | silently drop any row containing NaN in any referenced variable |
| `"raise"` | raise `ValueError` when any NaN is encountered |
| `"ignore"` | preserve all rows; NaN values flow through untouched |

### 5.3 `cluster_by=` — column clustering

Default is the term order from §2. `cluster_by="numerical_factors"` groups columns by their shared numerical-factor membership: columns containing NO numerical factor first, then columns whose numerical factor is `x`, then `y`, etc. The column set is unchanged, only the order.

---

## 6. `ModelSpec` — captured encoding state

Every materialized model matrix carries an attached `ModelSpec`, accessed as `result.model_spec` (one-sided) or `result.rhs.model_spec` (two-sided). The spec captures the parsed formula, the exact output columns, and the state of every stateful transform (categorical levels, training means/stds, poly orthogonalization coefficients, spline knots).

A spec can be reapplied via `spec.get_model_matrix(new_data)`.

### 6.1 Stateful-transform reuse

Reusing a spec on new data MUST apply training-derived state, not recompute it:
- **`scale(x)`** — training mean and training std on new data. New data is NOT re-standardized against itself.
- **`poly(x, k)`** — training orthogonalization coefficients on new data. Re-applying a spec to any subset of the training data must reproduce the corresponding rows of the original output exactly.
- **Categorical encoding** — level set captured at training time is preserved (column names AND order). Levels absent from new data still appear as columns (filled with zeros); levels in new data not in the training set are treated as null.

### 6.2 `ModelSpec` API

- `column_names` — ordered tuple of output column names.
- `column_indices` — dict mapping each column name to its integer index.
- `get_column_indices(names)` — integer indices for a nominated list, **in the requested order**.
- `terms` — list of `Term` objects in the order they appear in the matrix; each Term's str-repr matches its term name (`"1"` for intercept, `"x"` for a main effect, `"x:g"` for an interaction).
- `term_slices` — mapping from each `Term` (or its string form) to a Python `slice` selecting that term's columns. A 1-column term gets a 1-wide slice; a categorical encoded into `k` columns gets a `k`-wide slice.
- `update(**kwargs)` — returns a NEW `ModelSpec` with the nominated attributes overridden; captured state is preserved (e.g. `spec.update(output="numpy").get_model_matrix(df)` switches backend without recomputing).
- `subset(terms_spec)` — returns a new `ModelSpec` restricted to a subset of terms. `terms_spec` is a formula-style specification (list of term strings, or a string parsed as a formula); the intercept can be selected via the term string `"1"`. Raises `ValueError` if `terms_spec` references a term not in the original spec. A subsetted spec preserves, for each retained term, the encoding captured in the parent spec — the exact output column names, their order, and the reduced-rank-vs-full-rank contrast choice — when re-materialized via `get_model_matrix`. The §3.1 rank choice is fixed at the parent's original materialization and is NOT re-derived from the subset's own term set: dropping the intercept term from the subset does not switch a categorical to full-rank, so a factor the parent encoded reduced-rank as `g[T.B]` stays `g[T.B]` (with the same level→value mapping) even when `"1"` is absent from the subset. (Subsetting is therefore in general not equivalent to building a fresh spec from the subset formula.)

---

## 7. Linear constraints

`spec.get_linear_constraints(constraint_spec)` builds a `LinearConstraints` object representing one or more linear equality constraints `A @ beta = b`, where `A` is a coefficient matrix over the spec's output columns and `b` is the values vector.

Returned object exposes:
- `.constraint_matrix` — 2-D ndarray-like, shape `(n_constraints, n_columns)`; coefficients aligned to `spec.column_names`.
- `.constraint_values` — 1-D array of length `n_constraints`.
- `.variable_names` — ordered tuple of column names (mirrors `spec.column_names`).

Supported `constraint_spec` forms:

| Form | Interpretation |
|---|---|
| Single-equality string (`"x = 0"`) | One row in the constraint matrix; column-references resolve to the matching column name |
| Multi-equality string (`"x = 1, g[T.B] = 2"`) | Comma-separated equalities; each becomes one row |
| Dict (`{"x": 2, "g[T.B]": -1}`) | Each key is parsed as a constraint formula and each value is the RHS; one row per key in dict-insertion order |
