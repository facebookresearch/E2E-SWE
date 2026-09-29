"""Digit-exact behavioral contract tests for an arbitrary-precision numerics library.

Each test below represents a realistic user workflow: set a working precision,
call one or more public functions, and assert that the returned values are
correct to the requested number of digits. The hard part of the task is not the
API surface (which is conventional) but reproducing the *values* a correct
implementation must emit -- which requires correct series acceleration,
asymptotic expansions, argument reduction, precision bookkeeping, and the
numerical algorithms (adaptive quadrature, eigen/SVD decompositions,
integer-relation detection, extrapolation) behind them.

Reference values are asserted with `aeq`, an almost-equal check with a relative
tolerance set a few digits inside the active working precision: a correct
implementation that differs only in the last couple of guard digits passes,
while an implementation that gets the algorithm wrong (and therefore loses many
digits) fails. Each test sets `mp.dps` explicitly and is bounded so it runs
quickly on the pure-Python big-integer backend.
"""

from mpmath import (
    mp,
    mpf,
    mpc,
    iv,
    matrix,
    pi,
    e,
    euler,
    catalan,
    inf,
    j,
    exp,
    log,
    sqrt,
    sin,
    cos,
    atan,
    agm,
    cbrt,
    gamma,
    factorial,
    rgamma,
    loggamma,
    digamma,
    polygamma,
    beta,
    harmonic,
    bernoulli,
    zeta,
    altzeta,
    zetazero,
    siegelz,
    polylog,
    lerchphi,
    stieltjes,
    besselj,
    bessely,
    besseli,
    besselk,
    airyai,
    airybi,
    struveh,
    hyp2f1,
    hyp1f1,
    hyp0f1,
    hyperu,
    hyp2f0,
    hyper,
    meijerg,
    erf,
    erfinv,
    ei,
    ci,
    fresnels,
    ellipk,
    ellipe,
    jtheta,
    ellipfun,
    elliprf,
    qp,
    legendre,
    hermite,
    jacobi,
    spherharm,
    quad,
    quadgl,
    quadosc,
    findroot,
    polyroots,
    diff,
    taylor,
    pade,
    nsum,
    nprod,
    limit,
    invertlaplace,
    odefun,
    lu_solve,
    det,
    inverse,
    qr_solve,
    cholesky,
    eig,
    eigsy,
    svd_r,
    expm,
    norm,
    mnorm,
    cond,
    sqrtm,
    pslq,
    identify,
    lambertw,
    fsum,
    fdot,
)


def aeq(got, expected, tol=None):
    """Almost-equal with an explicit relative tolerance.

    The default tolerance is set a few digits inside the active working
    precision so that a correct implementation (which may differ from the
    reference only in the last couple of guard digits) passes, while an
    implementation that gets the algorithm wrong -- and therefore loses many
    digits -- fails.
    """
    if tol is None:
        tol = mpf(10) ** (-(mp.dps - 6))
    if not isinstance(got, (mpf, mpc)):
        if isinstance(got, complex):
            got = mpc(got.real, got.imag)
        else:
            got = mpf(got)
    return got.ae(expected, rel_eps=tol)


# ---------------------------------------------------------------------------
# Precision context + elementary functions (de-weighted: bundled into broad
# workflows so the memorizable basics are credited once, not fragmented).
# ---------------------------------------------------------------------------


def test_precision_context_and_constants():
    """Set working precision and read the standard mathematical constants plus
    basic elementary evaluations, verifying correct rounding at 50 digits and
    that precision is independent across calls."""
    mp.dps = 50
    assert aeq(pi, mpf("3.1415926535897932384626433832795028841971693993751"))
    assert aeq(e, mpf("2.7182818284590452353602874713526624977572470937000"))
    assert aeq(euler, mpf("0.57721566490153286060651209008240243104215933593992"))
    assert aeq(catalan, mpf("0.91596559417721901505460351493238411077414937428167"))
    assert exp(mpf(1)).ae(e)
    assert aeq(log(mpf(2)), mpf("0.69314718055994530941723212145817656807550013436026"))
    assert aeq(sqrt(mpf(2)), mpf("1.4142135623730950488016887242096980785696718753769"))
    assert (atan(mpf(1)) * 4).ae(pi)
    # Precision is contextual: a smaller dps rounds the same expression.
    mp.dps = 15
    assert aeq(sqrt(mpf(2)), mpf("1.4142135623730951"))


