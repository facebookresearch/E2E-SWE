# returns — Typed Functional Programming Containers for Python

Implement `returns`, a Python library providing typed monadic containers for functional programming. The library enables composable error handling, dependency injection, and async operations through container types that enforce explicit control flow.

## Dependencies

The environment is **offline** — all dependencies are already installed and you must not install
anything. The project is installed for you by a `setup.sh` that runs offline (editable install
against the pre-baked packages); do not run `pip install` yourself.

- Python 3.10+
- `typing-extensions` (the only runtime dependency — already installed)
- No other runtime dependencies

## Package Structure

All public APIs are importable from submodules of the `returns` package (e.g., `from returns.result import Success`). The package name is `returns`.

---

## 1. Result Container (`returns.result`)

Represents computations that may succeed (`Success(value)`) or fail (`Failure(error)`). `Result` is the abstract base class; `Success` and `Failure` are its concrete subclasses.

Both `Success` and `Failure` support the standard monadic interface: `map`, `bind`, `apply`, `alt`, `lash`, `swap`, `unwrap`, `failure`, `value_or`. They also support `do`-notation via generator expressions for composing multiple Results with short-circuiting. Class methods: `Result.from_value`, `Result.from_failure`, `Result.from_result`, `Result.do`.

**Do-notation call form and iteration contract** (shared by `Result.do`, `Maybe.do`, and `IO.do`): `X.do(...)` takes a **generator expression whose `for`-clauses iterate the containers themselves** — e.g. `Result.do(x + y for x in Success(1) for y in Success(2)) == Success(3)`. Iterating a success/present container (`for x in Success(v)` / `for x in Some(v)` / `for x in IO(v)`) yields its single inner value once; encountering a failure/empty container short-circuits the whole expression so `X.do(...)` evaluates to that failed/empty container (e.g. `Result.do(x + y for x in Success(1) for y in Failure('e')) == Failure('e')`). The result is re-wrapped in the same container type (`Result.do → Result`, `Maybe.do → Maybe`, `IO.do → IO`).

The `apply` method takes a *function container*: `container.apply(func_container)` applies the function held in `func_container` to the value in `container`. This is the applicative signature used by every container's `apply` throughout this spec.

The `lash` method is the **failure-track counterpart of `bind`** (it is `bind` on the error channel), used by every fallible container listed in this spec (`Result`, `Maybe`, `IOResult`, `FutureResult`, and the `RequiresContext*` family). `container.lash(function)`: on a failure/empty container, calls `function(failure_value)` and returns the **container it produces** (which may itself be a success — `lash` is the primary recovery combinator); on a success/present container, returns the container unchanged without calling `function`. So `Failure('e').lash(lambda e: Success(0)) == Success(0)`, `Success(1).lash(lambda e: Success(0)) == Success(1)`, and `Nothing.lash(lambda _: Some('d')) == Some('d')` while `Some(5).lash(...) == Some(5)`. (Contrast with `alt`, which *maps* the failure value rather than returning a new container.)

Containers are comparable (`Success(1) == Success(1)`), hashable, picklable, and support structural pattern matching (`match container: case Success(value): ...`).

`repr(Success(1))` returns `'<Success: 1>'`. `repr(Failure("err"))` returns `'<Failure: err>'`.

### Decorators

- **`safe`** — Catches exceptions and wraps them in `Failure`. Supports `@safe` (catches all `Exception`) or `@safe(exceptions=(ExceptionType,))` to catch specific types.
- **`attempt`** — Catches exceptions but wraps the *input argument* (not the exception) in `Failure`.

---

## 2. Maybe Container (`returns.maybe`)

Represents computations that may return nothing. `Some(value)` for present values, `Nothing` for absence. `Nothing` is a module-level singleton constant (`Maybe.empty`).

Standard interface: `map`, `bind`, `apply`, `lash`, `value_or`, `unwrap`, `failure`. Additional methods: `bind_optional` (calls a function returning `value | None`, converting `None` to `Nothing`), `or_else_call` (the lazy-factory counterpart of `value_or`; see below). Class methods: `Maybe.from_value` (always wraps, even `None`), `Maybe.from_optional` (`None` → `Nothing`), `Maybe.do` (do-notation over generator expressions, using the shared call form and iteration contract described in §1).

`or_else_call(factory)` returns a **raw value** (never a `Maybe`): on `Some(value)` it returns the unwrapped inner `value` (it does **not** call `factory`); on `Nothing` it calls the zero-argument `factory` and returns its result.

`bool(Some(x))` is always `True` (even `Some(None)`). `bool(Nothing)` is `False`.

