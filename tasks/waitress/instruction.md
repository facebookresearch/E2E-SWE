# waitress — Multi-Threaded WSGI Server

Build **waitress**, a production-quality multi-threaded WSGI server for Python. Waitress serves WSGI applications over HTTP using an async I/O event loop for connection management and a thread pool for request handling.

**Version**: 3.0.2

## Environment & Dependencies

The environment is **offline** — there is no network access, and every dependency you need is
**already installed**. Do **not** install or download anything.

**Runtime dependencies**: None. Waitress is pure Python and uses only the standard library, so there
are no third-party packages to import or install.

The project is installed for you by a `setup.sh` that runs **offline** (it performs
`pip install -e . --no-build-isolation` against the pre-installed build backend). Place your
implementation so that an editable install picks it up; you do not need to run any install command
yourself.

---

## Core API

### `waitress.serve(app, **kw)`

Blocking function — creates server and runs the event loop. `app` is a WSGI callable `(environ, start_response) -> iterable`.

### `waitress.create_server(app, **kw)`

Non-blocking — creates and returns a server. Call `server.run()` to start (blocking). Returns `TcpWSGIServer`, `UnixWSGIServer`, or `MultiSocketServer`.

Server attributes: `effective_host`, `effective_port`. Methods: `run()` (blocking), `close()`.

---

## Configuration (`waitress.adjustments.Adjustments`)

All `**kw` to `serve()`/`create_server()` are Adjustments parameters:

- `host` (str, `"0.0.0.0"`), `port` (int, `8080`) — listen address
- `listen` (str list) — alternative to host/port, e.g. `"0.0.0.0:8080"`
- `threads` (int, `4`) — worker thread count
- `url_prefix` (str, `""`) — SCRIPT_NAME prefix added to environ
- `url_scheme` (str, `"http"`) — wsgi.url_scheme default (e.g., `"https"`)
- `expose_tracebacks` (bool, False) — include traceback in 500 error responses
- `ident` (str, `"waitress"`) — Server response header value
- `max_request_header_size`, `max_request_body_size` — request size limits (see HTTP Request Handling for the over-limit rejection behavior)
- `trusted_proxy` (str or `"*"`) — IP of trusted proxy; enables proxy header processing
- `trusted_proxy_count` (int) — number of trusted proxies between the server and the real client. Of the `X-Forwarded-For` chain (leftmost = original client), the rightmost `trusted_proxy_count` entries are kept and the **leftmost of that kept slice** becomes `REMOTE_ADDR`. Example: for `X-Forwarded-For: a, b, c` with `trusted_proxy_count=1`, the rightmost entry `c` becomes `REMOTE_ADDR`; with `trusted_proxy_count=2`, `b` becomes `REMOTE_ADDR`
- `trusted_proxy_headers` (set of str) — which proxy headers to trust (e.g., `{"x-forwarded-for", "x-forwarded-proto", "x-forwarded-host"}`)
- `clear_untrusted_proxy_headers` (bool, True) — remove untrusted proxy headers
- `channel_timeout` (int, 120), `connection_limit` (int, 100)
- `backlog` (int, 1024), `recv_bytes` (int, 8192)

Mutual exclusion: `host`/`port`, `listen`, `sockets`, `unix_socket` are mutually exclusive. Passing `host` and/or `port` **together with** `listen` (or with `sockets`, or with `unix_socket`) raises `ValueError`; likewise combining `listen`, `sockets`, and `unix_socket` with each other raises `ValueError`. This is keyed on whether the argument was *supplied* as a keyword — passing `host`/`port` alongside `listen` raises even when the given `host`/`port` equal their defaults (`"0.0.0.0"`/`8080`), so supplying `listen`/`sockets`/`unix_socket` requires that `host` and `port` not be passed at all. Unknown parameters also raise `ValueError`.

---

## WSGI Compliance

