"""Hidden test suite for the FastStream (Core + Redis) whole-repo-generation task.

Every test method exercises a distinct, user-facing behavioral contract of the library as a
realistic workflow. Broker behavior is tested against a live Redis server (started by test.sh);
pure-Python subsystems (DI, AsyncAPI generation) need no server. Tests use exact expected values
and avoid shallow assertions so a plausibly-broken implementation cannot pass.
"""

import asyncio
import uuid
from contextlib import asynccontextmanager
from unittest.mock import MagicMock, patch

import anyio
import pytest
import redis as sync_redis
from pydantic import BaseModel
from redis.asyncio import Redis

from faststream import (
    Context,
    ContextRepo,
    Depends,
    FastStream,
    Header,
    NoCast,
    Path,
    apply_types,
)
from faststream.exceptions import StopConsume
from faststream.middlewares import BaseMiddleware, ExceptionMiddleware
from faststream.redis import (
    BinaryMessageFormatV1,
    ListSub,
    RedisBroker,
    RedisResponse,
    RedisRoute,
    RedisRouter,
    StreamSub,
)
from faststream.specification import AsyncAPI

REDIS_URL = "redis://localhost:6379"
pytestmark = pytest.mark.asyncio


# --------------------------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------------------------- #
def name() -> str:
    """A unique destination name per test for isolation."""
    return uuid.uuid4().hex


@asynccontextmanager
async def running(broker: RedisBroker):
    """Connect + start a broker's subscribers, then stop it on exit."""
    await broker.connect()
    await broker.start()
    try:
        yield broker
    finally:
        await broker.stop()


def spy(method):
    """Wrap a (possibly async) method, recording calls on `.mock`, then delegating."""
    mock = MagicMock()

    async def awrapper(*args, **kwargs):
        mock(*args, **kwargs)
        return await method(*args, **kwargs)

    def swrapper(*args, **kwargs):
        mock(*args, **kwargs)
        return method(*args, **kwargs)

    wrapper = awrapper if asyncio.iscoroutinefunction(method) else swrapper
    wrapper.mock = mock
    return wrapper


async def wait(event: asyncio.Event, timeout: float = 5.0) -> None:
    await asyncio.wait_for(event.wait(), timeout=timeout)


class Data(BaseModel):
    m: str


# --------------------------------------------------------------------------------------------- #
# Wire format & serialization
# --------------------------------------------------------------------------------------------- #
class TestSerialization:
    async def test_binary_message_format_on_the_wire(self):
        """Published payloads use the custom BinaryMessageFormatV1 envelope, not bare JSON."""
        q = name()
        broker = RedisBroker(REDIS_URL)
        async with running(broker):
            await broker.publish("hello", list=q, headers={"x": "1"})
            await anyio.sleep(0.2)
        raw = sync_redis.Redis.from_url(REDIS_URL).lpop(q)
        assert raw is not None
        assert raw.startswith(b"\x89BIN\x0d\x0a\x1a\x0a")
        assert b"hello" in raw
        parsed = BinaryMessageFormatV1.parse(raw)
        body = parsed[0] if isinstance(parsed, tuple) else parsed
        assert b"hello" in (body if isinstance(body, bytes) else str(body).encode())

    async def test_serializer_int_to_float(self):
        """A float-typed handler coerces an int body to float via pydantic serialization."""
        q = name()
        broker = RedisBroker(REDIS_URL)
        got = {}
        event = asyncio.Event()

        @broker.subscriber(channel=q)
        async def h(msg: float):
            got["v"] = msg
            event.set()

        async with running(broker):
            await broker.publish(1, channel=q)
            await wait(event)
        assert got["v"] == 1.0
        assert isinstance(got["v"], float)

    async def test_pydantic_model_body(self):
        """A pydantic-typed handler param deserializes a dict body into the model."""
        q = name()
        broker = RedisBroker(REDIS_URL)
        got = {}
        event = asyncio.Event()

        @broker.subscriber(channel=q)
        async def h(msg: Data):
            got["v"] = msg
            event.set()

        async with running(broker):
            await broker.publish({"m": "hi"}, channel=q)
            await wait(event)
        assert got["v"] == Data(m="hi")


