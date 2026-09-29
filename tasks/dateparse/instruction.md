# Build `dateparse` — a format-detecting date/time parser

Implement a Go package that parses date/time strings **without being told the format in advance**. It
inspects the string, infers which of many layouts it matches, and parses it — leaning toward US
(month-first) interpretation when a date is ambiguous.

## Deliverable and constraints

- Write a Go module whose root package is **`package dateparse`** and whose module path is
  **`dateparse`** (so the hidden tests, which are `package dateparse_test` and `import "dateparse"`,
  compile against it). Building with `go build ./...` must succeed.
- **Use only the Go standard library** (`time`, `strconv`, `strings`, `unicode`, `fmt`, …). No
  third-party dependencies. The build/test environment is **offline**.

## Public API (exact signatures)

```go
type ParserOption func(/* unexported */) error   // opaque option type returned by the funcs below

func ParseAny(datestr string, opts ...ParserOption) (time.Time, error)
func ParseIn(datestr string, loc *time.Location, opts ...ParserOption) (time.Time, error)
func ParseLocal(datestr string, opts ...ParserOption) (time.Time, error)
func ParseStrict(datestr string, opts ...ParserOption) (time.Time, error)
func MustParse(datestr string, opts ...ParserOption) time.Time          // panics on error
func ParseFormat(datestr string, opts ...ParserOption) (string, error)  // returns the detected layout

func PreferMonthFirst(preferMonthFirst bool) ParserOption
func RetryAmbiguousDateWithSwap(retry bool) ParserOption
```

- `ParseAny` parses in UTC for zone-less inputs; an explicit offset/zone in the string is honored.
- `ParseIn` parses zone-less inputs **in `loc`**. `ParseLocal` parses them in `time.Local`.
- `ParseFormat` returns the **Go reference layout** the input matches (see below) — it does *not*
  return a `time.Time`.
- `ParseStrict` behaves like `ParseAny` but **returns an error for any input whose month/day order is
  ambiguous** (any slashed `m/d/y`-style date), even if only one interpretation is numerically valid.
- The option funcs return values applied left-to-right; unknown-format inputs return a non-nil error.

## The Go reference layout

Go formats time against the reference instant **`Mon Jan 2 15:04:05 MST 2006`** (Unix `1136239445`),
whose components are: year `2006`/`06`, month `01`/`1`/`Jan`/`January`, day `02`/`2`, weekday
`Mon`/`Monday`, 24-hour `15`, 12-hour `03`/`3`, minute `04`/`4`, second `05`/`5`, AM/PM `PM`,
timezone `MST`/`-0700`/`-07:00`/`Z07:00`. `ParseFormat` must return the string built from these
reference components that matches the input's shape.

## Layout-detection rules (what `ParseFormat` returns)

**Field width mirrors the input token.** A numeric field written with a leading zero or two digits
uses the padded reference component; a single-digit field uses the unpadded one. This applies
independently per field, so month and day can differ:
- `03/31/2014` → `01/02/2006`; `3/31/2014` → `1/02/2006`; `3/5/2014` → `1/2/2006`.
- `2014/3/31` → `2006/1/02`; `2014/4/2` → `2006/1/2`.
- Times: `04:08:09` → `15:04:05`; `4:8:9` → `3:4:5`; `4:8` → `3:4`.

**Date separators** may be `-`, `/`, `.`, or `:` and are preserved literally; more generally, every
character that is not part of a recognized field is carried into the returned layout unchanged:
- `3.31.2014` → `1.02.2006`; `08.21.71` → `01.02.06`; `4:2:2014 04:08:09` → `1:2:2006 15:04:05`.

Two fields separated by a space may also be separated by a run of several spaces; such a run is
accepted, and because the extra spaces belong to no field they are carried into the returned layout
in full. (A *leading* space is still an error — see Rejected inputs.)

**Ambiguous month/day defaults to month-first (US).** `04/02/2014` → April 2 (`01/02/2006`). If the
first field cannot be a month (>12), it is rejected under the default: `31/03/2014` → error. Disable
with `PreferMonthFirst(false)` (day-first: `04/02/2014` → `02/01/2006`, Feb-4) or recover a swapped
date with `RetryAmbiguousDateWithSwap(true)` (`31/03/2014` → `2014-03-31`).

**Year width.** Four digits → `2006`, two digits → `06` (`8/8/71` → `1/2/06`). An apostrophe year
keeps the literal apostrophe and uses the two-digit year reference: `oct 7, '70` → `Jan 2, '06`.

**Fractional seconds** keep the exact digit count, and a comma separator is normalized to a dot in
the layout: `…:05.99` → `…:05.00`; `…:13,787` → `…:05.000`; `…:37.3186369` → `…:05.0000000`;
`…:59.257000000` → `…:05.000000000`.

**12/24-hour + AM/PM.** When an AM/PM marker is present the hour component follows the width rule
against the 24-hour vs 12-hour reference: a two-digit hour uses `15`, a single-digit hour uses `3`.
A marker set off by a space is normalized to the uppercase `PM` reference token; a marker attached
directly to the time with no separating space is preserved verbatim in its original case:
- `04/02/2014 4:8 PM` → `01/02/2006 3:4 PM`; `04/02/2014 04:08:09 AM` → `01/02/2006 15:04:05 PM`.
- `September 17, 2012 10:09am PST-08` → `January 02, 2006 15:04am MST-07` (attached `am` stays `am`).

