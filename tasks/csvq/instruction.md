# Build `csvq`: a SQL query engine for CSV files

Implement a command-line tool, **`csvq`**, that executes SQL-like queries against CSV (and
TSV/JSON) files and prints the result set in a chosen output format. This is a self-contained query
engine: a lexer, an SQL parser, an expression/evaluation engine with SQL three-valued logic, a
relational executor (projection, filtering, joins, grouping, ordering, set operations, subqueries,
common table expressions, and window/analytic functions), a library of built-in scalar and
aggregate functions, and CSV/TSV/JSON/TEXT/GFM serializers.

## Language, build, and runtime constraints

- Write the program in **Go, using only the Go standard library** (no third-party modules). The
  grading environment is fully offline.
- Your repository root must be a Go module whose `main` package builds the CLI.
- Provide an executable **`setup.sh`** in the repo root that builds the binary to **`/app/csvq`**:
  ```sh
  go build -o /app/csvq .
  ```
- Grading drives `/app/csvq` as a black box via subprocess: it passes the SQL string as a single
  command-line argument (plus option flags), optionally pipes data on stdin, and compares stdout,
  stderr, and the exit code. Only the externally observable behavior described here is graded.

## Invocation

```
csvq [options] "<sql statement>"
csvq [options] calc "<expression>"          # subcommand; see below
```

- The SQL statement is a **single positional argument**. Multiple statements separated by `;` are
  allowed but the graded scenarios use one `SELECT` statement.
- Exit status is `0` on success. On any error (parse error, missing file, unknown column, unknown
  function, type error, …) exit with a **non-zero** status and print a diagnostic message to
  **stderr** (nothing to stdout). The exact wording of diagnostics is not graded; only that the exit
  code is non-zero, stderr is non-empty, and stdout is empty.

### Referring to tables (files)

- In a `FROM` clause a table is a file, written either as a **backtick-quoted path**
  (`` FROM `users.csv` ``) or as a **bare identifier with no extension** (`FROM users`), which
  resolves to `users.csv` in the current working directory.
- The keyword **`STDIN`** (`` FROM STDIN ``) exposes CSV data piped on standard input as a table.
- Files are resolved relative to the process's current working directory.

### Options (flags)

| Flag | Meaning |
| --- | --- |
| `-f`, `--format` `FMT` | Output format: `CSV` (default when writing to a pipe), `TSV`, `JSON`, `TEXT`, `GFM`, `ORG`, `LTSV`, `FIXED`. |
| `-d`, `--delimiter` `D` | Input field delimiter for CSV (default `,`). Accepts `\t` for a tab. |
| `--no-header`, `-n` | Treat the input's first line as data; auto-name columns `c1`, `c2`, … |
| `--without-header`, `-N` | Omit the header line from the output. |

## Output formats

For a result set with columns `id,name` and one row `1,Alice`:

- **CSV** (default): a header line then one line per row, `\n`-terminated. Fields are quoted only
  when necessary — i.e. when they contain a comma, a double quote, or a newline — and embedded
  double quotes are doubled (RFC 4180). Example:
  ```
  id,name
  1,Alice
  ```
- **TSV** (`-f TSV`): same as CSV but tab-separated.
- **JSON** (`-f JSON`): a compact array of objects on a single line, followed by a trailing newline:
  `[{"id":"1","name":"Alice"}]\n`. Values loaded from a CSV file are emitted as JSON **strings** (no
  type inference for file fields); a NULL value is emitted as JSON `null`. The `JSON_OBJECT(a, b, …)`
  function builds an object keyed by the argument expressions' names.
- **TEXT** (`-f TEXT`): an ASCII-bordered table. Borders use `+`, `-`, `|`; each cell is padded with
  at least one space on each side; headers are centered; **numeric columns are right-aligned and
  string columns left-aligned**. A column is as wide as its widest cell (header or value), widened by
  exactly one character only when that is needed for the header to sit exactly centered in it (the
  same number of spaces on either side of the header), and never widened for any other reason. A
  NULL prints as `NULL` and an empty string as nothing. For columns `id,name` / row `1,Alice`:
  ```
  +----+--------+
  | id |  name  |
  +----+--------+
  | 1  | Alice  |
  +----+--------+
  ```
