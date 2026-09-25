// Hidden E2E grading suite for the apd (arbitrary-precision decimal) WRG task.
//
// External `apd_test` package: it imports the module under test through its public API only
// (github.com/cockroachdb/apd/v3) and asserts documented, observable behavior — result values and
// Condition-flag *semantics* (via the predicate methods), never the surface string form of
// Condition or a specific trailing-zero representation. One top-level func Test == one CTRF entry
// (no subtests).
package apd_test

import (
	"testing"

	apd "github.com/cockroachdb/apd/v3"
)

// ---- helpers ----

// ctx builds a Context with the given precision/rounding and the package exponent limits. Traps is
// left zero so operations report Condition flags instead of returning errors.
func ctx(prec uint32, r apd.Rounder) *apd.Context {
	return &apd.Context{Precision: prec, Rounding: r, MaxExponent: apd.MaxExponent, MinExponent: apd.MinExponent}
}

// d parses s with BaseContext (no rounding); it fails the test on a parse error.
func d(t *testing.T, s string) *apd.Decimal {
	t.Helper()
	x, _, err := apd.NewFromString(s)
	if err != nil {
		t.Fatalf("NewFromString(%q): %v", s, err)
	}
	return x
}

// run executes a Context operation into a fresh Decimal and returns the result and its Condition.
func run(t *testing.T, fn func(o *apd.Decimal) (apd.Condition, error)) (*apd.Decimal, apd.Condition) {
	t.Helper()
	var o apd.Decimal
	cond, _ := fn(&o)
	return &o, cond
}

// str asserts the exact String() form (used only for formatting and irrational values whose
// significant digits are fully determined by the requested precision).
func str(t *testing.T, what, got, want string) {
	t.Helper()
	if got != want {
		t.Errorf("%s: got %q, want %q", what, got, want)
	}
}

// num asserts numeric equality via Cmp, so a result is accepted regardless of trailing-zero
// representation (e.g. "3" vs "3.000000000000000").
func num(t *testing.T, what string, got, want *apd.Decimal) {
	t.Helper()
	if got.Cmp(want) != 0 {
		t.Errorf("%s: got %s, want value %s", what, got.String(), want.String())
	}
}

// flag asserts a Condition predicate (semantic flag), independent of Condition's string form.
func flag(t *testing.T, what string, got, want bool) {
	t.Helper()
	if got != want {
		t.Errorf("%s: flag = %v, want %v", what, got, want)
	}
}

// ---- tests ----

func TestParseAndStringFormatting(t *testing.T) {
	x := apd.New(1234, -2) // 12.34
	str(t, "Text e", x.Text('e'), "1.234e+1")
	str(t, "Text E", x.Text('E'), "1.234E+1")
	str(t, "Text f", x.Text('f'), "12.34")
	str(t, "Text g", x.Text('g'), "12.34")
	str(t, "Text G", x.Text('G'), "12.34")

	str(t, "String 1.230", apd.New(1230, -3).String(), "1.230")
	str(t, "String 1.23", apd.New(123, -2).String(), "1.23")
	str(t, "String 5E-7", apd.New(5, -7).String(), "5E-7")
	str(t, "String 0", apd.New(0, 0).String(), "0")
	str(t, "Text -6 e", apd.New(-6, 0).Text('e'), "-6e+0")

	str(t, "parse 1.5E3", d(t, "1.5E3").String(), "1.5E+3")
	str(t, "parse 123E4", d(t, "123E4").String(), "1.23E+6")
	str(t, "parse 0.0000005", d(t, "0.0000005").String(), "5E-7")
	str(t, "parse Infinity", d(t, "Infinity").String(), "Infinity")

	// Round-trip: SetString(String()) reproduces the same representation.
	orig := apd.New(1230, -3)
	if orig.CmpTotal(d(t, orig.String())) != 0 {
		t.Errorf("round-trip CmpTotal failed for %s", orig)
	}
}

func TestNumDigitsAndReduce(t *testing.T) {
	if n := apd.New(1230, -3).NumDigits(); n != 4 {
		t.Errorf("NumDigits(1.230): got %d, want 4", n)
	}
	var r apd.Decimal
	_, removed := r.Reduce(apd.New(12300, -4)) // 1.2300
	num(t, "Reduce value", &r, apd.New(123, -2))
	if removed != 2 {
		t.Errorf("Reduce removed: got %d, want 2", removed)
	}
	// Reducing any zero yields 0.
	var rz apd.Decimal
	rz.Reduce(d(t, "0.000"))
	num(t, "Reduce 0.000", &rz, apd.New(0, 0))
	// Neg normalizes -0 to +0.
	var nz apd.Decimal
	nz.Neg(d(t, "-0"))
	str(t, "Neg(-0)", nz.String(), "0")
}

func TestCmpNumericAndTotal(t *testing.T) {
	if c := apd.New(120, -2).Cmp(apd.New(12, -1)); c != 0 { // 1.20 == 1.2 numerically
		t.Errorf("Cmp(1.20, 1.2): got %d, want 0", c)
	}
	if c := apd.New(12300, -4).CmpTotal(apd.New(123, -2)); c != -1 { // 1.2300 sorts below 1.23
		t.Errorf("CmpTotal(1.2300, 1.23): got %d, want -1", c)
	}
	if c := apd.New(1, 0).Cmp(apd.New(2, 0)); c != -1 {
		t.Errorf("Cmp(1, 2): got %d, want -1", c)
	}
	if c := d(t, "Infinity").Cmp(apd.New(99999, 0)); c != 1 {
		t.Errorf("Cmp(Inf, 99999): got %d, want 1", c)
	}
	if c := d(t, "-Infinity").Cmp(d(t, "Infinity")); c != -1 {
		t.Errorf("Cmp(-Inf, Inf): got %d, want -1", c)
	}
}

