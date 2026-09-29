"""Hidden test suite for the `fend` calculator task.

Each test drives the compiled `fend` binary (built by setup.sh, installed on PATH) the way a
user would, and asserts exact output strings. One test function = one behavioral contract;
every assertion inside must hold for the test to pass (no partial credit).
"""
import subprocess


def _run(expr):
    return subprocess.run(["fend", expr], capture_output=True, text=True, timeout=20)


def ev(expr, expected):
    """Evaluate expr; require success and exact stdout (one trailing newline stripped)."""
    r = _run(expr)
    assert r.returncode == 0, f"{expr!r} errored (exit {r.returncode}): {r.stderr!r}"
    out = r.stdout[:-1] if r.stdout.endswith("\n") else r.stdout
    assert out == expected, f"{expr!r}: got {out!r}, want {expected!r}"


def err(expr, message=None):
    """Evaluate expr; require rejection (non-zero exit). Optionally check the exact message."""
    r = _run(expr)
    assert r.returncode != 0, f"{expr!r} unexpectedly succeeded: {r.stdout!r}"
    if message is not None:
        got = r.stderr.strip()
        assert got == message, f"{expr!r}: got message {got!r}, want {message!r}"


def test_operator_precedence_and_grouping():
    """Operator precedence, associativity (incl. right-assoc ^ with unary minus), and grouping."""
    ev("2+2*3", "8")
    ev("2*2+3", "7")
    ev("2-3-4", "-5")
    ev("7-3*2", "1")
    ev("(2+3)*(4-1)", "15")
    ev("2*(3+4)*5", "70")
    ev("4^-1^2", "0.25")
    ev("(1+2)*3", "9")

def test_unary_operators_and_factorial():
    """Unary plus/minus binding and postfix factorial."""
    ev("-2^2", "-4")
    ev("(-2)^2", "4")
    ev("5!", "120")
    ev("3!+1", "7")
    ev("2*-3", "-6")
    ev("-(2+3)", "-5")

def test_implicit_multiplication_and_mixed_fraction():
    """Implicit multiplication, including mixed fractions appearing inside a product."""
    ev("5(6)", "30")
    ev("2*1 1/2", "3")
    ev("3*2*1 1/2", "9")

def test_arbitrary_precision_integers():
    """Arbitrary-precision integer arithmetic, factorial ratios, and large base-36 parsing."""
    ev("315427679023453451289740 * 927346502937456234523452", "292510755072077978255166497050046859223676982480")
    ev("2^100", "1267650600228229401496703205376")
    ev("100!", "93326215443944152681699238856266700490715968264381621468592963895217599993229915608941463976156518286253697920827223758251185210916864000000000000000000000000")
    ev("1000! / 999!", "1000")
    ev("0 + 36#0123456789abcdefghijklmnopqrstuvwxyz", "86846823611197163108337531226495015298096208677436155")
    ev("12345678901234567890 + 98765432109876543210", "111111111011111111100")

def test_exact_fractions():
    """Exact rational arithmetic and simplification across chained operations."""
    ev("1/2 + 1/3 + 1/6", "1")
    ev("2/3 - 1/6", "0.5")
    ev("(3/4)*(8/9)", "approx. 0.6666666667")
    ev("5/3", "approx. 1.6666666667")
    ev("22/7", "approx. 3.1428571429")
    ev("(1/2)/(1/4)", "2")

def test_exact_vs_approx_rendering():
    """The same exact rational renders as a 10-dp approximation by default but exactly via to-float."""
    ev("11/6", "approx. 1.8333333333")
    ev("11/6 to float", "1.8(3)")
    ev("7/12 to float", "0.58(3)")

def test_recurring_decimals_gauntlet():
    """Recurring-decimal detection across long periods, offsets, minimal-period, termination, and the inverse."""
    ev("1/17 to float", "0.(0588235294117647)")
    ev("1/19 to float", "0.(052631578947368421)")
    ev("1/23 to float", "0.(0434782608695652173913)")
    ev("2/7 to float", "0.(285714)")
    ev("3/14 to float", "0.2(142857)")
    ev("1/12 to float", "0.08(3)")
    ev("1/74 to float", "0.0(135)")
    ev("22/7 to float", "3.(142857)")
    ev("100/99 to float", "1.(01)")
    ev("41/333 to float", "0.(123)")
    ev("0.(33) to float", "0.(3)")
    ev("0.(0) to float", "0")
    ev("0.123(00) to float", "0.123")
    ev("0.58(3) to fraction", "7/12")
    ev("0.(09) to fraction", "1/11")