The server builds a standard WSGI environ dict with: `REQUEST_METHOD`, `PATH_INFO`, `QUERY_STRING`, `CONTENT_TYPE`, `CONTENT_LENGTH`, `SERVER_NAME`, `SERVER_PORT`, `REMOTE_ADDR`, `HTTP_HOST`, `wsgi.url_scheme`, `wsgi.input` (file-like object for reading the request body), `SCRIPT_NAME`, plus all HTTP request headers mapped as `HTTP_*` keys (e.g., `Accept` → `HTTP_ACCEPT`, `X-Custom` → `HTTP_X_CUSTOM`).

`start_response(status, response_headers)` returns a `write` callable. The app returns an iterable of byte chunks. The response headers supplied by the app are sent to the client **unchanged** except that each header name is normalized to capitalized-hyphenated form (e.g. `content-type` → `Content-Type`); the header **value** (including any parameters such as `; charset=utf-8`) is preserved verbatim.

Every response includes a `Date` header whose value is the current time as an RFC 7231 HTTP-date, unless the app already supplied one.

The response status line echoes the **same** HTTP version as the request: an `HTTP/1.0` request receives an `HTTP/1.0 ...` status line, an `HTTP/1.1` request an `HTTP/1.1 ...` status line.

The server handles:
- All standard HTTP methods (GET, POST, PUT, DELETE, HEAD, etc.)
- HTTP/1.0 and HTTP/1.1. HTTP/1.1 connections are persistent (keep-alive) by default. HTTP/1.0 connections are non-persistent by default: the server sends `Connection: close` and closes the socket after a single response. When an HTTP/1.0 client sends `Connection: keep-alive`, the server honors it — it echoes `Connection: Keep-Alive` and keeps the connection open for further requests.
- HTTP pipelining — multiple requests sent on the same connection without waiting for responses. Responses must be serialized in request order on the same connection.
- Chunked transfer encoding (request and response)
- Content-Length-based body reading
- HEAD requests (response body suppressed)
- Error responses (500) when the app raises exceptions. With `expose_tracebacks=True`, the 500 response body includes the traceback text; with `expose_tracebacks=False` (default), it is hidden. This 500 substitution only applies while **no** response data has been sent yet. For a streaming response (no `Content-Length`), the status line, headers, and any body chunks already produced are flushed to the client as they are generated; once any response data has been sent, an exception raised later by the app can **no longer** be converted into a 500 — the already-sent partial data stands and the connection is then closed/finalized.

---

## HTTP Request Handling

**Request size limits.** When an inbound request's headers exceed `max_request_header_size`, or its declared/received body exceeds `max_request_body_size`, the server **rejects** the request: instead of dispatching it to the WSGI app, it sends back an HTTP client-error (4xx) status line on the connection — `431` (Request Header Fields Too Large) for oversized headers and `413` (Request Entity Too Large) for an oversized body — and then closes the connection. A client reading the socket therefore observes a 4xx status line rather than the app's response or a silently dropped/truncated request.

---

## Proxy Headers

When `trusted_proxy` is configured, the server processes `X-Forwarded-For`, `X-Forwarded-Host`, `X-Forwarded-Proto`, `X-Forwarded-Port`, and RFC 7239 `Forwarded` headers, modifying the environ accordingly.

---

## CLI (`waitress-serve`)

Entry point: `waitress-serve = waitress.runner:run`

Usage: `waitress-serve [OPTIONS] MODULE:OBJECT`

`waitress-serve` resolves `MODULE:OBJECT` by importing `MODULE` and looking up `OBJECT`. The current working directory is prepended to `sys.path` before resolution, so a module living in the directory you run the command from is importable (e.g. run `waitress-serve myapp:app` from the project root). With `--call`, the resolved object is **called** and its return value is used as the WSGI app (i.e. `OBJECT` is treated as an app factory); without `--call` the object is used directly.

Options mirror Adjustments parameters: `--host`, `--port`, `--listen`, `--threads`, `--unix-socket`, `--url-prefix`, `--[no-]expose-tracebacks`, `--call` (call the resolved object), `--help`.

---

## setup.sh

The project is installed offline via:

```bash
pip install -e . --no-build-isolation
```
