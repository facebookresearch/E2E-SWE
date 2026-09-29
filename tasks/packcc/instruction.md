# PackCC

Build **PackCC**, a parser generator for C. PackCC reads a grammar written
in a **PEG** (Parsing Expression Grammar — a top-down parsing formalism
similar to regular expressions, where alternation is ordered and there is no
separate tokenisation step) and emits a **packrat** parser (recursive
descent with memoisation, giving linear-time parsing of any PEG). Unlike
common packrat parsers, PackCC additionally supports direct and indirect
**left-recursive** rules using the Warth / Douglass / Millstein algorithm.

The whole tool is a **single, self-contained C source file** (`src/packcc.c`)
that compiles with strict C90 and depends only on the C standard library.
The generated parser it emits is likewise a single `.c`/`.h` pair with no
external dependencies. Alongside the source tree ships an `import/`
directory of reusable grammar fragments (character-class rules, EOL / TAB
helpers, an AST-builder module) that user grammars can pull in with the
`%import` directive.

Example use:

```sh
# Compile the parser generator itself.
cc -o packcc src/packcc.c

# Turn a PEG grammar into a parser source pair.
./packcc example.peg          # -> example.c, example.h
./packcc -o parser example.peg # -> parser.c,  parser.h
```

A generated parser is used by a driver that includes the generated code and
loops over `pcc_parse(ctx, &ret)` until it returns 0:

```c
#include "parser.h"
#include "parser.c"

int main(void) {
    int ret;
    pcc_context_t *ctx = pcc_create(NULL);
    while (pcc_parse(ctx, &ret));
    pcc_destroy(ctx);
    return 0;
}
```

A complete end-to-end example — a line-numbering parser:

```
# echo.peg — prefix each stdin line with its 1-based line number.
%source {
    static int lineno = 0;
}

top  <- line* !.
line <- <[^\r\n]*> '\r'? '\n' { lineno++; printf("%d: %s\n", lineno, $1); }
```

```c
// main.c — driver.
#include <stdio.h>
#include "parser.h"
#include "parser.c"

int main(void) {
    int ret;
    pcc_context_t *ctx = pcc_create(NULL);
    while (pcc_parse(ctx, &ret));
    pcc_destroy(ctx);
    return 0;
}
```

```sh
./packcc -o parser echo.peg    # -> parser.c, parser.h
cc -o echo main.c              # main.c #includes parser.[hc]
printf 'alpha\nbeta\ngamma\n' | ./echo
# 1: alpha
# 2: beta
# 3: gamma
```

## 1. Dependencies and build contract

* A C compiler (`gcc` on Linux). The generator source itself must compile
  under strict C90 (`-std=c90 -pedantic`); the generated parser is portable
  C that also compiles under C99.
* Standard C library only. No external third-party libraries at build or
  runtime.

### 1.1 Install contract

After `./setup.sh` completes, invoking the generator from any working
directory must:

* Provide `packcc` as an executable on `PATH` — reachable simply as
  `packcc`, without a directory prefix.
* Resolve `%import "char/…"`, `%import "util/…"`, and `%import "code/…"`
  references against a system default directory with no `-I` flag or
  `PCC_IMPORT_PATH` env-var required. The recognised system default is
  **`/usr/share/packcc/import`** (Linux); the bundled `import/` tree
  should be installed under that path preserving its layout, so that
  `%import "char/ascii_character_group.peg"` opens
  `/usr/share/packcc/import/char/ascii_character_group.peg`, etc.

`setup.sh` runs offline (`PIP_NO_INDEX=1`; no network); `apt-get install`
and `pip install` inside it will fail.

## 2. Command-line interface

```
packcc [OPTIONS] [FILE]
```

If no `FILE` is given, the PEG source is read from standard input and the
output base name is `-` (i.e. writing `-.c` and `-.h`). Otherwise the input
is the given file and the output base name is the input's stem (i.e.
`packcc grammar.peg` writes `grammar.c` and `grammar.h` in the current
directory).

Options:

