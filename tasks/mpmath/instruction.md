# mpmath

Build `mpmath`, a pure-Python library for **arbitrary-precision floating-point
arithmetic** over the real and complex numbers, plus an interval-arithmetic
context. On top of the number types it provides a large library of correctly
rounded elementary and special functions, numerical calculus (quadrature,
differentiation, summation, root-finding, ODEs, inverse Laplace transforms),
arbitrary-precision linear algebra, and integer-relation detection.

The defining contract of the library is **digit-exact correctness at a
user-chosen working precision**: every function must return a result that is
correct to (essentially) all of the active working digits, for all of the
argument regimes documented below. Producing the right *values* — not merely the
right call signatures — is the task.

## Dependencies

- The environment is **offline**: there is no network access, and every
  dependency needed at runtime is **already installed**. Do **not** attempt to
  install anything (`pip install`, `apt-get`, etc.) — installs will fail and are
  unnecessary. Your project is installed for grading by a `setup.sh` that runs
  fully offline against the pre-installed toolchain.
- The library itself is **pure Python with no required third-party runtime
  dependencies** — the standard library only. Do **not** depend on `gmpy2`,
  `numpy`, or any C extension: the grading environment runs the pure-Python
  big-integer backend, and every numeric result below must be reproduced on that
  backend.

## Package structure and imports

Everything used below is importable directly from the top-level package, e.g.

```python
from mpmath import mp, mpf, mpc, iv, matrix, pi, gamma, zeta, quad, findroot
```

The single exception is the **interval context**, which is the importable
singleton object `iv` (see "Interval arithmetic"). You are free to organize the
internal module layout however you like; only the top-level import names below
are part of the contract.

## Working precision and number types

### The precision context `mp`

`mp` is a global context object that holds the active **working precision**.

- `mp.dps` — working precision in **decimal places** (the number of significant
  decimal digits). Assigning to it (e.g. `mp.dps = 50`) changes the precision
  for all subsequent computations. The default is `15`.
- `mp.prec` — the equivalent precision in **bits** (the binary mantissa size);
  it stays consistent with `mp.dps`.

Precision is contextual: the *same* expression evaluated at `mp.dps = 50`
yields ~50 correct digits, and at `mp.dps = 15` yields the result rounded to
~15 digits. Functions compute at the active precision (typically with a few
internal guard digits) and round the final result correctly.

### `mpf` — real floating-point numbers

`mpf` is a binary floating-point number with a precision-controlled mantissa.

- Construct from a Python `int`, `float`, decimal **string** (e.g.
  `mpf('0.1')`), or other numeric values. String construction must parse the
  decimal value and round it correctly to the working precision (so `mpf('0.1')`
  is the correctly rounded binary value, and `mpf('0.1') + mpf('0.2')` equals
  `mpf('0.3')` to working precision).
- Supports the full arithmetic (`+ - * / **`), comparisons, `abs()`, and equality
  against other numbers and Python ints/floats.
- Behaves as an exact value where representable: e.g. `besseli(0, 0) == 1`,
  `abs(mpc(3, 4)) == 5`.

### `mpc` — complex floating-point numbers

`mpc` is a complex number whose real and imaginary parts are each `mpf`-like.

- Construct as `mpc(re, im)`; each part may be an `int`, `float`, or decimal
  string. The imaginary unit is available as the constant `j`, so e.g.
  `(2 + j) / 3` builds a complex value.
- Attributes: `.real` and `.imag` return the real and imaginary parts.
- Methods/operators: `.conjugate()` (and `abs()`, arithmetic, equality) behave as
  for ordinary complex numbers, at working precision.

### Almost-equal comparison: `.ae`

Every `mpf` and `mpc` provides an **almost-equal** method used to compare
numerical results up to rounding:

```python
x.ae(y, rel_eps=None, abs_eps=None)
```