func TestAddSubRounding(t *testing.T) {
	o, c := run(t, func(o *apd.Decimal) (apd.Condition, error) {
		return ctx(4, apd.RoundHalfEven).Add(o, apd.New(12345, 0), apd.New(678, 0))
	})
	str(t, "Add 12345+678 p4 he", o.String(), "1.302E+4")
	flag(t, "Add inexact", c.Inexact(), true)

	o, c = run(t, func(o *apd.Decimal) (apd.Condition, error) {
		return ctx(5, apd.RoundHalfEven).Sub(o, apd.New(5, 0), apd.New(3, 0))
	})
	num(t, "Sub 5-3", o, apd.New(2, 0))
	flag(t, "Sub exact", c.Inexact(), false)

	// Exact opposites: +0 unless RoundFloor gives -0.
	o, _ = run(t, func(o *apd.Decimal) (apd.Condition, error) {
		return ctx(5, apd.RoundHalfEven).Add(o, apd.New(2, 0), apd.New(-2, 0))
	})
	str(t, "Add 2+(-2) he sign", o.String(), "0")
	o, _ = run(t, func(o *apd.Decimal) (apd.Condition, error) {
		return ctx(5, apd.RoundFloor).Add(o, apd.New(2, 0), apd.New(-2, 0))
	})
	str(t, "Add 2+(-2) floor sign", o.String(), "-0")
}

func TestMulRounding(t *testing.T) {
	o, c := run(t, func(o *apd.Decimal) (apd.Condition, error) {
		return ctx(3, apd.RoundHalfUp).Mul(o, d(t, "1.23"), d(t, "4.56"))
	})
	str(t, "Mul 1.23*4.56 p3 hu", o.String(), "5.61")
	flag(t, "Mul inexact", c.Inexact(), true)

	o, c = run(t, func(o *apd.Decimal) (apd.Condition, error) {
		return ctx(5, apd.RoundHalfEven).Mul(o, apd.New(2, 0), apd.New(3, 0))
	})
	num(t, "Mul 2*3", o, apd.New(6, 0))
	flag(t, "Mul exact", c.Inexact(), false)
}

func TestQuoRoundingAndSpecials(t *testing.T) {
	o, c := run(t, func(o *apd.Decimal) (apd.Condition, error) {
		return ctx(5, apd.RoundHalfEven).Quo(o, apd.New(1, 0), apd.New(3, 0))
	})
	num(t, "Quo 1/3 he", o, d(t, "0.33333"))
	flag(t, "Quo 1/3 he inexact", c.Inexact(), true)

	o, _ = run(t, func(o *apd.Decimal) (apd.Condition, error) {
		return ctx(5, apd.RoundUp).Quo(o, apd.New(1, 0), apd.New(3, 0))
	})
	num(t, "Quo 1/3 up", o, d(t, "0.33334"))

	o, c = run(t, func(o *apd.Decimal) (apd.Condition, error) {
		return ctx(10, apd.RoundHalfEven).Quo(o, apd.New(10, 0), apd.New(4, 0))
	})
	num(t, "Quo 10/4", o, d(t, "2.5"))
	flag(t, "Quo 10/4 exact", c.Inexact(), false)

	o, c = run(t, func(o *apd.Decimal) (apd.Condition, error) {
		return ctx(5, apd.RoundHalfEven).Quo(o, apd.New(1, 0), apd.New(0, 0))
	})
	str(t, "Quo 1/0", o.String(), "Infinity")
	flag(t, "Quo 1/0 divByZero", c.DivisionByZero(), true)

	o, c = run(t, func(o *apd.Decimal) (apd.Condition, error) {
		return ctx(5, apd.RoundHalfEven).Quo(o, apd.New(0, 0), apd.New(0, 0))
	})
	str(t, "Quo 0/0", o.String(), "NaN")
	flag(t, "Quo 0/0 divUndefined", c.DivisionUndefined(), true)
}

func TestQuoIntegerAndRem(t *testing.T) {
	o, _ := run(t, func(o *apd.Decimal) (apd.Condition, error) {
		return ctx(5, apd.RoundHalfEven).QuoInteger(o, apd.New(7, 0), apd.New(2, 0))
	})
	num(t, "QuoInteger 7/2", o, apd.New(3, 0))

	o, c := run(t, func(o *apd.Decimal) (apd.Condition, error) {
		return ctx(1, apd.RoundHalfEven).QuoInteger(o, apd.New(100, 0), apd.New(1, 0))
	})
	str(t, "QuoInteger 100/1 p1", o.String(), "NaN")
	flag(t, "QuoInteger divImpossible", c.DivisionImpossible(), true)

	o, _ = run(t, func(o *apd.Decimal) (apd.Condition, error) {
		return ctx(5, apd.RoundHalfEven).Rem(o, apd.New(7, 0), apd.New(3, 0))
	})
	num(t, "Rem 7/3", o, apd.New(1, 0))
	o, _ = run(t, func(o *apd.Decimal) (apd.Condition, error) {
		return ctx(5, apd.RoundHalfEven).Rem(o, apd.New(-7, 0), apd.New(3, 0))
	})
	num(t, "Rem -7/3 (sign of dividend)", o, apd.New(-1, 0))
	o, _ = run(t, func(o *apd.Decimal) (apd.Condition, error) {
		return ctx(5, apd.RoundHalfEven).Rem(o, apd.New(7, 0), apd.New(-3, 0))
	})
	num(t, "Rem 7/-3 (sign of dividend)", o, apd.New(1, 0))

	// Rem is DivisionImpossible when the integer quotient needs more than Precision digits.
	o, c = run(t, func(o *apd.Decimal) (apd.Condition, error) {
		return ctx(1, apd.RoundHalfEven).Rem(o, apd.New(100, 0), apd.New(3, 0))
	})
	str(t, "Rem 100/3 p1", o.String(), "NaN")
	flag(t, "Rem 100/3 p1 divImpossible", c.DivisionImpossible(), true)
}

