"""Tests for a from-scratch reimplementation of the formulaic library.

The library implements Wilkinson formulas for Python: a string DSL such as
`y ~ x + z` is parsed into a structured Formula, which can then be materialized
against a pandas DataFrame to produce a numeric model matrix suitable for
linear regression (with categorical encoding, splines, polynomial bases, NA
handling, etc.).

Each test below exercises one realistic end-to-end user workflow against the
public API exposed at `formulaic.*` (Formula, model_matrix, ModelSpec).
"""

import numpy as np
import pandas as pd
import pytest
import scipy.sparse as spsparse


# ---------------------------------------------------------------------------
# Group A: Basic formula parsing + intercept handling
# ---------------------------------------------------------------------------


class TestBasicFormulas:
    @pytest.fixture
    def df(self):
        return pd.DataFrame(
            {
                "y": [0.0, 1.0, 2.0, 3.0],
                "x": [10.0, 20.0, 30.0, 40.0],
                "z": [0.1, 0.2, 0.3, 0.4],
            }
        )

    def test_two_sided_formula_splits_lhs_rhs(self, df):
        """A two-sided formula `y ~ x + z` materializes into a pair (LHS, RHS)
        with the y-vector on the left and the design matrix on the right."""
        from formulaic import Formula

        y, X = Formula("y ~ x + z").get_model_matrix(df)
        assert list(y.columns) == ["y"]
        assert list(X.columns) == ["Intercept", "x", "z"]
        assert list(y["y"]) == [0.0, 1.0, 2.0, 3.0]
        assert list(X["Intercept"]) == [1.0, 1.0, 1.0, 1.0]
        assert list(X["x"]) == [10.0, 20.0, 30.0, 40.0]

    def test_one_sided_formula_returns_single_matrix(self, df):
        """A one-sided formula `~ x + z` materializes into a single design
        matrix (no LHS pair)."""
        from formulaic import Formula

        X = Formula("~ x + z").get_model_matrix(df)
        assert list(X.columns) == ["Intercept", "x", "z"]

    def test_intercept_is_auto_included(self, df):
        """The default formula parser auto-inserts an Intercept term, so
        `y ~ x` produces a design matrix whose first column is `Intercept`."""
        from formulaic import Formula

        _, X = Formula("y ~ x").get_model_matrix(df)
        assert list(X.columns) == ["Intercept", "x"]
        assert list(X["Intercept"]) == [1.0, 1.0, 1.0, 1.0]

    def test_intercept_can_be_removed_two_equivalent_ways(self, df):
        """The intercept can be removed two equivalent ways: subtract `1`
        (`y ~ x - 1`) or add `0` (`y ~ 0 + x`, where `0` is rewritten to
        `-1` before operator evaluation). Both produce the same design
        matrix with no `Intercept` column and only the remaining terms."""
        from formulaic import Formula

        _, X_minus = Formula("y ~ x - 1").get_model_matrix(df)
        _, X_zero = Formula("y ~ 0 + x").get_model_matrix(df)
        assert list(X_minus.columns) == ["x"]
        assert list(X_zero.columns) == ["x"]
        assert list(X_minus["x"]) == list(X_zero["x"])


# ---------------------------------------------------------------------------
# Group B: Operator semantics
# ---------------------------------------------------------------------------


class TestOperators:
    @pytest.fixture
    def df(self):
        return pd.DataFrame(
            {
                "a": ["A", "B", "A", "B"],
                "b": ["X", "Y", "X", "Y"],
                "x": [1.0, 2.0, 3.0, 4.0],
            }
        )

    def test_star_expands_to_main_effects_plus_interaction(self, df):
        """The `*` operator expands `a*b` to `a + b + a:b` (main effects plus
        interaction). For two binary categoricals with intercept, this produces
        columns: Intercept, a[T.B], b[T.Y], a[T.B]:b[T.Y]."""
        from formulaic import Formula

        X = Formula("~ a*b").get_model_matrix(df)
        assert list(X.columns) == [
            "Intercept",
            "a[T.B]",
            "b[T.Y]",
            "a[T.B]:b[T.Y]",
        ]

    def test_colon_is_interaction_only(self, df):
        """The `:` operator produces interactions WITHOUT main effects. For
        numeric `a:x` this is a single column equal to the product."""
        from formulaic import Formula

        df_num = pd.DataFrame({"a": [1.0, 2.0, 3.0], "x": [10.0, 20.0, 30.0]})
        X = Formula("~ 0 + a:x").get_model_matrix(df_num)
        assert list(X.columns) == ["a:x"]
        assert list(X["a:x"]) == [10.0, 40.0, 90.0]

    def test_power_double_star_expands_to_pairwise(self, df):
        """`(a + b + x)**2` expands to all main effects plus all pairwise
        interactions, but NOT the three-way interaction. With 2-level
        categoricals `a`, `b` and continuous `x` (reduced-rank encoding),
        the result has exactly 7 columns: intercept, 3 main effects, and
        3 pairwise interactions — and no column references all three
        original variables together (no three-way interaction)."""
        from formulaic import Formula

        X = Formula("~ (a + b + x)**2").get_model_matrix(df)
        cols = list(X.columns)
        # 7 columns total
        assert len(cols) == 7
        # Intercept + 3 main effects present
        assert "Intercept" in cols
        assert any(c == "x" for c in cols)
        assert any("a" in c and ":" not in c for c in cols)
        assert any("b" in c and ":" not in c for c in cols)
        # 3 pairwise interactions (factor-order within the name is
        # implementation-defined, so check membership of each pair)
        interaction_cols = [c for c in cols if ":" in c]
        assert len(interaction_cols) == 3
        # No three-way interaction (no column contains all of a, b, x)
        assert not any(("a" in c and "b" in c and "x" in c) for c in interaction_cols)
        # Each expected pair appears in exactly one interaction
        assert sum(("a" in c and "b" in c) for c in interaction_cols) == 1
        assert sum(("a" in c and "x" in c) for c in interaction_cols) == 1
        assert sum(("b" in c and "x" in c) for c in interaction_cols) == 1
        # `^` is a pure alias of `**`: `(a + b + x)^2` produces the identical
        # column set (same 7 columns, same order), so the alias is verified
        # here rather than in a separate equal-weight graded slot.
        cols_caret = list(Formula("~ (a + b + x)^2").get_model_matrix(df).columns)
        assert cols_caret == cols

    def test_minus_subtracts_terms(self):
        """`-` removes a term from the running set, so `a*b - a:b` equals
        `a + b` (the interaction is added by `*`, then removed)."""
        from formulaic import Formula

        df = pd.DataFrame({"a": [1.0, 2.0, 3.0], "b": [4.0, 5.0, 6.0]})
        X = Formula("~ a*b - a:b").get_model_matrix(df)
        assert list(X.columns) == ["Intercept", "a", "b"]

    def test_slash_is_nested_main_plus_interaction(self):
        """The `/` operator is nesting: `a/b` expands to the parent term `a`
        followed by the interaction `a:b` — i.e. `a + a:b`, NOT
        `a + b + a:b` (which is `*`)."""
        from formulaic import Formula

        df_num = pd.DataFrame({"a": [1.0, 2.0, 3.0], "b": [4.0, 5.0, 6.0]})
        X = Formula("~ 0 + a/b").get_model_matrix(df_num)
        # The expansion is {a, a:b}, no standalone `b`
        assert list(X.columns) == ["a", "a:b"]
        assert list(X["a:b"]) == [4.0, 10.0, 18.0]