**Connector words.** An `at`/`AT` word between the date and the time is preserved verbatim (original
case) in the layout: `September 17, 2012 at 5:00pm UTC-05` → `January 02, 2006 at 3:04pm MST-07`. In
a month-name date a **comma** may likewise separate the date from the following time; that separating
comma is kept literally in the returned layout: `March 3, 1999, 07:08:09` →
`January 2, 2006, 15:04:05`.

**Leading weekday.** A space-separated leading weekday name is dropped from the returned layout, but
a weekday immediately followed by a comma (RFC 1123 / RFC 822 style) is preserved and rendered as
`Mon,`:
- `Mon Jan 02 15:04:05 -0700 2006` → `Jan 02 15:04:05 -0700 2006` (space-separated: dropped).
- `Fri, 03 Jul 2015 08:08:08 MST` → `Mon, 02 Jan 2006 15:04:05 MST` (comma form: `Mon,` kept).
- `Fri Jul 03 2015 18:04:07 GMT+0100 (GMT Daylight Time)` → `Jan 02 2006 15:04:05 MST-0700`
  (the `GMT+0100 (…)` trailer becomes `MST-0700`).

**Month/weekday names** detect `Jan`/`January` (case-insensitive, optional trailing `.`) and produce
the matching reference token; a trailing `.` on an abbreviated name is kept as a literal in the
layout: `oct 7, 1970` → `Jan 2, 2006`; `7 September 1970` → `2 January 2006`; `2013-Feb-03` →
`2006-Jan-02`; `Sept. 7, '70` → `Jan. 2, '06`. The reference token mirrors the **length of the input
month word**: a month name of three letters uses the short `Jan` token, while a fully spelled name of
more than three letters uses `January`. This is decided purely by length, so `May` — whose complete
spelling is itself only three letters — takes the short `Jan` token, never `January`.

A **day-first** date that uses a month *name* with dash separators (`dd-Mon-yy` / `dd-Mon-yyyy`,
optionally followed by a time and a numeric offset) is recognized, and its layout mirrors the input's
day-first shape: `17-Sep-12` → `02-Jan-06`; `09-Mar-1999 07:08:09 +0530` →
`02-Jan-2006 15:04:05 -0700`. The month name removes the day/month ambiguity, so this form is
distinct from — and not blocked by — the rejected all-numeric `dd-mm-yyyy` dash form (see Rejected
inputs).

**Timezone forms.** A named/alphabetic zone abbreviation (`MST`, `PST`, `GMT`, `UTC`, …) renders as
the `MST` reference token. A numeric offset renders mirroring the input width — `-0700` (4 digits),
`-07:00` (with colon), or `-07` (2 digits) — with `+0000` rendering as `-0700` and `Z` as `Z`. E.g.
`2014-12-16 06:20:00 UTC` → `2006-01-02 15:04:05 MST`; `2012-08-03 …59.000000000 +0000` → `… -0700`;
`2006-01-02T15:04:05-0700` → itself. A date with **no time component** may still be immediately
followed by a numeric offset (`YYYY-MM-DD±HH:MM`); it is parsed as midnight at that offset:
`2021-11-05-05:00` → 2021-11-05T05:00:00Z.

**All-numeric inputs** are classified by digit count:
- 4 digits → year only: `2014` → `2006`.
- 8 digits → `YYYYMMDD`: `20140601` → `20060102`.
- 14 digits → `YYYYMMDDhhmmss`: `20140722105203` → `20060102150405`.
- 10 / 13 / 16 / 19 digits → Unix epoch in seconds / milliseconds / microseconds / nanoseconds; for
  these `ParseFormat` returns **the input string unchanged** and `ParseAny` returns the corresponding
  instant (`1332151919` → 2012-03-19T10:11:59Z; `1384216367111222333` → …:47.111222333Z).
- `060102 15:04:05`-style compact: `171113 14:14:20` → `060102 15:04:05`.

## Rejected inputs (return a non-nil error from both `ParseFormat` and `ParseAny`)

- Too short / not a date: `"3"`, `"xyzq-baad"`.
- Out-of-range fields: `"2009-15-12T22:15Z"` (month 15).
- `dd-mm-yyyy` with **dash** separators is not recognized: `"29-06-2016"`, `"3-31-2014"`.
- A leading space: `" 2018-01-02 17:08:09 -07:00"`.
- Malformed timezone offset: `"2019-05-29T08:41-047"` (offset must be 2 or 4 digits, optional colon).

## Notes

- Reproduce **standard Go `time` parsing/formatting semantics** exactly (layout components, zone
  math, fractional handling). Determinism: the tests pin `time.Local = time.UTC`, so zone-less
  results and the swap-retry path resolve at UTC.
- Error *wording* is not graded — only that an error is (or isn't) returned, plus exact layouts and
  parsed instants.
