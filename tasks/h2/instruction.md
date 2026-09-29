# h2 — Pure-Python HTTP/2 Protocol Implementation

Build **h2**, a pure-Python HTTP/2 protocol library. Sans-I/O design: processes bytes in, produces bytes out. Implements binary framing, stream multiplexing, header compression, flow control, and settings negotiation per RFC 7540.

## Usage

The connection object never touches the network: you call methods on it, drain the bytes it queues with `data_to_send()`, transmit them yourself, and feed bytes you receive back in with `receive_data()`, which returns the events they produced. A single client GET round-trip between a client and server connection looks like:

```python
import h2.connection, h2.config, h2.events

client = h2.connection.H2Connection(config=h2.config.H2Configuration(client_side=True))
server = h2.connection.H2Connection(config=h2.config.H2Configuration(client_side=False))

# Handshake: each side initiates and exchanges its preface/SETTINGS bytes.
client.initiate_connection()
server.initiate_connection()
server.receive_data(client.data_to_send())
client.receive_data(server.data_to_send())

# Client sends a request; server reads it off the wire as a RequestReceived event.
client.send_headers(1, [(":method", "GET"), (":path", "/"),
                        (":scheme", "https"), (":authority", "example.com")], end_stream=True)
events = server.receive_data(client.data_to_send())  # -> [RequestReceived, StreamEnded, ...]

# Server responds on the same stream; client reads the response + body + end.
server.send_headers(1, [(":status", "200")])
server.send_data(1, b"hello", end_stream=True)
events = client.receive_data(server.data_to_send())  # -> [ResponseReceived, DataReceived, StreamEnded]
```

## Dependencies

The environment is **offline** and every dependency is **already installed** — do not install,
download, or fetch anything (there is no network). The runtime dependencies are:

- `hyperframe` — HTTP/2 frame serialization (frame types, parsing, serialization)
- `hpack` — HPACK header compression (encoding/decoding HTTP/2 headers)

## setup.sh

The project is installed offline by a `setup.sh` that runs against the pre-installed dependencies:

```bash
pip install -e . --no-build-isolation
```

---

## 1. Configuration

`h2.config.H2Configuration(client_side=True, header_encoding=None)`

- `client_side` — `True` for client connections, `False` for server connections. Determines stream ID parity rules and connection preface behavior.
- `header_encoding` — Controls how decoded headers are returned in events:
  - `None` (default): headers are returned as **bytes** tuples, e.g. `(b":method", b"GET")`
  - `"utf-8"`: headers are returned as **str** tuples, e.g. `(":method", "GET")`

---

## 2. Connection — `h2.connection.H2Connection`

`H2Connection(config=None)` — the main protocol state machine. All network I/O is external; the connection object only processes byte buffers.

### Connection Lifecycle

- `initiate_connection()` — Initialize the connection. For clients, queues the HTTP/2 connection preface: the 24-byte magic string `b'PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n'` followed by a SETTINGS frame. For servers, queues a SETTINGS frame. Call `data_to_send()` afterward to get the bytes to transmit.

- `initiate_upgrade_connection(settings_header=None)` — HTTP/1.1 upgrade to HTTP/2.
  - **Client side** (no `settings_header`): Returns a `bytes` object containing the base64url-encoded client settings (suitable for the `HTTP2-Settings` header in an HTTP/1.1 `Upgrade` request). Also queues the connection preface for sending. After calling, stream 1 is implicitly open.
  - **Server side** (`settings_header=<bytes>`): Accepts the base64url-encoded settings from the client's upgrade request. Initializes the connection with those settings. Stream 1 is implicitly open for the server to send a response.

- `receive_data(data)` → `list[Event]` — Feed received bytes into the connection. Parses frames and returns a list of event objects (see §3). May also queue response frames internally (e.g. SETTINGS acknowledgment, PING response). Receiving the peer's SETTINGS frame during the initial handshake (the peer's `initiate_connection` preface/SETTINGS) always yields a `RemoteSettingsChanged` event enumerating the peer's advertised settings — even when those advertised values equal the receiver's own defaults — with each `ChangedSetting.original_value` reflecting the receiver's documented default and `.new_value` the peer's advertised value.

