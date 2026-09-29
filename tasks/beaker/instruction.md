# Beaker

Build `beaker`, a Python library for web session management and general-purpose caching.

## Dependencies

The environment is **offline** — every dependency is already installed, and you must not attempt to install anything (there is no network). The project itself is installed by a `setup.sh` that runs offline (for a Python project, a `setup.py` / `pyproject.toml` installable with `pip install -e . --no-build-isolation`).

`beaker` itself has **no mandatory runtime dependencies** (it is pure-Python over the stdlib). The following backend/encryption libraries are pre-installed and used by the optional backends below:

- `redis` — for the `ext:redis` cache/session backend (a `redis-server` service is running locally).
- `python-memcached` — for the `ext:memcached` backend (a `memcached` service is running locally).
- `sqlalchemy` — for the `ext:sqla` cache/session backend.
- `pycryptodome` and `cryptography` — for AES session encryption (`crypto_type='pycrypto'` uses PyCryptodome, `crypto_type='cryptography'` uses pyca/cryptography).

## Package Structure

Importable as `beaker`. Key imports:
- `beaker.cache`: `Cache`, `CacheManager`, `cache_regions`, `cache_region`, `region_invalidate`
- `beaker.session`: `Session`, `SignedCookie`, `InvalidSignature`
- `beaker.middleware`: `SessionMiddleware`, `CacheMiddleware`
- `beaker.exceptions`: `BeakerException`
- `beaker.util`: `parse_cache_config_options`

## Cache

Constructor: `Cache(namespace, type='memory', expire=None, **nsargs)`. Backend types: `'memory'`, `'dbm'`, `'file'` (pass `data_dir`), `'ext:redis'` (pass `url`), `'ext:memcached'` (pass `url`), `'ext:sqla'` (pass `bind` engine + `table` + `data_dir`). Dict-like interface plus `put(key, value)`, `get(key, createfunc=None)` (where `createfunc` auto-populates on miss; if the key is missing and `createfunc` is `None`, `get()` raises `KeyError`), `remove(key)`, `has_key(key)`.

File and dbm backends support concurrent access from multiple threads via file-level locking.

External backend dependencies: Redis requires `redis` package, `url='redis://localhost:6379/0'`. Memcached requires `python-memcached` package, `url='127.0.0.1:11211'`. SQLAlchemy requires `sqlalchemy` package; cache table columns: `namespace` (String(255), primary key), `accessed` (DateTime), `created` (DateTime), `data` (PickleType); pass `bind=engine, table=cache_table, data_dir=dir`.

## CacheManager

Constructor: `CacheManager(cache_regions={'short': {'type': 'memory', 'expire': 60}})`. Methods: `get_cache(name, **kwargs)` (returns a Cache for the given namespace using the manager's default backend/options, overridden by any explicit kwargs), `get_cache_region(name, region)` (raises `BeakerException` for unconfigured regions), `region()` decorator, `region_invalidate()`, `cache(namespace, type=None, expire=None, ...)` decorator — caches function results keyed by namespace + args with explicit backend type and expiration (does not require pre-configured regions).

## Cache Region Decorators

Module-level `cache_regions` dict configures regions. `@cache_region(region, *args)` caches function results and preserves the wrapped function's `__name__` and `__doc__` attributes (decorator transparency). `region_invalidate(func, region, *args)` clears cached values.

The cache key is derived from the function's module + name, the decorator's extra positional `*args`, and the positional args passed to the function at call time (in that order). The decorator's extra `*args` therefore participate in the key — they act as an additional namespace component that distinguishes functions sharing the same name. To invalidate a specific cached call, `region_invalidate(func, region, *args)` must be passed the **same** extra args given to `@cache_region(region, *args)`, followed by the positional call args used at the call site, so both sides reconstruct an identical key. For example, with `@cache_region('myregion', 'alias')` decorating `f(x, y)`, the entry produced by `f(1, 2)` is cleared by `region_invalidate(f, 'myregion', 'alias', 1, 2)`. The same contract applies to the manager-bound `CacheManager.region(region, *args)` / `CacheManager.region_invalidate(func, region, *args)`.

Kwargs are normalized to positional order — `func(1, c=3, b=2)` produces the same key as `func(1, 2, 3)`. `self`/`cls` are dropped so different instances share a cache.

## Session

Constructor: `Session(request_environ, type=None, data_dir=None, key='beaker.session.id', timeout=None, secret=None, encrypt_key=None, validate_key=None, data_serializer='pickle'` (also supports `'json'`), `use_cookies=True, invalidate_corrupt=False, id=None, cookie_domain=None, cookie_path='/', ...)`.

Dict subclass. Types: `'memory'`, `'file'`, `'dbm'`, `'cookie'` (pure cookie-based, requires `validate_key`), `'ext:redis'`, `'ext:memcached'`, `'ext:sqla'`. Methods: `save()`, `delete()`, `invalidate()`, `revert()`, `regenerate_id()`, `load()`, `get_by_id(id)` (returns a new Session loaded with data for the given ID, using the same backend configuration). Properties: `id`, `is_new`, `created`. Encryption via `crypto_type`: `'pycrypto'` (default, PyCryptodome) or `'cryptography'` (pyca). `cookie_domain` sets cookie Domain (cross-subdomain), `cookie_path` sets cookie Path (default `'/'`). `invalidate_corrupt=True` discards corrupted data instead of raising. `timeout` is a session-inactivity lifetime in seconds: when a stored session is loaded more than `timeout` seconds after it was last saved/accessed, its data is discarded and it is treated as a new, empty session (`is_new` is `True`); `timeout=None` (default) disables expiry.

## SignedCookie

HMAC-SHA1 signed cookie. `SignedCookie(secret)` extends `SimpleCookie`. `InvalidSignature` is a falsy singleton returned on tampered values.

## SessionMiddleware

`SessionMiddleware(app, config={}, **kwargs)`. Config keys prefixed `session.` or `beaker.session.`; the same prefixed keys may be supplied either as entries of `config` or as keyword arguments. Exposes lazy session at `environ['beaker.session']`. `session.auto=True` saves after every request. `session.accessed_time=True` saves on read access (distinct from auto). Cookie sessions: `session.type='cookie'` + `session.validate_key` (HMAC signing); add `session.encrypt_key` to enable AES encryption. File encryption: `session.encrypt_key` + `session.validate_key`. Signing (non-cookie sessions): `session.secret`.

## CacheMiddleware

Exposes `CacheManager` at `environ['beaker.cache']`. Config keys prefixed `cache.`.

## Configuration Parsing

`beaker.util.parse_cache_config_options(config)` takes a flat dict with `cache.`-prefixed keys, coerces types (`'300'` -> `300` for `expire`). `cache.regions` (comma-separated) triggers per-region extraction from `cache.<region>.type`, `cache.<region>.expire`, etc. into `options['cache_regions']`.

## Exceptions

`BeakerException` — base exception for all beaker errors.

## setup.sh

```bash
pip install -e . --no-build-isolation
```
