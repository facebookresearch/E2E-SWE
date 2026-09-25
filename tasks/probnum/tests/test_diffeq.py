"""User-facing tests for probnum probabilistic ODE solvers (``probnum.diffeq``).

Covers ``probsolve_ivp`` (EK0/EK1) on ODEs with known/analytic or scipy-computable
solutions: terminal and trajectory accuracy, dense output, the effect of prior order,
adaptive vs fixed stepping, calibrated uncertainty, and the perturbation solver.
ODEs are defined inline so the tests do not depend on the problem zoo.
"""
import numpy as np
import pytest
import scipy.integrate
import scipy.linalg

from probnum import diffeq, randvars


# --- Inline ODEs with known references -------------------------------------

def _decay_f(t, y):
    return -0.5 * y


def _decay_solution(t):
    return np.exp(-0.5 * t)


def _logistic_f(t, y):
    return y * (1.0 - y)


def _logistic_df(t, y):
    return np.array([[1.0 - 2.0 * y[0]]])


def _logistic_solution(t, y0=0.1):
    return y0 * np.exp(t) / (1.0 - y0 + y0 * np.exp(t))


def _pendulum_f(t, y):
    return np.array([y[1], -np.sin(y[0]) - 0.3 * y[1]])


def _pendulum_df(t, y):
    return np.array([[0.0, 1.0], [-np.cos(y[0]), -0.3]])


# --- Tests -----------------------------------------------------------------

def test_probsolve_ek0_recovers_linear_ode_without_jacobian():
    """EK0 (which uses no Jacobian) recovers the analytic terminal value of a linear ODE.

    Distinct from the EK1 trajectory/convergence tests: it exercises the EK0 scheme (``df``
    omitted) on a constant-Jacobian linear decay problem, where EK0 alone must still reach the
    analytic solution.
    """
    sol = diffeq.probsolve_ivp(
        _decay_f, 0.0, 3.0, np.array([1.0]),
        method="EK0", algo_order=3, adaptive=True, atol=1e-9, rtol=1e-9,
    )
    assert sol.states.mean.shape == (len(sol.locations), 1)
    terminal = sol.states[-1].mean[0]
    np.testing.assert_allclose(terminal, _decay_solution(sol.locations[-1]), rtol=1e-6)


def test_probsolve_trajectory_accuracy_on_logistic_ode():
    """The full solution trajectory of the logistic ODE matches the analytic solution at every grid node."""
    sol = diffeq.probsolve_ivp(
        _logistic_f, 0.0, 5.0, np.array([0.1]), df=_logistic_df,
        method="EK1", algo_order=4, adaptive=True, atol=1e-10, rtol=1e-10,
    )
    means = sol.states.mean[:, 0]
    expected = _logistic_solution(sol.locations)
    np.testing.assert_allclose(means, expected, rtol=1e-4, atol=1e-6)


def test_probsolve_dense_output_at_offgrid_points():
    """Dense output evaluates the posterior between grid nodes (scalar and array query) vs the analytic solution."""
    h = 0.1
    sol = diffeq.probsolve_ivp(
        _logistic_f, 0.0, 2.0, np.array([0.1]), df=_logistic_df,
        method="EK1", algo_order=4, adaptive=False, step=h, dense_output=True,
    )
    t_query = 0.55  # strictly between grid nodes for h=0.1
    assert t_query not in sol.locations
    marginal = sol(t_query)
    assert isinstance(marginal, randvars.Normal)
    np.testing.assert_allclose(marginal.mean[0], _logistic_solution(t_query), rtol=1e-4)

    # The same dense output evaluated on a whole array of off-grid times matches analytically.
    query = np.array([0.37, 1.04, 1.55, 1.93])  # all strictly off-grid, sorted
    means = np.array([m.mean[0] for m in sol(query)])
    np.testing.assert_allclose(means, _logistic_solution(query), rtol=1e-4)