- **GFM** (`-f GFM`): a GitHub-Flavored-Markdown table — a header row, a separator row of dashes,
  then data rows. Header cells are centered (as in TEXT) and data cells are left-aligned; each cell is
  padded with one space on each side to the column
  width; the separator cell is filled with dashes to that same inner width. For columns `id,name`
  with rows `1,Alice` / `2,Bob`:
  ```
  |  id  |  name  |
  | ---- | ------ |
  | 1    | Alice  |
  | 2    | Bob    |
  ```
- **ORG** (`-f ORG`): an Emacs org-mode table — like TEXT but with no outer top/bottom border and the
  separator row joining columns with `+`:
  ```
  | id |  name  |
  |----+--------|
  | 1  | Alice  |
  | 2  | Bob    |
  ```
- **LTSV** (`-f LTSV`): one `key:value` record per row, tab-separated, no header line
  (`id:1<TAB>name:Alice`).
- **FIXED** (`-f FIXED`): fixed-width space-padded columns — a header line then one line per row.
  Every column (including the last) is **left-aligned** and padded to the width of its widest cell,
  and columns are joined by a **single space**; the trailing column keeps its padding, so lines are
  **not** right-stripped. For columns `id,name` with rows `1,Alice` / `2,Bob` (the header line and
  the `Bob` line therefore end in trailing spaces):
  ```
  id name 
  1  Alice
  2  Bob  
  ```

## Values, types, and NULL

- A field read from a CSV file is text, but it is **interpreted as a number when used in a numeric
  context** (arithmetic, numeric comparison, numeric aggregates). In particular **comparisons coerce
  numeric-looking strings to numbers** — `'02' = 2` is true and `'10' > 9` is true (not a lexical
  comparison). In CSV/JSON output an unmodified field is emitted as its original text.
- An **empty CSV field is NULL** (not the empty string): it is skipped by `COUNT(column)` and by
  numeric aggregates. (A wholly blank input line is skipped entirely, contributing no row.)
- The string-concatenation operator `||` **stringifies numeric operands** (`1 || 'x' || 2` → `1x2`).
- Integer vs. float: an arithmetic expression over two integers stays integer; if any operand is a
  float the result is float. **Integer division truncates toward zero** (`7 / 2` → `3`); `%` is the
  integer modulo. A float result with no fractional part is printed **as an integer** (`3.0` → `3`,
  `6.0 / 2` → `3`).
- Floats are formatted with Go's shortest round-trip representation
  (`AVG` of `30,25,40` → `31.666666666666668`; `POW(2, 0.5)` → `1.4142135623730951`).
- **Booleans** print lowercase: `true` / `false`.
- csvq uses SQL **three-valued logic** (TRUE / FALSE / UNKNOWN). `NULL = NULL` is UNKNOWN, which
  renders as an **empty field** in CSV; `NULL IS NULL` is the boolean `true`. A NULL operand of
  string concatenation `||` makes the whole result NULL. `TERNARY(value)` casts to the ternary type
  and renders TRUE/FALSE as `true`/`false` and UNKNOWN as empty.

## SQL surface to implement

### SELECT

`WITH` … `SELECT [DISTINCT] <select-list> FROM <tables/joins> WHERE <cond> GROUP BY <keys>
HAVING <cond> ORDER BY <keys> LIMIT <n> OFFSET <m>`

- **Select list**: column references, `table.column`, `*`, expressions, and `AS` aliases (an alias
  becomes the output column name). `*` preserves source column order.