def test_mixed_and_improper_fractions():
    """Mixed-number parsing/arithmetic and conversion between mixed and improper display forms."""
    ev("4/3 to mixed_frac", "1 1/3")
    ev("5/2 to mixed_frac", "2 1/2")
    ev("7/3 to fraction", "7/3")
    ev("2 1/2 + 1 1/2", "4")
    ev("5 1/2 / 2", "2.75")
    ev("1 1/3 + 1 1/3 to fraction", "8/3")
    ev("3 3/4 - 1 1/4", "2.5")
    ev("-8 1/2", "-8.5")
    ev("1 2/3 + -4 5/6", "approx. -3.1666666667")

def test_unit_quantities_and_conversion():
    """Physical-unit quantities: unit-bearing conversion, dimension-tracking arithmetic (addition,
    dimensional products, scaling), and rejection of incompatible-dimension conversions."""
    ev("1 ft to cm", "30.48 cm")
    ev("1 mile to km", "1.609344 km")
    ev("1 GiB to bytes", "1073741824 bytes")
    ev("1 kg + 1 g", "1.001 kg")
    ev("2 m * 3 m", "6 m^2")
    ev("a = 4 kg; b = 2; a * b^2", "16 kg")
    err("1 m to kg")

def test_temperature_conversion():
    """Temperature conversion applies each scale's zero offset (not a bare ratio)."""
    ev("0 C to F", "32 °F")
    ev("100 C to F", "212 °F")

def test_decimal_formatting():
    """Decimal arithmetic with canonical trailing-zero-stripped formatting."""
    ev("0.1+0.2", "0.3")
    ev("2.50", "2.5")
    ev("3.14*2", "6.28")
    ev("10.0/4", "2.5")

def test_scientific_notation():
    """Scientific-notation input (e/E exponents) evaluated to plain decimals."""
    ev("1e-01", "0.1")
    ev("1E3", "1000")
    ev("1.5e-1", "0.15")
    ev("1.23e2", "123")

def test_number_base_parsing():
    """Parsing binary/octal/hex and explicit base-N literals (values via decimal where notation varies)."""
    ev("0x0000_00ff", "0xff")
    ev("6#100 to decimal", "36")
    ev("16#deadbeef to decimal", "3735928559")
    ev("12#bb to decimal", "143")
    ev("0xabcdef to decimal", "11259375")
    ev("0o17", "0o17")

def test_base_conversion():
    """Converting values between bases and base-preserving arithmetic between non-decimal literals."""
    ev("0x10ffff to decimal", "1114111")
    ev("65536 to hex", "10000")
    ev("123 to base 7", "234")
    ev("7#66 to decimal", "48")
    ev("0xa + 0xa", "0x14")
    ev("0b1111 * 0b10", "0b11110")

def test_base_parsing_gauntlet():
    """Robust non-decimal-literal parsing: exponent-vs-digit by base, letter digits, large bases (all to decimal)."""
    ev("0b1e10 to decimal", "4")
    ev("0b11e101 to decimal", "96")
    ev("0b1e1010 to decimal", "1024")
    ev("8#7e1 to decimal", "56")
    ev("8#1e2 to decimal", "64")
    ev("3#22e2 to decimal", "72")
    ev("16#2e3 to decimal", "739")
    ev("16#1e10 to decimal", "7696")
    ev("16#ace to decimal", "2766")
    ev("36#xyz to decimal", "44027")
    ev("6#5e2 to decimal", "180")
    ev("0o17e2 to decimal", "960")
    ev("0xdeadbeef to decimal", "3735928559")
    ev("0b10E100 to decimal", "32")

def test_digit_separators():
    """Underscore/comma digit separators are ignored between digits."""
    ev("123_456_789_123", "123456789123")
    ev("1.1_1", "1.11")
    ev("1,1", "11")
    ev("123,456,789,123", "123456789123")

def test_mathematical_constants():
    """Built-in constants pi/e/tau/phi and Greek-symbol spellings, shown to 10 dp."""
    ev("pi", "approx. 3.1415926536")
    ev("e", "approx. 2.7182818285")
    ev("tau", "approx. 6.2831853072")
    ev("phi", "approx. 1.6180339887")
    ev("\u03c0", "approx. 3.1415926536")
    ev("\u03c4", "approx. 6.2831853072")