func TestRoundingModes(t *testing.T) {
	type mode struct {
		r    apd.Rounder
		want string
	}
	cases := map[string][]mode{
		"2.5": {{apd.RoundDown, "2"}, {apd.RoundHalfUp, "3"}, {apd.RoundHalfEven, "2"}, {apd.RoundCeiling, "3"},
			{apd.RoundFloor, "2"}, {apd.RoundHalfDown, "2"}, {apd.RoundUp, "3"}, {apd.Round05Up, "2"}},
		"1.5": {{apd.RoundDown, "1"}, {apd.RoundHalfUp, "2"}, {apd.RoundHalfEven, "2"}, {apd.RoundCeiling, "2"},
			{apd.RoundFloor, "1"}, {apd.RoundHalfDown, "1"}, {apd.RoundUp, "2"}, {apd.Round05Up, "1"}},
		"-2.5": {{apd.RoundDown, "-2"}, {apd.RoundHalfUp, "-3"}, {apd.RoundHalfEven, "-2"}, {apd.RoundCeiling, "-2"},
			{apd.RoundFloor, "-3"}, {apd.RoundHalfDown, "-2"}, {apd.RoundUp, "-3"}, {apd.Round05Up, "-2"}},
		"2.05": {{apd.RoundDown, "2"}, {apd.RoundHalfUp, "2"}, {apd.RoundHalfEven, "2"}, {apd.RoundCeiling, "3"},
			{apd.RoundFloor, "2"}, {apd.RoundHalfDown, "2"}, {apd.RoundUp, "3"}, {apd.Round05Up, "2"}},
	}
	for val, modes := range cases {
		for _, m := range modes {
			o, c := run(t, func(o *apd.Decimal) (apd.Condition, error) {
				return ctx(10, m.r).Quantize(o, d(t, val), 0)
			})
			num(t, "Quantize("+val+","+string(m.r)+")", o, d(t, m.want))
			flag(t, "Quantize("+val+","+string(m.r)+") inexact", c.Inexact(), true)
		}
	}
}

func TestRound05Up(t *testing.T) {
	// Round05Up rounds away from zero ONLY when the kept last digit would become 0 or 5; otherwise
	// it truncates. All inputs here round to an integer (exponent 0).
	for _, tc := range []struct{ in, want string }{
		{"5.7", "6"},  // kept digit 5 -> add one
		{"0.7", "1"},  // kept digit 0 -> add one
		{"5.2", "6"},  // kept digit 5 -> add one
		{"1.7", "1"},  // kept digit 1 -> truncate
		{"2.7", "2"},  // kept digit 2 -> truncate
		{"4.7", "4"},  // kept digit 4 -> truncate
		{"-5.7", "-6"},
		{"-0.7", "-1"},
	} {
		o, c := run(t, func(o *apd.Decimal) (apd.Condition, error) {
			return ctx(10, apd.Round05Up).Quantize(o, d(t, tc.in), 0)
		})
		num(t, "Round05Up "+tc.in, o, d(t, tc.want))
		flag(t, "Round05Up "+tc.in+" inexact", c.Inexact(), true)
	}
}

func TestQuantize(t *testing.T) {
	o, c := run(t, func(o *apd.Decimal) (apd.Condition, error) {
		return ctx(5, apd.RoundHalfEven).Quantize(o, d(t, "2.17"), -1)
	})
	str(t, "Quantize 2.17 -> -1 he", o.String(), "2.2")
	flag(t, "Quantize 2.17 inexact", c.Inexact(), true)

	// Result would need more than Precision digits -> NaN + InvalidOperation.
	o, c = run(t, func(o *apd.Decimal) (apd.Condition, error) {
		return ctx(3, apd.RoundHalfEven).Quantize(o, apd.New(1234, 0), -1)
	})
	str(t, "Quantize 1234 -> -1 p3", o.String(), "NaN")
	flag(t, "Quantize overflow invalid", c.InvalidOperation(), true)

	// Adding scale to an exact value: exponent set, value unchanged.
	o, _ = run(t, func(o *apd.Decimal) (apd.Condition, error) {
		return ctx(5, apd.RoundHalfEven).Quantize(o, d(t, "2.5"), -2)
	})
	str(t, "Quantize 2.5 -> -2 he", o.String(), "2.50")

	// Quantizing to an exponent below the subnormal floor (Etiny) -> NaN + InvalidOperation.
	sc := &apd.Context{Precision: 5, MaxExponent: 96, MinExponent: -95, Rounding: apd.RoundHalfEven}
	o, c = run(t, func(o *apd.Decimal) (apd.Condition, error) { return sc.Quantize(o, apd.New(1, 0), -200) })
	str(t, "Quantize below Etiny", o.String(), "NaN")
	flag(t, "Quantize below Etiny invalid", c.InvalidOperation(), true)
}