- **WHERE**: comparison operators (`= <> < <= > >=`), `AND` / `OR` / `NOT` with parentheses,
  `LIKE` / `NOT LIKE` (**case-insensitive**; `%` matches any run, `_` matches one character), `IN` / `NOT IN`
  (list-or-subquery), `BETWEEN a AND b` (inclusive), `IS [NOT] NULL`, and `EXISTS (subquery)`
  including **correlated** subqueries that reference the outer row. String comparisons order
  lexicographically. `NOT IN` against a list that contains NULL evaluates to UNKNOWN (no rows match).
- **Joins**: `[INNER] JOIN … ON …`, `LEFT [OUTER] JOIN … ON …` (unmatched right columns are NULL),
  `CROSS JOIN` (Cartesian product). Several tables may be chained with successive joins, and a table
  may be joined to itself via aliases.
- **GROUP BY / HAVING**: group on one or more keys; `HAVING` filters groups by aggregate predicates
  (composable with a row-level `WHERE` and an aggregate `ORDER BY`).
- **ORDER BY**: multiple keys, each `ASC` (default) or `DESC`; may sort by an expression or by a
  select-list alias. (A bare integer in `ORDER BY` is a constant expression, **not** a column
  position.)
- **LIMIT / OFFSET**: bound and skip rows.
- **DISTINCT**: remove duplicate result rows.
- **Subqueries**: scalar subqueries usable as a value; `IN (SELECT …)`; correlated `EXISTS`; and a
  parenthesized subquery used directly in a `FROM` clause as a **derived table** with an alias
  (`FROM (SELECT …) t`), whose result columns are visible to the outer query.
- **Set operations**: `UNION` (deduplicates), `INTERSECT`, `EXCEPT`, and their `ALL` variants
  (`UNION ALL`, `INTERSECT ALL`, `EXCEPT ALL`) which keep duplicate rows. Precedence and
  associativity among set operators chained without parentheses follow standard SQL.
- **Common table expressions**: `WITH name AS (…)`, including `WITH RECURSIVE name(col, …) AS
  (anchor UNION ALL recursive)`.
- **Window / analytic functions** with `OVER ([PARTITION BY …] ORDER BY …)`:
  `ROW_NUMBER()`, `RANK()` (gaps after ties), `DENSE_RANK()` (no gaps),
  `LAG(expr)` / `LEAD(expr)` (previous/next row, NULL at the edges),
  `FIRST_VALUE(expr)`, `NTILE(n)` (distribute rows into n buckets),
  `PERCENT_RANK()` (`(rank − 1) / (rows − 1)`), and any aggregate used as a window function
  (`SUM(x) OVER (ORDER BY …)` is a running total).

### `calc` subcommand

`csvq calc "<expression>"` reads **one CSV row from stdin**, exposes its fields as columns
`c1`, `c2`, …, evaluates the expression, and prints the single result value **with no trailing
newline**. Example: stdin `1,2,3`, expression `c1 + c3` → `4`.

## Built-in functions

Implement at least the following. Names are case-insensitive in SQL but shown uppercase here.

- **String**: `UPPER`, `LOWER`, `TRIM(str[,cutset])`, `LTRIM(str[,cutset])`, `RTRIM(str[,cutset])`,
  `LEN` (counts Unicode runes), `SUBSTRING(str, start[, length])` (**1-based** start),
  `SUBSTR(str, start[, length])` (**0-based** start), where a negative start counts from the end and
  an over-long length clamps; `LPAD(str, len, pad)`, `RPAD(str, len, pad)`,
  `REPLACE(str, old, new)` (replaces all occurrences),
  `INSTR(str, sub)` returns the **0-based** index of the first occurrence or **NULL** if not found,
  `TITLE_CASE` (capitalize each word), `FORMAT(fmt, args…)` (printf-style verbs `%s`, `%d`, `%f`,
  `%.2f`, …), `REGEXP_REPLACE(str, pattern, repl)` (replace all regex matches),
  `WIDTH(str)` (display width — East-Asian wide characters count as 2), `BYTE_LEN(str)` (UTF-8 byte
  count), and `JSON_VALUE(path, json)` (extract a value from a JSON document by dotted path).