`repr(Some(42))` returns `'<Some: 42>'`. `repr(Nothing)` returns `'<Nothing>'`.

Supports structural pattern matching.

### Decorator

- **`maybe`** — Wraps a function's return through `Maybe.from_optional`, converting `None` returns to `Nothing`.

---

## 3. IO Container (`returns.io`)

Marks impure computations. `IO(inner_value)` wraps a value to indicate side effects.

Standard interface: `map`, `bind`, `apply`. Also: `IO.from_value`, `IO.from_io`, `IO.from_ioresult`, `IO.do` (do-notation over generator expressions, using the shared call form and iteration contract described in §1).

`IO.from_ioresult(ioresult)` converts an `IOResult` back into a plain `IO` — the inverse of `IOResult.from_typecast`.

`repr(IO(1))` returns `'<IO: 1>'`.

### Decorator

- **`impure`** — Wraps the return value in `IO`.

---

## 4. IOResult Container (`returns.io`)

Combines `IO` with `Result` — for impure computations that may fail. `IOResult` is the abstract base class; `IOSuccess` and `IOFailure` are its concrete **subclasses** (classes, not factory functions — analogous to `Success`/`Failure` for `Result`), constructed as `IOSuccess(value)` / `IOFailure(error)`. Because they are classes, instances work with `isinstance(x, IOFailure)` and with structural pattern matching (`case IOSuccess(...)`).

Standard interface: `map`, `bind`, `apply`, `alt`, `lash`, `swap`. Also: `bind_result` (function returns `Result`), `bind_io` (function returns `IO`), `bind_ioresult` (alias for `bind`), `compose_result` (function receives the inner `Result` — i.e. it is called for both success and failure states — and returns an `IOResult`).

`unwrap()` and `failure()` return `IO`-wrapped values. `value_or(default)` returns `IO(value)` or `IO(default)`.

Class methods: `IOResult.from_result(result)` wraps an existing `Result` (`Success`→`IOSuccess`, `Failure`→`IOFailure`); `from_value(v)` → `IOSuccess(v)`; `from_failure(e)` → `IOFailure(e)`; `from_io(IO(v))` → `IOSuccess(v)`; `from_failed_io(IO(e))` → `IOFailure(e)`; `from_typecast(IO(result))` wraps an `IO[Result]` as an `IOResult`; `from_ioresult(ioresult)` is identity.

`str(IOSuccess(1))` returns `'<IOResult: <Success: 1>>'`.

Supports structural pattern matching. Note: `IOSuccess` wraps a `Result` internally, so pattern matching works as `case IOSuccess(Success(value)): ...`.

### Decorator

- **`impure_safe`** — Like `safe` but wraps in `IOResult`. Supports `@impure_safe` and `@impure_safe(exceptions=(...))`.

---

## 5. Future Container (`returns.future`)

Wraps async computations. When awaited (via `.awaitable()`), returns `IO[value]`.

A `Future` is reusable: a single `Future` may be derived from (e.g. via several `.map` calls) and each derivation awaited, even though awaiting evaluates the underlying coroutine. The first await runs the coroutine and its result is cached, so the coroutine body executes exactly once no matter how many derived containers are awaited.

Interface: `map`, `bind`, `apply`, `bind_io`, `bind_awaitable` (async function returning plain value), `bind_async` (async function returning `Future`). Class methods: `Future.from_value`, `Future.from_io`, `Future.from_future`, `Future.from_future_result` (downgrades a `FutureResult[a, b]` to a `Future[Result[a, b]]`), `Future.do` (async do-notation using `async for`).

`Future.do(async_gen)` is the async analogue of the do-notation contract in §1: it takes an **async generator expression whose `async for`-clauses iterate `Future` containers directly** — `async for a in Future.from_value(10)` yields the future's resolved inner value once. `Future.do(...)` returns a **`Future` synchronously** (not a coroutine), so it can be `.map`/`.bind`/`.awaitable()`'d like any other `Future`; awaiting it yields `IO(<combined value>)`.

### Decorators

- **`future`** — Wraps an `async def` to return `Future`.
- **`asyncify`** — Wraps a sync function to return a coroutine.

### `async_identity(value)` — Async function that returns its argument unchanged.

---

## 6. FutureResult Container (`returns.future`)

Wraps async computations that may fail. When awaited, returns `IOResult`.

Interface: `map`, `bind`, `apply`, `alt`, `lash`, `swap`, `bind_result`, `bind_io`, `bind_ioresult` (function returns `IOResult`), `bind_future` (function returns `Future`), `bind_awaitable` (async function returning a plain value), `bind_async` (async function returning a `FutureResult`), `compose_result` (function receives the inner `Result` and returns a `FutureResult`).

