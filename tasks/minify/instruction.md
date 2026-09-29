# Build a multi-format minifier CLI (`minify`)

Implement a command-line **minifier** in Go that removes redundant bytes from **CSS**, **JSON**, and
**XML** while preserving semantics. Minification means producing the shortest byte sequence that is
equivalent to the input for that format. Output is deterministic and byte-exact.

## Language / dependency constraint

- Implement everything using the **Go standard library only**. Do not add third-party modules.
- Your build must produce the executable at **`/app/minify`**. Provide a `setup.sh` in the working
  directory that builds it, e.g. `go build -o /app/minify .`.

## CLI contract

- The program reads the document from **stdin** and writes the minified result to **stdout**.
- `--type=<css|json|xml>` selects the input format. When reading from stdin, `--type` is
  **required**; without it the program must exit non-zero and print a diagnostic to stderr.
- `-o <file>` / `--output <file>` writes the result to `<file>` instead of stdout.
- The output is the exact minified bytes with **no trailing newline appended**.
- Empty input produces empty output with exit code 0.
- Flags:
  - `--json-keep-numbers` — do not rewrite JSON number literals.
  - `--json-precision <n>` — round JSON numbers to `n` significant digits (`0` = no limit).
  - `--css-precision <n>` — round CSS numeric values to `n` significant digits (`0` = no limit).
  - `--xml-keep-whitespace` — keep whitespace in XML text, but still collapse runs to one space.

## Number canonicalization

Numbers are rewritten to a shorter equivalent representation. Unless noted, these rules apply to both
CSS and JSON:

- Drop trailing fractional zeros: `1.500` → `1.5`, `1.0` → `1`, `5.0` → `5`, `50.0` → `50`.
- Use scientific notation **only when the result is strictly shorter** than the plain form, with a
  lowercase `e` and no `+` and no leading zeros in the exponent: `100000` → `1e5`, `1000` → `1e3`,
  `0.0001` → `1e-4`, `1E+03` → `1e3`, `1.3e1` → `13`, `10000` → `1e4`, `1000000` → `1e6`. When the
  scientific form is not shorter, the plain form is kept: `100` stays `100`, `12345678` stays
  `12345678`, and an already-minimal `1e3`/`1e100`/`1e-100` is kept. The plain-vs-scientific length
  comparison is made against the **fully shortened plain form** (with a CSS-style leading integer
  zero dropped, e.g. `.001`), and a **tie keeps the plain form**; a format that then requires a
  leading digit (JSON, below) re-adds it only after this decision.
- Any zero value collapses to `0`, dropping a sign or exponent: `-0` → `0`, `-0.0` → `0`, `0e0` → `0`.
- With a precision flag, keep at most `n` significant digits (precision 4 turns
  `3.141592653589793` into `3.142`; precision 3 turns `1.23456` into `1.23`).

**CSS-only:** additionally drop a leading integer zero from a fraction — `0.5` → `.5`, `-0.5` → `-.5`,
`0.05` → `.05`, `0.001` → `.001`.

**JSON keeps the leading zero** (its grammar requires a digit before the decimal point): `0.1` stays
`0.1`, `0.5` stays `0.5`, `0.05` stays `0.05`.

## JSON minification

- Remove all insignificant whitespace between tokens; preserve document structure exactly.
- Canonicalize numbers as above unless `--json-keep-numbers` is set (which preserves the original
  literal, e.g. `1.0` stays `1.0` and `1E+03` stays `1E+03`).
- Preserve string contents byte-for-byte, including escape sequences (`\n`, `\t`, `\/`, `\uXXXX`,
  surrogate pairs) and object keys.
- Preserve `true`/`false`/`null` and duplicate keys.
- Syntactically invalid JSON is an error: exit non-zero with a diagnostic on stderr.

## CSS minification

**Whitespace / structure**

- Remove whitespace around selectors, combinators (`>`, `+`, `~`), commas, colons, braces and
  declarations: `a , b { x : y }` → `a,b{x:y}`; `a > b` → `a>b`.
- Drop the trailing semicolon of the last declaration in a block; drop empty declarations
  (`a{;;}` → ``); remove rules with an empty body entirely (`a{}` → ``); remove blank lines between
  rules.
- Remove comments everywhere, including between selector tokens (`a/*x*/b` → `ab`). The one exception
  is a `/*! ... */` bang comment, which is kept and internally trimmed (`/*! keep */` → `/*!keep*/`).
- Lowercase element (type) selector names, at-rule keywords (`@MEDIA` → `@media`) and hex color
  digits — but **not** class names, IDs, or other custom identifiers (`.CLA` stays `.CLA`).
- Unquote an attribute-selector value when it is a **valid CSS identifier**, for every operator
  (`=`, `~=`, `|=`, `*=`, `^=`, `$=`), and remove internal whitespace: `[type="radio"]` →
  `[type=radio]`, `[id ^= L]` → `[id^=L]`, `[class~="x"]` → `[class~=x]`. A value that is not a valid
  identifier keeps its quotes: `[href$=".pdf"]` stays `[href$=".pdf"]` (leading `.`).

**Values**

