# goawk — an AWK interpreter with CSV support, in Go

Build `goawk`, a command-line AWK interpreter in Go: a **POSIX-compatible awk** plus the GoAWK
extensions below (CSV/TSV mode, named fields, negative field indexes, Unicode "chars" mode).

Implement standard **POSIX awk semantics** exactly (per the POSIX `awk` definition and mainstream
awks). This document names the surface you must cover and spells out only the points that are
GoAWK-specific or easy to get wrong; for everything else, match POSIX awk precisely (including the
finer points — number formatting, comparison/coercion rules, operator precedence, field rebuilding,
array semantics, and built-in edge cases).

## Build & environment
- Go, **standard library only** (no third-party modules). Grading is **offline** — nothing can be
  downloaded. Provide a `go.mod`; `go build` must succeed offline.
- Provide `setup.sh` (run from the working directory) that builds the binary to **`/app/goawk`**,
  e.g. `go build -o /app/goawk .`. Any source layout within the Go module is fine; grading drives
  the built binary through its CLI.
- The binary must be a **self-contained** interpreter: your own Go code lexes, parses and evaluates
  the AWK program. It must not run the program by invoking an external `awk`/`gawk`/`mawk` or any
  other external interpreter, and must behave identically when no such program is present on
  `PATH`. (This does not restrict `system()` or `cmd |` / `| cmd`, which run commands the AWK
  program itself asks for.)

## Command line
```
goawk [options] 'program' [file ...]
```
The first non-option argument is the program; the rest are input files (none, or `-`, → stdin).
Options may be joined or separated (`-F,` or `-F ,`); `--` ends options.

- `-F <sep>` — field separator `FS`.
- `-v <var>=<value>` — pre-set a global (repeatable); the value gets string-literal **escape
  processing** (`-v X=a\tb` → a tab). A bare `var=value` **argument among the files** is applied, in
  order, when reached (it is not a filename) — same escape processing.
- `-i <mode>` / `--csv` (= `-i csv`) — CSV/TSV input mode; `-o <mode>` — CSV/TSV output mode;
  `-H` — header row / named fields (only valid with `-i`); `-c` — chars mode (see extensions).

**Errors:** invalid usage exits nonzero with a stderr diagnostic and no stdout — an unknown option,
a missing option-argument, a `-v` not of the form `name=value`, or a nonexistent input file (message
indicates the file was not found). A program **syntax error** exits nonzero with a stderr diagnostic
naming the offending **1-based line number**. A runtime **division by zero** is fatal (nonzero exit;
message contains `division by zero`).

## Language (POSIX awk)
Implement the full language, matching POSIX awk exactly:

- `pattern { action }` rules with `BEGIN`/`END`, bare patterns (which print `$0`), bare actions,
  `/regex/` patterns, and range `pattern1, pattern2` patterns; `;`/newline statement separators;
  `#` comments. A program with only `BEGIN` rules must not read input.
- Records & fields: `$0`, `$1..$NF`, `NF`. Fields and `NF` are assignable lvalues (including `$i++`
  and compound assignment); modifying a field, `NF`, or `$0` rebuilds/re-splits per POSIX rules.
  `FS` (default whitespace; a single char; a regex if multi-char; `""` splits per character),
  `RS` (including paragraph mode `RS=""`), `OFS`, `ORS`.
- Dynamically typed values; uninitialized = `0`/`""`. **Numeric strings** (e.g. input fields)
  compare numerically; string constants compare as strings.
- Operators: `+ - * / % ^`, comparisons, `~`/`!~`, `&& || !`, ternary `?:`, concatenation
  (juxtaposition), `=` and `+= -= *= /= %= ^=`, `++`/`--`, `in`. This line only names the operators;
  precedence and associativity follow POSIX awk.
- Control flow: `if`/`else`, `while`, `do`/`while`, `for(;;)`, `for(k in a)`, `break`, `continue`,
  `next`, `nextfile`, `exit [code]` (runs `END`, then exits with `code` as the process status).
- Arrays: associative; multi-subscript via `SUBSEP`; `(k in a)`; `delete a[k]`; `delete a`.
- Functions: `function f(params){...}` with `return`; recursion; arrays passed by reference and
  scalars by value; extra parameters serve as locals.
- Built-ins (standard POSIX behavior): `length`, `substr`, `index`, `split` (its separator may be a
  regex), `sub`, `gsub`, `match`, `sprintf`, `toupper`, `tolower`; `int`, `sqrt`, `exp`, `log`,
  `sin`, `cos`, `atan2`, `rand`, `srand`; `getline` (plain, `< file`, and `cmd |`), `close`,
  `system`. `rand` returns a value in `[0, 1)`; its exact values are implementation-defined, but
  `srand(seed)` re-seeding with the same value must reproduce the sequence.
- `printf`/`sprintf`: conversions `%d %i %o %x %X %e %E %f %g %G %c %s %%`, with field width,
  precision, the `-` and `0` flags, and `*` (width taken from an argument). String-literal escape
  sequences (`\n`, `\t`, …) are interpreted.
- Output redirection `>`, `>>`, `|`; `getline` from `< file` and `cmd |`; `close` to flush and
  reopen a stream.
- Special variables: `NR`, `NF`, `FNR`, `FILENAME`, `FS`, `OFS`, `ORS`, `RS`, `SUBSEP`, `RSTART`,
  `RLENGTH`, `CONVFMT`, `OFMT`, `ENVIRON`, and (header mode) `FIELDS`.

## GoAWK extensions
- **Negative field indexes:** `$-1` is the last field, `$-2` the second-to-last, etc.
- **Chars mode (`-c`):** `length`, `substr`, `index`, `match`, and `%c` operate on Unicode
  characters (runes) instead of bytes.
- **CSV/TSV input (`-i csv` | `-i tsv` | `--csv`):** parse records/fields per RFC 4180 (fields may be
  quoted with `"`, contain the separator or embedded newlines, and use `""` for a literal `"`),
  ignoring `FS`/`RS`; access fields as `$1`, `$2`, … (and via negative indexes). Mode options
  (space-separated) are `separator=<char>`, `comment=<char>` (skip lines starting with it), and
  `header` (equivalent to `-H`). In CSV input mode the two-argument `split(s, a)` splits using CSV
  rules; the three-argument form is unchanged.
- **Named fields (`-H` / `header`):** `@"name"` (and computed `@(expr)`) accesses the field under
  that header column; the `FIELDS` array maps column number → name for the current header.
- **CSV/TSV output (`-o csv` | `-o tsv`, optional `separator=<char>`):** `print` with arguments
  emits CSV/TSV (ignoring `OFS`/`ORS`), quoting any field that contains the separator, a quote, or a
  newline (interior quotes doubled); `printf` is unaffected. A field assignment such as `$1=$1`
  rebuilds `$0` in the output format.
