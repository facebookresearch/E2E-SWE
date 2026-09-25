# icontract — Design-by-Contract for Python

Build `icontract`, a library that adds design-by-contract to Python through
decorators: preconditions, postconditions, and class invariants, with
**informative violation messages** that show the values of the offending
expression and its sub-expressions, and with **contract inheritance** that
follows the Liskov substitution principle.

## Dependencies

The environment is **offline**: all dependencies are **already installed** and
there is no network, so **do not install anything**. The project is installed
for you by a `setup.sh` that runs offline (it performs an editable install
against the pre-installed packages).

Still declare the runtime dependencies in your package metadata (e.g.
`install_requires`) so the offline editable install resolves them:
`asttokens>=2,<3` and `typing_extensions`. No system services are required.

`asttokens` is used to recover the *verbatim source text* of a contract
condition (see "Violation messages").

## Public API

Build a package named `icontract` that exposes the following at the top level
(`import icontract; icontract.require(...)`). The internal module layout is up to
you; only these top-level names are used:

- `icontract.require` — precondition decorator.
- `icontract.ensure` — postcondition decorator.
- `icontract.snapshot` — capture "old" state for postconditions.
- `icontract.invariant` — class-invariant decorator.
- `icontract.DBC` — base class enabling contract inheritance.
- `icontract.ViolationError` — exception raised on a contract violation.
- `icontract.InvariantCheckEvent` — `enum.Flag` of invariant check triggers
  (`CALL`, `SETATTR`, and `ALL = CALL | SETATTR`).

## Example usage

The decorators wrap ordinary functions, methods, and classes. A satisfied
contract is a silent no-op; a violated one raises `ViolationError` whose message
shows the condition source and the values that made it fail.

```python
import icontract

# Precondition: checked before the function body runs.
@icontract.require(lambda x: x < 5)
def f(x):
    return x

f(x=3)        # -> 3 (contract holds)
f(x=100)      # raises icontract.ViolationError: "x < 5: x was 100"

# Postcondition: `result` binds the return value.
@icontract.ensure(lambda result, x: result > x)
def increment(x):
    return x + 1

# Snapshot: capture "old" state for use as OLD in a postcondition.
@icontract.snapshot(lambda lst: lst[:])          # reachable as OLD.lst
@icontract.ensure(lambda OLD, lst: len(lst) == len(OLD.lst) + 1)
def append_one(lst):
    lst.append(42)

# Class invariant: must hold after __init__ and after every public method call.
@icontract.invariant(lambda self: self.x > 0)
class Counter:
    def __init__(self):
        self.x = 1
    def decrement(self):
        self.x -= 2                              # drives x below 0 -> violation

# Contract inheritance (Liskov): preconditions weaken, postconditions strengthen.
class Base(icontract.DBC):
    @icontract.require(lambda x: x % 2 == 0)
    def g(self, x): ...

class Derived(Base):
    @icontract.require(lambda x: x % 3 == 0)
    def g(self, x): ...

Derived().g(x=4)   # OK: satisfies Base's precondition (4 % 2 == 0)
Derived().g(x=9)   # OK: satisfies Derived's precondition (9 % 3 == 0)
Derived().g(x=5)   # raises ViolationError: satisfies neither
```

## Conditions

A *condition* is a callable returning a truthy/falsy value. icontract maps the
decorated function's arguments to the condition's parameters **by name**: a
condition only needs to declare the parameters it uses (e.g.
`lambda x: x > 0` for a function `f(x, y)`). The condition may also reference
names from the enclosing scope (globals/closures).

Special parameter names available to conditions:

- In `ensure` conditions, `result` binds the function's return value.
- In `ensure` conditions, `OLD` binds the snapshots captured by `snapshot`
  (see below); `invariant`/`require`/`ensure` conditions on methods receive
  `self`.

## Decorators

All four decorators accept `enabled` (default `__debug__`): when falsy, the
contract is not installed and adds no runtime overhead or checking.

`require`, `ensure`, and `invariant` also accept:
- `description` (optional str) — prepended to the violation message.
- `error` (optional) — either an exception instance/type, or a callable taking
  the same named arguments as the condition; when the condition fails, the
  result of `error` is raised *instead of* `ViolationError` (and no message is
  composed).
- `a_repr` (optional) — a `reprlib.Repr` instance that controls how
  sub-expression values are rendered in the violation message (see "Violation
  messages"). Defaults to a built-in `reprlib.Repr` whose size limits are raised
  well above the stdlib defaults (so typical collections/strings render in full
  rather than being truncated).

### `require(condition, description=None, a_repr=..., enabled=__debug__, error=None)`

Precondition. Before the wrapped function runs, the condition is evaluated
against the call arguments. If it is falsy, raise `ViolationError` (or the
custom `error`).

### `ensure(condition, description=None, a_repr=..., enabled=__debug__, error=None)`

Postcondition. After the wrapped function returns, the condition is evaluated
with `result` bound to the return value (and `OLD` if snapshots are present). If
falsy, raise `ViolationError` (or the custom `error`).

### `snapshot(capture, name=None, enabled=__debug__)`

Captures a value *before* the wrapped function executes, for use in an `ensure`
postcondition via `OLD`. `capture` is a callable of (a subset of) the function's
arguments. The captured value is exposed as `OLD.<name>`. If `name` is omitted,
it defaults to the single argument name that `capture` takes (e.g.
`snapshot(lambda lst: lst[:])` is reachable as `OLD.lst`). A `snapshot` must be
applied **above** (outer to) the `ensure` it feeds.

### `invariant(condition, description=None, a_repr=..., enabled=__debug__, error=None, check_on=InvariantCheckEvent.CALL)`

Class decorator. The condition takes `self`. The invariant is verified at the end
of `__init__` and, depending on `check_on`:
- `InvariantCheckEvent.CALL` (default): after every public method call.
- `InvariantCheckEvent.SETATTR`: whenever an instance attribute is assigned.
- `InvariantCheckEvent.ALL` (= `CALL | SETATTR`): on both of the above.

Multiple `invariant` decorators may be stacked; each is enforced independently.

`InvariantCheckEvent` is an `enum.Flag` with members `CALL`, `SETATTR`, and the
combined `ALL` (defined as `CALL | SETATTR`). All three appear in
`InvariantCheckEvent.__members__`.

## Violations and violation messages

`ViolationError` is a subclass of `AssertionError`.

When a condition fails (and no custom `error` is given), compose a message as
follows. (Tests strip a leading location line of the exact form
`File <path>, line <N> in <scope>:\n` that you should prepend to the message;
everything below is the text *after* that line.)

1. Start from the condition's **verbatim source text** (obtained via
   `asttokens`, so spacing/formatting matches exactly how the condition was
   written), optionally prefixed by `"<description>: "`.
