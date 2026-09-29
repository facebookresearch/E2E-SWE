# numfmt

Build **numfmt**, a spreadsheet (Excel/ECMA-376-style) **number and date format engine**: given a
format-pattern string and a value, produce the exact formatted string, plus utilities for parsing
values, inspecting format patterns, and converting dates to/from serial numbers. Implement the
semantics described below; you have no network access.

## Runtime & packaging

- Node 20. **No runtime dependencies** and no build/transpile step are required. No network access.
- Deliverables under `/app`:
  1. A CommonJS module at **`/app/numfmt.js`** whose export **is the numfmt API object** — i.e.
     `const numfmt = require("/app/numfmt.js")` must work and expose the named functions below
     (`numfmt.format`, `numfmt.parseValue`, …). You may split your implementation across files under
     `/app` and `require` them from `/app/numfmt.js`.
  2. A **`/app/setup.sh`** that is **run** (offline) to build/install the project before the tests run
     — a no-op (`:`) is fine.

Object/array results are compared by their **JSON-normalized structure** (the observable shape), so
any internal object representation is fine.

## Dates as serial numbers

Dates are represented as Excel **serial numbers**: integer part = days since the epoch (serial `1` =
1900-01-01), fractional part = time of day (`0.5` = noon). The engine reproduces the historical
**1900 leap-year bug**: serial **60 = 1900-02-29** (a day that never existed), so serial 59 =
1900-02-28 and 61 = 1900-03-01.

## `format(pattern, value, options?) -> string`

Format `value` (a number; or a serial date; or a string/boolean/null) per `pattern`. `null`/`undefined`
→ `""`; a boolean → its locale word (`true` → `"TRUE"`); a non-number/non-boolean value is sent
through the text section (below).

The optional trailing `options` argument (on `format`, `formatColor`, and `parseValue`) selects
locale overrides; every case here uses the **default en-US locale**, so `options` may be omitted.

**Pattern language** (default en-US locale: `.` decimal, `,` group):

- **Digit placeholders:** `0` = digit or `0`; `#` = digit if present, else nothing; `?` = digit or a
  padding **space**. `.` is the decimal point. E.g. `format("#,##0.00", 1234.56)` → `"1,234.56"`;
  `format("0.??", 1.5)` → `"1.5 "` (trailing `?` pads a space). Because `#` emits nothing for an
  absent digit, an all-`#` value of `0` yields `""` (`format("#", 0)` → `""`) and `format("#.##", 0)`
  → `"."` (the decimal point still prints).
- **Thousands grouping:** a `,` between digit placeholders groups by 3 — `format("#,##0", 1234567)` →
  `"1,234,567"`.
- **Scaling:** a `,` that follows the digit placeholders with no further digit after it scales the
  number down by 1000 per comma — `format("0.0,,", 12200000)` → `"12.2"`, `format("0,", 12345)` →
  `"12"`.
- **Percent:** `%` scales the value by 100 and appends `%` — `format("0%", 0.7)` → `"70%"`.
- **Scientific:** `E+`/`E-` — `format("0.00E+00", 12200000)` → `"1.22E+07"`. A mantissa with several
  integer placeholders (e.g. `##0`) selects **engineering notation**: the exponent snaps to a multiple
  of the integer-placeholder count (so 1–3 integer digits show) and `E+0` prints the exponent with
  minimal digits — `format("##0.0E+0", 12200000)` → `"12.2E+6"`, `format("##0.0E+0", 1234)` → `"1.2E+3"`.
- **Fractions:** `?/?` (free denominator), `?/8` (fixed denominator), `# ?/?` (mixed with an integer
  part). The fraction is the **continued-fraction convergent** — the best rational whose numerator and
  denominator fit the placeholder digit-counts (the same method as `dec2frac`), which can differ from
  the numerically closest fraction. The **numerator right-aligns and the denominator left-aligns**,
  each `?` emitting a space for an absent digit — `format("# ?/?", 1.25)` → `"1 1/4"`,
  `format("?/8", 0.5)` → `"4/8"`, `format("?/?", 0.5)` → `"1/2"`, `format("??/??", 0.5)` → `" 1/2 "`,
  `format("# ??/??", 3.14159)` → `"3  1/7 "`.
- **Sections:** a pattern may have up to four `;`-separated sections applied by value:
  **positive; negative; zero; text**. `format('"P";"N";"Z"', 5|-5|0)` → `"P"|"N"|"Z"`. With fewer
  sections the engine derives the rest (a single section also handles negatives, prefixing a minus).
- **Text section / `@`:** a string value is emitted through the text section, where `@` is the value
  placeholder — `format("0.00", "hello")` → `"hello"`, `format('"v="@', "foo")` → `"v=foo"`.