func TestRoundToIntegralCeilFloor(t *testing.T) {
	o, c := run(t, func(o *apd.Decimal) (apd.Condition, error) {
		return ctx(10, apd.RoundHalfEven).RoundToIntegralValue(o, d(t, "2.5"))
	})
	num(t, "RoundToIntegralValue 2.5", o, apd.New(2, 0))
	flag(t, "RoundToIntegralValue clears inexact", c.Inexact(), false)

	o, c = run(t, func(o *apd.Decimal) (apd.Condition, error) {
		return ctx(10, apd.RoundHalfEven).RoundToIntegralExact(o, d(t, "2.5"))
	})
	num(t, "RoundToIntegralExact 2.5", o, apd.New(2, 0))
	flag(t, "RoundToIntegralExact reports inexact", c.Inexact(), true)

	for _, tc := range []struct {
		name, in, want string
		ceil           bool
	}{
		{"Ceil 2.1", "2.1", "3", true},
		{"Floor 2.9", "2.9", "2", false},
		{"Ceil -2.1", "-2.1", "-2", true},
		{"Floor -2.1", "-2.1", "-3", false},
	} {
		o, _ := run(t, func(o *apd.Decimal) (apd.Condition, error) {
			if tc.ceil {
				return ctx(10, apd.RoundHalfEven).Ceil(o, d(t, tc.in))
			}
			return ctx(10, apd.RoundHalfEven).Floor(o, d(t, tc.in))
		})
		num(t, tc.name, o, d(t, tc.want))
	}
}

func TestSqrt(t *testing.T) {
	o, c := run(t, func(o *apd.Decimal) (apd.Condition, error) {
		return ctx(16, apd.RoundHalfEven).Sqrt(o, apd.New(2, 0))
	})
	str(t, "Sqrt 2 p16 (correctly rounded)", o.String(), "1.414213562373095")
	flag(t, "Sqrt 2 inexact", c.Inexact(), true)

	o, c = run(t, func(o *apd.Decimal) (apd.Condition, error) {
		return ctx(16, apd.RoundHalfEven).Sqrt(o, apd.New(9, 0))
	})
	num(t, "Sqrt 9", o, apd.New(3, 0))
	flag(t, "Sqrt 9 exact", c.Inexact(), false)

	o, _ = run(t, func(o *apd.Decimal) (apd.Condition, error) {
		return ctx(16, apd.RoundHalfEven).Sqrt(o, apd.New(0, 0))
	})
	num(t, "Sqrt 0", o, apd.New(0, 0))

	o, c = run(t, func(o *apd.Decimal) (apd.Condition, error) {
		return ctx(16, apd.RoundHalfEven).Sqrt(o, apd.New(-1, 0))
	})
	str(t, "Sqrt -1", o.String(), "NaN")
	flag(t, "Sqrt -1 invalid", c.InvalidOperation(), true)
}

func TestCbrt(t *testing.T) {
	o, _ := run(t, func(o *apd.Decimal) (apd.Condition, error) {
		return ctx(16, apd.RoundHalfEven).Cbrt(o, apd.New(27, 0))
	})
	num(t, "Cbrt 27", o, apd.New(3, 0))

	o, _ = run(t, func(o *apd.Decimal) (apd.Condition, error) {
		return ctx(16, apd.RoundHalfEven).Cbrt(o, apd.New(-8, 0))
	})
	num(t, "Cbrt -8", o, apd.New(-2, 0))

	o, c := run(t, func(o *apd.Decimal) (apd.Condition, error) {
		return ctx(16, apd.RoundHalfEven).Cbrt(o, apd.New(2, 0))
	})
	str(t, "Cbrt 2 p16 (correctly rounded)", o.String(), "1.259921049894873")
	flag(t, "Cbrt 2 inexact", c.Inexact(), true)
}

func TestExp(t *testing.T) {
	o, c := run(t, func(o *apd.Decimal) (apd.Condition, error) {
		return ctx(16, apd.RoundHalfEven).Exp(o, apd.New(1, 0))
	})
	str(t, "Exp 1 p16 (correctly rounded)", o.String(), "2.718281828459045")
	flag(t, "Exp 1 inexact", c.Inexact(), true)

	o, _ = run(t, func(o *apd.Decimal) (apd.Condition, error) {
		return ctx(16, apd.RoundHalfEven).Exp(o, apd.New(0, 0))
	})
	num(t, "Exp 0", o, apd.New(1, 0))

	o, _ = run(t, func(o *apd.Decimal) (apd.Condition, error) {
		return ctx(16, apd.RoundHalfEven).Exp(o, d(t, "-Infinity"))
	})
	num(t, "Exp -Inf", o, apd.New(0, 0))
}

