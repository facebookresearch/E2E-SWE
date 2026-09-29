# shfmt — a shell script formatter, in Go

Build `shfmt`, a command-line formatter for shell programs (POSIX sh, bash, and mksh), implemented
in Go. It reads a shell script, parses it, and prints it back in a canonical, deterministic style.
Output is byte-for-byte reproducible: the same input and flags always produce the same output.

Throughout, "standard shell syntax" means the grammar accepted by mainstream shells (bash for the
default/`bash` dialect, the POSIX shell command language for `posix`, mksh for `mksh`). You only need
to implement the surface described in this document; where it says "format canonically", produce
exactly the formatting specified here.

## Environment, dependencies, and build

- The implementation must be in **Go** using **only the standard library** — no third-party modules.
  The grading environment is **offline** (no network), so you cannot download anything.
- Provide a `go.mod`. The build must succeed offline with `go build` (the module cache is empty;
  there is nothing to fetch because you use only the standard library).
- Provide a `setup.sh` in the working directory that builds the program to the path **`/app/shfmt`**:

  ```sh
  go build -o /app/shfmt .
  ```

  The grader runs `setup.sh` and then invokes `/app/shfmt`. Organize your Go source however you like
  (any package layout); only the CLI behavior is graded.

## Command-line interface

```
shfmt [flags] [path ...]
```

- With no path arguments, or with a single `-` argument, the program reads the script from
  **standard input** and writes the formatted result to **standard output**.
- With a file path argument, the program reads that file, writes the formatted result to **standard
  output**, and **does not modify the file on disk** (there is no in-place write in this task).
- The formatted output always ends with exactly one trailing newline. **Empty input** produces a
  single newline (`"\n"`).

### Flags

- `-i <uint>` — indentation. `0` (the default) means **one tab per nesting level**; a value `n > 0`
  means `n` **spaces** per level.
- `-bn` — *binary next line*: when a binary operator (`|`, `&&`, `||`) spans multiple lines, start
  the continuation line with the operator (see "Line breaks" below).
- `-ci` — *case indent*: indent `case` patterns one level under the `case` keyword.
- `-sr` — *space redirects*: put a space after redirection operators (`>`, `>>`, `<`, `2>`, …).
- `-kp` — *keep padding*: preserve the script's original column alignment instead of recomputing it.
- `-fn` — *function next line*: put a function's opening `{` on its own line.
- `-mn` — *minify*: produce minimal output (strip indentation, comments, and redundant blank lines;
  collapse keyword separators). Minify **implies** simplify (`-s`).
- `-s` — *simplify*: apply the simplification rules listed below.
- `-ln <dialect>` — language dialect: `bash` (default behavior for bash syntax), `posix`, or `mksh`.
  The default when `-ln` is not given is automatic detection that accepts bash syntax.
- `-l` — *list*: do not print formatted output; instead, for each path whose current contents differ
  from the formatted result, print the path (followed by a newline) to stdout and exit with status
  `1`. If all inputs are already formatted, print nothing and exit `0`.

## Default formatting contract

Format every construct canonically:

- **Indentation** uses tabs by default, one tab per nesting level; compound statements
  (`if`/`for`/`while`/`case`/function bodies/subshells) indent their contents one further level.
- **Token spacing** is normalized to single spaces (e.g. `if  true` → `if true`,
  `((x=1+2))` → `((x = 1 + 2))`).
- **Statement separators**: `;`-separated **simple** commands are split onto separate lines
  (`a; b; c` → three lines). A `;` that separates a command from a following keyword on the same line
  is kept as `; ` (e.g. `if cond; then echo hi; fi` stays on one line). A trailing `;` at the end of
  a simple command is removed.
- **`case` clauses**: a clause's body stays on the same line as its terminator with exactly one
  space before it (`a) echo a;;` → `a) echo a ;;`). This applies to the `;;`, `;&`, and `;;&`
  terminators.
- **Blank lines**: a run of consecutive blank lines collapses to a single blank line; leading blank
  lines at the start of the file are removed.
- **Inline comments** that appear on consecutive lines are aligned to a common column — one space
  after the longest code segment in that contiguous block. (With `-kp`, the original padding is
  kept instead.)
- **Heredoc bodies** are copied verbatim — their internal whitespace is never altered.
- **Long lines are never wrapped.**
- **Subshells**: `( … )` has no inner padding (`( echo a )` → `(echo a)`). A brace group keeps its
  spacing: `{ echo b; }`.
- **Redirections** have no space after the operator by default (`echo hi >file`); `-sr` adds one.
- Quotes (single and double), parameter expansions (`${x:-default}`), here-strings (`<<<`),
  background `&`, and `\`-escaped line continuations are preserved (a continuation's next line is
  indented).
- Formatting is **idempotent**: formatting already-formatted output yields the same bytes.

### Line breaks for multiline binary operators

When a pipeline or `&&`/`||` list is written across multiple lines:

- **Default**: keep the operator at the **end** of each line, and indent continuation lines one
  level. For input
  ```
  foo |
  bar &&
  baz
  ```
  the output is `foo |`, then a tab + `bar &&`, then a tab + `baz`.
- **With `-bn`**: move the operator to the **start** of the continuation line, ending the previous
  line with a `\`. The same input becomes `foo \`, then tab + `| bar \`, then tab + `&& baz`.

## Simplify rules (`-s`, also applied by `-mn`)

Apply these source-preserving simplifications:

- Remove redundant parentheses in arithmetic: `$(( (a) ))` → `$((a))`.
- Remove `$` from variables used in arithmetic: `$(( $a + $b ))` → `$((a + b))`.
- Remove redundant quotes in test expressions: `[[ "$x" == y ]]` → `[[ $x == y ]]` — **but** keep
  quotes on the right-hand side of `==`/`!=` when removing them would change glob matching
  (`[[ $x == "a*" ]]` is left unchanged).
- Merge a negation with a unary test operator: `[[ ! -n $x ]]` → `[[ -z $x ]]`, and
  `[[ ! -z $x ]]` → `[[ -n $x ]]`.
- Use single quotes to shorten literals where possible: `"\$foo"` → `'$foo'`.

Without `-s` (or `-mn`), none of these rewrites are applied.

## Language dialects (`-ln`)

In `posix` mode, bash-only constructs are **rejected** as parse errors (see below). This includes:

- arrays — `a=(1 2)`
- process substitution — `<(…)` / `>(…)`
- parameter slicing — `${x:0:2}`
- the `function` keyword — `function f { …; }`

A plain POSIX-compatible script (e.g. `echo hi`) formats normally in every dialect. The `bash` and
`mksh` dialects accept their respective extensions (e.g. arrays format fine under `bash`). The `mksh`
dialect additionally accepts mksh-only syntax such as a coprocess (`cmd |&`), which the `bash` and
`posix` dialects reject as parse errors.

## Parse errors

If the input is not valid shell for the active dialect (incomplete compound command, unbalanced
parentheses, a dialect violation as above, etc.), the program:

- writes **nothing** to standard output,
- writes a diagnostic to **standard error** that begins with the source position in the form
  `<standard input>:<line>:<column>:` (for input read from stdin), and
- exits with status **`1`**.

You do not need to match the exact wording of the diagnostic message — only the position prefix,
the empty stdout, and the exit status are graded.
