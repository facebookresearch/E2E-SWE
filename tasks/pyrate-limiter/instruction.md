# PyrateLimiter — Implementation Specification

## Overview

PyrateLimiter is a Python rate-limiting library implementing the **Leaky Bucket Algorithm**. It enables controlling the rate at which operations are permitted, supporting configurable rate limits, multiple storage backends, both synchronous and asynchronous workflows, and thread-safe concurrent access.

The library enables users to:
- Define rate limits with configurable intervals (requests per second/minute/hour/day/week)
- Apply rate limiting with blocking or non-blocking behaviour
- Use multiple storage backends (in-memory, SQLite)
- Support both sync and async workflows with proper event-loop integration
- Rate-limit functions via decorators (sync and async)
- Share limiters safely across threads

## Package Name

The package is named `pyrate_limiter` and must be installable via `pip install .` from the project root.

## Dependencies

The environment is **offline**: every dependency below is already installed, and the project itself
is installed for you by a `setup.sh` that runs offline (an editable install). **Do not install
anything** — there is no network access, so any `pip install` / `apt-get` will fail. Just implement
the library against the pre-installed packages and services.

Core: Python >= 3.10. The core leaky-bucket logic and the in-memory / SQLite / multiprocess buckets
require no external packages.

Pre-installed packages used by the optional backends and the HTTP-client integrations:
- `filelock` — for SQLite file locking in multi-process scenarios
- `redis` — for `RedisBucket` (both sync and `redis.asyncio` clients)
- `psycopg[pool]` (i.e. `psycopg` + `psycopg_pool`) — for `PostgresBucket` and `PostgresClock`
- `httpx` — for the HTTPX transport integrations
- `requests` — for the requests session integration
- `aiohttp` — for the aiohttp session integration

Pre-installed and running system services (already started — do not start or install them yourself
when self-testing, they are available on localhost):
- **Redis** on `localhost:6379` — backs the `RedisBucket` tests.
- **PostgreSQL** on `localhost:5432` (user `postgres`, password `postgres`) — backs the
  `PostgresBucket` tests.

## Core Data Types

### 1. Duration (Enum)

An enumeration of common time intervals, all in **milliseconds**.

**Location**: `pyrate_limiter.Duration`

| Member | Value (ms) |
|--------|-----------|
| `SECOND` | 1 000 |
| `MINUTE` | 60 000 |
| `HOUR` | 3 600 000 |
| `DAY` | 86 400 000 |
| `WEEK` | 604 800 000 |

**Arithmetic operations** (all return `int`):
- Multiply: `Duration.SECOND * 2` → `2000`; `3 * Duration.SECOND` → `3000`
- Add: `Duration.SECOND + Duration.MINUTE` → `61000`
- Int conversion: `int(Duration.HOUR)` → `3600000`
- Equality: `Duration.SECOND == 1000` → `True`

**Static method**:
- `Duration.readable(value: int) -> str` — convert an integer millisecond value to a human-readable string. Uses the largest fitting unit with one decimal place. Examples: `300` → `"300ms"`, `1000` → `"1.0s"`, `1500` → `"1.5s"`, `60000` → `"1.0m"`, `3600000` → `"1.0h"`, `86400000` → `"1.0d"`, `604800000` → `"1.0w"`. Unit suffixes are: `w`, `d`, `h`, `m`, `s`, `ms`. Note: pass `int(Duration.MINUTE)` when converting a Duration member (the method expects a plain int, not a Duration enum).

---

### 2. Rate

Defines a rate-limit rule: at most `limit` acquisitions within a sliding window of `interval` milliseconds.

**Location**: `pyrate_limiter.Rate`

```python
Rate(limit: int, interval: Union[int, Duration])
```

- `limit` — maximum number of requests allowed
- `interval` — time window in milliseconds (or a `Duration` value)

Properties: `limit` (int), `interval` (int).

**String representation**: `str(Rate(5, Duration.SECOND))` produces `"limit=5/1.0s"` (uses `Duration.readable()` for the interval). `repr()` uses raw milliseconds: `"limit=5/1000"`.

---

### 3. RateItem

A timestamped item placed into a bucket.

**Location**: `pyrate_limiter.RateItem`

```python
RateItem(name: str, timestamp: int, weight: int = 1)
```

- `name` — identifier
- `timestamp` — time in milliseconds
- `weight` — how many "slots" the item consumes (default 1)

---

## Limiter (Main API)

### 4. Limiter