func TestLn(t *testing.T) {
	o, c := run(t, func(o *apd.Decimal) (apd.Condition, error) {
		return ctx(16, apd.RoundHalfEven).Ln(o, apd.New(10, 0))
	})
	str(t, "Ln 10 p16 (correctly rounded)", o.String(), "2.302585092994046")
	flag(t, "Ln 10 inexact", c.Inexact(), true)

	o, _ = run(t, func(o *apd.Decimal) (apd.Condition, error) {
		return ctx(16, apd.RoundHalfEven).Ln(o, apd.New(1, 0))
	})
	num(t, "Ln 1", o, apd.New(0, 0))

	o, _ = run(t, func(o *apd.Decimal) (apd.Condition, error) {
		return ctx(16, apd.RoundHalfEven).Ln(o, apd.New(0, 0))
	})
	str(t, "Ln 0", o.String(), "-Infinity")

	o, c = run(t, func(o *apd.Decimal) (apd.Condition, error) {
		return ctx(16, apd.RoundHalfEven).Ln(o, apd.New(-1, 0))
	})
	str(t, "Ln -1", o.String(), "NaN")
	flag(t, "Ln -1 invalid", c.InvalidOperation(), true)
}

func TestPow(t *testing.T) {
	o, _ := run(t, func(o *apd.Decimal) (apd.Condition, error) {
		return ctx(16, apd.RoundHalfEven).Pow(o, apd.New(2, 0), apd.New(10, 0))
	})
	num(t, "Pow 2^10", o, apd.New(1024, 0))

	o, c := run(t, func(o *apd.Decimal) (apd.Condition, error) {
		return ctx(16, apd.RoundHalfEven).Pow(o, apd.New(2, 0), d(t, "0.5"))
	})
	str(t, "Pow 2^0.5 (correctly rounded)", o.String(), "1.414213562373095")
	flag(t, "Pow 2^0.5 inexact", c.Inexact(), true)

	o, _ = run(t, func(o *apd.Decimal) (apd.Condition, error) {
		return ctx(16, apd.RoundHalfEven).Pow(o, apd.New(9, 0), d(t, "0.5"))
	})
	num(t, "Pow 9^0.5", o, apd.New(3, 0))

	o, _ = run(t, func(o *apd.Decimal) (apd.Condition, error) {
		return ctx(16, apd.RoundHalfEven).Pow(o, apd.New(5, 0), apd.New(0, 0))
	})
	num(t, "Pow 5^0", o, apd.New(1, 0))

	o, c = run(t, func(o *apd.Decimal) (apd.Condition, error) {
		return ctx(16, apd.RoundHalfEven).Pow(o, apd.New(0, 0), apd.New(0, 0))
	})
	str(t, "Pow 0^0", o.String(), "NaN")
	flag(t, "Pow 0^0 invalid", c.InvalidOperation(), true)

	o, c = run(t, func(o *apd.Decimal) (apd.Condition, error) {
		return ctx(16, apd.RoundHalfEven).Pow(o, apd.New(-2, 0), d(t, "0.5"))
	})
	str(t, "Pow -2^0.5", o.String(), "NaN")
	flag(t, "Pow -2^0.5 invalid", c.InvalidOperation(), true)

	o, _ = run(t, func(o *apd.Decimal) (apd.Condition, error) {
		return ctx(16, apd.RoundHalfEven).Pow(o, apd.New(2, 0), apd.New(-2, 0))
	})
	num(t, "Pow 2^-2", o, d(t, "0.25"))
}

func TestInt64Float64(t *testing.T) {
	if v, err := apd.New(12300, 0).Int64(); err != nil || v != 12300 {
		t.Errorf("Int64(12300): got %d, err=%v", v, err)
	}
	if _, err := d(t, "1.5").Int64(); err == nil {
		t.Errorf("Int64(1.5): expected error for fractional value")
	}
	if f, err := d(t, "1.5").Float64(); err != nil || f != 1.5 {
		t.Errorf("Float64(1.5): got %v, err=%v", f, err)
	}
	// SetFloat64 stores the exact decimal value of the float.
	var sf apd.Decimal
	if _, err := sf.SetFloat64(1.5); err != nil || sf.Cmp(apd.New(15, -1)) != 0 {
		t.Errorf("SetFloat64(1.5): got %s, err=%v", sf.String(), err)
	}
	if _, err := sf.SetFloat64(0.5); err != nil || sf.Cmp(apd.New(5, -1)) != 0 {
		t.Errorf("SetFloat64(0.5): got %s, err=%v", sf.String(), err)
	}
}

func TestSpecialValues(t *testing.T) {
	o, _ := run(t, func(o *apd.Decimal) (apd.Condition, error) {
		return ctx(5, apd.RoundHalfEven).Add(o, d(t, "NaN"), apd.New(1, 0))
	})
	str(t, "Add NaN+1", o.String(), "NaN")

	o, _ = run(t, func(o *apd.Decimal) (apd.Condition, error) {
		return ctx(5, apd.RoundHalfEven).Add(o, d(t, "Infinity"), d(t, "Infinity"))
	})
	str(t, "Add Inf+Inf", o.String(), "Infinity")

	o, c := run(t, func(o *apd.Decimal) (apd.Condition, error) {
		return ctx(5, apd.RoundHalfEven).Sub(o, d(t, "Infinity"), d(t, "Infinity"))
	})
	str(t, "Sub Inf-Inf", o.String(), "NaN")
	flag(t, "Sub Inf-Inf invalid", c.InvalidOperation(), true)

	o, c = run(t, func(o *apd.Decimal) (apd.Condition, error) {
		return ctx(5, apd.RoundHalfEven).Add(o, d(t, "sNaN"), apd.New(1, 0))
	})
	str(t, "Add sNaN+1", o.String(), "NaN")
	flag(t, "Add sNaN+1 invalid", c.InvalidOperation(), true)

	o, c = run(t, func(o *apd.Decimal) (apd.Condition, error) {
		return ctx(5, apd.RoundHalfEven).Mul(o, d(t, "Infinity"), apd.New(0, 0))
	})
	str(t, "Mul Inf*0", o.String(), "NaN")
	flag(t, "Mul Inf*0 invalid", c.InvalidOperation(), true)

	// A signaling NaN operand dominates a quiet NaN: result is NaN + InvalidOperation.
	o, c = run(t, func(o *apd.Decimal) (apd.Condition, error) {
		return ctx(5, apd.RoundHalfEven).Add(o, d(t, "sNaN"), d(t, "NaN"))
	})
	str(t, "Add sNaN+NaN", o.String(), "NaN")
	flag(t, "Add sNaN+NaN invalid", c.InvalidOperation(), true)
}