| Option | Effect |
|---|---|
| `-I DIRNAME` | Add DIRNAME to the `%import` search path. May be given multiple times; searched in the order given, ahead of `PCC_IMPORT_PATH`, the per-user default (`~/.packcc/import`), and the system default. |
| `-o BASENAME` | Override the output base name. Writes `BASENAME.c` and `BASENAME.h`. May be given at most once. |
| `-a`, `--ascii` | Disable UTF-8 support in the emitted parser. Character-class ranges over UTF-8 codepoints are still parsed by PackCC itself, but the generated parser reads input byte-by-byte and does not emit any UTF-8 codepoint-decoding helper. |
| `-l`, `--lines` | Emit `#line N "input.peg"` directives in the generated `.c`/`.h` so that C-compiler diagnostics on embedded user code point back at the PEG source. |
| `-d`, `--debug` | Emit debug-build `#include`s / boilerplate friendly for debug builds. This flag does NOT gate the debug hook: the generated parser ALWAYS contains `PCC_DEBUG(auxil, event, rule, level, pos, buffer, length)` call sites on rule evaluate / match / no-match events (a no-op by default). A real hook is activated purely by `#define`-ing `PCC_DEBUG` yourself, independently of this flag (see §5.1 below). |
| `-h`, `--help` | Print a usage message and exit. |
| `-v`, `--version` | Print the version and exit. |

Invalid flags, ambiguous long-option prefixes, and unresolvable input files
produce a non-zero exit code. A grammar that fails to parse or that
references undefined rules likewise exits non-zero.

## 3. PEG grammar

A grammar file is a sequence of rule definitions:

```
rulename <- pattern
```

followed optionally by a `%%` marker after which arbitrary C source code
may be appended (that code is copied to the generated `.c` file, after the
generated parser implementation). Comments start with `#` and run to end of
line.

The **first** rule defined in the grammar file is the top-level (start) rule
— the one `pcc_parse` evaluates on each call (see §5). Imported rules and
rules defined later are only reached when the start rule (transitively)
references them.

Rule and rule-variable identifiers consist of alphabetics, digits and
underscores; they must start with an alphabetic or underscore; rule
variables additionally must not start with `pcc_` or `PCC_` and must not
be C reserved words.

### 3.1 Pattern elements

The following elements can appear in a pattern.

**Rule reference and rule variables**

```
foo             invokes the pattern in rule `foo`
name:foo        invokes `foo` and binds `foo`'s $$ (§4) into local `name`
```

**Alternation and sequencing**

```
a b c           sequence: match a, then b, then c
a / b / c       ordered choice: try a first, then b, then c; commit to the
                first that succeeds (subsequent alternatives are NOT tried)
```

Sequencing binds tighter than `/`; `foo bar / baz` means `(foo bar) / baz`.

**Literals and character classes**

```
'foo'   "bar"             match the exact string (ANSI C escapes recognised;
                           UNICODE escapes `\uXXXX` incl. surrogate pairs
                           recognised unless `--ascii` is set)
[abc]                     match any one of the listed characters
[^abc]                    match any one character NOT in the list
[a-zA-Z0-9_]              character ranges are inclusive
.                         match any single character (fails only at EOF)
^                         match the beginning of the input (position 0)
```

Escape sequences inside strings and classes: the usual C set (`\n`, `\r`,
`\t`, `\\`, `\'`, `\"`, `\0`, `\xNN`, `\uNNNN` and paired UTF-16 surrogates).

**Quantifiers, predicates, grouping, captures**

```
e ?             optional: match e once or zero times, always succeeds
e *             zero or more matches of e
e +             one or more matches of e
& e             positive lookahead: succeed iff e matches; do NOT consume
! e             negative lookahead: succeed iff e fails;   do NOT consume
( e )           group (adjusts precedence)
< e >           capture-group: matches e and remembers the matched text
                (numbered in evaluation order; referenced as $1, $2, …)
$N              back-reference: match the exact text captured by group N
```

Capture groups are numbered by the left-to-right position of their opening
`<` across the whole rule, spanning every ordered-choice alternative and
nested group: a `< … >` whose `<` appears earlier in the rule text gets the
lower index (so in `< a < b > >` the outer group is `$1` and the inner is
`$2`), and the second `< … >` in a rule is `$2` even when it lies in a
different `/` alternative. A group belonging to an alternative not taken at
run time keeps its static index and reads as the empty string.

The idiom `!.` (negative lookahead over any character) matches the end of
the input.

### 3.2 Actions and error actions

**`{ ... }`** — action

