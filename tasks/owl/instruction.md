# A parser generator for visibly-pushdown languages (`owl`)

Build a command-line tool in **C** that reads a grammar in a small custom
DSL and either (a) parses input against it on the fly (**interpreter mode**)
or (b) emits a self-contained C header that other C programs can use to
parse that language (**compilation mode**).

## A concrete example

Here's a small grammar for a toy assignment/print language:

```
program = stmt*
stmt =
    'print' expr : print
    identifier '=' expr : assign
expr =
    identifier : variable
    number : literal
  .operators infix left
    '+' : plus
    '-' : minus
```

Given this input:

```
x = 1 + 2
print x
```

`owl grammar.owl -i input.txt` (interpreter mode) prints a labeled
parse tree — the input tokens at the top, with rule and named-choice
labels (`stmt:assign`, `expr:plus`, `expr:variable`, …) stacked
underneath the tokens they matched. Running `owl grammar.owl -c`
instead emits a self-contained C header that another C program can
`#include` to parse the same language from a string or file; see
**Compilation mode** below for that API.

## Build contract

The repository's top-level `Makefile` default target MUST produce an
executable named `owl` at the repository root. Standard C toolchain only
(C11 is fine; the base image ships `gcc`, `make`, and the usual libc
headers). The build must succeed **offline** — no `pip install`, no
package downloads.

Also provide a top-level `setup.sh` that builds the project offline
(typically just runs `make`). It is invoked from the repository root
(working directory is the repo root); `setup.sh` must not rely on
`$0` / `BASH_SOURCE` and need not change directory. After it runs,
an executable `./owl` must exist at the repository root.

## Command-line interface

```
owl [options] grammar.owl
```

The grammar is normally given as a positional file argument, but you may
substitute `-g <text>` (or `--grammar <text>`) to pass the grammar
directly on the command line.

| flag              | long form           | meaning                                                                                     |
|-------------------|---------------------|---------------------------------------------------------------------------------------------|
| `-i <file>`       | `--input <file>`    | Read the input to parse from `<file>` instead of standard input.                            |
| `-o <file>`       | `--output <file>`   | Write output to `<file>` instead of standard output.                                        |
| `-c`              | `--compile`         | Compilation mode: emit a C header instead of interpreting input.                            |
| `-g <text>`       | `--grammar <text>`  | Provide the grammar text inline on the command line.                                        |
| `-p <prefix>`     | `--prefix <prefix>` | Custom prefix for generated names (see Compilation mode).                                   |
| `-V`              | `--version`         | Print the version string `owl.v4` to standard error and exit 0.                             |
| `-h`              | `--help`            | Print a usage summary to standard error and exit non-zero.                                  |

Argument errors (missing grammar, unknown option, missing required value
after a flag, an unreadable grammar file) exit **non-zero** with a
message on standard error.

## Grammar language

A grammar is a list of rules; the **first rule** in the file is the
*root rule* and is what gets matched against the input. Later rules
serve as patterns used inside the root rule or in each other. A rule
may only reference rules that appear later in the file (or itself,
but *only* inside guard brackets or as the operand of an operator
group — see below).

### Version pragma (optional)

A grammar file may begin with a line of the form

```
#using owl.v4
```

If present, this pins the grammar to a specific format version. When a
grammar is compiled with `-c` **without** a `#using` line, print a
warning on standard error (but still succeed). If the requested version
is not compatible with the tool's own version (`owl.v4`), print an error
and exit non-zero.

### Rules

A rule has the form `name = body` where a body is either a single
pattern, or one or more *named choices* optionally followed by
*operator groups*.

```
# single pattern
list = item (',' item)*

# named choices
item =
   identifier : ident
   integer    : num
   string     : text
```

Named choices produce a parse tree in which each match records *which*
choice was taken.

### Patterns

Atomic patterns match one token:

| atom              | matches                                                                                      |
|-------------------|----------------------------------------------------------------------------------------------|
| `'keyword'`       | The literal keyword text. Any character may appear; use `\'` to escape a quote.              |
| `""` or `''`      | The empty pattern — matches an empty sequence of tokens.                                     |
| `identifier`      | Letter/underscore followed by letters, digits, underscores, dashes.                          |
| `integer`         | Decimal digits, or `0x`/`0X` followed by hex digits. Value must fit in `uint64_t`.           |
| `number`          | Floating-point literal: digits, optional decimal point, optional exponent (parsed like `strtod`). |
| `string`          | Text delimited by matching `'…'` or `"…"`, with `\` escapes (`\n`, `\t`, `\r`, `\b`, `\f`, `\'`, `\"`, `\\`). |

