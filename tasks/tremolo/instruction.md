# tremolo — pure-Python asynchronous HTTP/1.x server

Build `tremolo`, an asynchronous HTTP/1.x server written in **pure Python**
(`asyncio` + `socket` + `ssl`, no third-party runtime dependencies). It exposes
both a built-in routing/request/response framework and an **ASGI server** that
can host external ASGI apps. It also speaks **WebSockets** over the same port.

The package must be installable from the project root with a standard
setuptools build (an editable `pip install -e .`) and expose its public API at
the import paths listed below.

---

## Dependencies

- **The environment is OFFLINE — there is no network and you must not install
  anything.** Every dependency needed to build and test the project is already
  installed in the image. The project itself is installed for you by a
  `setup.sh` that runs *offline* against the pre-baked build backend
  (`setuptools` + `wheel`); do not add network-dependent install steps.
- **Runtime: stdlib only.** `tremolo` has *zero* third-party runtime
  dependencies — there is nothing to install. Do *not* import any third-party
  package (no `httptools`, no `uvloop`, no `websockets`, no `multidict`, no
  `pydantic`). Use `asyncio`, `socket`, `ssl`, `gzip`, `logging`,
  `multiprocessing`, etc.
- **Python 3.10+** is the target.

---

## Package layout (import paths used by callers)

Expose at least the following fully-qualified import paths. Organise the rest of
the package however you like.

```
tremolo                        -> Application, Tremolo, run, exceptions
tremolo.exceptions             -> HTTPException, HTTPRedirect,
                                  BadRequest, Unauthorized, Forbidden,
                                  NotFound, MethodNotAllowed, RequestTimeout,
                                  PreconditionFailed, PayloadTooLarge,
                                  RangeNotSatisfiable, ExpectationFailed,
                                  TooManyRequests, InternalServerError,
                                  ServiceUnavailable,
                                  WebSocketException,
                                  WebSocketClientClosed, WebSocketServerClosed
```

`Application` is an alias for the main server class `Tremolo`. `run(app, **options)`
is a one-shot helper that instantiates a server and calls `.run()`.

---

## `Application` / `Tremolo`

```python
class Tremolo:
    def __init__(self, name=None): ...

Application = Tremolo
```

- `name` (when provided) is a logger name — pass `None` for no preconfigured logger.
  **Must be a `str` or `None`** (passing other types is not supported).

### Registering routes

```python
@app.route(path, **options)
def handler(...): ...

app.route(path)(MyClass)        # class-based view
app.add_route(func_or_class, path, **options)
```

Path strings are either literal (match exact path, trailing `/` optional) or
raw regex (`^…` prefix or `…$` suffix). Named groups `(?P<name>…)` extracted
from the compiled pattern are passed to the handler as keyword arguments
named after the group.

If no route matches, respond with **404 Not Found**.

### Class-based views (CBV)

When `app.route(path)(MyClass)` is called with a class, every public method on
the class becomes a handler for the HTTP method matching its name (`get`,
`post`, `put`, `delete`, `patch`, `head`, `options`). Requests whose method
does not match any defined method must yield **405 Method Not Allowed**.

Function-based handlers do not filter by method — they receive every request
that matches their path.

### Custom error pages

```python
@app.error(code)
def my_error_handler(**server): ...
```

Re-binds the handler for HTTP error code (range `400`–`511`); raising
`ValueError` for codes outside that range. When an uncaught
(non-`HTTPException`) exception propagates from a handler, the registered
`500` error handler (if any) generates the response body.

### Hooks

```python
@app.on_worker_start
@app.on_worker_stop
@app.on_connect
@app.on_close
```

Lifecycle hooks. Registered hooks **must** run at their matching event:
`on_worker_start` once per worker during boot (before the worker accepts its
first request), `on_worker_stop` during graceful shutdown, and
`on_connect` / `on_close` on each accepted TCP connection's lifecycle.

A running server treats **`SIGTERM` and `SIGINT`** as a request for graceful
shutdown: on either signal the worker stops accepting connections, runs the
registered `on_worker_stop` hooks, and exits. (Sending `SIGTERM` to the server
process must therefore fire `on_worker_stop`, not kill the worker before it
runs.)

### Middleware