# ---------------------------------------------------------------------------
# Group C: Categorical encoding (contrasts)
# ---------------------------------------------------------------------------


class TestCategoricalEncoding:
    def test_string_column_default_treatment_contrasts(self):
        """A string column is auto-encoded as categorical with treatment
        contrasts. With an intercept present, encoding is reduced-rank: the
        first level (alphabetical) is the reference and dropped; columns are
        named `{var}[T.{level}]`."""
        from formulaic import Formula

        df = pd.DataFrame({"y": [0, 1, 2], "x": ["A", "B", "C"]})
        _, X = Formula("y ~ x").get_model_matrix(df)
        assert list(X.columns) == ["Intercept", "x[T.B]", "x[T.C]"]
        assert list(X["x[T.B]"]) == [0, 1, 0]
        assert list(X["x[T.C]"]) == [0, 0, 1]

    def test_no_intercept_uses_full_rank_encoding(self):
        """When the intercept is removed, the categorical encoding switches to
        full-rank: all levels get columns, named `{var}[{level}]` (no `T.`)."""
        from formulaic import Formula

        df = pd.DataFrame({"y": [0, 1, 2, 3], "x": ["A", "B", "C", "A"]})
        _, X = Formula("y ~ 0 + x").get_model_matrix(df)
        assert list(X.columns) == ["x[A]", "x[B]", "x[C]"]
        assert list(X["x[A]"]) == [1, 0, 0, 1]

    def test_C_wrapper_marks_numeric_as_categorical(self):
        """`C(x)` explicitly marks a column as categorical even if its dtype is
        numeric, producing the same `[T.level]` column-naming pattern."""
        from formulaic import model_matrix

        df = pd.DataFrame({"x": [1, 2, 3, 1, 2, 3]})
        X = model_matrix("0 + C(x)", df)
        assert list(X.columns) == ["C(x)[1]", "C(x)[2]", "C(x)[3]"]

    def test_categorical_interaction_full_rank_column_naming(self):
        """For a full-rank interaction between two categorical variables
        (e.g. `0 + a:b`), every combination of (a-level, b-level) gets its
        own column named `a[<la>]:b[<lb>]` (no `T.` prefix since the encoding
        is full-rank). With 2 levels each, this produces exactly 4 columns
        — one per Cartesian-product cell — and each row picks exactly one
        of them. Column ordering across the interaction is implementation
        defined; this test only checks the COLUMN-NAME SET and that the
        encoding is a valid one-hot."""
        from formulaic import model_matrix

        df = pd.DataFrame({"a": ["A", "B", "A", "B"], "b": ["X", "Y", "X", "Y"]})
        X = model_matrix("0 + a:b", df)
        assert set(X.columns) == {
            "a[A]:b[X]",
            "a[B]:b[X]",
            "a[A]:b[Y]",
            "a[B]:b[Y]",
        }
        # Each row picks exactly one column = 1
        rows = X.to_numpy()
        assert (rows.sum(axis=1) == 1).all()

    def test_sum_contrasts_with_intercept(self):
        """`C(x, contr.sum)` with an intercept uses sum-to-zero contrasts:
        levels get columns named `[S.{level}]` and the last alphabetical level
        is encoded as -1 across the contrast columns."""
        from formulaic import model_matrix

        df = pd.DataFrame({"x": ["A", "B", "C", "A", "B", "C"]})
        X = model_matrix("C(x, contr.sum)", df)
        assert list(X.columns) == [
            "Intercept",
            "C(x, contr.sum)[S.A]",
            "C(x, contr.sum)[S.B]",
        ]
        # 'C' is encoded as (-1, -1) across the two contrast columns
        assert list(X["C(x, contr.sum)[S.A]"]) == [1.0, 0.0, -1.0, 1.0, 0.0, -1.0]
        assert list(X["C(x, contr.sum)[S.B]"]) == [0.0, 1.0, -1.0, 0.0, 1.0, -1.0]


# ---------------------------------------------------------------------------
# Group D: Transforms (log, scale, center, poly, identity)
# ---------------------------------------------------------------------------


