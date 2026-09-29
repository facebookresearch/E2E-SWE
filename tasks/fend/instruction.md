# fend — an arbitrary-precision calculator

Build **`fend`**, a command-line calculator that evaluates a single mathematical expression and
prints the result. It supports exact arbitrary-precision rational arithmetic, complex numbers, a
small expression language with variables and functions, multiple number bases, physical units with
unit-aware arithmetic and conversion, and several output formats. The examples below illustrate the
*conventions*; apply them generally.

## Implementation language and build

- Implement in **Rust, using only the standard library** — no external crates. The grading
  environment is fully offline; nothing can be downloaded at build time. A standard-library-only
  crate builds with no network access.
- Provide an executable **`setup.sh`** in the project root that builds the project and installs an
  executable named **`fend`** onto `PATH`, e.g.:
  ```bash
  cargo build --release --offline
  cp target/release/<your-bin-name> /usr/local/bin/fend
  ```

## Command-line contract

- Invocation: `fend "<expression>"` — the whole expression is a single command-line argument.
- **Success:** print the result (see *Output formatting*) to **stdout followed by a single
  newline**, exit `0`.
- **Error** (syntax error, math domain error, etc.): print a message to **stderr** and exit
  **non-zero**; print nothing to stdout.

## Output formatting

- **Canonical form**, fractions reduced; equal values print identically however they were written.
- **Exact vs. approximate.** A value expressible as a *finite* decimal is **exact** and printed
  directly, with trailing fractional zeros and any dangling decimal point removed (`3/8` → `0.375`,
  `7/4` → `1.75`). A value that is *not* a finite decimal — irrational/transcendental, or an exact
  rational whose decimal does not terminate — is printed as `approx. ` followed by the value
  **rounded to exactly 10 decimal places**, keeping trailing zeros (`1/9` → `approx. 0.1111111111`,
  `10/3` → `approx. 3.3333333333`). Trailing-zero stripping applies only to exact values.
- **Integers** print with no decimal point and no digit grouping, in full at any size.
- An expression with no value (e.g. `()`) prints the empty string.

## Numbers

- Arbitrary-precision integers and decimals; no overflow.
- **Digit separators** `_` and `,` group digits and are ignored; they are valid only **between two
  digits** (a leading, trailing, doubled, or pre-decimal-point separator is an error). In the
  default mode `,` is a separator, not a decimal point.
- Surrounding whitespace is ignored.
- **Fractions** `a/b`; a **mixed number** is an integer then a fraction, meaning their sum
  (`2 1/4` = `2 + 1/4`). A mixed number binds as a single term, tighter than a surrounding `*`/`/`,
  so it may be a factor of `*` (`2 * 1 1/4` = `2 × (1 + 1/4)`) or the **dividend** (left operand) of
  `/` (`5 1/2 / 2` = `(5 1/2) / 2` = `2.75`). Its three parts must each be plain numeric literals: a
  mixed number may not be the **divisor** (right operand) of `/` (so `1/1 1/2` is an error), may not
  contain `^`, may not have a negative denominator, and may not follow a non-numeric term — such
  inputs are errors (a leading `-` negates the whole number).
- **Recurring decimals**: a parenthesised digit group repeats, both on input and via `to float`
  output (`1/6 to float` → `0.1(6)`, `5/12 to float` → `0.41(6)`); `to fraction` is the inverse.
  `to float` always emits the **minimal** repeating block (`0.(66)` → `0.(6)`), and an all-zero
  recurring block renders as a plain terminating decimal (`0.5(0)` → `0.5`).
- **Scientific notation**: `1e10`, `1.5e-1`, uppercase `E` allowed.
- **Number bases (2–36)**: prefixes `0x`/`0o`/`0b`, and explicit `<base>#<digits>` with digits
  `0-9a-z`. A non-decimal literal **keeps its base for display** (leading zeros and separators
  removed, hex lowercased); arithmetic between non-decimal values keeps the **left** operand's base
  (`0o16` → `0o16`, `0x1f + 0x1` → `0x20`); a decimal operand makes the result decimal. An
  `e`-exponent applies only where `e` is not a digit of the base (`0b1e11` → `0b1000`; in base 16
  `e` is a digit).

## Operators

- `+ - * /` (usual precedence, left-associative); `^` / `**` exponentiation (right-associative,
  binding tighter than a unary minus on the base). Fractional exponents take roots, **exact** when
  the result is rational (`16^(1/2)` → `4`, `64^(1/3)` → `4`), approximate otherwise.
- Unary `+`/`-`; postfix factorial `!` on non-negative integers.
- **Implicit multiplication** between adjacent terms (`2pi`, `4a`).
- `mod`; `nCr`/`choose`; `nPr`/`permute`; comparisons `==`, `!=` (also `≠`) → booleans;
  bitwise `&`, `|`, `xor`, `<<`, `>>` on non-negative integers (results follow the base rules above).
- Unicode operator glyphs are accepted (`−`, `×`/`✕`, `÷`/`∕`); superscript digits are exponents.

## Constants and functions

- Constants `pi` (`π`), `e`, `tau` (`τ`), `phi` — shown as 10-dp approximations.
- `sqrt`, `cbrt`: exact for perfect powers, else approximate. `abs`, `floor`, `ceil`, `round`
  (`round` rounds half **away from zero**). `sin`, `cos`, `tan`, `asin`, `acos`, `atan`, `sinh`,
  `cosh`, `tanh`, `ln`, `log2`, `log10`, `exp`: approximate to 10 dp (`cos 0.5` →
  `approx. 0.8775825619`). `fib` — Fibonacci numbers.

