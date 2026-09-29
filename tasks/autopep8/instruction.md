# autopep8

Build `autopep8`, a command-line tool that automatically reformats Python source code to
conform to the [PEP 8](https://peps.python.org/pep-0008/) style guide. It reads Python source,
detects style violations, rewrites the parts that need fixing, and reproduces the rest of the
source unchanged.

Organize the internals however you like as long as the command-line interface and the observable
formatting behavior described here are reproduced exactly.

## Example use case

autopep8 reads Python source, fixes the parts that violate PEP 8, and leaves everything else
unchanged. By default it makes only whitespace/layout fixes; `-a`/`--aggressive` (repeatable)
enables semantic fixes. Run it on a file — writing the result to stdout, rewriting in place, or
showing a diff:

```console
$ python -m autopep8 example.py             # print the reformatted source to stdout
$ python -m autopep8 --in-place example.py  # rewrite the file in place
$ python -m autopep8 -aa --diff example.py  # show a unified diff, with aggressive fixes applied
```

More concretely, here are the transformations the examples above produce (reading from
stdin with `-`):

Whitespace normalization on stdin (default mode):

```
$ printf 'x=1\nspam( ham[ 1 ] )\n' | python -m autopep8 -
x = 1
spam(ham[1])
```

A `== None` comparison is only rewritten with `--aggressive`:

```
$ printf 'if x == None:\n    pass\n' | python -m autopep8 -a -
if x is None:
    pass
```

Structure-aware line shortening collapses a too-long collection (two `--aggressive` flags):

```
$ printf "d = {'apple': 1, 'banana': 2, 'cherry': 3, 'damson': 4, 'elderberry': 5, 'fig': 6}\n" \
    | python -m autopep8 -aa -
d = {
    'apple': 1,
    'banana': 2,
    'cherry': 3,
    'damson': 4,
    'elderberry': 5,
    'fig': 6}
```

## Dependencies

autopep8 does **not** detect the violations itself. It uses the
[`pycodestyle`](https://pypi.org/project/pycodestyle/) library (the PEP 8 checker) to report
every violation as a `(line, column, code, text)` record, and then applies a fix for each code it
supports. Depend on `pycodestyle` (>= 2.12) and use it for detection; your job is the *fixing*
engine on top of it. No other third-party runtime dependency and no network access are needed.

## Invocation

The package installs with `pip install -e .` and must be runnable as `python -m autopep8`.
The general form is:

```
python -m autopep8 [OPTIONS] <file> [<file> ...]
```

A single `-` in place of a file means "read source from standard input".

### Modes (how output is produced)

- **Standard input (`-`)**: read the whole source from stdin, write the formatted source to
  stdout, and exit `0` (or, under `--exit-code`, `2` when the source was changed). `--in-place`,
  `--diff`, and `--recursive` are errors when reading from stdin.
- **Default (one file argument, no mode flag)**: do not modify the file; write the formatted
  source to stdout.
- **`--diff` / `-d`**: do not modify any file; write a unified diff of the proposed changes to
  stdout. Use `difflib.unified_diff` with the header labels `original/<path>` and `fixed/<path>`
  (the path exactly as given on the command line) and `lineterm='\n'`.
- **`--in-place` / `-i`**: rewrite each file that would change with its formatted contents; write
  nothing to stdout.

`--in-place` and `--diff` are mutually exclusive. With more than one file argument, `--in-place`
or `--diff` is required.

### Exit codes

By default the exit code does **not** reflect whether changes were made:

- `0`: success (this is returned even when source was reformatted).
- `1`: an I/O error occurred (for example, an input file does not exist or cannot be read).
- `99`: a command-line usage error (see below).

When `--exit-code` is given, the tool instead returns `2` when there were any differences (and
still `0` when the input was already formatted). Usage errors that return `99` include: no file
arguments and no `--list-fixes`; mixing stdin (`-`) with `--diff`, `--in-place`, or `--recursive`;
giving both `--diff` and `--in-place`; more than one file without `--in-place`/`--diff`; using
`--recursive` without `--in-place` or `--diff` (a usage error on its own), or likewise requesting
more than one parallel `--jobs` (a value greater than 1) without `--in-place`/`--diff`; and a
`--max-line-length` that is not greater than 0.

## How fixing works

Run pycodestyle on the source to get the list of violations, then repeatedly apply the
fixes below and re-run pycodestyle until the source stops changing (a fixed point). Formatting is
**idempotent**: running autopep8 on already-formatted output yields identical text. Content inside
multiline strings (triple-quoted strings and docstrings) is never reformatted — only real code is
touched. Line endings are normalized to the file's dominant newline.

Each fix is identified by its pycodestyle code, and the `--select` / `--ignore` options (below)
control which codes are fixed. Code matching is by prefix in **both** directions: a selected/
ignored value of `E1` matches `E111`, `E126`, etc., and a value of `E126` is also matched by the
family `E1`.

### Default (whitespace-only) fixes

In the **default** aggressiveness level autopep8 makes only whitespace/layout changes. The
following are always applied unless ignored:

- **E101 / W191** — re-indent: convert tab indentation to 4 spaces and make indentation
  consistent.
- **E111 / E114 / E117** — normalize statement indentation to a multiple of 4 spaces per
  block-nesting level, independent of whether tabs are present. This belongs to the same `E1`
  indentation family as E101, so `--ignore=E1` disables it too.
- **E12x** — fix the indentation of continuation lines of a bracketed expression. Continuation
  indentation is tracked **per bracket**: each continuation line is governed by the innermost
  bracket still open at the start of that line, and once an inner bracket closes on a continuation
  line the following lines revert to the alignment of the enclosing (outer) bracket. For the
  governing bracket, when the opening bracket is followed by a token on the same line, align
  continuation lines under that first token (visual indent); when the opening bracket is the last
  thing on its line, indent the continuation lines by 4 from the indentation of the line that opens
  the bracket — i.e. 4 additional spaces per nested bracket level (hanging indent). A comment line
  inside the continuation is aligned the same way. A closing bracket left alone on its own line
  aligns with the visual indent (visual case) or returns to the statement's own indentation
  (hanging case). One exception: a `def`'s parameter list opened with a hanging indent uses an
  **8-space** hang (a double indent) so the parameters are visually distinct from the 4-space body.
- **E201 / E202** — remove whitespace just inside `(`, `[`, `{` and just before `)`, `]`, `}`.
- **E211** — remove whitespace before a `(` call or `[` subscript.
- **E225 / E231** — add the single space PEP 8 requires around operators (E225) and after `,`/`:`
  separators (E231).
- **E251** — remove the spaces around the `=` of a keyword argument / parameter default.
- **E221 / E222** — collapse multiple spaces before/after an operator down to the single required
  space (e.g. `x       = 1` → `x = 1`).
- **E271 / E272 / E273 / E274 / E275** — normalize whitespace around keywords (`and`, `or`, `in`,
  `not`, `if`, `else`, …) to a single space (e.g. `a  and  b` → `a and b`).
- **E203** — remove whitespace before a `,`, `;`, or `:` (e.g. `print(a ,b)` → `print(a, b)`,
  `if True :` → `if True:`).
- **E261** — an inline comment is separated from the code by at least two spaces (e.g. `x = 1 # c`
  → `x = 1  # c`).
- **E262 / E265 / E266** — normalize comment hashes: an inline comment uses a single `# `, a block
  comment has one space after its `#`, and extra leading hashes on a block comment (`## `, `### `)
  collapse to a single `# `.
- **E301 / E302 / E303 / E304 / E305 / E306** — normalize blank lines around definitions: two blank
  lines around top-level functions/classes, one inside classes, with excess blank lines removed and
  missing ones inserted (including after a function/class body before following top-level code), and
  any blank line between a decorator and the function/class it decorates is removed (E304).
- **E401** — put each comma-separated `import` on its own line.
- **E701 / E702 / E703** — split a colon-compound statement (`if x: y`) and semicolon-joined
  statements (`a; b`) onto separate lines, and remove a redundant trailing semicolon (`x = 1;` →
  `x = 1`); each resulting statement keeps the indentation of the original line (statements that
  end up inside a block are indented to match that block).
- **E502** — remove a backslash line-continuation that is redundant because the break is already
  inside brackets (e.g. `(1 + \` followed by `2)` drops the `\`).
- **E501** — shorten lines longer than the maximum length (see "Long lines" below).
- **W291 / W293** — strip trailing whitespace from code lines and from otherwise-blank lines.
- **W292** — add a final newline if the file does not end with one.
- **W391** — remove blank lines at the end of the file.

By default the codes `E226` (missing whitespace around an arithmetic operator such as `a+b`),
`E24`, `W503`/`W504` (line break before/after a binary operator), and `W690` are **not** fixed.
So in default mode `a+b` is left as-is.

### Aggressive (non-whitespace) fixes

`-a` / `--aggressive` enables changes that may alter semantics; repeating the flag raises the
level. Higher levels also shorten lines more aggressively (see below). The semantic fixes are
gated by level:

- **One `-a` (level 1):**
  - **E711** — `x == None` → `x is None`; `x != None` → `x is not None`.
  - **E722** — a bare `except:` → `except BaseException:`.
  - **E731** — a `name = lambda args: body` assignment → `def name(args): return body`.
  - **W605** — fix an invalid escape sequence in a string literal (e.g. `'\d'` → `'\\d'`).
- **Two `-a` (level 2):**
  - **E712** — `x == True` → `x`; `x == False` → `not x`; and the `!=` forms invert: `x != True` →
    `not x`; `x != False` → `x`.
  - **E713** — `not x in y` → `x not in y`.
  - **E714** — `not x is y` → `x is not y`.
  - **E721** — a type comparison `type(x) == type(y)` → `isinstance(x, type(y))`.
  - **E402** — a module-level import placed after other code is moved up above that code (kept below
    a leading module docstring / `__future__` imports).
- **Three `-a` (level 3):**
  - **E704** — split a one-line `def f(): return x` into two lines.

(When `--aggressive` is given without `--select`/`--ignore`, the default-ignored codes above are
re-enabled so that, e.g., `E226` is fixed.)

### Long lines (E501)

A line longer than the maximum length (`--max-line-length`, default `79`) is shortened:

- **Default level** — shorten "physically": prefer breaking right after an opening **call or
  collection-literal** bracket so its contents move onto the next line (indented by 4). Subscript /
  indexing brackets (`obj[...]`) are **not** used as physical break points. If there is no call or
  collection-literal bracket to break inside, fall back to a backslash (`\`) continuation: keep the
  binary operator at the end of the first line, follow it with a single space and then the `\`, and
  indent the continuation line by 4.
- **Aggressive (two or more `-a`)** — reflow the logical line by its structure: place each
  top-level element of a bracketed call/collection on its own line, indented by 4 per nesting
  level, with the closing bracket attached to the last element. Any nested bracket that contains
  more than one element is likewise reflowed one element per line, recursively, regardless of
  whether that nested bracket by itself still exceeds the limit. A `def` signature reflowed this
  way puts each parameter on the 8-space def double-hang. When the line cannot be broken inside a
  bracket, fall back to a backslash continuation (operator kept at the end of the first line,
  followed by a single space and then the `\`, 4-space indent).

Lines that lie inside multiline strings, and lines that look like commented-out code, are not
shortened.

Under `--aggressive`, a comment line that exceeds the maximum length (and is not commented-out
code) is additionally word-wrapped at whitespace boundaries so that each resulting physical line
fits within the limit, with every continuation line kept at the original indentation and
re-prefixed with `# `. In the default (non-aggressive) mode an over-length comment is left
unchanged.

### Disabling regions

A region bracketed by `# autopep8: off` ... `# autopep8: on` (or `# fmt: off` ... `# fmt: on`) is
left exactly as written; code outside such regions is still formatted.

## Options

- `-d`, `--diff` — print a unified diff instead of writing the result.
- `-i`, `--in-place` — rewrite the file in place.
- `-r`, `--recursive` — recurse into directories (requires `--in-place` or `--diff`).
- `-a`, `--aggressive` — enable non-whitespace changes; repeatable for higher levels.
- `--experimental` — enable experimental (deprecated) structure-aware line shortening.
- `--select errors` — fix only these comma-separated codes (e.g. `E225` or `E1,W`).
- `--ignore errors` — do not fix these comma-separated codes (e.g. `E1`).
- `--max-line-length n` — maximum allowed line length (default `79`).
- `--line-range start end`, `--range start end` — only fix violations on lines in this inclusive,
  1-indexed range.
- `-p n`, `--pep8-passes n` — maximum number of additional passes (default: unlimited).
- `-j n`, `--jobs n` — number of parallel jobs (requires `--in-place`/`--diff`).
- `--exit-code` — return `2` when differences were found (see "Exit codes").
- `--list-fixes` — print the supported fix codes, one per line as `CODE - description`, then exit
  `0`. The descriptions for representative codes are exactly `E101 - Reindent all lines.`,
  `E225 - Fix missing whitespace around operator.`,
  `E501 - Try to make lines fit within --max-line-length characters.`, and
  `W291 - Remove trailing whitespace.`.
- `--version` — print the version and exit.
