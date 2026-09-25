# pyrsistent — Persistent/Immutable Data Structures

Build **pyrsistent**, a Python library providing persistent (immutable) data structures.

## Dependencies & Environment

This is a **pure-Python** library with **no runtime dependencies** — implement everything using only the Python standard library.

The environment is **offline**: there is no network access, and every dependency you need is **already installed**. Do **not** attempt to install anything (`pip install`, `apt-get`, etc.) — installs will fail with no network. The project is installed for you by a `setup.sh` that runs `pip install -e . --no-build-isolation` offline against the pre-baked build backend (setuptools + wheel). Provide a standard setuptools-buildable package (`pyproject.toml` / `setup.py`) so this editable install succeeds.

---

## Short factory names

Every collection section heading below lists two module-level names, e.g. `pvector` and `v`. The short name is not an alias of the long factory: it is a literal-style constructor that receives the collection's contents directly as arguments — `v`, `s`, `l`, `b` and `dq` as positional varargs, `m` as keyword pairs — whereas the long factory takes a single iterable (or mapping).

---

## PVector (`pyrsistent.pvector`, `pyrsistent.v`)

Persistent vector: an immutable, indexable sequence that must scale efficiently to large sizes (tens of thousands of elements) with copy-on-write updates. Supports slicing (including step), concatenation, repetition, `count`, `index`. Hashable. Supports pickle roundtrip.

Supports set, append, extend, delete (including negative index), mset — all return new vectors. `set` raises `IndexError` if out of bounds. `mset(i1, v1, i2, v2, ...)` takes alternating index/value positional arguments and returns a new vector with all the listed indices set.

**Evolver**: `evolver()` returns mutable builder. Supports `evolver[i] = val`, `append(val)`, `extend(iter)`, `del evolver[i]`, `persistent()` returns immutable PVector. Must correctly handle long sequences of interleaved set/append/extend/delete operations, producing the correct final vector while leaving the original PVector unchanged. Must remain correct across the full range of sizes, from a few elements up to tens of thousands, for both single updates and batched evolver mutations.

---

## PMap (`pyrsistent.pmap`, `pyrsistent.m`)

Persistent hash map (immutable, dict-like). Must correctly handle hash collisions, including extreme cases where 50+ keys share the same hash value (via a custom `__hash__`).

`keys()` returns a `PSet`. PMaps with same content are equal (same hash) regardless of insertion order. Equality with plain `dict` supported. Supports pickle roundtrip.

Methods: `set(key, val)`, `remove(key)` raises `KeyError`, `discard(key)` returns unchanged map if missing, `update(*maps)`.

**Evolver**: `evolver[key] = val`, `del evolver[key]` (raises `KeyError` for non-existent or already-deleted keys), `persistent()`. Evolver remains usable after `KeyError` exceptions.

---

## PSet (`pyrsistent.pset`, `pyrsistent.s`)

Persistent set. Full set algebra: `union`/`|`, `intersection`/`&`, `difference`/`-`, `symmetric_difference`/`^`, `issubset`, `issuperset`. Hashable. Supports pickle roundtrip.

Methods: `add`, `remove` (raises `KeyError`), `discard`.

**Evolver**: `add`, `remove`, `persistent()`.

Must correctly handle elements that share hash values via a custom `__hash__`, including many colliding elements.

---

## PList (`pyrsistent.plist`, `pyrsistent.l`)

Persistent singly-linked list. Properties: `first` (head), `rest` (tail). `bool(empty_plist)` is `False`. Supports indexing including negative. Hashable. Registered as a `collections.abc.Sequence` (`isinstance(plist(...), collections.abc.Sequence)` is `True`). Supports pickle roundtrip.

Methods: `cons(elem)` prepends, `mcons(iterable)` prepends multiple (items in reverse order: `plist([1,2,3]).mcons([10,20])` yields `[20, 10, 1, 2, 3]`), `remove(elem)` raises `ValueError`, `reverse()`, `split(index)` returns `(left, right)` tuple.

---

## PBag (`pyrsistent.pbag`, `pyrsistent.b`)

Persistent multiset. Hashable. `__eq__` order-independent. `__len__` returns total including duplicates. Iteration yields all elements including duplicates. Supports pickle roundtrip.