def test_mpf_mpc_construction_and_arithmetic():
    """Construct numbers from int/str/fraction, do exact arithmetic, and verify
    string round-tripping and basic complex arithmetic at 50 digits."""
    mp.dps = 50
    assert aeq(mpf(1) / 3, mpf("0.33333333333333333333333333333333333333333333333333"))
    assert aeq(mpf("0.1") + mpf("0.2"), mpf("0.3"))
    z = mpc(2, 3)
    assert (z * z).ae(mpc(-5, 12))
    assert abs(mpc(3, 4)) == 5
    assert z.conjugate() == mpc(2, -3)
    assert aeq(cbrt(mpf(2)), mpf("1.2599210498948731647672106072782283505702514647015"))
    assert aeq(
        agm(mpf(1), sqrt(mpf(2))),
        mpf("1.1981402347355922074399224922803238782272126632157"),
    )


def test_elementary_branches_and_powers():
    """Elementary functions on the complex plane: principal branch of the
    square root of a negative real, complex logarithm, and the Lambert W
    function on its principal and -1 branches."""
    mp.dps = 50
    assert (mpc(-1, 0) ** mpf("0.5")).ae(mpc(0, 1))
    assert log(mpc(-1, 0)).ae(mpc(0, pi))
    assert aeq(
        lambertw(mpf(1)), mpf("0.56714329040978387299996866221035554975381578718651")
    )
    assert aeq(
        lambertw(mpf(-1) / 5, -1),
        mpf("-2.5426413577735264242938061566618482901614749075294"),
    )


# ---------------------------------------------------------------------------
# Gamma family (HARD: Spouge/Stirling + reflection, complex args).
# ---------------------------------------------------------------------------


def test_gamma_function_real_and_complex():
    """Evaluate the gamma function at fractional, half-integer and complex
    arguments, including a point where the reflection formula must be applied
    for a negative real part."""
    mp.dps = 50
    assert aeq(
        gamma(mpf(1) / 3), mpf("2.6789385347077476336556929409746776441286893779573")
    )
    assert factorial(mpf(1) / 2).ae(sqrt(pi) / 2)
    assert aeq(
        rgamma(mpf(-7) / 2), mpf("3.7024941420321506330967714008675700946015822549716")
    )
    assert aeq(
        gamma(mpc(5, 6)),
        mpc(
            "-0.61415029784858603278704313522634469315872687927397",
            "-0.68780600579394331640541106127564751392641063033745",
        ),
    )
    assert aeq(
        gamma(mpc(-0.5, 12)),
        mpc(
            "-1.1915104716171217619519946858429415091178246739705e-9",
            "-6.5394717435888800499557128132037818733231273157887e-10",
        ),
    )


def test_loggamma_digamma_polygamma_beta():
    """Log-gamma at a complex point (with correct branch), the digamma and a
    higher polygamma at fractional arguments, the beta function, a harmonic
    number, and a Bernoulli number."""
    mp.dps = 50
    assert aeq(
        loggamma(mpc(5, 6)),
        mpc(
            "-0.081107905395725522245729389069614057882694404686879",
            "10.266688988334668000668076504871017371288419628534",
        ),
    )
    assert aeq(
        digamma(mpf(1) / 7), mpf("-7.3639802422243431985495153030168810478199162355903")
    )
    assert aeq(
        polygamma(3, mpf(5) / 2),
        mpf("0.22390584881725205125514750351992606454240048750024"),
    )
    assert aeq(
        beta(mpf(5) / 2, mpf(7) / 2),
        mpf("0.036815538909255389513234102147806674424185578898927"),
    )
    assert aeq(harmonic(10), mpf("2.9289682539682539682539682539682539682539682539683"))
    assert aeq(bernoulli(20), mpf(-174611) / 330)


# ---------------------------------------------------------------------------
# Zeta family (HARDEST: Euler-Maclaurin + Riemann-Siegel).
# ---------------------------------------------------------------------------