Class methods: `FutureResult.from_value`, `FutureResult.from_failure`, `FutureResult.from_result`, `from_io` (successful `IO` → success), `from_failed_io` (`IO` → failure), `from_ioresult`, `from_future` (successful `Future` → success), `from_failed_future` (`Future` → failure), `from_typecast` (wraps a `Future[Result]`).

Module-level unit helpers: `FutureSuccess(value)` ≡ `FutureResult.from_value(value)`; `FutureFailure(error)` ≡ `FutureResult.from_failure(error)`.

### Decorator

- **`future_safe`** — Like `safe` but for async functions, wrapping in `FutureResult`.

---

## 7. RequiresContext Container (`returns.context`)

Wraps a function `deps -> value`, enabling typed dependency injection and lazy evaluation.

`RequiresContext(function)` — callable with `(deps)` to evaluate. Interface: `map`, `bind`, `apply`, `modify_env` (transforms deps before passing to inner function). Class methods: `RequiresContext.from_value`, `RequiresContext.ask()` (returns a context that yields the dependencies themselves).

`RequiresContext.no_args` is a **class attribute** (a sentinel constant, not a method): pass it as the `deps` argument when evaluating a container built via `from_value`/`from_*` that ignores its dependencies. This same `no_args` attribute exists on all `RequiresContext*` containers below.

---

## 8. RequiresContextResult Container (`returns.context`)

Combines `RequiresContext` with `Result` — context-dependent computation that may fail. The wrapped function takes deps and returns a `Result`.

Interface: `map`, `bind` (function returns another `RequiresContextResult`), `bind_result` (function returns a `Result`), `bind_context` (function returns a `RequiresContext`), `bind_context_result` (function returns a `RequiresContextResult`; alias of `bind`), `apply`, `alt`, `lash`, `swap`, `modify_env` (adapts deps). Class methods: `from_value`, `from_failure`, `from_result` (lifts a `Result`), `ask()` (yields deps wrapped in `Success`). `no_args` class attribute as in §7.

---

## 9. RequiresContextIOResult Container (`returns.context`)

Combines `RequiresContext` with `IOResult` — context-dependent impure computation that may fail. The wrapped function takes deps and returns an `IOResult`.

Import: `from returns.context import RequiresContextIOResult`

Interface: `map`, `bind` (function returns another `RequiresContextIOResult`), `bind_result` (returns a `Result`), `bind_io` (returns an `IO`), `bind_ioresult` (returns an `IOResult`), `bind_context` (returns a `RequiresContext`), `apply`, `alt`, `lash`, `swap`, `compose_result` (function receives the inner `Result` and returns a `RequiresContextIOResult`), `modify_env`. Class methods: `from_value` (returns `IOSuccess`), `from_failure` (returns `IOFailure`), `from_result`, `from_io` (success), `from_failed_io` (failure), `from_ioresult`, `ask()` (yields deps wrapped in `IOSuccess`). `no_args` class attribute as in §7.

---

## 10. RequiresContextFutureResult Container (`returns.context`)

Combines `RequiresContext` with `FutureResult` — context-dependent async computation that may fail. The wrapped function takes deps and returns a `FutureResult`.

Import: `from returns.context import RequiresContextFutureResult`

`RequiresContextFutureResult(function)` — callable with `(deps)` returning `FutureResult`. Interface: `map`, `lash`, `swap`, `alt`, `apply`, `bind` (function returns another `RequiresContextFutureResult`), `bind_result` (returns a `Result`), `bind_io` (returns an `IO`), `bind_ioresult` (returns an `IOResult`), `bind_future` (returns a `Future`), `bind_future_result` (returns a `FutureResult`), `bind_awaitable` (async function returning a plain value), `bind_async` (async function returning a `RequiresContextFutureResult`), `compose_result` (function receives the inner `Result` and returns a `RequiresContextFutureResult`), `modify_env`. Class methods: `from_value`, `from_failure`, `from_result`, `from_io`, `from_ioresult`, `from_future`, `from_future_result`, `ask()` (yields deps wrapped in a successful `FutureResult`). `no_args` class attribute as in §7.

---

## 11. Pointfree Functions (`returns.pointfree`)

Lift operations to work with any compatible container:

- `map_(function)` — `map_(f)(container)` ≡ `container.map(f)`
- `bind(function)` — `bind(f)(container)` ≡ `container.bind(f)`
- `alt(function)` — `alt(f)(container)` ≡ `container.alt(f)`
- `lash(function)` — `lash(f)(container)` ≡ `container.lash(f)`
- `apply(func_container)` — `apply(fc)(vc)` ≡ `vc.apply(fc)`
- `cond(container_type, success_value[, error_value])` — Creates container from boolean. For `Result`: needs both values. For `Maybe`: only success value (False → `Nothing`).
- `bimap(on_success, on_failure)` — `bimap(f, g)(c)` ≡ `c.map(f).alt(g)`.
- `unify(function)` — Like `bind` but widens the error-type union; `unify(f)(c)` ≡ `c.bind(f)`.
- `bind_result(function)` — `bind_result(f)(c)` ≡ `c.bind_result(f)` (function returns a `Result`).
- `bind_io(function)` — `bind_io(f)(c)` ≡ `c.bind_io(f)` (function returns an `IO`).
- `bind_ioresult(function)` — `bind_ioresult(f)(c)` ≡ `c.bind_ioresult(f)`.
- `compose_result(function)` — `compose_result(f)(c)` ≡ `c.compose_result(f)`.
- `bind_optional(function)` — `bind_optional(f)(c)` ≡ `c.bind_optional(f)` (for `Maybe`).
- `bind_future(function)` — `bind_future(f)(c)` ≡ `c.bind_future(f)`.
- `bind_awaitable(function)` — `bind_awaitable(f)(c)` ≡ `c.bind_awaitable(f)` (async function returning a plain value).
- `bind_async(function)` — `bind_async(f)(c)` ≡ `c.bind_async(f)` (async function returning a container).
- `bind_context(function)` — `bind_context(f)(c)` ≡ `c.bind_context(f)` (function returns a `RequiresContext`).
- `modify_env(function)` — `modify_env(f)(c)` ≡ `c.modify_env(f)`.

Each pointfree function delegates to the same-named method on the container, so it works for any container that implements that method.

---

## 12. Pipeline Utilities (`returns.pipeline`)

- **`flow(value, *functions)`** — Eagerly applies functions left to right.
- **`pipe(*functions)`** — Creates a reusable pipeline (lazy `flow`).
- **`is_successful(container)`** — Returns `True` for success containers (`Success`, `Some`, `IOSuccess`).
- **`managed(use, release)`** — Resource management. Returns a callable that takes an `IOResult` (acquire). On success: calls `use(resource)` → gets result → calls `release(resource, result)` → returns the use result. If acquire fails, use and release are skipped. If release fails, its failure is returned instead of the use result. The `release` function receives the resource and the use `Result` (not `IOResult`).

---

## 13. Converters (`returns.converters`)

- `result_to_maybe(result)` — `Success(x)` → `Some(x)`, `Failure(x)` → `Nothing`. Note: `Success(None)` → `Some(None)`.
- `maybe_to_result(maybe[, default_error])` — `Some(x)` → `Success(x)`, `Nothing` → `Failure(None)` or `Failure(default_error)`.
- `flatten(container)` — Flattens nested container via `bind(identity)`. `Failure(Failure(x))` does NOT flatten.

---

## 14. Curry (`returns.curry`)

- **`curry(function)`** — Automatic currying. A curried function can be called with fewer arguments than required, returning a new function awaiting the rest. Supports keyword arguments, keyword-only args, `*args`, and `**kwargs`. Raises `TypeError` on wrong, excess, or **unknown-keyword** arguments. A function whose parameters are **purely variadic** (only `*args`, with no required positional parameters) has no fixed arity and therefore **cannot be partially applied** — any call invokes it immediately (e.g. a `*args`-only sum returns its result on the very first call, including the zero-argument call; a second call on that already-computed result is just a normal call on the returned value). Preserves the original function's docstring. Partial application results are immutable (earlier calls don't affect later calls).
- **`partial(function, *args, **kwargs)`** — Typed wrapper around `functools.partial`.

---

## 15. Trampolines (`returns.trampolines`)

Stack-safe recursion. Instead of a recursive call, a `@trampoline`-decorated function returns `Trampoline(func, *args, **kwargs)` to defer execution. The `@trampoline` decorator runs an iterative loop: it invokes the decorated function and, while the returned value is a `Trampoline`, re-runs the deferred call with its `*args, **kwargs`, until a non-`Trampoline` value is produced, which it returns.

The observable guarantee is **stack safety**: deferring via `Trampoline(...)` must not grow the Python call stack, *even when the deferred `func` is the decorated function itself*. So a self-recursive `@trampoline` function that defers to its own decorated name completes at depths far beyond the interpreter's recursion limit, where ordinary recursion would raise `RecursionError`. Results are unaffected: the decorated function still computes the same value it would under plain recursion.

