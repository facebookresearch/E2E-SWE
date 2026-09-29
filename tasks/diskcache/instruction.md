# DiskCache

Build `diskcache`, a Python library providing disk-backed cache, persistent data structures, and distributed computing recipes, all powered by SQLite. The library is thread-safe and process-safe.

## Dependencies

The environment is **offline**: every dependency is already installed and you must **not** install
anything. The project is installed for you by a `setup.sh` that runs offline (`pip install -e .
--no-build-isolation`), so a `pyproject.toml` / `setup.py` that installs cleanly that way is all the
packaging you need to provide.

- The core library (`Cache`, `FanoutCache`, `Deque`, `Index`, `Disk`, `JSONDisk`, recipes) uses the
  **Python standard library only** (sqlite3, pickle, json, zlib, threading, tempfile, os, io, time,
  math, functools, etc.). It declares **no runtime dependencies**.
- `Django` (a pre-installed third-party package) is required only by the `DjangoCache` backend. Your
  `diskcache` package must export `DjangoCache` **only when `django` is importable** (i.e. import it
  lazily / conditionally), so that the rest of the library works without Django.
- No system services are needed (storage is SQLite + the local filesystem).

## Package Structure

The library is importable as `diskcache`. Public API exports from `diskcache`:

- `Cache`, `FanoutCache`, `DjangoCache`, `Deque`, `Index`, `Disk`, `JSONDisk`
- `Timeout`, `ENOVAL`, `UNKNOWN`, `DEFAULT_SETTINGS`, `EVICTION_POLICY`

Recipe classes/functions importable from both `diskcache` and `diskcache.recipes`:

- `Lock`, `RLock`, `BoundedSemaphore`, `Averager`, `throttle`, `barrier`, `memoize_stampede`

## Cache

Core disk-backed key-value store using SQLite. Thread-safe and process-safe — multiple threads and processes can share the same cache directory concurrently.

Readers are never blocked by an in-progress write transaction: while one thread or process holds an open write transaction (e.g. inside `transact()`), concurrent `get`/`read`/`__getitem__` calls on the same cache see the last committed state and return immediately rather than blocking or timing out.

```python
Cache(directory=None, timeout=60, disk=Disk, **settings)
```

Settings include `statistics`, `tag_index`, `eviction_policy`, `size_limit`, `cull_limit`, `disk_min_file_size`, `disk_pickle_protocol`, and various `sqlite_*` options. See `DEFAULT_SETTINGS` dict for all defaults. Settings are also accessible as read properties on the cache instance (e.g., `cache.size_limit`, `cache.cull_limit`, `cache.eviction_policy`).

### Key-Value Operations

Standard dict-like interface: `set`, `get`, `delete`, `add`, `pop`, `__setitem__`, `__getitem__`, `__delitem__`, `__contains__`, `__len__`, `clear`.

- `set(key, value, expire=None, read=False, tag=None, retry=False)` → `True`.
- `get(key, default=None, read=False, expire_time=False, tag=False, retry=False)` → value or default. When `expire_time=True` and/or `tag=True`, returns tuples: `(value, expire_time)`, `(value, tag)`, or `(value, expire_time, tag)`.
- `add(key, value, ...)` → `True` only if key not already present (atomic).
- `delete(key, retry=False)` → `True` if deleted, `False` if not found.
- `pop(key, default=None, expire_time=False, tag=False, retry=False)` → value, removes item. Returns `default` when key is missing. Same tuple return semantics as `get()`.
- `__delitem__` raises `KeyError` if missing. `__getitem__` raises `KeyError` if missing.

### Expiration & Tags

- `touch(key, expire=None)` → `True` if found and TTL updated.
- `expire(now=None, retry=False)` → count of expired items removed. `now` overrides the current time used to decide what is expired (defaults to `time.time()`). `retry` follows the same semantics as elsewhere on `Cache`: `retry=False` (default) raises `Timeout` on a database-lock timeout, while `retry=True` blocks and retries until it succeeds.
- `evict(tag)` → count of items with matching tag removed.
- `create_tag_index()` — create a database index on tags for faster `evict()`.
- `drop_tag_index()` — remove the tag index.

### Increment / Decrement

- `incr(key, delta=1, default=0)` → new value. Atomic. Creates key from `default` if missing (expired keys count as missing).
- `decr(key, delta=1, default=0)` → new value.

### Push / Pull (Queue)

Integer keys starting at 500 trillion (500000000000000).

