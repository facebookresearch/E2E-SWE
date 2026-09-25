"""User-facing tests for probnum Bayesian filtering/smoothing (``probnum.filtsmooth``).

Covers the top-level ``filter_kalman`` / ``smooth_rts`` on linear-Gaussian state-space
models: exactness against a from-scratch textbook Kalman filter, the smoother reducing
uncertainty relative to the filter, latent-trajectory recovery, RMSE ordering, dense
output / extrapolation behaviour, and input validation.
"""
import numpy as np
import pytest

from probnum import filtsmooth, randvars


# A small linear-Gaussian state-space model (discrete-time).
_F = np.array([[1.0, 0.3], [0.0, 1.0]])          # state transition
_L = np.array([[0.02, 0.0], [0.0, 0.05]])        # process-noise covariance
_H = np.array([[1.0, 0.0]])                       # observe the first coordinate
_R = np.array([[0.15]])                           # measurement-noise covariance
_M0 = np.array([0.0, 1.0])                        # initial mean
_C0 = np.eye(2)                                   # initial covariance


def _textbook_kalman_filter(observations):
    """Standard Kalman filter; probnum does an update-only step at the first location."""
    m, p = _M0.copy(), _C0.copy()
    means, covs = [], []
    for k, y in enumerate(observations):
        if k > 0:  # predict (no predict before the first observation)
            m = _F @ m
            p = _F @ p @ _F.T + _L
        s = _H @ p @ _H.T + _R
        gain = p @ _H.T @ np.linalg.inv(s)
        m = m + gain @ (y - _H @ m)
        p = (np.eye(2) - gain @ _H) @ p
        means.append(m.copy())
        covs.append(p.copy())
    return np.array(means), np.array(covs)


def _simulate(rng, n):
    """Simulate a latent trajectory and noisy position observations."""
    x = _M0.copy()
    states, obs = [], []
    for k in range(n):
        if k > 0:
            x = _F @ x + rng.multivariate_normal(np.zeros(2), _L)
        states.append(x.copy())
        obs.append(_H @ x + rng.multivariate_normal(np.zeros(1), _R))
    return np.array(states), np.array(obs)


def test_kalman_filter_matches_textbook_implementation():
    """probnum's discrete Kalman filter reproduces a from-scratch textbook filter to machine precision."""
    rng = np.random.default_rng(0)
    n = 12
    observations = rng.normal(size=(n, 1))
    locations = np.arange(n, dtype=float)

    posterior = filtsmooth.filter_kalman(
        observations, locations, _F, _L, _H, _R, _M0, _C0, prior_model="discrete"
    )
    ref_means, ref_covs = _textbook_kalman_filter(observations)

    np.testing.assert_allclose(posterior.states.mean, ref_means, atol=1e-9)
    np.testing.assert_allclose(posterior.states.cov, ref_covs, atol=1e-9)


def test_smoother_reduces_uncertainty_relative_to_filter():
    """RTS smoothing never increases, and strictly decreases at interior nodes, the marginal covariance trace."""
    rng = np.random.default_rng(1)
    n = 15
    observations = rng.normal(size=(n, 1))
    locations = np.arange(n, dtype=float)

    filtered = filtsmooth.filter_kalman(
        observations, locations, _F, _L, _H, _R, _M0, _C0, prior_model="discrete"
    )
    smoothed = filtsmooth.smooth_rts(
        observations, locations, _F, _L, _H, _R, _M0, _C0, prior_model="discrete"
    )

    filt_traces = np.array([np.trace(c) for c in filtered.states.cov])
    smooth_traces = np.array([np.trace(c) for c in smoothed.states.cov])

    assert np.all(smooth_traces <= filt_traces + 1e-9)
    assert smooth_traces[n // 2] < filt_traces[n // 2]
    # The last node coincides between filter and smoother.
    np.testing.assert_allclose(smooth_traces[-1], filt_traces[-1], atol=1e-9)


def test_filter_recovers_latent_trajectory():
    """Filtering noisy observations recovers the latent state within a reasonable error bound."""
    rng = np.random.default_rng(2)
    n = 200
    latent, observations = _simulate(rng, n)
    locations = np.arange(n, dtype=float)

    posterior = filtsmooth.filter_kalman(
        observations, locations, _F, _L, _H, _R, _M0, _C0, prior_model="discrete"
    )
    est = posterior.states.mean[:, 0]
    filt_rmse = np.sqrt(np.mean((est - latent[:, 0]) ** 2))
    obs_rmse = np.sqrt(np.mean((observations[:, 0] - latent[:, 0]) ** 2))
    assert filt_rmse < obs_rmse


def test_smoothing_beats_filtering_in_rmse():
    """The smoothed estimate has lower trajectory RMSE than the filtered estimate."""
    rng = np.random.default_rng(3)
    n = 200
    latent, observations = _simulate(rng, n)
    locations = np.arange(n, dtype=float)

    filtered = filtsmooth.filter_kalman(
        observations, locations, _F, _L, _H, _R, _M0, _C0, prior_model="discrete"
    )
    smoothed = filtsmooth.smooth_rts(
        observations, locations, _F, _L, _H, _R, _M0, _C0, prior_model="discrete"
    )
    filt_rmse = np.sqrt(np.mean((filtered.states.mean[:, 0] - latent[:, 0]) ** 2))
    smooth_rmse = np.sqrt(np.mean((smoothed.states.mean[:, 0] - latent[:, 0]) ** 2))
    assert smooth_rmse < filt_rmse


def test_posterior_dense_output_and_extrapolation_contracts():
    """Dense output returns discrete states at nodes, interpolates between them, and rejects left-extrapolation."""
    rng = np.random.default_rng(4)
    n = 10
    observations = rng.normal(size=(n, 1))
    locations = np.linspace(0.0, 9.0, n)

    smoothed = filtsmooth.smooth_rts(
        observations, locations, _F, _L, _H, _R, _M0, _C0, prior_model="discrete"
    )

    at_node = smoothed(locations[3])
    np.testing.assert_allclose(at_node.mean, smoothed.states[3].mean, atol=1e-9)

    interior = smoothed((locations[3] + locations[4]) / 2)
    assert isinstance(interior, randvars.Normal)

    with pytest.raises(ValueError):
        smoothed(np.array([5.0, 1.0]))  # unsorted query times

    with pytest.raises(NotImplementedError):
        smoothed(locations[0] - 1.0)  # left-extrapolation is unsupported


def test_filter_rejects_repeating_timepoints():
    """Filtering requires strictly increasing time points."""
    observations = np.zeros((4, 1))
    locations = np.array([0.0, 1.0, 1.0, 2.0])
    with pytest.raises(ValueError):
        filtsmooth.filter_kalman(
            observations, locations, _F, _L, _H, _R, _M0, _C0, prior_model="discrete"
        )


def test_invalid_prior_model_raises():
    """An unknown ``prior_model`` string is rejected."""
    observations = np.zeros((3, 1))
    locations = np.arange(3, dtype=float)
    with pytest.raises(ValueError):
        filtsmooth.filter_kalman(
            observations, locations, _F, _L, _H, _R, _M0, _C0, prior_model="bogus"
        )