class TestTransforms:
    @pytest.fixture
    def df(self):
        return pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0, 5.0]})

    def test_log_transform_uses_numpy_log(self, df):
        """`log(x)` is available in the formula namespace and applies
        `numpy.log` elementwise. The output column is named `log(x)`."""
        from formulaic import model_matrix

        X = model_matrix("0 + log(x)", df)
        assert list(X.columns) == ["log(x)"]
        np.testing.assert_allclose(X["log(x)"], np.log([1.0, 2.0, 3.0, 4.0, 5.0]))

    def test_center_subtracts_mean(self, df):
        """`center(x)` subtracts the mean. Output column is `center(x)`."""
        from formulaic import model_matrix

        X = model_matrix("0 + center(x)", df)
        assert list(X.columns) == ["center(x)"]
        assert list(X["center(x)"]) == [-2.0, -1.0, 0.0, 1.0, 2.0]

    def test_scale_centers_and_divides_by_sample_std(self, df):
        """`scale(x)` centers AND scales by the sample standard deviation
        (Bessel-corrected, i.e. ddof=1, NOT population std with ddof=0)."""
        from formulaic import model_matrix

        X = model_matrix("0 + scale(x)", df)
        assert list(X.columns) == ["scale(x)"]
        # For [1,2,3,4,5]: mean=3, std_ddof1 = sqrt(10/4) ≈ 1.5811388
        np.testing.assert_allclose(
            X["scale(x)"],
            [-1.2649110, -0.6324555, 0.0, 0.6324555, 1.2649110],
            atol=1e-6,
        )

    def test_poly_raw_returns_pure_powers(self, df):
        """`poly(x, 3, raw=True)` returns the raw powers x, x^2, x^3 as three
        columns (no orthogonalization, no constant column)."""
        from formulaic import model_matrix

        X = model_matrix("0 + poly(x, 3, raw=True)", df)
        # Three columns, one per power
        assert len(X.columns) == 3
        # First column is x, second is x^2, third is x^3
        assert list(X.iloc[:, 0]) == [1.0, 2.0, 3.0, 4.0, 5.0]
        assert list(X.iloc[:, 1]) == [1.0, 4.0, 9.0, 16.0, 25.0]
        assert list(X.iloc[:, 2]) == [1.0, 8.0, 27.0, 64.0, 125.0]

    def test_poly_orthonormal_columns_are_orthogonal(self, df):
        """`poly(x, 3)` returns an orthonormal polynomial basis (3 columns,
        constant term dropped). The columns must be pairwise orthogonal and
        unit-norm under the standard inner product."""
        from formulaic import model_matrix

        X = model_matrix("0 + poly(x, 3)", df)
        assert X.shape == (5, 3)
        cols = [X.iloc[:, i].to_numpy() for i in range(3)]
        # Each column has unit L2 norm
        for c in cols:
            np.testing.assert_allclose(np.sum(c * c), 1.0, atol=1e-9)
        # Pairwise orthogonal
        np.testing.assert_allclose(np.dot(cols[0], cols[1]), 0.0, atol=1e-9)
        np.testing.assert_allclose(np.dot(cols[0], cols[2]), 0.0, atol=1e-9)
        np.testing.assert_allclose(np.dot(cols[1], cols[2]), 0.0, atol=1e-9)

    def test_I_identity_escapes_arithmetic(self, df):
        """`I(...)` is the identity / "as-is" transform — it lets the user
        write arithmetic expressions like `I(x**2 + 1)` that would otherwise
        be interpreted by the formula parser."""
        from formulaic import model_matrix

        X = model_matrix("0 + I(x**2 + 1)", df)
        # Exactly one column, values are x^2 + 1
        assert X.shape == (5, 1)
        assert list(X.iloc[:, 0]) == [2.0, 5.0, 10.0, 17.0, 26.0]

    def test_basis_spline_returns_correct_basis_count(self, df):
        """`bs(x, df=4)` returns a B-spline basis with exactly `df` columns
        (degrees of freedom). All basis values are non-negative — a defining
        property of B-spline basis functions."""
        from formulaic import model_matrix

        X = model_matrix("0 + bs(x, df=4)", df)
        assert X.shape == (5, 4)
        # B-spline basis functions are non-negative everywhere by construction
        assert (X.to_numpy() >= 0).all()
        # And include_intercept=True makes them partition unity (sum to 1)
        X_full = model_matrix("0 + bs(x, df=4, include_intercept=True)", df)
        np.testing.assert_allclose(
            X_full.to_numpy().sum(axis=1), np.ones(5), atol=1e-9
        )

    def test_natural_cubic_spline_cr(self, df):
        """`cr(x, df=3)` is the natural cubic regression spline transform — it
        returns exactly `df` columns of basis values. On `[1, 2, 3, 4, 5]` the
        `df=3` knots are the data min/max plus the interior quantile, i.e.
        1, 3, 5; the basis is cardinal at those knots (each knot row activates
        exactly one column to 1.0, columns ordered by ascending knot) and
        partitions unity (every row sums to 1). Those constraints plus the
        NATURAL boundary condition (zero second derivative at the outer knots)
        make the interpolant unique, so the whole matrix is determined: the
        interior rows x=2 and x=4 are the natural-cubic-spline values, which a
        piecewise-linear or otherwise non-cubic basis does not reproduce."""
        from formulaic import model_matrix

        X = model_matrix("0 + cr(x, df=3)", df)
        assert X.shape == (5, 3)
        basis = X.to_numpy()
        # Partition of unity: each row sums to 1.
        np.testing.assert_allclose(basis.sum(axis=1), np.ones(5), atol=1e-9)
        # Cardinal at the three knots (rows for x=1, 3, 5 → rows 0, 2, 4) and
        # the unique natural cubic spline in between.
        expected = np.array(
            [
                [1.0, 0.0, 0.0],
                [0.40625, 0.6875, -0.09375],
                [0.0, 1.0, 0.0],
                [-0.09375, 0.6875, 0.40625],
                [0.0, 0.0, 1.0],
            ]
        )
        np.testing.assert_allclose(basis, expected, atol=1e-9)

    def test_lag_shifts_series(self):
        """`lag(x, n)` shifts a series forward by `n` positions, dropping
        rows where the lookback would step before the start of the series.
        `lag(x, 1)` on a 5-row input produces a 4-row output containing the
        first 4 values of `x` (rows 1..4 in the output correspond to original
        rows 0..3)."""
        from formulaic import model_matrix

        df = pd.DataFrame({"x": [10.0, 20.0, 30.0, 40.0, 50.0]})
        X = model_matrix("0 + lag(x, 1)", df)
        assert X.shape == (4, 1)
        assert list(X.iloc[:, 0]) == [10.0, 20.0, 30.0, 40.0]


# ---------------------------------------------------------------------------
# Group E: ModelSpec reuse on new data (the headline feature)
# ---------------------------------------------------------------------------


class TestModelSpecReuse:
    def test_scale_state_persists_for_new_data(self):
        """When a ModelSpec generated by `scale(x)` on training data is reused
        on new data, the same training mean and std are applied — the new data
        is NOT re-standardized against itself."""
        from formulaic import model_matrix

        train = pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0, 5.0]})
        X_train = model_matrix("0 + scale(x)", train)
        spec = X_train.model_spec

        # New data — apply with the SAME (training-derived) mean=3, std≈1.5811
        new = pd.DataFrame({"x": [10.0, 20.0, 30.0]})
        X_new = spec.get_model_matrix(new)
        np.testing.assert_allclose(
            X_new["scale(x)"],
            [(10 - 3) / 1.5811388, (20 - 3) / 1.5811388, (30 - 3) / 1.5811388],
            atol=1e-5,
        )

    def test_poly_orthogonalization_state_persists(self):
        """`poly(x, k)` retains its orthogonalization coefficients in the
        ModelSpec. Re-applying to the first n rows of the training data must
        reproduce those rows exactly."""
        from formulaic import model_matrix

        train = pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0, 5.0]})
        X_train = model_matrix("0 + poly(x, 2)", train)
        spec = X_train.model_spec

        new = pd.DataFrame({"x": [1.0, 2.0, 3.0]})
        X_new = spec.get_model_matrix(new)
        # Same first three rows as training output
        np.testing.assert_allclose(
            X_new.to_numpy(), X_train.to_numpy()[:3, :], atol=1e-9
        )

    def test_categorical_levels_persist_across_reuse(self):
        """When a categorical encoding is reused, the SAME level set (and
        therefore the SAME column names and column ordering) is applied to the
        new data, regardless of which levels actually appear in the new data."""
        from formulaic import model_matrix

        train = pd.DataFrame({"x": ["A", "B", "C", "A"]})
        X_train = model_matrix("0 + x", train)
        spec = X_train.model_spec
        assert list(X_train.columns) == ["x[A]", "x[B]", "x[C]"]

        # New data only sees B and A in different order; columns must remain
        # the training-derived [A, B, C] order.
        new = pd.DataFrame({"x": ["B", "A"]})
        X_new = spec.get_model_matrix(new)
        assert list(X_new.columns) == ["x[A]", "x[B]", "x[C]"]
        assert list(X_new["x[A]"]) == [0, 1]
        assert list(X_new["x[B]"]) == [1, 0]
        assert list(X_new["x[C]"]) == [0, 0]