- `push(value, prefix=None, side='back', expire=None, read=False, tag=None, retry=False)` → key. `side='back'` appends (incrementing from 500 trillion); `side='front'` prepends (decrementing below 500 trillion). With `prefix`, keys become strings like `"prefix-NNNNNNNNNNNNNNN"`.
- `pull(prefix=None, default=(None, None), side='front', expire_time=False, tag=False, retry=False)` → `(key, value)`.
- `peek(prefix=None, default=(None, None), side='front', expire_time=False, tag=False, retry=False)` → `(key, value)` without removing.

### Iteration & Inspection

- `__iter__()` — yield keys in insertion order.
- `__reversed__()` — yield keys in reverse insertion order.
- `iterkeys(reverse=False)` — yield keys in sorted order (or reverse sorted if `reverse=True`).
- `peekitem(last=True)` → `(key, value)`. Peeks in insertion order (the same order as `__iter__`, **not** the sorted order of `iterkeys`): `last=True` returns the most-recently-inserted item, `last=False` the least-recently-inserted.

### Statistics

- `stats(enable=True, reset=False)` → `(hits, misses)`.

### Memoize

```python
@cache.memoize(name=None, typed=False, expire=None, tag=None, ignore=())
```

Caches function results. `typed=True` caches different types separately. `ignore` is a tuple of parameter names to exclude from the cache key. Decorated function gains `__cache_key__(*args, **kwargs)` which returns a tuple. The tuple returned by `__cache_key__` **is** the actual cache key under which the result is stored, so `cache[fn.__cache_key__(*args, **kwargs)]` returns the memoized result and `del cache[fn.__cache_key__(...)]` invalidates it. Using `@cache.memoize` without parens raises `TypeError("name cannot be callable")`.

### Transactions, Context Manager, Settings

- `transact(retry=False)` — context manager for atomic operations.
- `with Cache(directory) as cache:` — auto-closes.
- `directory` property, `volume()` → total size in bytes, `timeout`, `disk` properties. `volume()` reports the total size of the cached *content* — the sum of the stored value sizes (values held inline in the database plus values written to external files) — and therefore **decreases as items are removed** (via `delete`, `evict`, `expire`, `pop`, or `cull`) and grows as items are added. It reflects the logical stored data, not the cache file's unreclaimed on-disk footprint, and it is the quantity `cull()` measures against `size_limit`.
- `reset(key, value=ENOVAL)` — read a setting (no value arg) or update a setting (with value). Settings keys include `'size_limit'`, `'cull_limit'`, `'eviction_policy'`, etc.
- `check(fix=False)` → list of warnings (empty if consistent). `fix=True` repairs issues.
- `cull(retry=False)` → count of items removed. Enforces `size_limit` by removing items per the eviction policy in **fixed batches of `cull_limit`**. When a write (`set`/`__setitem__`/`push`/`incr`/…) drives total `volume()` above `size_limit`, it removes the next `cull_limit` items in eviction-policy order as a single batch — the full `cull_limit`, **not** merely the minimum needed to fall back under `size_limit` — so a single overflow can leave `volume()` well below `size_limit`. If after a batch `volume()` is still above `size_limit`, another batch of `cull_limit` is removed, repeating until at or under the limit. Under the `'none'` policy `cull()` removes nothing and returns 0.
- `close()` — close the SQLite connection.

### Read Mode

- `set(key, value, read=True)` — store from file-like object.
- `read(key)` → open file handle for stored value. Works on any stored value, not only those stored with `read=True`.

### Eviction Policies

- `'least-recently-stored'` (default) — evicts the item stored/updated least recently.
- `'least-recently-used'` — evicts the item accessed least recently. Each `get` or `__getitem__` updates access time.
- `'least-frequently-used'` — evicts the item with fewest accesses. Each `get` or `__getitem__` increments counter. Ties in access count are broken by store order (the least-recently-stored item among the tie is evicted first), so an item just written by the operation that triggered the cull survives a tie against equally-accessed older items.
- `'none'` — no automatic eviction. Cache grows without bound. `cull()` returns 0 and removes nothing under this policy. Manual `delete()` required.

Policies are stored in `EVICTION_POLICY` dict mapping policy names to their configuration.

## FanoutCache

Sharded cache distributing keys across multiple `Cache` instances for higher write concurrency.

```python
FanoutCache(directory=None, shards=8, timeout=0.010, disk=Disk, **settings)
```