func TestCmpTotalFullOrder(t *testing.T) {
	lt := func(a, b string) {
		if d(t, a).CmpTotal(d(t, b)) >= 0 {
			t.Errorf("CmpTotal(%s, %s) should be < 0", a, b)
		}
	}
	lt("-Infinity", "-1")   // -Infinity below all finite
	lt("-1", "0")           // negative below zero
	lt("-0", "0")           // -0 sorts below +0 in the total order
	lt("1.2300", "1.23")    // equal value, larger exponent sorts higher
	lt("1", "Infinity")     // finite below +Infinity
	lt("Infinity", "sNaN")  // +Infinity below sNaN
	lt("sNaN", "NaN")       // sNaN below NaN
	if d(t, "1.23").CmpTotal(d(t, "1.23")) != 0 {
		t.Errorf("CmpTotal of identical representations should be 0")
	}
	// Negative special forms sort below all finite negatives, mirroring the positive order.
	lt("-NaN", "-sNaN")     // -NaN is the minimum of the total order
	lt("-sNaN", "-Infinity")
	lt("-NaN", "-Infinity")
	if d(t, "NaN").CmpTotal(d(t, "-NaN")) <= 0 { // NaN is the maximum, -NaN the minimum
		t.Errorf("CmpTotal(NaN, -NaN) should be > 0")
	}
}

func TestFormattingExponentBoundary(t *testing.T) {
	// String() uses positional form when Exponent<=0 and adjusted exponent>=-6, else scientific.
	str(t, "New(1,-6)", apd.New(1, -6).String(), "0.000001")
	str(t, "New(1,-7)", apd.New(1, -7).String(), "1E-7")
	str(t, "New(123,5)", apd.New(123, 5).String(), "1.23E+7")
	str(t, "New(-45,-8)", apd.New(-45, -8).String(), "-4.5E-7")
	str(t, "New(1,6)", apd.New(1, 6).String(), "1E+6")
}

func TestMixedScaleDivision(t *testing.T) {
	hc := ctx(10, apd.RoundHalfEven)
	o, _ := run(t, func(o *apd.Decimal) (apd.Condition, error) { return hc.QuoInteger(o, d(t, "7.5"), d(t, "0.5")) })
	num(t, "QuoInteger 7.5/0.5", o, apd.New(15, 0))

	o, _ = run(t, func(o *apd.Decimal) (apd.Condition, error) { return hc.Rem(o, d(t, "7.5"), apd.New(2, 0)) })
	num(t, "Rem 7.5/2", o, d(t, "1.5"))

	o, c := run(t, func(o *apd.Decimal) (apd.Condition, error) { return hc.Quantize(o, apd.New(12345, 0), 2) })
	num(t, "Quantize 12345 -> +2", o, apd.New(123, 2)) // 12300
	flag(t, "Quantize 12345 -> +2 inexact", c.Inexact(), true)

	o, _ = run(t, func(o *apd.Decimal) (apd.Condition, error) { return hc.Quantize(o, d(t, "2.5"), 0) })
	num(t, "Quantize 2.5 -> 0 he", o, apd.New(2, 0))
}

func TestSubnormalUnderflow(t *testing.T) {
	// decimal32-like range: Emax 96, Emin -95, precision 7. A finite result whose adjusted
	// exponent is below MinExponent is subnormal.
	sc := &apd.Context{Precision: 7, MaxExponent: 96, MinExponent: -95, Rounding: apd.RoundHalfEven}
	o, c := run(t, func(o *apd.Decimal) (apd.Condition, error) { return sc.Mul(o, d(t, "1E-50"), d(t, "1E-50")) })
	num(t, "Mul 1E-50^2 (subnormal)", o, d(t, "1E-100"))
	flag(t, "Mul subnormal flag", c.Subnormal(), true)

	o, c = run(t, func(o *apd.Decimal) (apd.Condition, error) { return sc.Quo(o, apd.New(1, 0), d(t, "1E100")) })
	num(t, "Quo 1/1E100 (subnormal)", o, d(t, "1E-100"))
	flag(t, "Quo subnormal flag", c.Subnormal(), true)
}

func TestModf(t *testing.T) {
	// Modf splits a value into its truncated-toward-zero integer part (exponent >= 0) and the
	// fractional remainder (exponent <= 0); both parts share the sign of the input and sum back to
	// it. Cases cover the no-fraction, integer-part-zero, and general split branches.
	for _, tc := range []struct{ in, integ, frac string }{
		{"3.75", "3", "0.75"},
		{"-3.75", "-3", "-0.75"},
		{"12", "12", "0"},
		{"1.2E3", "1200", "0"},
		{"0.25", "0", "0.25"},
		{"-0.5", "0", "-0.5"},
		{"0.001", "0", "0.001"},
	} {
		var integ, frac apd.Decimal
		d(t, tc.in).Modf(&integ, &frac)
		num(t, "Modf("+tc.in+") integ", &integ, d(t, tc.integ))
		num(t, "Modf("+tc.in+") frac", &frac, d(t, tc.frac))
		var sum apd.Decimal
		if _, err := ctx(20, apd.RoundHalfEven).Add(&sum, &integ, &frac); err != nil {
			t.Fatalf("Modf(%s) Add(integ,frac): %v", tc.in, err)
		}
		num(t, "Modf("+tc.in+") integ+frac", &sum, d(t, tc.in))
	}
}