Methods: `add`, `remove` (raises `KeyError`), `count` (returns 0 if absent), `update(iterable)`.

Operators: `+` sums counts, `-` subtracts (clamped at 0, zero-count dropped), `|` union (max), `&` intersection (min).

---

## PDeque (`pyrsistent.pdeque`, `pyrsistent.dq`)

Persistent double-ended queue. Properties: `left`, `right`, `maxlen`. Hashable. Registered as a `collections.abc.Sequence` (`isinstance(pdeque(...), collections.abc.Sequence)` is `True`). Supports pickle roundtrip.

Methods: `append`, `appendleft`, `pop(count=1)`, `popleft(count=1)`, `remove`, `extend`, `extendleft` (reversed order like `collections.deque`), `count`, `reverse`, `rotate(steps)` (positive: right-to-left, negative: left-to-right).

When bounded (`maxlen` set), `append`/`extend` drop from left; `appendleft`/`extendleft` drop from right.

---

## PRecord (`pyrsistent.PRecord`)

PMap subclass with fixed typed fields via `field()`. Fields default to optional unless `mandatory=True` is specified. `field(initial=<value>)` supplies the default value used when the field is omitted at construction; an optional field with no `initial` is simply absent. `set(**kwargs)` or `set(key, value)` returns new record. Raises `PTypeError` on type violations, `InvariantException` on missing mandatory fields, `AttributeError` on undeclared fields or direct assignment.

**Invariants**: `field(invariant=lambda x: (bool, error_msg))` for per-field (receives the field value). `__invariant__` class attribute for global record-level: it is called with the constructed record itself, so it reads field values as attributes. Each invariant returns a `(bool, error_message)` pair; a `False` result raises `InvariantException`.

**Factory**: `field(factory=callable)` transforms input before storage. **Serializer**: `field(serializer=lambda format, value: ...)` used by `record.serialize(format)`.

**Inheritance**: subclass fields merged with parent. **create()**: `MyRecord.create(dict, ignore_extra=False)` constructs recursively — typed sub-records are constructed and ALL invariants validated at ALL nesting levels (including 4+ levels deep). `create()` on existing instance returns same object. `ignore_extra=True` silently ignores extra keys; without it, `AttributeError`.

**Evolver**: `r.evolver()`, `evolver[key] = val`, `evolver.persistent()`.

---

## PClass (`pyrsistent.PClass`)

Immutable object with typed fields (not a PMap subclass). Hashable (instances usable as dict keys). Supports pickle roundtrip (module-level PClass subclasses round-trip through `pickle.dumps`/`pickle.loads` preserving field values and equality, despite the blocked attribute assignment). `set(**kwargs)` or `set(key, value)` returns new instance. `__setattr__`/`__delattr__` raise `AttributeError`. Raises `TypeError` on wrong types, `InvariantException` on missing mandatory, `AttributeError` on undeclared fields.

`optional(*types)` from `pyrsistent` wraps types to also allow `None` — use with `field(type=optional(str))`.

**Invariants, Factory, Serializer**: same as PRecord. Factory re-applied on `set()`. Serializers recurse through nested PClass fields applying per-field serializers at each level.

**create()**: recursive nested construction from dicts. **Evolver**: `set(key, val)`, `remove(key)`, dot-notation, chaining. `persistent()` returns same instance if no changes.

**remove(name)**: removes optional field. Raises `AttributeError` if not present, `InvariantException` if mandatory.

**transform()**: `instance.transform(['field', 'subfield'], value_or_fn)` for deep updates.

---

## Transformations (`pyrsistent.inc`, `pyrsistent.discard`, `pyrsistent.rex`, `pyrsistent.ny`)

`.transform(*transformations)` on PMap/PVector/PClass. Transformations are `(path, command)` pairs; multiple pairs applied in sequence.

Path elements: literal keys/indices, `ny` (matches any), `rex(pattern)` (regex on string keys only — non-string keys skipped), lambda with 1 arg (key predicate), lambda with 2 args (key, value predicate).

Commands: callable applied to current value (user-defined lambdas, `inc`), or literal value (replaces). `discard` removes the element.