# ---------------------------------------------------------------------------
# Group F: ModelSpec introspection (column_names, indices, subset)
# ---------------------------------------------------------------------------


class TestModelSpecIntrospection:
    @pytest.fixture
    def spec(self):
        from formulaic import model_matrix

        df = pd.DataFrame(
            {
                "y": [1.0, 2.0, 3.0, 4.0],
                "x": [10.0, 20.0, 30.0, 40.0],
                "g": ["A", "B", "A", "B"],
            }
        )
        return model_matrix("y ~ x + g", df).rhs.model_spec

    def test_column_names_and_indices(self, spec):
        """ModelSpec exposes `column_names` (the ordered tuple of output
        columns) and `column_indices` (name → index mapping)."""
        assert tuple(spec.column_names) == ("Intercept", "x", "g[T.B]")
        assert spec.column_indices == {"Intercept": 0, "x": 1, "g[T.B]": 2}

    def test_get_column_indices_for_subset(self, spec):
        """`get_column_indices([...])` returns the integer indices for a
        nominated subset of column names, in the requested order."""
        assert spec.get_column_indices(["x", "g[T.B]"]) == [1, 2]
        assert spec.get_column_indices(["g[T.B]", "Intercept"]) == [2, 0]

    def test_subset_restricts_to_named_terms(self, spec):
        """`ModelSpec.subset([...])` returns a new ModelSpec containing only
        the nominated terms (matched by term string)."""
        sub = spec.subset(["x"])
        assert tuple(sub.column_names) == ("x",)
        sub_g = spec.subset(["1", "g"])
        assert tuple(sub_g.column_names) == ("Intercept", "g[T.B]")

    def test_subset_with_unknown_term_raises(self, spec):
        """`ModelSpec.subset([...])` with a term that wasn't in the original
        spec raises a `ValueError`."""
        with pytest.raises(ValueError):
            spec.subset(["unknown_term"])


# ---------------------------------------------------------------------------
# Group G: Output formats (pandas, numpy, sparse)
# ---------------------------------------------------------------------------


class TestOutputFormats:
    @pytest.fixture
    def df(self):
        return pd.DataFrame(
            {
                "y": [1.0, 2.0, 3.0, 4.0],
                "x": [10.0, 20.0, 30.0, 40.0],
                "g": ["A", "B", "A", "B"],
            }
        )

    def test_pandas_output_is_default(self, df):
        """When no `output=` is specified, materialization returns a
        pandas DataFrame (or a proxy that exposes `.columns` and supports
        column indexing like one). Without an intercept, the categorical
        encoding is full-rank, naming columns `{var}[{level}]`."""
        from formulaic import model_matrix

        X = model_matrix("0 + x + g", df)
        assert list(X.columns) == ["x", "g[A]", "g[B]"]
        assert list(X["x"]) == [10.0, 20.0, 30.0, 40.0]

    def test_numpy_output_returns_ndarray(self, df):
        """Passing `output="numpy"` returns an underlying numpy ndarray whose
        contents match the dense materialization of `0 + x + g` (full-rank
        categorical encoding of `g`), not merely a right-shaped array."""
        from formulaic import model_matrix

        X = model_matrix("0 + x + g", df, output="numpy")
        # The model matrix proxies an ndarray
        assert isinstance(np.asarray(X), np.ndarray)
        assert X.shape == (4, 3)
        # The encoded contents (same dense matrix the sparse-output test pins)
        expected = np.array(
            [[10.0, 1, 0], [20.0, 0, 1], [30.0, 1, 0], [40.0, 0, 1]]
        )
        np.testing.assert_array_equal(np.asarray(X), expected)

    def test_sparse_output_returns_scipy_sparse(self, df):
        """Passing `output="sparse"` returns a result backed by a
        scipy.sparse matrix. The result must expose `.shape`, support
        `.toarray()`-style conversion to a dense ndarray, and produce
        identical values to the dense materialization."""
        from formulaic import model_matrix

        X = model_matrix("0 + x + g", df, output="sparse")
        assert X.shape == (4, 3)
        # Any sparse-backed result must round-trip to dense.
        dense = X.toarray() if hasattr(X, "toarray") else np.asarray(X)
        expected = np.array(
            [[10.0, 1, 0], [20.0, 0, 1], [30.0, 1, 0], [40.0, 0, 1]]
        )
        np.testing.assert_array_equal(np.asarray(dense), expected)


# ---------------------------------------------------------------------------
# Group H: Multi-part formulas and structured outputs
# ---------------------------------------------------------------------------


class TestStructuredFormulas:
    def test_pipe_creates_multipart_rhs(self):
        """The `|` operator splits the RHS into an indexable sequence of
        independent parts, each independently getting its own auto-inserted
        intercept, in left-to-right order. `y ~ x | z` yields a two-part RHS;
        the split generalizes to 3+ parts (`y ~ x | z | g`), including a
        categorical part that is reduced-rank under its own intercept."""
        from formulaic import Formula

        df = pd.DataFrame(
            {
                "y": [1.0, 2.0, 3.0],
                "x": [10.0, 20.0, 30.0],
                "z": [0.1, 0.2, 0.3],
                "g": ["A", "B", "A"],
            }
        )
        # Two-part split: LHS is a single matrix; RHS is a sequence of two matrices.
        mm = Formula("y ~ x | z").get_model_matrix(df)
        assert list(mm.lhs.columns) == ["y"]
        assert len(mm.rhs) == 2
        assert list(mm.rhs[0].columns) == ["Intercept", "x"]
        assert list(mm.rhs[1].columns) == ["Intercept", "z"]
        # Three-part split preserves left-to-right ordering; the categorical
        # third part is reduced-rank under its own intercept.
        mm3 = Formula("y ~ x | z | g").get_model_matrix(df)
        assert len(mm3.rhs) == 3
        assert list(mm3.rhs[0].columns) == ["Intercept", "x"]
        assert list(mm3.rhs[1].columns) == ["Intercept", "z"]
        assert "Intercept" in mm3.rhs[2].columns
        assert "g[T.B]" in mm3.rhs[2].columns

    def test_required_variables_lists_data_columns(self):
        """`Formula.required_variables` reports the set of data-column names
        the formula needs in order to materialize: both LHS and RHS variables
        are included. Transform names like `scale` or `log` (which come from
        the formula evaluation namespace, not the data) are NOT included."""
        from formulaic import Formula

        rv = Formula("y ~ x + g").required_variables
        names = sorted(str(v) for v in rv)
        assert names == ["g", "x", "y"]