Combined patterns:

| pattern                   | meaning                                                                                  |
|---------------------------|------------------------------------------------------------------------------------------|
| `(a)`                     | Grouping. Same as `a`.                                                                   |
| `a b`                     | Concatenation. Binds tighter than choice.                                                |
| `a?`                      | Zero or one.                                                                             |
| `a*`                      | Zero or more.                                                                            |
| `a+`                      | One or more.                                                                             |
| `a{n}`                    | Exactly `n` copies of `a`.                                                               |
| `a{n,m}`                  | Between `n` and `m` copies, inclusive.                                                   |
| `a{n+}`                   | `n` or more copies.                                                                      |
| `a{b}`                    | Zero or more `a` separated by `b` (i.e. `(a (b a)*)?`).                                  |
| `a{b, n+}`                | `n` or more `a` separated by `b`.                                                        |
| `[ 'begin' a 'end' ]`     | **Guard brackets**: `a` enclosed between literal begin/end keywords.                     |

One more combined pattern, *choice*, matches either alternative and
binds looser than concatenation:

```
a | b
```

Guard brackets are the only way to make a rule recursive in its
non-operator body.

### Rule references

Any rule name is itself a pattern. Two decorations are allowed:

| pattern         | meaning                                                                              |
|-----------------|--------------------------------------------------------------------------------------|
| `rule@field`    | Rename the reference to `field` in the resulting parse tree.                         |
| `rule\:choice`  | Exclude a named choice (or operator) of `rule` at this reference site.               |

### Operator groups

A rule with named choices may also have one or more *operator groups*.
Each group begins with `.operators` and a fixity keyword; groups
listed earlier in the rule bind more tightly than later ones.

```
expr =
   identifier : var
   number     : lit
   [ '(' expr ')' ] : parens
 .operators prefix
   '-' : neg
 .operators infix left
   '*' : mul
   '/' : div
 .operators infix left
   '+' : add
   '-' : sub
```

Fixity keywords:

| fixity                 | shape                                                                          |
|------------------------|--------------------------------------------------------------------------------|
| `prefix`               | `op* next`                                                                     |
| `postfix`              | `next op*`                                                                     |
| `infix left`           | `next (op next)*`, resulting tree is left-associative.                         |
| `infix right`          | `next (op next)*`, resulting tree is right-associative.                        |
| `infix flat`           | `next (op next)*`, resulting tree has all operands as siblings under one node. |
| `infix nonassoc`       | `next op next` — exactly one operator; two in a row is an error.               |

For an infix operator, the emitted rule struct carries two extra fields
`.left` and `.right` (both `owl_ref`) for the two operands; for a prefix
or postfix operator, a single `.operand` field is emitted.

### Directives

| directive                          | meaning                                                                                  |
|------------------------------------|------------------------------------------------------------------------------------------|
| `.token name 'ex1' 'ex2' …`        | Declare a user-defined token type (matched by callback in compilation mode).             |
| `.line-comment-token 'prefix'`     | Text from this prefix through end-of-line is treated as whitespace.                      |
| `.whitespace 'ws1' 'ws2' …`        | Explicit whitespace list; overrides the built-in defaults. Empty list disables whitespace entirely. |

The default whitespace characters are space, tab, carriage return, and
newline. The default line comment is `#` in the grammar file only (the
input parsed by the grammar has no comment default).

### Tokens vs. keywords

The tokenizer picks the **longest match** at each position; ties between
a keyword and a built-in token (identifier/number/etc.) go to the
keyword. If both `integer` and `number` can match the same input,
`integer` is preferred.

## Interpreter mode

Default when `-c` is not given. Reads the grammar, reads the input from
standard input (or `-i <file>`), and prints a visual representation of
the parse tree to standard output (or `-o <file>`).

The output shape is: the input text at the top, with rule/choice/operator
labels stacked below covering the tokens they matched. The exact layout
(column widths, punctuation) is a visual detail. What matters:

- The tokens appear in the output.
- Each named choice or operator that matched appears as a label of the
  form `rule:choice-name` in the tree region below the tokens.
- Rules that matched (regardless of whether they have named choices) also
  appear as bare labels in the tree region under the tokens they cover.
- Repetitions produce one label per iteration.
- On success, exit 0.

If the input does not match the grammar, print an error on standard
error and exit non-zero. If the grammar itself is **ambiguous** (i.e.
some input can be parsed in more than one way), Owl detects this and
exits with **status 3**, printing a message including the substring
`ambiguous` on standard error.