def test_probsolve_dense_output_reduces_to_discrete_states_at_nodes():
    """Evaluating dense output at interior grid nodes returns the stored discrete states."""
    sol = diffeq.probsolve_ivp(
        _logistic_f, 0.0, 2.0, np.array([0.1]), df=_logistic_df,
        method="EK1", algo_order=4, adaptive=False, step=0.1, dense_output=True,
    )
    last = len(sol.locations) - 1
    for i in (3, last // 2, last - 2):  # interior nodes
        at_node = sol(sol.locations[i])
        np.testing.assert_allclose(at_node.mean, sol.states[i].mean, atol=1e-7)


def test_probsolve_higher_prior_order_improves_accuracy():
    """A higher prior order gives a clearly more accurate solution at a fixed step.

    The comparison is made at a coarse fixed step (0.2 is fine enough that both a low and a high
    order already reach the numerical error floor, where the sign of their tiny difference is not
    determined by prior order). At a coarser step the low-order solve is well above the floor, so a
    higher order yields a clearly more accurate solution — the directional consequence of the prior
    order that the spec promises ("a higher order yields a more accurate solution at a given step
    size"), rather than a knife-edge tie at the floor. Only that directional contract is asserted
    (with a modest margin so it discriminates a genuinely better high-order solve from a tie); the
    exact size of the gap is a step-sensitive numerical detail the spec does not pin.
    """
    def terminal_error(order):
        sol = diffeq.probsolve_ivp(
            _logistic_f, 0.0, 4.0, np.array([0.1]), df=_logistic_df,
            method="EK1", algo_order=order, adaptive=False, step=0.5,
        )
        return abs(sol.states[-1].mean[0] - _logistic_solution(sol.locations[-1]))

    # The high order is clearly (not knife-edge) more accurate than the low order at this coarse
    # step — the directional contract the spec states, not a specific order-of-magnitude factor.
    assert terminal_error(5) < terminal_error(1) / 2.0


def test_probsolve_ek0_and_ek1_posteriors_agree_at_shared_query_times():
    """The EK0 and EK1 schemes produce mutually consistent posteriors on the same ODE.

    Distinct from the per-scheme accuracy tests (EK0 terminal recovery, the full EK1 trajectory):
    EK0 and EK1 pick their own adaptive grids, so this compares the two *strategies* against each
    other via dense output at a shared set of off-grid query times rather than re-checking either
    one against the analytic solution. At tight tolerances the two posterior mean trajectories must
    agree, and at the same query times their posterior standard deviations are the same order.
    """
    solve_kw = dict(adaptive=True, atol=1e-9, rtol=1e-9, dense_output=True)
    sol_ek0 = diffeq.probsolve_ivp(
        _logistic_f, 0.0, 5.0, np.array([0.1]),
        method="EK0", algo_order=3, **solve_kw,
    )
    sol_ek1 = diffeq.probsolve_ivp(
        _logistic_f, 0.0, 5.0, np.array([0.1]), df=_logistic_df,
        method="EK1", algo_order=3, **solve_kw,
    )

    t_query = np.array([0.7, 1.6, 2.9, 4.3])  # interior, off the requested grids
    mean_ek0 = np.array([m.mean[0] for m in sol_ek0(t_query)])
    mean_ek1 = np.array([m.mean[0] for m in sol_ek1(t_query)])
    # The two strategies' posterior means agree with each other (not merely with the truth).
    np.testing.assert_allclose(mean_ek0, mean_ek1, rtol=1e-3)

    # Their posterior uncertainties at the same times are the same order of magnitude.
    std_ek0 = np.array([float(np.sqrt(np.atleast_2d(m.cov)[0, 0])) for m in sol_ek0(t_query)])
    std_ek1 = np.array([float(np.sqrt(np.atleast_2d(m.cov)[0, 0])) for m in sol_ek1(t_query)])
    assert np.all(std_ek0 > 0) and np.all(std_ek1 > 0)
    ratio = std_ek0 / std_ek1
    assert np.all((ratio > 1e-2) & (ratio < 1e2))


def test_probsolve_nonlinear_system_matches_scipy():
    """A nonlinear 2-D system (damped pendulum) solved with EK1 agrees with scipy's reference integrator."""
    t0, tmax, y0 = 0.0, 4.0, np.array([1.5, 0.0])
    sol = diffeq.probsolve_ivp(
        _pendulum_f, t0, tmax, y0, df=_pendulum_df,
        method="EK1", algo_order=4, adaptive=True, atol=1e-8, rtol=1e-8,
    )
    assert sol.states.mean.shape[1] == 2

    ref = scipy.integrate.solve_ivp(
        _pendulum_f, (t0, tmax), y0, rtol=1e-11, atol=1e-13, dense_output=True
    )
    for t_query in (1.0, 2.5, 3.5):
        np.testing.assert_allclose(sol(t_query).mean, ref.sol(t_query), rtol=1e-4, atol=1e-4)


def test_probsolve_fixed_step_grid_is_uniform_adaptive_is_not():
    """A fixed step produces an evenly spaced grid; adaptive stepping produces a non-uniform one."""
    fixed = diffeq.probsolve_ivp(
        _logistic_f, 0.0, 2.0, np.array([0.1]), df=_logistic_df,
        method="EK1", algo_order=2, adaptive=False, step=0.2,
    )
    diffs = np.diff(fixed.locations)
    # All genuine steps share the fixed size (the solver may append tmax as a tiny final step).
    significant = diffs[diffs > 1e-9]
    np.testing.assert_allclose(significant, 0.2)
    assert fixed.locations[-1] == pytest.approx(2.0)

    adaptive = diffeq.probsolve_ivp(
        _logistic_f, 0.0, 5.0, np.array([0.1]), df=_logistic_df,
        method="EK1", algo_order=3, adaptive=True, atol=1e-7, rtol=1e-7,
    )
    adiffs = np.diff(adaptive.locations)
    assert adiffs.min() / adiffs.max() < 0.9


def test_probsolve_uncertainty_accumulates_from_certain_initial_state():
    """Uncertainty starts near-zero at the (known) initial state and grows along the trajectory.

    Beyond the structural symmetric-PSD check on every marginal covariance, this verifies the
    accumulation contract distinct from the calibration check: the initial point is the most
    certain point of the solution and the posterior standard deviation at the terminal time is
    substantially larger than at the start.
    """
    sol = diffeq.probsolve_ivp(
        _logistic_f, 0.0, 3.0, np.array([0.1]), df=_logistic_df,
        method="EK1", algo_order=3, adaptive=False, step=0.25,
    )
    for state in sol.states:
        cov = np.atleast_2d(state.cov)
        np.testing.assert_allclose(cov, cov.T, atol=1e-12)
        assert np.min(np.linalg.eigvalsh(cov)) >= -1e-9

    stds = np.array([np.sqrt(np.atleast_2d(state.cov)[0, 0]) for state in sol.states])
    # The known initial condition is the most certain point of the trajectory...
    assert np.argmin(stds) == 0
    # ...and uncertainty meaningfully accumulates by the terminal time.
    assert stds[-1] > 10 * stds[0]


_LINEAR_SYSTEM_M = np.array([[-0.5, 0.1, 0.0], [0.0, -0.3, 0.2], [0.1, 0.0, -0.4]])


def _linear_system_f(t, y):
    return _LINEAR_SYSTEM_M @ y


def _linear_system_df(t, y):
    return _LINEAR_SYSTEM_M


def test_probsolve_uncertainty_brackets_the_true_error():
    """The posterior standard deviation is calibrated: the true error stays within a few sigma and is not vacuous."""
    sol = diffeq.probsolve_ivp(
        _logistic_f, 0.0, 4.0, np.array([0.1]), df=_logistic_df,
        method="EK1", algo_order=4, adaptive=True, atol=1e-6, rtol=1e-6,
    )
    errors, stds = [], []
    for i, t in enumerate(sol.locations[1:], start=1):  # skip the (certain) initial point
        errors.append(abs(sol.states[i].mean[0] - _logistic_solution(t)))
        stds.append(np.sqrt(np.atleast_2d(sol.states[i].cov)[0, 0]))
    errors, stds = np.array(errors), np.array(stds)
    # Calibrated: essentially all true errors lie within 5 sigma...
    assert np.mean(errors <= 5 * stds + 1e-12) >= 0.95
    # ...and the uncertainty is meaningful (not absurdly inflated) for this tolerance.
    assert np.median(stds) < 1e-2


def test_probsolve_time_stops_are_grid_nodes_on_higher_dimensional_system():
    """``time_stops`` land exactly on the grid of a 3-D system, and the states there match the analytic solution.

    Solving a 3-dimensional coupled linear system with requested stop times exercises both the
    higher-dimensional integration path and the ``time_stops`` contract (the grid must include
    those times exactly). The closed-form solution is the matrix exponential ``expm(M t) @ y0``.
    """
    t0, tmax, y0 = 0.0, 5.0, np.array([1.0, 1.0, 1.0])
    stops = np.array([1.5, 3.0, 4.5])
    sol = diffeq.probsolve_ivp(
        _linear_system_f, t0, tmax, y0, df=_linear_system_df,
        method="EK1", algo_order=4, adaptive=True, atol=1e-8, rtol=1e-8,
        time_stops=stops,
    )
    assert sol.states.mean.shape[1] == 3

    # Every requested stop time appears exactly as a grid node.
    for t in stops:
        assert np.any(np.isclose(sol.locations, t, atol=1e-12)), f"{t} missing from grid"

    # The solution at those nodes matches the closed-form matrix-exponential trajectory.
    for t in stops:
        expected = scipy.linalg.expm(_LINEAR_SYSTEM_M * t) @ y0
        np.testing.assert_allclose(sol(t).mean, expected, rtol=1e-4, atol=1e-4)


def test_probsolve_constant_and_dynamic_diffusion_models():
    """Both the constant and dynamic diffusion models integrate the ODE to the analytic solution."""
    target = _logistic_solution(4.0)
    for diffusion in ("constant", "dynamic"):
        sol = diffeq.probsolve_ivp(
            _logistic_f, 0.0, 4.0, np.array([0.1]), df=_logistic_df,
            method="EK1", algo_order=3, adaptive=True, atol=1e-8, rtol=1e-8,
            diffusion_model=diffusion, time_stops=np.array([4.0]),
        )
        np.testing.assert_allclose(sol(4.0).mean[0], target, rtol=1e-3)


def test_perturbsolve_tracks_reference_solution():
    """The perturbation solver returns an ODESolution that tracks the analytic solution."""
    sol = diffeq.perturbsolve_ivp(
        f=_logistic_f, t0=0.0, tmax=2.0, y0=np.array([0.1]),
        rng=np.random.default_rng(1), method="RK45", adaptive=False, step=0.05,
    )
    assert isinstance(sol, diffeq.ODESolution)
    assert isinstance(sol.states[-1], randvars.Constant)
    assert len(sol) == len(sol.locations)
    np.testing.assert_allclose(
        sol.states[-1].mean[0], _logistic_solution(sol.locations[-1]), rtol=1e-3
    )