# ---------------------------------------------------------------------------
# Group I: NA handling
# ---------------------------------------------------------------------------


class TestNAHandling:
    def test_na_action_drop_is_default(self):
        """The default behavior is `na_action="drop"`: rows containing NaN in
        any input variable are silently dropped."""
        from formulaic import model_matrix

        df = pd.DataFrame({"y": [1.0, 2.0, np.nan, 4.0], "x": [1.0, np.nan, 3.0, 4.0]})
        mm = model_matrix("y ~ x", df)
        # Only rows 0 and 3 survive
        assert mm.lhs.shape == (2, 1)
        assert mm.rhs.shape == (2, 2)
        assert list(mm.lhs["y"]) == [1.0, 4.0]
        assert list(mm.rhs["x"]) == [1.0, 4.0]

    def test_na_action_raise_rejects_nulls(self):
        """`na_action="raise"` raises a `ValueError` when nulls are present
        instead of silently dropping rows."""
        from formulaic import model_matrix

        df = pd.DataFrame({"y": [1.0, 2.0, np.nan], "x": [1.0, 2.0, 3.0]})
        with pytest.raises(ValueError):
            model_matrix("y ~ x", df, na_action="raise")


# ---------------------------------------------------------------------------
# Group J: Linear constraints (hypothesis specification)
# ---------------------------------------------------------------------------


