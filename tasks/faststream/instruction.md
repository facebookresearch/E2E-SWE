# FastStream — Redis Broker & Core Framework

Build `faststream`, an asynchronous Python framework for writing message-driven services on top of message brokers. This task covers the **core framework** (application lifecycle, dependency injection, middleware, message handling, AsyncAPI documentation generation) and the **Redis broker backend** (Pub/Sub channels, lists, and streams).

A service is written declaratively: the user creates a broker, decorates async functions as *subscribers* (consumers) and *publishers* (producers), and runs them inside an application. The framework parses incoming broker messages, injects dependencies into handlers, routes return values to publishers, and can emit an AsyncAPI schema describing the service.

## Dependencies

These packages are already installed (the environment is offline — do not install anything):

- `fast-depends[pydantic]` — the dependency-injection engine the framework is built on (`Depends`, `inject`, custom fields, pydantic-based casting). `faststream` re-exports and extends it.
- `pydantic` (v2), `anyio`, `typing-extensions`.
- `redis` (the `redis` / `redis.asyncio` client; server features such as `LPOP key count` are available).
- A live **Redis server** is running on `redis://localhost:6379` during testing.

The project must be installable with `pip install -e . --no-build-isolation`. Its build backend is `uv_build`; the package directory is `faststream/`.

## Package Structure

Public objects must be importable from exactly these paths:

- `faststream` → `FastStream`, `Context`, `ContextRepo`, `Depends`, `Header`, `Path`, `NoCast`, `apply_types`
- `faststream.redis` → `RedisBroker`, `RedisRouter`, `RedisRoute`, `RedisResponse`, `PubSub`, `ListSub`, `StreamSub`, `BinaryMessageFormatV1`
- `faststream.middlewares` → `BaseMiddleware`, `ExceptionMiddleware`
- `faststream.specification` → `AsyncAPI`
- `faststream.exceptions` → `StopConsume`

You are free to organize internal modules however you like; only the import paths above are part of the contract.

---

## 1. Application & broker lifecycle

`FastStream(broker)` wraps one or more brokers into a runnable application. It exposes lifecycle-hook decorators that register async callbacks:

- `@app.on_startup` — runs before the broker(s) start.
- `@app.after_startup` — runs after the broker(s) have started and are connected/consuming.
- (`on_shutdown` / `after_shutdown` mirror these on teardown.)

Hooks run in registration order. The ordering contract: **all `on_startup` hooks run, then brokers start, then all `after_startup` hooks run.** Therefore inside an `after_startup` hook the broker is live and `broker.publish(...)` delivers to subscribers. Hook callbacks may declare dependency-injected parameters.

`RedisBroker(url)` is the Redis backend. Lifecycle:

- `await broker.connect()` — establish the connection (idempotent; the underlying client is reachable as `broker._connection` for advanced use such as issuing raw commands).
- `await broker.start()` — begin consuming for every registered subscriber.
- `await broker.stop()` — stop consuming. Calling `stop()` before `start()` is a harmless no-op.

`app.start()` / `app.stop()` drive the registered hooks plus the broker lifecycle.

---

## 2. Subscribers

`@broker.subscriber(...)` registers the decorated async function as a consumer. The first positional argument or the keyword selects the destination **and its type** — exactly one of:

- `channel=` — a Redis Pub/Sub channel.
- `list=` — a Redis list.
- `stream=` — a Redis stream.

Passing more than one, or none, is a configuration error (`SetupError`). A bare string positional (`@broker.subscriber("name")`) is shorthand for `channel=`.

The handler receives the **decoded message body** as its first parameter (see §4 for decoding/casting and body unwrapping). The decorator returns a wrapper object exposing `.get_one(...)` for manual pulls (§11).

### Channels (Pub/Sub)

`channel=` subscribes to a Redis channel. Channels are fire-and-forget (no acknowledgement).

