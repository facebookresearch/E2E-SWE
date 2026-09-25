"""User-facing tests for probnum random variables (``probnum.randvars``).

Covers the Normal (uni/multi/matrix/operator-variate), Constant, and Categorical
random variables, their moment/distribution surface, the covariance-Cholesky
lifecycle, affine/arithmetic propagation, structured (Kronecker) covariances,
marginalization via indexing, and ``asrandvar`` dispatch.
"""
import numpy as np
import pytest
import scipy.stats

from probnum import linops, randvars


def _spd(rng, n):
    """A symmetric positive-definite matrix."""
    q = rng.normal(size=(n, n))
    return q @ q.T + n * np.eye(n)


def test_univariate_normal_matches_scipy_distribution():
    """A univariate Normal exposes the full scalar distribution surface of scipy.stats.norm."""
    mean, var = 0.5, 2.0
    rv = randvars.Normal(mean, var)
    ref = scipy.stats.norm(loc=mean, scale=np.sqrt(var))

    assert rv.mean == pytest.approx(mean)
    assert rv.var == pytest.approx(var)
    assert rv.std == pytest.approx(np.sqrt(var))
    assert rv.median == pytest.approx(mean)
    assert rv.mode == pytest.approx(mean)

    xs = np.array([-1.0, 0.0, 0.5, 1.7, 3.0])
    np.testing.assert_allclose(rv.pdf(xs), ref.pdf(xs))
    np.testing.assert_allclose(rv.cdf(xs), ref.cdf(xs))
    np.testing.assert_allclose(rv.logpdf(xs), ref.logpdf(xs))
    np.testing.assert_allclose(rv.quantile(0.5), mean)

    samples = rv.sample(np.random.default_rng(0), size=(50000,))
    assert samples.shape == (50000,)
    assert samples.mean() == pytest.approx(mean, abs=0.05)
    assert samples.std() == pytest.approx(np.sqrt(var), abs=0.05)


def test_multivariate_normal_moments_and_cholesky():
    """A multivariate Normal reports consistent moments and a valid lazy Cholesky factor."""
    rng = np.random.default_rng(1)
    mean = rng.normal(size=5)
    cov = _spd(rng, 5)
    rv = randvars.Normal(mean, cov)

    assert rv.shape == (5,)
    assert rv.cov.shape == (5, 5)
    np.testing.assert_allclose(rv.cov, cov)
    np.testing.assert_allclose(rv.var, np.diag(cov))
    np.testing.assert_allclose(rv.std, np.sqrt(np.diag(cov)))

    assert rv.cov_cholesky_is_precomputed is False
    chol = rv.cov_cholesky
    assert rv.cov_cholesky_is_precomputed is True
    # Lower-triangular factor that reconstructs the covariance.
    np.testing.assert_allclose(chol, np.tril(chol))
    np.testing.assert_allclose(chol @ chol.T, cov, atol=1e-9)


def test_normal_cholesky_precompute_damping_and_passed_factor():
    """The Cholesky lifecycle honours damping, rejects double precompute, and accepts a given factor."""
    rng = np.random.default_rng(2)
    mean = np.zeros(3)
    cov = _spd(rng, 3)

    rv = randvars.Normal(mean, cov)
    rv.precompute_cov_cholesky(damping_factor=10.0)
    np.testing.assert_allclose(
        rv.cov_cholesky @ rv.cov_cholesky.T, cov + 10.0 * np.eye(3), atol=1e-9
    )
    with pytest.raises(Exception):
        rv.precompute_cov_cholesky()

    given = np.linalg.cholesky(cov)
    rv2 = randvars.Normal(mean, cov, cov_cholesky=given)
    assert rv2.cov_cholesky_is_precomputed is True
    np.testing.assert_allclose(rv2.cov_cholesky, given)


def test_normal_additive_covariance_algebra():
    """Sums/differences of Normals add covariances; shifting by a Constant leaves covariance intact."""
    rng = np.random.default_rng(3)
    m0, m1 = rng.normal(size=4), rng.normal(size=4)
    c0, c1 = _spd(rng, 4), _spd(rng, 4)
    n0, n1 = randvars.Normal(m0, c0), randvars.Normal(m1, c1)

    s = n0 + n1
    np.testing.assert_allclose(s.mean, m0 + m1)
    np.testing.assert_allclose(s.cov, c0 + c1)

    d = n0 - n1
    np.testing.assert_allclose(d.mean, m0 - m1)
    np.testing.assert_allclose(d.cov, c0 + c1)  # subtraction still ADDS covariance

    shift = np.arange(4.0)
    shifted = n0 + randvars.Constant(shift)
    np.testing.assert_allclose(shifted.mean, m0 + shift)
    np.testing.assert_allclose(shifted.cov, c0)

    with pytest.raises(ValueError):
        _ = n0 + randvars.Normal(rng.normal(size=5), _spd(rng, 5))