```python
@app.on_request         # runs before handler
@app.on_response        # runs after handler
```

Middleware receives the same `request` / `response` / `**server` injection as
handlers (see below) and may **raise an `HTTPException` to short-circuit**
(returning the exception's status to the client without invoking the handler).
Middleware that returns normally is followed by the route handler.

---

## Handler signatures

A handler is a regular function or coroutine. The framework inspects each
handler's signature and injects only the parameters it asks for, by name.
Recognised parameters include:

| Param        | What it is                                                      |
|--------------|-----------------------------------------------------------------|
| `request`    | the parsed `HTTPRequest`                                          |
| `response`   | the `HTTPResponse` being assembled                                |
| `websocket`  | a `WebSocket` if the request was an upgrade, else absent          |
| `**server`   | catch-all for the rest of the server-managed kwargs               |
| any named regex group | the captured string from the path                        |

Both `async def` and regular `def` handlers are supported; sync handlers are
dispatched by the server's internal executor (a separate thread) so they may
perform blocking work without halting the event loop.

### Handler return types

A non-generator handler returns `bytes`/`bytearray` (sent verbatim), `str`
(UTF-8 encoded), a `(str, encoding)` tuple (str encoded with the given codec),
or `None` (response closed without body).

An **async generator** handler (`async def` + `yield`) is streamed: each
`yield`-ed `bytes` value is sent as a chunk over `Transfer-Encoding: chunked`
on HTTP/1.1. An empty `b""` yield is permitted and produces no output — it
is **not** an end-of-stream sentinel; the generator's `StopAsyncIteration`
ends the stream.

The default response status is `200 OK`. The default `Content-Type` is
`text/html; charset=utf-8`. The `Server` response header is `Tremolo`.

The server must implement **HTTP/1.1 persistent connections**: when the
client keeps the connection alive (HTTP/1.1 default, or explicit
`Connection: keep-alive`), multiple sequential requests on the same TCP
socket are serviced in order.

A request with method `HEAD` must produce the same status line and headers
as the equivalent `GET` would, but **no body bytes** follow the headers.

---

## `HTTPRequest`

Provides the parsed view of the inbound request:

- `request.method` — bytes (`b"GET"`, `b"POST"`, …)
- `request.path` — bytes, URL path without query
- `request.query` — dict mapping (str or bytes) keys to **lists** of values.
- `request.headers` — dict-like. Header names are **normalised to lowercase
  bytes on parse**; look them up with the lowercase form. Values are **lists
  of bytes** to accommodate repeated headers.
- `request.cookies` — parsed dict from the Cookie header. Keys are cookie
  names; **values are lists of strings** (one entry per occurrence).
- `request.content_type` / `request.content_length`
- `request.ip` / `request.scheme`. `request.host` is the value of the
  inbound `Host:` header (typically `addr:port` for non-default ports).
- `await request.body()` — read and return the entire body as `bytes` /
  `bytearray`. Must transparently de-chunk `Transfer-Encoding: chunked` bodies.

---

## `HTTPResponse`

Mutates outbound response state:

- `response.set_status(code, message=None)` — set the status line. The default
  status is `200 OK`; `message` is the wire-level reason phrase that follows
  the code on the HTTP/1.1 status line (defaults to the standard phrase for
  the code). `message` accepts **bytes or str** (like `set_header` /
  `set_content_type`).
- `response.set_header(name, value)` — set a header (bytes or str on both
  sides). Setting the same header twice overwrites the previous value.
- `response.set_content_type(value)` — set the response `Content-Type`
  (bytes or str). Overrides the default `text/html; charset=utf-8`.
- `response.set_cookie(name, value="", expires=0, path="/", domain=None,
  secure=False, httponly=False, samesite=None)` — append a `Set-Cookie`
  header (the `HttpOnly` and `Secure` flags must appear when their kwargs
  are truthy).
- `await response.sendfile(path, content_type=b"application/octet-stream",
  **kwargs)` — stream a file on disk to the client. Without a `Range:` request
  header, returns the **full file** with status `200 OK`. With a
  `Range: bytes=N-M` request header, responds with **`206 Partial Content`**,
  emits a `Content-Range: bytes N-M/total` response header, and writes only
  that byte slice as the body. A multi-range request (`Range: bytes=A-B,C-D`)
  may respond with either a single 206 carrying only the first slice OR a
  `multipart/byteranges` body containing all slices.

---

## HTTP exceptions

`exceptions.HTTPException` is the base class. The standard subclasses each
carry a status `code` attribute equal to the HTTP code they represent and
accept a message body argument. Raising any of them from a handler or
middleware causes the server to emit a response with that status code.

**Uncaught (non-`HTTPException`) exceptions** raised by handlers, middleware,
or hooks must be caught by the server and surfaced as a **`500 Internal
Server Error`** response — the connection is **not** dropped silently.

`HTTPRedirect` is the redirect helper:
`raise exceptions.HTTPRedirect(message, location=url, code=302)`. Raising sets
the response status to `code` (default `302`) and emits a `Location:` response
header whose value is the `location` argument.

---

## WebSocket

A WebSocket route is declared with `@app.route(path)` — the framework upgrades
the connection when the request is a WebSocket upgrade and injects a
`websocket` kwarg (otherwise the kwarg is `None`).

`WebSocket` is the per-connection object:

- `await websocket.accept()` — complete the RFC 6455 opening handshake (respond
  `101 Switching Protocols`) so that a standard WebSocket client accepts the
  connection.
- `await websocket.receive()` — return the next message. Text frames return a
  `str`; binary frames return `bytes`.
- `await websocket.send(payload)` — send a text frame for a `str` payload, a
  binary frame for `bytes`/`bytearray`.
- `await websocket.close(code=1000)` — close the connection with the given
  WebSocket close code. The client must see a `ConnectionClosed`-style event
  carrying that exact code.

The handler is responsible for the receive loop; the server does **not** close
the WebSocket on its own when the handler returns normally.

---

## ASGI server

`Application` (or `Tremolo`) can also host an external ASGI3 app:

```python
async def asgi_app(scope, receive, send): ...

Application().run(app=asgi_app, host=..., port=..., log_level="ERROR")
```

(or use the module-level `tremolo.run(asgi_app, **options)`.)

The ASGI app must receive a real ASGI3 `(scope, receive, send)` callable contract:

- `scope["type"]` is `"http"` for HTTP requests, `"websocket"` for WS upgrades,
  and `"lifespan"` for the lifespan protocol.
- For HTTP, `scope` carries at least `method`, `path`, `query_string`,
  `headers`, and `version`. The app drains the body via `receive()` until a
  message with `more_body=False`, sends a `http.response.start` (with
  `status` + `headers`), then one or more `http.response.body` messages.
- For the **lifespan** protocol, the framework opens a single
  `scope["type"] == "lifespan"` call at startup and delivers a
  `{"type": "lifespan.startup"}` message; the app acknowledges with
  `{"type": "lifespan.startup.complete"}`. A `lifespan.shutdown` is delivered
  on graceful shutdown. If the app does not handle lifespan (the call raises
  or returns without acking), the server must continue serving HTTP without
  blocking on the missing ack.

---

## CLI

A module-level CLI is available: `python -m tremolo [OPTIONS] APP`.

`APP` is the positional argument (always last) — one of:
  - `module:name` — import path; `name` resolves to an ASGI callable.
  - `/path/to/file.py` or `/path/to/file.py:name` — file path form.

Common flags:
  - `--host <addr>` (default `127.0.0.1`)
  - `--port <n>` (default `8000`)
  - `--log-level <NAME>` (default `DEBUG`)
  - `--help` — print usage and exit 0
  - `--version` — print version and exit 0

When invoked without an `APP` argument, the CLI prints an error to
stdout and exits with non-zero status. The APP is dispatched through
the ASGI server pathway.

---

## `app.run()` parameters

```python
app.run(host="127.0.0.1", port=8000, **options)
```

Common options used by the test suite:

- `host`, `port` — bind address (positional or keyword).
- `app` — an ASGI callable to host (when set, the app is dispatched through
  the ASGI server pathway).
- `log_level` — string (`"DEBUG"`, `"INFO"`, `"ERROR"`, …).

The full set of tunables (`worker_num`, `ssl_cert`, `keepalive_timeout`,
`client_max_body_size`, `ws_max_payload_size`, etc.) is permitted but not
required to be wired beyond accepting them without error.