def test_riemann_zeta_real_and_critical_strip():
    """Riemann zeta at integer and fractional real arguments (closed forms),
    inside the critical strip at a complex argument, and at a negative argument
    far from the origin where the functional equation dominates."""
    mp.dps = 50
    assert zeta(2).ae(pi**2 / 6)
    assert aeq(zeta(3), mpf("1.2020569031595942853997381615114499907649862923405"))
    assert aeq(
        zeta(mpf(1) / 2), mpf("-1.4603545088095868128894991525152980124672293310126")
    )
    assert aeq(
        zeta(mpc(0.5, 30)),
        mpc(
            "-0.12064228759004369991402114731201628193052858529308",
            "-0.58369121476370628875763582566425519414475114806123",
        ),
    )
    assert aeq(
        zeta(mpc(-15.5, 8)),
        mpc(
            "11041.445704899662087082346753246878928861594876322",
            "-9705.4939072225636400872522059204865673575620527247",
        ),
    )


def test_zeta_zeros_and_siegelz():
    """Locate nontrivial zeros of the Riemann zeta function on the critical line
    (Riemann-Siegel based) and evaluate the Riemann-Siegel Z function, whose
    sign changes mark the zeros."""
    mp.dps = 30
    z1 = zetazero(1)
    assert z1.real == mpf("0.5")
    assert aeq(z1.imag, mpf("14.1347251417346937904572519836"))
    assert aeq(zetazero(10).imag, mpf("49.7738324776723021819167846786"))
    assert zeta(mpc(0.5, z1.imag)).ae(0, abs_eps=mpf(10) ** -20)
    assert aeq(siegelz(20), mpf("1.14784241218519727763503408717975"))


def test_zeta_relatives_polylog_lerch_stieltjes():
    """The Dirichlet eta (alternating zeta), Hurwitz zeta, the polylogarithm,
    the Lerch transcendent, and a Stieltjes constant -- the constellation of
    functions that share the zeta machinery."""
    mp.dps = 40
    assert aeq(altzeta(mpf(1) / 2), mpf("0.6048986434216303702472659142359554997598"))
    assert aeq(
        zeta(mpf(5) / 2, mpf(7) / 10), mpf("2.9028675777573462196283576576094997915366")
    )
    assert aeq(
        polylog(3, mpf(7) / 10), mpf("0.7800639342576615608835690998593831324363")
    )
    assert aeq(
        lerchphi(mpf(3) / 10, 2, mpf(4) / 10),
        mpf("6.4215466035222619620693139135963798072707"),
    )
    assert aeq(stieltjes(2), mpf("-0.009690363192872318484530386035212529359066"))


# ---------------------------------------------------------------------------
# Bessel / Airy (HARD: small-argument series vs large-argument asymptotics).
# ---------------------------------------------------------------------------


def test_bessel_functions_small_and_large_argument():
    """Bessel J/Y/I/K at small real arguments (power series regime) and at a
    very large argument (1e10, where the asymptotic expansion governs and the
    series would never converge), plus a complex-order, complex-argument case."""
    mp.dps = 50
    assert aeq(
        besselj(0, 1), mpf("0.76519768655796655144971752610266322090927428975533")
    )
    assert aeq(
        besselj(3, 3), mpf("0.30906272225525164361826019494683314942913593599306")
    )
    # Large-argument asymptotic regime:
    assert aeq(
        besselj(3, 10**10) * 10**5,
        mpf("0.76765081748139204022731189715056312466930501238070"),
    )
    assert aeq(
        bessely(3, 10**10) * 10**5,
        mpf("0.21755917537013204057945489439945362476936828103112"),
    )
    # Complex order and argument:
    assert aeq(
        besselj(mpc(1, 2), mpc(3, 4)),
        mpc(
            "0.31924742874187213098194645783893538036333733214561",
            "-0.66955774888036567849729242362576147241499328624355",
        ),
    )
    assert besseli(0, 0) == 1
    assert aeq(
        besselk(2, mpc(3, 4)),
        mpc(
            "0.00057274759539475327390095680106566179551930650574",
            "0.035205977657653012161883927031822074183400703575801",
        ),
    )


