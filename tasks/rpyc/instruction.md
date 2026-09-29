# RPyC (Remote Python Call)

Build `rpyc`, a transparent and symmetric distributed computing library for Python. RPyC provides transparent access to remote objects, as though they were local, via object proxying. It uses a service-based architecture for defining remote APIs and transparent proxy objects (netrefs) for seamless remote attribute access, method calls, iteration, the object-representation protocol (`repr()`/`str()`), and the context-manager protocol. Because netrefs forward `__enter__`/`__exit__` to the remote object, a remote object may be used directly in a `with` statement (e.g. a remote file handle), with entry and exit delegated to the remote side. Likewise, `repr()` and `str()` on a netref are forwarded to the remote object and return the remote object's own `repr()`/`str()` verbatim (they are **not** rendered locally as a netref-identifying placeholder such as `<netref ...>`).

## Usage Example

The canonical flow is: define a `Service` with `exposed_` methods, start a `ThreadedServer`, connect a client, and call methods through `conn.root`:

```python
import rpyc

class CalcService(rpyc.Service):
    def exposed_add(self, x, y):
        return x + y

server = rpyc.ThreadedServer(CalcService, port=0, auto_register=False)
# server.start() blocks, so run it in a background thread; server.port holds the bound port.
conn = rpyc.connect("localhost", server.port)
assert conn.root.add(3, 4) == 7
conn.close()
```

## Dependencies

The environment is **offline** and all dependencies are **already installed** — do **not** install
anything (no `pip install`, no network access).

- `plumbum` (Python package — rpyc's only runtime dependency; used for SSH tunneling and zero-deploy
  features) is pre-installed.
- `gevent` is pre-installed (needed for the optional `GeventServer`, described below).
- The `openssl` command-line tool is available (used by SSL-related functionality).
- No system services are required.

## Setup

The project is installed offline by a `setup.sh` that runs `pip install -e . --no-build-isolation`
against the pre-installed dependencies. Provide a `pyproject.toml` declaring `hatchling` as the
build backend (`build-backend = "hatchling.build"`); the build backend is pre-installed, so the
editable install resolves with no network. The only runtime dependency is `plumbum`.

## Top-Level Imports

The following must be importable from the top-level `rpyc` package:

```python
import rpyc
rpyc.Service
rpyc.VoidService
rpyc.ThreadedServer
rpyc.OneShotServer
rpyc.connect
rpyc.connect_thread
rpyc.async_
rpyc.timed
rpyc.restricted
rpyc.BgServingThread
rpyc.buffiter
rpyc.exposed                  # decorator
rpyc.service                  # decorator
rpyc.SlaveService
rpyc.classic                  # module providing classic-mode utilities
```

## Services

### `class rpyc.Service`
Base class for RPyC services.

- **`on_connect(self, conn)`**: Called when connection is established. Override for custom init.
- **`on_disconnect(self, conn)`**: Called after disconnect. Override for cleanup.
- **Exposed methods**: Methods prefixed with `exposed_` are accessible to the remote party. Non-prefixed methods are local-only.

Service subclasses may define `__init__()` with no required arguments. The connection is delivered via `on_connect()`, not the constructor.

### `class rpyc.VoidService(Service)`
A do-nothing service with no exposed methods.

### Classic Service Architecture

The classic service provides full-duplex remote Python control. It is built from layered components:

**`class Slave`** — A plain object (not a Service) that provides the core implementation for remote code execution. It maintains a `namespace` dict for executed code, and exposes `execute(code)`, `eval(code)`, `getmodule(name)` (if `name` is a tuple, joins with `"."` first), and `getconn()`. `getconn()` returns the connection to the other side, or `None` when the slave is not attached to a connection (e.g. a freshly constructed `Slave`).

**`class SlaveService(Slave, Service)`** — Exposes the Slave methods as a service. On connect, it configures the connection for full remote access (all attributes, pickle, custom exceptions enabled).

**`class MasterService(Service)`** — The client-side counterpart. On connect, it installs convenience attributes on the Connection object: `conn.modules` (a `ModuleNamespace`), `conn.execute`, `conn.eval`, `conn.namespace`, and `conn.builtins`/`conn.builtin`.

**`class ClassicService(MasterService, SlaveService)`** — Full duplex: both sides have full control. Combining `MasterService` and `SlaveService` means each endpoint both installs the master convenience attributes **and** enables full remote attribute access on its own end (the `SlaveService` capability above). Consequently, when both peers run `ClassicService`, either side may read and call attributes on a local object that has been handed to the remote as a proxy. A connection where only one side runs `ClassicService`/`SlaveService` does **not** grant attribute access on the *other* side, so such back-references would be blocked there.

### ModuleNamespace
A namespace object (returned as `conn.modules`) that lazily imports and caches modules. Supports `__getattr__` for attribute access (returns module), `__getitem__` for module names with dots (e.g., `modules["os.path"]`), and `__contains__` for checking module availability (e.g., `"os" in modules`).

## Connection