C source code enclosed in braces. Bound to a successful match of the
enclosing rule; actual firing time is subject to the thunk semantics
described below. May appear anywhere between elements (or at the
start/end of a rule) and may occur multiple times.

Actions are queued as thunks tied to the currently-attempted parse tree.
If the enclosing sequence or alternative later fails and the parser
backtracks, the queued action is discarded, not executed. Only actions
belonging to the ultimately-committed parse tree fire, and they fire at
the end of the top-level `pcc_parse` call, in match order.

Inside an action the following identifiers are predefined:

| Name | Meaning |
|---|---|
| `$$` | Output value slot for this rule. Type set by `%value` (default `int`). |
| `auxil` | The user-defined context data passed to `pcc_create`. Type set by `%auxil` (default `void *`). |
| _name_ | The value of a rule variable `name:rulename` used earlier in the pattern. Zero-cleared if the referenced rule was not actually evaluated. |
| `$N` (positive integer) | The text (`const char *`) captured by the N-th `< … >` group. |
| `$Ns` | 0-based start position of the N-th capture (`size_t`). |
| `$Ne` | 0-based end position of the N-th capture (`size_t`). |
| `$0` | The text spanning from where the rule pattern started matching up to the position just before this action. |
| `$0s` | Start position of the rule attempt. |
| `$0e` | Position just before this action. |
| `@`_var_ | Value of a marker variable (see §3.4); read-only in actions. |

Queuing a thunk records the marker variables along with it: the action
reads each marker's integer and string slot as they stood at the point in
the parse where the action was queued, not the marker's live value at
flush time (programmable predicates, which run during the match itself,
read and write the live state).

Capture strings (`$N`, `$0`) are freed immediately after the action
returns; copy anything you need to persist into `$$` or `auxil`.

**`e ~{ ... }`** — error action

An error action associated with the immediately preceding element `e`.
The block runs immediately when `e` fails to match — error actions fire
during backtracking and are NOT deferred as thunks (unlike regular
actions). The predefined identifiers are the same as for a regular
action. `~` binds less tightly than every other operator except `/` and
sequencing.

### 3.3 Programmable predicates

**`&{ ... }`** — programmable predicate

C source code that must set the output variable `@@` (an `int`) to a
non-zero value for the match to proceed. Initial value of `@@` is 1. No
input is consumed. All marker updates made inside a `&{ }` are rolled back
if the surrounding match ultimately fails.

**`!{ ... }`** — negative programmable predicate

Same as `&{ }` but the match proceeds only when `@@` is set to 0. Initial
value of `@@` is 0.

Inside a programmable predicate, `$N`, `$Ns`, `$Ne`, `$0`, `$0s`, `$0e`,
`auxil`, and `@`_var_ are available; `@`_var_ is writable (unlike in
actions, which see markers read-only). Rule variables and `$$` are NOT
accessible in predicates.

The predicate must be a pure function of the visible captures + marker
state: given the same values of `$N`/`$Ns`/`$Ne` and marker variables it
must always return the same `@@` and produce the same marker updates.
Violating this may make the generated parser behave incorrectly.

### 3.4 Marker variables — `%marker @name1 @name2 …`

Declares one or more marker variables. Marker names follow the same
identifier rules as rule variables. Markers have TWO independent slots per
variable:

* an integer slot (`ptrdiff_t`, initially 0), used as `@name` — increment,
  decrement, compare, sum, etc.;
* a string slot (`const char *`, initially NULL), used via the methods
  `@name.set_string(s)`, `@name.get_string()`, and `@name.append_string(s)`.

Both slots persist across `pcc_parse` calls on the same context. Marker
values save/restore the two slots together onto a per-marker stack:

```
@name.save()      // push current (integer, string) onto @name's stack
@name.restore()   // pop  (integer, string) back off @name's stack
```

When `@name` appears as a pattern element (e.g. `body <- @name`), it
matches the current string-slot text at the input position (used to gate
matching on a previously captured string; the balanced-quote idiom in
§3.5 uses this).

Marker variables are read-only inside actions (§3.2 says which value an
action observes); writable inside programmable predicates; not accessible
elsewhere. `%marker` may appear multiple times in a source file, including
from within imported files.

### 3.5 Idioms

**Balanced quoted string with matching delimiter**

```
%marker @quote

string <- start body end
start  <- < "'''" / '"""' / "'" / '"' > &{ @quote.set_string($1); }
body   <- ( !@quote . )*
end    <- @quote
```