- Colors are rewritten to the **shortest** equivalent, choosing freely among 6-/3-digit hex,
  8-/4-digit hex, `rgb()`/`rgba()` (comma or space separated), `hsl()`/`hsla()`, and color names:
  - `#ffffff` → `#fff`, `#aabbcc` → `#abc`, `#AABBCCDD` → `#abcd` (collapse 6→3 / 8→4 when each pair
    repeats; lowercase digits).
  - `white` → `#fff`, `black` → `#000` (name → shorter hex); `#ff0000` → `red`, `#808080` → `gray`,
    `rgb(255,0,0)` → `red`, `rgb(255 0 0)` → `red`, `rgb(0,128,0)` → `green` (→ shorter name);
    `rgb(1,2,3)` → `#010203` (→ hex when no shorter name).
  - A **fully opaque** color drops its alpha and shortens: `#ffffffff` → `#fff`,
    `rgb(255,255,255)` → `#fff`, `rgba(255,255,255,1)` → `#fff`, `hsl(120,100%,50%)` → `#0f0`.
  - `rgba(0,0,0,0)` → `transparent`. A partial alpha `0 < a < 1` is left as-is:
    `rgba(255,0,0,.5)` and `hsla(0,100%,50%,.5)` are unchanged.
  - A color is switched to a different representation **only when that representation is strictly
    shorter** than the current one; when a shortening is forced and several equivalents tie for the
    shortest length, the hex form is chosen.
- Drop the unit of a **zero length or angle**: `0px` → `0`, `-0px` → `0`, `rotate(0deg)` →
  `rotate(0)`, `rotate(0turn)` → `rotate(0)`. Keep the unit where CSS requires it for a zero, e.g.
  `0s` (time) and `0%` (percentage) stay.
- Collapse repeated box shorthands to the shortest mirrorable form: `0 0 0 0` → `0`, `0 0` → `0`,
  `1px 1px` → `1px`, `10px 20px 10px 20px` → `10px 20px`, `5px 10px 5px` → `5px 10px`,
  `1px 2px 1px` → `1px 2px`. A shorthand that is **not** a mirrorable pattern is left unchanged:
  `1px 2px 3px 4px` and `1px 2px 3px` stay. Collapsing still applies when `!important` follows:
  `margin:0 0 0 0 !important` → `margin:0!important`. Negative values are preserved (`-10px`).
- Collapse runs of whitespace inside a value to a single space: `1px    2px` → `1px 2px`.
- `font-weight:bold` → `font-weight:700`, `font-weight:normal` → `font-weight:400`.
- Remove all whitespace around the `!important` annotation and between its `!` and the `important`
  keyword, but **preserve the keyword's letter case**: `red !important` → `red!important`,
  `red !IMPORTANT` → `red!IMPORTANT`.
- Unquote a `url(...)` value and remove internal whitespace when the result is still a valid
  unquoted URL token: `url('x.png')` → `url(x.png)`. A value that needs quotes (e.g. containing a
  space) keeps them.
- Preserve function bodies that must not be reordered/re-spaced: `calc(...)` internal spacing
  (including nested `calc(100% - calc(10px + 5px))`), `min()`/`max()`/`clamp()`, `var(--x)` — but a
  comma inside a `var()` fallback drops its following space: `var(--x, red)` → `var(--x,red)`.
  `@keyframes` bodies and custom-property values are preserved (trimming only surrounding
  whitespace: `--my-var: 10px` → `--my-var:10px`).

**At-rules**

- Collapse whitespace inside media/feature queries: `(max-width : 800px)` → `(max-width:800px)`.
- The space after `@media` is removed only when the query begins with `(`:
  `@media (min-aspect-ratio:16/9){…}` → `@media(min-aspect-ratio:16/9){…}`, but a query beginning
  with a keyword keeps the space: `@media only screen and (max-width:800px){…}`, `@media all{…}`.
  Comma-separated media lists and `not`/`only` qualifiers keep their structure
  (`@media screen,print{…}`, `@media not all and (monochrome){…}`).
- `@supports (…)` → `@supports(…)`; `@import url('file');` → `@import 'file'`;
  `@charset "utf-8";` → `@charset "utf-8"`.

Malformed CSS is handled leniently — the minifier recovers and still exits 0 (CSS is not strictly
validated the way JSON is).

## XML minification

- Collapse insignificant whitespace between and inside elements
  (`<root>  <a> x </a>  </root>` → `<root><a>x</a></root>`; `x    y` → `x y`). With
  `--xml-keep-whitespace`, keep whitespace but still collapse each run to a single space.
- Rewrite an element with no content to self-closing form: `<a></a>` → `<a/>`. This applies only to
  elements already written empty in the source; an element left empty solely because its comments (or
  whitespace) were removed keeps its explicit open and close tags (`<a><!--c--></a>` → `<a></a>`).
- Remove whitespace around attribute assignments, keeping the original quote character and a single
  space between attributes: `<a  b = 'c' />` → `<a b='c'/>`; `<a  x='1'   y='2'/>` → `<a x='1' y='2'/>`.
- Remove comments, including those between sibling elements (`<a/><!--c--><b/>` → `<a/><b/>`).
- Always unwrap a `CDATA` section to text, escaping any characters that then need it:
  `<![CDATA[ x ]]>` → ` x `; `<![CDATA[x < y]]>` → `x &lt; y`.
- Preserve the XML declaration (`<?xml version='1.0'?>`) and character entity references
  (`&amp;`, `x &amp; y`).
