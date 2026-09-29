# bosphorus

Bosphorus is a C++17 preprocessor for **ANF** (Algebraic Normal Form) — systems of Boolean
polynomial equations over **GF(2)**, the two-element field where addition is XOR and
multiplication is AND. It takes an ANF as input, runs several simplification passes on it, and
can also translate the simplified ANF into an equisatisfiable **CNF** (Conjunctive Normal Form)
in the standard **DIMACS** file format for downstream **SAT** (Boolean satisfiability) solvers,
optionally invoking one to find a solution.

The primary interface is a command-line tool (`bosphorus`) used as a front-end preprocessor
for XOR-heavy SAT problems that arise in algebraic cryptanalysis and post-quantum
cryptography research.

Your job is to build the `bosphorus` project from scratch — a CMake C++17 project that
produces a `bosphorus` CLI executable and installs it under `/usr/local/`.

---

## Build & install contract

Your `setup.sh` runs offline and must produce (after `bash ./setup.sh`):

- Executable at `/usr/local/bin/bosphorus`
- `ldconfig` run after install

Everything must be produced from your source tree via a standard `cmake -B build … && cmake
--build build && cmake --install build && ldconfig` cycle. The C++ standard is C++17 minimum.

The following are available in the image:

| Dependency        | Purpose                                                        |
|-------------------|----------------------------------------------------------------|
| Boost 1.74        | `program_options` for CLI parsing; standard headers throughout |
| zlib              | Optional gzipped DIMACS input support                          |
| libpng            | Optional matrix-dump image emitter (unused by default)         |
| libm4ri           | Dense GF(2) matrix operations (Gaussian elimination)           |
| BRiAl             | Boolean ring algebra — polynomial arithmetic in GF(2)[x_1,…]   |
| BRiAl-groebner    | Groebner-basis helpers used by BRiAl                           |
| cryptominisat5    | SAT solver embedded via its C++ API (`libcryptominisat5-dev`)  |

---

## ANF input format

An ANF file is a sequence of lines, each of which is either:

- A comment line starting with `c` (the rest of the line is ignored)
- A polynomial equation implicitly equated to zero

Variables may be written either as `xN` or `x(N)` where `N` is a non-negative integer index.
Both notations refer to the same variable (so `x1` and `x(1)` are the same).

A polynomial is a XOR (`+`) of terms. Each term is either:

- The constant `1`
- A product of variables joined by `*` (e.g. `x1*x2*x5`)

Whitespace is insignificant except as a token separator. `*` binds tighter than `+`.
Redundant parentheses around individual sub-expressions are accepted at the parser's discretion;
malformed parentheses (unmatched, stray closing brackets) cause the tool to exit with a nonzero
status.

Example (from `test.anf`):

```
c A tiny ANF over x1, x2, x3
x1 + x2 + x3
x1*x2 + x2*x3 + 1
```

This represents the system `x1 ⊕ x2 ⊕ x3 = 0` and `x1·x2 ⊕ x2·x3 ⊕ 1 = 0` over GF(2).

---

## Command-line interface

```
bosphorus [options]
```

### I/O options

| Flag                    | Description                                                    |
|-------------------------|----------------------------------------------------------------|
| `--anfread <file>`      | Read ANF from `<file>`                                         |
| `--cnfread <file>`      | Read CNF (DIMACS) from `<file>` and chunk into an ANF          |
| `--anfwrite <file>`     | Write the (simplified) ANF to `<file>` — `/dev/stdout` allowed |
| `--cnfwrite <file>`     | Write an equisatisfiable CNF to `<file>`                       |
| `--solvewrite <file>`   | Solve and write the assignment to `<file>` (also implies solve) |
| `--solmap <file>`       | Also write a solution map (variable-lineage trace) to `<file>` |

Exactly one of `--anfread` and `--cnfread` must be provided. If neither is given, the tool
prints `c ERROR: you must provide an ANF/CNF input file` on stderr and exits with a nonzero
status.

### Simplification-pass toggles

Each pass has an integer 0/1 knob (default: on). Passing `0` disables the pass; `1` enables it.

| Flag              | Pass                                                                    |
|-------------------|-------------------------------------------------------------------------|
| `--el <0\|1>`     | ElimLin — Gauss-Jordan elimination pass that derives new linear consequences |
| `--xl <0\|1>`     | XL (extended linearization) — multiply/expand polynomials then linearize |
| `--sat <0\|1>`    | SAT — run cryptominisat5 to learn additional facts                      |
| `--simplify <N>`  | Master simplification switch: `0` disables the whole simplify loop      |

Beyond the on/off toggles:

| Flag                | Meaning                                                             |
|---------------------|---------------------------------------------------------------------|
| `--maxiters <N>`    | Maximum outer simplify iterations (default 100)                     |
| `--xldeg <N>`       | XL expansion degree, 0-3 (default 1; 0 = plain Gauss-Jordan only)   |
| `--cutnum <N>`      | Clause cutting number for CNF conversion, 3-10 (default 5)          |
| `--karn <N>`        | Karnaugh table cutoff for Brickenstein's algorithm, 0-20 (default 8) |
| `--maxtime <sec>`   | Stop solving after this many seconds; 0 = only propagate            |
| `--satinc <N>`      | Conflict-increment for the built-in SAT solver                      |
| `--satlim <N>`      | Conflict-limit for the built-in SAT solver                          |
| `--threads,-t <N>`  | Threads for the SAT solver                                          |
| `--onlynewcnfcls <N>` | With `--cnfread`, output only newly discovered CNF clauses         |

### Solve options

| Flag                 | Description                                                        |
|----------------------|--------------------------------------------------------------------|
| `--solve`            | After preprocessing, run cryptominisat5 to find one satisfying assignment |
| `--allsol`           | With `--solve` / `--solvewrite`, enumerate all distinct solutions  |
| `--maxsol <N>`       | Cap on how many solutions to enumerate (default 1)                 |

### Diagnostics & meta

| Flag                | Description                                                         |
|---------------------|---------------------------------------------------------------------|
| `--help,-h`         | Print the option groups (see below) and exit 0                      |
| `--version`         | Print version tag, git SHA1, and compilation env; exit 0            |
| `--verb,-v <N>`     | Verbosity 0-3; higher prints more `c ...` comment lines to stdout   |
| `--comments <0\|1>` | Include `c` header/trailer comments in output files (default on)    |

Invalid flags cause the CLI to print `Some option you gave was wrong. Please give '--help' to
get help` followed by `Unkown option: …` and exit with a nonzero status. Out-of-range values
for `--cutnum` (outside 3-10), `--karn` (>20), or `--xldeg` (>3) print an `ERROR!` line and exit
with a nonzero status.

`--help` output is grouped into five sections in this order: "Main options", "CNF conversion",
"XL", "ElimLin options", "SAT options". Each section header is followed by an aligned two-column
listing of that group's flags and descriptions.

---

## Output format: simplified ANF

`--anfwrite` writes the simplified ANF as three blocks in this exact order and shape (each
comment line begins with `c `):

```
c Executed arguments: --anfread test.anf --anfwrite /dev/stdout ...
c -------------
c Fixed values
c -------------
x(2)
x(5) + 1
c -------------
c Equivalences
c -------------
x(3) + x(1) + 1
x(7) + x(4)
c UNSAT : false
```

- **Header line** repeats the CLI arguments (excluding argv[0]).
- **Fixed values block** — one line per variable that has been proven equal to 0 or 1. A
  variable proven equal to 1 is written as `x(N) + 1`; a variable proven equal to 0 is
  written as `x(N)`.
- **Equivalences block** — one line per non-trivial variable identification. `x(a) = x(b)`
  is written as `x(a) + x(b)`; `x(a) = ¬x(b)` (equal-to-negation) is written as
  `x(a) + x(b) + 1`. Only pairs where `a ≠ b` and where `a` has not already been shown as a
  fixed value appear.
- **UNSAT marker** — `c UNSAT : true` or `c UNSAT : false` at the very end. When true, an
  extra block precedes the marker:
  ```
  c -------------
  c because of Fixed & Equivalences, it is UNSAT
  c -------------
  1
  ```

Each block header is 3 lines: a `c -------------` fence, the block title, another
`c -------------` fence.

Within a block, entries are emitted in ascending variable-index order.

---

## Output format: CNF DIMACS

`--cnfwrite` produces a standard DIMACS CNF file: a `p cnf <numvars> <numclauses>` problem
line followed by one clause per line, each terminated by ` 0`. Comment lines start with `c `.
Variables are numbered from 1. Positive literals are `k`; negated literals are `-k`.

XOR clauses that cannot be represented as a single OR clause are broken up according to the
`--cutnum` cutting number. Brickenstein's algorithm is used when the involved polynomial's
support fits inside the `--karn` Karnaugh cutoff.

---

## Output format: solution files & stdout

When `--solve` (or `--solvewrite`) is used and the resulting CNF is satisfiable, the CLI writes
to stdout:

```
s ANF-SATISFIABLE
v 1+x(0) x(1) 1+x(2) x(3)
```