The Connection object is returned by `rpyc.connect()` and `rpyc.connect_thread()`. It manages request/reply and netref proxying. Supports context manager protocol. The `root` property returns the remote service's root object.

- **`ping(data=None, timeout=3)`**: Asserts the other party is responsive by sending data and verifying it is echoed back before the timeout.
- **`closed`** (property): `True` once the connection has been closed (e.g. via `close()` or exiting the context manager), `False` while open.

The protocol config (passed as `protocol_config` to servers or `config` to connect functions) is a dict of settings that control attribute access, exception handling, and timeouts. Key settings include `allow_all_attrs` (default `False` -- if True, allows access to non-exposed attributes), `exposed_prefix` (default `"exposed_"`), `sync_request_timeout`, and flags for pickle, custom exceptions, and attribute get/set/del permissions.

Builtin exceptions (ValueError, AttributeError, StopIteration, etc.) are re-raised on the client as their original type, not wrapped in a generic exception class.

## Servers

### `class rpyc.ThreadedServer`
Multi-threaded server (thread per connection). Constructor accepts `service` (the Service class), `authenticator` (optional callable), `registrar` (optional RegistryClient), `auto_register` (default True if registrar given), `protocol_config` (dict of overrides), and `socket_path` (Unix socket). After `start()`, the bound port is available as the `port` attribute. `close()` stops the server.

### `class rpyc.OneShotServer`
Serves exactly one connection then closes. Same constructor as ThreadedServer.

### `class rpyc.utils.server.GeventServer`
A server that uses gevent greenlets instead of threads for concurrency. Same constructor interface as ThreadedServer (accepts `service`, `port`, `authenticator`, `auto_register`, `protocol_config`). Requires `gevent` to be installed. The `start()` method blocks, so it should be spawned in a greenlet. Port is available as `server.port` after start.

## Connection Factories

- `rpyc.connect(host, port, ...)` -- socket connection.
- `rpyc.connect_stream(stream, service, config)` -- connection over an existing stream (e.g., SSL-wrapped socket).
- `rpyc.connect_thread(service=VoidService, config={}, remote_service=VoidService, remote_config={})` -- starts a server on a background thread bound to an arbitrary port and connects to it over a socket; convenient for in-process testing. `service` is the local service exposed by the returned client connection; `remote_service` is the service the background server runs, so the returned `conn.root` is the root of `remote_service`. Returns a `Connection`.
- `rpyc.ssl_connect(host, port, ...)` -- SSL-wrapped connection.

### `rpyc.core.stream.SocketStream`
The underlying stream transport for socket-based connections. Provides a class method `SocketStream.ssl_connect(host, port, ssl_kwargs, **kwargs)` that creates an SSL-wrapped stream. The `ssl_kwargs` dict may contain keys such as `certfile`, `keyfile`, `ca_certs`, `cert_reqs` (e.g., `ssl.CERT_NONE`), `check_hostname` (bool), `ciphers`, and `ssl_version`.

## Classic Mode

Accessed via `rpyc.classic`, this module provides classic-mode utilities.

### Connection functions
- `rpyc.classic.connect_thread()`: Starts a background-thread classic server and connects to it, useful for in-process testing. It runs the full-duplex classic service on **both** ends, so each side has full remote control of the other — including full attribute access on local objects handed across the connection (see Classic Service Architecture). The returned `conn` therefore supports `conn.execute`/`conn.eval`/`conn.modules` and lets the remote call back onto local objects it is given.

### Remote utilities
- `rpyc.classic.obtain(proxy) -> object`: Copies a remote object by value (via pickle).
- `rpyc.classic.deliver(conn, localobj) -> proxy`: Sends a local object to the remote side (via pickle).
- `rpyc.classic.redirected_stdio(conn)`: Context manager that redirects remote stdio to local.
- `rpyc.classic.teleport_function(conn, func, globals=None, def_=True)`: Teleports a function to the remote side using bytecode export/import.

### `class rpyc.utils.classic.MockClassicConnection`
Provides the classic-mode interface **entirely in-process, with no network and no underlying connection**. It is constructed with no arguments and wraps a local `Slave` as its `root`. Because there is no connection, `mock.root.getconn()` returns `None`.

It installs the same classic convenience attributes that `MasterService` installs on a real Connection (see above) directly on the mock object itself: `execute`, `eval`, `namespace`, `modules`, and `builtins`. These delegate to the local `Slave`, so they all share one local `namespace` dict — `mock.namespace is mock.root.namespace`, and code run via `mock.execute(...)` is visible to `mock.eval(...)` and recorded in `mock.namespace`. Because everything runs locally, `mock.modules` resolves to the **real module objects of the current process** (e.g. `mock.modules.os` is the local `os`), not remote proxies.

## Helpers

### `rpyc.buffiter(obj, chunk=10, max_chunk=1000, factor=2)`
Buffered iterator for remote iterables. Reads the remote iterator in chunks starting with `chunk`, multiplying the chunk size by `factor` each time (up to `max_chunk`). Yields individual elements. `factor` must be >= 1 (raises `ValueError` otherwise).