---

## 16. Fold (`returns.iterables`)

Functional iteration over containers. The `acc` argument is a **seed container of the target container type** (e.g. `Success(0)`, `Some(0)`); the result is returned wrapped in that same container type. `Fold` is generic over the container type: `acc` may be any container in this spec that supports the standard interface, including containers that have no failure state.

- `Fold.loop(iterable, acc, function)` — Folds containers, seeded by `acc`. `function(value)` returns a function updating the accumulator. Short-circuits on failure.
- `Fold.collect(iterable, acc)` — Collects the inner values into a tuple, wrapped in `acc`'s container type. Any failure short-circuits.
- `Fold.collect_all(iterable, acc)` — Collects only successes, skipping failures.

---

## 17. Helper Functions (`returns.functions`)

- `identity(value)` — Returns argument unchanged.
- `tap(function)` — Returns a function that applies `function` for side effects but returns the original argument.
- `untap(function)` — Returns a function that applies `function` and always returns `None`.
- `compose(first, second)` — `compose(f, g)(x)` ≡ `g(f(x))`.
- `not_(function)` — Negates a predicate.
- `raise_exception(exception)` — Raises the given exception.

---

## 18. Exceptions (`returns.primitives.exceptions`)

- **`UnwrapFailedError`** — Raised by `.unwrap()` on failure or `.failure()` on success. Has `halted_container` attribute. When a `Failure` contains an `Exception`, unwrapping chains it as `__cause__`.

---

## 19. Base Container (`returns.primitives.container`)

All containers inherit from `BaseContainer`:
- Immutable (attribute assignment raises error)
- `__repr__` returns `'<ClassName: value>'`, where `value` is rendered with `str()`, not `repr()` (so `repr(Failure("err"))` is `'<Failure: err>'`, not `"<Failure: 'err'>"`)
- `__eq__` compares type and inner value
- `__hash__` based on inner value
- Pickle support via `__getstate__`/`__setstate__`

---

## 20. User-Facing Utilities

- **`unsafe_perform_io(io)`** (`returns.unsafe`) — Extracts the raw value from an `IO` container. Escape hatch from the IO world.
- **`partition(containers)`** (`returns.methods.partition`) — Splits an iterable of unwrappable containers into `(successes_list, failures_list)`. Preserves order. Uses `unwrap()`/`failure()` internally.
- **`unwrap_or_failure(container)`** (`returns.methods.unwrap_or_failure`) — Returns the success value or the failure value, whichever is present. For `IOResult`, returns `IO`-wrapped values.

---

## 21. ReAwaitable (`returns.primitives.reawaitable`)

Lets a single awaitable be awaited multiple times by caching the result of the first `await`.

- **`ReAwaitable(coro)`** — Wraps an awaitable. Awaiting the wrapper repeatedly runs the underlying coroutine exactly once and returns the cached result on every subsequent `await`.
- **`reawaitable(coro_function)`** — Decorator wrapping an `async def` so that each call's returned awaitable is independently re-awaitable (the coroutine body runs once per call, then caches).

---

## 22. Higher-Kinded Types (`returns.primitives.hkt`)

Emulated Higher-Kinded Type (HKT) support, used to write functions and containers generic over the container type. These are typing utilities and are **runtime no-ops**.

- **`KindN`** and aliases `Kind1`, `Kind2`, `Kind3` — annotate values generic over a container (e.g. `Kind1[IO, int]`). `KindN` has no runtime instances.
- **`SupportsKindN`** and aliases `SupportsKind1`, `SupportsKind2`, `SupportsKind3` — base classes a custom container inherits from so it participates in HKT (e.g. `class Box(BaseContainer, SupportsKind1[Box, int]): ...`).
- **`kinded(function)`** — Decorator that "dekinds" a function's declared `KindN` return type into the concrete container type. Returns the function unchanged at runtime.
- **`dekind(kind)`** — Turns a `Kind1[IO, int]`-typed value into the real `IO[int]` type. At runtime it returns its argument unchanged (`dekind(x) is x`).

A typical custom container defines `map`/`bind`/etc. directly and uses `@kinded` + `dekind` inside generic helper functions written against it.

---

## Notes

- The library is pure Python with zero runtime dependencies beyond `typing-extensions`.
- All containers are immutable.
- The `returns.interfaces` package contains abstract interface ABCs (Mappable, Bindable, etc.) for type checking. These don't need implementation logic — concrete containers implement methods directly.