func TestRoundLargeNumber(t *testing.T) {
	o, c := run(t, func(o *apd.Decimal) (apd.Condition, error) {
		return ctx(3, apd.RoundHalfEven).Round(o, apd.New(123456, 0))
	})
	num(t, "Round 123456 p3", o, apd.New(123, 3)) // 123000
	flag(t, "Round 123456 inexact", c.Inexact(), true)
}

func TestNegativeIntegerPow(t *testing.T) {
	hc := ctx(16, apd.RoundHalfEven)
	o, _ := run(t, func(o *apd.Decimal) (apd.Condition, error) { return hc.Pow(o, apd.New(2, 0), apd.New(-10, 0)) })
	num(t, "Pow 2^-10", o, d(t, "0.0009765625"))
	o, _ = run(t, func(o *apd.Decimal) (apd.Condition, error) { return hc.Pow(o, apd.New(10, 0), apd.New(-3, 0)) })
	num(t, "Pow 10^-3", o, d(t, "0.001"))
	o, _ = run(t, func(o *apd.Decimal) (apd.Condition, error) { return hc.Pow(o, apd.New(3, 0), apd.New(-4, 0)) })
	num(t, "Pow 3^-4", o, d(t, "0.01234567901234568"))
	o, _ = run(t, func(o *apd.Decimal) (apd.Condition, error) { return hc.Pow(o, apd.New(2, 0), apd.New(20, 0)) })
	num(t, "Pow 2^20", o, apd.New(1048576, 0))
	// Negative base with an integer exponent keeps the correct result sign.
	o, _ = run(t, func(o *apd.Decimal) (apd.Condition, error) { return hc.Pow(o, apd.New(-2, 0), apd.New(3, 0)) })
	num(t, "Pow (-2)^3", o, apd.New(-8, 0))
	o, _ = run(t, func(o *apd.Decimal) (apd.Condition, error) { return hc.Pow(o, apd.New(-2, 0), apd.New(4, 0)) })
	num(t, "Pow (-2)^4", o, apd.New(16, 0))
	o, _ = run(t, func(o *apd.Decimal) (apd.Condition, error) { return hc.Pow(o, apd.New(-3, 0), apd.New(3, 0)) })
	num(t, "Pow (-3)^3", o, apd.New(-27, 0))
}

func TestLogarithmValues(t *testing.T) {
	hc := ctx(16, apd.RoundHalfEven)
	o, c := run(t, func(o *apd.Decimal) (apd.Condition, error) { return hc.Log10(o, apd.New(2, 0)) })
	str(t, "Log10 2 (correctly rounded)", o.String(), "0.3010299956639812")
	flag(t, "Log10 2 inexact", c.Inexact(), true)
	o, _ = run(t, func(o *apd.Decimal) (apd.Condition, error) { return hc.Log10(o, apd.New(50, 0)) })
	str(t, "Log10 50 (correctly rounded)", o.String(), "1.698970004336019")
	// A power of ten has an exactly-representable log, yet the general algorithm still discards
	// nonzero guard digits: the result is numerically 3 but Inexact is set.
	o, c = run(t, func(o *apd.Decimal) (apd.Condition, error) { return hc.Log10(o, apd.New(1000, 0)) })
	num(t, "Log10 1000", o, apd.New(3, 0))
	flag(t, "Log10 1000 inexact", c.Inexact(), true)
	o, _ = run(t, func(o *apd.Decimal) (apd.Condition, error) { return hc.Ln(o, apd.New(2, 0)) })
	str(t, "Ln 2 (correctly rounded)", o.String(), "0.6931471805599453")
	o, _ = run(t, func(o *apd.Decimal) (apd.Condition, error) { return hc.Ln(o, apd.New(100, 0)) })
	str(t, "Ln 100 (correctly rounded)", o.String(), "4.605170185988091")
}

func TestExpAndFractionalPow(t *testing.T) {
	hc := ctx(16, apd.RoundHalfEven)
	o, c := run(t, func(o *apd.Decimal) (apd.Condition, error) { return hc.Exp(o, apd.New(2, 0)) })
	str(t, "Exp 2 (correctly rounded)", o.String(), "7.389056098930650")
	flag(t, "Exp 2 inexact", c.Inexact(), true)
	o, _ = run(t, func(o *apd.Decimal) (apd.Condition, error) { return hc.Exp(o, apd.New(-1, 0)) })
	str(t, "Exp -1 (correctly rounded)", o.String(), "0.3678794411714423")
	o, _ = run(t, func(o *apd.Decimal) (apd.Condition, error) { return hc.Pow(o, apd.New(2, 0), d(t, "1.5")) })
	str(t, "Pow 2^1.5 (correctly rounded)", o.String(), "2.828427124746190")
	o, _ = run(t, func(o *apd.Decimal) (apd.Condition, error) { return hc.Pow(o, apd.New(10, 0), d(t, "0.25")) })
	str(t, "Pow 10^0.25 (correctly rounded)", o.String(), "1.778279410038923")
}