**Pattern subscriptions.** A channel containing `*`, or containing `{name}` placeholders, is treated as a pattern (Redis `PSUBSCRIBE`). With `{placeholder}` segments, the matched values are exposed to the handler via `Path` parameters (§5). You may also pass `PubSub("name.*", pattern=True)` explicitly.

### Lists

`list=` consumes items pushed onto a Redis list. Use `ListSub(name, batch=..., max_records=...)` to configure:

- Default (non-batch): one list element → one handler call.
- `batch=True`: the handler is called with a **list** of decoded items. A single published item is delivered as a one-element list (e.g. publishing `"hi"` calls the handler with `["hi"]`). `max_records` bounds how many items one batch may contain.

### Streams

`stream=` consumes from a Redis stream. Use `StreamSub(name, ...)` to configure:

- Default (non-batch): one stream entry → one handler call.
- `batch=True`: handler receives a **list** of entries; a single entry arrives as a one-element list. `max_records=` bounds how many entries one batch may contain.
- `group=` and `consumer=` enable consumer-group consumption (Redis `XREADGROUP`). **Both must be supplied together** or it is a configuration error.
- `min_idle_time=` switches the read strategy to claim pending-but-unacknowledged entries (Redis `XAUTOCLAIM`) instead of the normal group read.
- `no_ack=True` disables automatic acknowledgement.
- `last_id=` sets the id to start reading from; it defaults to the "only new messages" sentinel (`"$"`) without a group and the "undelivered messages" sentinel (`">"`) with a consumer group.

See §6 for stream acknowledgement and error semantics.

---

## 3. Publishers & publishing

### Direct publish

`await broker.publish(body, channel=... | list=... | stream=...)` sends one message. Publishing with no destination is a `ValueError`. Optional `headers=` (a dict) and `correlation_id=` travel with the message.

`await broker.publish_batch(item1, item2, ..., list=name)` pushes several items in one operation; a batch list subscriber receives them together.

### Publisher decorators

`@broker.publisher(channel=... | list=... | stream=...)` stacked on a subscriber publishes the **handler's return value** to that destination. Stacking multiple publishers publishes the return value to each.

### Request / reply (RPC)

`await broker.request(body, channel=... | list=... | stream=..., correlation_id=..., timeout=...)` publishes a message and waits for the handler's reply, returning a message object whose `await .decode()` yields the reply body. The caller-supplied `correlation_id` is preserved on the response (`response.correlation_id`). If no reply arrives within `timeout`, a `TimeoutError` is raised.

### `RedisResponse`

A handler may return `RedisResponse(body, correlation_id=..., headers=...)` instead of a bare value to control the published/replied message explicitly. The wrapped body is what the requester decodes.

---

## 4. Message bodies: serialization, decoding, unwrapping

### On-the-wire format

Messages are serialized with a custom binary envelope, `BinaryMessageFormatV1`, which is the default message format for the Redis broker. The encoded bytes begin with the magic prefix `\x89BIN\x0d\x0a\x1a\x0a`, embed the raw body, and carry headers. `BinaryMessageFormatV1.parse(raw_bytes)` decodes an envelope back into its body and headers; the implementation must round-trip what it encodes.

For streams specifically, the framework stores the encoded payload under a single stream field. Consequently:

- `broker.publish("hello", stream=q)` delivers `"hello"` to the handler.
- A **native** `xadd` of an arbitrary field dict (e.g. `broker._connection.xadd(q, {"k": "v"})`) is delivered to the handler as the **whole dict** `{"k": "v"}` (it is not unwrapped, because it lacks the framework's envelope).

### Casting

The handler's first parameter is decoded and then **cast to its type annotation** using pydantic. For example, an `int` published to a handler annotated `msg: float` arrives as `1.0`; a dict published to a handler annotated `msg: SomeModel` arrives as a validated model instance.

### Body unwrapping

When the decoded body is a collection and the handler declares **multiple** parameters, the body is unpacked into them:

- A **dict** body is unpacked as keyword arguments: publishing `{"a": 1, "b": 2}` to `async def h(a: int, b: int)` calls `h(a=1, b=2)`.
- A **list** body is unpacked positionally (with `*args` absorbing the remainder): publishing `[1, 2, 3, 4]` to `async def h(a, b, *args)` calls `h(1, 2, (3, 4))`.

A handler with a single body parameter receives the whole decoded body unchanged.

---

## 5. Dependency injection & context

The framework injects values into handler (and lifecycle-hook) parameters based on special default values, on top of `fast-depends`.

- `Depends(func)` — calls `func` (resolving *its* injected params too) and passes the result. A **synchronous** consumer declaring an **async** `Depends` is rejected at decoration time (raises `AssertionError`); an async consumer may use either.
- `Context(name="", *, cast=False, default=..., initial=...)` — pulls a value from the context store (§ below). Resolution rules:
  - The lookup key is `name`, or the **parameter's own name** when `name` is omitted.
  - **`cast` defaults to `False`** → the stored object is returned by identity, *not* coerced to the annotation. `cast=True` coerces it to the annotation type.
  - `default=` supplies a fallback when the key is absent; without a default, a missing key makes the parameter required and raises a validation error.
  - Dotted names traverse nested mappings/attributes: `Context("data.inner.x")`.
  - `initial=<factory>` builds a value on first resolution and **persists it in the global context**, so repeated calls observe the accumulated object (e.g. `initial=list` yields `[1]`, then `[1, 1]`, ... across calls that append).
- `Header(name="", *, cast=True, default=...)` — pulls from the incoming message's headers. Like `Context` but reads from headers and **casts by default** (a header `"2"` into an `int` parameter arrives as `2`).
- `Path(name="", *, cast=True, default=...)` — pulls a named segment captured by a `{placeholder}` channel pattern; casts by default.
- `NoCast` — used as `NoCast[T]`, marks a parameter to **skip** pydantic casting even though it carries a type annotation (the raw value passes through unchanged).
- `apply_types(func=None, *, context__=...)` — decorator that wires the above injection onto an arbitrary async/sync function, binding it to a given context store. `Context`/`Header`/`Path` resolve against the bound store.

### The context store

`ContextRepo` is the value store. Methods include `set_global(key, value)` to register a value; values are then resolvable by `Context("key")`. During message processing the framework populates the store with at least:

- `"message"` — the current message object (exposes `.headers` (dict), `.correlation_id`, `.batch_headers` (per-item headers for batch subscribers), and `await .decode()`).

`Header`/`Path` are defined in terms of the `"message"` entry (headers and captured path segments respectively).

---

## 6. Stream acknowledgement & error semantics

For **consumer-group** stream subscribers (`group=` + `consumer=`):

- On a successful handler return, the framework **acknowledges** the entry (Redis `XACK`).
- With `no_ack=True`, automatic acknowledgement is disabled — no `XACK` is issued.
- If the consumer group disappears (e.g. the stream/group is deleted) the subscriber encounters a `NOGROUP` condition and **stops consuming**; subsequent messages are not delivered.
- `min_idle_time=` makes the subscriber reclaim pending entries via `XAUTOCLAIM` rather than reading new ones via `XREADGROUP`.

Misconfiguration warnings: constructing a `StreamSub` with `no_ack=True` together with a consumer group and a `last_id` other than the "undelivered messages" sentinel `">"` raises a `RuntimeWarning`.

Channels and lists have no acknowledgement concept.

---

## 7. Middleware

`BaseMiddleware` is the user-extensible middleware base. Subclasses are constructed per message as `Middleware(msg, *, context)` and may override:

- `async on_receive(self)` — runs when a message arrives, before the handler.
- `async after_processed(self, exc_type, exc_val, exc_tb)` — runs after handler processing; return `True` to suppress an exception, falsy to let it propagate (the default).
- `async consume_scope(self, call_next, msg)` — wraps handler invocation; must `return await call_next(msg)`.
- `async publish_scope(self, call_next, cmd)` — wraps each publish; may mutate the outgoing command (e.g. `cmd.body`) before `await call_next(cmd)`.

Middlewares are registered with `Broker(url, middlewares=(...))` (and likewise on routers). **Ordering contract** when several are stacked:

- `on_receive` runs in **registration order** (first-registered first); `after_processed` unwinds in **reverse** order.
- For routers, the nesting is broker-outermost → router → nested-router (on the consume path the broker's middleware's `on_receive` runs first).

`ExceptionMiddleware` maps exception types to handler callbacks:

- `@mw.add_handler(ExcType, publish=True)` — when the handler raises `ExcType` (matched by MRO), the callback's return value is used as the handler's result and **published** (substitution).
- `@mw.add_handler(ExcType)` (no `publish`) — the callback runs and the exception is **suppressed** (no substitution of a published value).

---

## 8. Routers

`RedisRouter` groups subscribers/publishers for inclusion into a broker (or another router). `broker.include_router(router, prefix="...")` registers the router's handlers, **prefixing** their destination names with `prefix`. Nested routers are supported and middleware nests as described in §7. Including a router of a different broker type is a `SetupError`.

Handlers may be declared imperatively rather than by decoration: `RedisRouter(handlers=(RedisRoute(func, channel=... | list=... | stream=...),))` registers `func` as a subscriber on that destination.

---

## 9. Custom parsers / decoders / codecs

A subscriber may override message processing:

- `parser=` and `decoder=` — callables of the form `async def (msg, original)` that may pre/post-process and delegate to `original(msg)`. A subscriber-level parser/decoder is used for that subscriber's messages.
- `codec=` — an encode/decode strategy object. Supplying **both** a `codec` and a `decoder` is contradictory and raises a `ValueError`.

---

## 10. AsyncAPI specification

`AsyncAPI(broker, schema_version="3.0.0")` produces an AsyncAPI documentation object for a broker's subscribers/publishers. `.to_specification().to_jsonable()` returns a plain dict. `None`-valued fields are omitted from the output.

### v3.0.0 structure

Top level includes `channels`, `operations`, `servers`, `components`.

- **Channel keys** are derived from the destination and handler: e.g. a `channel="test"` subscriber on handler `handle` produces channel key `test:Handle` (the handler name is camel-cased).
- **Operations**: a subscriber produces an operation keyed `<channel>Subscribe` with `action: "receive"`; e.g. `test:HandleSubscribe`.
- A handler with **no body parameter** produces a payload schema named `EmptyPayload` equal to `{"title": "EmptyPayload", "type": "null"}` under `components/schemas`.
- **Redis channel bindings** live under each channel's `bindings.redis` and carry a `method` keyed to the destination type, plus `bindingVersion: "custom"`:
  - channel → `"subscribe"`; pattern channel → `"psubscribe"`; list → `"lpop"`; stream → `"xread"`; stream with a consumer group → `"xreadgroup"` (with `groupName` and `consumerName`).
- **Servers**: the `servers` map holds a single default entry keyed `development`; in v3.0.0 its connection is described by a `host`/`pathname` split.

### v2.6.0 structure

With `schema_version="2.6.0"` the output has **no top-level `operations`**; operations are nested inside channels, and—counter-intuitively—a **subscriber** appears under the channel's **`publish`** key. The `development` server entry is described by a `url` string (rather than the v3 `host`/`pathname` split).

---

## 11. Manual consumption

A subscriber object created without immediately decorating a handler (e.g. `sub = broker.subscriber(list=name)`) supports `await sub.get_one(timeout=...)` to pull a single message, returning a message object (or `None` on timeout). Calling `get_one()` on a subscriber that already has a registered handler is an error (`AssertionError`).

---

## 12. Exceptions

- `StopConsume` — a handler may raise it to process the current message and then **stop consuming** further messages on that subscriber.
- `SetupError` — invalid configuration (e.g. multiple/zero destinations, cross-broker router inclusion).
