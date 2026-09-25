# render — a Django-style template engine

Implement a command-line tool named `render` that renders a text template (Django/Jinja-style syntax)
against a JSON context.

Write it in **Go, using only the standard library** (no third-party modules). Your build must produce
the binary at `/app/render`. Provide a `setup.sh` in the working directory that builds it, e.g.:

```sh
go build -o /app/render .
```

## Command-line interface

```
render <template-file>
```

- The single argument is a path to a template file.
- A **JSON object** is read from standard input and becomes the template context.
- The rendered result is written to standard output.

### JSON context mapping

- JSON string → string; JSON `true`/`false` → boolean; JSON `null` → an absent/none value.
- JSON number: the int/float distinction follows the JSON literal's **lexical form**, not its value — a
  number written without a `.`, `e`, or `E` (e.g. `5`) is provided as an **integer**, while one written
  with any of them (e.g. `5.5`, `2.0`, `1e3`) is a **float**. So `2.0` is a float (it renders
  `2.000000`), not an integer.
- JSON array → a list (index with `.0`, `.1`, …); JSON object → a map (access with `.key`).
- A variable that is not in the context renders as the **empty string**.

### Exit codes

- `0` — success.
- `1` — the template fails to parse or to render (write a diagnostic to stderr, no stdout).
- `2` — no template-file argument, or the stdin context is not valid JSON.

## Template syntax

Implement standard Django template semantics, with the specifics below. Output tags `{{ expr }}`
evaluate an expression; block tags `{% tag ... %}` control rendering.

### Expressions

- **Literals**: integers, floats, single- or double-quoted strings, `true`/`false`, and identifiers.
- **Access**: `a.b` (map key or struct-like field) and `a.0` (list index), chainable (`a.b.0.c`).
- **Arithmetic**: `+ - * / %` with standard precedence (`*`,`/`,`%` bind tighter than `+`,`-`), and
  unary minus. Division of two integers is **integer division** (`7 / 2` → `3`).
- **Comparison**: `== != < > <= >=` (strings compare lexicographically). **Logical**: `and`, `or`,
  `not`, where `not` binds tightest and `and` binds tighter than `or` (`a or b and c` == `a or (b and c)`).
  **Membership**: `x in seq`. Iterating a string with `{% for c in s %}` yields its characters.
- **Filters**: `expr|name` or `expr|name:arg`, chainable left-to-right (`x|lower|capfirst`).

### Output and auto-escaping

`{{ }}` output is **HTML auto-escaped by default**: `< > & ' "` become `&lt; &gt; &amp; &#39; &quot;`.
This applies to the *result* of the expression, including strings produced by filters (so, e.g.,
`linebreaksbr` — which inserts `<br />` — has that `<br />` escaped in the default output). Use the
`safe` filter, or wrap a region in `{% autoescape off %}…{% endautoescape %}`, to emit raw HTML. Once a
value is marked safe (by `safe`), it stays safe through the rest of a filter chain (`x|safe|upper` is
not re-escaped).

Rendering of values:
- Booleans render as `True` / `False`. Integers render with no decimal point.
- **Floating-point values render with six decimal places** (Go `%f` formatting): `5.5` → `5.500000`,
  and `1.0 + 2.0` → `3.000000`. (This is only the default rendering of a bare float; the `floatformat`
  filter controls precision explicitly.) Note integer ÷ integer is integer division, so `10 / 4` → `2`,
  but a float operand makes the result a float.
- Text outside `{{ }}`/`{% %}` is emitted verbatim, including stray `%` and `}` characters.

### Tags

- `{% if %}` / `{% elif %}` / `{% else %}` / `{% endif %}`
- `{% for x in seq %}` … `{% empty %}` … `{% endfor %}` (append ` reversed` to iterate in reverse:
  `{% for x in seq reversed %}`), with a `forloop` object exposing
  `Counter` (1-based), `Counter0` (0-based), `Revcounter` (n..1), `Revcounter0`, `First`, `Last`, and
  (inside a nested loop) `Parentloop` referring to the enclosing loop's forloop object.