def test_roots():
    """Square and cube roots: exact when the result is rational, else 10-dp approximation."""
    ev("sqrt 2", "approx. 1.4142135624")
    ev("sqrt 9", "3")
    ev("sqrt(144)", "12")
    ev("sqrt(2/8)", "0.5")
    ev("cbrt 8", "2")
    ev("cbrt 27", "3")

def test_exponentiation():
    """Exponentiation including negative powers and grouping."""
    ev("2^10", "1024")
    ev("2**10", "1024")
    ev("3^3", "27")
    ev("2^-2", "0.25")
    ev("10^3", "1000")

def test_exact_decimal_precision():
    """Exact negative-power decimals printed in full with all leading zeros (no truncation/mis-scaling)."""
    ev("2^-10", "0.0009765625")
    ev("2^-20", "0.00000095367431640625")
    ev("5^-15", "0.000000000032768")
    ev("4^-8", "0.0000152587890625")
    ev("8^-5", "0.000030517578125")
    ev("2^-50", "0.00000000000000088817841970012523233890533447265625")
    ev("10^-12", "0.000000000001")
    ev("5^-10", "0.0000001024")
    ev("2^-30", "0.000000000931322574615478515625")
    ev("2^-3^4", "0.000000000000000000000000413590306276513837435704346034981426782906055450439453125")

def test_fractional_exponents_and_roots():
    """Fractional exponents: exact roots when rational (incl. of fractions), else approximate."""
    ev("1000^(1/3)", "10")
    ev("64^(2/3)", "16")
    ev("(8/27)^(1/3)", "approx. 0.6666666667")
    ev("(125/8)^(1/3)", "2.5")
    ev("(343/8)^(1/3)", "3.5")
    ev("(1/8)^(2/3)", "0.25")
    ev("100000^(1/5)", "10")
    ev("(2/3)^(4/5)", "approx. 0.7229811808")

def test_logarithms_and_exp():
    """Natural/base-2/base-10 logarithms and the exponential function (irrational results, 10 dp)."""
    ev("ln 2", "approx. 0.6931471806")
    ev("exp 2", "approx. 7.3890560989")
    ev("exp 1", "approx. 2.7182818285")
    ev("ln 10", "approx. 2.3025850930")
    ev("log2 10", "approx. 3.3219280949")
    ev("log10 2", "approx. 0.3010299957")

def test_trig_functions():
    """Trigonometric and inverse-trig functions (approximate, 10 dp)."""
    ev("sin 1", "approx. 0.8414709848")
    ev("cos 1", "approx. 0.5403023059")
    ev("tan 1", "approx. 1.5574077247")
    ev("asin 0.5", "approx. 0.5235987756")
    ev("acos 0.5", "approx. 1.0471975512")
    ev("atan 1", "approx. 0.7853981634")
    ev("asin 1", "approx. 1.5707963268")
    ev("cos 2", "approx. -0.4161468365")

def test_hyperbolic_functions():
    """Hyperbolic functions (irrational results, 10 dp)."""
    ev("sinh 1", "approx. 1.1752011936")
    ev("cosh 1", "approx. 1.5430806348")
    ev("tanh 1", "approx. 0.7615941560")
    ev("sinh 2", "approx. 3.6268604078")
    ev("cosh 0.5", "approx. 1.1276259652")

def test_rounding_functions():
    """floor/ceil and round (half away from zero) with positive and negative inputs."""
    ev("floor(3.9)", "3")
    ev("floor(-3.1)", "-4")
    ev("ceil(3.3)", "4")
    ev("ceil(-3.9)", "-3")
    ev("round(3.7)", "4")
    ev("round(2.5)", "3")
    ev("round(-2.5)", "-3")
    ev("abs(-3.5)", "3.5")

def test_fibonacci():
    """Fibonacci function, including a bignum index."""
    ev("fib 10", "55")
    ev("fib 100", "354224848179261915075")

def test_complex_arithmetic():
    """Complex-number arithmetic with canonical a + bi display, including collapse of pure results."""
    ev("3i+4", "4 + 3i")
    ev("i*i", "-1")
    ev("i*i*i", "-i")
    ev("2i + 3i", "5i")
    ev("(1+i)*(1-i)", "2")
    ev("i+1", "1 + i")

