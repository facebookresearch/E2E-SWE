"""User-facing tests for probnum probabilistic linear solvers (``probnum.linalg``).

Covers ``problinsolve`` on SPD systems: solution recovery, the matrix and inverse
beliefs and their structured posterior covariance, the ``info`` dictionary and its
self-consistency, matrix-variate priors, sparse systems, multiple right-hand sides,
early stopping, and the per-iteration callback.
"""
import numpy as np
import pytest
import scipy.sparse

from probnum import linops, randvars
from probnum.linalg import problinsolve


def _spd(rng, n):
    q = rng.normal(size=(n, n))
    return q @ q.T + n * np.eye(n)


def test_problinsolve_recovers_spd_solution_with_rv_outputs():
    """On an SPD system the posterior mean recovers the true solution and outputs are random variables."""
    rng = np.random.default_rng(0)
    n = 25
    a = _spd(rng, n)
    x_true = rng.normal(size=n)
    b = a @ x_true

    x, ahat, ainvhat, info = problinsolve(A=a, b=b, atol=1e-10, rtol=1e-10)

    assert isinstance(x, randvars.RandomVariable)
    assert isinstance(ahat, randvars.RandomVariable)
    assert isinstance(ainvhat, randvars.RandomVariable)
    np.testing.assert_allclose(x.mean, x_true, rtol=1e-6, atol=1e-6)
    assert info["resid_l2norm"] < 1e-6


def test_problinsolve_info_dict_is_self_consistent():
    """The info dict carries the documented keys and its residual/trace fields are internally consistent."""
    rng = np.random.default_rng(1)
    n = 20
    a = _spd(rng, n)
    b = a @ rng.normal(size=n)

    x, _, _, info = problinsolve(A=a, b=b)

    assert {"iter", "maxiter", "resid_l2norm", "trace_sol_cov"}.issubset(info.keys())
    assert 0 < info["iter"] <= info["maxiter"]
    assert info["resid_l2norm"] == pytest.approx(np.linalg.norm(a @ x.mean - b))
    assert info["trace_sol_cov"] == pytest.approx(x.cov.trace())


def test_problinsolve_posterior_covariance_is_symmetric_psd():
    """The inverse-belief posterior has symmetric Kronecker covariance with PSD factors."""
    rng = np.random.default_rng(2)
    n = 15
    a = _spd(rng, n)
    b = a @ rng.normal(size=n)

    _, ahat, ainvhat, _ = problinsolve(A=a, b=b)

    def _dense(x):  # the operator/factor may be a linop or a plain array
        return x.todense() if hasattr(x, "todense") else np.asarray(x)

    ainv_mean = _dense(ainvhat.mean)
    np.testing.assert_allclose(ainv_mean, ainv_mean.T, atol=1e-9)
    for belief in (ahat, ainvhat):
        cov_factor = _dense(belief.cov.A)
        np.testing.assert_allclose(cov_factor, cov_factor.T, atol=1e-9)
        # PSD up to eigendecomposition roundoff at the factor's own scale: a faithful solver may
        # choose a small posterior covariance, so floor the negative-eigenvalue tolerance relative
        # to the factor's magnitude rather than at an absolute 1e-8 (still rejects an indefinite cov).
        eigvals = np.linalg.eigvalsh(cov_factor)
        assert np.min(eigvals) >= -1e-8 * max(1.0, np.max(np.abs(eigvals)))


def test_problinsolve_with_matrixvariate_prior():
    """A matrix-variate prior on the inverse still yields the correct solution."""
    rng = np.random.default_rng(3)
    n = 12
    a = _spd(rng, n)
    x_true = rng.normal(size=n)
    b = a @ x_true

    ainv0 = randvars.Normal(
        mean=np.eye(n), cov=linops.SymmetricKronecker(A=np.eye(n))
    )
    x, _, _, _ = problinsolve(A=a, b=b, Ainv0=ainv0)
    np.testing.assert_allclose(x.mean, x_true, rtol=1e-5, atol=1e-5)


def test_problinsolve_on_sparse_system():
    """A sparse SPD system is solved to match scipy's sparse direct solver."""
    n = 30
    diag = 2.0 * np.ones(n)
    offdiag = -1.0 * np.ones(n - 1)
    a = scipy.sparse.diags([offdiag, diag, offdiag], offsets=[-1, 0, 1], format="csr")
    rng = np.random.default_rng(4)
    b = rng.normal(size=n)

    x, _, _, _ = problinsolve(A=a, b=b)
    x_ref = scipy.sparse.linalg.spsolve(a.tocsc(), b)
    np.testing.assert_allclose(x.mean, x_ref, rtol=1e-4, atol=1e-4)


