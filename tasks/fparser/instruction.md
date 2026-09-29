# fparser — a Fortran parser in pure Python (fparser2)

Build `fparser`, a pure-Python parser for Fortran (the modern "fparser2" engine). It reads
Fortran source (fixed-form or free-form), parses it, and can reconstruct canonical Fortran
source via `str()` on the parse tree. Only the exact `str()` of the parse tree is graded.

## Dependencies

The package has **no third-party runtime dependencies** — it is pure Python (standard library
only). The environment is **offline**: everything needed is already installed, so do **not**
attempt to install anything (there is no network).

Make the package installable by a `setup.sh` that runs offline in this environment — provide a
`pyproject.toml` (or `setup.py`) so it installs with `pip install -e . --no-build-isolation`. The
build backend (`setuptools` plus `setuptools_scm` if you derive the version from VCS) is already
pre-installed. The package must also be importable as `import fparser` and expose `__version__`.

## Public API
```python
from fparser.two.parser import ParserFactory
from fparser.common.readfortran import FortranStringReader
from fparser.common.sourceinfo import FortranFormat

parser = ParserFactory().create(std="f2008")          # also "f2003"
reader = FortranStringReader(source, ignore_comments=False)
reader.set_format(FortranFormat(is_free, is_strict))  # is_free=False => fixed-form
tree = parser(reader)
str(tree)   # reconstructed, canonical Fortran source
```
- `ParserFactory().create(std=...)` returns a callable parser; calling it on a reader returns
  the top-level parse-tree node.
- `FortranStringReader(source, ignore_comments=False)` wraps a source string; the reader handles
  line continuation, comments, and fixed/free-form mechanics.
- `FortranFormat(is_free, is_strict)` selects the source form; `reader.set_format(...)` applies it.

## Scope (constructs to support)
Program units: `program`, `module` (incl. `contains`), `subroutine`, `function` (incl.
`result`), `interface` blocks. Declarations: intrinsic types with kind selectors
(`real(kind=8)`), attributes (`parameter`, `dimension(:,:)`, `allocatable`, `pointer`,
`target`, `intent(in/out)`), `character(len=*)`, multiple entities, initializers, derived
`type` definitions. Expressions: arithmetic (`+ - * /`, `**`), relational (`> < == …`),
logical (`.and. .or. .not.`), string concat (`//`), array constructors (`(/ … /)`),
subscripting; legacy star-length types (`real*8`, `character*10`). Statements: assignment,
pointer assignment (`=>`), `if`/`else if`/`else`/`end if`, arithmetic `if (e) l1, l2, l3`,
`do`, `do while`, labelled `do`, `continue`, `select case`, `where`, `write`/`format`,
`parameter (...)` statement, computed `go to (...) e`, `associate`/`end associate`,
`forall`, and the `block`/`end block` construct.

## Output (`str()`) conventions
- **Keywords are UPPERCASED** (`PROGRAM`, `INTEGER`, `DO`, `END PROGRAM`, `.AND.`), as are
  `FORMAT` edit descriptors (`1X`, `F10.2`); **user identifiers keep their source case**
  (`do10i`, a variable named `if`).
- **Indentation** is 2 spaces per nesting level (program-unit body, construct body, …);
  statement **labels** are written starting at column 0 (e.g. `10 CONTINUE`). A construct's
  intermediate/closing keyword lines (`ELSE`, `ELSE IF`, `CASE`, `CASE DEFAULT`, `END IF`,
  `END SELECT`, `END DO`, …) sit at the **same** indent as the construct's opening line, and
  the statements they contain are indented one level deeper; `CONTAINS` and the procedures
  after it sit at the host unit's body level.
- **Spacing is normalized**: a single space around binary operators and after commas; unary
  minus is also spaced (`x = - 1`); selectors render as `REAL(KIND = 8)`,
  `DIMENSION(:, :)`, `CHARACTER(LEN = *)`; array constructors as `(/1, 2, 3/)`.
- A program unit ends `END PROGRAM p` / `END MODULE m` / `END SUBROUTINE s` in free-form;
  in fixed-form a program unit ends with a bare `END`.
- A derived `type` definition's closing line **repeats the type name** — `TYPE :: point` … is
  terminated by `END TYPE point` (following the program-unit convention of echoing the name), in
  contrast to the nameless construct terminators `END IF` / `END SELECT` / `END DO` / `END BLOCK`.
- `str(tree)` returns the reconstructed source with **no trailing newline** — the whole-document
  output ends exactly at the final program-unit terminator line (`END PROGRAM p`, or a bare
  `END` in fixed-form) with no terminating `\n`.
- The output contains **no blank/empty lines** anywhere — every statement and every construct
  keyword line (including each contained procedure after `CONTAINS`) is emitted on consecutive
  lines with no vertical spacing. In particular `CONTAINS` is immediately followed by the first
  contained procedure's opening line (no blank separator line after `CONTAINS`, between contained
  procedures, or between statements).
- A few constructs have specific renderings: `PARAMETER(n = 10)` and `ASSOCIATE(a => b + c)`
  (keyword immediately followed by `(`, no space); I/O statements likewise place `(` directly
  after the keyword with no space, e.g. `WRITE(*, 100) x` and `100 FORMAT(1X, F10.2)`; a function
  result clause renders as `FUNCTION f(x) RESULT(y)` — the `RESULT` keyword is immediately
  followed by `(` with no space, like the procedure signature; a computed
  go-to is `GO TO (10, 20, 30), i` (note the comma before the selector); `FORALL (i = 1 : n) a(i) = i`;
  legacy lengths keep the star form (`REAL*8`, `CHARACTER*10`); the `block`/`end block` construct
  renders as `BLOCK` … `END BLOCK` with its body indented one level.
- **Multiple statements** separated by `;` on one source line are emitted as **separate lines**
  (e.g. `x = 1; y = 2` → `x = 1` then `y = 2`).

## Fixed-form reading & the context-sensitivity (important)
In fixed-form (`is_free=False`): columns 1–5 hold an optional statement label, **column 6**
holds a continuation marker (any non-blank/non-zero continues the previous line), code is in
columns 7–72, a `C` or `*` in **column 1** marks a comment line, and **blanks are
insignificant** inside statements. Fortran has **no reserved keywords** — *any* word (including `if`, `do`, `real`, `data`,
`format`, `write`, `call`, `type`, …) may be an ordinary variable name — so a statement's kind
is decided by its full form, not a leading word. This applies in free-form too:
- `DO 10 I = 1, 10` (a comma after the label/bounds) is a **DO loop**, but `DO10I = 1.10`
  (no comma; `.10` is a real literal) is an **assignment** to a variable `DO10I`.
- A name followed by `=` and an expression is an **assignment**, even when that name is
  otherwise a keyword (e.g. `data = 1`, `format = 1`, `call = x`, `type = read`); such a name
  may also be declared (`integer :: data`) and used in expressions like any variable.
Continued lines are joined into one logical statement before parsing.
