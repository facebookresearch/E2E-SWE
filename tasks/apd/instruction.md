# Task: Arbitrary-Precision Decimal Arithmetic Library (Go)

Implement a Go library for **arbitrary-precision decimal arithmetic** conforming to the
[General Decimal Arithmetic (GDA) specification](http://speleotrove.com/decimal/). This is the
same model implemented by Python's `decimal` module and IBM's decNumber: base-10 arithmetic with
configurable precision, IEEE-754-style rounding modes, condition flags, traps, and the special
values Infinity, NaN, and signaling NaN.

Unlike binary floating point, results are computed to a caller-specified number of **significant
decimal digits** and rounded with a caller-selected rounding mode, so decimal fractions like `0.1`
are represented exactly and rounding behavior is fully deterministic.

## Dependencies

- **Go standard library only** (in particular `math/big` for the coefficient). No third-party
  packages. The environment is fully offline — do not attempt to download anything.
- The project must build offline with `go build ./...` against the pre-installed toolchain.

## Package Structure

- Module path (must match exactly): `github.com/cockroachdb/apd/v3`
- Package name: `apd`
- The hidden test suite is an external `apd_test` package that imports
  `github.com/cockroachdb/apd/v3` and exercises only the exported API described below. Provide a
  `go.mod` declaring the module path above and `go 1.22`; the build must succeed offline with
  network-free `go build ./...`.
- You work in the `/app` directory. At grading time the hidden `*_test.go` files are copied into
  your module's directory (the directory that contains your `go.mod`) and `go test` is run there,
  so your package must compile and pass `go test` from the module root.

---

## Core types

### `Decimal`

An arbitrary-precision decimal whose numeric value is `(-1)^Negative × Coeff × 10^Exponent`.

```go
type Decimal struct {
    Form     Form   // Finite (default), Infinite, NaNSignaling, or NaN
    Negative bool   // sign; true means negative
    Exponent int32  // power-of-ten scale
    Coeff    BigInt // non-negative coefficient (magnitude); see note
}
```

- `Coeff` holds the **non-negative** coefficient magnitude (the sign lives in `Negative`). You may
  back it with any arbitrary-precision unsigned integer representation; expose a type named `BigInt`
  for the field. The test suite constructs decimals through the constructors and parsing functions
  below and observes them through the methods below — it does not read `Coeff`'s internal layout.
- `Exponent`, `Negative`, and `Form` are read as documented by the observable contracts below.

### `Form`

```go
type Form int8
const (
    Finite       Form = iota // finite number (default zero value)
    Infinite                 // ±Infinity
    NaNSignaling             // signaling NaN — raises InvalidOperation when used as an operand
    NaN                      // quiet NaN
)
```
These constants **must be declared in this order** — the total ordering used by `CmpTotal` depends
on it.

### `Context`

All arithmetic lives on `Context`, which carries precision/range/rounding/trap settings:

```go
type Context struct {
    Precision   uint32    // number of significant digits to round results to (0 = no rounding)
    MaxExponent int32     // largest allowed adjusted exponent
    MinExponent int32     // smallest allowed adjusted exponent
    Traps       Condition // conditions that turn into a returned error when raised
    Rounding    Rounder   // rounding mode; RoundHalfUp if empty
}

func (c *Context) WithPrecision(p uint32) *Context // copy of c with Precision = p
```

- `MaxExponent`/`MinExponent` bound the **adjusted exponent** (the exponent in scientific
  notation). The package constants `MaxExponent = 100000` and `MinExponent = -100000` are the
  supported limits.
- `Precision == 0` disables rounding for value-preserving operations, but the division and
  transcendental operations require `Precision > 0` and return an error otherwise.

`BaseContext` is a ready-made context with `Precision: 0`, `MaxExponent: MaxExponent`,
`MinExponent: MinExponent`, and `Traps: DefaultTraps`, where
`DefaultTraps = SystemOverflow | SystemUnderflow | Overflow | Underflow | Subnormal |
DivisionUndefined | DivisionByZero | DivisionImpossible | InvalidOperation`.

### `Rounder` and rounding modes

```go
type Rounder string
const (
    RoundDown     Rounder = "down"      // toward zero (truncate)
    RoundHalfUp   Rounder = "half_up"   // nearest; ties away from zero
    RoundHalfEven Rounder = "half_even" // nearest; ties to even digit (banker's)
    RoundCeiling  Rounder = "ceiling"   // toward +Infinity
    RoundFloor    Rounder = "floor"     // toward -Infinity
    RoundHalfDown Rounder = "half_down" // nearest; ties toward zero
    RoundUp       Rounder = "up"        // away from zero
    Round05Up     Rounder = "05up"      // away from zero only if the rounded digit becomes 0 or 5;
                                        // otherwise truncate
)
```

Rounding discards digits beyond `Precision` and conditionally increments the last kept digit
according to the mode. "Ties" are cases where the discarded part is exactly one half.

### `Condition`

A bitfield of flags reported by every `Context` operation:

```go
type Condition uint32
const (
    SystemOverflow Condition = 1 << iota
    SystemUnderflow
    Overflow
    Underflow
    Inexact
    Subnormal
    Rounded
    DivisionUndefined
    DivisionByZero
    DivisionImpossible
    InvalidOperation
    Clamped
)
```
(The constants must keep this bit order.) Provide predicate methods returning whether a given flag
is set: `Overflow()`, `Underflow()`, `Inexact()`, `Subnormal()`, `Rounded()`,
`DivisionUndefined()`, `DivisionByZero()`, `DivisionImpossible()`, `InvalidOperation()`,
`Clamped()`, plus `Any() bool` (true if any flag set). Meanings:

- **Inexact** — a non-zero digit was discarded during rounding (the result differs from the exact
  mathematical value).
- **Rounded** — one or more digits were discarded (may be set even when the discarded digits were
  zero).
- **DivisionByZero** — non-zero dividend divided by zero (result is signed Infinity).
- **DivisionUndefined** — `0 / 0` (result NaN).
- **DivisionImpossible** — integer division whose integer result needs more than `Precision`
  digits.
- **InvalidOperation** — a mathematically undefined/forbidden operation (e.g. `sqrt` of a negative,
  `Inf - Inf`, operand is signaling NaN).
- **Subnormal** — the result is subnormal: its adjusted exponent (`Exponent + NumDigits − 1`) is
  less than `MinExponent`. Raised (before rounding) on any non-zero result that falls in this range.
- **Underflow** — raised when a result is **both subnormal and inexact** (i.e. `Subnormal` and
  `Inexact` both hold).
- **Overflow / Clamped** — the other exponent-range conditions: `Overflow` when the adjusted
  exponent exceeds `MaxExponent`; `Clamped` when the exponent is adjusted to fit the representable
  range (e.g. a result rounded down to zero at the subnormal floor).

The smallest exponent a finite result may take is the **subnormal floor**
`Etiny = MinExponent − (Precision − 1)`. A non-zero result whose exponent would fall below `Etiny`
is rounded up to `Etiny`, dropping the extra low-order digits.

### Errors and traps

Each `Context` operation returns `(Condition, error)`. The `error` is non-nil **iff** a raised flag
is also present in `c.Traps` (or a system range error occurred). With `Traps == 0`, operations never
return an error for ordinary conditions and simply report flags. When an error is returned, the
condition value is still returned alongside it.

---

## Construction and parsing

```go
func New(coeff int64, exponent int32) *Decimal          // value = coeff × 10^exponent (sign from coeff)
func NewWithBigInt(coeff *BigInt, exponent int32) *Decimal

func (d *Decimal) SetInt64(x int64) *Decimal            // value = x
func (d *Decimal) SetFinite(x int64, exp int32) *Decimal
func (d *Decimal) SetFloat64(f float64) (*Decimal, error) // exact decimal value of the float64

// Parsing. NewFromString/(*Decimal).SetString use BaseContext (no rounding, full precision).
// The (*Context) variants round the parsed value to the context's precision.
func NewFromString(s string) (*Decimal, Condition, error)
func (d *Decimal) SetString(s string) (*Decimal, Condition, error)
func (c *Context) NewFromString(s string) (*Decimal, Condition, error)
func (c *Context) SetString(d *Decimal, s string) (*Decimal, Condition, error)
```

Parsing accepts: an optional leading `+`/`-`; a mantissa with an optional single `.`; an optional
`e`/`E` exponent (case-insensitive); and the special strings `Infinity`/`Inf`, `NaN`, and `sNaN`
(case-insensitive, optional sign and optional NaN payload digits). The scale is derived from the
fractional digit count and the explicit exponent (e.g. `"1.23"` → coeff 123, exponent −2;
`"1.5E3"` → coeff 15, exponent 2). Invalid input returns a non-nil error.

---

## Observation and representation

```go
func (d *Decimal) String() string          // == Text('G'); the GDA "to-scientific-string" form
func (d *Decimal) Text(format byte) string // 'e','E','f','g','G' (see Formatting)
func (d *Decimal) Sign() int               // -1, 0, +1 (0 for ±0); for non-finite, sign of Negative
func (d *Decimal) IsZero() bool
func (d *Decimal) Cmp(x *Decimal) int      // -1/0/+1 by numeric value; result undefined if NaN
func (d *Decimal) CmpTotal(x *Decimal) int // total order over the abstract representation
func (d *Decimal) NumDigits() int64        // number of significant digits in the coefficient
func (d *Decimal) Int64() (int64, error)   // error if non-finite, fractional, or out of range
func (d *Decimal) Float64() (float64, error)
func (d *Decimal) Set(x *Decimal) *Decimal
func (d *Decimal) Neg(x *Decimal) *Decimal // d = -x (−0 normalizes to +0)
func (d *Decimal) Abs(x *Decimal) *Decimal // d = |x|
func (d *Decimal) Reduce(x *Decimal) (*Decimal, int) // remove trailing zeros; returns count removed
func (d *Decimal) Modf(integ, frac *Decimal)         // split into integer and fractional parts
func (d *Decimal) MarshalText() ([]byte, error)      // == String()
func (d *Decimal) UnmarshalText(b []byte) error      // == SetString
```

- **`Cmp`** compares numeric value: `New(120,-2)` (`1.20`) and `New(12,-1)` (`1.2`) compare **equal**
  (returns 0). `±Infinity` compares as expected; comparisons involving NaN are undefined.
- **`CmpTotal`** orders by the *representation*, not just value: equal values with different
  exponents are ordered by exponent (`1.2300` sorts **below** `1.23`), and the NaN/Infinity forms
  have a defined position (`… < -Infinity < finite < +Infinity < sNaN < NaN`, with negatives of the
  special forms below all finite negatives). The sign is part of the total order, so `-0` sorts
  **below** `+0` (even though they compare equal under `Cmp`). Trailing-zero differences therefore
  matter for `CmpTotal` but not for `Cmp`.
- **`Reduce`** removes trailing zeros from the coefficient (adjusting the exponent): `1.2300`
  reduces to `1.23` and reports `2` zeros removed; any zero reduces to `0` (exponent 0).
- **`Modf`** sets `integ` to the truncated-toward-zero integer part (exponent ≥ 0) and `frac` to the
  remainder (exponent ≤ 0); both share the sign of the input.
- **`Int64`** errors if the value is non-finite, has a non-zero fractional part, or does not fit in
  an `int64`.

---

## Arithmetic operations (methods on `*Context`)

Every operation writes its result into the destination `d` (which may alias an operand) and returns
`(Condition, error)`. Results are rounded to `c.Precision` significant digits using `c.Rounding`,
raising `Inexact` and `Rounded` as appropriate.

```go
func (c *Context) Add(d, x, y *Decimal) (Condition, error) // x + y
func (c *Context) Sub(d, x, y *Decimal) (Condition, error) // x - y
func (c *Context) Mul(d, x, y *Decimal) (Condition, error) // x * y
func (c *Context) Abs(d, x *Decimal) (Condition, error)
func (c *Context) Neg(d, x *Decimal) (Condition, error)

func (c *Context) Quo(d, x, y *Decimal) (Condition, error)        // x / y (true division; needs Precision > 0)
func (c *Context) QuoInteger(d, x, y *Decimal) (Condition, error) // integer quotient (exponent 0)
func (c *Context) Rem(d, x, y *Decimal) (Condition, error)        // remainder; result takes the dividend's sign

func (c *Context) Cmp(d, x, y *Decimal) (Condition, error)        // sets d to -1/0/1; NaN operands set d to NaN

func (c *Context) Quantize(d, x *Decimal, exp int32) (Condition, error) // rescale x to exponent exp
func (c *Context) Round(d, x *Decimal) (Condition, error)               // round x to Precision (no-op if Precision==0)
func (c *Context) RoundToIntegralValue(d, x *Decimal) (Condition, error) // round to integer; clears Inexact/Rounded
func (c *Context) RoundToIntegralExact(d, x *Decimal) (Condition, error) // round to integer; keeps Inexact/Rounded
func (c *Context) Ceil(d, x *Decimal) (Condition, error)                 // smallest integer >= x
func (c *Context) Floor(d, x *Decimal) (Condition, error)                // largest integer <= x
func (c *Context) Reduce(d, x *Decimal) (int, Condition, error)          // strip trailing zeros

func (c *Context) Sqrt(d, x *Decimal) (Condition, error)   // square root
func (c *Context) Cbrt(d, x *Decimal) (Condition, error)   // cube root
func (c *Context) Exp(d, x *Decimal) (Condition, error)    // e^x
func (c *Context) Ln(d, x *Decimal) (Condition, error)     // natural log
func (c *Context) Log10(d, x *Decimal) (Condition, error)  // base-10 log
func (c *Context) Pow(d, x, y *Decimal) (Condition, error) // x^y
```

### Behavioral contracts

- **Add/Sub/Mul** compute the exact result, then round to `Precision`. When rounding discards a
  non-zero digit, both `Inexact` and `Rounded` are set. Adding exact opposites yields `0`; its sign
  is `-` only under `RoundFloor`, otherwise `+`.
- **Quo** performs true division to `Precision` digits. An exact quotient sets no `Inexact` flag; a
  non-terminating one sets `Inexact | Rounded` and is rounded per `c.Rounding`. `x/0` with `x ≠ 0`
  sets `DivisionByZero` and yields signed `Infinity`; `0/0` sets `DivisionUndefined` and yields
  `NaN`. `Precision == 0` is an error.
- **QuoInteger** yields the integer part of `x/y` with exponent 0. If that integer needs more than
  `Precision` digits, it sets `DivisionImpossible` and yields `NaN`.
- **Rem** yields `x − QuoInteger(x,y)·y`; the result carries the **dividend's** sign. Same
  `DivisionImpossible` rule as `QuoInteger`.
- **Quantize** rescales `x` so its exponent equals `exp`, rounding the coefficient as needed
  (raising `Inexact`/`Rounded` if digits are dropped). It returns `NaN` with `InvalidOperation` if
  the coefficient would need more than `Precision` digits, if `exp` exceeds the exponent range, or
  if `x` is infinite. Quantize never raises `Underflow`. Example: quantizing `2.17` to exponent −1
  with `RoundHalfEven` gives `2.2`.
- **RoundToIntegralValue / RoundToIntegralExact / Ceil / Floor** produce an integer-valued result.
  `RoundToIntegralValue` clears `Inexact` and `Rounded`; `RoundToIntegralExact` reports them.
  `Ceil`/`Floor` round toward +∞/−∞ regardless of `c.Rounding`.
- **Sqrt** returns the correctly-rounded square root to `Precision` digits (`Inexact` when
  irrational). `Sqrt` of a negative finite number is `NaN` with `InvalidOperation`; `Sqrt(0) = 0`.
- **Cbrt** returns the cube root; unlike `Sqrt` it is defined for negative inputs
  (`Cbrt(-8) = -2`).
- **Exp / Ln / Log10 / Pow** return results **correctly rounded to `Precision` significant digits**
  (last-digit accurate for the given precision) and set `Inexact` and `Rounded`. `Inexact` is set
  for every result obtained from the correctly-rounded transcendental computation — even when the
  true mathematical value happens to be exactly representable — and is cleared only for the exact
  special/algebraic cases in the domain rules below (e.g. `Ln(1) = 0`, `Exp(0) = 1`, `x^0 = 1`, and
  exact integer powers). You choose the algorithm; only the rounded output and flags are checked.
  Domain rules:
  - `Ln`/`Log10` of a negative number → `NaN` + `InvalidOperation`; of `0` → `-Infinity`; of `1`
    → `0`.
  - `Exp(0) = 1`; `Exp(-Infinity) = 0`; `Exp(+Infinity) = +Infinity`.
  - `Pow`: `x^0 = 1` for any **non-zero** `x`; `0^0` → `NaN` + `InvalidOperation`;
    `0^positive = 0` and `0^negative = +Infinity`; a negative base with a non-integer exponent →
    `NaN` + `InvalidOperation`; a **positive integer exponent** yields an exact-then-rounded result
    (negative bases keep the correct result sign), and a **negative integer exponent** yields the
    reciprocal (`x**(-n) == 1 / x**n`).
- **NaN / sNaN propagation.** If any operand is `NaN` or `NaNSignaling`, the result is `NaN`. A
  signaling-NaN operand additionally raises `InvalidOperation`. (`sNaN` is produced by parsing
  `"sNaN"`.)
- **Infinity arithmetic.** `Inf + Inf = Inf`, `Inf − Inf = NaN` + `InvalidOperation`,
  `Inf × 0 = NaN` + `InvalidOperation`, `finite / Inf = 0`, etc., following the GDA rules.

---

## Formatting (`String` / `Text`)

`Text(format)` supports these format bytes:

- `'e'` / `'E'` — scientific: one digit before the point, then `e±d` / `E±d` with the adjusted
  exponent (no leading zeros, always a sign).
- `'f'` — plain positional notation, no exponent.
- `'g'` / `'G'` — GDA "to-scientific-string": use positional (`'f'`-like) form when the exponent is
  `≤ 0` **and** the adjusted exponent (`Exponent + NumDigits − 1`) is `≥ −6`; otherwise use
  scientific (`'e'`/`'E'`) form. `String()` is `Text('G')`.

The output preserves the coefficient's digit count (trailing zeros are significant): `New(120,-2)`
formats as `1.20`, while `New(12,-1)` formats as `1.2`. Special values format as `NaN`, `sNaN`,
`Infinity` (with a leading `-` when negative). Examples for `String()`:

- `New(1230, -3)` → `1.230`
- `New(123, -2)` → `1.23`
- `New(5, -7)` → `5E-7` (adjusted exponent −7 < −6 → scientific)
- `New(0, 0)` → `0`
- `New(-6, 0)` with `Text('e')` → `-6e+0`

---

## Notes

- Constructors, parsing, and the `String`/`Text` round-trip must all agree so that
  `SetString(d.String())` reproduces the same value.
- The library must not panic on any input the API accepts; error conditions are surfaced via the
  returned `error`/`Condition`, not panics.
- Everything is pure computation — no files, no network, no goroutines are required.
</content>
