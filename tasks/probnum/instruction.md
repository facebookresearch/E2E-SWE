# ProbNum — Probabilistic Numerics in Python

## What you are building

You are building **`probnum`**, a scientific-computing library whose theme is *quantifying
uncertainty in numerical computation*. Where an ordinary numerical routine returns a single
answer (the solution of a linear system, the trajectory of an ODE, the value of an integral),
ProbNum's routines return a **probability distribution over the answer** — a best estimate
together with a calibrated measure of how uncertain that estimate is.

To make that possible the library has two layers:

* **Building blocks** — *random variables* (values bundled with uncertainty), *linear
  operators* (matrices that may be represented implicitly/lazily), *functions*, and
  *covariance functions / Gaussian processes*.
* **Solvers** that consume and produce those building blocks — a *probabilistic linear
  solver*, *probabilistic ODE solvers*, *Bayesian quadrature*, and *Bayesian filtering and
  smoothing*.

A reader should be able to do realistic things like: build a Gaussian random variable and
transform it, solve `Ax = b` and ask how confident the solver is, integrate an ODE and read
off the uncertainty of the trajectory, estimate an integral, or run a Kalman filter over noisy
measurements.

This document describes the **public behaviour** your implementation must provide. You are free
to organise the internals however you like, as long as the import paths and observable
behaviour below are matched exactly.

## Dependencies and packaging

* The only third-party libraries you need are **NumPy** and **SciPy**. Both are already
  installed in this environment — do not try to install anything (there is no network access).
* Ship the project as an installable Python package named **`probnum`** with a standard
  `pyproject.toml` / `setup.py`, so it can be installed in editable mode
  (`pip install -e .`). The top-level import is `import probnum`.
* Random sampling everywhere uses NumPy's modern generator API: methods that draw samples take
  a `numpy.random.Generator` (as produced by `numpy.random.default_rng(...)`).

The package is organised into the submodules described below. The import paths shown are part
of the contract — use them exactly.

---

## 1. Random variables — `probnum.randvars`

Import as `from probnum import randvars`.

A **random variable** represents an uncertain quantity. The shared base class is
`randvars.RandomVariable` (used for `isinstance` checks). Every random variable exposes, where
they are defined, the moment properties `.mean`, `.cov`, `.var`, `.std`, plus `.mode` and
`.median`, and a `.sample(rng, size=())` method whose output has shape `size + rv.shape`.

A subtle but important shape convention: for a length-`n` (multivariate) random variable,
`.mean`, `.var` and `.std` have shape `(n,)`, but `.cov` is the full `(n, n)` covariance
matrix. For a scalar random variable `.cov` is a scalar (shape `()`).

### `randvars.Normal(mean, cov, cov_cholesky=None)`

A Gaussian random variable. It must support several regimes selected by the shapes of its
arguments:

* **Univariate** — scalar `mean` and scalar variance `cov`. Here the full scalar distribution
  surface is available and must agree with the corresponding `scipy.stats.norm`: `.pdf(x)`,
  `.cdf(x)`, `.logpdf(x)`, `.quantile(p)`, and the moments `.mean`, `.var`, `.std`,
  `.median` (= mean), `.mode` (= mean).
* **Multivariate** — vector `mean` of shape `(n,)` and covariance `cov` of shape `(n, n)`.
  `.var` equals the diagonal of the covariance and `.std` its square root. `.quantile` and
  `.median` are only meaningful for scalar variables and need not work here.
* **Matrix-variate / operator-structured** — `mean` may be a matrix and `cov` may be a
  *linear operator* (see §2), e.g. a `linops.SymmetricKronecker`. When the covariance is a
  symmetric-Kronecker operator built from a single factor, the random variable describes a
  random *symmetric matrix*, and its samples must come out symmetric.

Other required behaviour:

* **Covariance Cholesky factor.** A Normal exposes a lower-triangular factor `L` of its
  covariance via `.cov_cholesky` (so that `L @ L.T` reconstructs the covariance), computed
  lazily on first access. A boolean `.cov_cholesky_is_precomputed` reports whether the factor
  has been computed yet (it flips to `True` after the factor is accessed, and is `True`
  immediately if a `cov_cholesky` was supplied to the constructor). `.precompute_cov_cholesky(
  damping_factor=None)` forces the computation; with a damping factor it factorises
  `cov + damping_factor * I` instead. Calling `precompute_cov_cholesky` a second time (when the
  factor already exists) raises an exception.
* **Indexing marginalises.** Indexing a multivariate Normal with an integer, a slice, or an
  integer array returns the corresponding marginal Normal: its mean is the indexed mean and its
  covariance is the correspondingly indexed sub-block of the covariance matrix. An integer index
  yields a scalar Normal.
* **Arithmetic.** Normals support natural arithmetic, with the following conventions:
  * `N0 + N1` and `N0 - N1` add/subtract the means; **both** add the covariances
    (subtraction of two independent Gaussians still *adds* their covariances). Adding/subtracting
    Normals of incompatible shapes raises `ValueError`.
  * Adding or subtracting a `Constant` (see below) shifts the mean and leaves the covariance
    unchanged.
  * Multiplying by a scalar `c` scales the mean by `c` and the covariance by `c**2`. Multiplying
    by `0` collapses the variable to a `Constant` of zeros. Dividing by a `Constant` of value 0
    raises `ZeroDivisionError`.
  * Left/right matrix multiplication by a deterministic matrix (a `Constant` wrapping a matrix,
    or a linear operator) applies the affine transform to the distribution: `A @ N` has mean
    `A @ mean` and covariance `A @ cov @ A.T`; `N @ B` transforms correspondingly on the right.

### `randvars.Constant(support)`

A degenerate ("certain") random variable concentrated on a single value `support`. Its `.mean`
equals the support, its `.cov` and `.var` are all zeros, and `.sample(rng, size=...)` returns
copies of the support tiled to the requested shape — independent of the generator. For a scalar
support, `.median` equals the value.

### `randvars.Categorical(probabilities, support=None)`

A discrete random variable over a finite set. `support` defaults to `0, 1, ..., k-1`. It
provides `.probabilities`, `.support`, a probability-mass function `.pmf(x)` (the probability of
`x`, or `0.0` if `x` is not in the support), `.mode` (the support entry with the highest
probability), and `.resample(rng)`, which draws a new equally-weighted empirical sample: the
result is another `Categorical` whose support is a subset of the original support and whose
probabilities are uniform.

### `randvars.asrandvar(obj)`

A convenience converter: plain numbers/arrays become a `Constant`; a frozen `scipy.stats`
distribution (e.g. `scipy.stats.norm(...)`) becomes the matching `Normal` (with the same mean and
variance); an object that is already a random variable is returned unchanged.

---

## 2. Linear operators — `probnum.linops`

Import as `from probnum import linops`.

A **linear operator** behaves like a matrix but may be stored implicitly so that large or
structured matrices never have to be formed densely. The shared abstraction is
`linops.LinearOperator`. Every operator must support:

* matrix multiplication with the `@` operator against vectors and matrices, **broadcasting over
  leading batch dimensions exactly like `numpy.matmul`** (e.g. applying an operator to a stack
  of matrices of shape `(..., n, k)`);
* `.todense()` to materialise the equivalent dense NumPy array;
* `.T` (transpose);
* `.inv()` (a lazy inverse operator) and `.solve(b)` for square operators;
* the scalar quantities `.det()`, `.logabsdet()`, `.trace()`, `.eigvals()`, `.rank()`,
  `.diagonal()`;
* composition and combination: `op @ op`, `op + op`, scalar `* op`, and unary negation, each of
  which must produce an operator equal (when densified) to the corresponding dense computation.

Square-only operations (`inv`, `solve`, `det`, `logabsdet`, `trace`, `eigvals`) raise
`numpy.linalg.LinAlgError` when applied to a non-square operator, matching NumPy's behaviour.
The key correctness contract throughout is that a lazy operator agrees with the equivalent dense
computation.