Each `v` entry is `x(N)` if variable N is false or `1+x(N)` if variable N is true.

When UNSAT, stdout is:

```
s ANF-UNSATISFIABLE
```

When `--solvewrite <file>` is provided, `<file>` receives the CNF-style solution instead:

```
Solution SAT
v -0 1 -2 3
```

Positive literal `k` means variable `k` is true; `-k` means false. When UNSAT, `<file>`
contains a single line `Solution UNSAT`.

When `--allsol` (or `--maxsol > 1`) is set, each solution is preceded by its own
`s ANF-SATISFIABLE` / `s ANF-UNSATISFIABLE` line, and a trailing
`c Number of solutions found: <N>` is printed to stdout after enumeration ends.

---

## Simplification pipeline (conceptual)

Bosphorus loops up to `--maxiters` times over the following passes, stopping when a pass makes
no progress (no new fact learned, no equation shortened):

1. **Linear substitution.** Any polynomial that is a linear equation
   `x(a_1) + x(a_2) + … + x(a_k) + c = 0` — with **any** number of variables `k`, not only the
   fixed form `x(a) + c = 0` and the pairwise form `x(a) + x(b) + c = 0` — is used to eliminate one
   of its variables from **every other polynomial in the system, including non-linear ones**. A
   polynomial reducible to a fixed value `x(a) + c = 0` sets `x(a)` and eliminates it.
2. **ElimLin.** Treats every distinct monomial — including non-linear ones such as `x(a)*x(b)`
   — as an independent column, builds the coefficient matrix of the **whole** system over GF(2)
   (not just the already-linear polynomials), and performs Gaussian elimination; any row that
   comes out linear in the original variables is read back as a new linear consequence. Because
   monomials are linearized this way, `--el 1` on its own (even with `--xl 0`) can extract new
   linear equations — fixed values or equivalences — from a purely non-linear system.
3. **XL (extended linearization).** Differs from ElimLin only by first multiplying polynomials by
   each variable up to `--xldeg` extra degrees to create additional equations, then applying the
   same linearize-every-monomial-and-eliminate step; new linear polynomials found this way feed
   the next iteration.
4. **SAT-learning.** Converts the current ANF to CNF (see below), invokes cryptominisat5 with
   the `--satinc`/`--satlim` conflict budget, and lifts any variable assignment or unit clause
   the solver proves back into the ANF.

Each pass is a no-op when the corresponding CLI flag is 0. When a pass's toggle is 1 it runs and
contributes the consequences described for it above; the exact ordering and per-iteration
triggering within the loop is at the library's discretion. A fully-run simplify with all passes
enabled derives every fact any single pass would find.

## ANF → CNF conversion

The `write_cnf` / `anf_to_cnf` path converts each Boolean polynomial into a set of CNF clauses:

- Purely linear polynomials become XOR-clauses (which are then cut into OR-clauses using at
  most `--cutnum` literals per cut). Long XOR chains introduce fresh auxiliary variables.
- Small non-linear polynomials whose variable support fits inside the `--karn` Karnaugh
  cutoff are translated using Brickenstein's algorithm — enumerate the polynomial's satisfying
  points and emit a CNF that has exactly those satisfying assignments over the support
  variables.
- Larger non-linear polynomials fall back to a generic monomial-encoding: each monomial
  `m = x_1*x_2*...*x_k` gets a fresh CNF variable `y_m` linked by clauses to its factors, then
  the polynomial becomes a sum of `y_m`'s (in turn XOR-cut per `--cutnum`).

The observable contract is: the CNF is satisfiable iff the ANF is, and each ANF variable that
appears in both maps to the same CNF variable index (recorded in the solution-map trace).

The `--solmap` trace records enough to reconstruct a full original-ANF assignment from a CNF
solution: each ANF variable proven to a fixed value during simplification is recorded with that
boolean value, each variable eliminated by an equivalence is recorded together with the variable
it was proven equal to, and each variable that survives into the CNF is recorded with its CNF
variable index. The exact textual layout of each record is left to the implementation.

---

## Behaviour on ill-formed input

- A file containing only a bare closing parenthesis (or any grossly malformed polynomial) is
  rejected: `bosphorus` exits with a nonzero status. The exact stderr wording is
  implementation-defined; the observable contract is only that the process fails.
- Providing both `--anfread` and `--cnfread` prints
  `You cannot give both ANF/CNF files to read in` and exits with a nonzero status.
- Requesting `--cutnum` outside 3-10, `--karn` above 20, or `--xldeg` above 3 prints an
  `ERROR!` line and exits with a nonzero status.

Anything not documented above is unspecified; you may choose any sensible behaviour.