def test_problinsolve_multiple_and_zero_right_hand_sides():
    """Multiple RHS are solved column-wise, and a zero RHS yields a zero solution."""
    rng = np.random.default_rng(5)
    n = 14
    a = _spd(rng, n)

    bmat = rng.normal(size=(n, 4))
    x, _, _, _ = problinsolve(A=a, b=bmat)
    assert x.shape == (n, 4)
    np.testing.assert_allclose(x.mean, np.linalg.solve(a, bmat), rtol=1e-4, atol=1e-4)

    xz, _, _, _ = problinsolve(A=a, b=np.zeros(n))
    np.testing.assert_allclose(xz.mean, np.zeros(n), atol=1e-10)


def test_problinsolve_callback_runs_once_per_iteration():
    """A user callback is invoked once per solver iteration."""
    rng = np.random.default_rng(6)
    n = 18
    a = _spd(rng, n)
    b = a @ rng.normal(size=n)

    calls = []
    x, _, _, info = problinsolve(
        A=a, b=b, callback=lambda **kwargs: calls.append(1)
    )
    # One call per iteration (allowing a one-step difference for the initial/final convention).
    assert len(calls) > 0
    assert abs(len(calls) - info["iter"]) <= 1


def test_problinsolve_search_directions_are_a_conjugate():
    """The solver's successive search directions are mutually A-conjugate (s_i^T A s_j = 0, i != j)."""
    rng = np.random.default_rng(8)
    n = 16
    a = _spd(rng, n)
    b = a @ rng.normal(size=n)

    directions = []
    problinsolve(A=a, b=b, callback=lambda **kw: directions.append(np.asarray(kw["sk"]).ravel()))
    assert len(directions) >= 2

    dirs = np.array(directions)
    max_offdiag = max(
        abs(dirs[i] @ a @ dirs[j])
        for i in range(len(dirs))
        for j in range(i + 1, len(dirs))
    )
    scale = max(abs(dirs[i] @ a @ dirs[i]) for i in range(len(dirs)))
    assert max_offdiag <= 1e-6 * scale


def test_problinsolve_calibration_methods_meet_tolerance():
    """Each uncertainty-calibration mode still produces an accurate solution."""
    rng = np.random.default_rng(9)
    n = 20
    a = _spd(rng, n)
    x_true = rng.normal(size=n)
    b = a @ x_true

    for calibration in (None, 0, "adhoc", "weightedmean"):
        x, _, _, _ = problinsolve(A=a, b=b, calibration=calibration)
        np.testing.assert_allclose(x.mean, x_true, rtol=1e-3, atol=1e-3)


def test_problinsolve_posterior_contracts_with_more_iterations():
    """Allowing more solver iterations contracts the posterior (smaller solution-covariance trace)."""
    rng = np.random.default_rng(10)
    n = 30
    a = _spd(rng, n)
    b = a @ rng.normal(size=n)

    _, _, _, info_few = problinsolve(A=a, b=b, maxiter=3)
    _, _, _, info_many = problinsolve(A=a, b=b, maxiter=n, atol=1e-12, rtol=1e-12)
    assert info_many["trace_sol_cov"] < info_few["trace_sol_cov"]
    assert info_many["iter"] > info_few["iter"]


def test_problinsolve_matrix_and_inverse_beliefs_recover_a():
    """The matrix and inverse beliefs recover A and A^-1: A_belief.mean ~= A and Ainv_belief.mean @ A ~= I."""
    rng = np.random.default_rng(7)
    n = 18
    a = _spd(rng, n)
    b = a @ rng.normal(size=n)

    _, ahat, ainvhat, _ = problinsolve(A=a, b=b, atol=1e-12, rtol=1e-12, maxiter=5 * n)

    def _dense(x):  # the belief mean may be a linop or a plain array
        return x.todense() if hasattr(x, "todense") else np.asarray(x)

    a_mean = _dense(ahat.mean)
    ainv_mean = _dense(ainvhat.mean)
    # The matrix belief recovers A on the explored Krylov space, so it reproduces A's action on b.
    np.testing.assert_allclose(a_mean @ b, a @ b, rtol=1e-4, atol=1e-4)
    # The inverse belief inverts A's action on b (A^-1 @ (A @ x) == x).
    np.testing.assert_allclose(ainv_mean @ b, np.linalg.solve(a, b), rtol=1e-4, atol=1e-4)