- **Conditions:** a section may be guarded by `[cond]` using `= < > <= >= <>` (e.g. `[>100]`); the
  first matching section wins — `format('[>100]"big";[<=100]"small"', 50)` → `"small"`.
- **Literals & spacing:** text in `"..."`, an escaped char `\c`, and pass-through symbols (space, `$`,
  `-`, `+`, `(`, `)`, `/`) print literally. `_` skips a width equal to the next char (emits one
  space) — used for accounting alignment; `*` fills (emits nothing by default). So
  `format("#,##0_);(#,##0)", -1234)` → `"(1,234)"` and `1234` → `"1,234 "`; `format('0 "bells"', 7)`
  → `"7 bells"`.
- **Dates & times:** `yyyy`/`yy` year, `mm`/`m` month, `dd`/`d` day; `mmm`→`"Oct"`, `mmmm`→`"October"`, `mmmmm`→`"O"` (single letter);
  `ddd`→`"Sun"`, `dddd`→`"Sunday"`; `hh`/`h`, `mm`/`m` minutes (a `m` next to `h`/`s` is minutes, else
  month), `ss`/`s`; `AM/PM` selects a 12-hour clock. `[h]`/`[m]`/`[s]` are **elapsed** counters that
  accumulate beyond a day and show a leading minus for negatives — `format("[h]:mm", 1.5)` → `"36:00"`,
  `-1.5` → `"-12:00"`. `format("h:mm AM/PM", 0.5)` → `"12:00 PM"`.
- **`General`:** a special format with adaptive precision — it keeps up to **~11 significant digits**,
  so an integer up to 11 digits prints in full (`format("General", 12345678901)` → `"12345678901"`) and
  other values are trimmed to fit (`format("General", 0.3333333333333333)` → `"0.333333333"`). It
  switches to scientific only when the plain form would need more than that budget —
  `format("General", 1234.5)` → `"1234.5"`, `format("General", 123456789012)` → `"1.23457E+11"`.
- **Color markup** (`[Red]`, `[Blue]`, `[Color n]`) selects a color but is **not** emitted in the
  formatted string — `format("[Red]0;[Blue]-0", -3)` → `"-3"`.
- **Rounding is half-away-from-zero** (symmetric), applied at the pattern's decimal precision —
  `format("0", 2.5)` → `"3"`, `format("0", 3.5)` → `"4"`.

## `formatColor(pattern, value, options?) -> string | null`

Return the color name of the section that `value` routes to (e.g. `"blue"`), or `null` when that
section declares no color — `formatColor("[Red]0;[Blue]-0", -3)` → `"blue"`, `3` → `"red"`,
`formatColor("0", 3)` → `null`.

## `parseValue(string, options?) -> { v, z? } | null`

Parse a string into `{ v, z? }` where `v` is the value (dates/times as serials/fractions, booleans as
booleans) and `z` is the **inferred format code** — omitted when it would be `General`. Returns `null`
if unrecognized. Recognizes signed numbers, currency, percent (dividing by 100), parenthesized
negatives, grouped numbers, scientific (`E`) notation, dates, times, and booleans. The inferred `z`
mirrors the *input's own style* (a date/time reuses the field order and widths that were typed) and
never carries the negative sign (that is encoded in `v`); scientific input always infers the canonical
`0.00E+00` code regardless of how many decimals were typed. Examples:

- `parseValue("-123")` → `{ v: -123 }`
- `parseValue("$1,234")` → `{ v: 1234, z: "$#,##0" }`
- `parseValue("50%")` → `{ v: 0.5, z: "0%" }`
- `parseValue("(1,234)")` → `{ v: -1234, z: "#,##0" }`  (parentheses = negative)
- `parseValue("1.5E3")` → `{ v: 1500, z: "0.00E+00" }`  (scientific → canonical `0.00E+00`)
- `parseValue("07 October 1984")` → `{ v: 30962, z: "dd mmmm yyyy" }`
- `parseValue("11:12:13")` → `{ v: 0.4668171296296296, z: "hh:mm:ss" }`
- `parseValue("true")` → `{ v: true }`;  `parseValue("not a number")` → `null`

## `getFormatInfo(pattern) -> object`

Return format metadata:
`{ type, isDate, isText, isPercent, maxDecimals, scale, color, parentheses, grouped, code, level }`.

- `type` ∈ `general | number | grouped | percent | scientific | currency | fraction | date | time |
  datetime | text | error`.
- `isDate`/`isText`/`isPercent` booleans; `maxDecimals` (int); `scale` (1, 100 for percent, …);
  `color`/`parentheses`/`grouped` are `0`/`1` flags. `parentheses` is `1` only when the
  **positive/first section itself** is wrapped in parentheses (e.g. `(0)`); a parenthesized *negative*
  section (as in `$#,##0.00;[Red]($#,##0.00)`) does **not** set it — that pattern has `parentheses: 0`.
  `color` is `1` only when the **negative-number section** carries a color (in a single-section pattern
  that section acts as the negative one) — so `[Red]0` → `1` and `$#,##0.00;[Red]($#,##0.00)` → `1`,
  but `[Red]0;0` (only the positive section is colored) → `0`.