Same key-value API as Cache: `set`, `get`, `add`, `delete`, `pop`, `incr`, `decr`, `__setitem__`, `__getitem__`, `__delitem__`, `__contains__`, `__len__`, `__iter__`, `__reversed__`, `clear`. Also supports `stats`, `volume`, `transact`, `memoize`, `touch`, `reset`, `read`, `evict`, `expire`, `cull`, `check`, `create_tag_index`, `drop_tag_index`. Supports context manager (`with FanoutCache(...) as fc:`).

Note: `size_limit` is the total size across all shards. Each shard's limit is `size_limit / shards`.

Timeout / retry behavior (differs from Cache): because sharding trades reliability for write concurrency, FanoutCache uses a small default `timeout` (`0.010`) and **fails silently on a database lock timeout** instead of raising `Timeout`. When an operation cannot acquire the shard's lock within `timeout` and `retry=False` (the default), it gives up and reports failure rather than raising: `set`/`add`/`touch` return `False`, `incr`/`decr` return `None`, and `get`/`pop` return their `default`. With `retry=True`, the operation instead blocks and retries until the lock frees, then succeeds (so `set`/`add` return `True`). `Timeout` surfaces only on unrecoverable errors.

Note: `FanoutCache` does **not** support `push`/`pull`/`peek` queue operations directly.

### Subdirectory Factories

- `cache(name, timeout=60, disk=None, **settings)` → `Cache` in subdirectory.
- `deque(name, maxlen=None)` → `Deque` in subdirectory.
- `index(name)` → `Index` in subdirectory.

## DjangoCache

Django cache backend built on `FanoutCache`. Provides the full Django cache API plus diskcache extensions.

```python
DjangoCache(directory, params)
```

`params` is a dict with keys:
- `'TIMEOUT'` — default TTL in seconds (e.g., `300`).
- `'SHARDS'` — number of shards (e.g., `4`).
- `'DATABASE_TIMEOUT'` — SQLite timeout (e.g., `0.1`).
- `'OPTIONS'` — dict of cache settings (e.g., `{'size_limit': 2**30, 'eviction_policy': 'least-recently-stored'}`).

### Standard Django Cache API

- `set(key, value, timeout=DEFAULT_TIMEOUT, version=None, read=False, tag=None, retry=True)`
- `get(key, default=None, version=None, read=False, expire_time=False, tag=False)`
- `add(key, value, timeout=DEFAULT_TIMEOUT, version=None, read=False, tag=None, retry=True)` → `True`/`False`
- `delete(key, version=None, retry=True)`
- `has_key(key, version=None)` → bool
- `clear()`
- `close(**kwargs)`
- `__contains__(key)` — same as `has_key`

### Bulk Operations

- `set_many(data, timeout=DEFAULT_TIMEOUT, version=None)` — set multiple key-value pairs.
- `get_many(keys, version=None)` → dict of found key-value pairs.
- `delete_many(keys, version=None)` — delete multiple keys.
- `get_or_set(key, default, timeout=DEFAULT_TIMEOUT, version=None)` → existing value or sets and returns default.

### Increment / Decrement / Versioning

- `incr(key, delta=1, version=None, default=None, retry=True)` → new value. `default` parameter creates key if missing (diskcache extension).
- `decr(key, delta=1, version=None, default=None, retry=True)` → new value.
- `incr_version(key, delta=1, version=None)` → new version number.
- `decr_version(key, delta=1, version=None)` → new version number.

### Expiration

- `touch(key, timeout=DEFAULT_TIMEOUT, version=None, retry=True)` → `True` if found.

### DiskCache Extensions (beyond standard Django API)

- `pop(key, default=None, version=None, expire_time=False, tag=False, retry=True)`
- `read(key, version=None)` → file handle
- `memoize(name=None, timeout=DEFAULT_TIMEOUT, version=None, typed=False, tag=None, ignore=())`
- `stats(enable=True, reset=False)` → `(hits, misses)`
- `evict(tag)`, `expire()`, `cull()`
- `create_tag_index()`, `drop_tag_index()`
- `cache(name)` → `Cache`, `deque(name, maxlen=None)` → `Deque`, `index(name)` → `Index`

Note: `retry=True` is the default for most DjangoCache methods (unlike Cache where it defaults to `False`).

## Deque

Persistent double-ended queue backed by `Cache`.

```python
Deque(iterable=(), directory=None, maxlen=None)
```