- `{% ifequal a b %}` / `{% else %}` / `{% endifequal %}` (and `{% ifnotequal %}`/`{% endifnotequal %}`).
- `{% with name=expr %}` … `{% endwith %}` (defines a scoped variable).
- `{% set name=expr %}` (defines a variable in the current scope).
- `{% cycle "a" "b" … %}` — cycles through its arguments on successive calls within a loop.
- `{% firstof a b c %}` — outputs the first argument that is truthy.
- `{% spaceless %}` … `{% endspaceless %}` — removes whitespace *between* HTML tags.
- `{% filter name %}` … `{% endfilter %}` — applies a filter to the block's contents.
- `{% comment %}` … `{% endcomment %}` — omitted from output.
- `{% templatetag openblock %}` etc. — emits literal delimiters: `openblock`→`{%`, `closeblock`→`%}`,
  `openvariable`→`{{`, `closevariable`→`}}`.
- `{% macro name(args) %}` … `{% endmacro %}` defines a callable macro; call it as `{{ name(a, b) }}`.
  A macro's body is rendered as template output — its literal text is emitted verbatim and only the
  inner `{{ }}` expressions are escaped normally — and the calling `{{ name(...) }}` emits that rendered
  fragment as-is (already safe, not re-escaped), so literal markup such as `<`/`>` in the macro body
  passes through unescaped.
- **Inheritance / composition** (templates resolve referenced files relative to the current template):
  - `{% extends "base.html" %}` with `{% block name %}…{% endblock %}`; a child overrides a parent's
    block by redefining it, and blocks may be nested.
  - `{% include "partial.html" %}` renders another template inline with the current context.

### Filters

Implement these with standard Django semantics; specific behaviors are pinned where they matter:

- Case/'text': `upper`, `lower`, `title`, `capfirst`. `title` lowercases the whole string, then
  capitalizes the first letter of each run of alphanumerics that begins at the start or immediately
  after a non-alphanumeric separator (space, apostrophe, hyphen, …); a letter that immediately follows a
  digit stays lowercase (digits are not word boundaries), e.g. `jean-luc o'neil 2nd` → `Jean-Luc O'Neil 2nd`.
- `truncatechars:n` — truncate to `n` characters **including** a trailing `...` when truncated.
- `truncatewords:n` — keep the first `n` words and append ` ...` when truncated.
- `wordcount`; `make_list` (string → list of its characters); `phone2numeric` (letters → phone digits).
- Padding: `center:w`, `ljust:w`, `rjust:w` (pad to width `w`; when the padding is odd, `center` puts
  the **extra** space on the **left**, and when it is even the padding is split evenly on both sides,
  e.g. `"hi"|center:9` → `"    hi   "` and `"ab"|center:6` → `"  ab  "`). `cut:"s"` removes all
  occurrences of `s`. `slice:"a:b"` slices sequences/strings using non-negative `a`/`b` bounds
  (`slice:":3"`, `slice:"2:"`).