# --------------------------------------------------------------------------------------------- #
# Pub/Sub channels & patterns
# --------------------------------------------------------------------------------------------- #
class TestPubSub:
    async def test_channel_roundtrip_and_headers(self):
        """A channel subscriber receives the decoded body plus custom + correlation headers."""
        q = name()
        broker = RedisBroker(REDIS_URL)
        got = {}
        event = asyncio.Event()

        @broker.subscriber(channel=q)
        async def h(body: str, message=Context("message")):
            got["body"] = body
            got["custom"] = message.headers.get("custom")
            got["corr"] = message.correlation_id
            event.set()

        async with running(broker):
            await broker.publish("payload", channel=q, headers={"custom": "1"}, correlation_id="c-9")
            await wait(event)
        assert got["body"] == "payload"
        assert got["custom"] == "1"
        assert got["corr"] == "c-9"

    async def test_pattern_channel_with_path(self):
        """A `{param}` channel pattern matches and exposes the segment via Path() with cast."""
        q = name()
        broker = RedisBroker(REDIS_URL)
        got = {}
        event = asyncio.Event()

        @broker.subscriber(channel=f"{q}.{{level}}.{{code}}")
        async def h(body: str, level: str = Path(), code: int = Path("code")):
            got.update(body=body, level=level, code=code)
            event.set()

        async with running(broker):
            await broker.publish("p", channel=f"{q}.error.7")
            await wait(event)
        assert got["body"] == "p"
        assert got["level"] == "error"
        assert got["code"] == 7
        assert isinstance(got["code"], int)

    async def test_publish_without_destination_raises(self):
        """publish() with no channel/list/stream is a ValueError."""
        broker = RedisBroker(REDIS_URL)
        async with running(broker):
            with pytest.raises(ValueError):
                await broker.publish("x")


# --------------------------------------------------------------------------------------------- #
# Lists + batch
# --------------------------------------------------------------------------------------------- #
class TestLists:
    async def test_list_roundtrip_and_rpc(self):
        """A list subscriber consumes a pushed item; request() returns the handler's reply."""
        q = name()
        broker = RedisBroker(REDIS_URL)

        @broker.subscriber(list=q)
        async def h(msg: int):
            return msg + 1

        async with running(broker):
            resp = await broker.request(1, list=q, timeout=5)
            assert await resp.decode() == 2

    async def test_list_batch_single_item_wrapping(self):
        """A batch list subscriber wraps a single publish into a one-element list."""
        q = name()
        broker = RedisBroker(REDIS_URL)
        got = {}
        event = asyncio.Event()

        @broker.subscriber(list=ListSub(q, batch=True, max_records=5))
        async def h(msgs: list):
            got["v"] = msgs
            event.set()

        async with running(broker):
            await broker.publish("hi", list=q)
            await wait(event)
        assert got["v"] == ["hi"]

    async def test_list_batch_multi_and_headers(self):
        """publish_batch delivers all items; batch_headers expose one header dict per item."""
        q = name()
        broker = RedisBroker(REDIS_URL)
        got = {}
        event = asyncio.Event()

        @broker.subscriber(list=ListSub(q, batch=True, max_records=5))
        async def h(msgs: list, message=Context("message")):
            got["v"] = set(msgs)
            got["per_item_headers"] = len(message.batch_headers) == len(msgs)
            event.set()

        async with running(broker):
            await broker.publish_batch(1, "two", list=q)
            await wait(event)
        assert got["v"] == {1, "two"}
        assert got["per_item_headers"] is True


