# websockets — WebSocket Protocol Implementation

Build **websockets**, a Python library implementing the WebSocket protocol (RFC 6455) with asyncio and threading APIs. The library provides a Sans-I/O protocol core, frame encoding/decoding, HTTP/1.1 upgrade handshake, and permessage-deflate compression.

**Version**: 16.1
**Dependencies**: None (pure Python, stdlib only).

The environment is **offline**: all build/test tooling is already installed and there is no network access — do **not** install anything. The project is installed for you by a `setup.sh` that runs offline (`pip install -e . --no-build-isolation`). Just implement the package; the harness builds and tests it.

---

## Architecture

Three layers sharing common modules:
1. **Sans-I/O Protocol** — state machine, no I/O
2. **Asyncio API** — async server/client
3. **Sync API** — threaded server/client

---

## Usage

The high-level APIs are a server `serve(handler, host, port)` plus a client `connect(uri)`, both
context managers. A connection is iterable (yielding inbound messages) and exposes `recv()` /
`send(message)`.

Sync (threading) echo server and client:

```python
from websockets.sync.server import serve
from websockets.sync.client import connect

def handler(websocket):
    for message in websocket:
        websocket.send(f"echo: {message}")

with serve(handler, "localhost", 8765) as server:
    ...  # server.serve_forever() in a thread

with connect("ws://localhost:8765") as ws:
    ws.send("hello")
    assert ws.recv() == "echo: hello"
```

Asyncio echo server and client (same flow, awaited):

```python
from websockets.asyncio.server import serve
from websockets.asyncio.client import connect

async def handler(websocket):
    async for message in websocket:
        await websocket.send(f"echo: {message}")

async with serve(handler, "localhost", 8765) as server:
    ...

async with connect("ws://localhost:8765") as ws:
    await ws.send("hello")
    assert await ws.recv() == "echo: hello"
```

---

## Frames (`websockets.frames`)

`Opcode(IntEnum)`: Standard WebSocket opcodes per RFC 6455. Provide aliases like `OP_CONT`, `OP_TEXT`, etc.

`Frame(opcode, data, fin, rsv1, rsv2, rsv3)`: `serialize(mask) -> bytes`, `parse(cls, read_exact, mask)` (generator-based), `check()` (validates per RFC: reserved bits, control frame constraints).

On both `serialize` and `parse`, `mask` is a **boolean flag** (not the key bytes) selecting whether the frame is masked — `True` for client→server frames, `False` for server→client; masking itself follows RFC 6455 §5.3. This is distinct from `apply_mask(data, mask)` (below), the lower-level primitive whose `mask` argument is the explicit 4-byte key.

`CloseCode(IntEnum)`: Standard close codes per RFC 6455. Members include `NORMAL_CLOSURE` (1000) and `GOING_AWAY` (1001); the no-status / empty-payload case (no close code present) is `NO_STATUS_RCVD` (1005).

`Close(code, reason)`: `parse(cls, data)`, `serialize() -> bytes`, `check()`. `Close.parse` itself validates the payload length: an empty payload yields `NO_STATUS_RCVD`, a payload of exactly 1 byte (a present-but-truncated status code) raises `ProtocolError`, and a 2+ byte payload decodes the status code and reason.

---

## Headers (`websockets.datastructures`)

`Headers(MutableMapping)`: Case-insensitive keys, multi-value. `__setitem__` appends. `__getitem__` returns one value or raises `MultipleValuesError`. `get_all(key)`, `raw_items()`, `serialize()`, `copy()`.

`str(headers)` (i.e. `Headers.__str__`) returns the serialized HTTP header block: each entry as `"Name: value\r\n"` in insertion order, followed by a trailing `"\r\n"`. `serialize()` is that same block encoded to `bytes`.

---

## Header Parsing (`websockets.headers`)

Functions for parsing and building HTTP headers used in the WebSocket handshake:

`parse_extension(header) -> list[tuple[name, list[tuple[key, value]]]]`: Parse `Sec-WebSocket-Extensions` header.

`build_extension(extensions) -> str`: Serialize extension list back to header format.

`parse_subprotocol(header) -> list[str]`: Parse `Sec-WebSocket-Protocol` header.

`build_subprotocol(protocols) -> str`: Serialize subprotocol list back to header format.

---

## URI (`websockets.uri`)

`WebSocketURI(secure, host, port, path, query, username, password)`: `resource_name`, `user_info`. `user_info` returns the `(username, password)` tuple, or `None` when the URI has no userinfo.

`parse_uri(uri) -> WebSocketURI`: ws://→port 80, wss://→443. Raises `InvalidURI`.

---

## HTTP/1.1 (`websockets.http11`)

`Request(path, headers)`: `serialize()`, `parse(cls, read_line)` (generator-based).
`Response(status_code, reason_phrase, headers, body=b"")`: `serialize()`, `parse(cls, read_line, read_exact, read_to_eof)` (generator-based).

---

## StreamReader (`websockets.streams`)

`StreamReader`: Buffered reader with generator-based API. `feed_data(data)`, `feed_eof()`, `read_line(max)`, `read_exact(n)`, `read_to_eof(max)` — each read method is a generator.

---

## Utils (`websockets.utils`)

`GUID`: The RFC 6455 magic GUID string (module-level constant). `generate_key()`, `accept_key(key)` (per RFC 6455 §4.2.2), `apply_mask(data, mask)`.

