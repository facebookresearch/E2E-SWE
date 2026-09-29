"""User-facing tests for probnum Bayesian quadrature (``probnum.quad``).

Covers ``bayesquad`` and ``bayesquad_from_data``: integrating known integrands under
Lebesgue and Gaussian measures, the calibrated Normal integral belief, variance
shrinkage with more evaluations, and input validation.
"""
import numpy as np
import pytest

from probnum import randvars
from probnum.quad import bayesquad, bayesquad_from_data
from probnum.quad.integration_measures import GaussianMeasure
from probnum.randprocs.covfuncs import ExpQuad


def test_bayesquad_integrates_constant_over_unit_box():
    """Integrating f(x)=1 over the unit interval returns a calibrated belief centred on 1."""
    integral, _ = bayesquad(
        fun=lambda x: np.ones(x.shape[0]),
        input_dim=1,
        domain=(0.0, 1.0),
        rng=np.random.default_rng(0),
    )
    assert isinstance(integral, randvars.Normal)
    assert integral.mean == pytest.approx(1.0, abs=1e-2)
    assert integral.var >= 0.0


def test_bayesquad_integrates_linear_function():
    """The integral of f(x)=x over [0, 1] is recovered as 1/2 by both BQ entry points."""
    integral, _ = bayesquad(
        fun=lambda x: x[:, 0],
        input_dim=1,
        domain=(0.0, 1.0),
        rng=np.random.default_rng(1),
    )
    assert integral.mean == pytest.approx(0.5, abs=2e-2)

    nodes = np.linspace(0.0, 1.0, 25).reshape(-1, 1)
    integral_data, info = bayesquad_from_data(
        nodes=nodes, fun_evals=nodes[:, 0], domain=(0.0, 1.0)
    )
    assert integral_data.mean == pytest.approx(0.5, abs=2e-2)
    assert info.nevals == 25


def test_bayesquad_variance_shrinks_with_more_evaluations():
    """Allocating more evaluations to BQ tightens the posterior variance of the integral."""
    integral_small, info_small = bayesquad(
        fun=lambda x: np.sin(3.0 * x[:, 0]), input_dim=1, domain=(0.0, 1.0),
        rng=np.random.default_rng(2), options=dict(max_evals=20),
    )
    integral_large, info_large = bayesquad(
        fun=lambda x: np.sin(3.0 * x[:, 0]), input_dim=1, domain=(0.0, 1.0),
        rng=np.random.default_rng(2), options=dict(max_evals=150),
    )
    assert integral_large.var < integral_small.var


def test_bayesquad_belief_is_calibrated():
    """The true integral value lies within a few posterior standard deviations of the BQ mean."""
    true_value = (np.cos(0.0) - np.cos(2.0)) / 2.0  # integral of sin(2x) over [0,1]
    integral, _ = bayesquad(
        fun=lambda x: np.sin(2.0 * x[:, 0]),
        input_dim=1,
        domain=(0.0, 1.0),
        rng=np.random.default_rng(3),
        options=dict(max_evals=100),
    )
    assert integral.std > 0.0
    assert abs(integral.mean - true_value) <= 4.0 * integral.std + 1e-3


def test_bayesquad_higher_dimensional_gaussian_moment():
    """Under a 3-D Gaussian measure, BQ of sum(x_i^2) recovers sum(mu_i^2 + sigma_i^2)."""
    import itertools

    means = np.array([0.5, -1.0, 0.0])
    variances = np.array([1.0, 0.5, 2.0])
    dim = 3
    measure = GaussianMeasure(mean=means, cov=np.diag(variances), input_dim=dim)

    gh_1d, _ = np.polynomial.hermite_e.hermegauss(7)
    grid = np.array(list(itertools.product(gh_1d, repeat=dim)))
    nodes = means + np.sqrt(variances) * grid
    fun_evals = np.sum(nodes**2, axis=1)

    integral, _ = bayesquad_from_data(nodes=nodes, fun_evals=fun_evals, measure=measure)
    np.testing.assert_allclose(integral.mean, np.sum(means**2 + variances), atol=5e-2)


def test_kernel_embedding_matches_quadrature_of_kernel_translate():
    """The kernel mean equals the BQ estimate of integrating a kernel translate k(., x0)."""
    from probnum.quad.kernel_embeddings import KernelEmbedding

    measure = GaussianMeasure(mean=0.0, cov=1.0, input_dim=1)
    kernel = ExpQuad((1,), lengthscales=1.0)
    embedding = KernelEmbedding(kernel, measure)

    x0 = np.array([[0.3]])
    analytic_mean = float(embedding.kernel_mean(x0)[0])

    nodes = np.linspace(-5.0, 5.0, 60).reshape(-1, 1)
    fun_evals = kernel.matrix(nodes, x0).ravel()
    integral, _ = bayesquad_from_data(nodes=nodes, fun_evals=fun_evals, measure=measure)
    # The spec promises the embedding is "consistent with what BQ computes when integrating a
    # kernel translate" and that BQ "recovers analytic integrals" under a Gaussian measure, while
    # leaving BQ's internal surrogate open. Both sides are computed by the implementation itself,
    # so assert a scalar Normal belief, a finite positive mean (the integrand is strictly
    # positive), and agreement with the analytic embedding in the same band the sibling
    # Gaussian-moment test uses — loose enough for any surrogate that actually fits the 60 densely
    # sampled values, tight enough to reject one that does not.
    assert isinstance(integral, randvars.Normal)
    bq_mean = float(integral.mean)
    assert np.isfinite(bq_mean)
    assert bq_mean > 0.0
    np.testing.assert_allclose(bq_mean, analytic_mean, atol=5e-2)


def test_bayesquad_requires_domain_or_measure():
    """Calling BQ without either a domain or a measure raises an error."""
    with pytest.raises(ValueError):
        bayesquad(fun=lambda x: x[:, 0], input_dim=1, rng=np.random.default_rng(0))
    with pytest.raises(ValueError):
        bayesquad_from_data(
            nodes=np.linspace(0, 1, 5).reshape(-1, 1), fun_evals=np.zeros(5)
        )