The concrete operators you must provide:

* **`linops.Matrix(A)`** — wraps a dense or sparse matrix `A`; densifies back to `A`.
* **`linops.Identity(n)`** — the identity; densifies to `numpy.eye(n)`, has determinant 1,
  log-abs-determinant 0, trace `n`, rank `n`, unit eigenvalues, and acts as a neutral element
  (`Identity @ op` returns `op` unchanged).
* **`linops.Scaling`** — a diagonal operator. Its first positional argument accepts *either* a
  1-D array of diagonal entries (anisotropic) *or* a single scalar (isotropic); the isotropic
  form additionally takes a `shape` and builds a scalar multiple of the identity, i.e.
  `linops.Scaling(3.0, shape=n)` is the `n×n` operator `3 * eye(n)` (the `shape` may be given as
  the integer `n` or the pair `(n, n)`). Its dense form is the corresponding diagonal matrix;
  `.diagonal()`, `.det()` (product of factors) and `.trace()` (sum of factors) follow. A scaling
  with a zero factor is singular, so `.inv()` raises `numpy.linalg.LinAlgError`.
* **`linops.Kronecker(A, B)`** — the Kronecker product `A ⊗ B`; densifies to `numpy.kron(A, B)`,
  with transpose, inverse, trace and determinant all consistent with that dense form.
* **`linops.SymmetricKronecker(A, B=None)`** — the symmetric Kronecker operator. With two
  factors it densifies to `0.5 * (kron(A, B) + kron(B, A))` and is symmetric in its two factors
  (swapping `A` and `B` gives the same operator). With a single factor (`B` omitted) it
  densifies to `kron(A, A)`.
* **`linops.IdentityKronecker(num_blocks, B)`** — equals `kron(eye(num_blocks), B)`, exposes
  `.num_blocks`, and keeps its structure under transpose and inverse.
* **`linops.Selection(indices, shape)`** — gathers the listed entries of a vector (a row-selection
  matrix). Its transpose is an **`linops.Embedding`**, which scatters values back into the larger
  space (zeros elsewhere).
* **`linops.BlockDiagonalMatrix(*blocks)`** — a block-diagonal operator built from square blocks;
  densifies to `scipy.linalg.block_diag(*blocks)`, with the corresponding determinant, inverse and
  total shape.
* **`linops.aslinop(A)`** — a converter: a NumPy array (or sparse matrix) becomes a `Matrix`; an
  object that is already a linear operator is returned unchanged.

Dtype handling should follow NumPy's promotion rules (e.g. a `Kronecker` of an integer and a
float operator has the promoted floating dtype).

---

## 3. Functions — `probnum.functions`

Import as `from probnum.functions import LambdaFunction, SumFunction, ScaledFunction, Zero`.

A **function** object is a callable with a declared `input_shape` and `output_shape` that
evaluates in a vectorised way, broadcasting over arbitrary leading batch dimensions. Calling it
on input whose trailing dimensions do not match `input_shape` raises `ValueError`.

* **`LambdaFunction(fn, input_shape, output_shape=())`** wraps a plain Python callable.
* **`Zero(input_shape, output_shape=())`** is the function that returns all zeros.
* **`SumFunction(*summands)`** is constructible directly: it takes the summand function objects
  as **positional varargs** (e.g. `SumFunction(f0, f1)`, not a single iterable of functions), and
  raises `ValueError` if their input/output shapes are incompatible.
* Functions form an algebra:
  * `f + g` and `f - g` produce a `SumFunction` that evaluates to the pointwise sum/difference.
    Chained additions/subtractions **flatten** into a single `SumFunction` whose summands are
    available via `.summands`; a subtracted term appears as a `ScaledFunction` with scalar `-1`.
    Adding the `Zero` function returns the other operand unchanged.
  * `f * c` and `c * f` produce a `ScaledFunction` with `.function` and `.scalar`; scaling an
    already-scaled function folds the scalars together rather than nesting.
  * Unary negation `-f` is supported and is equivalent to `f * -1`, producing a `ScaledFunction`
    with `.scalar == -1` (so negating then re-scaling folds the scalars rather than nesting).
  * Building a `SumFunction` from functions with incompatible shapes raises `ValueError`.