Matches `'foo'`, `"bar"`, `'''baz'''`, `"""qux"""`; the closing delimiter
is forced by the marker to equal the opening one.

**Length-gated match with marker counter**

```
%marker @count

hashes <- &{ @count = 0; } ( '#' &{ @count++; } )+
          &{ @@ = (@count >= 5 && @count <= 10); }
```

Matches only sequences of 5 to 10 `#` characters.

## 4. Directives

Directives configure how the parser is generated. Every directive begins
with `%` in the first column.

### 4.1 Emitted C code — `%header`, `%source`, `%common`, `%early*`

* **`%header { … }`** — code copied verbatim into the generated `.h` file,
  before the parser API declarations.
* **`%source { … }`** — code copied verbatim into the generated `.c` file,
  before the parser implementation code.
* **`%common { … }`** — code copied into BOTH the `.h` and the `.c`.
* **`%earlyheader { … }`**, **`%earlysource { … }`**, **`%earlycommon { … }`**
  — same as above, but the code is placed at the very BEGINNING of the
  output file, before any code or `#include`s generated by PackCC itself.
  Useful e.g. for defining feature-test macros (`_POSIX_C_SOURCE`) or
  overriding standard-library behaviour before headers are pulled in.

Each of these may appear multiple times; blocks are emitted in source
order. Braces inside the block must nest properly, but braces inside
strings, comments, and directive lines are ignored for nesting.

Intrinsic-macro substitutions (§4.5) fire inside these blocks — including
inside `/* */` comments and inside string literals.

### 4.2 API customisation — `%prefix`, `%value`, `%auxil`

* **`%prefix "name"`** — rename the API from `pcc_*` to `name_*`. Also
  renames every internal `pcc_` symbol, and the emitted type
  `pcc_context_t` becomes `name_context_t`. May appear at most once.
  Cannot be used from imported files.
* **`%value "T"`** — change the return-value type (i.e. the type of `$$`
  and the second argument of `pcc_parse`) from the default `int` to `T`.
  May appear at most once.
* **`%auxil "T"`** — change the user-data type (i.e. the type of `auxil`
  and the first argument of `pcc_create`) from the default `void *` to
  `T`. May appear at most once.

### 4.3 Version & requirements — `%version`, `%requires`

* **`%version X.Y.Z`** — declare the version of the PEG source file (X,
  Y, Z are non-negative integers without leading zeros). Defaults to
  `0.0.0`. Available inside actions/predicates/directives as
  `${version}`.
* **`%requires packcc OP VER [, OP VER …]`** — restrict which PackCC
  versions may generate a parser from this grammar. `OP` is one of
  `==`, `!=`, `<=`, `>=`, `<`, `>`; multiple constraints join with `,`
  meaning AND. If any constraint fails, generation aborts with an error.

### 4.4 Import — `%import "file" [OP VER …]`

Splice the contents of another PEG file at this point. Directives, rules,
markers, and appended C code (after `%%`) all apply as if the file's
contents were inlined. Optional trailing version constraints (using the
same syntax as `%requires`) restrict which versions of the imported file
are acceptable.

Search order for a relative import path:

1. the directory of the importing file (for the top-level file, the
   current directory);
2. `-I` directories in command-line order;
3. `PCC_IMPORT_PATH` env-var directories (colon-separated on Unix);
4. the per-user default `~/.packcc/import`;
5. the system default `/usr/share/packcc/import`.

The same file is silently skipped on any subsequent `%import` of it.

`%import` may appear multiple times and may itself appear inside imported
files.

### 4.5 Intrinsic macros

Inside any `%header` / `%source` / `%common` / `%early*` block, any action,
error action, or programmable predicate — including inside `/* */`
comments and inside `"…"` / `'…'` string literals — the following
macro-like tokens are substituted:

| Macro | Expansion |
|---|---|
| `${prefix}` | the `%prefix` value (lowercase) |
| `${PREFIX}` | the `%prefix` value uppercased |
| `${version}` | the current file's `%version`, X.Y.Z string |
| `${packcc.version}` | the version of PackCC itself, X.Y.Z |
| `${packcc.option.ascii}` | `"1"` if `--ascii` was passed, `"0"` otherwise |
| `${packcc.option.lines}` | `"1"` if `--lines` was passed, `"0"` otherwise |