def test_complex_powers():
    """Integer and complex powers of i, including the real-valued i^i."""
    ev("i^2", "-1")
    ev("i^3", "-i")
    ev("i^4", "1")
    ev("i^i", "approx. 0.2078795764")

def test_complex_advanced():
    """Complex division, reciprocal, modulus, conjugate, and real/imag/arg accessors."""
    ev("(2+3i)/(1-i)", "-0.5 + 2.5i")
    ev("(0.5 + 0.5i) * 2", "1 + i")
    ev("1/(1+i)", "0.5 - 0.5i")
    ev("conjugate(5-2i)", "5 + 2i")
    ev("abs(5+12i)", "13")
    ev("real(3+4i)", "3")
    ev("imag(3+4i)", "4")
    ev("arg(1+i)", "approx. 0.7853981634")

def test_complex_transcendental():
    """Functions extended to the complex domain: roots of negatives, complex exp/ln, complex powers."""
    ev("4^i", "approx. 0.1834569747 + 0.9830277404i")
    ev("2^i", "approx. 0.7692389014 + 0.6389612763i")
    ev("exp(i)", "approx. 0.5403023059 + 0.8414709848i")
    ev("i^(1/2)", "approx. 0.7071067812 + 0.7071067812i")
    ev("(1+i)^i", "approx. 0.4288290063 + 0.1548717525i")

def test_complex_fractions():
    """Complex components that are non-terminating rationals display in fraction form (unit on the
    numerator), not as 10-dp approximations; recurring parts render as mixed numbers."""
    ev("i/3", "i/3")
    ev("2i/3", "2i/3")
    ev("2i/-3-1", "-1 - 2i/3")
    ev("1.(3)i", "1 1/3 i")

def test_probability_distributions():
    """Dice distributions: dN, sums via convolution (m dN), percentage display, and expected value."""
    ev("mean(d6)", "3.5")
    ev("mean(2d6)", "7")
    ev("mean(3d6)", "10.5")
    ev("d6", "{ 1: 16.67%, 2: 16.67%, 3: 16.67%, 4: 16.67%, 5: 16.67%, 6: 16.67% }")
    ev("2d6", "{ 2: 2.78%, 3: 5.56%, 4: 8.33%, 5: 11.11%, 6: 13.89%, 7: 16.67%, 8: 13.89%, 9: 11.11%, 10: 8.33%, 11: 5.56%, 12: 2.78% }")

def test_variables_and_assignment():
    """Variable assignment, chaining, and reuse with implicit multiplication."""
    ev("a = b = 2; b", "2")
    ev("a = 3; a = a + 4a; a", "15")
    ev("a = 3; b = 2a; c = a * b; c + a", "21")
    ev("test_a = 5; test_a", "5")

def test_lambdas():
    """Lambda definition and application, including multi-argument (curried) selection."""
    ev("(x: x^2) 5", "25")
    ev("(x: y: x) 1 2", "1")
    ev("(x: y: z: y) 1 2 3", "2")
    ev("(x => x) 1", "1")
    ev("(\\x. y => x) 1 2", "1")

def test_lambdas_implicit():
    """Implicit-lambda form: applying a negated function."""
    ev("(-sqrt) 4", "-2")
    ev("(-sqrt) 9", "-3")
    ev("(-cbrt) 8", "-2")

def test_booleans_and_comparisons():
    """Boolean literals, logical not, and numeric equality/inequality."""
    ev("not true", "false")
    ev("not false", "true")
    ev("1 + 2 == 3", "true")
    ev("1 + 2 != 4", "true")
    ev("2 != 3", "true")
    ev("2 \u2260 3", "true")

def test_bitwise_operations():
    """Bitwise and/or/xor and shifts, preserving the operands' base, including large integers."""
    ev("255 | 34", "255")
    ev("0b0011 | 0b0101", "0b111")
    ev("(0xbeef & 255) to decimal", "239")
    ev("(0xcafe xor 0xf0f0) to decimal", "14862")
    ev("1 xor 1", "0")
    ev("54 << 1", "108")
    ev("54 >> 1", "27")

def test_combinatorics():
    """Combinations and permutations, including large values."""
    ev("5 nCr 2", "10")
    ev("5 choose 2", "10")
    ev("52 nCr 5", "2598960")
    ev("20 nCr 10", "184756")
    ev("17 nCr 5", "6188")
    ev("12 nPr 4", "11880")
    ev("100 nCr 2", "4950")