# --------------------------------------------------------------------------------------------- #
# Streams
# --------------------------------------------------------------------------------------------- #
class TestStreams:
    async def test_stream_roundtrip_and_native(self):
        """A stream publish delivers the body; native xadds arrive whole, incl. via _connection."""
        q = name()
        broker = RedisBroker(REDIS_URL)
        got = []
        event = asyncio.Event()

        @broker.subscriber(stream=StreamSub(q))
        async def h(msg):
            got.append(msg)
            if len(got) >= 3:
                event.set()

        async with running(broker):
            await broker.publish("hello", stream=q)
            await Redis.from_url(REDIS_URL).xadd(q, {"k": "v"})
            # The connected broker must also expose its own client for raw commands.
            await broker._connection.xadd(q, {"n": "1"})
            await wait(event)
        assert "hello" in got
        assert {"k": "v"} in got
        assert {"n": "1"} in got

    async def test_stream_batch_shape(self):
        """A batch stream subscriber delivers a single publish as a one-element list."""
        q = name()
        broker = RedisBroker(REDIS_URL)
        got = {}
        event = asyncio.Event()

        @broker.subscriber(stream=StreamSub(q, batch=True, max_records=5))
        async def h(msgs: list):
            got["v"] = msgs
            event.set()

        async with running(broker):
            await broker.publish("hello", stream=q)
            await wait(event)
        assert got["v"] == ["hello"]

    async def test_stream_group_acks_on_success(self):
        """A grouped stream subscriber XACKs the message after a successful handler."""
        q = name()
        broker = RedisBroker(REDIS_URL)
        event = asyncio.Event()

        @broker.subscriber(stream=StreamSub(q, group="g1", consumer="c1"))
        async def h(msg: str):
            event.set()

        ack_spy = spy(Redis.xack)
        with patch.object(Redis, "xack", ack_spy):
            async with running(broker):
                await broker.publish("hello", stream=q)
                await wait(event)
                await anyio.sleep(0.4)
        assert ack_spy.mock.called

    async def test_stream_manual_no_ack(self):
        """A MANUAL (no_ack) grouped stream subscriber does NOT auto-XACK."""
        q = name()
        broker = RedisBroker(REDIS_URL)
        event = asyncio.Event()

        @broker.subscriber(stream=StreamSub(q, group="g2", consumer="c2", no_ack=True))
        async def h(msg: str):
            event.set()

        ack_spy = spy(Redis.xack)
        with patch.object(Redis, "xack", ack_spy):
            async with running(broker):
                await broker.publish("hello", stream=q)
                await wait(event)
                await anyio.sleep(0.4)
        assert not ack_spy.mock.called

    async def test_stream_min_idle_time_uses_xautoclaim(self):
        """min_idle_time switches the read strategy to XAUTOCLAIM instead of XREADGROUP."""
        q = name()
        broker = RedisBroker(REDIS_URL)

        @broker.subscriber(stream=StreamSub(q, group="g3", consumer="c3", min_idle_time=1))
        async def h(msg):
            pass

        ac = spy(Redis.xautoclaim)
        rg = spy(Redis.xreadgroup)
        with patch.object(Redis, "xautoclaim", ac), patch.object(Redis, "xreadgroup", rg):
            async with running(broker):
                await anyio.sleep(0.6)
        assert ac.mock.called
        assert not rg.mock.called

    async def test_stream_nogroup_stops_subscriber(self):
        """Deleting the consumer group stops the subscriber; later messages are not received."""
        q = name()
        broker = RedisBroker(REDIS_URL)
        got = []

        @broker.subscriber(stream=StreamSub(q, group="g4", consumer="c4"))
        async def h(msg: str):
            got.append(msg)

        async with running(broker):
            await broker.publish("first", stream=q)
            await anyio.sleep(0.6)
            sync_redis.Redis.from_url(REDIS_URL).delete(q)
            await anyio.sleep(0.6)
            await broker.publish("second", stream=q)
            await anyio.sleep(0.6)
        assert "first" in got
        assert "second" not in got