---

## 4. Random processes and covariance functions — `probnum.randprocs`

Covariance functions (kernels) live in `from probnum.randprocs import covfuncs`; the Gaussian
process is `from probnum.randprocs import GaussianProcess`.

### Covariance functions (kernels)

Each kernel is constructed with an `input_shape` (e.g. `(1,)` for scalar inputs, `(d,)` for
`d`-dimensional inputs). A kernel can be called as `k(x0, x1)` (pass `x1=None` to get the
diagonal, i.e. the values at coincident inputs), and `k.matrix(x0, x1=None)` returns the full
Gram matrix between two sets of inputs (or of a set with itself). For a set of `N` inputs the
Gram matrix has shape `(N, N)`, is symmetric, and is positive semidefinite.

The required kernels and their exact formulas (with `r = ||x0 - x1||` the Euclidean distance and
`l` the length scale) are:

* **`ExpQuad(input_shape, lengthscales=1.0)`** — the squared-exponential / RBF kernel
  `exp(-r**2 / (2 * l**2))`. Its diagonal is all ones.
* **`Matern(input_shape, nu=1.5, lengthscales=1.0)`** — the Matérn kernel. For the common
  half-integer smoothness parameters it must reduce to the closed forms
  `nu = 0.5`: `exp(-r / l)`;
  `nu = 1.5`: `(1 + sqrt(3) * r / l) * exp(-sqrt(3) * r / l)`;
  `nu = 2.5`: `(1 + sqrt(5) * r / l + 5 * r**2 / (3 * l**2)) * exp(-sqrt(5) * r / l)`.
* **`Linear(input_shape, constant=0.0)`** — `x0 . x1 + constant`.
* **`Polynomial(input_shape, constant=0.0, exponent=1.0)`** — `(x0 . x1 + constant) ** exponent`.
* **`RatQuad(input_shape, lengthscale=1.0, alpha=1.0)`** — the rational-quadratic kernel
  `(1 + r**2 / (2 * alpha * l**2)) ** (-alpha)`. As `alpha -> infinity` it approaches `ExpQuad`.
* **`WhiteNoise(input_shape, sigma_sq=1.0)`** — `sigma_sq` when the two inputs coincide and `0`
  otherwise (i.e. `sigma_sq` on the diagonal of a Gram matrix, zero off-diagonal).

### `GaussianProcess(mean, cov)`

A Gaussian process is defined by a `mean` (a function object, e.g. `Zero`) and a `cov` (a
kernel). Evaluating the process at a set of inputs `X` returns the finite-dimensional marginal as
a `randvars.Normal` whose mean is `mean(X)` and whose covariance is the kernel Gram matrix
`cov.matrix(X)`. It also provides `.mean` (the mean function), `.var(X)` (the marginal variances,
i.e. the diagonal of the Gram matrix), `.std(X)`, and `.sample(rng, X, size=())` for drawing
sample paths evaluated at `X` (shape `size + (len(X),)`, reproducible for a fixed generator
seed).

---

## 5. Probabilistic linear solver — `probnum.linalg`

Import as `from probnum.linalg import problinsolve, bayescg`.

`problinsolve(A, b, A0=None, Ainv0=None, x0=None, maxiter=None, atol=1e-6, rtol=1e-6,
calibration=None, callback=None)` solves a symmetric positive-definite system `A x = b`
*probabilistically*: rather
than a single solution it returns beliefs (random variables) over the solution, the matrix, and
its inverse. `A` may be dense, a linear operator, or a SciPy sparse matrix; `b` may be a single
right-hand side or several stacked column-wise.

It returns a 4-tuple **`(x, A_belief, Ainv_belief, info)`**:

* `x`, `A_belief`, `Ainv_belief` are all `randvars.RandomVariable`s. The posterior mean `x.mean`
  recovers the true solution (to within the requested tolerance — i.e. for a solvable SPD system
  with tight tolerances it matches `numpy.linalg.solve(A, b)`). For multiple right-hand sides
  `x` has the same shape as `b`; for a zero right-hand side the solution is zero.
* `A_belief` and `Ainv_belief` are matrix-variate Normals: their means are linear operators
  (use `.mean.todense()`), and their covariances are `SymmetricKronecker` operators exposing the
  two factors `.A` and `.B`. The inverse-belief mean is symmetric, and the covariance factors are
  symmetric and positive semidefinite. Like `x.mean`, the belief means recover `A` and its inverse
  on the solved system to within the requested tolerance (for a solvable SPD system with tight
  tolerances and enough iterations).
* `info` is a dictionary that includes at least the keys `"iter"` (iterations performed),
  `"maxiter"`, `"resid_l2norm"` (the residual norm `||A @ x.mean - b||`), and `"trace_sol_cov"`
  (which equals `x.cov.trace()`).

`problinsolve` also accepts a matrix-variate prior over the inverse via `Ainv0`, an uncertainty
`calibration` mode (e.g. `None`, `0`, `"adhoc"`, `"weightedmean"`) that still yields an accurate
solution, and a `callback` invoked once per solver iteration. The callback receives keyword
arguments describing the iteration — including the current search direction `sk` (the successive
search directions are mutually `A`-conjugate). Allowing more iterations contracts the posterior
(a smaller `info["trace_sol_cov"]`).

`bayescg(A, b)` is part of the public surface but is **not implemented** — calling it raises
`NotImplementedError`.

---

## 6. Probabilistic ODE solvers — `probnum.diffeq`

Import as `from probnum import diffeq`.

`diffeq.probsolve_ivp(f, t0, tmax, y0, df=None, method="EK0", dense_output=True, algo_order=2,
adaptive=True, atol=1e-2, rtol=1e-2, step=None, time_stops=None, diffusion_model="dynamic")`
solves the initial value
problem `y'(t) = f(t, y)`, `y(t0) = y0`, returning a *probabilistic* solution: an estimate of the
trajectory together with its uncertainty.

* `f(t, y)` returns the derivative as an array; `df(t, y)` (optional) returns the Jacobian
  matrix of `f` with respect to `y`.
* `method` selects the filtering scheme: `"EK0"` (no Jacobian needed) or `"EK1"` (which uses the
  Jacobian `df`).
* `algo_order` sets the smoothness/order of the underlying prior; a higher order yields a more
  accurate solution at a given step size.
* With `adaptive=True` the solver chooses step sizes automatically (controlled by `atol`/`rtol`),
  producing a non-uniformly spaced time grid. With `adaptive=False` you must pass a fixed `step`,
  producing an evenly spaced grid. `time_stops` lists times the grid must include exactly.
* `diffusion_model` (`"dynamic"` or `"constant"`) selects how the prior's diffusion is calibrated;
  both produce an accurate solution.

The returned solution object provides:

* `.locations` — the time grid (a sorted 1-D array).
* `.states` — the per-time-point marginals as a list-like of random variables; `.states.mean`
  has shape `(number_of_times, dimension)`, and each `.states[i]` is a `randvars.Normal` whose
  covariance is symmetric positive-semidefinite. `len(solution)` equals the number of time
  points. The supplied initial condition `y0` is essentially certain, so the first state is the
  most certain point of the solution and the marginal uncertainty accumulates away from it
  (the terminal state carries substantially more uncertainty than the initial one).
* **Calibrated uncertainty.** Beyond being positive-semidefinite and accumulating, the posterior
  standard deviation is *calibrated* to the true error: along the trajectory the true solution
  stays within a few posterior standard deviations of the posterior mean. The uncertainty is also
  scaled to the accuracy the solve actually achieves (i.e. to the requested tolerance) rather than
  left at a fixed prior scale, i.e. a meaningful, non-vacuous uncertainty rather than an inflated
  one.