def test_airy_and_struve_functions():
    """The Airy functions Ai and Bi at a negative real argument (oscillatory
    region) and a complex argument, and a Struve H function."""
    mp.dps = 50
    assert aeq(airyai(-5), mpf("0.35076100902411431978801632769674222148444325089309"))
    assert aeq(
        airybi(mpc(2, 3)),
        mpc(
            "-0.39636825504039208527258118055410696131107533046975",
            "-0.56973091295594972030580026944386178752901260933010",
        ),
    )
    assert aeq(
        struveh(1, mpf(5) / 2),
        mpf("0.86315420665653531619196262970080248809572854024904"),
    )


# ---------------------------------------------------------------------------
# Hypergeometric (HARDEST: series + analytic continuation + asymptotics).
# ---------------------------------------------------------------------------


def test_hypergeometric_2f1_continuation():
    """The Gauss hypergeometric 2F1 evaluated near and beyond the unit disk,
    where analytic continuation is required, plus a complex argument case and a
    point with a known rational closed form."""
    mp.dps = 50
    # Known closed form: 2F1(1/3, 2/3; 5/6; 27/32) = 1.6
    assert aeq(hyp2f1((1, 3), (2, 3), (5, 6), mpf(27) / 32), mpf("1.6"))
    assert aeq(
        hyp2f1((2, 3), (1, 1), (3, 2), (2 + j) / 3),
        mpc(
            "1.3275316035586790929868521884256234195598301427602",
            "0.43958508009276925290116702478570048955120347728954",
        ),
    )
    # Outside the unit disk -- requires continuation:
    assert aeq(hyp2f1(1, 1, 2, mpf(-3)), log(mpf(4)) / 3)


def test_confluent_hypergeometric_large_argument():
    """The confluent hypergeometric 1F1 and 0F1 at very large arguments where
    the defining series diverges numerically and an asymptotic expansion must
    take over, and the second-kind confluent function U."""
    mp.dps = 50
    assert aeq(
        hyp1f1(2, 3, mpf(10) ** 10),
        mpf("2.1555012157015796988367796097826663959355067733209e+4342944809"),
    )
    assert aeq(
        hyp0f1(3, mpf(10) ** 9),
        mpf("4.9679055380347771271521357849510670595492492149788e+27455"),
    )
    assert aeq(
        hyperu(mpf(3) / 2, mpf(5) / 2, 3),
        mpf("0.19245008972987525483638292683398581854920058375671"),
    )
    # A divergent (asymptotic) 2F0 series, summed via Borel-style regularization:
    assert aeq(
        hyp2f0(1, mpf(3) / 2, mpf(-1) / 10),
        mpf("0.87826774139446546084806734901512451483939751094494"),
    )


def test_general_hyper_and_meijerg():
    """The generalized pFq through the `hyper` entry point and a Meijer G
    function reproducing exp(-x) via its G-function representation."""
    mp.dps = 50
    assert hyper([], [], mpf(-2)).ae(exp(mpf(-2)))
    assert hyper([2], [], mpf(3) / 2).ae(mpf(4))
    # G^{1,0}_{0,1}(x | ; 0) = exp(-x)
    assert meijerg([[], []], [[0], []], mpf(1) / 2).ae(exp(mpf(-1) / 2))


# ---------------------------------------------------------------------------
# Error / exponential integrals (HARD).
# ---------------------------------------------------------------------------


def test_error_and_exponential_integrals():
    """The error function on the complex plane and its inverse, the exponential
    integral Ei, the cosine integral Ci at a complex point, and the Fresnel S
    integral."""
    mp.dps = 50
    assert aeq(
        erf(mpc(1, 2)),
        mpc(
            "-0.53664356577856503399179555931419274944209386881428",
            "-5.0491437034470346695430369586141405655530910763099",
        ),
    )
    assert aeq(
        erfinv(mpf(9) / 10), mpf("1.1630871536766740867262542605629475934779325500021")
    )
    assert aeq(
        ei(mpf(5) / 2), mpf("7.0737658945786007119235519624510125469963201056904")
    )
    assert aeq(
        ci(mpc(3, 1)),
        mpc(
            "0.078134230477495714401983633057082669599566619254273",
            "-0.37814733904787920181190368789446967062238084671268",
        ),
    )
    assert aeq(
        fresnels(mpf(3) / 2),
        mpf("0.69750496008209301308065516318726833294476912137929"),
    )


# ---------------------------------------------------------------------------
# Elliptic / theta (HARD).
# ---------------------------------------------------------------------------