# --------------------------------------------------------------------------------------------- #
# DI / Context / Header / unwrap / NoCast
# --------------------------------------------------------------------------------------------- #
class TestDI:
    async def test_context_cast_default_nested_and_required(self):
        """Context defaults to no-cast (identity); cast=True coerces; default/nested/required work."""
        ctx = ContextRepo()
        ctx.set_global("num", 3)
        ctx.set_global("data", {"inner": {"x": 5}})

        @apply_types(context__=ctx)
        async def identity(v=Context("num")):
            return v

        @apply_types(context__=ctx)
        async def casted(v: float = Context("num", cast=True)):
            return v

        @apply_types(context__=ctx)
        async def defaulted(v=Context("missing", default="d")):
            return v

        @apply_types(context__=ctx)
        async def nested(v=Context("data.inner.x")):
            return v

        @apply_types(context__=ctx)
        async def accumulate(v=Context("acc", initial=list)):
            v.append(1)
            return list(v)

        @apply_types(context__=ctx)
        async def required(v=Context("does_not_exist")):
            return v

        r = await identity()
        assert r == 3 and isinstance(r, int)
        c = await casted()
        assert c == 3.0 and isinstance(c, float)
        assert await defaulted() == "d"
        assert await nested() == 5
        assert await accumulate() == [1]
        assert await accumulate() == [1, 1]
        with pytest.raises(Exception):
            await required()

    async def test_header_extraction_and_cast(self):
        """Header() pulls from message headers (by param name and alias) and casts by default."""
        q = name()
        broker = RedisBroker(REDIS_URL)
        got = {}
        event = asyncio.Event()

        @broker.subscriber(channel=q)
        async def h(body: str, name_: str = Header("name"), id_: int = Header("id")):
            got.update(name=name_, id=id_)
            event.set()

        async with running(broker):
            await broker.publish("b", channel=q, headers={"name": "john", "id": "2"})
            await wait(event)
        assert got["name"] == "john"
        assert got["id"] == 2
        assert isinstance(got["id"], int)

    async def test_depends_and_sync_async_guard(self):
        """Depends resolves sub-dependencies; a sync consumer with an async Depends is rejected."""
        ctx = ContextRepo()

        def sync_dep():
            return "dep-value"

        @apply_types(context__=ctx)
        async def consumer(d=Depends(sync_dep)):
            return d

        assert await consumer() == "dep-value"

        async def async_dep():
            return 1

        with pytest.raises(AssertionError):

            @apply_types(context__=ctx)
            def bad(d=Depends(async_dep)):
                return d

    async def test_body_unwrap_and_nocast(self):
        """A dict body unpacks into kwargs; a list into positional+*args; NoCast skips coercion."""
        q1, q2 = name(), name()
        broker = RedisBroker(REDIS_URL)
        got = {}
        e1, e2 = asyncio.Event(), asyncio.Event()

        @broker.subscriber(channel=q1)
        async def unwrap_dict(a: int, b: int):
            got["dict"] = (a, b)
            e1.set()

        @broker.subscriber(channel=q2)
        async def unwrap_list(a: int, b: int, *args):
            got["list"] = (a, b, args)
            e2.set()

        async with running(broker):
            await broker.publish({"a": 1, "b": 2}, channel=q1)
            await broker.publish([1, 2, 3, 4], channel=q2)
            await wait(e1)
            await wait(e2)
        assert got["dict"] == (1, 2)
        assert got["list"] == (1, 2, (3, 4))

        ctx = ContextRepo()

        @apply_types(context__=ctx)
        def keep(s: NoCast[str]):
            return s

        assert keep(1) == 1
        assert isinstance(keep(1), int)


# --------------------------------------------------------------------------------------------- #
# Middleware
# --------------------------------------------------------------------------------------------- #
def _recording_mw(tag, log):
    class _MW(BaseMiddleware):
        def __init__(self, msg, *, context):
            super().__init__(msg, context=context)

        async def on_receive(self):
            log.append((tag, "recv"))

        async def after_processed(self, exc_type, exc_val, exc_tb):
            log.append((tag, "after"))
            return False

    return _MW