class TestLinearConstraints:
    @pytest.fixture
    def spec(self):
        from formulaic import model_matrix

        df = pd.DataFrame(
            {
                "y": [1.0, 2.0, 3.0],
                "x": [1.0, 2.0, 3.0],
                "g": ["A", "B", "A"],
            }
        )
        return model_matrix("y ~ x + g", df).rhs.model_spec

    def test_single_string_constraint(self, spec):
        """`get_linear_constraints("x = 0")` returns a LinearConstraints object
        with a single row in the constraint matrix indicating `x`'s coefficient
        is constrained to 0."""
        c = spec.get_linear_constraints("x = 0")
        # variable_names mirrors the spec's column_names
        assert tuple(c.variable_names) == ("Intercept", "x", "g[T.B]")
        # One constraint: 0*Intercept + 1*x + 0*g[T.B] = 0
        np.testing.assert_array_equal(c.constraint_matrix, [[0.0, 1.0, 0.0]])
        np.testing.assert_array_equal(c.constraint_values, [0])

    def test_dict_constraint_form(self, spec):
        """A dict like `{"x": 2, "g[T.B]": -1}` specifies multiple equality
        constraints in one call."""
        c = spec.get_linear_constraints({"x": 2, "g[T.B]": -1})
        # Two rows
        assert c.constraint_matrix.shape == (2, 3)
        np.testing.assert_array_equal(
            c.constraint_matrix, [[0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
        )
        np.testing.assert_array_equal(c.constraint_values, [2, -1])

    def test_multi_constraint_comma_string(self, spec):
        """A constraint string may contain multiple equality constraints
        separated by commas. `"x = 1, g[T.B] = 2"` parses as two
        independent constraints."""
        c = spec.get_linear_constraints("x = 1, g[T.B] = 2")
        assert c.constraint_matrix.shape == (2, 3)
        np.testing.assert_array_equal(
            c.constraint_matrix, [[0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
        )
        np.testing.assert_array_equal(c.constraint_values, [1, 2])


# ---------------------------------------------------------------------------
# Group K: Advanced features (differentiation, dot operator, na_action ignore,
# explicit levels, post-hoc spec mutation, term slicing, custom contrasts,
# explicit spline knots)
# ---------------------------------------------------------------------------


class TestAdvancedFeatures:
    def test_differentiate_returns_partial_derivative_formula(self):
        """`Formula(...).differentiate(var)` returns a new Formula in which
        each non-vanishing term has been symbolically differentiated with
        respect to `var`. For `~ x + x:z` differentiated wrt `x` (without
        sympy): `x` differentiates to `1` and `x:z` differentiates to `z`.
        Whether the differentiated-to-zero intercept term is retained as a
        literal `0` or pruned from the output is implementation-defined
        (standard symbolic-diff libraries prune zeros)."""
        from formulaic import Formula

        f = Formula("~ x + x:z").differentiate("x")
        # str() of a one-sided formula may or may not carry a leading "~" sigil
        # (the spec does not pin this); strip it so the check is on the
        # differentiation CONTENT, not the string form.
        rendered = str(f).split("~")[-1]
        rendered_terms = {t.strip() for t in rendered.split("+") if t.strip()}
        # The result is fully determined: x -> 1, x:z -> z, and the intercept
        # differentiates to 0 (retained as a literal "0" or pruned). The
        # undifferentiated x / x:z terms must NOT survive.
        assert rendered_terms in ({"1", "z"}, {"0", "1", "z"})

    def test_dot_operator_includes_all_remaining_data_columns(self):
        """The `.` postfix operator on the RHS expands to all data-frame
        columns not already used elsewhere in the formula. For data with
        columns `[y, x, g]` and the formula `y ~ .`, the RHS expansion is
        `1 + x + g` — i.e. intercept + all non-LHS data columns. With a
        2-level categorical `g`, the materialized columns are
        `["Intercept", "x", "g[T.B]"]`."""
        from formulaic import model_matrix

        df = pd.DataFrame(
            {"y": [1.0, 2.0, 3.0, 4.0], "x": [10.0, 20.0, 30.0, 40.0],
             "g": ["A", "B", "A", "B"]}
        )
        mm = model_matrix("y ~ .", df)
        assert list(mm.rhs.columns) == ["Intercept", "x", "g[T.B]"]

    def test_na_action_ignore_preserves_nan_rows(self):
        """`na_action="ignore"` is a third option (beyond `drop` and
        `raise`) that preserves rows with NaN values rather than dropping
        them. The result has the same number of rows as the input."""
        from formulaic import model_matrix

        df = pd.DataFrame(
            {"y": [1.0, 2.0, np.nan, 4.0], "x": [1.0, np.nan, 3.0, 4.0]}
        )
        mm = model_matrix("y ~ x", df, na_action="ignore")
        # All 4 rows preserved (vs 2 rows with default na_action="drop")
        assert mm.lhs.shape == (4, 1)
        assert mm.rhs.shape == (4, 2)

    def test_C_explicit_levels_preserves_argument_order(self):
        """`C(x, levels=[...])` honors the EXPLICIT level ordering supplied
        — the columns appear in the order given in `levels=`, NOT
        alphabetically. For `levels=['B', 'A', 'C']` and full-rank
        encoding, the columns are `[B]`, `[A]`, `[C]` in that exact order."""
        from formulaic import model_matrix

        df = pd.DataFrame({"x": ["A", "B", "C", "A"]})
        X = model_matrix("0 + C(x, levels=['B', 'A', 'C'])", df)
        cols = list(X.columns)
        # Extract just the level inside the trailing brackets from each col
        levels_in_order = [c[c.rindex("[") + 1 : c.rindex("]")] for c in cols]
        assert levels_in_order == ["B", "A", "C"]

    def test_modelspec_update_changes_output_backend(self):
        """`spec.update(output=...)` returns a NEW ModelSpec with the
        nominated attribute(s) overridden. Calling `get_model_matrix(df)`
        on the updated spec uses the new output backend without losing
        any of the previously-captured encoding state."""
        from formulaic import model_matrix

        df = pd.DataFrame(
            {"y": [1.0, 2.0, 3.0, 4.0], "x": [10.0, 20.0, 30.0, 40.0],
             "g": ["A", "B", "A", "B"]}
        )
        spec = model_matrix("y ~ x + g", df).rhs.model_spec
        # Switch backend to numpy via update
        np_spec = spec.update(output="numpy")
        result = np_spec.get_model_matrix(df)
        assert isinstance(np.asarray(result), np.ndarray)
        assert result.shape == (4, 3)
        # The encoded contents must survive `update`: RHS is the reduced-rank
        # treatment encoding of `y ~ x + g` → columns [Intercept, x, g[T.B]].
        # Asserting the concrete matrix (not just the shape) catches an `update`
        # that drops the captured level set or re-encodes `g` against new data.
        expected = np.array(
            [[1.0, 10.0, 0.0], [1.0, 20.0, 1.0], [1.0, 30.0, 0.0], [1.0, 40.0, 1.0]]
        )
        np.testing.assert_array_equal(np.asarray(result), expected)

    def test_modelspec_term_slices_maps_terms_to_column_slices(self):
        """`spec.term_slices` is a mapping from each Term to a Python slice
        object that selects the column range for that term in the
        materialized matrix. For a spec built from `y ~ x + g + x:g` with
        a 2-level `g`, the column layout is
        `[Intercept(1), x(1), g[T.B](1), x:g[T.B](1)]` — so each term gets
        a 1-wide slice."""
        from formulaic import model_matrix

        df = pd.DataFrame(
            {"y": [1.0, 2.0, 3.0, 4.0], "x": [10.0, 20.0, 30.0, 40.0],
             "g": ["A", "B", "A", "B"]}
        )
        spec = model_matrix("y ~ x + g + x:g", df).rhs.model_spec
        slices = {str(term): sl for term, sl in spec.term_slices.items()}
        assert slices["1"] == slice(0, 1, None)
        assert slices["x"] == slice(1, 2, None)
        assert slices["g"] == slice(2, 3, None)
        # Factor order within the interaction's name is implementation-defined
        # (mirroring test_spec_terms_lists_one_term_object_per_term,
        # test_power_double_star_expands_to_pairwise, and
        # test_three_way_interaction_expansion), so resolve the interaction key
        # by its factor SET rather than a fixed 'x:g' spelling.
        interaction_key = next(
            k for k in slices if set(k.split(":")) == {"x", "g"}
        )
        assert slices[interaction_key] == slice(3, 4, None)

    def test_helmert_contrasts_column_naming(self):
        """`C(g, contr.helmert)` uses Helmert contrasts: column-naming uses
        the prefix `H.` (mirroring `T.` for treatment and `S.` for sum).
        For a 2-level categorical `g` with intercept, the encoding is
        reduced rank — a single contrast column named
        `C(g, contr.helmert)[H.B]` with values -1 and +1 for the two
        levels."""
        from formulaic import model_matrix

        df = pd.DataFrame({"y": [1.0, 2.0, 3.0, 4.0], "g": ["A", "B", "A", "B"]})
        _, X = model_matrix("y ~ C(g, contr.helmert)", df)
        assert list(X.columns) == ["Intercept", "C(g, contr.helmert)[H.B]"]
        # Level A → -1, level B → +1
        assert list(X["C(g, contr.helmert)[H.B]"]) == [-1.0, 1.0, -1.0, 1.0]

    def test_bs_with_explicit_knots(self):
        """`bs(x, knots=[...])` allows the user to specify explicit internal
        knot positions instead of relying on `df` to auto-generate them.
        With default `degree=3` and one internal knot, the basis has
        `degree + n_knots = 4` columns (when `include_intercept=False`), and
        its values are fully determined: the boundary knots sit at the data
        range [1, 5] and are clamped (an input at the lower bound activates
        only the first basis function, one at the upper bound only the last),
        so the knot vector is [1, 1, 1, 1, 2.5, 5, 5, 5, 5] and the degree-3
        basis over it is the unique Cox-de Boor basis; `include_intercept=False`
        then drops the leftmost function."""
        from formulaic import model_matrix

        df = pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0, 5.0]})
        X = model_matrix("0 + bs(x, knots=[2.5])", df)
        basis = X.to_numpy()
        # degree=3 + 1 internal knot = 4 basis columns
        assert X.shape == (5, 4)
        # B-spline basis functions are non-negative everywhere by construction.
        assert (basis >= 0).all()
        # Pinning the matrix catches an implementation that ignores the explicit
        # knot, mis-places the boundary knots, or uses the wrong degree while
        # still emitting 4 columns; rows 0 and 4 are the clamped-boundary rows.
        expected = np.array(
            [
                [0.0, 0.0, 0.0, 0.0],
                [0.6157407407407407, 0.3055555555555556, 0.041666666666666664, 0.0],
                [0.2, 0.48, 0.312, 0.008],
                [0.025, 0.21, 0.549, 0.216],
                [0.0, 0.0, 0.0, 1.0],
            ]
        )
        np.testing.assert_allclose(basis, expected, atol=1e-9)
        # include_intercept=True restores the constant basis so the rows
        # partition unity (sum to 1).
        X_full = model_matrix("0 + bs(x, knots=[2.5], include_intercept=True)", df)
        np.testing.assert_allclose(X_full.to_numpy().sum(axis=1), np.ones(5), atol=1e-9)

    def test_spec_terms_lists_one_term_object_per_term(self):
        """`spec.terms` is a list of Term objects in the order they appear in
        the materialized matrix, with EXACTLY ONE Term per formula term — even
        when a term expands to several output columns. Here `g` is a 4-level
        categorical, so the reduced-rank `g` term spans 3 columns and the `x:g`
        interaction another 3, giving 8 output columns; yet `spec.terms` lists
        only the 4 terms `["1", "x", "g", "x:g"]` (one Term each, NOT one per
        column). Each Term's str-repr matches the term name."""
        from formulaic import model_matrix

        df = pd.DataFrame(
            {"y": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0],
             "x": [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0],
             "g": ["A", "B", "C", "D", "A", "B", "C", "D"]}
        )
        spec = model_matrix("y ~ x + g + x:g", df).rhs.model_spec
        # The matrix is wider than the term list: g and x:g each span 3 columns.
        assert len(spec.column_names) == 8
        # spec.terms still lists one Term per term, in materialized order.
        term_strs = [str(t) for t in spec.terms]
        assert len(spec.terms) == 4
        # First three terms are pinned in source order; the interaction term's
        # factor order within its name is implementation-defined (mirroring
        # test_power_double_star_expands_to_pairwise and
        # test_three_way_interaction_expansion), so check its factor SET.
        assert term_strs[:3] == ["1", "x", "g"]
        assert set(term_strs[3].split(":")) == {"x", "g"}

    def test_cluster_by_numerical_factors_reorders_columns(self):
        """The `cluster_by="numerical_factors"` materialization option
        groups output columns by their shared numerical factors. For
        `y ~ x + g + x:g` (mixed numeric/categorical), the default
        ordering interleaves the categorical's columns next to its
        related interaction; `cluster_by="numerical_factors"` instead
        emits all columns with NO numerical factor first, then those with
        the numerical factor `x`. This reorders versus the default."""
        from formulaic import model_matrix

        df = pd.DataFrame(
            {"y": [1.0, 2.0, 3.0, 4.0], "x": [10.0, 20.0, 30.0, 40.0],
             "g": ["A", "B", "A", "B"]}
        )
        default_cols = list(
            model_matrix("y ~ x + g + x:g", df).rhs.columns
        )
        clustered_cols = list(
            model_matrix(
                "y ~ x + g + x:g", df, cluster_by="numerical_factors"
            ).rhs.columns
        )
        # The set of columns is the same; the order is different
        assert set(default_cols) == set(clustered_cols)
        assert default_cols != clustered_cols
        # In the clustered output, all 'x'-containing columns come AFTER all
        # non-x columns
        clustered_has_x = ["x" in c for c in clustered_cols]
        # No True (has_x) appears before a False (no_x) — i.e., the False
        # values all come first
        last_false = max(
            (i for i, b in enumerate(clustered_has_x) if not b), default=-1
        )
        first_true = min(
            (i for i, b in enumerate(clustered_has_x) if b), default=len(clustered_cols)
        )
        assert last_false < first_true

    def test_formula_accepts_list_specification(self):
        """`Formula` accepts a list of term-string specifications as an
        alternative to a formula string. `Formula(["1", "x", "y:z"])`
        constructs a SimpleFormula whose terms (in degree-sorted order)
        are the intercept, the main effect `x`, and the interaction `y:z`."""
        from formulaic import Formula

        f = Formula(["x", "y:z", "1"])
        # Degree-sort: intercept (0), main effects (1), interactions (2).
        # str() of a one-sided/list-built SimpleFormula may or may not carry a
        # leading "~" sigil (the spec does not pin this; see
        # test_differentiate_returns_partial_derivative_formula), so strip an
        # optional leading "~" before checking the term CONTENT.
        rendered = str(f).split("~")[-1]
        rendered_terms = {t.strip() for t in rendered.split("+") if t.strip()}
        assert rendered_terms == {"1", "x", "y:z"}

    def test_two_equivalent_formulas_compare_equal(self):
        """Two Formula instances constructed from equivalent specifications
        compare equal via `==`. Equality is by the underlying term content,
        NOT by object identity."""
        from formulaic import Formula

        f1 = Formula(["1", "x"])
        f2 = Formula(["1", "x"])
        assert f1 == f2
        # And a different formula compares not-equal
        f3 = Formula(["1", "y"])
        assert f1 != f3

    def test_three_way_interaction_expansion(self):
        """`a*b*c` for three categoricals expands to: all main effects +
        all pairwise interactions + the three-way interaction. With three
        binary-categorical inputs (no intercept), the full-rank encoding
        yields 8 columns total: the encoded `a` levels, the contrast
        column for `b`, the contrast column for `c`, the three pairwise
        interactions, and the single three-way interaction."""
        from formulaic import model_matrix

        df = pd.DataFrame(
            {"a": ["A", "B"], "b": ["X", "Y"], "c": ["P", "Q"]}
        )
        X = model_matrix("0 + a*b*c", df)
        assert X.shape == (2, 8)
        # The three-way interaction column must exist (factor order may vary
        # within the interaction; check for the marker)
        three_way_cols = [c for c in X.columns if c.count(":") == 2]
        assert len(three_way_cols) == 1, (
            f"expected exactly one three-way interaction column, got "
            f"{three_way_cols}"
        )

    def test_model_matrix_sugar_reuses_attached_modelspec_from_matrix(self):
        """The sugar function `model_matrix(spec, data)` accepts an
        existing model matrix as the `spec` argument and reuses the
        `ModelSpec` attached to it. This supports the common train→predict
        workflow without manually extracting `.model_spec`."""
        from formulaic import model_matrix

        train = pd.DataFrame(
            {"y": [1.0, 2.0, 3.0, 4.0], "g": ["A", "B", "A", "B"]}
        )
        mm_train = model_matrix("y ~ g", train)
        new = pd.DataFrame({"y": [10.0, 20.0], "g": ["B", "A"]})
        # Pass the existing model matrix instead of the formula string
        mm_new = model_matrix(mm_train, new)
        assert list(mm_new.rhs.columns) == ["Intercept", "g[T.B]"]
        # Level B → 1, Level A → 0 on the contrast column
        assert list(mm_new.rhs["g[T.B]"]) == [1, 0]

    def test_subset_spec_can_materialize_on_fresh_data(self):
        """`spec.subset([...])` returns a new ModelSpec that retains all
        the encoding state needed to materialize on fresh data. The
        subsetted spec produces a matrix with ONLY the subset's columns;
        rows are encoded with the same scheme as the original spec."""
        from formulaic import model_matrix

        train = pd.DataFrame(
            {"y": [1.0, 2.0, 3.0, 4.0], "x": [1.0, 2.0, 3.0, 4.0],
             "g": ["A", "B", "A", "B"]}
        )
        full_spec = model_matrix("y ~ x + g + x:g", train).rhs.model_spec
        # Subset to just main effects (drop the interaction)
        sub = full_spec.subset(["x", "g"])
        # New data — no `y` needed because the subset spec only references
        # x and g
        new = pd.DataFrame({"x": [5.0, 10.0, 15.0], "g": ["A", "B", "A"]})
        sub_mm = sub.get_model_matrix(new)
        # Columns are only x and the g contrast (no intercept since `1`
        # wasn't in subset; no x:g interaction)
        assert list(sub_mm.columns) == ["x", "g[T.B]"]
        assert list(sub_mm["x"]) == [5.0, 10.0, 15.0]
        # Level B → 1 (matches original spec's encoding choice)
        assert list(sub_mm["g[T.B]"]) == [0, 1, 0]

    def test_linear_constraint_algebraic_expression(self):
        """Constraint strings support arithmetic on column-name terms.
        `"x - g[T.B] = 0"` parses as one constraint with coefficient
        vector `[0, 1, -1]` over `(Intercept, x, g[T.B])` and constant
        value 0 — i.e., the linear hypothesis "x's coefficient equals
        g[T.B]'s coefficient"."""
        from formulaic import model_matrix

        df = pd.DataFrame(
            {"y": [1.0, 2.0, 3.0, 4.0], "x": [1.0, 2.0, 3.0, 4.0],
             "g": ["A", "B", "A", "B"]}
        )
        spec = model_matrix("y ~ x + g", df).rhs.model_spec
        c = spec.get_linear_constraints("x - g[T.B] = 0")
        assert c.constraint_matrix.shape == (1, 3)
        np.testing.assert_array_equal(c.constraint_matrix, [[0.0, 1.0, -1.0]])
        np.testing.assert_array_equal(c.constraint_values, [0])

    def test_lag_state_persists_across_reuse(self):
        """`lag(x, n)` is stateful in that the captured `n` value is
        preserved in the spec. Reusing a spec built from `lag(x, 1)` on
        new data drops 1 row from the output (the lookback step before
        the start), regardless of the new data's length."""
        from formulaic import model_matrix

        train = pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0, 5.0]})
        train_mm = model_matrix("0 + lag(x, 1)", train)
        spec = train_mm.model_spec
        # Reuse on a smaller dataset
        new = pd.DataFrame({"x": [100.0, 200.0, 300.0]})
        new_mm = spec.get_model_matrix(new)
        # 3 input rows → 2 output rows (n=1 step lost from the front)
        assert new_mm.shape == (2, 1)
        # Output contains the original first 2 values (lag drops the trailing
        # value because the lookback can't reach past the end)
        assert list(new_mm.iloc[:, 0]) == [100.0, 200.0]


