# Jamal – A Java Macro Language

Implement a text macro processing library in Java.

Jamal expands macros delimited by configurable opening/closing strings (default `{` / `}`). Text outside macros passes through unchanged. Macros may be built-in (provided by the engine) or user-defined.

Target: Java 11+. No external dependencies.

## Build

- Packages: `javax0.jamal.api`, `javax0.jamal.engine`, `javax0.jamal.builtins`, `javax0.jamal.tools`
- Built-in macros are discovered via SPI (`META-INF/services/javax0.jamal.api.Macro`)
- Must build with Maven/Gradle – all tests must pass

## Entry Point

```java
import javax0.jamal.engine.Processor;

try (Processor p = new Processor("{", "}")) {
    String result = p.process(inputString);
}
```
The concrete, instantiable class constructed via `new Processor(open, close)` is `javax0.jamal.engine.Processor`; it implements the `javax0.jamal.api.Processor` interface (which is what `AutoCloseable` and the public methods below are declared on).

## Macro Language

### Invocation

- Built-in: `{@name ...}` – content passed verbatim, `{ #name ...}` – inner macros expanded first
- User-defined: `{name}` or `{name/arg1/arg2...}` – result is recursively processed
- `{!name}` – post-evaluate the result (repeatable: `{!!name}`, etc.)
- `{?name}` – tolerant: undefined → empty string, no error

With `#` the expansion pass covers the whole body between the delimiters, including the position where the built-in's name stands; the engine splits the expanded text into a macro name plus that macro's input only afterwards, so the name itself may be produced by expanding another macro (this is the "recursive macro construction" of Requirement 6). The scope a built-in macro establishes — `block`'s anonymous scope, for example — is nevertheless entered when the invocation starts, before its body is expanded, so a macro defined while the body is being expanded lives in that scope and is discarded when the invocation ends unless it is exported. With `@` the name is always taken literally.

### define

```
{@define name=value}
```
Output is empty. Subsequent `{name}` expands to `value`.

Parameters:
```
{@define f(a,b)=a+b}
{f/1/2}  --> 1+2
```
First non-alphanumeric character after the macro name is the argument separator. Single-parameter macros accept space-separated arguments.

Modifiers:
- `{@define ? a=val}` – define only if not already defined
- `{@define ! a=val}` – error if already defined
- `{@define ~ a=...}` / `{@define [verbatim] a=...}` – result is not re-evaluated
- `{@define [tail] x(a,b)=...}` – last parameter consumes remaining arguments
- `{@define [export] a=...}` – export to parent scope
- `{@define :g=...}` – define globally

A user-defined macro named `default` catches undefined macro references.

### Core built-in macros

- `options` – set named boolean flags, e.g. `{@options emptyUndef}`. Multiple flags are separated by `|` or whitespace (`{@options a|b|c}`); a leading `~` negates a flag (`{@options ~a}`). A flag is readable as a macro: `{name}` expands to `true` when the flag is set and `false` when it is unset or negated. Options are scoped. The built-in flag `emptyUndef` makes undefined macros expand to the empty string.
- `if` – conditional: `{@if /condition/then/else}`; the `else` field is optional. Separator is the first non-whitespace character. A bare `condition` is **false** when it is empty/whitespace-only, the literal `false` (case-insensitive), or the integer `0`; any other non-empty value (including non-zero numbers) is **true**. Modifiers: `[not]` negates the condition result; `[eval]` evaluates the condition as Jamal before testing its truthiness; `[isDefined]` is true iff the condition names a currently-defined macro; `[lessThan=N]` / `[greaterThan=N]` are true iff the condition, parsed as an integer, is `< N` / `> N`.
- `for` – loop: `{@for x in (a,b,c)=...}`. The list is split on commas; a multi-value item uses `|` to separate the values for a multi-variable loop (`{@for (x,y) in (a|1,b|2)=...}`). Iterations are concatenated with no separator by default. Options:
  - `[join=SEP]` – place `SEP` between iterations.
  - `[trim]` – strip leading/trailing whitespace from each value.
  - `[skipEmpty]` – drop empty items from the list before iterating.
  - `[lenient]` – do not require each item to supply exactly as many values as there are variables; missing values become empty strings.
  - `[evalist]` – evaluate/expand the parenthesized list expression first, then split the result into items.

  Multiple options may be combined within a single `[...]` bracket, separated by whitespace, e.g. `{@for [trim join=;] p in ( x , y )=p}` → `x;y`.
