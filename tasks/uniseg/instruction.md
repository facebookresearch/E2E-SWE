# uniseg — Unicode Text Segmentation, Line Breaking, and Monospace Width (Go)

Implement the Go package `github.com/rivo/uniseg`: a pure-standard-library library that splits
strings into **grapheme clusters**, **words**, and **sentences** according to
[Unicode Standard Annex #29](https://unicode.org/reports/tr29/), determines **line-break
opportunities** according to [Unicode Standard Annex #14](https://unicode.org/reports/tr14/), and
computes the **monospace display width** of strings.

The correctness of this package is defined entirely by these two Unicode annexes (UAX #29 and
UAX #14) and by the width rules stated below, at **Unicode 15.0.0** (the version of the provided
property tables). Grapheme-cluster, word, and sentence segmentation follow the default (untailored)
UAX #29 rules. Line breaking follows UAX #14 untailored except for numbers, where it applies the
tailoring of UAX #14 Section 8.2, Example 7 — rule LB25 replaced by the `Regex-Number` rule stated
there, together with the accompanying `[^NU]`-qualified form of LB13 — which is the variant the
official Unicode 15.0.0 `LineBreakTest.txt` data exercises. Your implementation must apply those
rules faithfully across the whole of Unicode — including the long tail of scripts, combining marks,
Hangul jamo, emoji ZWJ sequences, regional-indicator pairs, and the numeric / punctuation / spacing
line-break classes.

## Environment

- Go module rooted at `/app`, module path `github.com/rivo/uniseg` (see `/app/go.mod`), Go 1.22.
- **Fully offline.** The toolchain is pre-installed and `GOPROXY=off`; do not fetch anything. The
  library depends only on the standard library (`unicode/utf8`).
- `setup.sh` (which you write at `/app/setup.sh`) must build the package offline. A minimal one:
  ```bash
  #!/bin/bash
  export GOTOOLCHAIN=local GOPROXY=off GOFLAGS=-mod=mod GOCACHE="${GOCACHE:-/tmp/gocache}"
  go build ./... || return 1
  ```
  The grader runs it to build the package before running the test suite.

## Provided: the Unicode data layer (do NOT modify or re-create)

The Unicode Character Database property tables and their lookup helpers are **already provided** in
`/app` as part of the package. You must build the segmentation and line-breaking algorithms *on top*
of them — do not regenerate, hardcode, or alter these files:

- `properties.go` — the property-value constants (`prXX`, e.g. `prExtend`, `prZWJ`,
  `prRegionalIndicator`, `prExtendedPictographic`, `prL`/`prV`/`prT`/`prLV`/`prLVT`, the word/
  sentence/line-break classes, the East-Asian-width classes, `prEmojiPresentation`), the Unicode
  general-category constants (`gcXX`), the special code points `vs15`/`vs16`, and the lookup
  helpers below.
- `graphemeproperties.go`, `wordproperties.go`, `sentenceproperties.go`, `lineproperties.go`,
  `eastasianwidth.go`, `emojipresentation.go` — the generated range tables.

Lookup helpers you can call (all in `properties.go` — read it for the exact set):

- `property(dict [][3]int, r rune) int` — property value for `r` from a `[][3]int` table.
- `propertyGraphemes(r rune) int` — grapheme-cluster-break property (ASCII fast-pathed).
- `propertyLineBreak(r rune) (property, generalCategory int)` — line-break class + general category.
- `propertyEastAsianWidth(r rune) int` — East-Asian-width property.
- Tables: `graphemeCodePoints`, `workBreakCodePoints` (note: spelled `work…`, not `word…`),
  `sentenceBreakCodePoints` (`[][3]int`), `lineBreakCodePoints` (`[][4]int`), `eastAsianWidth`,
  `emojiPresentation` (`[][3]int`).

## Public API to implement

All functions live in `package uniseg`. The `state int` argument is an opaque parser state: pass
`-1` on the first call, then pass back the `newState` from the previous call to continue scanning
the same string. When a `rest`/remaining length reaches 0, the input is fully consumed.

### Grapheme clusters (UAX #29)

- `type Graphemes` with constructor `NewGraphemes(str string) *Graphemes` and methods:
  - `Next() bool` — advance to the next grapheme cluster; false when past the end. Must be called
    before the first cluster is read.
  - `Runes() []rune`, `Str() string`, `Bytes() []byte` — the current cluster (nil/empty before the
    first `Next` or past the end).
  - `Positions() (int, int)` — byte interval `[from, to)` of the current cluster in the original
    string (`0,0` before the first `Next`; `1,1` past the end).
  - `Reset()` — restart iteration.
  - `IsWordBoundary() bool`, `IsSentenceBoundary() bool` — whether a word/sentence ends after the
    current cluster.
  - `LineBreak() int` — one of `LineDontBreak`, `LineCanBreak`, `LineMustBreak` for the position
    after the current cluster.
  - `Width() int` — monospace width of the current cluster.
- `GraphemeClusterCount(s string) int` — number of grapheme clusters in `s`.
- `FirstGraphemeCluster(b []byte, state int) (cluster, rest []byte, width, newState int)` and
  `FirstGraphemeClusterInString(str string, state int) (cluster, rest string, width, newState int)`
  — the first grapheme cluster and its monospace width. Empty input returns zero values.
- `ReverseString(s string) string` — reverse `s` observing grapheme-cluster boundaries.

### Words (UAX #29) and sentences (UAX #29)

- `FirstWord(b []byte, state int) (word, rest []byte, newState int)` /
  `FirstWordInString(str string, state int) (word, rest string, newState int)`.
- `FirstSentence(b []byte, state int) (sentence, rest []byte, newState int)` /
  `FirstSentenceInString(str string, state int) (sentence, rest string, newState int)`.

### Line breaking (UAX #14)

- `FirstLineSegment(b []byte, state int) (segment, rest []byte, mustBreak bool, newState int)` /
  `FirstLineSegmentInString(str string, state int) (segment, rest string, mustBreak bool, newState int)`
  — the next segment after which a line break may (`mustBreak == false`) or must
  (`mustBreak == true`) occur. Per UAX #14 rule LB3, the final segment always ends with
  `mustBreak == true`.
- `HasTrailingLineBreak(b []byte) bool` / `HasTrailingLineBreakInString(str string) bool` — whether
  the last rune is a mandatory-break code point (LB4/LB5: BK, CR, LF, NL).
- Constants `LineDontBreak`, `LineCanBreak`, `LineMustBreak` (in that order; `LineDontBreak == 0`).

### Unified iterator

- `Step(b []byte, state int) (cluster, rest []byte, boundaries, newState int)` /
  `StepString(str string, state int) (cluster, rest string, boundaries, newState int)` — return the
  next grapheme cluster together with packed boundary/width info, combining the four algorithms
  above. Decode `boundaries` with the exported masks:
  - `MaskLine = 3` — `boundaries & MaskLine` is one of the `LineXxx` constants.
  - `MaskWord = 4` — nonzero if a word boundary follows the cluster.
  - `MaskSentence = 8` — nonzero if a sentence boundary follows the cluster.
  - `ShiftWidth = 4` — `boundaries >> ShiftWidth` is the cluster's monospace width.

### Monospace width

- `StringWidth(s string) int` — total monospace width of `s`.
- `EastAsianAmbiguousWidth int` — package-level variable (default `1`) giving the width used for
  East-Asian *Ambiguous* characters.

Width is computed per grapheme cluster; `StringWidth` sums the widths of all clusters.

**Single code point.** The width of one code point, given its grapheme-cluster-break property, is
determined by the following checks **in this exact order** (the first match wins):

1. Grapheme-break property Control, CR, LF, Extend, or ZWJ → **0**.
2. Grapheme-break property Regional Indicator → **2**.
3. Grapheme-break property Extended Pictographic → **2** if its Emoji Presentation flag is "Yes",
   otherwise **1**.
4. U+2E3A (Two-Em Dash) → **3**; U+2E3B (Three-Em Dash) → **4**.
5. East-Asian width Fullwidth (F) or Wide (W) → **2**; Ambiguous (A) → `EastAsianAmbiguousWidth`;
   otherwise → **1**.

The order matters: Regional Indicator and Extended Pictographic are decided **before** East-Asian
width and the em-dash special cases (e.g. an Extended Pictographic code point that is also East-Asian
Wide but has Emoji Presentation "No" has width 1, not 2).

**Grapheme cluster.** Let `firstProp` be the grapheme-break property of the cluster's first code
point. Initialize the cluster width to the single-code-point width of that first code point. Then,
for each subsequent code point `r` in the cluster:

- If `firstProp` is Extended Pictographic: if `r` is Variation Selector-15 (U+FE0E) **set** the
  cluster width to 1; if `r` is Variation Selector-16 (U+FE0F) **set** the cluster width to 2;
  otherwise leave it unchanged. (So the VS16 → 2 / VS15 → 1 override applies **only** when the
  cluster starts with an Extended Pictographic — not to arbitrary clusters ending in a variation
  selector.)
- Else if `firstProp` is **neither** Regional Indicator **nor** Hangul L (leading jamo): **add** the
  single-code-point width of `r` to the cluster width.
- Else (Regional Indicator or Hangul-L–initiated clusters): the subsequent code points contribute 0.

## Notes

- Tests import the package as an external `uniseg_test` package and exercise it through the public
  API above against the official Unicode 15.0.0 conformance vectors; they do not inspect internal
  types, state encodings, or unexported symbols, so you are free to design those however you like.