Returns `True` when `x` and `y` agree to within the given tolerance. With no
tolerance supplied it uses a default tied to the working precision (so two
values that differ only in the last few guard digits compare equal). `rel_eps`
sets a relative tolerance and `abs_eps` sets an absolute tolerance; supplying
`abs_eps` lets values near zero compare equal (e.g. `zeta(0.5 + 14.134...j)`
compared against `0` with `abs_eps=1e-20`).

### Mathematical constants

The following are available as values that evaluate to the active working
precision: `pi`, `e`, `euler` (the Euler–Mascheroni constant γ), `catalan`
(Catalan's constant), `inf` (positive infinity), and `j` (the imaginary unit).

## Elementary functions

All elementary functions accept real (`mpf`/`int`/`float`) and complex (`mpc`)
arguments and return correctly rounded results at the working precision, using
the principal branch for multivalued functions.

- `exp`, `log` (natural logarithm; principal branch for complex/negative
  arguments, so `log(-1) = πi`), `sqrt` (principal branch, so `sqrt(-1) = i`),
  `cbrt` (real cube root for real input).
- Trigonometric `sin`, `cos`, and the inverse `atan`, with correct argument
  reduction at high precision.
- `agm(a, b)` — the arithmetic–geometric mean of `a` and `b`.
- `lambertw(x, k=0)` — the Lambert W function. `k` selects the branch: `k=0` is
  the principal branch, `k=-1` is the lower real branch (defined for
  `-1/e ≤ x < 0`).

## Gamma and related functions

Computed to full working precision for real and complex arguments, including
negative arguments (via the reflection formula) where the function is defined.

- `gamma(z)` — the gamma function (real, complex, fractional, and complex
  arguments with negative real part).
- `factorial(z)` — equals `gamma(z + 1)`.
- `rgamma(z)` — the reciprocal gamma `1/Γ(z)` (entire; finite at the poles of Γ).
- `loggamma(z)` — the principal branch of the logarithm of the gamma function
  (the analytic continuation, not `log(abs(gamma(z)))`; matches the conventional
  branch with imaginary part continuous off the real axis).
- `digamma(z)` — the logarithmic derivative `Γ'(z)/Γ(z)` (a.k.a. ψ).
- `polygamma(n, z)` — the `n`-th polygamma function (the `n`-th derivative of
  `digamma`).
- `beta(a, b)` — the beta function `Γ(a)Γ(b)/Γ(a+b)`.
- `harmonic(n)` — the `n`-th harmonic number (generalized to non-integers via
  digamma).
- `bernoulli(n)` — the `n`-th Bernoulli number `B_n` (with `B_1 = -1/2`
  convention), returned exactly where rational.

## Zeta family and related transcendents

These require correct behavior across the whole complex plane, including the
critical strip and negative arguments via the functional equation.

- `zeta(s)` — the Riemann zeta function for real and complex `s` (including the
  critical strip `0 < Re(s) < 1` and negative real parts).
- `zeta(s, a)` — the Hurwitz zeta function `ζ(s, a) = Σ (n+a)^{-s}`.
- `altzeta(s)` — the Dirichlet eta (alternating zeta) `η(s) = Σ (-1)^{n-1} n^{-s}`.
- `zetazero(n)` — the `n`-th nontrivial zero of ζ on the critical line, returned
  as an `mpc` with real part exactly `1/2` and positive imaginary part (the
  zeros ordered by increasing imaginary part, `n` starting at 1).
- `siegelz(t)` — the Riemann–Siegel Z function `Z(t)`, real for real `t`, whose
  sign changes mark the zeros (`Z(t) = e^{iθ(t)} ζ(1/2 + it)`).
- `polylog(s, z)` — the polylogarithm `Li_s(z) = Σ z^k / k^s`.
- `lerchphi(z, s, a)` — the Lerch transcendent `Φ(z, s, a) = Σ z^k / (k+a)^s`.
- `stieltjes(n)` — the `n`-th Stieltjes constant γ_n (the coefficients in the
  Laurent expansion of ζ about `s = 1`).

## Bessel, Airy, and Struve functions

Must be correct in **both** the small-argument (power-series) regime and the
large-argument (asymptotic) regime, and for complex order and argument. In
particular they must remain accurate for arguments as large as `1e10`, where any
naive series diverges and the asymptotic behavior governs.

- `besselj(n, z)`, `bessely(n, z)`, `besseli(n, z)`, `besselk(n, z)` — the Bessel
  functions of the first/second kind and the modified Bessel functions, for
  real or complex order `n` and argument `z`. `besseli(0, 0) == 1`.
- `airyai(z)`, `airybi(z)` — the Airy functions Ai and Bi (real negative
  arguments lie in the oscillatory region; complex arguments are supported).
- `struveh(n, z)` — the Struve function **H**_n.

## Hypergeometric functions

The hardest regime: correct evaluation requires the defining series where it
converges, **analytic continuation** outside the disk of convergence, and
**asymptotic expansions** for large arguments (including arguments around
`1e9`–`1e10`, where results may be astronomically large but must still be
correct to working precision in the mantissa and exponent).

- `hyp2f1(a, b, c, z)` — the Gauss hypergeometric ₂F₁, valid for `|z| ≥ 1` via
  continuation and for complex `z`. Numeric parameters may be given **as a
  2-tuple `(p, q)` denoting the exact rational `p/q`** (e.g. `hyp2f1((1,3),
  (2,3), (5,6), z)` uses parameters `1/3, 2/3, 5/6`).
- `hyp1f1(a, b, z)` — the confluent hypergeometric ₁F₁ (Kummer's M), accurate at
  very large `z` via asymptotics.
- `hyp0f1(a, z)` — the confluent ₀F₁, accurate at very large `z`.
- `hyperu(a, b, z)` — the confluent hypergeometric function of the second kind U.
- `hyp2f0(a, b, z)` — the (generally divergent) ₂F₀, summed via Borel-style
  regularization of its asymptotic series.
- `hyper(a_s, b_s, z)` — the generalized ₚF_q, where `a_s` and `b_s` are lists of
  upper and lower parameters (so `hyper([], [], z) = exp(z)` and
  `hyper([2], [], z) = (1 - z)^{-2}`).
- `meijerg(a_s, b_s, z)` — the Meijer G-function. `a_s` is `[a_top, a_bot]` and
  `b_s` is `[b_top, b_bot]`, each a list of parameter lists, matching the
  standard `G^{m,n}_{p,q}` partitioning (top/bottom split of the numerator and
  denominator parameter rows). For example `meijerg([[], []], [[0], []], x)`
  evaluates `G^{1,0}_{0,1}(x | ; 0) = e^{-x}`.

## Error, exponential, and Fresnel integrals

- `erf(z)` — the error function (real and complex `z`).
- `erfinv(y)` — the inverse error function.
- `ei(z)` — the exponential integral Ei.
- `ci(z)` — the cosine integral Ci (real and complex `z`).
- `fresnels(z)` — the Fresnel sine integral, in the **normalized** convention
  `S(z) = ∫₀ᶻ sin(πt²/2) dt` (so `fresnels(inf) = 1/2`), not the unnormalized
  `∫₀ᶻ sin(t²) dt` form.

## Elliptic integrals and theta/elliptic functions

- `ellipk(m)` — the complete elliptic integral of the first kind K (parameter
  `m = k²` convention).
- `ellipe(m)` — the complete elliptic integral of the second kind E (same
  parameter convention).
- `elliprf(x, y, z)` — Carlson's symmetric elliptic integral R_F.
- `jtheta(n, z, q)` — the Jacobi theta function θ_n (n = 1..4) with argument `z`
  and nome `q`.
- `ellipfun(kind, u, m)` — the Jacobi elliptic functions, selected by a string
  `kind` such as `'sn'`, `'cn'`, `'dn'`; `m` is the parameter (`m = k²`).
- `qp(z, q=None)` — the q-Pochhammer symbol; `qp(z)` is `(z; z)_∞`, i.e. the
  Euler function evaluated with nome equal to the argument.

## Orthogonal polynomials and spherical harmonics

Evaluate the classical orthogonal polynomials at a point (exact where the result
is rational), generalized to non-integer degrees/parameters where applicable.

- `legendre(n, x)` — the Legendre polynomial P_n.
- `hermite(n, x)` — the (physicists') Hermite polynomial H_n.
- `jacobi(n, a, b, x)` — the Jacobi polynomial P_n^{(a,b)}.
- `spherharm(l, m, theta, phi)` — the spherical harmonic Y_l^m (complex-valued),
  in the **orthonormalized** convention
  `Y_l^m(θ, φ) = √[(2l+1)/(4π) · (l-m)!/(l+m)!] · P_l^m(cos θ) · e^{imφ}` (the
  standard quantum-mechanics normalization, with the Condon–Shortley phase
  carried by the associated Legendre function `P_l^m`). The argument order is
  `spherharm(l, m, theta, phi)` with `theta` the **polar** (colatitude) angle and
  `phi` the **azimuthal** angle.

## Numerical quadrature

Adaptive numerical integration to full working precision, handling smooth
integrands, integrable endpoint singularities (a few digits may legitimately be
lost there), and improper integrals over infinite ranges.

- `quad(f, interval, ...)` — adaptive integration of `f` over an interval given
  as a 2-element sequence `[a, b]` (where `a`/`b` may be `±inf`). For
  **multidimensional** integration, pass one interval per variable:
  `quad(lambda x, y: ..., [a, b], [c, d])` integrates over the rectangle.
- `quadgl(f, interval)` — integration using Gauss–Legendre quadrature.
- `quadosc(f, interval, period=...)` — integration of an oscillatory integrand
  over a (possibly half-infinite) range; `period` gives the oscillation period
  (e.g. `2*pi`) used to accelerate convergence.

## Root finding

- `findroot(f, x0, solver=...)` — find a root of `f` near the starting point
  `x0`, to full working precision. The default solver handles a scalar
  transcendental equation; `solver='secant'` selects the secant method. For a
  **system**, pass a function returning a list of residuals and a tuple starting
  point, e.g. `findroot(lambda x, y: [r1, r2], (x0, y0))`, which returns the
  solution as an indexable vector (`sol[0]`, `sol[1]`).
- `polyroots(coeffs)` — all roots of a polynomial whose coefficients are given
  **highest-degree first** (so `[1, 0, -2, 1]` is `x³ - 2x + 1`). Returns the
  list of roots (complex where appropriate).

## Numerical calculus

- `diff(f, x, n=1)` — the `n`-th numerical derivative of `f` at `x`, accurate to
  working precision.
- `taylor(f, x, n)` — the list of Taylor **coefficients** `[c0, c1, ..., cn]` of
  `f` about `x` (so `c_k = f^{(k)}(x)/k!`).
- `pade(taylor_coeffs, p, q)` — the Padé approximant of numerator degree `p` and
  denominator degree `q` from a list of Taylor coefficients; returns a pair
  `(num_coeffs, den_coeffs)` of coefficient lists (each ordered from the constant
  term upward; the denominator is normalized so its constant term is 1).
- `nsum(f, interval, method=...)` — sum a series `Σ f(n)` over an integer range
  `[a, inf]`, using convergence acceleration so that even slowly converging and
  alternating series are summed to full working precision. `method='r'` selects
  Richardson extrapolation.
- `nprod(f, interval)` — the analogous infinite product `Π f(n)`.
- `limit(f, x)` — the limit of `f(n)` as its argument tends to `x` (e.g.
  `inf`), computed by extrapolation.
- `odefun(F, x0, y0)` — solve the ODE `y'(x) = F(x, y)` with `y(x0) = y0`,
  returning a **callable** `f` such that `f(x)` gives `y(x)` to working
  precision.
- `invertlaplace(F, t, method=...)` — the numerical inverse Laplace transform of
  `F(s)` evaluated at `t`; `method='talbot'` selects the Talbot contour method.

## Arbitrary-precision linear algebra

A `matrix` type plus decompositions and solvers that operate at arbitrary
precision.

- `matrix(rows)` — construct a matrix from a list of row lists
  (`matrix([[a, b], [c, d]])`); a single list builds a column vector
  (`matrix([x, y, z])`). Elements are accessed as `M[i, j]` (and `v[i]` for
  vectors). Supports matrix multiplication (`A * B`).
- `lu_solve(A, b)` — solve `A x = b` (square `A`) via LU decomposition.
- `det(A)` — the determinant.
- `inverse(A)` — the matrix inverse.
- `qr_solve(A, b)` — least-squares solve of an overdetermined system via QR;
  returns a pair whose first element is the solution vector (and second the
  residual norm).
- `cholesky(A)` — the Cholesky factor of a symmetric positive-definite matrix,
  returned as a lower-triangular matrix `L` with `L Lᵀ = A`.
- `eig(A, left=False, right=False)` — eigen-decomposition of a general square
  matrix. With `left=False, right=False` it returns just the list of
  eigenvalues.
- `eigsy(A, eigvals_only=False)` — eigen-decomposition of a **symmetric** real
  matrix. With `eigvals_only=True` it returns the eigenvalues as an indexable
  vector (ascending order).
- `svd_r(A, compute_uv=True)` — the singular value decomposition of a real
  matrix. With `compute_uv=False` it returns the singular values as an indexable
  vector in descending order.
- `expm(A)` — the matrix exponential `e^A`.
- `sqrtm(A)` — the principal matrix square root.
- `norm(v, p)` — the vector `p`-norm (e.g. `norm(v, 2)` is the Euclidean norm).
- `mnorm(A, p)` — the matrix `p`-norm (e.g. `mnorm(A, 1)` is the maximum absolute
  column sum).
- `cond(A)` — the condition number `||A|| * ||A^-1||`, computed in the matrix
  1-norm by default (the maximum absolute column sum).

## Interval arithmetic

`iv` is a separate context (analogous to `mp`) that performs **rigorous interval
arithmetic**: every result is an interval guaranteed to enclose the true value.

- `iv.dps` — the working precision of the interval context.
- `iv.mpf([a, b])` — an interval number spanning `[a, b]`. Its endpoints are
  accessible as `.a` (lower) and `.b` (upper).
- Arithmetic on interval numbers (e.g. `iv.mpf([1, 2]) * iv.mpf([3, 4])`)
  produces an interval that rigorously encloses every possible product (here
  exactly `[3, 8]`).
- Elementary functions are provided on the context, e.g. `iv.sin(x)`, and return
  an interval enclosing the image of the input interval.

## Integer-relation detection and identification

- `pslq(vector)` — the PSLQ algorithm. Given a list of real numbers, return a
  list of small **integer** coefficients giving a linear relation that is zero
  (to working precision), or a falsey value if none is found. For example
  `pslq([1, 2^{1/3}, 2^{2/3}, 2])` returns `[2, 0, 0, -1]` (encoding
  `x³ - 2 = 0` for `x = 2^{1/3}`), and `pslq([log2, log3, log6])` returns
  `[1, 1, -1]`.
- `identify(x)` — attempt to identify a closed form for the real number `x`,
  returning a **string** expression (e.g. `identify(e)` returns `'exp(1)'`).

## Accurate accumulation helpers

- `fsum(terms)` — sum an iterable of numbers without intermediate rounding error,
  so catastrophic cancellation does not occur (e.g.
  `fsum([1e20, 1, -1e20]) == 1`).
- `fdot(pairs)` — the dot product of a list of `(a, b)` pairs, computed without
  cancellation error (`fdot([(1,2),(3,4),(5,6)]) == 44`).