The main user-facing API. Both `try_acquire` and `try_acquire_async` must work correctly with any bucket type, including async buckets such as `BucketAsyncWrapper`.

**Location**: `pyrate_limiter.Limiter`

```python
Limiter(
    argument: Union[AbstractBucket, Rate, List[Rate]],
    buffer_ms: int = 50,
)
```

- `argument` — a single `Rate`, a list of `Rate`s (auto-creates `InMemoryBucket`), or an `AbstractBucket`.
- `buffer_ms` — extra delay buffer in ms added to computed wait times (default 50).

#### `try_acquire`

```python
def try_acquire(
    self,
    name: str = "pyrate",
    weight: int = 1,
    blocking: bool = True,
    timeout: int | float = -1,
) -> Union[bool, Awaitable[bool]]
```

Acquire a permit. In blocking mode (default), sleeps until a permit is available. In non-blocking mode (`blocking=False`), returns `False` immediately if the limit is exceeded.

- `weight` — number of permits to consume (items with weight > 1 are stored as multiple unit items; insertion is atomic). **Special case**: `weight=0` always returns `True` immediately without consuming any capacity, useful for health checks or metadata queries.
- `timeout` — maximum wait time in seconds; -1 means indefinite. Returns `False` on timeout.

**Parameter validation**:
- `blocking=False` with `timeout != -1` raises `RuntimeError("Can't set timeout with non-blocking")`.
- `timeout < 0` and `timeout != -1` raises `ValueError("timeout must be -1 or >= 0")`.

**Unacquirable weight**: If `weight` exceeds the bucket's maximum capacity (e.g., `weight=10` on a `Rate(5, ...)` bucket), `try_acquire` returns `False` immediately even in blocking mode, rather than blocking forever.

#### `try_acquire_async`

```python
async def try_acquire_async(
    self,
    name: str = "pyrate",
    weight: int = 1,
    blocking: bool = True,
    timeout: int | float = -1,
) -> bool
```

Async variant. Uses a thread-local `asyncio.Lock` internally. Same parameter validation rules as `try_acquire`.

#### `as_decorator`

```python
def as_decorator(self, *, name: str = "ratelimiter", weight: int = 1)
```

Returns a decorator for sync or async functions. Automatically detects coroutine functions and uses the async path.

#### Other methods

- `buckets() -> List[AbstractBucket]` — return the list of buckets the limiter is currently managing. When the limiter is constructed from a `Rate` or `List[Rate]`, the auto-created `InMemoryBucket` is one such active bucket, so `buckets()` returns a single-element list while the limiter is open. After `close()` (whether called directly or via `__exit__`) the limiter releases its buckets, so `buckets()` returns `[]` (an empty list).
- `close()` — release resources (background threads, buckets, etc.). `close()` is idempotent — calling it more than once (e.g. after the context manager has already exited) is safe and does not raise.
- Context manager protocol (`__enter__` / `__exit__`). `__exit__` always calls `close()` (releasing all active buckets so `buckets()` returns `[]` afterward) and does **not** suppress exceptions — an exception raised inside the `with` block propagates out, and the buckets are still released.

---

## Bucket Backends

Buckets provide different storage backends for the `Limiter`. Users typically create a bucket and pass it to `Limiter(bucket)`, then interact through the Limiter's `try_acquire` / `try_acquire_async` API. The bucket handles the underlying storage and rate-checking logic.

### 5. AbstractBucket (ABC)

Base class for bucket implementations.

**Location**: `pyrate_limiter.AbstractBucket`

Abstract methods: `put`, `leak`, `count`, `peek`, `flush`.

Concrete methods:
- `now() -> int` — retrieve the current timestamp in milliseconds from the bucket's clock backend.
- `waiting(item: RateItem) -> int` — calculate milliseconds until the bucket has capacity for `item`. Returns `0` if ready, positive int for wait time, `-1` if `item.weight` exceeds the rate limit (can never fit). The wait is measured **relative to the queried `item.timestamp`**, not the live `now()` clock: it is the time until the earliest currently-counted item that is blocking the failing rate would expire.
- `close()` — release resources. Subclasses may override.
- Context manager protocol (`__enter__` / `__exit__`).

Properties:
- `rates` (List[Rate]) — the configured rates.
- `failing_rate` (Optional[Rate]) — the rate that caused the last `put()` to fail, or `None`.

---

### 6. InMemoryBucket

In-memory bucket using a Python list.

**Location**: `pyrate_limiter.InMemoryBucket`

```python
InMemoryBucket(rates: List[Rate])
```

