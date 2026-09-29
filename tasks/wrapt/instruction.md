# wrapt — decorators, wrappers, proxies and monkey patching

Implement a Python package named **`wrapt`** that provides a transparent object
proxy and a family of utilities built on top of it: a universal decorator
factory, function wrappers, monkey-patching helpers, post-import hooks, thread
and async synchronization, signature overriding, an LRU cache, lazy/auto
proxies and a weak-reference function proxy.

The library is pure Python and depends only on the standard library. Every
public name listed below must be importable directly from the top-level package
(`import wrapt; wrapt.ObjectProxy`, etc.). The internal module layout is
entirely up to you — only the top-level `wrapt.<name>` access matters.

### Dependencies and environment

This environment is **offline** — there is no network access, and every
dependency you need is **already installed**. Do not attempt to install,
download, or fetch anything (e.g. no `pip install`). The package has **no
third-party runtime dependencies**: it is implemented entirely on top of the
Python standard library.

Your job is to provide the package source plus the usual packaging files so the
project can be installed in editable mode. Installation is performed for you by
a `setup.sh` script that runs **offline** (it invokes
`pip install -e . --no-build-isolation` against the pre-installed build
backend). Provide a `pyproject.toml` (and/or `setup.py`) configured for the
standard `setuptools` build backend so this editable install succeeds.

---

## 1. `ObjectProxy` — transparent object proxy

`ObjectProxy(wrapped)` wraps any object and forwards essentially all behaviour
to it, so the proxy is, as far as possible, indistinguishable from the wrapped
object.