* **Dense output**: calling the solution at a time, `solution(t)`, returns the marginal
  `randvars.Normal` at `t`, interpolating between grid points; evaluating exactly at a grid
  location reproduces that stored state. `t` may also be a sorted array of query times, in which
  case `solution(t)` returns a **sequence of per-time marginals**: iterating it yields one
  `randvars.Normal` per query time, in query order (each with a `.mean` of shape `(dimension,)`
  and a `.cov`). The interpolation is *not* a plain linear blend of the two bracketing grid means:
  it is the solver's own posterior between nodes, so an off-grid query returns a marginal whose
  mean tracks the true solution to the **same accuracy as the surrounding grid nodes** (i.e. to
  the solve's requested tolerance), with no extra order-of-`step` interpolation error.

The solver's mean trajectory must approximate the true ODE solution to within the requested
tolerances (matching an analytic solution or a high-accuracy reference such as
`scipy.integrate.solve_ivp`).

`diffeq.perturbsolve_ivp(f, t0, tmax, y0, rng, method="RK45", adaptive=True, atol=1e-6,
rtol=1e-3, step=None)` is a second solver that produces an uncertain solution by randomly
perturbing the steps of a classical Runge–Kutta integrator (`"RK45"`/`"RK23"`). It returns a
solution of the same family (`isinstance(sol, diffeq.ODESolution)`) whose per-step states are
`randvars.Constant`s and whose mean trajectory tracks the true solution.

---

## 7. Bayesian quadrature — `probnum.quad`

Import as `from probnum.quad import bayesquad, bayesquad_from_data`; integration measures are in
`from probnum.quad.integration_measures import GaussianMeasure`.

Bayesian quadrature estimates an integral and returns the estimate as a Gaussian belief.

* `bayesquad(fun, input_dim, domain=None, measure=None, rng=None, options=None)` integrates the
  function `fun` (which maps an array of shape `(num_points, input_dim)` to a 1-D array of
  values). Provide either a `domain` (e.g. `(0.0, 1.0)` for the unit interval, integrating
  against the uniform/Lebesgue measure) or a `measure`. It evaluates `fun` adaptively, choosing
  evaluation points itself, and returns `(integral, info)` where `integral` is a scalar
  `randvars.Normal` (with `.mean`, `.var`, `.std`) and `info` carries run metadata. Tuning knobs
  such as the evaluation budget are passed inside `options` (e.g. `options=dict(max_evals=...)`);
  giving a larger budget tightens the integral's posterior variance. The true integral lies
  within a few posterior standard deviations of the mean.
* `bayesquad_from_data(nodes, fun_evals, domain=None, measure=None)` performs the same estimate
  from precomputed evaluations: `nodes` is a 2-D array of shape `(num_points, input_dim)` and
  `fun_evals` the matching 1-D array of function values. Its `info` reports the number of
  evaluations (`info.nevals`). Under a `GaussianMeasure(mean, cov, input_dim)` this recovers
  analytic integrals — e.g. the integral of `x**2` equals `mean**2 + cov`.

Calling either entry point with neither a `domain` nor a `measure` raises an error.

A **kernel embedding** captures the integral of a covariance function against a measure:
`probnum.quad.kernel_embeddings.KernelEmbedding(kernel, measure)` exposes `kernel_mean(nodes)`
(the integral of `k(node, ·)` under the measure, for each node) — consistent with what BQ computes
when integrating a kernel translate.

---

## 8. Bayesian filtering and smoothing — `probnum.filtsmooth`

Import as `from probnum import filtsmooth`.

These routines estimate the hidden state of a linear-Gaussian state-space model from noisy
observations. Both take the same arguments:

`filter_kalman(observations, locations, F, L, H, R, m0, C0, prior_model="continuous")`
`smooth_rts (observations, locations, F, L, H, R, m0, C0, prior_model="continuous")`

where `observations` has shape `(N, m)`, `locations` is the strictly increasing array of `N`
time points, and the model matrices are: `F` the state-transition, `L` the process-noise
covariance, `H` the measurement matrix, `R` the measurement-noise covariance, `m0`/`C0` the
initial state mean/covariance.

For **`prior_model="discrete"`**, `F` is used directly as the one-step state-transition matrix
and `L` as the per-step process-noise covariance. The filter incorporates the **first** time
point with a measurement update only (there is no prediction step before the first observation);
each subsequent point applies one prediction followed by one update. This is the standard Kalman
recursion, and with these conventions the filtered means and covariances match a textbook Kalman
filter exactly. `prior_model="continuous"` is also supported; an unrecognised `prior_model`
raises `ValueError`. Time points that are not strictly increasing raise `ValueError`.

Both functions return a posterior object with:

* `.locations` and `.states` (the per-time-point marginals; `.states.mean` has shape `(N, n)`,
  `.states.cov` has shape `(N, n, n)`, and `.states[i]` is a `randvars.Normal`).
* **Dense output**: calling `posterior(t)` returns the marginal at `t` — exactly the stored
  state at a grid location, or an interpolated `randvars.Normal` between locations. Querying with
  an unsorted array of times raises `ValueError`, and querying before the first location
  (left-extrapolation) raises `NotImplementedError`.

`filter_kalman` runs the forward Kalman filter. `smooth_rts` additionally runs the
Rauch–Tung–Striebel backward pass, which incorporates later observations: its marginal
covariances are no larger than the filter's (strictly smaller at interior points, equal at the
final point), and its state estimates have lower error than the filter's.