Recognized error categories (the error text should identify the offending
token/range or otherwise describe the failure; exact wording is not
pinned down):

| situation                                                | exit    |
|----------------------------------------------------------|---------|
| input can't be tokenized (invalid char / unknown token)  | ≠ 0     |
| tokenized OK but out-of-place token for the grammar      | ≠ 0     |
| input ends in the middle of a valid prefix (incomplete)  | ≠ 0     |
| grammar itself is ambiguous                              | **3**   |
| grammar uses a C reserved keyword as a rule/token name   | ≠ 0     |
| `#using owl.vN` where `N` is not compatible              | ≠ 0     |
| grammar file can't be opened / grammar text malformed    | ≠ 0     |

The grammar-validity checks in this table — C reserved keyword,
incompatible `#using`, ambiguous grammar, malformed grammar text — are
properties of the grammar itself and fire in both **interpreter** mode
(the default) and **compilation** mode (`-c`).

## Compilation mode

With `-c`, `owl` does **not** parse any input. Instead, it emits a
self-contained C header on standard output (or into `-o <file>`) that a
user's C program can `#include` to parse the same language later.

The header is in "single-file library" style: it declares the API in an
always-included section, and the implementation is guarded by
`OWL_PARSER_IMPLEMENTATION` (or `<PREFIX>_PARSER_IMPLEMENTATION`
under `-p`). The user's C program does

```c
#define OWL_PARSER_IMPLEMENTATION
#include "parser.h"
```

in exactly one translation unit and just `#include "parser.h"` in any
others. The header must be self-sufficient once included — the user's
compilation should not need any other file from your generator (only
the C standard library).

### Generated API — universal

For a grammar whose root rule is `ROOT`, the header defines (using
default `owl_` / `parsed_` names; substitute the `-p` prefix if
supplied):

```c
struct owl_tree;

/* Construction */
struct owl_tree *owl_tree_create_from_string(const char *nul_terminated);
struct owl_tree *owl_tree_create_from_file(FILE *file);

struct owl_tree_options {
    const char *string;   /* set exactly one of string / file */
    FILE       *file;
    /* + tokenize callback fields when the grammar has .token declarations
       (described below) */
};
struct owl_tree *owl_tree_create_with_options(struct owl_tree_options opts);

void owl_tree_destroy(struct owl_tree *tree);   /* NULL is a no-op */
void owl_tree_print  (struct owl_tree *tree);   /* prints the same visual tree */

/* Error inspection */
enum owl_error {
    ERROR_NONE,
    ERROR_INVALID_FILE,
    ERROR_INVALID_OPTIONS,
    ERROR_INVALID_TOKEN,
    ERROR_UNEXPECTED_TOKEN,
    ERROR_MORE_INPUT_NEEDED,
    ERROR_ALLOCATION_FAILURE,
};
struct source_range { size_t start; size_t end; };
enum owl_error owl_tree_get_error(struct owl_tree *tree, struct source_range *out_range);

/* Ref traversal */
struct owl_ref {
    struct owl_tree *_tree;
    size_t           _offset;
    uint32_t         _type;
    bool             empty;
};
struct owl_ref owl_next(struct owl_ref);
bool           owl_refs_equal(struct owl_ref a, struct owl_ref b);
struct owl_ref owl_tree_root_ref(struct owl_tree *tree);

/* Convenience: unpack the root as its typed struct */
struct parsed_ROOT owl_tree_get_parsed_ROOT(struct owl_tree *tree);
```

The struct fields whose names begin with `_` are implementation-internal
but the *layout* of `owl_ref` (four fields, `empty` last, and in
particular the fact that `empty` is a bool the caller reads) is part
of the contract — callers depend on `.empty` being observable.

If a create-function fails (bad file, bad options, or a parse error),
it still returns a non-NULL `owl_tree *` — an **error tree**. The
caller detects this by calling `owl_tree_get_error`.

For `ERROR_INVALID_TOKEN` / `ERROR_UNEXPECTED_TOKEN` /
`ERROR_MORE_INPUT_NEEDED`, the `out_range` (if non-NULL) is filled with
byte offsets into the input string; for the other errors it is
untouched. For `ERROR_INVALID_TOKEN`, `out_range` begins at the offset
of the first unrecognized byte in the input; its length spans the
offending token.

### Generated API — per rule

For each rule `RULE` in the grammar (root or not), the header defines:

```c
struct parsed_RULE {
    struct source_range range;
    /* one owl_ref field per child rule / built-in token referenced
       by the rule's body, named after the child (or after its @rename).
       An enum parsed_type field named `type` is included iff the
       rule has named choices or operator groups. */
};
struct parsed_RULE parsed_RULE_get(struct owl_ref ref);
```

