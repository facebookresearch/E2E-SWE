"""User-facing tests for probnum random processes and covariance functions.

Covers the covariance-function (kernel) library against explicit closed-form
formulas (ExpQuad, Matern half-integers, Linear, Polynomial, RatQuad, WhiteNoise),
Gram-matrix symmetry/PSD, and Gaussian-process marginals/sampling.
"""
import numpy as np
import pytest

from probnum.randprocs import GaussianProcess
from probnum.randprocs import covfuncs
from probnum.functions import Zero


def test_expquad_matches_closed_form():
    """The ExpQuad Gram matrix equals exp(-r^2 / (2 l^2)) with unit diagonal."""
    xs = np.linspace(0.0, 1.0, 6).reshape(-1, 1)
    lengthscale = 0.3
    k = covfuncs.ExpQuad((1,), lengthscales=lengthscale)
    gram = k.matrix(xs)

    sqdist = (xs - xs.T) ** 2
    expected = np.exp(-sqdist / (2 * lengthscale**2))
    np.testing.assert_allclose(gram, expected)
    np.testing.assert_allclose(np.diag(gram), np.ones(6))


def test_matern_half_integer_formulas():
    """Matern kernels at nu = 1/2, 3/2, 5/2 match their closed-form half-integer expressions."""
    xs = np.linspace(0.0, 2.0, 5).reshape(-1, 1)
    l = 0.7
    r = np.abs(xs - xs.T)

    k_half = covfuncs.Matern((1,), nu=0.5, lengthscales=l).matrix(xs)
    np.testing.assert_allclose(k_half, np.exp(-r / l))

    k_32 = covfuncs.Matern((1,), nu=1.5, lengthscales=l).matrix(xs)
    s3 = np.sqrt(3.0) * r / l
    np.testing.assert_allclose(k_32, (1 + s3) * np.exp(-s3))

    k_52 = covfuncs.Matern((1,), nu=2.5, lengthscales=l).matrix(xs)
    s5 = np.sqrt(5.0) * r / l
    np.testing.assert_allclose(k_52, (1 + s5 + 5 * r**2 / (3 * l**2)) * np.exp(-s5))


def test_linear_and_polynomial_kernels():
    """Linear and Polynomial kernels equal the dot-product and its shifted power."""
    rng = np.random.default_rng(0)
    xs = rng.normal(size=(5, 3))

    lin = covfuncs.Linear((3,), constant=2.0).matrix(xs)
    np.testing.assert_allclose(lin, xs @ xs.T + 2.0)

    poly = covfuncs.Polynomial((3,), constant=1.0, exponent=3).matrix(xs)
    np.testing.assert_allclose(poly, (xs @ xs.T + 1.0) ** 3)


def test_ratquad_formula_and_expquad_limit():
    """RatQuad equals (1 + r^2/(2 a l^2))^-a and approaches ExpQuad as alpha grows."""
    xs = np.linspace(0.0, 1.5, 5).reshape(-1, 1)
    l, alpha = 0.5, 3.0
    rq = covfuncs.RatQuad((1,), lengthscale=l, alpha=alpha).matrix(xs)
    r2 = (xs - xs.T) ** 2
    np.testing.assert_allclose(rq, (1 + r2 / (2 * alpha * l**2)) ** (-alpha))

    rq_big = covfuncs.RatQuad((1,), lengthscale=l, alpha=1e8).matrix(xs)
    eq = covfuncs.ExpQuad((1,), lengthscales=l).matrix(xs)
    np.testing.assert_allclose(rq_big, eq, atol=1e-4)


def test_whitenoise_kernel_is_diagonal():
    """WhiteNoise contributes sigma^2 on coincident inputs and zero off-diagonal."""
    xs = np.linspace(0.0, 1.0, 4).reshape(-1, 1)
    sigma_sq = 2.5
    k = covfuncs.WhiteNoise((1,), sigma_sq=sigma_sq)
    np.testing.assert_allclose(k.matrix(xs), sigma_sq * np.eye(4))


def test_gram_matrices_are_symmetric_and_psd():
    """Mercer kernels produce symmetric, positive-semidefinite Gram matrices."""
    rng = np.random.default_rng(1)
    xs = rng.normal(size=(8, 2))
    for k in (
        covfuncs.ExpQuad((2,), lengthscales=0.8),
        covfuncs.Matern((2,), nu=1.5, lengthscales=0.5),
        covfuncs.RatQuad((2,), lengthscale=1.0, alpha=2.0),
    ):
        gram = k.matrix(xs)
        np.testing.assert_allclose(gram, gram.T, atol=1e-10)
        assert np.min(np.linalg.eigvalsh(gram)) >= -1e-8


def test_gaussian_process_marginal_is_normal_with_kernel_covariance():
    """Evaluating a GP at inputs yields a Normal with mean=mean(x) and covariance=Gram matrix."""
    from probnum import randvars

    k = covfuncs.ExpQuad((1,), lengthscales=0.5)
    gp = GaussianProcess(mean=Zero((1,)), cov=k)
    xs = np.linspace(-1.0, 1.0, 7).reshape(-1, 1)

    marginal = gp(xs)
    assert isinstance(marginal, randvars.Normal)
    np.testing.assert_allclose(marginal.mean, np.zeros(7))
    np.testing.assert_allclose(marginal.cov, k.matrix(xs))
    np.testing.assert_allclose(gp.var(xs), np.diag(k.matrix(xs)))
    np.testing.assert_allclose(gp.std(xs), np.sqrt(np.diag(k.matrix(xs))))


def test_gaussian_process_sampling_shapes():
    """GP sampling at given inputs produces correctly shaped, reproducible draws."""
    k = covfuncs.ExpQuad((1,), lengthscales=0.5)
    gp = GaussianProcess(mean=Zero((1,)), cov=k)
    xs = np.linspace(-1.0, 1.0, 5).reshape(-1, 1)

    s_single = gp.sample(np.random.default_rng(0), xs)
    assert s_single.shape == (5,)
    s_batch = gp.sample(np.random.default_rng(0), xs, size=(3,))
    assert s_batch.shape == (3, 5)
    # Reproducible with the same seed.
    np.testing.assert_allclose(s_single, gp.sample(np.random.default_rng(0), xs))


def test_kernel_matrix_and_diagonal_conventions():
    """``k.matrix`` produces the cross/Gram matrix; ``k(x, None)`` reduces to the diagonal."""
    xs = np.linspace(0.0, 1.0, 6).reshape(-1, 1)
    ys = np.linspace(0.0, 1.0, 4).reshape(-1, 1)
    k = covfuncs.ExpQuad((1,), lengthscales=0.4)

    # Two-argument Gram matrix between distinct input sets.
    cross = k.matrix(xs, ys)
    assert cross.shape == (6, 4)
    np.testing.assert_allclose(cross, np.exp(-((xs - ys.T) ** 2) / (2 * 0.4**2)))

    # Calling with x1 omitted yields the marginal (diagonal) values.
    diag = k(xs, None)
    assert diag.shape == (6,)
    np.testing.assert_allclose(diag, np.ones(6))