- Numbers: `floatformat` — rounding uses **round-half-to-even** (banker's rounding) applied to the
  value's **exact stored IEEE-754 `float64`** — equivalently Go's `strconv.FormatFloat(x, 'f', n, 64)`,
  not a decimal-string or scale-by-`10^n` intermediate. Exactly-representable halves round to even
  (`2.5|floatformat:0` → `2`, `3.5|floatformat:0` → `4`), but a written decimal whose nearest `float64`
  is slightly above it is **not** a tie and rounds up. No arg → round to **1** decimal; `floatformat:n`
  (n≥0) → `n` decimals; `floatformat:"-n"` → `n` decimals but drop them entirely if the value is integral
  (`3.0|floatformat:"-2"` → `3`, `3.1|floatformat:"-2"` → `3.10`). A negative value that rounds to a
  zero magnitude keeps its leading minus sign (`-0.4|floatformat:0` → `-0`).
- `divisibleby:n`; `get_digit:n` (n-th digit from the right, 1-based; returns the value unchanged if
  `n` exceeds its digits); `add:x` (numeric add, or string concatenation when both are strings);
  `pluralize` (→ `"s"` unless the value is 1; `pluralize:"es"` for a custom suffix; `pluralize:"y,ies"`
  for distinct singular,plural suffixes); `stringformat:"fmt"` — passes the value through a
  C/`printf`-style format that **must include the leading `%`** (e.g. `stringformat:"%05d"` → `00042`).
- Lists: `join:"sep"`, `length`, `length_is:n`, `first`, `last`, `split:"sep"`.
- Defaults: `default:"x"` (use `x` if the value is falsy), `default_if_none:"x"` (use `x` only if the
  value is none/null). `yesno:"y,n,maybe"` (true→y, false→n, none→maybe; two-arg `yesno:"y,n"` maps
  none to the false value).
- `slice:"a:b"` also slices lists. `stringformat` accepts any single C/`printf` verb
  (`%d %x %o %e %g %.2f %+d %05d %10s …`); a literal `%` is written `%%`. `get_digit` on a single-digit
  value returns it unchanged.
- HTML / encoding filters:
  - `escape`, `safe`, `striptags` (remove all `<…>` tags, including their attributes).
  - `escapejs` — JavaScript-escape, producing `\uXXXX` (uppercase hex) forms for `'` `"` `<` `>` `&`
    `\`, ASCII control characters (newline = `\u000A`, tab = `\u0009`, CR = `\u000D`), and
    non-ASCII runes (`é` = `\u00E9`). `/` is left as-is.
  - `urlencode` — percent-encode every byte **except** the unreserved set `A-Za-z0-9` and `-` `_` `.`
    `~`; spaces become `+`; non-ASCII is percent-encoded per UTF-8 byte (`é`→`%C3%A9`). Reserved
    characters like `/ @ : ? = # & ! * ( )` **are** encoded.
  - `iriencode` — like `urlencode` but leaves the reserved characters `/ ? = # &` unencoded; spaces
    still become `+` and non-ASCII is still percent-encoded.
  - `linebreaksbr` — every newline → `<br />` (leading/trailing newlines included).
  - `linebreaks` — split into paragraphs on blank lines (a run of one or more empty lines is a single
    separator); wrap each paragraph in `<p>…</p>` and convert single newlines inside
    a paragraph to `<br />`. Consecutive wrapped paragraphs are concatenated **back-to-back with no
    separator** between them, e.g. `"a\n\nb"|linebreaks` → `<p>a</p><p>b</p>`. Leading blank lines are
    dropped, but a trailing blank line yields a final empty `<p></p>`. An input consisting solely of
    blank lines (no non-blank content) yields a single empty paragraph, e.g. `"\n\n\n"|linebreaks` →
    `<p></p>`.
  Remember auto-escaping applies to these results too (unless `safe`), so `linebreaks`/`linebreaksbr`
  output has its `<br />`/`<p>` escaped in the default context.

Iteration over lists preserves order. (Do not rely on any particular iteration order for maps.)

## Examples

```
$ printf '{% for x in xs %}{{ forloop.Counter }}:{{ x }}{% if not forloop.Last %},{% endif %}{% endfor %}' > t.html
$ echo '{"xs":["a","b","c"]}' | render t.html
1:a,2:b,3:c

$ printf '{{ s }}|{{ s|safe }}' > t.html
$ echo '{"s":"<b>x</b>"}' | render t.html
&lt;b&gt;x&lt;/b&gt;|<b>x</b>

$ printf '{{ n|floatformat }} {{ n|floatformat:2 }}' > t.html
$ echo '{"n":3.14159}' | render t.html
3.1 3.14

$ printf '{{ x|stringformat:"%05d" }}' > t.html
$ echo '{"x":42}' | render t.html
00042
```