def test_modulo():
    """Modulo on integers, including large operands and modular exponentiation."""
    ev("100 mod 7", "2")
    ev("17 mod 5", "2")
    ev("2^10 mod 1000", "24")
    ev("2^32 mod 7", "4")
    ev("123456789 mod 97", "39")

def test_format_decimal_places():
    """Rounding output to N decimal places (trailing zeros stripped)."""
    ev("1.00000001 as 10 dp", "1.00000001")
    ev("1/3 to 5 dp", "approx. 0.33333")
    ev("100/7 to 4 dp", "approx. 14.2857")
    ev("0.123456789 to 6 dp", "approx. 0.123457")
    ev("1000.5 to 2 dp", "1000.5")

def test_format_significant_figures():
    """Rounding to N significant figures: integer carry, leading-zero counting, sub-unit values."""
    ev("1234567.55645 to 1 sf", "approx. 1000000")
    ev("1234567.55645 to 2 sf", "approx. 1200000")
    ev("1234567.55645 to 7 sf", "approx. 1234568")
    ev("1234567.55645 to 8 sf", "approx. 1234567.6")
    ev("123.9 to 3 sf", "approx. 124")
    ev("0.00555 to 2 sf", "approx. 0.0056")
    ev("pi / 1000000 to 3 sf", "approx. 0.00000314")

def test_statements_and_empty():
    """Statement sequences (;) yield the last value; the unit value prints empty."""
    ev("5; 10; 15", "15")
    ev("()", "")

def test_unicode_and_superscripts():
    """Unicode operator glyphs and superscript exponents."""
    ev("200\u00b2", "40000")
    ev("5 \u2212 2 \u2715 3 \u00d7 1 \u00f7 1 \u2215 3", "3")

def test_error_division_by_zero():
    """Division and modulo by zero are rejected."""
    err("1/0")
    err("0/0")
    err("-1/0")

def test_error_modulo_by_zero():
    """Modulo by zero is rejected."""
    err("5 mod 0")

def test_error_invalid_base():
    """Out-of-range or non-integer bases are rejected."""
    err("0#0")
    err("1#0")
    err("5 to base 1")
    err("5 to base (-5)")
    err("5 to base 1.5")
    err("5 to base pi")
    err("5 to base 1000000000")

def test_error_domain_and_factorial():
    """Domain errors and factorial of unsupported operands are rejected."""
    err("0.5!")
    err("(-2)!")
    err("3i!")
    err("ln 0")

def test_error_digit_separators():
    """Misplaced digit separators (not strictly between digits) are rejected."""
    err("1__1")
    err("1_.1")
    err("_1")
    err("1_")

def test_error_parse():
    """Malformed input (empty recurring block, dangling/duplicated operators, bad application) is rejected."""
    err("0.()")
    err("1 +")
    err("3 + * 4")

def test_long_period_recurring_gauntlet():
    """Long-period recurring decimals via `to float`: exact bignum long division + uncapped cycle
    detection. The minimal repeating block must be emitted in full (96- and 272-digit periods), so a
    fixed-width / capped / float-based remainder implementation produces a wrong or truncated value."""
    ev("1/97 to float", "0.(010309278350515463917525773195876288659793814432989690721649484536082474226804123711340206185567)")
    ev("1/289 to float", "0.(00346020761245674740484429065743944636678200692041522491349480968858131487889273356401384083044982698961937716262975778546712802768166089965397923875432525951557093425605536332179930795847750865051903114186851211072664359861591695501730103806228373702422145328719723183391)")
    ev("1/49 to float", "0.(020408163265306122448979591836734693877551)")
    ev("1/27 to float", "0.(037)")

def test_recurring_to_fraction_gauntlet():
    """Recurring-decimal -> fraction inversion (closed form digits/(base^k - 1) with a prefix shift),
    in fully reduced form. Includes the 0.(9) = 1 collapse and prefix/leading-zero-in-period cases."""
    ev("0.(9) to fraction", "1")
    ev("0.0(135) to fraction", "1/74")
    ev("0.1(6) to fraction", "1/6")
    ev("0.(142857) to fraction", "1/7")

def test_error_grammar():
    """Mixed-number grammar restrictions and the 0^0 domain error are rejected, not silently accepted."""
    err("0^0")
    err("1/1 1/2")
    err("1 2/3^2")
    err("1 2/-3")
    err("pi 1 1/2")
