# Implement a jq processor

## What you are building

You are implementing a **jq processor** in pure Java. `jq` is a small, Turing-complete **query and
transformation language for JSON**: a program takes one JSON value as input (referred to as `.`) and
produces a *stream* of zero, one, or many JSON values as output. Your job is to parse a jq program,
run it against a JSON input value, and return the output stream.

Target the **jq 1.6** language and its standard builtin library. If you are unsure how a construct or
builtin should behave, match what the `jq` 1.6 command-line tool does.

The target is **strictly jq 1.6** — not a later version. Any name jq 1.6 does not define, and any
syntax jq 1.6 does not accept, must raise an error, so `evaluate` returns `"ERROR"`. Implementing a
*superset* of jq (builtins or grammar from a newer jq release) is not rewarded: the suite expects
jq-1.6 behavior, so a program jq 1.6 rejects must error rather than produce a value.

## The exact interface you must implement

Create the class **`com.wrg.jq.JqEngine`** (under `/app/src/com/wrg/jq/`) with a public no-argument
constructor and this method:

```java
package com.wrg.jq;

public class JqEngine {
    /**
     * @param program   the jq program to run.
     * @param inputJson the JSON text of the single input value the program runs against (the `.`).
     * @return the program's output stream, serialized as described below; or the exact string
     *         "ERROR" if the program raises ANY error (a compile/parse error or a runtime error).
     */
    public String evaluate(String program, String inputJson) {
        // ...
    }
}
```

The grader calls `evaluate` once per test case, each with a freshly constructed `JqEngine`, so a call
must be self-contained. Every program runs against exactly one input value; there is no additional
input stream, no environment/`$ENV`, no modules or `import`, and no file/network I/O.

## Output format

A jq program produces a **stream** of output JSON values. Serialize the output exactly as the `jq`
command-line tool does with the **`-c` (compact)** flag:

- Each output value is printed as **compact JSON** — no insignificant whitespace (`{"a":1,"b":[2,3]}`).
- Multiple output values are **separated by a newline** (`\n`), in the order produced. Zero output
  values → the empty string; a single value → just that value.
- **Object keys keep their order** (jq preserves order; it does not sort keys unless the program does).
- **Strings**: standard JSON string escaping — `\"`, `\\`, `\b`, `\f`, `\n`, `\r`, `\t` are emitted as
  their two-character escapes, and any *other* control character (U+0000–U+001F) as `\u00XX`;
  non-ASCII characters are emitted **literally as UTF-8** (not `\u`-escaped); `/` is **not** escaped.
- **Numbers**: formatted the way jq prints them — integral values without a decimal point (`2`, `-7`,
  `10`), non-integral values in jq's canonical shortest form (`1.5`, `0.1`); e.g. `1e3` prints as `1000`.
- **Booleans / null**: `true`, `false`, `null`.

A case passes when your serialized output matches the expected output exactly (a trailing newline is
ignored). If running the program raises any error — a parse/compile error, or a runtime error such as
indexing a number, dividing by zero, or an explicit `error(...)` — return exactly `"ERROR"`. The
specific error message is **not** checked.

Examples (input `▸` program `▸` result):

| input | program | `evaluate` returns |
|---|---|---|
| `null` | `1 + 2` | `3` |
| `{"a":1,"b":2}` | `.a` | `1` |
| `[1,2,3]` | `.[]` | `1`⏎`2`⏎`3` |
| `[1,2,3]` | `map(.*2)` | `[2,4,6]` |
| `{"b":2,"a":1}` | `.` | `{"b":2,"a":1}` |
| `[3,1,2]` | `sort` | `[1,2,3]` |
| `"a,b,c"` | `split(",")` | `["a","b","c"]` |
| `null` | `[range(3)]` | `[0,1,2]` |
| `{"x":1}` | `.y.z` | `null` |
| `1` | `. + "x"` | `ERROR` |

(⏎ marks the newline separator between stream values.)

## Builtin notes

Builtins behave as in jq 1.6. One detail worth pinning explicitly: `from_entries` reads each entry's
**key** from the first present of the field names `key`, `Key`, `name`, `Name`, and its **value** from
the first present of `value`, `Value` (an entry with no value field yields `null`).

Comparison and ordering follow jq 1.6's fixed **total order across value types** (match the `jq` 1.6
command-line tool): `null < false < true < numbers < strings < arrays < objects`. Within a type,
numbers compare numerically, strings by Unicode code point, arrays lexicographically (element by
element), and objects by their sorted key arrays first and then by the values at those keys. This
order governs the comparison operators (`<`, `<=`, `>`, `>=`, `==`, `!=`) and the ordering builtins
(`sort`, `sort_by`, `unique`, `min`/`max`, `min_by`/`max_by`, `group_by`), so a mixed-type array
sorts into that cross-type sequence rather than erroring.

Indexing and slicing coerce their bounds as jq 1.6 does: a non-integer numeric array/string index or
slice bound is truncated to an integer toward negative infinity; an out-of-range index or bound is
clamped to the valid range (a negative bound counts from the end, clamping no lower than `0`); and a
`NaN` slice bound yields an empty result.

`ltrimstr`/`rtrimstr` strip a matching leading/trailing substring, but are lenient about types: if the
input value or the prefix/suffix argument is not a string, they return the input **unchanged** (no
error).

Mind the version boundary. The following were added in jq versions *after* 1.6, so they are **not**
defined in jq 1.6 and calling them must raise an error (→ `"ERROR"`): `abs`, `toboolean`, `pick`,
`trim`/`ltrim`/`rtrim`, `skip`, `have_decnum`, and the one-argument `add(filter)` form (jq 1.6's `add`
takes no argument). Grammar is 1.6 too: an `if`/`elif` chain **must** end with an `else` branch, so a
bare `if … then … end` with no `else` is a parse error (→ `"ERROR"`). jq's reserved keywords (`if`,
`then`, `else`, `elif`, `end`, `and`, `or`, `as`, `def`, `reduce`, `foreach`, `try`, `catch`, `label`,
`import`, `include`, `module`) remain valid as **bareword object keys** in `{...}` construction (e.g.
`{if:0,and:1}` builds an object with keys `"if"` and `"and"`), even though they may not be used as
`$`-variable or label names.

## How it is built and run

- Put your Java source under **`/app/src/`**, in package `com.wrg.jq`.
- Create **`/app/setup.sh`** that compiles your sources into `/app/out`, e.g.:
  ```bash
  mkdir -p /app/out
  find /app/src -name '*.java' -print0 | xargs -0 javac -d /app/out
  ```
  Use **only the standard JDK**. There is no JSON library on the classpath, so implement JSON parsing
  and serialization yourself, and implement the jq language yourself — do not use any third-party jq,
  JSON, or query library.

## Scope

Implement as much of jq as you can — the grader runs a broad behavioral suite spanning jq's operators,
control-flow constructs, path expressions, and builtin functions. Each case is scored independently, so
a partial implementation earns credit for every case it handles: getting the core language and the
common builtins right already scores well, and breadth across the long tail raises the score further.
"Breadth" means covering more of jq **1.6**; do not add constructs from newer jq versions (see the
version-boundary note above), since the suite expects those to error.