`\$` and `\@` escape the macro / marker syntax back to a literal `$` / `@`.

### 4.6 Trailing code — `%%`

Everything after a line consisting of `%%` is copied verbatim to the
generated `.c` file, after the parser implementation. Intrinsic-macro
substitution still applies here.

## 5. Parser runtime

The generated parser exposes three functions with the default `pcc` prefix
(replace `pcc` by the value of `%prefix` if set):

```c
pcc_context_t *pcc_create (auxil_t auxil);            /* auxil_t = void * by default */
int            pcc_parse  (pcc_context_t *ctx, ret_t *ret);  /* ret_t = int by default */
void           pcc_destroy(pcc_context_t *ctx);
```

Semantics:

* **`pcc_create(auxil)`** allocates a fresh parser context and binds the
  user-supplied `auxil` to it (available in actions/predicates/macros).
* **`pcc_parse(ctx, ret)`** parses one top-level match of the grammar's
  first (start) rule, writing the result value into `*ret`. Returns non-zero while more input
  remains to parse; returns 0 when the input is exhausted. The check for
  remaining input is made before the start rule is evaluated: when the input
  is already exhausted, `pcc_parse` returns 0 immediately without evaluating
  the start rule again, so that terminating call fires no actions and emits
  no `PCC_DEBUG` events. `ret` may be
  `NULL` if the caller does not need the output value.
* **`pcc_destroy(ctx)`** releases the context and all resources it owns.

Typical driver:

```c
int ret;
pcc_context_t *ctx = pcc_create(NULL);
while (pcc_parse(ctx, &ret));
pcc_destroy(ctx);
```

### 5.1 Runtime customisation macros

A user may `#define` any of the following BEFORE the generated parser
implementation is compiled — the natural place is inside a `%source { … }`
block. Each has a documented default.

* **`PCC_GETCHAR(auxil)`** — return the next input character as an `int`
  (0-255), or `-1` on end of input. Default: `getchar()` (reads stdin).
* **`PCC_ERROR(auxil)`** — invoked on a syntax error. May abort the
  program or return normally. Default: `fprintf(stderr, "Syntax
  error\n"); exit(1);`.
* **`PCC_MALLOC(auxil, size)`** — allocate `size` bytes and return a
  pointer or `NULL`. Default: `malloc(size)` with an out-of-memory abort.
* **`PCC_REALLOC(auxil, ptr, size)`** — reallocate. Default: `realloc`
  with an out-of-memory abort.
* **`PCC_FREE(auxil, ptr)`** — free. Default: `free(ptr)`.
* **`PCC_DEBUG(auxil, event, rule, level, pos, buffer, length)`** —
  debug hook. Called on rule evaluate, rule match, and rule no-match
  events. Arguments:
  * `event` — an integer identifying the event. The three defined
    events are:
    * `PCC_DBG_EVALUATE = 0` — parser is about to evaluate `rule`;
    * `PCC_DBG_MATCH    = 1` — `rule` matched; `buffer` / `length` hold
      the matched text;
    * `PCC_DBG_NOMATCH  = 2` — `rule` did NOT match at the current
      position.
  * `rule` — the name of the rule (`const char *`).
  * `level` — nesting depth (non-negative `int`).
  * `pos` — 0-based byte offset from the start of the current context
    (`size_t`).
  * `buffer` — a `const char *` into the internal input buffer;
    `length` bytes are valid.

  Default: no-op (`((void)0)`). Enabling this macro is orthogonal to the
  `--debug` CLI flag: the flag only asks the generator to emit `#include`
  and boilerplate friendly for debug builds — supplying a real
  implementation is done by `#define`-ing `PCC_DEBUG` yourself.
* **`PCC_BUFFERSIZE`** — initial text-buffer size (`size_t`). Default 256.
* **`PCC_ARRAYSIZE`** — initial size of internal dynamic arrays other
  than the text buffer. Default 2.

## 6. Bundled `%import` fragments

The `import/` tree ships alongside the source and is installed at the
system default import path (see §1.1). User grammars may pull in these
fragments with `%import`.

### 6.1 `char/ascii_character_group.peg`