class TestMiddleware:
    async def test_broker_middleware_enter_exit_order(self):
        """on_receive runs in registration order; after_processed unwinds in reverse."""
        q = name()
        log = []
        event = asyncio.Event()
        broker = RedisBroker(
            REDIS_URL,
            middlewares=(_recording_mw("m1", log), _recording_mw("m2", log)),
        )

        @broker.subscriber(channel=q)
        async def h(msg: str):
            log.append(("handler", "run"))
            event.set()

        async with running(broker):
            await broker.publish("x", channel=q)
            await wait(event)
            await anyio.sleep(0.3)
        recv = [t for (t, k) in log if k == "recv"]
        after = [t for (t, k) in log if k == "after"]
        assert recv == ["m1", "m2"]
        assert after == ["m2", "m1"]
        assert ("handler", "run") in log

    async def test_router_nested_middleware_order(self):
        """Broker, router and nested-router middlewares nest outermost-first on consume."""
        q = name()
        log = []
        event = asyncio.Event()

        nested = RedisRouter(middlewares=(_recording_mw("nested", log),))

        @nested.subscriber(channel=q)
        async def h(msg: str):
            event.set()

        router = RedisRouter(middlewares=(_recording_mw("router", log),))
        router.include_router(nested)
        broker = RedisBroker(REDIS_URL, middlewares=(_recording_mw("broker", log),))
        broker.include_router(router)

        async with running(broker):
            await broker.publish("x", channel=q)
            await wait(event)
            await anyio.sleep(0.3)
        recv = [t for (t, k) in log if k == "recv"]
        assert recv == ["broker", "router", "nested"]

    async def test_publish_scope_mutation(self):
        """A broker middleware's publish_scope can mutate the outgoing command body."""
        q_in, q_out = name(), name()
        got = {}
        event = asyncio.Event()

        class DoubleMw(BaseMiddleware):
            def __init__(self, msg, *, context):
                super().__init__(msg, context=context)

            async def publish_scope(self, call_next, cmd):
                if isinstance(cmd.body, str):
                    cmd.body = cmd.body * 2
                return await call_next(cmd)

        broker = RedisBroker(REDIS_URL, middlewares=(DoubleMw,))

        @broker.subscriber(channel=q_in)
        @broker.publisher(channel=q_out)
        async def worker(msg: str):
            return "ab"

        @broker.subscriber(channel=q_out)
        async def sink(msg: str):
            got["v"] = msg
            event.set()

        async with running(broker):
            await broker.publish("trigger", channel=q_in)
            await wait(event)
        assert got["v"] == "abab"

    async def test_exception_middleware_substitute_and_suppress(self):
        """ExceptionMiddleware publish=True substitutes a return; publish=False suppresses."""
        q_pub, q_out, q_sup = name(), name(), name()
        got = {}
        e_pub, e_sup = asyncio.Event(), asyncio.Event()

        exc_mw = ExceptionMiddleware()

        @exc_mw.add_handler(ValueError, publish=True)
        async def on_value(exc):
            return "recovered"

        @exc_mw.add_handler(KeyError)
        async def on_key(exc):
            got["suppressed"] = True
            e_sup.set()

        broker = RedisBroker(REDIS_URL, middlewares=(exc_mw,))

        @broker.subscriber(channel=q_pub)
        @broker.publisher(channel=q_out)
        async def raiser(msg: str):
            raise ValueError("boom")

        @broker.subscriber(channel=q_out)
        async def sink(msg: str):
            got["published"] = msg
            e_pub.set()

        @broker.subscriber(channel=q_sup)
        async def suppressed(msg: str):
            raise KeyError("k")

        async with running(broker):
            await broker.publish("go", channel=q_pub)
            await broker.publish("go", channel=q_sup)
            await wait(e_pub)
            await wait(e_sup)
        assert got["published"] == "recovered"
        assert got["suppressed"] is True