- `data_to_send()` → `bytes` — Returns all pending outbound data (frames queued by send methods and automatic responses). Returns `b""` if nothing is queued.

- `clear_outbound_data_buffer()` — Discard any pending outbound data without sending it.

### Sending Data

- `send_headers(stream_id, headers, end_stream=False)` — Send a HEADERS frame on the given stream. `headers` is a list of `(name, value)` tuples (strings). Opens the stream if not already open. If `end_stream=True`, the stream's send side is closed after headers. Client stream IDs must be odd and must increase monotonically. Raises `ProtocolError` on violations or closed streams. Raises `TooManyStreamsError` if exceeding `MAX_CONCURRENT_STREAMS`.

- `send_data(stream_id, data, end_stream=False)` — Send a DATA frame. `data` is `bytes`. Each call sends a single frame — `len(data)` must not exceed `MAX_FRAME_SIZE`. Raises `FlowControlError` if `len(data)` exceeds the available flow control window. Raises `FrameTooLargeError` if `len(data)` exceeds `MAX_FRAME_SIZE`. The flow control window is checked **first**, so when `len(data)` exceeds both limits, `FlowControlError` is raised before `FrameTooLargeError`. Raises `ProtocolError` if the stream's send side is already closed.

- `end_stream(stream_id)` — Send an empty DATA frame with the END_STREAM flag. Closes the send side of the stream. This is an alternative to passing `end_stream=True` on `send_headers` or `send_data`.

### Stream Management

- `get_next_available_stream_id()` → `int` — Returns the next stream ID. Client IDs are odd (1, 3, 5, ...), server IDs are even (2, 4, 6, ...). Increments by 2 each time a stream is opened.

- `reset_stream(stream_id, error_code=0)` — Send a RST_STREAM frame to cancel a stream. `error_code` is an `ErrorCodes` value (see §6).

- `push_stream(parent_stream_id, push_stream_id, headers)` — Server sends a PUSH_PROMISE frame. `push_stream_id` should be obtained from `get_next_available_stream_id()` (server-side, so it will be even). `headers` are the promised request headers. Raises `ProtocolError` if the peer has disabled server push (it set `ENABLE_PUSH=0`) — the server must not send a PUSH_PROMISE once the client has disabled push.

- `close_connection(error_code=0, last_stream_id=None)` — Send a GOAWAY frame. `error_code` is an `ErrorCodes` value. `last_stream_id` indicates the highest stream ID the sender will process. A connection that has received GOAWAY rejects new streams.

- `prioritize(stream_id, weight=None, depends_on=None, exclusive=None)` — Send a PRIORITY frame to set stream priority. `weight` is 1-256 (default 16). `depends_on` is the stream ID this stream depends on (default 0 = root). `exclusive` is a boolean. The remote side receives a `PriorityUpdated` event.

### Flow Control

- `local_flow_control_window(stream_id)` → `int` — Remaining bytes the local side can send on this stream. Raises `NoSuchStreamError` if the stream does not exist.

- `remote_flow_control_window(stream_id)` → `int` — Peer's flow control window for this stream.

- `acknowledge_received_data(size, stream_id)` — Acknowledge consumed received data, allowing the library to send WINDOW_UPDATE frames.

- `increment_flow_control_window(increment, stream_id=None)` — Send a WINDOW_UPDATE frame. If `stream_id` is None, increments the connection-level window; otherwise the stream-level window.

### Settings and Ping

- `update_settings(new_settings)` — Send a SETTINGS frame. `new_settings` is a dict mapping `SettingCodes` values to integers (e.g. `{SettingCodes.MAX_CONCURRENT_STREAMS: 50}`). The peer receives a `RemoteSettingsChanged` event.

- `ping(opaque_data)` — Send a PING frame. `opaque_data` must be exactly 8 bytes. The peer automatically responds with a PING ACK. The original sender receives a `PingAckReceived` event.

### Alternative Service

- `advertise_alternative_service(field_value, stream_id=None)` — Send an ALTSVC frame. `field_value` is `bytes` (e.g. `b'h2=":8000"'`). If `stream_id` is 0 or None, the frame applies to the connection origin. The peer receives an `AlternativeServiceAvailable` event.