Missing intermediate keys create new empty PMaps. When a transform path targets an out-of-bounds PVector index, the vector is extended with new empty PMaps. No-change transform returns exact same object (identity preserved).

---

## Freeze / Thaw / mutant

`freeze(obj, strict=True)` — recursively converts: `dict`/`defaultdict` to PMap, `list` to PVector, `set` to PSet, `tuple` preserved (elements recursed). `strict=True` recurses INTO already-persistent types. `strict=False` does NOT recurse into persistent types.

`thaw(obj, strict=True)` — inverse. Handles PRecord subclasses (converts to dict with all nested persistent fields thawed).

`mutant` decorator (`pyrsistent.mutant`): freezes all arguments and return value.

`get_in(keys, coll, default=None, no_default=False)` — nested access. Returns `default` if missing. `no_default=True` raises `KeyError`. Works with list indexing.

---

## Checked Types

**Construction**: a checked-type subclass is instantiated by **calling the class directly** with a single source collection — `CheckedPVector`/`CheckedPSet` subclasses from any iterable (e.g. `IntVector([1, 2, 3])`, `IntSet([1, 2, 3])`), a `CheckedPMap` subclass from a mapping or iterable of key/value pairs (e.g. `StrIntMap({'a': 1})`). Direct construction populates the collection with those elements and applies the same element/key/value type checks and `__invariant__` validation described below (raising on any violation, otherwise returning a valid instance). `create(source)` is an equivalent idempotent factory that accepts the same source or an already-built instance, returning that same object unchanged when the argument is already an instance. Both entry points type-check identically, and the pickle roundtrip reconstructs through this same construction path.

**CheckedPVector** (`pyrsistent.CheckedPVector`): `__type__`, optional `__invariant__ = lambda n: (bool, msg)`. Raises `TypeError` on type violations (construction, `append`, `set`, `extend`). `InvariantException` on invariant failure. `create()` idempotent. `serialize()` returns list.

**CheckedPMap** (`pyrsistent.CheckedPMap`): `__key_type__`, `__value_type__`. Raises `CheckedKeyTypeError`/`CheckedValueTypeError` (importable from top-level `pyrsistent`) — both `TypeError` subclasses with `source_class`, `expected_types` (tuple), `actual_type`, `actual_value` — on key/value type violations at construction and `set`. `create()`, `serialize()`.

**CheckedPSet** (`pyrsistent.CheckedPSet`): `__type__`. Raises `TypeError` on type violations (construction, `add`). All checked types support `__reduce__` for pickling.

---

## immutable (`pyrsistent.immutable`)

`immutable(members='', name='Immutable')` — namedtuple-like with `set(**kwargs)`. `members` can be a comma-separated string ('x, y'), space-separated ('x y'), or a list of strings. Raises `AttributeError` for non-existing members. **Frozen members**: trailing `_` cannot be set — raises `AttributeError`. Supports subclassing with custom `__new__`. `set(**kwargs)` builds the updated value through the class's normal construction path (it re-invokes the subclass `__new__`), so any custom `__new__` validation re-runs on every `set()` update and may reject the new field values by raising. `set()` with no args on empty immutable returns same instance.

---

## Exceptions

`InvariantException` (`pyrsistent.InvariantException`): Constructor `InvariantException(error_codes=(), missing_fields=())`. Note: constructor kwarg is `error_codes`, but attribute is `invariant_errors`. Attributes: `invariant_errors` (tuple), `missing_fields` (tuple of strings). Both appear in `str()`.

`PTypeError` (`pyrsistent.PTypeError`): subclass of `TypeError` raised by PRecord on field type violations.

---

## Field helpers (`pyrsistent.pvector_field`, `pyrsistent.pmap_field`, `pyrsistent.pset_field`)

Convenience field factories for PRecord: `pvector_field(item_type)` (CheckedPVector-backed, mandatory, empty initial), `pmap_field(key_type, value_type)` (CheckedPMap-backed, mandatory, empty initial — an omitted field defaults to `pmap()`), `pset_field(item_type, optional=False)` (CheckedPSet-backed; with `optional=False` it has an empty initial, so an omitted field defaults to `pset()`; `optional=True` allows `None`). Removing mandatory field helper raises `InvariantException`.
