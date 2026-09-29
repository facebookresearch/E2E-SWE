"""User-facing tests for probnum linear operators (``probnum.linops``).

The recurring contract: a lazy ``LinearOperator`` must agree with the equivalent
dense numpy computation for matmul, ``todense``, transpose, inverse/solve, and the
scalar quantities (det/logabsdet/trace/eigvals/cond/rank). The structured operators
(Kronecker, SymmetricKronecker, IdentityKronecker, Selection/Embedding, Scaling) and
composite arithmetic are exercised against their dense references.
"""
import numpy as np
import pytest
import scipy.linalg

from probnum import linops


def _spd(rng, n):
    q = rng.normal(size=(n, n))
    return q @ q.T + n * np.eye(n)


def test_matrix_operator_mirrors_its_array():
    """``Matrix`` reproduces its backing array under matmul, transpose and densification."""
    rng = np.random.default_rng(0)
    a = rng.normal(size=(4, 3))
    op = linops.Matrix(a)

    assert op.shape == (4, 3)
    np.testing.assert_array_equal(op.todense(), a)

    v = rng.normal(size=3)
    np.testing.assert_allclose(op @ v, a @ v)
    m = rng.normal(size=(3, 5))
    np.testing.assert_allclose(op @ m, a @ m)
    w = rng.normal(size=4)
    np.testing.assert_allclose(w @ op, w @ a)
    np.testing.assert_allclose(op.T.todense(), a.T)


def test_identity_is_neutral_element():
    """``Identity`` acts as a true neutral element with the expected scalar invariants."""
    rng = np.random.default_rng(1)
    n = 5
    ident = linops.Identity(n)
    x = rng.normal(size=(n, 3))

    np.testing.assert_array_equal(ident.todense(), np.eye(n))
    np.testing.assert_allclose(ident @ x, x)
    assert ident.det() == pytest.approx(1.0)
    assert ident.logabsdet() == pytest.approx(0.0)
    assert ident.trace() == pytest.approx(n)
    assert int(ident.rank()) == n
    np.testing.assert_allclose(np.sort(ident.eigvals()), np.ones(n))

    other = linops.Matrix(rng.normal(size=(n, n)))
    np.testing.assert_allclose((ident @ other).todense(), other.todense())


def test_scaling_isotropic_and_anisotropic():
    """``Scaling`` matches a dense diagonal for matmul and all derived scalar quantities."""
    rng = np.random.default_rng(2)
    factors = np.array([2.0, -3.0, 0.5, 4.0])
    n = factors.size
    aniso = linops.Scaling(factors)
    dense = np.diag(factors)

    np.testing.assert_allclose(aniso.todense(), dense)
    np.testing.assert_allclose(aniso.diagonal(), factors)
    assert aniso.det() == pytest.approx(np.prod(factors))
    assert aniso.trace() == pytest.approx(factors.sum())
    x = rng.normal(size=(n, 2))
    np.testing.assert_allclose(aniso @ x, dense @ x)

    iso = linops.Scaling(3.0, shape=n)
    np.testing.assert_allclose(iso.todense(), 3.0 * np.eye(n))
    assert iso.det() == pytest.approx(3.0**n)

    singular = linops.Scaling(np.array([1.0, 0.0, 2.0]))
    with pytest.raises(np.linalg.LinAlgError):
        singular.inv()


def test_kronecker_matches_np_kron_for_all_quantities():
    """``Kronecker`` agrees with ``np.kron`` for matmul, transpose, inverse, and scalar quantities."""
    rng = np.random.default_rng(3)
    a = _spd(rng, 3)
    b = _spd(rng, 2)
    kron = linops.Kronecker(a, b)
    dense = np.kron(a, b)

    np.testing.assert_allclose(kron.todense(), dense)
    x = rng.normal(size=(6, 4))
    np.testing.assert_allclose(kron @ x, dense @ x)
    np.testing.assert_allclose(kron.T.todense(), dense.T)
    np.testing.assert_allclose(kron.inv().todense(), np.linalg.inv(dense), atol=1e-9)
    assert kron.trace() == pytest.approx(np.trace(dense))
    assert kron.det() == pytest.approx(np.linalg.det(dense), rel=1e-6)


def test_symmetric_kronecker_dense_and_symmetry():
    """``SymmetricKronecker`` densifies to the symmetrized Kronecker sum and is commutative."""
    rng = np.random.default_rng(4)
    n = 3
    a = _spd(rng, n)
    b = _spd(rng, n)

    distinct = linops.SymmetricKronecker(a, b)
    expected = 0.5 * (np.kron(a, b) + np.kron(b, a))
    np.testing.assert_allclose(distinct.todense(), expected)
    # Symmetric in its factors.
    np.testing.assert_allclose(
        distinct.todense(), linops.SymmetricKronecker(b, a).todense()
    )

    identical = linops.SymmetricKronecker(a)
    np.testing.assert_allclose(identical.todense(), np.kron(a, a))
    dense_id = identical.todense()
    np.testing.assert_allclose(dense_id, dense_id.T)