### `rpyc.async_(proxy) -> proxy`
Returns an async wrapper around a remote callable. When called, returns an `AsyncResult` instead of blocking.

### `rpyc.timed(proxy, timeout) -> proxy`
Returns a timed async wrapper: invoking it returns an `AsyncResult` with the expiry already set to `timeout` seconds. If the operation does not complete within `timeout`, accessing the result's `value` raises `AsyncResultTimeout`.

### `rpyc.restricted(obj, rattrs, wattrs=None) -> _Restricted`
Creates a restricted view of an object. `rattrs` is the set of readable attributes. `wattrs` is the set of writable attributes (default: same as `rattrs`). Access to other attributes raises `AttributeError`.

### `class rpyc.BgServingThread`
A background thread that calls `conn.serve()` in a loop.
- `__init__(self, conn, callback=None)`: Starts serving.
- `stop()`: Stops the background thread.

### `rpyc.utils.helpers.classpartial(cls, *args, **kwargs) -> type`
Like `functools.partial` but for classes. Returns a new class whose `__init__` has the given args pre-bound.

## Async Results (`rpyc.core.async_`)

### `class rpyc.core.async_.AsyncResult`
Represents the result of an asynchronous operation (standard future pattern: `ready`, `error`, `value`, `wait()`). Additional members:

- **`expired`** (property): `True` if the expiry time has passed.
- **`set_expiry(timeout)`**: Sets the expiry time (seconds from now).
- **`add_callback(func)`**: Adds a callback that receives the AsyncResult when ready. `func` signature: `func(async_result)`.
- `value` raises `AsyncResultTimeout` if expired.

### `class rpyc.core.async_.AsyncResultTimeout(Exception)`
Raised when an AsyncResult times out.

## Registry (`rpyc.utils.registry`)

### Constants
- `REGISTRY_PORT = 18811`

### Registry Servers (`UDPRegistryServer`, `TCPRegistryServer`)
Service registry servers (UDP and TCP variants). Constructor accepts `host`, `port` (default `REGISTRY_PORT`), `pruning_timeout`, `logger`, and `allow_listing` (default False). Methods: `start()` (blocking), `close()`. Registry servers bind their listening socket at construction, so when `port=0` is passed the OS-assigned ephemeral port is available via the `port` attribute immediately, before `start()` is called.

### Registry Clients (`UDPRegistryClient`, `TCPRegistryClient`)
Clients for discovering services. Constructor accepts `ip` as the first argument (the registry server's address). Both provide:
- `discover(name) -> tuple`: Returns `((host, port), ...)`.
- `register(aliases, port, interface="") -> bool`: Returns True on success. The server files each entry under the **source/peer IP** of the registering request (the address the registration arrives from), not under the `interface` argument — so with the default empty `interface`, a registration from `127.0.0.1` is recorded under host `127.0.0.1`.
- `unregister(port)`: Unregisters.
- `list(filter_host=None) -> tuple`: Lists registered services (requires `allow_listing=True` on server). Returns a tuple of the registered service alias name strings (aliases are stored uppercased). When `filter_host` is given, only services whose recorded host (the source IP they registered from, per `register` above) equals `filter_host` are returned; an unrelated host therefore matches nothing.

## Authenticators (`rpyc.utils.authenticators`)

### `class rpyc.utils.authenticators.AuthenticationError(Exception)`
Raised to signal failed authentication. When the server's authenticator rejects a connection, the server closes the socket. On the client side, `rpyc.connect()` (and `ssl_connect` / `connect_stream`) still **return a `Connection` object without raising** — the rejection is not surfaced during `connect()` itself. It surfaces as `EOFError` only on the client's first attempt to **use** that connection (a remote call such as `conn.root.<method>()`, or `conn.ping()`).

### `class rpyc.utils.authenticators.SSLAuthenticator`
SSL certificate-based authenticator for servers. Constructor takes `keyfile`, `certfile`, `ca_certs=None`, `cert_reqs=None`, `ssl_version=None`, `ciphers=None`. If `ca_certs` is provided and `cert_reqs` is None, defaults to `ssl.CERT_REQUIRED`. If `ca_certs` is None and `cert_reqs` is None, defaults to `ssl.CERT_NONE`. The constructor arguments are stored as same-named public attributes (e.g. `ca_certs`, and the resolved `cert_reqs`). When called with a socket, wraps it with SSL and raises `AuthenticationError` on SSL errors.

## Exposed/Service Decorators

### `@rpyc.exposed`
Decorator that marks a method or nested class to be exposed over a connection. When used with `@rpyc.service`, the decorated item becomes accessible to the remote party. Can also be applied to nested classes inside a service, which are then recursively processed by `@rpyc.service`.

### `@rpyc.service`
Class decorator for Service subclasses. Finds all `@rpyc.exposed`-marked methods and classes and makes them accessible over a connection by also binding them with the `exposed_` prefix. For exposed nested classes, it recurses to process their `@rpyc.exposed` methods as well.