- **Numeric**: `ABS`, `CEIL(n[, place])`, `FLOOR(n[, place])`, `ROUND(n[, place])`
  (**rounds halves away from zero** — `ROUND(2.5)` → `3`, `ROUND(-2.5)` → `-3`),
  `POW(base, exp)` (fractional exponents allowed), `SQRT`, `NUMBER_FORMAT(n[, place])` (groups
  thousands with commas, optional decimal places), and base conversions `BIN`, `OCT`, `HEX` of an
  integer (`HEX` uses **lowercase** digits, e.g. `HEX(255)` → `ff`).
- **Cast**: `INTEGER(v)` (truncates toward zero), `FLOAT(v)`, `STRING(v)`, `BOOLEAN(v)`,
  `TERNARY(v)`. (Note: there is **no** `CAST(x AS type)` syntax — use these functions.)
- **Logical**: `COALESCE(v…)` (first non-NULL), `IF(cond, a, b)`, `IFNULL(v, alt)`,
  `NULLIF(a, b)` (NULL when equal), and both searched (`CASE WHEN … THEN … ELSE … END`) and simple
  (`CASE expr WHEN v THEN … END`) `CASE`. A `CASE` with no matching branch and no `ELSE` is NULL.
- **Datetime**: `DATETIME(str)` parses `'YYYY-MM-DD[ HH:MM:SS]'`; `DATETIME_FORMAT(dt, layout)` with
  `%`-placeholders — `%Y` (4-digit year), `%m` (2-digit month number), `%d` (2-digit day),
  `%H` (2-digit hour), **`%i` (2-digit minute)**, `%s` (2-digit second), **`%M` (full month name)**,
  `%a` (abbreviated weekday, e.g. `Thu`), `%b` (abbreviated month, e.g. `Mar`), `%W` (full weekday
  name), `%p` (`AM`/`PM`); component extractors `YEAR`, `MONTH`, `DAY`, `HOUR`, `MINUTE`, `SECOND`,
  `WEEKDAY` (Sunday = 0), and `DAY_OF_YEAR` (return integers); arithmetic `ADD_DAY(dt, n)` and
  `ADD_MONTH(dt, n)` — both use **Go-style date normalization**, so `ADD_MONTH('2021-01-31', 1)` is
  `2021-03-03` (Feb 31 normalized to Mar 3), not Feb 28 — and `DATE_DIFF(a, b)` (whole-day difference
  `a - b`).
- **Aggregate** (over a group or the whole result set): `COUNT(*)` counts rows, while
  `COUNT([DISTINCT] expr)` and the numeric aggregates **skip NULLs**. `SUM`, `AVG` (yields an
  integer when the mean divides evenly, else a float), `MIN`, `MAX`, `MEDIAN`, `STDEV`, `VAR`
  (**sample** statistics — divide by n−1), `LISTAGG([DISTINCT] expr[, sep]) WITHIN GROUP (ORDER BY
  …)`, and `JSON_AGG(expr)` (aggregate into a JSON array). Over an empty group `COUNT` is `0` and
  `SUM`/`MIN`/`MAX` are NULL.

## Notes on identifiers

Identifiers may be bare words or backtick-quoted. SQL keywords (e.g. `NEXT`, `SUM`, `ORDER`) are
reserved and cannot be used as bare aliases — quote them or pick another alias.

Implement standard SQL semantics for everything above except where this document specifies csvq's
particular behavior — integer division, float normalization, 0-based `SUBSTR`/`INSTR`, sample
`STDEV`/`VAR`, three-valued NULL logic, the cast-function family, ROUND half-away-from-zero,
case-insensitive `LIKE`, Go-style `ADD_MONTH` normalization, numeric-string coercion in comparisons,
and the exact output formats (CSV/TSV/JSON/TEXT/GFM/ORG/LTSV/FIXED). Those specified behaviors are
what the grader checks.