def test_elliptic_integrals_and_jacobi_theta():
    """Complete elliptic integrals K and E, a symmetric (Carlson) elliptic
    integral RF, a Jacobi theta function, a Jacobi elliptic function sn, and the
    q-Pochhammer symbol -- the elliptic/theta toolkit."""
    mp.dps = 50
    assert aeq(
        ellipk(mpf(1) / 2), mpf("1.8540746773013719184338503471952600462175988235218")
    )
    assert aeq(
        ellipe(mpf(7) / 10), mpf("1.2416705679458227508715113251723844272203973543966")
    )
    assert aeq(
        elliprf(1, 2, 3), mpf("0.72694593546890819853957062601989181443786387872278")
    )
    assert aeq(
        jtheta(3, 0, mpf(1) / 2),
        mpf("2.1289368272118771586694585485449513246125165399409"),
    )
    assert aeq(
        ellipfun("sn", mpf(1) / 2, mpf(1) / 3),
        mpf("0.47363764036935590182718373457697657737138526521851"),
    )
    assert aeq(
        qp(mpf(1) / 3), mpf("0.56012607792794894496979224331414001437973633379836")
    )


# ---------------------------------------------------------------------------
# Orthogonal polynomials (MED-HARD).
# ---------------------------------------------------------------------------


def test_orthogonal_polynomials_and_spherical_harmonics():
    """Classical orthogonal polynomials (Legendre, Hermite, Jacobi) evaluated at
    a point, plus a spherical harmonic with complex-valued output."""
    mp.dps = 50
    assert aeq(legendre(5, mpf(3) / 10), mpf("0.34538625"))
    assert hermite(6, mpf(3) / 2).ae(mpf(-201))
    assert aeq(jacobi(4, 1, 2, mpf(3) / 10), mpf("0.3270625"))
    assert aeq(
        spherharm(3, 2, mpf(1) / 2, mpf(1) / 3),
        mpc(
            "0.16200756238883057468095642974475461630152976747338",
            "0.12747449850650109500660559139489077817776572573758",
        ),
    )


# ---------------------------------------------------------------------------
# Adaptive quadrature (HARD: node/weight generation + convergence).
# ---------------------------------------------------------------------------


def test_adaptive_quadrature_endpoint_and_infinite():
    """Adaptive numerical integration: a smooth definite integral, an integrand
    with an integrable endpoint singularity (1/sqrt(x)), an improper integral to
    infinity, and Gauss-Legendre integration of a smooth function."""
    mp.dps = 40
    assert aeq(quad(sin, [0, pi]), mpf(2))
    # Endpoint singularity: tanh-sinh converges, but a few digits are lost.
    assert quad(lambda x: 1 / sqrt(x), [0, 1]).ae(mpf(2), rel_eps=mpf(10) ** -18)
    assert aeq(quad(lambda x: exp(-(x**2)), [0, inf]), sqrt(pi) / 2)
    assert aeq(quadgl(lambda x: exp(x), [0, 1]), e - 1)


def test_oscillatory_and_multidimensional_quadrature():
    """Oscillatory quadrature of a slowly decaying integrand (sinc) over a
    half-infinite range, and a two-dimensional integral of a Gaussian over the
    unit square."""
    mp.dps = 30
    assert aeq(
        quadosc(lambda x: sin(x) / x, [1, inf], period=2 * pi),
        mpf("0.62471325642771360428996837781657"),
    )
    mp.dps = 40
    val = quad(lambda x, y: exp(-(x**2) - y**2), [0, 1], [0, 1])
    assert aeq(val, mpf("0.55774628535103364077463611410230002315246"))


# ---------------------------------------------------------------------------
# Root finding (HARD).
# ---------------------------------------------------------------------------