If a rule references the same built-in token or child rule multiple times
without `@rename`, all matches share a single field, iterable via
`owl_next`.

For built-in tokens actually used in the grammar, the corresponding
unpacker is emitted:

```c
struct parsed_identifier { struct source_range range; const char *identifier; size_t length; };
struct parsed_integer    { struct source_range range; uint64_t integer; };
struct parsed_number     { struct source_range range; double   number;  };
struct parsed_string     { struct source_range range; const char *string; size_t length; };

struct parsed_identifier parsed_identifier_get(struct owl_ref);
struct parsed_integer    parsed_integer_get   (struct owl_ref);
struct parsed_number     parsed_number_get    (struct owl_ref);
struct parsed_string     parsed_string_get    (struct owl_ref);
```

`parsed_string.string` and `.length` describe the string's *content* —
the surrounding `'…'`/`"…"` quotes are stripped and escape sequences
(`\n`, `\t`, `\'`, `\"`, `\\`, `\r`, `\b`, `\f`) are decoded. `.length`
excludes the quotes. The lifetime of `.string` is tied to the
`owl_tree`; do not use it after `owl_tree_destroy`.

If the grammar has any named choices or operator groups, a **single**
enum is emitted collecting all their names, one enumerator per choice,
in `UPPER_SNAKE_CASE`, prefixed with `PARSED_` (or `<PREFIX>_` under
`-p`). The first enumerator has value `1` (0 is reserved); the rest
follow in an unspecified but stable order. Each choice-name maps to a
distinct positive value. A `parsed_RULE.type` field of this enum type
indicates which choice matched.

Fields corresponding to references that couldn't have matched for the
chosen `type` have `.empty == true`.

### Iterating children

A single grammar reference can match multiple times (via `*`, `+`,
`{n}`, delimiter lists…). The parse tree exposes each such match as a
linked chain: the struct field is the *first* ref; `owl_next(ref)`
returns the next one; iteration ends when `ref.empty` is true.

### `-p <prefix>` — custom prefix

`owl -c -p asdf grammar.owl -o parser.h` emits the same header but with
every top-level identifier `owl_`/`parsed_`/`OWL_` renamed to
`asdf_`/`asdf_`/`ASDF_` respectively. For example:

* `struct owl_tree` → `struct asdf_tree`
* `owl_tree_create_from_string` → `asdf_tree_create_from_string`
* `parsed_expr` → `asdf_expr`
* `PARSED_ADD` → `ASDF_ADD`
* `OWL_PARSER_IMPLEMENTATION` → `ASDF_PARSER_IMPLEMENTATION`

The substitution applies to **every** occurrence of one of these tokens
inside a generated name, not only a leading one, so a name that embeds
two of them is renamed at both positions.

The tokens and rule names inside the grammar are not affected — only
the tool's own names in the generated code.

### User-defined tokens (`.token`)

If the grammar declares any `.token` types, `owl_tree_options` gains
two extra fields:

```c
typedef struct owl_token (*owl_token_func_t)(const char *string, void *info);
struct owl_tree_options {
    /* … string / file … */
    owl_token_func_t tokenize;
    void            *tokenize_info;
};

struct owl_token {
    enum owl_token_type type;   /* per-token-type enum, see below */
    size_t length;
    union { uint64_t integer; double real; void *pointer; } data;
};

/* A zero-initialized owl_token value the callback can return to signal
   "no match". Any return whose .length == 0 also counts as no match. */
static struct owl_token owl_token_no_match;
```

The callback is invoked at each tokenization step with the remaining
input (NUL-terminated) and the caller's `tokenize_info`. A match of
length 0 means "no match"; a match of `length > 0` is accepted, with
whatever payload the callback stashed in `data`.

The enum `owl_token_type` contains an `OWL_TOKEN_<NAME>` value for each
`.token NAME` declared in the grammar (uppercased with `-` → `_`) plus
the sentinel `OWL_WHITESPACE`. If the callback returns a token whose
type is `OWL_WHITESPACE`, that span is treated as whitespace.

For each `.token NAME`, the generated header also emits a
`struct parsed_<NAME>` containing `range` and the same `data` union;
`parsed_<NAME>_get` unpacks it.

## Determinism

Invoking `owl` with identical inputs (same grammar text, same input, same
flags) MUST produce byte-for-byte identical output on every run — this
applies both to interpreter mode's stdout/stderr and to compilation
mode's emitted header. In particular, no timestamps, no PIDs, no random
names, no hash-order-dependent enum values.