2. Re-evaluate the condition's expression tree and collect the value of each
   relevant sub-expression, rendered as `<source-of-subexpression> was <repr>`
   using Python `repr` (so strings are quoted, bytes carry the `b` prefix, etc.).
   The values reported are:
   - For a **precondition**: every bound function argument, plus any other
     names/sub-expressions referenced by the condition (globals, attribute
     accesses, calls, subscripts, comprehension results, …).
   - For a **postcondition**: `result`, **every bound function argument** (not
     only the ones the condition references — same rule as the precondition),
     and the `OLD` snapshots (`OLD` itself renders as `a bunch of OLD values`,
     and each `OLD.<name>` is shown). For a **method**, this means `self` is
     always reported, even when the condition does not mention it.
   - For an **invariant**: `self` and the referenced `self.<attr>` /
     `self.<method>()` values.
3. **Layout:** if there is exactly one value to report, render it inline as
   `<condition>: <expr> was <repr>`. Otherwise render
   `<condition>:` then one `\n`-separated line per value, the value lines
   **sorted by their source text using Python's default string ordering**
   (i.e. `sorted(lines)` — codepoint order, so uppercase letters sort before
   lowercase ones, e.g. `OLD`/`OLD.lst` sort before `len(...)`/`lst`).

### Sub-expression recomputation specifics

The re-evaluation reports intermediate values, not just leaf names. For example:
- `sum([1, y, x]) > 10` reports `sum([1, y, x]) was 5`, `x was 3`, `y was 1`.
- A call `x > y()` reports `y() was 1` (the call's result), **not** the callee
  `y` itself.
- An attribute `p.a > 0` reports `p was <repr>` and `p.a was <repr>`.
- A method call `self.is_valid()` reports `self was <repr>` and
  `self.is_valid() was <repr>` (the call's result), **not** the bound-method
  callee `self.is_valid` — see the callee-suppression rule below.
- A list comprehension reports the built list, e.g.
  `[item > 0 for item in lst] was [True, False, True]`.
- A **generator expression** that is consumed by `all`/`any` reports a
  counterexample rather than the generator object, in the form:
  `all(item > 0 for item in lst) was False, e.g., with` then a line
  `  item = -2` naming the first element for which it failed.
- f-strings, dict/set comprehensions, and subscripts also get their own
  `<expr> was <repr>` line.

**Which nodes get a value line.** Only these sub-expression kinds are reported
as `<source> was <repr>`: names (leaves), attribute accesses, calls,
subscripts, comprehensions (the built collection together with its iterable /
input sub-values), and f-strings (plus the generator-counterexample form
above). Pure operator nodes — unary, binary, and boolean operators
(`-x`, `x + y`, `x and y`, etc.) — and conditional expressions
(`a if c else b`) do **not** each get their own line, nor do comparisons at
any depth (including the top-level comparison being checked). Value lines are
keyed by their source text, so a sub-expression occurring several times in a
condition still yields a single line.

**Callee suppression.** When a name or an attribute access is itself the
callee (the function being invoked) of a call that is already reported, that
callee node does **not** get its own value line — only the call's result is
reported. So `x > y()` reports `y() was 1` but never a line for `y`, and an
invariant `self.is_valid()` reports `self was <repr>` and
`self.is_valid() was <repr>` but never a line for the intermediate bound-method
`self.is_valid`. (A data-attribute used directly as an operand, e.g. `p.a` in
`p.a > 0` or `self.x` in `self.x > 0`, is **not** a callee and **is** reported.)

Because object reprs are used, instances appearing in messages (e.g. `self`)
render via their `__repr__`.

## Contract inheritance (`DBC` / `DBCMeta`)

Classes deriving from `icontract.DBC` (which is built on a metaclass) inherit and
combine contracts across the hierarchy following Liskov substitution:

- **Preconditions weaken.** An overriding method's precondition is OR-ed with the
  inherited preconditions: the call is admitted if *any* of them holds. When a
  call satisfies none of them, the violation reports the overriding (subclass's
  own) precondition.
- **Postconditions strengthen.** All inherited and own postconditions must hold
  (logical AND).
- **Invariants strengthen.** A subclass enforces its own and all inherited
  invariants.
- **Snapshots are inherited** along with the postconditions that use them.
- `DBC` composes with `abc`: a subclass with an `abc.abstractmethod` cannot be
  instantiated (raises `TypeError`), as usual.

## Async support

The decorators also support `async def` functions: preconditions are checked
before awaiting, postconditions after the result is awaited, and conditions may
themselves be coroutine functions (which are awaited). The composed violation
messages are identical to the synchronous case.