Methods:
- `put(item: RateItem) -> bool` — add item; returns `True` on success, `False` if any rate exceeded. When it returns `False`, the bucket's `failing_rate` attribute is set to the `Rate` that was exceeded.
- `leak(current_timestamp: int) -> int` — remove items older than the maximum rate interval relative to `current_timestamp`; returns count of items removed.
- `count() -> int` — total weighted count of items in the bucket. An item with `weight=3` counts as 3.
- `peek(index: int) -> Optional[RateItem]` — peek at item at index in **latest-to-earliest** order. `peek(0)` returns the most recently added item, `peek(count-1)` returns the oldest. Returns `None` if index is out of bounds.
- `flush() -> None` — clear all items and reset `failing_rate`.
- `waiting(item: RateItem) -> int` — calculate how many milliseconds until the bucket has capacity for `item`. Returns `0` if the bucket is ready, a positive integer for the wait time, or `-1` if the item's weight exceeds the bucket's maximum capacity (can never fit). The wait is measured relative to the queried `item.timestamp`, not the live clock — see `AbstractBucket.waiting`.

---

### 7. SQLiteBucket

SQLite-backed bucket for **persistent** rate limiting. State survives across different bucket/limiter instances that connect to the same `db_path`.

**Location**: `pyrate_limiter.SQLiteBucket`

```python
@classmethod
def init_from_file(
    cls,
    rates: List[Rate],
    table: str = "rate_bucket",
    db_path: Optional[str] = None,
    create_new_table: bool = True,
    use_file_lock: bool = False,
) -> "SQLiteBucket"
```

- `rates` — rate configurations
- `table` — SQLite table name
- `db_path` — path to database file (temp file if `None`)
- `create_new_table` — create the table if it doesn't exist
- `use_file_lock` — enable file locking for multi-process access (requires `filelock`)

Same methods as `InMemoryBucket`, plus `close()` to release the database connection.

---

### 8. MultiprocessBucket

Bucket for multiprocessing environments using shared memory.

**Location**: `pyrate_limiter.MultiprocessBucket`

```python
@classmethod
def init(cls, rates: List[Rate]) -> "MultiprocessBucket"
```

---

### 9. RedisBucket

Bucket backed by Redis sorted sets for distributed rate limiting across multiple application instances.

**Location**: `pyrate_limiter.RedisBucket`

```python
@classmethod
def init(cls, rates: List[Rate], redis, bucket_key: str) -> Union["RedisBucket", Awaitable["RedisBucket"]]
```

- `rates` — rate configurations
- `redis` — a `redis.Redis` (sync) or `redis.asyncio.Redis` (async) client instance. The same `init` method works for both; if an async client is provided, `init` returns an awaitable that resolves to a `RedisBucket`, and all bucket methods also return awaitables.
- `bucket_key` — Redis key name for the sorted set

The bucket stores items with millisecond timestamps and performs an atomic check-and-insert: `put()` succeeds (returns `True`) only if every configured rate window still has capacity, otherwise it returns `False`. This check-and-insert is atomic, so the bucket stays correct under concurrent access from multiple processes or machines.

Methods (same interface as other buckets):
- `put(item)` — atomically checks every configured rate window and inserts the item(s) iff all windows have capacity; returns `True` on insert, `False` otherwise.
- `leak(current_timestamp)` — removes items older than the maximum rate interval relative to `current_timestamp`.
- `count()` — returns the number of items currently stored.
- `peek(index)` — returns the item at `index` in latest-to-earliest order (or `None`).
- `flush()` — removes all items for this bucket key.

Timestamps come from a local monotonic clock, not the Redis server clock.

---

### 10. PostgresBucket

Bucket backed by PostgreSQL for rate limiting with database-level locking.

**Location**: `pyrate_limiter.PostgresBucket`

```python
PostgresBucket(pool: ConnectionPool, table: str, rates: List[Rate])
```

- `pool` — a `psycopg_pool.ConnectionPool` instance
- `table` — table name suffix (actual table created is `ratelimit___{table}`)
- `rates` — rate configurations

The table is auto-created if it doesn't exist. Multiple independent instances may create `PostgresBucket` on the same table concurrently, so table creation must be safe under concurrent access. Check-and-insert on the same table is atomic and serialized across concurrent writers: at most one writer performs the count-and-insert at a time, so within a single rate window successful acquisitions never exceed the window's capacity. Contention is handled fail-fast at the database level — if another concurrent transaction is already performing a check-and-insert on the same table, the call returns `False` immediately instead of blocking or retrying.

