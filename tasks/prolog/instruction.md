# Implement a Prolog interpreter

## What you are building

You are implementing a **Prolog interpreter** in pure Java. Prolog is a logic-programming language: a
*program* is a set of facts and rules (clauses), and a *query* is a goal that the interpreter tries to
prove against the program, producing zero, one, or many **solutions** (each solution being an
assignment of the query's variables). Your job is to consult a program and evaluate a query, returning
its solutions.

Support the standard core of Prolog: unification, clause resolution with **backtracking**, the cut,
conjunction, disjunction, negation and if-then-else, arithmetic evaluation and comparison, term
inspection and construction, type checks, the common list predicates, database update
(`assert`/`retract`), and standard order of terms — all following the usual Prolog conventions.

## The exact interface you must implement

Create the class **`com.wrg.prolog.PrologEngine`** (under `/app/src/com/wrg/prolog/`) with a public
no-argument constructor and this method:

```java
package com.wrg.prolog;

public class PrologEngine {
    /**
     * @param program the Prolog source to consult (clauses; lines beginning with % are comments).
     * @param query   a single Prolog goal to solve (without the trailing period).
     * @return the query's solutions serialized in the canonical form described below, or the bare
     *         5-character string ERROR (no surrounding quotes) if consulting the program or
     *         executing the query raises any error.
     */
    public String solve(String program, String query) {
        // ...
    }
}
```

The grader calls `solve` once per test case, each with a freshly constructed `PrologEngine`, so a
call is self-contained. There is no interactive input and no file/network I/O.

## Consulting a program

A consulted program is a sequence of clauses (facts and rules); lines beginning with `%` are
comments. Two further behaviors affect what a query can observe:

- **Directives.** A program may also contain *directive* lines written `:- Goal.` or `?- Goal.`.
  A directive is executed as a goal at consult (load) time rather than stored as a clause — for
  example, a program containing `?- assert(foo(1, 2)).` runs that goal while loading, so the fact
  `foo(1, 2)` is present by the time the query is evaluated.
- **Undefined predicates.** Calling a predicate the program does not define is **not** an error:
  it simply fails (contributes no solutions), so a query whose goal is undefined returns `false`.
  The `ERROR` result is reserved for a genuine parse error in the program or an error raised
  while evaluating the query itself (e.g. an arithmetic evaluation error).

## Output: the canonical solution format

Evaluate the query against the program and enumerate **all** solutions in order:

- For each solution, take the query's variables in **ascending alphabetical order** by name and print
  `Name=Term` for each, joined by `", "` (comma then space). Example: `X=1, Y=2`.
- If the query has **no variables** and succeeds, that solution is the single word `true`.
- Print one solution per line, separated by `\n`, in solution order.
- If the query has **no solutions**, return exactly `false`.
- If consulting the program or running the query raises any error, return exactly `ERROR` — the
  bare 5-character string, no surrounding quotes (the specific error is not checked).

**Term formatting** (match these conventions exactly):

- **Atoms** are written as-is, unquoted — even when they contain spaces or would normally need quotes:
  `'hello world'` prints as `hello world`.
- **Numbers**: integers `42`, `-5`; floats `3.14`. A float is printed in the shortest decimal form
  that round-trips to the same value and **always keeps a decimal point**, so a whole-valued float
  prints as e.g. `11.0` (never `11`).
- **Compound terms**: `functor(arg1, arg2, ...)` with `", "` between arguments — `f(1, 2, 3)`,
  `point(1, 2)`.
- **Operators are written infix with a single space on each side**: `1 + 2`, `a - b * c`,
  `a :- b , c`, `1 ; 2`. (This applies to the standard operators, e.g. `+ - * / =`, `,`, `;`, `:-`.)
  The infix form applies to an operator used at its standard **binary** arity; an operator atom used
  at any other arity (e.g. a unary `+`, or the comma `,` at arity 1) is written in canonical
  functional form `functor(arg, ...)`.
- The reader and writer use the **usual standard (SWI-flavored) operator table** — the conventional
  priorities and associativities — not only the operators shown above. One deviation from that
  table you must adopt: the module-qualifier `:` is `xfy` at priority 200, binding **tighter** than
  `/`.
- **Parentheses are added around an operand only when needed** to preserve operator
  priority/associativity, so the printed term re-reads as the same term; otherwise they are
  omitted — `a - b * c` needs none.
- This parenthesization concerns only the **operands of an operator** (an operator expression
  nested inside another operator expression). An operator term appearing directly as an **argument
  of a compound term** is written in its bare infix form with **no** extra enclosing parentheses —
  even though re-reading it in isolation would regroup the compound's arguments.
- **Lists** use bracket notation with `,` and **no spaces** between elements, and `|` before a
  non-nil tail: `[1,2,3]`, `[a,b|c]`. (List *elements* that are compound terms keep the compound
  spacing, e.g. `[point(1, 2),point(1, 2)]`.)

Every test's query binds its variables to fully ground terms (or simply succeeds/fails), so you do
not need to print unbound variables. A case passes when your serialized output matches the expected
output exactly (a trailing newline is ignored).

Examples (program `▸` query `▸` result):

| program | query | `solve` returns |
|---|---|---|
| (empty) | `X is 1 + 2` | `X=3` |
| (empty) | `atom(a)` | `true` |
| (empty) | `atom(1)` | `false` |
| (empty) | `member(X, [a,b,c])` | `X=a`⏎`X=b`⏎`X=c` |
| (empty) | `append(X, Y, [a,b])` | `X=[], Y=[a,b]`⏎`X=[a], Y=[b]`⏎`X=[a,b], Y=[]` |
| `p(1). p(2).` | `p(X)` | `X=1`⏎`X=2` |
| (empty) | `X = f(1,2)` | `X=f(1, 2)` |

(⏎ marks the newline separator between solutions.)

## Arithmetic

- Integers are **64-bit signed** (Java `long`, two's-complement). Arithmetic that overflows wraps
  around, so the maximum integer `9223372036854775807` plus `1` is `-9223372036854775808`.
- `/` applied to two integers yields an **integer when the division is exact**, otherwise a float;
  `//` is integer division (rounding toward zero).

## How it is built and run

- Put your Java source under **`/app/src/`**, in package `com.wrg.prolog`.
- Create **`/app/setup.sh`** that compiles your sources into `/app/out`, e.g.:
  ```bash
  mkdir -p /app/out
  find /app/src -name '*.java' -print0 | xargs -0 javac -d /app/out
  ```
  Use **only the standard JDK**. Implement the Prolog reader (tokenizer + operator-precedence parser),
  the unification/resolution engine, and the builtin predicates yourself — do not use any third-party
  Prolog or logic-programming library.

## Scope

Implement as much of standard Prolog as you can — the grader runs a broad behavioral suite spanning
unification and backtracking, the control constructs, arithmetic, term/type builtins, list
predicates, the all-solutions predicates, and database update. Each case is scored independently, so a
partial implementation earns credit for every case it handles: getting resolution + backtracking, the
core control constructs, and the common builtins right already scores well, and breadth across the
long tail of builtin predicates raises the score further.

Alongside the standard `repeat/0`, support the bounded **`repeat/1`**: `repeat(N)` succeeds and, on
backtracking, re-succeeds a total of `N` times (`repeat(0)` and negative counts fail; an unbound
argument raises an error).