def test_root_finding_scalar_and_system():
    """Scalar root finding (Newton on a transcendental equation, secant on a
    polynomial), polynomial root extraction, and a 2x2 nonlinear system."""
    mp.dps = 50
    assert aeq(
        findroot(lambda x: cos(x) - x, 1),
        mpf("0.73908513321516064165531208767387340401341175890076"),
    )
    assert findroot(lambda x: x**3 - 2, 1, solver="secant").ae(cbrt(mpf(2)))
    roots = sorted(polyroots([1, 0, -2, 1]), key=lambda r: r.real if hasattr(r, "real") else r)
    assert aeq(roots[0], mpf("-1.6180339887498948482045868343656381177203091798058"))
    assert aeq(roots[1], mpf("0.61803398874989484820458683436563811772030917980576"))
    assert aeq(roots[2], mpf(1))
    sol = findroot(lambda x, y: [x**2 + y**2 - 1, x - y], (0.5, 0.5))
    assert sol[0].ae(sqrt(mpf(2)) / 2)
    assert sol[1].ae(sqrt(mpf(2)) / 2)


# ---------------------------------------------------------------------------
# Numerical calculus: differentiation, summation, extrapolation, ODE, Laplace.
# ---------------------------------------------------------------------------


def test_numerical_differentiation_and_series():
    """High-order numerical differentiation, a Taylor series expansion, and a
    Pade approximant derived from a Taylor series."""
    mp.dps = 40
    assert diff(sin, 1).ae(cos(mpf(1)))
    assert diff(sin, 1, 3).ae(-cos(mpf(1)))
    tc = taylor(exp, 0, 5)
    assert tc[0].ae(mpf(1))
    assert tc[3].ae(mpf(1) / 6)
    assert tc[5].ae(mpf(1) / 120)
    p, q = pade(taylor(exp, 0, 6), 3, 3)
    assert p[0].ae(mpf(1))
    assert p[1].ae(mpf(1) / 2)
    assert q[1].ae(mpf(-1) / 2)


def test_summation_and_extrapolation():
    """Infinite-series summation with convergence acceleration: a convergent
    series with a closed form, an alternating series (handled by an alternating
    acceleration), a Richardson-extrapolated series, and a convergent product."""
    mp.dps = 40
    assert nsum(lambda n: 1 / n**2, [1, inf]).ae(pi**2 / 6)
    assert nsum(lambda n: (-1) ** (n + 1) / n, [1, inf]).ae(log(mpf(2)))
    assert nsum(lambda n: 1 / n**3, [1, inf], method="r").ae(zeta(3))
    assert nprod(lambda n: exp(1 / n**2), [1, inf]).ae(exp(pi**2 / 6))


def test_limit_ode_and_inverse_laplace():
    """A limit computed by extrapolation, an ODE solved as a callable solution
    function, and a numerical inverse Laplace transform."""
    mp.dps = 30
    assert limit(lambda n: (1 + 1 / n) ** n, inf).ae(e)
    f = odefun(lambda x, y: y, 0, 1)
    assert f(1).ae(e)
    assert invertlaplace(lambda s: 1 / (s + 1), 2, method="talbot").ae(exp(mpf(-2)))


# ---------------------------------------------------------------------------
# Arbitrary-precision linear algebra (HARD: decompositions at arbitrary prec).
# ---------------------------------------------------------------------------


def test_linear_solve_determinant_inverse():
    """Solve a linear system, compute a determinant and a matrix inverse, and
    solve an overdetermined least-squares system via QR -- the core direct
    solvers."""
    mp.dps = 50
    A = matrix([[2, 1, 1], [4, -6, 0], [-2, 7, 2]])
    x = lu_solve(A, matrix([5, -2, 9]))
    assert x[0].ae(mpf(1))
    assert x[1].ae(mpf(1))
    assert x[2].ae(mpf(2))
    assert det(A).ae(mpf(-16))
    Ainv = inverse(matrix([[2, 1], [1, 3]]))
    assert aeq(Ainv[0, 0], mpf("0.6"))
    assert aeq(Ainv[0, 1], mpf("-0.2"))
    lstsq = qr_solve(matrix([[1, 2], [3, 4], [5, 7]]), matrix([1, 2, 3]))[0]
    assert lstsq[0].ae(mpf(-1) / 14)
    assert aeq(lstsq[1], mpf("0.5"))