---

## Sans-I/O Protocol (`websockets.protocol`, `.server`, `.client`)

`Side(IntEnum)`, `State(IntEnum)`: Protocol roles and connection states.

`Protocol`: `receive_data(data)`, `receive_eof()`, `events_received()`, `data_to_send()`. Send: `send_text(data, fin)`, `send_binary(data, fin)`, `send_continuation(data, fin)`, `send_close(code=None, reason="")`, `send_ping(data)`, `send_pong(data)`. Properties: `state`, `close_code`, `close_reason`. Auto-responds to pings with pongs.

Both `send_close` arguments are optional: calling `send_close()` with no code emits an empty-payload close frame, which both endpoints surface (once the close handshake completes) as `close_code == NO_STATUS_RCVD` (1005) with an empty `close_reason`. Passing a `reason` without a `code` is an error.

`events_received()` returns the protocol-level objects parsed from the incoming bytes: a `Request`/`Response` during the opening handshake, and `Frame` objects (exposing `.opcode`, `.data`, `.fin`) for data and control messages once the connection is `OPEN`. A fragmented message therefore surfaces as a `TEXT`/`BINARY` frame with `fin=False` followed by one or more `CONT` frames.

`data_to_send()` symmetrically returns an **iterable of bytes chunks** (the wire bytes queued by the preceding `receive_*` / `send_*` call), to be written to the transport in order — empty when nothing is pending. It returns byte *chunks*, not a single concatenated `bytes` object, so a caller reassembles the wire bytes via `b"".join(protocol.data_to_send())` (or writes each chunk in turn).

`ServerProtocol(origins, extensions, subprotocols, ...)`: `accept(request) -> Response`, `send_response(response)`.

`ClientProtocol(uri, origin, extensions, subprotocols, ...)`: `connect() -> Request`, `send_request(request)`.

---

## Sync API (`websockets.sync`)

`serve(handler, host, port, compression, ...) -> Server`: Context manager. `serve_forever()` in thread. Handler gets `ServerConnection`. The `Server` exposes its bound listening socket as `server.socket` (a stdlib `socket`); when binding with `port=0`, read the actual address with `server.socket.getsockname()`.

`Server.shutdown()`: the standalone method that stops a server whose `serve_forever()` is running in a background thread. It interrupts the blocked accept loop so that a thread executing `serve_forever()` returns promptly (letting a subsequent `thread.join()` complete) and closes the bound listening socket. This is the explicit stop call used by the common "start `serve_forever()` in a thread, then `server.shutdown()` + `thread.join()`" pattern — separate from, and in addition to, the context manager's `__exit__` teardown.

`connect(uri, compression, ...) -> ClientConnection`: Context manager. `recv()`, `send(message)`, `close(code, reason)`, `ping(data)`, iteration via `for msg in ws`. `ping(data)` returns a `threading.Event`-like object that is set when the matching pong is received, so callers can `.wait(timeout=...)` on the round trip (the asyncio variant returns an awaitable).

Properties: `close_code`, `close_reason`.

---

## Asyncio API (`websockets.asyncio`)

`serve(handler, host, port, ...) -> Server`: Async context manager. `server.sockets` for bound addresses.

`connect(uri, ...) -> ClientConnection`: Async context manager. `await send()`, `await recv()`.

---

## Extensions (`websockets.extensions`)

`PerMessageDeflate(remote_no_context_takeover, local_no_context_takeover, remote_max_window_bits, local_max_window_bits)`: `encode(frame)`, `decode(frame)`. Property: `name`.

Factories: `ClientPerMessageDeflateFactory`, `ServerPerMessageDeflateFactory`. Enable via `compression="deflate"`.

`ClientPerMessageDeflateFactory`: `get_request_params() -> list`, `process_response_params(params, accepted_extensions) -> extension`.

`ServerPerMessageDeflateFactory`: `process_request_params(params, accepted_extensions) -> (accepted_params, extension)`.

Default negotiation contract (no constraints configured on either side):
- A default `ClientPerMessageDeflateFactory().get_request_params()` offer advertises exactly `[("client_max_window_bits", None)]` — i.e. it signals support for `client_max_window_bits` with no value, and includes no other parameters.
- A default `ServerPerMessageDeflateFactory().process_request_params(params, [])` accepts that offer with **empty** `accepted_params` (`[]`).
- Both the resulting server and client `PerMessageDeflate` extensions have `name == "permessage-deflate"` and default `remote_max_window_bits == local_max_window_bits == 15`.

---

## CLI (`websockets.cli`)

The `websockets` entry point provides an interactive WebSocket client. `websockets --version` prints the version as `websockets <version>`. On a successful connection it prints a banner of the form `Connected to <uri>.` to stdout before entering the interactive read/send loop. Register as console script `websockets = websockets.cli:main`.

---

## Exceptions (`websockets.exceptions`)

`WebSocketException` → `ConnectionClosed(rcvd, sent, rcvd_then_sent)` → `ConnectionClosedOK` / `ConnectionClosedError`. Also: `InvalidURI`, `InvalidHandshake` → `InvalidStatus` / `InvalidHeader` / `NegotiationError`, `ProtocolError`, `PayloadTooBig`, `InvalidState`.

---

## setup.sh

```bash
pip install -e . --no-build-isolation
```