Uses `PostgresClock` internally for timestamps.

Methods: same interface as other buckets (`put`, `leak`, `count`, `peek`, `flush`, `close`).

**Location of PostgresClock**: `pyrate_limiter.PostgresClock`

```python
PostgresClock(pool: ConnectionPool)
```

Falls back to local monotonic time if the DB query fails.

---

### 11. BucketAsyncWrapper

Wraps a synchronous bucket to make all methods async-compatible, so the limiter uses `asyncio.sleep` instead of `time.sleep`.

**Location**: `pyrate_limiter.BucketAsyncWrapper`

```python
BucketAsyncWrapper(bucket: AbstractBucket)
```

All bucket methods become coroutines.

---

## Factory Module

**Location**: `pyrate_limiter.limiter_factory`

### `create_inmemory_limiter`

```python
def create_inmemory_limiter(
    rate_per_duration: int = 3,
    duration: Union[int, Duration] = Duration.SECOND,
    buffer_ms: int = 50,
) -> Limiter
```

### `create_sqlite_limiter`

```python
def create_sqlite_limiter(
    rate_per_duration: int = 3,
    duration: Union[int, Duration] = Duration.SECOND,
    db_path: Optional[str] = None,
    table_name: str = "rate_bucket",
    buffer_ms: int = 50,
    use_file_lock: bool = False,
) -> Limiter
```

### `init_global_limiter`

```python
def init_global_limiter(bucket: AbstractBucket, buffer_ms: int = 50) -> None
```

Sets a module-level `LIMITER` global. Intended for `ProcessPoolExecutor` initializers.

---

## HTTP Client Integrations

### HTTPX Integration

**Location**: `pyrate_limiter.extras.httpx_limiter`

#### RateLimiterTransport

Synchronous HTTPX transport with rate limiting. Subclasses `httpx.HTTPTransport`.

```python
class RateLimiterTransport(httpx.HTTPTransport):
    def __init__(self, limiter: Limiter, **kwargs)
```

Overrides `handle_request()` to call `limiter.try_acquire()` before delegating to the parent transport. All keyword arguments are passed through to `HTTPTransport`.

#### AsyncRateLimiterTransport

Asynchronous HTTPX transport with rate limiting. Subclasses `httpx.AsyncHTTPTransport`.

```python
class AsyncRateLimiterTransport(httpx.AsyncHTTPTransport):
    def __init__(self, limiter: Limiter, **kwargs)
```

Overrides `handle_async_request()` to call `await limiter.try_acquire_async()` before delegating.

### Requests Integration

**Location**: `pyrate_limiter.extras.requests_limiter`

#### RateLimitedRequestsSession

A `requests.Session` subclass with built-in rate limiting.

```python
class RateLimitedRequestsSession(requests.Session):
    def __init__(self, limiter: Limiter, name: str = __name__, **_)
```

Overrides `request()` to call `limiter.try_acquire(name)` before delegating to `super().request()`.

### aiohttp Integration

**Location**: `pyrate_limiter.extras.aiohttp_limiter`

#### RateLimitedSession

An async HTTP session wrapping `aiohttp.ClientSession` with rate limiting.

```python
class RateLimitedSession:
    def __init__(self, limiter: Limiter, name: str = "pyrate", **kwargs)
```

- `limiter` — the rate limiter
- `name` — key for rate limiting bucket
- `**kwargs` — passed to `aiohttp.ClientSession`

Methods:
- `async get(*a, **k)` — calls `await limiter.try_acquire_async(name)` then `await session.get(*a, **k)`
- `async post(*a, **k)` — same pattern for POST
- Supports async context manager (`async with RateLimitedSession(...) as session:`)

---

## Implementation Notes

1. **Time units**: All times in the library are in **milliseconds**.
2. **Thread safety**: `Limiter` uses `threading.RLock` for thread-safe access.
3. **Async safety**: `try_acquire_async` additionally uses a thread-local `asyncio.Lock`.
4. **Leaking**: A background daemon thread periodically removes expired items from buckets.
5. **Weight**: Items with `weight > 1` are expanded into multiple unit items. Insertion is atomic — either all fit or none are inserted.
6. **Blocking**: In blocking mode, the limiter sleeps (`time.sleep` or `asyncio.sleep`) until a permit becomes available. In non-blocking mode, it returns `False` immediately.
7. **Rate ordering**: When using multiple rates, they must be ordered from smallest interval to largest.