- The wrapped object is available as the attribute `__wrapped__`.
- **Attribute access is transparent.** Reading, setting and deleting attributes
  goes through to the wrapped object (e.g. setting `proxy.x = 1` sets it on the
  wrapped object). The metadata attributes `__name__`, `__qualname__`,
  `__module__`, `__doc__` and `__dict__` reflect the wrapped object (so
  `vars(proxy)` returns the wrapped object's dict).
- **Proxy-private state.** Attributes whose names start with `_self_` are stored
  on the proxy itself and never forwarded to the wrapped object. The method
  `__self_setattr__(name, value)` stores an attribute on the proxy directly
  (bypassing forwarding) under any name, and the read-only property
  `__self_dict__` exposes the proxy's own instance dictionary (distinct from
  `__dict__`, which is the wrapped object's).
- **Type transparency.** `proxy.__class__` and `isinstance(proxy, T)` report the
  wrapped object's type, while `type(proxy)` is still the proxy class itself.
  When the wrapped object is a *class*, the proxy may also be used as the class
  argument of `isinstance()` / `issubclass()` — such checks are delegated to the
  wrapped class (i.e. the proxy honours `__instancecheck__` / `__subclasscheck__`).
- **Subclass introspection.** A subclass of `ObjectProxy` retains normal
  class-level introspection: the subclass's own `__doc__` and `__module__` are
  visible on the class object (e.g. `MyProxy.__doc__` is the subclass docstring),
  even though *instances* delegate `__doc__`/`__module__` to the wrapped object.
- **Deletion of `__wrapped__` is forbidden** and raises `TypeError`.
- **Weak references.** A proxy can itself be the target of `weakref.ref(proxy)`
  (it propagates a `__weakref__` slot).
- **Operators delegate to the wrapped object:**
  - Comparisons (`<`, `<=`, `==`, `!=`, `>`, `>=`), `hash()`, `bool()`.
  - String/representation: `str()`, `bytes()`, `format()` (with format spec).
    `repr(proxy)` returns a string of the form
    `"<ClassName at 0x... for WrappedClassName at 0x...>"` (i.e. it begins with
    `"<ClassName at 0x"`).
  - Numeric conversions and unary ops: `int()`, `float()`, `complex()`,
    `__index__`, `abs()`, `round()`, unary `-`, `+`, `~`.
  - Binary arithmetic/bitwise operators in both directions (so both
    `proxy + x` and `x + proxy` work): `+ - * / // % divmod ** pow(…,…,…)
    << >> & ^ | @`.
  - In-place operators (`+=`, `-=`, …, `@=`): if the wrapped object supports the
    corresponding in-place operation, mutate it in place and return the *same*
    proxy (with the same `__wrapped__`); otherwise compute a new value and
    return a *new* proxy of the same kind wrapping it.
  - Container protocol: `len()`, `x in proxy`, `proxy[k]`, `proxy[k] = v`,
    `del proxy[k]`, slicing, iteration, and `reversed()`.
  - Context-manager protocol: `with proxy:` drives the wrapped object's
    `__enter__`/`__exit__` (and the async equivalents for `async with`).
- **Copy/pickle.** The base `ObjectProxy` does not support copying or pickling:
  `copy.copy`, `copy.deepcopy` and `pickle.dumps` on a plain `ObjectProxy` each
  raise `NotImplementedError`. A subclass may opt in by implementing the usual
  copy/pickle hooks (e.g. `__reduce_ex__`).
- Subclassing `ObjectProxy` must work: subclasses can add methods/properties and
  override behaviour, and attributes a subclass needs internally should be kept
  under `_self_*` names.

### `CallableObjectProxy`

`CallableObjectProxy(wrapped)` is an `ObjectProxy` that is also callable: calling
it forwards positional and keyword arguments to the wrapped callable and returns
its result. All other proxy behaviour is inherited.

---

## 2. `decorator` — universal decorator factory

`@wrapt.decorator` turns a *wrapper function* into a decorator. The wrapper
function has the signature `wrapper(wrapped, instance, args, kwargs)` and is
responsible for calling `wrapped(*args, **kwargs)` (it may modify the arguments
or the result). `args` and `kwargs` are the positional and keyword arguments of
the call.

A decorator built this way works uniformly on functions, methods and classes and
**preserves introspection** of the decorated object (its `__name__`, `__doc__`,
`inspect.signature(...)`), and exposes the original via `__wrapped__`.

The `instance` argument identifies the binding context at call time:

- plain function: `instance is None`;
- instance method: `instance` is the object the method is bound to;
- class method: `instance` is the class;
- static method: `instance is None`;
- when the decorator is applied to a class: `instance is None`.

For an instance method, the normal Python equivalence between
`obj.method(arg)` and `Class.method(obj, arg)` is preserved: calling through the
class with the instance passed explicitly as the first argument still delivers
that instance as `instance` (and does not leak `self` into `args`).

`decorator` accepts keyword-only options (usable as `@wrapt.decorator(...)`):

- **`enabled`** — enable/disable the wrapper. If a `bool`, it is evaluated at
  decoration time: when `False`, the wrapper is *not* applied at all and the
  bare original function is returned (so it has no `__wrapped__`). If a callable,
  it is consulted on every call; when it returns false the wrapped function is
  called directly, bypassing the wrapper.
- **`adapter`** — override the *exposed* signature of the decorated function
  (what `inspect.signature` / `inspect.getfullargspec` report) without changing
  how it actually runs. The adapter may be: a prototype callable whose signature
  is used; an argument specification (as produced by `inspect.getfullargspec`);
  or an adapter factory built with `adapter_factory` (below). The real
  implementation still executes on call.

- **`proxy`** — the class used to build the wrapper. It defaults to
  `FunctionWrapper`; passing a `FunctionWrapper` subclass makes the decorated
  object an instance of that subclass (useful for attaching extra behaviour),
  while calls still dispatch through the wrapper.

A **class** may be used as the wrapper by decorating it with `@wrapt.decorator`;
instances of the class (whose `__call__` has the wrapper signature) then act as
the wrapper. Both `@TheClass` and `@TheClass(...)` forms must work, the latter
passing keyword arguments to the class constructor.

### `adapter_factory`

`adapter_factory(factory)` wraps a `factory(wrapped)` callable so the adapter is
built lazily from the wrapped function at decoration time. Pass the result as the
`adapter=` argument. The factory returns either a prototype callable or an
argument specification.

### `bind_state_to_wrapper`

`bind_state_to_wrapper(*, name="state")` is a descriptor decorator applied on top
of a wrapper-factory method (a method itself decorated with `function_wrapper` or
`decorator`). When that method is accessed through an owner instance and used to
decorate a function, the owner instance is automatically attached to the
resulting wrapper as an attribute named by `name` (default `"state"`), so it is
reachable as `decorated.<name>`.

---

## 3. Function wrappers

### `FunctionWrapper`

`FunctionWrapper(wrapped, wrapper)` is the proxy class used to apply a wrapper
(of signature `wrapper(wrapped, instance, args, kwargs)`) to a callable. It is an
`ObjectProxy` that handles method binding correctly. It is used directly by the
monkey-patching helpers (e.g. `wrap_object(..., wrapt.FunctionWrapper, (wrapper,))`
produces a `FunctionWrapper` instance). When placed in a class body, a
`FunctionWrapper` forwards `__set_name__` to the wrapped object, so a wrapped
descriptor still receives the name it was assigned to.

### `function_wrapper`

`function_wrapper(wrapper)` is a lightweight decorator builder for monkey
patching: given a `wrapper(wrapped, instance, args, kwargs)` function it returns a
decorator that wraps a target callable with a `FunctionWrapper`. It works on both
plain functions and instance methods, supplying the correct `instance`.

### `partial`

`partial(func, *args, **kwargs)` behaves like `functools.partial` — it pre-binds
arguments to `func` — but is implemented as a transparent proxy so the result
remains introspectable (`__wrapped__` is the original callable). Later keyword
arguments at call time override pre-bound ones. Constructing it with no arguments,
or with a non-callable first argument, raises `TypeError`.

---

## 4. Monkey-patching helpers

In all of these, a **target** may be a module, class or instance; if the target
is a string it is treated as a module name (imported if necessary). A **name** is
a dotted attribute path resolved against the target.

- **`resolve_path(target, name)`** → `(parent, attribute, original)`: resolves a
  dotted path and returns the immediate parent object, the final attribute name,
  and the current value. For a method on a class it returns the unbound function
  from the class `__dict__` (it does not trigger binding).
- **`apply_patch(parent, attribute, replacement)`**: sets `attribute` on
  `parent` to `replacement` (equivalent to `setattr`).
- **`wrap_object(target, name, factory, args=(), kwargs=None)`**: resolves
  `name` on `target`, builds a replacement by calling
  `factory(original, *args, **kwargs)`, installs it, and returns the replacement.
- **`wrap_object_attribute(target, name, factory, args=(), kwargs=None)`**: wraps
  an *instance* attribute by installing a descriptor on the owning class so that
  each read of the attribute is passed through `factory(value, *args, **kwargs)`
  while writes update the underlying value. Here `name` is `"ClassName.attribute"`
  resolved against `target` (commonly the module, e.g. the module's `__name__`).
- **`wrap_function_wrapper(target, name, wrapper)`**: wraps the function at
  `target.name` in place with a `FunctionWrapper` using `wrapper`
  (`wrapper(wrapped, instance, args, kwargs)`), so existing references see the
  new behaviour and `self` is delivered as `instance`. If `target` is a module
  name string with a trailing `?` (e.g. `"pkg.mod?"`), the wrapping is deferred:
  it is applied immediately if the module is already imported, otherwise it is
  registered to be applied when the module is first imported (returning `None` in
  the deferred case).
- **`patch_function_wrapper(target, name, enabled=None)`**: the decorator form of
  `wrap_function_wrapper` — decorate a wrapper function to patch `target.name`
  with it. It accepts the same trailing-`?` deferred-target syntax as
  `wrap_function_wrapper` (apply when the named module is first imported).
- **`transient_function_wrapper(target, name)`**: returns a decorator; while the
  decorated function runs, `target.name` is temporarily patched with the wrapper,
  and the original is restored afterwards (even on exception).

---

## 5. Post-import hooks

- **`register_post_import_hook(hook, name)`**: register `hook(module)` to run when
  the module named `name` is imported. If the module is already imported, the
  hook is called immediately; otherwise it fires automatically the moment the
  module is first imported. (Installing whatever import machinery is required to
  achieve this is part of the task.)
- **`when_imported(name)`**: a decorator equivalent — `@when_imported(name)`
  registers the decorated function as the hook and returns it unchanged.
- **`notify_module_loaded(module)`**: invoke any hooks registered for the
  module's name, passing the module object. (Used by the import machinery and
  callable directly.)

---

## 6. Synchronization and calling-convention helpers

### `synchronized`

`synchronized` provides mutual exclusion.

- As a decorator on a regular function or method (`@wrapt.synchronized`), it
  serializes calls so no two threads execute the body simultaneously, using a
  lock created automatically and associated with the appropriate context. The
  auto-created lock is reentrant.
- It also supports being stacked on top of `@classmethod` and `@staticmethod`;
  for a class method the class is delivered as the first argument, and such
  calls are serialized like any other.
- The decorated function can also be used as a context manager (`with func:`),
  holding its associated lock for the duration of the block.
- When applied to an `async def` function, it uses an `asyncio.Lock` and the
  wrapper awaits the lock, so concurrently-awaited calls never overlap. The
  decorated async function still reports as a coroutine function under
  `inspect.iscoroutinefunction`. Such a decorated async function can also be used
  with `async with func:` to hold its async lock for a block.
- When given an existing synchronization primitive — any object exposing
  `acquire()` and `release()` (e.g. `threading.Lock`) — `synchronized(lock)`
  returns something that both decorates a function to run while that lock is held
  *and* acts as a context manager that acquires/releases the supplied lock
  (its `__enter__` returns the lock). If the supplied lock has coroutine
  `acquire`/`release` methods (e.g. an `asyncio.Lock`), the async protocol is
  used to decorate async functions and to support `async with`.

### `async_to_sync` / `sync_to_async`

- **`async_to_sync(func)`**: adapt an async callable so it can be called from
  synchronous code; each call runs the coroutine to completion (via
  `asyncio.run`). The result reports as synchronous
  (`inspect.iscoroutinefunction` is `False`).
- **`sync_to_async(func)`**: adapt a synchronous callable so it can be awaited;
  each call dispatches the work to the default executor. The result reports as
  asynchronous (`inspect.iscoroutinefunction` is `True`).

### `mark_as_async` / `mark_as_sync`

These change the *reported* calling convention without otherwise changing the
implementation:

- **`mark_as_async(func, *, generator=None)`**: the result reports as a coroutine
  function (`inspect.iscoroutinefunction` is `True`) and calling it returns an
  awaitable whose result is the original return value. With `generator=True` it
  instead reports as an async generator function
  (`inspect.isasyncgenfunction` is `True`).
- **`mark_as_sync(func, *, generator=None)`**: the result reports as *not* a
  coroutine function (`inspect.iscoroutinefunction` is `False`), even if `func`
  was `async def`. With `generator=True` it reports as a plain (sync) generator
  function (`inspect.isgeneratorfunction` is `True`).

---

## 7. `with_signature` — override an exposed signature

`with_signature(*, prototype=None, signature=None, factory=None)` decorates a
callable to override the signature reported by `inspect.signature` and
`inspect.getfullargspec` (and the derived `__defaults__`, argument names,
`*args`/`**kwargs` and keyword-only parameters) without changing how the
callable runs. The override also updates the wrapper's `__code__` argument
attributes (`co_argcount`, leading `co_varnames`) so tools reading the raw code
object see it too (and keyword-only defaults are exposed via `__kwdefaults__`).
Exactly one of the three sources must be supplied, otherwise `TypeError` is
raised:

- `prototype`: a callable whose signature is used;
- `signature`: a prebuilt `inspect.Signature`;
- `factory`: `factory(wrapped)` invoked at decoration time, returning either a
  `Signature` or a prototype callable.

Applied to a method, the override is reported on the unbound function and `self`
is correctly stripped when the method is accessed through an instance; applied to
a class method, `cls` is likewise stripped when accessed through the class. Calls
still execute the real implementation.

---

## 8. `lru_cache` — memoization

`lru_cache` is a replacement for `functools.lru_cache` that handles methods
correctly. Usable as `@wrapt.lru_cache` or `@wrapt.lru_cache(maxsize=..., typed=...)`;
all keyword arguments are forwarded to `functools.lru_cache`.

- For **instance methods**, a *separate* cache is maintained per instance (so two
  instances do not share cached results, and per-instance statistics are
  independent).
- For plain functions, class methods and static methods, a single shared cache
  is used.
- The decorated callable exposes `cache_info()`, `cache_clear()` and
  `cache_parameters()` (for bound methods these operate on that instance's
  cache). `cache_info()` returns the usual hits/misses/maxsize/currsize info and
  `cache_parameters()` returns the configuration mapping.

---

## 9. Lazy and auto proxies

### `LazyObjectProxy`

`LazyObjectProxy(callback, *, interface=...)` is an `ObjectProxy` whose wrapped
object is created on first use by calling `callback()`. The factory is not
invoked merely by constructing the proxy; it runs the first time the proxy is
actually used, and the created object is cached for subsequent use.

Plain attribute access on the proxy triggers creation (and then forwards to the
created object) like any `ObjectProxy`. But special methods such as `__call__`,
`__iter__`, `len()` and the iterator/awaitable/descriptor protocols only work
*before* the object exists if the proxy advertises them up front: the
`interface` argument declares which of those special methods the proxy should
expose before the object exists (pass the type or an object whose protocol
should be matched). When `interface` is left at its default, the proxy
advertises **no** special methods, so a default `LazyObjectProxy` standing in
for a callable or an iterable must be given an explicit `interface` (or first
accessed via an attribute) before it can be called or iterated.

### `AutoObjectProxy`

`AutoObjectProxy(wrapped)` is an `ObjectProxy` that automatically adds the
special methods appropriate to the wrapped object — call forwarding for
callables, `__iter__`/`__next__` for iterables/iterators, `__aiter__`/`__anext__`
for async iterators, `__await__` for awaitables, `__length_hint__` when present,
and descriptor methods (`__get__` etc.) for descriptors, and so on. If `__wrapped__` is later reassigned, the set of special methods is
re-derived to match the new object.

### `lazy_import`

`lazy_import(name, attribute=None, *, interface=...)` returns a `LazyObjectProxy`
that imports the module `name` on first use; if `attribute` is given, the proxy
stands in for that attribute of the module instead of the module itself.

When `interface` is not supplied, `lazy_import` chooses a sensible default for
the kind of object being deferred: when `attribute` is given the proxy stands in
for a (typically callable) attribute, so it defaults to a callable interface —
i.e. `lazy_import("json", "dumps")` may be *called* before the import has
happened (the call itself triggering the import and then forwarding to the real
attribute); when no `attribute` is given the proxy stands in for the module
itself and defaults to a module interface (modules are not callable, so the
deferred module is used via attribute access, which triggers the import). An
explicit `interface=` overrides these defaults.

---

## 10. `WeakFunctionProxy` — weak reference to a callable

`WeakFunctionProxy(wrapped, callback=None)` is a weak-reference proxy that works
with plain functions and bound methods. For a bound method it holds weak
references to both the instance and the underlying function and rebinds them at
call time (a bound method is transient and cannot be weak-referenced directly).

- While the referent is alive, calling the proxy forwards to it and returns the
  result.
- Once the bound instance has been garbage collected, calling the proxy raises
  `ReferenceError`, and the optional `callback` (if given) is invoked once with
  the proxy when the referent expires.
- For a plain function, the proxy simply forwards calls while the function is
  alive.
