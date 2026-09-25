# dill — Extended Pickle Serialization

## Overview

Implement **dill**, a drop-in replacement for Python's `pickle` module that extends serialization to types pickle cannot handle: lambdas, closures, nested functions, dynamically-created classes, code objects, and more. The API mirrors pickle (`dumps`, `loads`, `dump`, `load`, `copy`) but registers custom reducer functions for ~50+ additional types.

dill works by subclassing Python's `Pickler` and `Unpickler`, overriding the type dispatch to handle types that the standard pickle protocol doesn't support natively. Each type gets a custom reducer that decomposes it into pickleable components.

## Dependencies

- No external runtime dependencies — dill is pure Python (standard library only).
- **The environment is offline and all build tooling is already installed — do not install anything.** The project is built and installed for you by a `setup.sh` that runs entirely offline (no network access). Implement the package from scratch using only the Python standard library.

---

## 1. Core API (`dill`)

Drop-in pickle replacement:
- `dill.dumps(obj, protocol=None, byref=False, recurse=False)` → `bytes`
- `dill.loads(data)` → object
- `dill.dump(obj, file, protocol=None)` / `dill.load(file)`
- `dill.copy(obj)` — deep copy via serialize/deserialize round-trip
- `dill.DEFAULT_PROTOCOL` — default pickle protocol version

Key difference from pickle: `recurse=True` pickles functions by value (capturing source code) rather than by reference (module + name).

---

## 2. Extended Type Support

Types dill can serialize that pickle cannot:
- Lambda functions
- Closures (functions with free variables / cell objects)
- Nested functions and decorated functions
- Functions serialized by value round-trip as equivalent function objects, preserving the attributes assigned on the function object (its `__dict__`) along with the rest of its state
- Generator functions (the function itself, not active generators)
- Dynamically-created classes (via `type()`)
- Open file handles (preserves file path, mode, and position)
- `dict_keys`, `dict_values`, `dict_items` (dictionary view objects)
- `property` objects (descriptor protocol preserved)
- `staticmethod` and `classmethod` descriptor objects (the bare descriptors, with the wrapped `__func__` preserved; a `classmethod` round-trips back to a `classmethod` instance)
- `functools.partial` objects
- `operator.itemgetter`, `operator.attrgetter`
- Named tuples and dataclasses (with full field preservation)
- Code objects
- Classes with lambda/closure attributes
- Classes defined with a custom metaclass (e.g. `abc.ABCMeta` / abstract base classes) — serialized by value so a concrete subclass round-trips and its methods still work after deserialization
- Instances of locally-defined classes that subclass a builtin type (e.g. subclassing `list` or `dict`) — round-trip preserving both the builtin contents and any custom instance attributes
- `threading.Lock` — the current locked/unlocked state is preserved, so a lock that was held remains held after deserialization until released
- `threading.RLock` — the reentrant acquisition count is preserved, so the restored lock must be released the same number of times it was acquired before it becomes free again
- `types.MappingProxyType`
- `functools.lru_cache` decorated functions — restored as an equivalently configured cache wrapper, with the original cache configuration preserved rather than reset to the decorator's defaults
- `super` objects (bound `super()` proxies — the bound type and instance are preserved so method resolution still delegates to the base class after a round-trip)
- `weakref.ref` objects — when serialized alongside their referent (e.g. in the same container), the restored weakref points at the restored referent, so calling it returns that object

---

## 3. Pickling Utilities (`dill`)

Top-level helpers for checking serializability and toggling dill's reducers:

- `dill.pickles(obj, exact=False)` → `bool` — return `True` if `obj` can be (de)serialized by dill, `False` otherwise. With `exact=True`, additionally require that the deserialized object compares equal to the original, returning `True` only on an equality-preserving round-trip.
- `dill.extend(use_dill=True)` — install (or, with `use_dill=False`, remove) dill's extended type reducers in the standard library's `pickle` dispatch registry. Specifically, the reducers are installed on the dispatch table of the standard library's *pure-Python* pickler, `pickle._Pickler` (the same class dill's own `Pickler` subclasses); the C-accelerated `pickle.Pickler` / `pickle.dumps` path is unaffected. So a serialization driven through `pickle._Pickler` gains support for dill's extra types after `extend(True)` (e.g. it can serialize a lambda) and reverts to stock pickle behavior after `extend(False)` (a lambda then raises `pickle.PicklingError`). Reversible: `extend(True)` restores dill's reducers. dill installs its reducers automatically on import.
- `dill.check(obj, *args, **kwds)` — verify `obj` survives a serialize/deserialize round-trip in a separate process, printing the result. Returns `None` on success. Passing `verbose=True` prints the round-trip outcome, reporting `SUCCESS` when the separate-process reload succeeds (and `LOAD FAILED` otherwise). Extra arguments are forwarded to `dumps`/`loads`.

---

## 4. Session Save/Restore (`dill.session` or `dill`)

- `dill.dump_module(filename, module=None)` — serialize a module's namespace to a file
- `dill.load_module(filename, module=None)` — restore a module's namespace from a file
- `dill.session.load_module_asdict(filename)` — load a saved module's contents into a dictionary

When `module` is `None` (the default), `dump_module`/`load_module` operate on the `__main__` module — the interactive session namespace — so `dump_module(filename)` saves the current `__main__` state and `load_module(filename)` restores into `__main__`. When `module` is provided, they save/restore that specific module instead. This enables saving the entire state of a Python session and restoring it later.

---

## 5. Source Inspection (`dill.source`)

- `dill.source.getsource(obj)` — retrieve source code for objects that `inspect.getsource` can't handle (lambdas, closures, interactively-defined functions)
- `dill.source.importable(obj)` — get an importable string (source code or import statement) that can recreate the given object. The returned string is executable: after `exec(importable(obj), ns)`, `ns` contains `obj` bound under its own name. For an object reachable by name from a module (a builtin such as `len`, or a module-level function/class), it returns a name-binding import statement, not a bare-name expression or a `repr`. For source-recreatable objects (lambdas, locally/interactively-defined functions), it returns their source instead.

---

## 6. Pickling Diagnostics (`dill.detect`)

- `dill.detect.baditems(obj)` — returns a list of items in `obj` that can't be pickled
- `dill.detect.globalvars(func)` — get objects defined in global scope that are referred to by `func`. Returns a dict of `{name: object}`.
- `dill.detect.nestedcode(func)` — get the code objects for any nested functions. Returns a list of code objects.

---

## 7. Temp File Utilities (`dill.temp`)

- `dill.temp.dump(obj)` — pickle an object to a `NamedTemporaryFile`. Returns the file handle.
- `dill.temp.load(file)` — load an object from a file handle returned by `dump`.

---

## 8. setup.sh

The project is installed offline (no network), so the editable install must skip build isolation
and use the pre-baked build backend:

```bash
pip install -e . --no-build-isolation
```
