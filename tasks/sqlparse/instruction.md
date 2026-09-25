# sqlparse

Build `sqlparse`, a **non-validating SQL parser** for Python. It splits SQL text into
statements, tokenizes and *groups* each statement into a navigable parse tree, and
re-emits ("formats") SQL according to a set of options. It never validates or executes
SQL — it accepts any input, preserves it faithfully, and degrades gracefully on
malformed input.

Organize the internals however you like as long as the import paths, the object model,
the formatting behavior, and the `sqlformat` command-line interface described here are
reproduced exactly.

## Dependencies

- **No third-party runtime dependencies** — use only the Python standard library.
- The package must install offline with `pip install -e . --no-build-isolation` (a
  `pyproject.toml` / `setup.py` and a build backend are expected; the environment is
  offline, so do not fetch anything).
- After install, `import sqlparse` must work and the CLI must run as `python -m sqlparse`.

## Import paths (must match exactly)

The tests import these names, so they must exist at these paths:

- `sqlparse` — `parse`, `parsestream`, `split`, `format`, `__version__`
- `sqlparse.lexer` — `tokenize`
- `sqlparse.sql` — `Statement`, `Token`, `TokenList`, `Identifier`, `IdentifierList`,
  `Function`, `Comparison`, `Where`, `Case`
- `sqlparse.tokens` — the token-type hierarchy (see "Token types")
- `sqlparse.exceptions` — `SQLParseError` (a subclass of `Exception`)

Command line: `python -m sqlparse` runs the `sqlformat` CLI (i.e. a `sqlparse/__main__.py`
delegates to the CLI's `main`).

## Top-level functions

- **`parse(sql, encoding=None) -> tuple[Statement, ...]`** — parse one or more statements.
  Returns a **tuple** of `Statement` objects with grouping applied. `str(statement)`
  reproduces that statement's original source **verbatim** (all whitespace and non-ASCII
  preserved). Empty / whitespace-only input returns an empty tuple.
- **`parsestream(sql, encoding=None) -> generator`** — like `parse` but returns a
  **generator** of `Statement` objects (accepts a string or a file-like object).
- **`split(sql, encoding=None, strip_semicolon=False) -> list[str]`** — return the source
  split into individual statement strings, each **stripped** of surrounding whitespace.
  With `strip_semicolon=True`, a trailing `;` is also removed from each. See "Statement
  splitting".
