"""User-facing tests for probnum nonlinear Bayesian filtering (EKF / UKF).

The top-level ``filter_kalman``/``smooth_rts`` handle linear-Gaussian models; nonlinear
state-space models are filtered by wrapping a nonlinear transition in an approximate
(extended/unscented Kalman) component and running the class-based ``Kalman`` estimator.
These tests exercise that path: the linearization "unlock" contract, EKF exactness on a
linear model, and trajectory recovery on a genuinely nonlinear system with EKF and UKF.
"""
import numpy as np
import pytest

from probnum import filtsmooth, problems, randprocs, randvars
from probnum.filtsmooth.gaussian import Kalman
from probnum.filtsmooth.gaussian.approx import DiscreteEKFComponent, DiscreteUKFComponent
from probnum.randprocs.markov import MarkovSequence
from probnum.randprocs.markov.discrete import LTIGaussian, NonlinearGaussian


# A scalar nonlinear growth model: x_{k+1} = x_k + 0.3*sin(x_k) + noise, observe x + noise.
def _nonlinear_dynamics(process_var=0.01):
    return NonlinearGaussian(
        input_dim=1,
        output_dim=1,
        transition_fun=lambda t, x: x + 0.3 * np.sin(x),
        transition_fun_jacobian=lambda t, x: np.array([[1.0 + 0.3 * np.cos(x[0])]]),
        noise_fun=lambda t: randvars.Normal(np.zeros(1), process_var * np.eye(1)),
    )


_MEAS_VAR = 0.05
_R = _MEAS_VAR * np.eye(1)
_INITRV = randvars.Normal(np.zeros(1), np.eye(1))


def _linear_measurement():
    return LTIGaussian(transition_matrix=np.eye(1), noise=randvars.Normal(np.zeros(1), _R))


def _simulate(rng, n, process_var=0.01):
    """Simulate the latent nonlinear trajectory and noisy observations."""
    x = np.array([0.5])
    latent, obs = [], []
    for _ in range(n):
        x = x + 0.3 * np.sin(x) + rng.multivariate_normal(np.zeros(1), process_var * np.eye(1))
        latent.append(x.copy())
        obs.append(x + rng.multivariate_normal(np.zeros(1), _R))
    return np.array(latent), np.array(obs)


def _filter(component_cls, observations, locations):
    dynamics = component_cls(_nonlinear_dynamics())
    measurement = component_cls(_linear_measurement())
    prior = MarkovSequence(transition=dynamics, initrv=_INITRV, initarg=float(locations[0]))
    rp = problems.TimeSeriesRegressionProblem(
        observations=observations,
        locations=locations,
        measurement_models=[measurement] * len(locations),
    )
    return Kalman(prior).filtsmooth(rp)


def test_nonlinear_transition_requires_linearization():
    """A raw NonlinearGaussian cannot be propagated directly; wrapping it in an EKF/UKF unlocks it."""
    dynamics = _nonlinear_dynamics()
    with pytest.raises(NotImplementedError):
        dynamics.forward_rv(_INITRV, t=0.0, dt=1.0)

    for component_cls in (DiscreteEKFComponent, DiscreteUKFComponent):
        out, _ = component_cls(dynamics).forward_rv(_INITRV, t=0.0, dt=1.0)
        assert isinstance(out, randvars.Normal)
        assert out.mean.shape == (1,)


def test_ekf_is_exact_on_a_linear_model():
    """Linearizing an already-linear model reproduces the exact linear-Gaussian prediction."""
    linear = LTIGaussian(
        transition_matrix=np.array([[1.0, 0.2], [0.0, 1.0]]),
        noise=randvars.Normal(np.zeros(2), 0.01 * np.eye(2)),
    )
    rv = randvars.Normal(np.array([1.0, -0.5]), np.eye(2))

    direct, _ = linear.forward_rv(rv, t=0.0)
    approx, _ = DiscreteEKFComponent(linear).forward_rv(rv, t=0.0)

    np.testing.assert_allclose(approx.mean, direct.mean, atol=1e-9)
    np.testing.assert_allclose(approx.cov, direct.cov, atol=1e-9)


def test_ekf_filter_recovers_nonlinear_latent_state():
    """EKF filtering of a nonlinear system estimates the latent state better than the raw observations."""
    rng = np.random.default_rng(0)
    n = 80
    latent, obs = _simulate(rng, n)
    locations = np.arange(n, dtype=float)

    posterior, _ = _filter(DiscreteEKFComponent, obs, locations)
    est = posterior.states.mean[:, 0]
    filt_rmse = np.sqrt(np.mean((est - latent[:, 0]) ** 2))
    obs_rmse = np.sqrt(np.mean((obs[:, 0] - latent[:, 0]) ** 2))
    assert filt_rmse < obs_rmse


def test_ukf_filter_recovers_nonlinear_latent_state():
    """UKF filtering of the same nonlinear system also beats the raw observations."""
    rng = np.random.default_rng(1)
    n = 80
    latent, obs = _simulate(rng, n)
    locations = np.arange(n, dtype=float)

    posterior, _ = _filter(DiscreteUKFComponent, obs, locations)
    est = posterior.states.mean[:, 0]
    filt_rmse = np.sqrt(np.mean((est - latent[:, 0]) ** 2))
    obs_rmse = np.sqrt(np.mean((obs[:, 0] - latent[:, 0]) ** 2))
    assert filt_rmse < obs_rmse


def test_nonlinear_smoothing_reduces_uncertainty():
    """RTS smoothing of the EKF posterior does not increase, and at interior nodes reduces, uncertainty."""
    rng = np.random.default_rng(2)
    n = 40
    _, obs = _simulate(rng, n)
    locations = np.arange(n, dtype=float)

    dynamics = DiscreteEKFComponent(_nonlinear_dynamics())
    measurement = DiscreteEKFComponent(_linear_measurement())
    prior = MarkovSequence(transition=dynamics, initrv=_INITRV, initarg=0.0)
    rp = problems.TimeSeriesRegressionProblem(
        observations=obs, locations=locations, measurement_models=[measurement] * n
    )
    kalman = Kalman(prior)
    filtered, _ = kalman.filter(rp)
    smoothed = kalman.smooth(filtered)

    filt_var = np.array([c[0, 0] for c in filtered.states.cov])
    smooth_var = np.array([c[0, 0] for c in smoothed.states.cov])
    assert np.all(smooth_var <= filt_var + 1e-9)
    assert smooth_var[n // 2] < filt_var[n // 2]