# --------------------------------------------------------------------------------------------- #
# AsyncAPI
# --------------------------------------------------------------------------------------------- #
class TestAsyncAPI:
    def _schema(self, broker, version="3.0.0"):
        return AsyncAPI(broker, schema_version=version).to_specification().to_jsonable()

    async def test_asyncapi_v3_redis_bindings(self):
        """v3 channel bindings carry the FastStream-specific Redis method per destination type."""
        broker = RedisBroker(REDIS_URL)

        @broker.subscriber(channel="chan")
        async def a(msg):
            pass

        @broker.subscriber(channel="pat.*")
        async def b(msg):
            pass

        @broker.subscriber(list="lst")
        async def c(msg):
            pass

        @broker.subscriber(stream=StreamSub("strm", group="g", consumer="c"))
        async def d(msg):
            pass

        schema = self._schema(broker)
        methods = {}
        for ch in schema["channels"].values():
            rb = ch.get("bindings", {}).get("redis", {})
            if rb.get("method"):
                methods[rb["method"]] = rb
        assert "subscribe" in methods
        assert "psubscribe" in methods
        assert "lpop" in methods
        assert methods["xreadgroup"]["groupName"] == "g"
        assert methods["xreadgroup"]["consumerName"] == "c"
        assert all(rb.get("bindingVersion") == "custom" for rb in methods.values())

    async def test_asyncapi_v3_naming_and_payload(self):
        """v3 derives channel/operation/message keys and an EmptyPayload for a no-arg handler."""
        broker = RedisBroker(REDIS_URL)

        @broker.subscriber(channel="test")
        async def handle():
            pass

        schema = self._schema(broker)
        assert "test:Handle" in schema["channels"]
        assert "test:HandleSubscribe" in schema["operations"]
        assert schema["operations"]["test:HandleSubscribe"]["action"] == "receive"
        assert schema["components"]["schemas"]["EmptyPayload"] == {
            "title": "EmptyPayload",
            "type": "null",
        }

    async def test_asyncapi_v2_publish_subscribe_inversion(self):
        """v2.6.0 has no top-level operations; a subscriber appears under channel.publish."""
        broker = RedisBroker(REDIS_URL)

        @broker.subscriber(channel="test")
        async def handle(msg):
            pass

        schema = self._schema(broker, version="2.6.0")
        assert "operations" not in schema
        assert "publish" in schema["channels"]["test:Handle"]
        assert "url" in schema["servers"]["development"]


# --------------------------------------------------------------------------------------------- #
# RPC / request-reply
# --------------------------------------------------------------------------------------------- #
class TestRequest:
    async def test_request_reply_correlation(self):
        """request() returns the handler reply and preserves the caller's correlation_id."""
        q = name()
        broker = RedisBroker(REDIS_URL)

        @broker.subscriber(channel=q)
        async def h(msg: int):
            return msg + 1

        async with running(broker):
            resp = await broker.request(1, channel=q, correlation_id="cid-1", timeout=5)
            assert await resp.decode() == 2
            assert resp.correlation_id == "cid-1"

    async def test_request_timeout(self):
        """request() to a channel with no responder times out."""
        q = name()
        other = name()
        broker = RedisBroker(REDIS_URL)

        @broker.subscriber(channel=other)
        async def h(msg):
            pass

        async with running(broker):
            with pytest.raises((TimeoutError, asyncio.TimeoutError)):
                await broker.request(1, channel=q, timeout=0.5)


# --------------------------------------------------------------------------------------------- #
# Routers
# --------------------------------------------------------------------------------------------- #
class TestRouters:
    async def test_router_prefix_and_delayed_handler(self):
        """include_router(prefix=) prefixes the subject; RedisRoute registers a delayed handler."""
        q = name()
        got = {}
        event = asyncio.Event()

        async def delayed(msg: str):
            got["v"] = msg
            event.set()

        router = RedisRouter(handlers=(RedisRoute(delayed, channel=q),))
        broker = RedisBroker(REDIS_URL)
        broker.include_router(router, prefix="pref_")

        async with running(broker):
            await broker.publish("hi", channel=f"pref_{q}")
            await wait(event)
        assert got["v"] == "hi"

    async def test_stream_no_ack_misconfigure_warns(self):
        """A no_ack stream group with a non-'>' last_id raises a RuntimeWarning."""
        with pytest.warns(RuntimeWarning):
            StreamSub("s", group="g", consumer="c", no_ack=True, last_id="5")