func TestExponentRangeOverflowClamp(t *testing.T) {
	// decimal32-like range: Emax 96, Emin -95.
	sc := &apd.Context{Precision: 5, MaxExponent: 96, MinExponent: -95, Rounding: apd.RoundHalfEven}
	o, c := run(t, func(o *apd.Decimal) (apd.Condition, error) { return sc.Mul(o, d(t, "9E95"), d(t, "1E5")) })
	str(t, "overflow -> Infinity", o.String(), "Infinity")
	flag(t, "overflow flag", c.Overflow(), true)

	// A result far below the subnormal floor rounds to zero and is Clamped.
	o, c = run(t, func(o *apd.Decimal) (apd.Condition, error) { return sc.Mul(o, d(t, "1E-90"), d(t, "1E-90")) })
	num(t, "underflow/clamp -> 0", o, apd.New(0, 0))
	flag(t, "clamped flag", c.Clamped(), true)
}

func TestSubnormalRounding(t *testing.T) {
	// A subnormal value that also needs rounding to fit the precision at the subnormal floor.
	sc := &apd.Context{Precision: 5, MaxExponent: 96, MinExponent: -95, Rounding: apd.RoundHalfEven}
	var o apd.Decimal
	_, c, _ := sc.SetString(&o, "1.234E-97")
	num(t, "subnormal rounded value", &o, d(t, "1.23E-97"))
	flag(t, "subnormal flag", c.Subnormal(), true)
	flag(t, "subnormal rounded flag", c.Rounded(), true)
	// Underflow is raised precisely when a result is both subnormal and inexact.
	flag(t, "subnormal underflow flag", c.Underflow(), true)
}

func TestExpPowExponentRange(t *testing.T) {
	// Bounded range (Emax 96, Emin -95). Exp/Pow must enforce the exponent range through their own
	// code paths, not just the basic arithmetic path.
	sc := &apd.Context{Precision: 5, MaxExponent: 96, MinExponent: -95, Rounding: apd.RoundHalfEven}
	o, c := run(t, func(o *apd.Decimal) (apd.Condition, error) { return sc.Exp(o, apd.New(1000, 0)) })
	str(t, "Exp(1000) overflow", o.String(), "Infinity")
	flag(t, "Exp(1000) overflow flag", c.Overflow(), true)

	o, c = run(t, func(o *apd.Decimal) (apd.Condition, error) { return sc.Pow(o, apd.New(10, 0), apd.New(100, 0)) })
	str(t, "Pow(10^100) overflow", o.String(), "Infinity")
	flag(t, "Pow(10^100) overflow flag", c.Overflow(), true)

	// Control: within range, no overflow.
	o, c = run(t, func(o *apd.Decimal) (apd.Condition, error) { return sc.Pow(o, apd.New(10, 0), apd.New(50, 0)) })
	num(t, "Pow(10^50) in range", o, apd.New(1, 50))
	flag(t, "Pow(10^50) no overflow", c.Overflow(), false)

	// Exp of a large negative argument underflows toward zero and is Clamped.
	o, c = run(t, func(o *apd.Decimal) (apd.Condition, error) { return sc.Exp(o, apd.New(-1000, 0)) })
	num(t, "Exp(-1000) underflow->0", o, apd.New(0, 0))
	flag(t, "Exp(-1000) clamped", c.Clamped(), true)
}

func TestTraps(t *testing.T) {
	// A trap for Inexact turns an inexact division into a returned error.
	inexactTrap := &apd.Context{Precision: 5, Rounding: apd.RoundHalfEven, MaxExponent: apd.MaxExponent, MinExponent: apd.MinExponent, Traps: apd.Inexact}
	var o apd.Decimal
	if _, err := inexactTrap.Quo(&o, apd.New(1, 0), apd.New(3, 0)); err == nil {
		t.Errorf("Quo(1/3) with Inexact trap: expected error, got nil (value %s)", o.String())
	}
	// A trap for DivisionByZero turns x/0 into a returned error.
	dbzTrap := &apd.Context{Precision: 5, Rounding: apd.RoundHalfEven, MaxExponent: apd.MaxExponent, MinExponent: apd.MinExponent, Traps: apd.DivisionByZero}
	var o2 apd.Decimal
	if _, err := dbzTrap.Quo(&o2, apd.New(1, 0), apd.New(0, 0)); err == nil {
		t.Errorf("Quo(1/0) with DivisionByZero trap: expected error, got nil")
	}
	// With no traps, the same operation reports a flag and returns no error.
	var o3 apd.Decimal
	if cond, err := ctx(5, apd.RoundHalfEven).Quo(&o3, apd.New(1, 0), apd.New(0, 0)); err != nil || !cond.DivisionByZero() {
		t.Errorf("Quo(1/0) no traps: got err=%v divByZero=%v", err, cond.DivisionByZero())
	}
	// A trap for Overflow turns an overflowing operation into a returned error.
	ovTrap := &apd.Context{Precision: 5, MaxExponent: 96, MinExponent: -95, Rounding: apd.RoundHalfEven, Traps: apd.Overflow}
	var o4 apd.Decimal
	if _, err := ovTrap.Mul(&o4, d(t, "9E95"), d(t, "1E5")); err == nil {
		t.Errorf("Mul overflow with Overflow trap: expected error, got nil")
	}
}