- `sep` – change the macro opening/closing delimiters. Surrounding whitespace in the argument is ignored; the remaining text is parsed as:
  - two characters `{@sep XY}` → open `X`, close `Y` (e.g. `{@sep []}` → `[` … `]`);
  - three characters `{@sep XsY}` → open `X`, close `Y`, where the middle character `s` separates them and must differ from both (e.g. `{@sep [ ]}` and `{@sep [/]}` → `[` … `]`);
  - two whitespace-separated tokens `{@sep OPEN CLOSE}` → the (possibly multi-character) open and close strings (e.g. `{@sep (( ))}` → `((` … `))`, `{@sep << >>}` → `<<` … `>>`);
  - a leading separator character `{@sepXopenXcloseX}` where the first character `X` fences the open and close strings (e.g. `{@sep/[/]}` → `[` … `]`).

  With no argument (`{@sep}` / `{#sep}`) the previously saved delimiters are restored.
- `eval` – evaluate content as Jamal.
- `comment` – discard content.
- `escape` – verbatim content with custom delimiter: `{@escape `|`...`|`}`. The end of an `escape` invocation is located by its custom closing delimiter, not by matching macro opening/closing delimiters: the escaped region is opaque to macro scanning, so it may contain macro delimiters in any number or order, including unbalanced ones.
- `block` – anonymous scope, result discarded. `[flat]` / `[export]` exports definitions.
- `begin` / `end` – named scopes with shadowing.
- `export` – move macro(s) to parent scope: `{@export a, b}`.
- `undefine` – remove a macro: `{@undefine name}`. Prefix `:` for global.
- `try` / `catch` – error handling:
  - `{@try ...}` – swallow error → empty
  - `{@try! ...}` – on failure return the error message (which names the offending macro); on success return the content
  - `{@try? ...}` – return `false` on failure, `true` on success
  - `{@catch ...}` – runs only if a preceding `try` caught an error; running a `catch` **consumes** that caught error, so a later `catch` with no new failing `try` produces empty output
- `ident` – return content unevaluated.

Other features: line continuation with a trailing `\` (the backslash and the following newline are removed), and recursive macro construction.

### Deferred evaluation (backtick)

A leading backtick before a macro name postpones its expansion by one evaluation pass: the reference is emitted with exactly **one** backtick removed, keeping its surrounding braces, and is **not** expanded on the current pass. Because only one backtick is removed per pass, a name carrying *N* leading backticks needs *N* passes before it expands. For example, given some macro `g`, a single-backtick reference `{`g}` emits `{g}` (the backtick is consumed and `g` is left unexpanded), and a double-backtick reference `{``g}` emits `{`g}` (one backtick removed, one still deferring `g`).

Each `{!name}` post-evaluation (repeatable: `{!!name}`) runs one further evaluation pass, peeling one deferral level, so a deferred reference is finally expanded once enough passes are applied. Deferral behaves the same at top level, inside macro bodies (a deferred reference stored in a body keeps its braces and is emitted one backtick lighter when the body is used, then expands once a further pass reaches it), and inside `eval` (which performs one pass).

## Public API

### Processor (interface `javax0.jamal.api.Processor`, concrete class `javax0.jamal.engine.Processor`)

- `String process(String in)` / `process(Input in)`
- `MacroRegister getRegister()`
- `define(Identified)` / `defineGlobal(Identified)`
- `separators(open, close)`
- `close()`

### Macro

```java
String evaluate(Input in, Processor processor) throws BadSyntax;
```
Discovered via SPI. `getId()` defaults to lowercase class name.

### Input

Mutable `CharSequence` with position tracking (file, line, column).

### BadSyntax

Checked exception for syntax errors.

### MacroRegister

- Macro lookup: built-in / user-defined
- `define` / `global` – register macros
- `export(id...)` – move to parent scope
- Scope push/pop, delimiter get/set

### UserDefinedMacro / Evaluable

- `evaluate(String... parameters)`
- `isVerbatim()`
- `expectedNumberOfArguments()`

## Requirements

1. Macro expansion must respect `@` (verbatim) vs `#` (pre-evaluate) built-in invocation, user-defined recursive evaluation, and `!` post-evaluation.
2. User-defined macros support parameters, tail parameters, verbatim mode, global scope (`:`), export, and `default` fallback.
3. All built-in macros (`define`, `options`, `if`, `for`, `sep`, `eval`, `comment`, `escape`, `block`, `begin`/`end`, `export`, `undefine`, `try`/`catch`, `ident`) must behave as described.
4. Scoping: inner scopes inherit outer macros; definitions do not leak unless exported. `begin`/`end` must match. Invoking a user-defined macro opens a scope for that invocation: its input (arguments / trailing content) is evaluated in that scope, and definitions made during that evaluation are visible to the macro body but are discarded when the invocation ends unless exported (this applies even to a macro with no declared parameters invoked with trailing content).
5. Undefined macro references throw `BadSyntax` unless `?` prefix, `default` macro, or `emptyUndef` option is active.
6. The engine must correctly handle delimiter changes, line continuation, and recursive macro construction.
7. All included tests must pass.