def test_matrix_decompositions_cholesky_eig_svd():
    """Cholesky factorization of a symmetric positive-definite matrix,
    eigenvalues of a general and a symmetric matrix, and singular values of a
    rectangular matrix."""
    mp.dps = 50
    C = cholesky(matrix([[4, 2], [2, 3]]))
    assert C[0, 0].ae(mpf(2))
    assert C[1, 1].ae(sqrt(mpf(2)))
    assert C[0, 1].ae(mpf(0))
    ev = sorted(
        eig(matrix([[2, 1], [1, 2]]), left=False, right=False), key=lambda v: v.real if hasattr(v, "real") else v
    )
    assert ev[0].ae(mpf(1))
    assert ev[1].ae(mpf(3))
    sev = eigsy(matrix([[2, 1, 0], [1, 3, 1], [0, 1, 2]]), eigvals_only=True)
    vals = sorted(sev[i] for i in range(3))
    assert vals[0].ae(mpf(1))
    assert vals[1].ae(mpf(2))
    assert vals[2].ae(mpf(4))
    sv = svd_r(matrix([[1, 2], [3, 4], [5, 6]]), compute_uv=False)
    assert aeq(sv[0], mpf("9.5255180915651082152532097646797212843117364825521"))
    assert aeq(sv[1], mpf("0.51430058065864427249187324348137730719645420544462"))


def test_matrix_functions_and_norms():
    """Functions of matrices (matrix exponential of a rotation generator,
    principal matrix square root) and vector/matrix norms plus a condition
    number."""
    mp.dps = 50
    E = expm(matrix([[0, 1], [-1, 0]]))
    assert E[0, 0].ae(cos(mpf(1)))
    assert E[0, 1].ae(sin(mpf(1)))
    assert E[1, 0].ae(-sin(mpf(1)))
    S = sqrtm(matrix([[2, 1], [1, 2]]))
    SS = S * S
    assert SS[0, 0].ae(mpf(2))
    assert SS[0, 1].ae(mpf(1))
    assert norm(matrix([3, 4]), 2).ae(mpf(5))
    assert mnorm(matrix([[1, 2], [3, 4]]), 1).ae(mpf(6))
    assert cond(matrix([[1, 2], [3, 4]])).ae(mpf(21))


# ---------------------------------------------------------------------------
# Interval arithmetic (MED).
# ---------------------------------------------------------------------------


def test_interval_arithmetic():
    """The interval-arithmetic context: products of intervals produce a
    rigorously enclosing interval, and a monotone elementary function maps an
    interval to its image enclosure."""
    iv.dps = 30
    r = iv.mpf([1, 2]) * iv.mpf([3, 4])
    assert r.a == mpf(3)
    assert r.b == mpf(8)
    s = iv.sin(iv.mpf([0, 1]))
    # Enclosure-only: the true image is [sin(0), sin(1)] = [0, sin(1)]. A rigorous
    # interval must enclose it (lower endpoint <= 0, upper endpoint >= sin(1)); it is
    # not required to return the tightest/best endpoint, so a valid implementation may
    # outward-round the lower endpoint below 0.
    assert s.a <= mpf(0)
    assert s.b >= sin(mpf(1))


# ---------------------------------------------------------------------------
# Integer-relation detection / identification (HARD).
# ---------------------------------------------------------------------------


def test_integer_relation_detection():
    """The PSLQ integer-relation algorithm recovering the minimal polynomial
    relation of an algebraic number and a linear relation among logarithms, plus
    the `identify` convenience built on top of it."""
    mp.dps = 30
    # 2^(1/3) satisfies x^3 - 2 = 0, i.e. relation [2,0,0,-1] over [1,x,x^2,x^3].
    rel = pslq([mpf(1), cbrt(2), cbrt(2) ** 2, cbrt(2) ** 3])
    assert rel == [2, 0, 0, -1]
    # log 2 + log 3 - log 6 = 0.
    assert pslq([log(mpf(2)), log(mpf(3)), log(mpf(6))]) == [1, 1, -1]
    assert identify(e) == "exp(1)"


# ---------------------------------------------------------------------------
# Accurate accumulation helpers.
# ---------------------------------------------------------------------------


def test_accurate_summation_helpers():
    """The catastrophic-cancellation-free summation and dot-product helpers
    return the mathematically exact result where naive accumulation would lose
    precision."""
    mp.dps = 50
    assert fsum([mpf(10) ** 20, mpf(1), -(mpf(10) ** 20)]) == mpf(1)
    assert fdot([(1, 2), (3, 4), (5, 6)]) == mpf(44)