### Properties

- `open_outbound_streams` → `int` — Number of streams initiated by this side that are currently open (not yet closed/reset/ended on both sides).
- `open_inbound_streams` → `int` — Number of streams initiated by the peer that are currently open.
- `inbound_flow_control_window` → `int` — Connection-level inbound flow control window. Initial value is 65535.

---

## 3. Events — `h2.events`

Events are returned by `receive_data()`. Each event has a `stream_id` attribute (where applicable).

| Event class | Key attributes |
|---|---|
| `RequestReceived` | `stream_id`, `headers`, `stream_ended`, `priority_updated` |
| `ResponseReceived` | `stream_id`, `headers`, `stream_ended`, `priority_updated` |
| `DataReceived` | `stream_id`, `data` (bytes), `flow_controlled_length`, `stream_ended` |
| `StreamEnded` | `stream_id` |
| `StreamReset` | `stream_id`, `error_code`, `remote_reset` |
| `TrailersReceived` | `stream_id`, `headers`, `stream_ended`, `priority_updated` |
| `RemoteSettingsChanged` | `changed_settings` — dict of `SettingCodes` → `ChangedSetting` (`.original_value`, `.new_value`) |
| `SettingsAcknowledged` | `changed_settings` |
| `WindowUpdated` | `stream_id`, `delta` |
| `PingReceived` | `ping_data` |
| `PingAckReceived` | `ping_data` |
| `PushedStreamReceived` | `parent_stream_id`, `pushed_stream_id`, `headers` |
| `ConnectionTerminated` | `error_code`, `last_stream_id`, `additional_data` |
| `PriorityUpdated` | `stream_id`, `weight`, `depends_on`, `exclusive` |
| `AlternativeServiceAvailable` | `origin`, `field_value` |

`headers` attributes are lists of `(name, value)` tuples — `bytes` when `header_encoding=None` (default), `str` when `"utf-8"`.

---

## 4. Error Codes — `h2.errors.ErrorCodes`

Integer constants per RFC 7540 §7:

| Name | Value |
|------|-------|
| `NO_ERROR` | 0 |
| `PROTOCOL_ERROR` | 1 |
| `INTERNAL_ERROR` | 2 |
| `FLOW_CONTROL_ERROR` | 3 |
| `SETTINGS_TIMEOUT` | 4 |
| `STREAM_CLOSED` | 5 |
| `FRAME_SIZE_ERROR` | 6 |
| `REFUSED_STREAM` | 7 |
| `CANCEL` | 8 |
| `COMPRESSION_ERROR` | 9 |
| `ENHANCE_YOUR_CALM` | 11 |

---

## 5. Setting Codes — `h2.settings.SettingCodes`

Integer constants per RFC 7540 §6.5.2:

| Name | Value |
|------|-------|
| `HEADER_TABLE_SIZE` | 1 |
| `ENABLE_PUSH` | 2 |
| `MAX_CONCURRENT_STREAMS` | 3 |
| `INITIAL_WINDOW_SIZE` | 4 |
| `MAX_FRAME_SIZE` | 5 |
| `MAX_HEADER_LIST_SIZE` | 6 |

### Connection setting defaults

A new connection's own (local) settings start at the RFC 7540 §6.5.2 defaults — `HEADER_TABLE_SIZE` 4096, `INITIAL_WINDOW_SIZE` 65535, `MAX_FRAME_SIZE` 16384 — **except** `MAX_CONCURRENT_STREAMS`, which this library defaults to **100** rather than the RFC's "unlimited" (an unbounded default would allow unbounded resource allocation). This is the baseline a peer sees. (This local default does not constrain the remote peer's settings, which the peer controls.)

---

## 6. Exceptions — `h2.exceptions`

- `ProtocolError` — General HTTP/2 protocol violation.
- `TooManyStreamsError` — Exceeding `MAX_CONCURRENT_STREAMS`.
- `FlowControlError` — Exceeding flow control window.
- `FrameTooLargeError` — Frame payload exceeds `MAX_FRAME_SIZE`.
- `NoSuchStreamError` — Operating on a non-existent stream.
- `StreamClosedError` — Operating on a closed stream.