def test_identity_kronecker_block_structure():
    """``IdentityKronecker`` matches ``kron(I, B)`` and preserves block structure under transpose/inverse."""
    rng = np.random.default_rng(5)
    num_blocks = 3
    b = _spd(rng, 2)
    ik = linops.IdentityKronecker(num_blocks, b)
    dense = np.kron(np.eye(num_blocks), b)

    assert ik.num_blocks == num_blocks
    np.testing.assert_allclose(ik.todense(), dense)
    x = rng.normal(size=(6, 4))
    np.testing.assert_allclose(ik @ x, dense @ x)
    np.testing.assert_allclose(ik.T.todense(), dense.T)
    np.testing.assert_allclose(ik.inv().todense(), np.linalg.inv(dense), atol=1e-9)


def test_selection_and_embedding_are_dual():
    """``Selection`` gathers entries; its transpose is an ``Embedding`` that scatters them back."""
    indices = [0, 2, 3]
    sel = linops.Selection(indices, shape=(3, 5))
    x = np.array([10.0, 11.0, 12.0, 13.0, 14.0])
    np.testing.assert_allclose(sel @ x, x[indices])

    emb = sel.T
    assert isinstance(emb, linops.Embedding)
    scattered = emb @ np.array([1.0, 2.0, 3.0])
    expected = np.zeros(5)
    expected[indices] = [1.0, 2.0, 3.0]
    np.testing.assert_allclose(scattered, expected)


def test_inverse_and_solve_match_numpy():
    """``inv``/``solve`` reproduce numpy on a non-singular operator and reject non-square ones."""
    rng = np.random.default_rng(6)
    a = _spd(rng, 4)
    op = linops.Matrix(a)

    np.testing.assert_allclose(op.inv().todense(), np.linalg.inv(a), atol=1e-10)
    b = rng.normal(size=4)
    np.testing.assert_allclose(op.solve(b), np.linalg.solve(a, b), atol=1e-10)
    bs = rng.normal(size=(4, 3))
    np.testing.assert_allclose(op.solve(bs), np.linalg.solve(a, bs), atol=1e-10)

    rect = linops.Matrix(rng.normal(size=(3, 5)))
    with pytest.raises(np.linalg.LinAlgError):
        rect.inv()


def test_composite_arithmetic_matches_dense():
    """Sums, scalar multiples and products of operators evaluate like the dense computation."""
    rng = np.random.default_rng(7)
    a = rng.normal(size=(3, 3))
    b = rng.normal(size=(3, 3))
    c = rng.normal(size=(3, 3))
    op_a, op_b, op_c = linops.Matrix(a), linops.Matrix(b), linops.Matrix(c)

    summed = 2.0 * op_a + op_b
    np.testing.assert_allclose(summed.todense(), 2.0 * a + b)

    product = op_a @ op_b @ op_c
    np.testing.assert_allclose(product.todense(), a @ b @ c)

    negated = -op_a
    np.testing.assert_allclose(negated.todense(), -a)


def test_batched_matmul_broadcasts_like_numpy():
    """Operator application broadcasts over leading batch dimensions exactly like ``numpy.matmul``."""
    rng = np.random.default_rng(8)
    a = rng.normal(size=(4, 3))
    op = linops.Matrix(a)

    stack = rng.normal(size=(5, 3, 2))  # batch of (3, 2) matrices
    np.testing.assert_allclose(op @ stack, a @ stack)

    col = rng.normal(size=(3, 1))
    np.testing.assert_allclose(op @ col, a @ col)


def test_block_diagonal_matrix_matches_dense_block_diag():
    """``BlockDiagonalMatrix`` matches ``scipy.linalg.block_diag`` for matmul, inverse and determinant."""
    rng = np.random.default_rng(10)
    blocks = [_spd(rng, 2), _spd(rng, 3), _spd(rng, 2)]
    op = linops.BlockDiagonalMatrix(*[linops.Matrix(b) for b in blocks])
    dense = scipy.linalg.block_diag(*blocks)

    assert op.shape == (7, 7)
    np.testing.assert_allclose(op.todense(), dense)
    x = rng.normal(size=(7, 3))
    np.testing.assert_allclose(op @ x, dense @ x)
    np.testing.assert_allclose(op.inv().todense(), np.linalg.inv(dense), atol=1e-9)
    assert op.det() == pytest.approx(np.linalg.det(dense), rel=1e-6)


def test_aslinop_dispatch_and_dtype_promotion():
    """``aslinop`` wraps arrays as ``Matrix`` and passes operators through; Kronecker promotes dtype."""
    rng = np.random.default_rng(9)
    arr = rng.normal(size=(3, 3))
    wrapped = linops.aslinop(arr)
    assert isinstance(wrapped, linops.Matrix)
    np.testing.assert_array_equal(wrapped.todense(), arr)

    existing = linops.Identity(3)
    assert linops.aslinop(existing) is existing

    kron = linops.Kronecker(np.eye(2, dtype=np.int64), np.eye(2, dtype=np.float64))
    assert kron.dtype == np.result_type(np.int64, np.float64)