## Units

- A number may carry a **physical unit** written after it (`5 kg`, `10 m`, `3 ft`, `1 GiB`); the
  unit attaches to the number (implicit multiplication). The common SI/US/UK units and standard
  data-size units are recognised by their usual names and symbols — length, mass, time, data size,
  speed, force, temperature, and so on.
- **Conversion** reuses the `to` / `as` / `in` directive: `<value> to <unit>` restates the value in
  the requested unit and prints as `<number> <unit>` (the value, a space, then the unit):
  `1 inch to cm` → `2.54 cm`, `1 KiB to bytes` → `1024 bytes`.
- **Unit-aware arithmetic**: quantities combine under `+ - * / ^`, tracking and simplifying their
  dimensions. `+` and `-` require the same dimension and keep the left operand's unit
  (`1 m + 50 cm` → `1.5 m`); `*` and `/` combine dimensions (`4 m * 5 m` → `20 m^2`), and scaling
  by a dimensionless value keeps the unit (`a = 3 m; b = 2; a * b` → `6 m`).
- **Temperature** conversions apply each scale's zero offset rather than a bare ratio; `C`, `F`, and
  `K` name the Celsius, Fahrenheit, and Kelvin scales (`25 C to F` → `77 °F`).
- Converting between **incompatible dimensions** is an error (`1 s to kg`).

## Complex numbers

- `i` is the imaginary unit; `3i` is imaginary. Arithmetic, integer/complex powers, and division
  are supported. Results display as `a + bi` / `a - bi`, real part first, with pure-real and
  pure-imaginary results collapsed (`(2+i)+(1+i)` → `3 + 2i`). The collapse depends only on a
  component being zero, so it applies to approximate results too; a non-zero component that merely
  rounds to `0` at 10 dp is not collapsed (as in the `sqrt(-4)` example below).
- A real or imaginary **part that is an exact but non-terminating rational** is shown in **fraction
  form** (not as a 10-dp approximation), with the imaginary unit on the numerator (`i/6` → `i/6`).
  When such an imaginary value has a whole part it is written as a **mixed number with the unit
  trailing the whole expression** — `<whole> <numerator>/<denominator> i`, the unit **not** on the
  numerator: `5/3 i` → `1 2/3 i`, and `7/6 + 5/6 i` → `1 1/6 + 5i/6`.
- `abs z` is the modulus (`abs(6+8i)` → `10`); accessors `real z`, `imag z`, `conjugate z`, and
  `arg z` (argument in radians, approximate).
- Functions extend to the **complex domain** (results approximate): roots of negatives, complex
  `exp`/`ln`, and powers with a complex base or exponent — e.g. `sqrt(-4)` → `approx. 0 + 2i`,
  `ln(-8)` → `approx. 2.0794415417 + 3.1415926536i`.

## Dice and probability distributions

- `dN` is the uniform distribution over the integers `1..N`; `m dN` (equivalently `dN + dN + …`)
  is the sum of `m` such dice, formed by convolution. A distribution **displays** as
  `{ value: percent%, … }` in ascending value order, each probability shown as a percentage to
  **2 decimal places** (`d4` → `{ 1: 25.00%, 2: 25.00%, 3: 25.00%, 4: 25.00% }`).
- `mean(<distribution>)` returns the expected value (`mean(d4)` → `2.5`).

## Variables, lambdas, statements

- `x = <expr>` assigns; assignment chains right-to-left (`a = b = 2`). Variables are reusable,
  including via implicit multiplication.
- A function is `x: <body>`, `\x. <body>`, or `x => <body>`; multiple arguments curry and apply
  left to right (`(x: y: <body>) 1 2`). A built-in function may be negated then applied.
- `;` separates statements; the whole input's value is the **last** expression's. `()` is empty.

## Booleans

- `true`, `false`, logical `not`; comparisons yield booleans.

## Output-format directives (`to` / `as`)

- **Bases**: `to hex`, `to binary`, `to octal`, `to decimal`, `to base <N>`. Converting an integer
  *to* a base shows the digits with **no prefix** (`8#17 to decimal` → `15`).
- **`to float`** — recurring-decimal form; **`to fraction`** — improper fraction `a/b`;
  **`to mixed_frac`** — mixed number (`2 1/4 to fraction` → `9/4`).
- **`to <N> dp`** — round to N decimal places, then display in canonical form with trailing zeros
  stripped (unlike a default approximation, which keeps 10 places); marked `approx.` if rounding
  changed the value (`3.14159 to 3 dp` → `approx. 3.142`).
- **`to <N> sf`** — round to N significant figures, displayed in plain (non-scientific) form with
  zero-padding to the value's magnitude (`0.0456 to 2 sf` → `approx. 0.046`). The `approx.` marker
  reflects whether rounding changed the value, even when the rounded value itself displays as an
  integer (so a 7-digit number to 1 sf → `approx. 1000000`).

## Errors

Reject (stderr message, non-zero exit) rather than returning a value: division or modulo by zero;
`0^0`; an invalid base (a non-integer or out-of-range base); math domain errors and unsupported
factorials (of negatives, non-integers, or complex numbers); and malformed input.