Defines named rules for common ASCII character groupings, notably
`ASCII_C_alnum`, `ASCII_C_alpha`, `ASCII_C_blank`, `ASCII_C_cntrl`,
`ASCII_C_digit`, `ASCII_C_graph`, `ASCII_C_lower`, `ASCII_C_print`,
`ASCII_C_punct`, `ASCII_C_space`, `ASCII_C_upper`, `ASCII_C_xdigit`, and
the higher-level `ASCII_Printable_Character` / `ASCII_Letter` /
`ASCII_Uppercase_Letter` / `ASCII_Lowercase_Letter` /
`ASCII_Number` / `ASCII_Special_Character` /
`ASCII_Control_Character`.

### 6.2 `char/unicode_general_category.peg`, `char/unicode_derived_core.peg`

Provide rules for matching characters in specific Unicode general
categories and derived core properties (per UAX #44). Only meaningful
when UTF-8 mode is enabled (i.e. `--ascii` is NOT passed).

### 6.3 `util/eol.peg`

Exports:

```
EOL  <- ( '\r\n' / '\n' / '\r' ) &{ @eol_lineno++; @eol_col_base = $0e; }
EOF  <- !.
```

Declares markers `@eol_lineno` and `@eol_col_base` so importers can query
current line / column info from actions.

### 6.4 `util/tab.peg`

Exports a `TAB` rule that treats `' '` and `'\t'` uniformly, expanding tabs
to the next multiple of `${PREFIX}_TAB_SIZE` (a user-configurable macro,
default 8) and tracking column in the `@tab_col` marker.

### 6.5 `code/pcc_ast.v3.peg`

Provides AST-building scaffolding. When a user grammar sets

```
%value "PREFIX_ast_node_t *"
%auxil "PREFIX_ast_manager_t *"
%prefix "PREFIX"
%import "code/pcc_ast.v3.peg"
```

the import contributes:

* type `PREFIX_ast_node_t` — a node with an arity, a child array, and a
  `custom` field of type `PREFIX_ast_node_custom_data_t` (which the user
  defines by first `#define`-ing `PREFIX_AST_NODE_CUSTOM_DATA_DEFINED`
  and then typedef-ing the struct in `%header`);
* type `PREFIX_ast_manager_t` — a container that owns every allocated
  node;
* constructors `PREFIX_ast_node__create_0()`,
  `PREFIX_ast_node__create_1(child)`,
  `PREFIX_ast_node__create_2(child_l, child_r)`, and a variadic form;
* accessors `PREFIX_ast_node__get_child_count(node)` and
  `PREFIX_ast_node__get_child_const_array(node)`;
* lifecycle `PREFIX_ast_manager__initialize(&mgr)`,
  `PREFIX_ast_manager__finalize(&mgr)`,
  `PREFIX_ast_node__destroy(&mgr, node)`.

When the user enables custom node data (`#define
PREFIX_AST_NODE_CUSTOM_DATA_DEFINED`), the user must also implement
`PREFIX_ast_node_custom_data__initialize(&mgr, obj)` and
`PREFIX_ast_node_custom_data__finalize(&mgr, obj)` (typically after `%%`).

### 6.6 `code/pcc_ast.peg`

A legacy variant of the AST scaffolding; users writing new code should
prefer `pcc_ast.v3.peg`.

## 7. Left recursion

Rules of the form `foo <- foo op x / y` (direct left recursion) and of
the form `foo <- bar ; bar <- foo …` (indirect left recursion) MUST be
supported without exponential blow-up, using memoisation of intermediate
results at each input position. The canonical shape:

```
term <- l:term _ '+' _ r:factor { $$ = l + r; }
      / l:term _ '-' _ r:factor { $$ = l - r; }
      / e:factor                { $$ = e; }
```

Must parse `1-2-3` as `(1-2)-3 = -4`, not as `1-(2-3) = 2`.

## 8. Error handling and exit codes

* `packcc` exits 0 on successful generation.
* Any error — unknown option, ambiguous long option, extra input file,
  missing option argument, unresolvable input path, unresolvable
  `%import`, malformed grammar, undefined rule reference, version
  constraint failure — exits with a non-zero code and prints a diagnostic
  to stderr.
* The generated parser's `pcc_parse` returns 0 when input is exhausted
  and non-zero otherwise. Syntax errors during parsing invoke
  `PCC_ERROR(auxil)` — the default implementation exits the process.

Anything not covered above is unspecified.