- **`format(sql, encoding=None, **options) -> str`** — return reformatted SQL. Options and
  behavior are in "Formatting". Invalid options raise `SQLParseError` (see "Option
  validation").

## Tokenizing

**`sqlparse.lexer.tokenize(sql, encoding=None)`** returns a **generator** of
`(token_type, value)` 2-tuples — the flat lexer stream before grouping. For example,
`select * from foo;` yields, in order, `(DML, 'select')`, whitespace, `(Wildcard, '*')`,
whitespace, `(Keyword, 'from')`, whitespace, `(Name, 'foo')`, `(Punctuation, ';')`.

Token classification rules the tests rely on:

- **Numbers**: integers → `Number.Integer`; decimals including a leading-dot form and
  scientific notation (`1.5`, `.5`, `6.67428E-8`) → `Number.Float`; `0x…` → `Number.Hexadecimal`.
  A bare word that merely looks like scientific notation (`e1`) is a `Name`, not a number.
- **Quoting**: `'...'` single-quoted text → `String.Single`; a `"..."` double-quoted name
  parses as an **`Identifier`** (double quotes delimit identifiers, not strings).
- **Placeholders**: `?`, `:name`, `:1`, `%s`, `%(name)s` → `Name.Placeholder`. A `%` used
  as modulo is an `Operator`, not a placeholder.
- **Keywords**: DML verbs (`select`/`insert`/`update`/`delete`) → `Keyword.DML`; multi-word
  keywords such as `UNION ALL` are one keyword token; `LIKE`/`ILIKE` → `Operator.Comparison`;
  `ASC`/`DESC` → `Keyword.Order`.
- **`*`** is a `Wildcard` when it stands for a column selector (`select *`, `a.*`) but an
  arithmetic `Operator` between operands (`1 * 2`).

## Token types (`sqlparse.tokens`)

`sqlparse.tokens` exposes a hierarchy of token-type singletons. A given type is reachable
by attribute access (e.g. `tokens.Keyword`, `tokens.Keyword.DML`, `tokens.Number.Integer`,
`tokens.Name.Placeholder`, `tokens.Operator.Comparison`, `tokens.Keyword.Order`,
`tokens.String.Single`, `tokens.Punctuation`, `tokens.Wildcard`, `tokens.Name`). The
required semantics:

- **Identity**: each type is a singleton, so `ttype is tokens.Wildcard` works.
- **Containment (`in`)**: a type is contained in any of its ancestors —
  `tokens.Keyword.DML in tokens.Keyword` and `tokens.Number.Integer in tokens.Number` are
  `True`, but a parent is **not** in its child (`tokens.Keyword in tokens.Keyword.DML` is
  `False`).
- **Top-level aliases**: besides the root types (`tokens.Keyword`, `tokens.Name`,
  `tokens.Punctuation`, `tokens.Wildcard`, `tokens.Operator`, …), the SQL-specific keyword
  subtypes `DML`, `DDL` and `CTE` are **also** bound as top-level attributes of
  `sqlparse.tokens`, each the identical singleton to its nested `Keyword.*` form —
  `tokens.DML is tokens.Keyword.DML`, `tokens.DDL is tokens.Keyword.DDL`,
  `tokens.CTE is tokens.Keyword.CTE`. So `tokens.DML` resolves to the exact type the lexer
  emits for a DML verb, matching the bare `(DML, 'select')` shorthand in the Tokenizing
  example. Other leaf subtypes (e.g. `Keyword.Order`, `Number.Integer`, `Name.Placeholder`,
  `String.Single`) are reachable only through their qualified path.

Every token exposes `.ttype` (its type, or `None` for a grouped node), `.value` (its
text), `.is_keyword` (True iff `.ttype` is within `Keyword`), and `.normalized` (the value
upper-cased for keywords, else the value unchanged).

## The parse tree / object model (`sqlparse.sql`)

`parse` groups the flat token stream into a tree of `TokenList` nodes. A `TokenList` holds
child tokens in `.tokens`, has `.is_group == True`, and stringifies to its source.

**`Statement`** (a `TokenList`):
- `get_type()` → the statement's kind as an upper-case string: the leading DML/DDL verb
  (`'SELECT'`, `'INSERT'`, `'UPDATE'`, `'DELETE'`, `'CREATE'`, …). A leading comment or
  whitespace is skipped. For a `WITH … ` CTE, the type is that of the statement the CTE
  feeds (e.g. `SELECT`). If no DML/DDL verb is present, it is `'UNKNOWN'`.

**Navigation** (on any `TokenList`):
- `flatten()` → generator over the leaf tokens (no groups) in order.
- `token_first(skip_ws=True, skip_cm=False)` → the first child token.
- `get_token_at_offset(offset)` → the leaf token covering character `offset` of the source.
- `within(cls)` → True if any ancestor is an instance of `cls`.
- `is_child_of(other)` → True if `other` is the direct parent.
- `has_ancestor(other)` → True if `other` is anywhere on the parent chain.
- `match(ttype, values, regex=False)` → True if a token's type is `ttype` and its
  (case-insensitive, for keywords) value matches `values` (a string or collection).

**Grouped constructs** — `parse` recognises these and wraps them in the corresponding
`sqlparse.sql` class:

- **`Identifier`** — a name, optionally qualified/aliased/cast/ordered:
  - `get_real_name()` → the name **after the first `.`** (or the sole name).
  - `get_parent_name()` → the name **before the first `.`** (or `None`).
  - `get_alias()` → the alias (from `AS x` or a trailing alias token), else `None`.
  - `get_name()` → the alias if present, else the real name.
  - `get_typecast()` → the type name of a PostgreSQL `value::type` cast, else `None`.
  - `get_ordering()` → `'ASC'` / `'DESC'` for an ordered identifier, else `None`.
  - `is_wildcard()` → True for `*` or a qualified `a.*` (whose `get_real_name()` is `'*'`).
  - `get_array_indices()` → for a subscripted name such as `col[1]`, yields the index
    expressions (each yielded item is a list of the tokens making up one `[...]` index).
  - Example: for `a.b`, `get_real_name() == 'b'` and `get_parent_name() == 'a'`. For
    `x.y as z`, `get_real_name() == 'y'`, `get_parent_name() == 'x'`, `get_alias() == 'z'`,
    `get_name() == 'z'`. A double-quoted `"quoted"` has `get_real_name() == 'quoted'`.
- **`IdentifierList`** — a comma-separated list; `get_identifiers()` yields its member
  tokens (commas and whitespace excluded). `select a, b, c` groups the three columns into
  one `IdentifierList` of three members.
- **`Function`** — `name(args)`; `get_real_name()` → the function name, `get_parameters()`
  → the list of argument tokens (`foo(a, b)` → `['a', 'b']`; `count(*)` → name `'count'`).
  A bare keyword before parentheses is **not** a function: `IN (1, 2)` stays a keyword plus
  parentheses. A `CREATE TABLE` target keeps its (possibly dotted) name as an identifier,
  not a function call: `create table db.tbl (…)` does not group `db.tbl (…)` as a `Function`.
- **`Comparison`** — an `a <op> b` comparison; `.left` and `.right` are the operand tokens
  (`a = 1` → left `a`, right `1`).
- **`Operation`** — an arithmetic expression such as `a + b` groups into an `Operation`.
- **`Where`** — a `WHERE` clause. It spans from `WHERE` up to (but not including) the next
  clause-starting keyword — `ORDER BY`, `GROUP BY`, `LIMIT`, `HAVING`, `UNION`, `RETURNING`,
  `INTO`, etc. — or the end of the statement.
- **`Case`** — a `CASE … END` expression; `get_cases(skip_ws=False)` returns a list of
  `(condition_tokens, value_tokens)` pairs, one per `WHEN` plus the `ELSE`. The `ELSE`
  branch has a condition of `None`.

Any faithful grouping is acceptable as long as these classes and accessors return the
documented values; the tests assert accessor results and `isinstance` membership, not a
specific raw token layout.

## Statement splitting

`split` (and the statement boundaries `parse`/`parsestream` produce) obey these rules:

- Split on a top-level `;`. A `;` inside a string literal or comment does **not** split.
- `strip_semicolon=True` additionally strips the trailing `;` from each returned statement.
- A `BEGIN … END` block is one statement: semicolons **inside** it do not split it.
- `BEGIN TRANSACTION` (and `BEGIN;`) is an ordinary standalone statement, **not** a block —
  it does not swallow following statements.
- A dollar-quoted body (`$$ … $$`, e.g. a `CREATE FUNCTION` body) is opaque: semicolons
  inside it do not split.
- `GO` is a batch separator; it stays attached to the batch it terminates.

## Formatting (`format` options and the CLI)

`format(sql, **options)` applies the following options (all default to off / `None` unless
noted). The `sqlformat` CLI exposes the same behaviors as flags.

Case & comments:
- `keyword_case` (`'upper'` / `'lower'` / `'capitalize'`) — recases **keyword** tokens
  only; identifiers and string literals are left unchanged.
- `identifier_case` (`'upper'` / `'lower'` / `'capitalize'`) — recases identifier names,
  but **never** a double-quoted identifier (`"BarCol"` is preserved verbatim).
- `strip_comments` (bool) — remove comments, but **preserve optimizer hint comments**
  (`/*+ ... */`). Removing a comment leaves the surrounding whitespace in place.
- `strip_whitespace` (bool) — collapse each run of whitespace between tokens to one space.
- `use_space_around_operators` (bool) — put a single space around arithmetic operators
  (`1+2` → `1 + 2`).
- `truncate_strings` (int > 1) — shorten single-quoted string literals whose **content** is
  longer than N characters: keep the opening quote and the first N content characters, append
  the marker, then keep the closing quote. `truncate_char` (default `'[...]'`) sets the marker.
  For example `truncate_strings=6` turns `'abcdefghijkl'` into `'abcdef[...]'`. Quoted
  **identifiers** are never truncated.

Output wrapping:
- `output_format` (`'python'` / `'php'` / `'sql'`) — wrap the statement as source in that
  language: `python` → `sql = '<stmt>'`; `php` → `$sql = "<stmt>";`.

Reindentation:
- `reindent` (bool) — pretty-print with each major clause on its own line (implies
  whitespace stripping). The layout rules:
  - Each clause keyword (`from`, `where`, `join … on …`, `group by`, `order by`, `union`,
    …) starts a new line at the statement's base indent. A `join … on …` stays on one line.
  - In a comma list (the select list, etc.), the first item stays on the keyword's line
    and each following item goes on its own line, left-padded to **align under the first
    item**. For example `select x, y, z from t` becomes:
    ```
    select x,
           y,
           z
    from t
    ```
  - A parenthesised subquery is placed on a new line, with the opening `(` indented by
    `indent_width` (default `2`); the subquery's inner clauses are reindented so its inner
    query aligns one column past the `(`. For example `select name from (select id from users)`
    becomes:
    ```
    select name
    from
      (select id
       from users)
    ```
    (the `(` sits at column 2 = `indent_width`; the inner `from` aligns under the inner
    `select`, i.e. at column 3, one past the `(`.)
  - A `CASE` expression puts each `WHEN`/`ELSE` on its own line, aligned a fixed indent past
    the `CASE` keyword, and de-indents the `END` to line up under the `CASE` value. For example
    `select case when flag then 1 else 0 end from data` becomes:
    ```
    select case
               when flag then 1
               else 0
           end
    from data
    ```
  - Boolean conditions (`AND`/`OR`) inside a `WHERE` clause each start a new line, indented by
    `indent_width` (2 spaces) under the `WHERE` line. For example
    `select y from tbl where m = 3 and n = 4` becomes:
    ```
    select y
    from tbl
    where m = 3
      and n = 4
    ```
  - `INSERT ... VALUES` puts each value tuple on its own line, aligned under the first tuple.
  - Successive statements are separated by one blank line.
- `indent_width` (int ≥ 1, default `2`) — spaces per indent level (used e.g. for subquery
  indentation).
- `indent_columns` (bool) — put **every** column of the select list on its own line
  indented by `indent_width` (rather than aligning under the first column); implies
  `reindent`.
- `indent_after_first` (bool) — indent the clauses that follow the first line.
- `comma_first` (bool) — lead each wrapped list continuation line with the comma.
- `reindent_aligned` (bool) — an alternative layout that **right-aligns clause keywords** to
  the width of `select` (6 characters) and lines the select list up beneath it. For example
  `select p, q from t1 join t2 on t1.a = t2.a where z is null` becomes:
  ```
  select p,
         q
    from t1
    join t2
      on t1.a = t2.a
   where z is null
  ```
  (`from`/`join` get two leading spaces, `on` four, `where` one — each keyword's last
  character sits at column 6.)

## The `sqlformat` command-line interface

`python -m sqlparse [OPTIONS] FILE [FILE ...]`. Use `-` as FILE to read from stdin. The CLI
wires its flags to the `format` options above and writes the result to stdout (or an output
file). The result is written **verbatim** — byte-for-byte equal to the `format()` return
value, with **no trailing newline appended** — to whichever destination is selected (stdout,
an `-o/--outfile` file, or a file rewritten with `--in-place`). Flags used here:

- `-k/--keywords {upper,lower,capitalize}` → `keyword_case`
- `-i/--identifiers {upper,lower,capitalize}` → `identifier_case`
- `-l/--language {python,php}` → `output_format`
- `-r/--reindent` → `reindent`; `-a/--reindent_aligned` → `reindent_aligned`
- `-s/--use_space_around_operators`; `--strip-comments`; `--indent_width N`
- `-o/--outfile FILE` — write to FILE instead of stdout
- `--in-place` — rewrite the input file(s) in place
- `--version` — print the package version (`sqlparse.__version__`) and exit 0
- `--help` — print usage and exit 0

Exit codes and error reporting:
- **0** — success (including when reading from stdin and writing the formatted result).
- **2** — an argparse **usage** error: an invalid option *choice* (e.g. `-l xml`) or a
  missing required file argument. Argparse prints its own usage/error text to stderr.
- **1** — a **runtime** error, reported to stderr as a line beginning with `[ERROR] `:
  - an invalid option *value* → `[ERROR] Invalid options: <message>` (e.g.
    `[ERROR] Invalid options: indent_width requires a positive integer`),
  - a missing/unreadable input file → `[ERROR] Failed to read <path>: <reason>`,
  - `-` combined with `--in-place` → `[ERROR] Cannot use --in-place with stdin`,
  - multiple input files without `--in-place` → an error mentioning `Multiple files`.

## Option validation errors

`format` (and the CLI, which surfaces the same messages) validates options and raises
`SQLParseError` with these exact messages:

- `keyword_case` / `identifier_case` not in the allowed set → `Invalid value for keyword_case: <value!r>`
  (respectively `identifier_case`).
- `output_format` unknown → `Unknown output format: <value!r>`.
- a boolean option given a non-boolean (`strip_comments`, `reindent`, …) →
  `Invalid value for <option>: <value!r>` (e.g. `Invalid value for reindent: 2`).
- `indent_width` not an integer → `indent_width requires an integer`; less than 1 →
  `indent_width requires a positive integer`.
- `wrap_after` not an integer → `wrap_after requires an integer`; negative →
  `wrap_after requires a positive integer`.
- `comma_first` not a boolean → `comma_first requires a boolean value`.
- `truncate_strings` not a usable positive integer → `Invalid value for truncate_strings: <value!r>`.

(`<value!r>` denotes the Python `repr` of the offending value, e.g. `'bogus'` or `None`.)

## Robustness / resource limits

The parser must not hang or crash on pathological input. When grouping would exceed its
safety limits, raise `SQLParseError`:

- more than 10 000 tokens in a group → `Maximum number of tokens exceeded (10000).`
- grouping nested deeper than 100 levels → `Maximum grouping depth exceeded (100).`
- hitting the Python recursion limit while parsing → `Maximum recursion depth exceeded`.

Ordinary, reasonably-sized SQL must continue to parse normally. Deeply nested input that
hits a cap must fail fast (well under a second), so compute a group's string value from its
direct children rather than by repeatedly re-flattening the whole subtree.