# --------------------------------------------------------------------------------------------- #
# Codec / parser
# --------------------------------------------------------------------------------------------- #
class TestParsing:
    async def test_subscriber_parser_decoder_override(self):
        """A subscriber-level parser/decoder is invoked for that subscriber's messages."""
        q = name()
        broker = RedisBroker(REDIS_URL)
        calls = {"parser": 0, "decoder": 0}
        got = {}
        event = asyncio.Event()

        async def parser(msg, original):
            calls["parser"] += 1
            return await original(msg)

        async def decoder(msg, original):
            calls["decoder"] += 1
            return await original(msg)

        @broker.subscriber(channel=q, parser=parser, decoder=decoder)
        async def h(msg: str):
            got["v"] = msg
            event.set()

        async with running(broker):
            await broker.publish("hi", channel=q)
            await wait(event)
        assert got["v"] == "hi"
        assert calls["parser"] >= 1
        assert calls["decoder"] >= 1

    async def test_codec_and_decoder_conflict_raises(self):
        """Specifying both a codec and a decoder is rejected."""
        q = name()
        broker = RedisBroker(REDIS_URL)

        async def decoder(msg, original):
            return await original(msg)

        class DummyCodec:
            def encode(self, message):
                return b""

            def decode(self, message):
                return message

        with pytest.raises(ValueError):

            @broker.subscriber(channel=q, codec=DummyCodec(), decoder=decoder)
            async def h(msg):
                pass

            async with running(broker):
                pass


# --------------------------------------------------------------------------------------------- #
# Response / lifecycle / manual pull
# --------------------------------------------------------------------------------------------- #
class TestLifecycle:
    async def test_response_object_controls_reply(self):
        """Returning RedisResponse lets a handler set the reply body."""
        q = name()
        broker = RedisBroker(REDIS_URL)

        @broker.subscriber(channel=q)
        async def h(msg: int):
            return RedisResponse(msg + 10, correlation_id="resp-cid")

        async with running(broker):
            resp = await broker.request(5, channel=q, timeout=5)
            assert await resp.decode() == 15

    async def test_stop_consume(self):
        """A handler raising StopConsume processes one message then stops consuming."""
        q = name()
        broker = RedisBroker(REDIS_URL)
        calls = []
        event = asyncio.Event()

        @broker.subscriber(list=q)
        async def h(msg: str):
            calls.append(msg)
            event.set()
            raise StopConsume()

        async with running(broker):
            await broker.publish("one", list=q)
            await wait(event)
            await anyio.sleep(0.4)
            await broker.publish("two", list=q)
            await anyio.sleep(0.6)
        assert calls == ["one"]

    async def test_get_one_and_active_handler_guard(self):
        """get_one() pulls a single message; calling it on a subscriber with a handler errors."""
        q1, q2 = name(), name()
        broker = RedisBroker(REDIS_URL)

        puller = broker.subscriber(list=q1)

        handler_sub = broker.subscriber(list=q2)

        @handler_sub
        async def h(msg):
            pass

        await broker.connect()
        try:
            await broker.publish("one", list=q1)
            msg = await puller.get_one(timeout=3.0)
            assert msg is not None
            assert await msg.decode() == "one"
            none = await puller.get_one(timeout=1e-24)
            assert none is None
            with pytest.raises(AssertionError):
                await handler_sub.get_one(timeout=0.1)
        finally:
            await broker.stop()


# --------------------------------------------------------------------------------------------- #
# Full app lifecycle
# --------------------------------------------------------------------------------------------- #
class TestAppLifecycle:
    async def test_after_startup_hook_runs_with_live_broker(self):
        """after_startup fires after on_startup with the broker connected (publish works)."""
        q = name()
        broker = RedisBroker(REDIS_URL)
        app = FastStream(broker)
        order = []
        received = []
        event = asyncio.Event()

        @broker.subscriber(channel=q)
        async def h(msg: str):
            received.append(msg)
            event.set()

        @app.on_startup
        async def _start():
            order.append("on_startup")

        @app.after_startup
        async def _after():
            order.append("after_startup")
            await broker.publish("from-hook", channel=q)

        await broker.connect()
        await app.start()
        try:
            await wait(event)
        finally:
            await app.stop()
        assert order == ["on_startup", "after_startup"]
        assert received == ["from-hook"]