def test_normal_scalar_scaling_edge_cases():
    """Scalar scaling propagates mean/cov^2; multiplying by zero collapses to a Constant."""
    rng = np.random.default_rng(4)
    mean = rng.normal(size=3)
    cov = _spd(rng, 3)
    rv = randvars.Normal(mean, cov)

    scaled = 2.0 * rv
    np.testing.assert_allclose(scaled.mean, 2.0 * mean)
    np.testing.assert_allclose(scaled.cov, 4.0 * cov)

    zeroed = 0.0 * rv
    assert isinstance(zeroed, randvars.Constant)
    np.testing.assert_allclose(zeroed.mean, np.zeros(3))

    with pytest.raises(ZeroDivisionError):
        _ = rv / randvars.Constant(0.0)


def test_normal_affine_matrix_transform_vector_case():
    """Left/right matrix multiplication of a multivariate Normal transforms mean and covariance."""
    rng = np.random.default_rng(5)
    mean = rng.normal(size=3)
    cov = _spd(rng, 3)
    rv = randvars.Normal(mean, cov)
    a = rng.normal(size=(2, 3))

    left = randvars.Constant(a) @ rv
    assert left.shape == (2,)
    np.testing.assert_allclose(left.mean, a @ mean)
    np.testing.assert_allclose(left.cov, a @ cov @ a.T, atol=1e-10)

    b = rng.normal(size=(3, 4))
    right = rv @ randvars.Constant(b)
    assert right.shape == (4,)
    np.testing.assert_allclose(right.mean, mean @ b)
    np.testing.assert_allclose(right.cov, b.T @ cov @ b, atol=1e-10)


def test_symmetric_kronecker_normal_samples_are_symmetric():
    """A Normal with a SymmetricKronecker (identical-factor) covariance draws symmetric-matrix samples."""
    rng = np.random.default_rng(6)
    n = 3
    a = _spd(rng, n)
    rv = randvars.Normal(
        mean=np.eye(n), cov=linops.SymmetricKronecker(A=a)
    )

    samples = rv.sample(rng, size=20)
    assert samples.shape == (20, n, n)
    for mat in samples:
        np.testing.assert_allclose(mat, mat.T, atol=1e-8)


def test_normal_indexing_marginalizes_distribution():
    """Indexing a multivariate Normal yields the correctly marginalized sub-distribution."""
    rng = np.random.default_rng(7)
    mean = rng.normal(size=6)
    cov = _spd(rng, 6)
    rv = randvars.Normal(mean, cov)

    scalar = rv[2]
    assert scalar.shape == ()
    np.testing.assert_allclose(scalar.mean, mean[2])
    np.testing.assert_allclose(scalar.cov, cov[2, 2])

    sl = rv[1:4]
    assert sl.shape == (3,)
    np.testing.assert_allclose(sl.mean, mean[1:4])
    np.testing.assert_allclose(sl.cov, cov[1:4, 1:4])

    idx = np.array([0, 2, 5])
    fancy = rv[idx]
    assert fancy.shape == (3,)
    np.testing.assert_allclose(fancy.mean, mean[idx])
    np.testing.assert_allclose(fancy.cov, cov[np.ix_(idx, idx)])


def test_constant_behaves_like_degenerate_distribution():
    """A Constant random variable has zero covariance and rng-independent samples equal to its support."""
    support = np.array([2.0, -3.0, 7.0])
    rv = randvars.Constant(support)

    np.testing.assert_allclose(rv.mean, support)
    np.testing.assert_array_equal(rv.cov, np.zeros((3, 3)))
    np.testing.assert_array_equal(rv.var, np.zeros(3))

    s1 = rv.sample(np.random.default_rng(0), size=(4,))
    s2 = rv.sample(np.random.default_rng(123), size=(4,))
    assert s1.shape == (4, 3)
    np.testing.assert_array_equal(s1, s2)  # independent of rng
    np.testing.assert_allclose(s1[0], support)


def test_categorical_pmf_mode_and_resample():
    """A Categorical reports the right pmf/mode, and resampling stays within the original support."""
    probs = np.array([0.1, 0.6, 0.3])
    support = np.array([10, 20, 30])
    rv = randvars.Categorical(probabilities=probs, support=support)

    np.testing.assert_allclose(rv.pmf(20), 0.6)
    np.testing.assert_allclose(rv.pmf(30), 0.3)
    np.testing.assert_allclose(rv.pmf(999), 0.0)  # outside support
    assert rv.mode == 20

    resampled = rv.resample(np.random.default_rng(0))
    assert isinstance(resampled, randvars.Categorical)
    # Resampling yields a uniform empirical distribution over a subset of the original support.
    probs = resampled.probabilities
    np.testing.assert_allclose(probs, np.full(probs.shape, 1.0 / probs.size))
    assert set(resampled.support.tolist()).issubset(set(support.tolist()))


def test_asrandvar_dispatches_by_input_type():
    """``asrandvar`` converts plain values to Constants and scipy frozen distributions to Normals."""
    const = randvars.asrandvar(np.array([1.0, 2.0]))
    assert isinstance(const, randvars.Constant)
    np.testing.assert_allclose(const.support, [1.0, 2.0])

    from_scipy = randvars.asrandvar(scipy.stats.norm(loc=3.0, scale=2.0))
    assert isinstance(from_scipy, randvars.Normal)
    assert from_scipy.mean == pytest.approx(3.0)
    assert from_scipy.var == pytest.approx(4.0)

    existing = randvars.Normal(0.0, 1.0)
    assert randvars.asrandvar(existing) is existing