- `code` follows Excel's `CELL("format")` codes: number → `"F"`+decimals (`0.000` → `"F3"`); grouped →
  `","`+decimals (`",2"`); percent → `"P"`+decimals (`"P1"`); scientific → `"S"`+decimals (`"S2"`);
  currency → `"C"`+decimals, with a trailing `"-"` when it has a distinct negative section
  (`$#,##0.00;[Red]($#,##0.00)` → `"C2-"`); general/date/datetime/time/text/fraction → `"G"`.
- `level` is a numeric sort rank: text `15`, date/time/datetime `10.8`, percent `10.6`, currency
  `10.4`, grouped `10.2`, scientific `6`, number `4`, fraction `2`, general/error `0`.

Examples: `getFormatInfo("#,##0.00")` → `{ type:"grouped", isDate:false, isText:false,
isPercent:false, maxDecimals:2, scale:1, color:0, parentheses:0, grouped:1, code:",2", level:10.2 }`;
`getFormatInfo("0.0%")` → `{ type:"percent", …, isPercent:true, maxDecimals:1, scale:100, code:"P1",
level:10.6 }`; `getFormatInfo("@")` → `type:"text", level:15`; `getFormatInfo("General")` →
`type:"general", maxDecimals:9, level:0`.

## `getFormatDateInfo(pattern) -> object`

`{ year, month, day, hours, minutes, seconds, clockType }` — booleans for which date fields the
pattern uses, and `clockType` `12` (if it has `AM/PM`) or `24`. E.g. `getFormatDateInfo("h:mm AM/PM")`
→ `{ year:false, month:false, day:false, hours:true, minutes:true, seconds:false, clockType:12 }`.

## Date <-> serial

- `dateToSerial(date) -> number | null` — `date` is a `[year, month, day, h?, mi?, s?]`
  array (month is **1-based**). Returns the serial, or `null` for other input. `dateToSerial([1978,5,17])`
  → `28627`; `dateToSerial([1900,2,28])` → `59`, `dateToSerial([1900,3,1])` → `61` (serial 60 skipped).
- `dateFromSerial(serial) -> [year, month, day, hours, minutes, seconds]`. `dateFromSerial(28627)` →
  `[1978,5,17,0,0,0]`; `dateFromSerial(60)` → `[1900,2,29,0,0,0]`.

## Predicates & utilities

- `isDateFormat(pattern)` / `isPercentFormat(pattern)` / `isTextFormat(pattern)` → booleans
  (`isTextFormat` is true only for a text-only pattern like `@`, not `#;@`).
- `isValidFormat(pattern)` → `true` if the pattern parses (an **empty** pattern is valid); `false` for
  malformed (`"[foo"`) or more than four sections (`"0;0;0;0;0"`).
- `round(number, places = 0)` → half-away-from-zero rounding: `round(2.5)` = `3`, `round(-2.5)` = `-3`,
  `round(1.2345, 2)` = `1.23`. `places` may be **negative** to round to tens/hundreds
  (`round(12345, -2)` = `12300`).
- `dec2frac(number, numeratorMaxDigits = 2, denominatorMaxDigits = 2)` → `[numerator, denominator]`
  (reduced) — the **continued-fraction convergent** whose parts fit the digit limits (not necessarily
  the numerically closest fraction): `dec2frac(0.25)` → `[1, 4]`; `dec2frac(3.14159, 3, 3)` →
  `[355, 113]`; `dec2frac(2.71828, 4, 4)` → `[1264, 465]`.
- `tokenize(pattern)` → an array of `{ type, value, raw }` tokens; `type` is a lowercase kind such as
  `zero`, `hash`, `qmark`, `point`, `group`, `comma`, `scale`, `percent`, `break` (a `;` section
  separator), `color`, `paren`, `string`, `escaped`, `datetime`, `exp`, `slash`, `general`. `raw` is
  the verbatim source text and `value` is its inner content — for bracketed tokens they differ
  (`[Red]` → `{ type:"color", value:"Red", raw:"[Red]" }`). E.g.
  `tokenize("0.0%")` → `[{type:"zero",value:"0",raw:"0"}, {type:"point",value:".",raw:"."},
  {type:"zero",value:"0",raw:"0"}, {type:"percent",value:"%",raw:"%"}]`.
- `parseLocale(tag)` → `{ lang, language, territory }` for a BCP-47 locale tag
  (`"en-US"` → `{ lang:"en_US", language:"en", territory:"US" }`); throws a `SyntaxError` on a
  malformed tag.