### Nonlinear filtering (extended / unscented Kalman)

The top-level helpers above cover linear-Gaussian models. Nonlinear state-space models are
handled with a small class-based API:

* **State-space transitions** live in `probnum.randprocs.markov`:
  * `randprocs.markov.discrete.LTIGaussian(transition_matrix=, noise=)` — a linear-Gaussian
    transition (`noise` is a `randvars.Normal`); used for linear dynamics or measurement models.
  * `randprocs.markov.discrete.NonlinearGaussian(input_dim=, output_dim=, transition_fun=,
    transition_fun_jacobian=, noise_fun=)` — a nonlinear transition, where `transition_fun(t, x)`
    maps a state to its (noiseless) next value, `transition_fun_jacobian(t, x)` is its Jacobian,
    and `noise_fun(t)` returns the additive-noise `randvars.Normal`. A `NonlinearGaussian` cannot
    be propagated directly: calling its `forward_rv(rv, t, dt)` raises `NotImplementedError` — it
    must first be linearized (see below).
* **Linearization components** live in `probnum.filtsmooth.gaussian.approx`:
  * `DiscreteEKFComponent(transition)` and `DiscreteUKFComponent(transition)` wrap a transition
    (linear or nonlinear) into an extended / unscented Kalman approximation. The wrapped object's
    `forward_rv(rv, t, dt=...)` returns `(randvars.Normal, info)`. Wrapping an already-linear
    transition reproduces the exact linear-Gaussian prediction.
* **Assembling and running the estimator**:
  * `randprocs.markov.MarkovSequence(transition=, initrv=, initarg=)` packages a (possibly
    linearized) dynamics transition with an initial `randvars.Normal` and initial time into a
    prior process.
  * `probnum.problems.TimeSeriesRegressionProblem(observations=, locations=, measurement_models=)`
    holds the data and a per-time-point list of (linearized) measurement models.
  * `probnum.filtsmooth.gaussian.Kalman(prior_process)` runs the estimator: `.filter(rp)` and
    `.filtsmooth(rp)` each return `(posterior, info)`, and `.smooth(filter_posterior)` returns a
    smoothing posterior. The posteriors have the same `.states` / `.locations` interface as above.

For a nonlinear system, filtering (EKF or UKF) estimates the latent state more accurately than the
raw observations, and smoothing further reduces the marginal uncertainty.