Full deque interface: `append`, `appendleft`, `pop`, `popleft`, `peek`, `peekleft`, `extend`, `extendleft`, `rotate(steps=1)`, `reverse`, `remove(value)`, `count(value)`, `index(value, start=0, stop=None)`, `copy`, `clear`, `__len__`, `__getitem__`, `__setitem__`, `__delitem__`, `__contains__`, `__iter__`, `__reversed__`, `__iadd__`, `__eq__`, `__lt__`, `__le__`, `__gt__`, `__ge__`, `transact()`.

`maxlen` is a settable property. When set, appending beyond `maxlen` evicts from the opposite end.

`directory` and `cache` are read-only properties.

Classmethod: `Deque.fromcache(cache, iterable=(), maxlen=None)` — create a Deque backed by an existing `Cache` instance. The returned deque's `.cache` property is the passed-in cache.

## Index

Persistent ordered mapping backed by `Cache`.

```python
Index(*args, **kwargs)
```

First positional arg can be a directory path (string). Implements `MutableMapping`: `__setitem__`, `__getitem__`, `__delitem__`, `__contains__`, `__len__`, `__iter__`, `__reversed__`, `keys`, `values`, `items`, `get(key, default=None)`, `update`, `setdefault(key, default=None)`, `pop(key, default=ENOVAL)` (raises `KeyError` if no default), `popitem(last=True)`, `peekitem(last=True)`, `clear`, `__eq__`, `push`, `pull`, `transact()`. Iteration is in insertion order; `popitem`/`peekitem` follow that same order — `last=True` operates on the most-recently-inserted item, `last=False` the least-recently-inserted.

`memoize(name=None, typed=False, ignore=())` — memoization decorator, same as `Cache.memoize`.

`directory` and `cache` are read-only properties.

Classmethod: `Index.fromcache(cache, *args, **kwargs)` — create an Index backed by an existing `Cache` instance. The returned index's `.cache` property is the passed-in cache.

## Disk

Handles key/value serialization for SQLite.

```python
Disk(directory, min_file_size=0, pickle_protocol=0)
```

The directory is stored as `self._directory`. Subclasses can access it to construct file paths.

- `filename(key, value)` → `(filename, full_path)` for file-backed values. Override in subclasses for custom naming. `full_path` should be constructed using `os.path.join(self._directory, filename)`.

## JSONDisk

`Disk` subclass using JSON + zlib compression.

```python
JSONDisk(directory, compress_level=1, **kwargs)
```

Usage: `Cache(directory, disk=JSONDisk, disk_compress_level=6)`.

## Constants

- `ENOVAL` — sentinel for "no value" (identity comparison).
- `UNKNOWN` — sentinel constant.
- `Timeout` — exception for SQLite timeouts (subclass of `Exception`).
- `DEFAULT_SETTINGS` — dict of default config (modifiable at runtime; new Cache instances read from it).
- `EVICTION_POLICY` — dict mapping policy names to their configuration.

## Recipes (`diskcache.recipes`)

### Lock / RLock / BoundedSemaphore

```python
Lock(cache, key, expire=None, tag=None)
RLock(cache, key, expire=None, tag=None)
BoundedSemaphore(cache, key, value=1, expire=None, tag=None)
```

Distributed synchronization primitives. Work across threads and processes. All support `acquire()`, `release()`, context manager.
- `Lock.locked()` → bool.
- `Lock` with `expire` parameter: lock auto-releases after `expire` seconds, allowing other acquirers to succeed.
- `RLock` is reentrant (same thread can acquire multiple times).
- `BoundedSemaphore` allows `value` concurrent acquisitions.

### Averager

```python
Averager(cache, key, expire=None, tag=None)
```

- `add(value)`, `get()` → current average, `pop()` → average and reset.

### throttle

```python
@throttle(cache, count, seconds, name=None, expire=None, tag=None)
```

Rate-limiting decorator. Token bucket: `count` calls per `seconds`. Sleeps when exceeded.

### barrier

```python
@barrier(cache, lock_factory, name=None, expire=None, tag=None)
```

Serialization decorator. `lock_factory` is `Lock`, `RLock`, or `BoundedSemaphore`.

### memoize_stampede

```python
@memoize_stampede(cache, expire, name=None, typed=False, tag=None)
```

Memoization with stampede protection. Decorated function gains `__cache_key__(*args, **kwargs)` which returns a tuple.

## setup.sh

Create `setup.sh` (it runs offline against the pre-installed dependencies):
```bash
pip install -e . --no-build-isolation
```