# ---------------------------------------------------------------------------
# Group L: Additional hard E2E features
#   (B-spline extrapolation reuse, polynomial contrasts, 3-part RHS split,
#    categorical NaN handling)
# ---------------------------------------------------------------------------


class TestAdditionalHardFeatures:
    def test_basis_spline_extrapolation_clip_reuses_boundary(self):
        """`bs(x, df, extrapolation='clip')` is a real prediction-time
        workflow: a model is fit on a training range and reused on new
        data that may contain values outside that range. With
        `extrapolation='clip'`, an out-of-range value is clipped to the
        nearest training-domain boundary BEFORE the basis is evaluated —
        so the basis row for an out-of-range input is identical to the
        basis row for the boundary point itself."""
        from formulaic import model_matrix

        train = pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0, 5.0]})
        spec = model_matrix(
            "0 + bs(x, df=4, extrapolation='clip')", train
        ).model_spec
        X_train = spec.get_model_matrix(train)
        new = pd.DataFrame({"x": [10.0]})  # outside [1, 5]
        X_new = spec.get_model_matrix(new)
        # x=10 is clipped to x=5 (upper bound); rows of basis values match
        for col in X_train.columns:
            assert X_new[col].iloc[0] == X_train[col].iloc[4]

    def test_polynomial_contrasts_naming_and_orthogonality(self):
        """`C(x, contr.poly)` produces orthogonal polynomial contrasts for
        an ordered categorical. For a 3-level factor with intercept, the
        encoding yields 2 contrast columns (linear + quadratic), named
        using the prefix `.L` for the linear contrast and `.Q` for the
        quadratic (mirroring R's `contr.poly` convention). The two
        contrast columns are pairwise orthogonal under the standard
        inner product."""
        from formulaic import model_matrix

        df = pd.DataFrame({"y": [1.0] * 9, "g": ["A", "B", "C"] * 3})
        _, X = model_matrix("y ~ C(g, contr.poly)", df)
        # 3 levels → intercept + 2 polynomial contrasts
        assert len(X.columns) == 3
        contrast_cols = [c for c in X.columns if c != "Intercept"]
        assert len(contrast_cols) == 2
        # Naming uses .L (linear) and .Q (quadratic)
        assert any(".L" in c for c in contrast_cols)
        assert any(".Q" in c for c in contrast_cols)
        # The two contrast columns are pairwise orthogonal
        linear_col = next(c for c in contrast_cols if ".L" in c)
        quad_col = next(c for c in contrast_cols if ".Q" in c)
        inner_product = (X[linear_col] * X[quad_col]).sum()
        assert abs(inner_product) < 1e-9

    def test_categorical_nan_row_dropped_under_default_na_action(self):
        """A NaN value in a categorical column is treated as a missing
        observation. Under the default `na_action='drop'`, the row is
        silently dropped from both LHS and RHS, and the encoder's level
        set is built from only the non-null distinct values seen in the
        data (NaN does NOT become a synthetic level)."""
        from formulaic import model_matrix

        df = pd.DataFrame(
            {"y": [1.0, 2.0, 3.0, 4.0], "g": ["A", np.nan, "B", "A"]}
        )
        mm = model_matrix("y ~ g", df)
        # NaN row dropped: 3 rows surviving on both sides
        assert mm.lhs.shape == (3, 1)
        assert mm.rhs.shape == (3, 2)
        # Only A and B levels present; reduced-rank encoding emits B's
        # column only (A is the reference, dropped)
        assert list(mm.rhs.columns) == ["Intercept", "g[T.B]"]
        # Surviving y values are from rows 0, 2, 3 (skipping NaN-in-g row 1)
        assert list(mm.lhs.iloc[:, 0]) == [1.0, 3.0, 4.0]
