"""
Integration tests for websockets — WebSocket protocol implementation.
Tests exercise the full stack: frame encoding, protocol state machine,
HTTP upgrade handshake, data structures, and end-to-end communication.
"""

import asyncio
import base64
import hashlib
import re
import struct
import subprocess
import threading
import time

import pytest


# =============================================================================
# Frame Encoding / Decoding
# =============================================================================


class TestFrames:
    """Tests for WebSocket frame encoding and decoding."""

    def test_frame_serialize_and_parse_roundtrip(self):
        """Serialize a text frame and parse it back, verifying data preserved."""
        from websockets.frames import Frame, Opcode

        # Create a text frame
        frame = Frame(opcode=Opcode.TEXT, data=b"Hello, World!", fin=True)

        # Serialize as server (no mask)
        serialized = frame.serialize(mask=False)
        assert isinstance(serialized, bytes)
        assert len(serialized) > 0

        # Parse it back
        from websockets.streams import StreamReader
        reader = StreamReader()
        reader.feed_data(serialized)
        reader.feed_eof()

        parser = Frame.parse(reader.read_exact, mask=False)
        try:
            next(parser)  # drive the generator
        except StopIteration as e:
            parsed = e.value
        else:
            pytest.fail("Parser didn't complete")

        assert parsed.opcode == Opcode.TEXT
        assert bytes(parsed.data) == b"Hello, World!"
        assert parsed.fin is True

    def test_frame_masked_roundtrip(self):
        """Client frames must be masked; server frames must not be."""
        from websockets.frames import Frame, Opcode

        plaintext = b"masked data"
        frame = Frame(opcode=Opcode.TEXT, data=plaintext, fin=True)

        # Serialize with mask (client->server). RFC 6455 section 5.3 requires a randomly
        # chosen 32-bit key from a strong entropy source, but does not dictate which RNG;
        # so read the key actually written on the wire instead of pinning the RNG source.
        masked = frame.serialize(mask=True)

        # The mask bit (high bit of the second header byte) must be set, and the 4-byte
        # mask key must be written after the length byte (no extended length for 11 bytes).
        assert masked[1] & 0x80
        mask_key = masked[2:6]
        assert len(mask_key) == 4

        # The on-the-wire payload must actually be XOR-masked (RFC 6455 section 5.3) with
        # that key: it must differ from the plaintext and equal the byte-wise XOR of the
        # plaintext with the key. This fails an implementation that sets the mask bit but
        # does not transform the data.
        wire_payload = masked[6:]
        assert wire_payload != plaintext
        expected = bytes(b ^ mask_key[i % 4] for i, b in enumerate(plaintext))
        assert wire_payload == expected

        # Parse expecting mask — parse(mask=True) must reverse the XOR and recover the original.
        from websockets.streams import StreamReader
        reader = StreamReader()
        reader.feed_data(masked)
        reader.feed_eof()

        parser = Frame.parse(reader.read_exact, mask=True)
        try:
            next(parser)
        except StopIteration as e:
            parsed = e.value
        else:
            pytest.fail("Parser didn't complete")

        assert bytes(parsed.data) == plaintext

    def test_close_frame_parsing(self):
        """Close frame payload encodes status code and reason."""
        from websockets.frames import Close, CloseCode

        # Parse close with code + reason
        data = struct.pack("!H", 1000) + b"normal close"
        close = Close.parse(data)
        assert close.code == CloseCode.NORMAL_CLOSURE
        assert close.reason == "normal close"

        # Serialize and verify
        serialized = close.serialize()
        assert struct.unpack("!H", serialized[:2])[0] == 1000
        assert serialized[2:] == b"normal close"

        # Empty close
        empty = Close.parse(b"")
        assert empty.code == CloseCode.NO_STATUS_RCVD
        assert empty.reason == ""

    def test_frame_binary_and_continuation(self):
        """Binary frames and continuation frames for fragmented messages."""
        from websockets.frames import Frame, Opcode
        from websockets.streams import StreamReader

        def roundtrip(frame):
            serialized = frame.serialize(mask=False)
            reader = StreamReader()
            reader.feed_data(serialized)
            reader.feed_eof()
            parser = Frame.parse(reader.read_exact, mask=False)
            try:
                next(parser)
            except StopIteration as e:
                return e.value
            pytest.fail("Parser didn't complete")

        # A fragmented message: a non-final TEXT frame followed by a final CONT
        # frame. Serialize and parse each back, verifying the DECODED fin bit and
        # opcode (the fin=False wire bit in particular) rather than echoed
        # constructor arguments.
        frag1 = roundtrip(Frame(opcode=Opcode.TEXT, data=b"Hello ", fin=False))
        assert frag1.opcode == Opcode.TEXT
        assert frag1.fin is False
        assert bytes(frag1.data) == b"Hello "

        frag2 = roundtrip(Frame(opcode=Opcode.CONT, data=b"World!", fin=True))
        assert frag2.opcode == Opcode.CONT
        assert frag2.fin is True
        assert bytes(frag2.data) == b"World!"

        # Binary opcode roundtrip with non-text bytes.
        payload = b"\x00\x01\x02\xff\xab\xcd"
        parsed = roundtrip(Frame(opcode=Opcode.BINARY, data=payload, fin=True))
        assert parsed.opcode == Opcode.BINARY
        assert bytes(parsed.data) == payload
        assert parsed.fin is True


# =============================================================================
# Headers
# =============================================================================


class TestHeaders:
    """Tests for the Headers data structure."""

    def test_headers_case_insensitive_access(self):
        """Headers provide case-insensitive key access with multi-value support."""
        from websockets.datastructures import Headers, MultipleValuesError

        h = Headers()
        h["Content-Type"] = "text/html"
        h["X-Custom"] = "value1"
        h["X-Custom"] = "value2"  # appends, doesn't replace

        # Case-insensitive access
        assert h["content-type"] == "text/html"
        assert "CONTENT-TYPE" in h

        # Multi-value raises on __getitem__
        with pytest.raises(MultipleValuesError):
            _ = h["X-Custom"]

        # get_all returns all values
        assert h.get_all("x-custom") == ["value1", "value2"]

        # Delete removes all values
        del h["x-custom"]
        assert h.get_all("x-custom") == []

    def test_headers_serialization(self):
        """Headers serialize to HTTP header format."""
        from websockets.datastructures import Headers

        h = Headers([("Host", "example.com"), ("Upgrade", "websocket")])
        s = str(h)
        assert "Host: example.com\r\n" in s
        assert "Upgrade: websocket\r\n" in s
        assert s.endswith("\r\n")

        # Serialize to bytes
        b = h.serialize()
        assert isinstance(b, bytes)
        assert b"Host: example.com\r\n" in b

    def test_headers_raw_items_and_copy(self):
        """raw_items preserves insertion order; copy creates independent copy."""
        from websockets.datastructures import Headers

        h = Headers([("A", "1"), ("B", "2"), ("A", "3")])
        items = list(h.raw_items())
        assert items == [("A", "1"), ("B", "2"), ("A", "3")]

        h2 = h.copy()
        h2["C"] = "4"
        assert h.get_all("c") == []  # original unchanged


# =============================================================================
# Header Parsing (headers.py)
# =============================================================================


class TestHeaderParsing:
    """Tests for the Sec-WebSocket-* header codecs used in handshake negotiation."""

    def test_parse_and_build_extension_and_subprotocol(self):
        """parse/build roundtrip for Sec-WebSocket-Extensions and Sec-WebSocket-Protocol."""
        from websockets.headers import (
            parse_extension, build_extension,
            parse_subprotocol, build_subprotocol,
        )

        # An externally supplied Sec-WebSocket-Extensions value carrying one valued and one
        # valueless parameter must parse into the documented
        # list[tuple[name, list[tuple[key, value]]]] shape.
        header = "permessage-deflate; server_max_window_bits=15; client_max_window_bits"
        parsed = parse_extension(header)
        assert len(parsed) == 1
        name, params = parsed[0]
        assert name == "permessage-deflate"
        param_dict = dict(params)
        assert set(param_dict) == {"server_max_window_bits", "client_max_window_bits"}
        # A parameter present with no value maps to None; a valued one carries its value
        # (compared as text so either a string or a numeric representation passes).
        assert param_dict["client_max_window_bits"] is None
        assert str(param_dict["server_max_window_bits"]) == "15"

        # build_extension is the inverse of parse_extension: re-parsing its output is stable.
        rebuilt = build_extension(parsed)
        assert parse_extension(rebuilt) == parsed

        # Subprotocols are a comma-separated token list, with the same roundtrip property.
        protos = parse_subprotocol("chat, superchat")
        assert protos == ["chat", "superchat"]
        assert parse_subprotocol(build_subprotocol(protos)) == protos


# =============================================================================
# URI Parsing
# =============================================================================


class TestURI:
    """Tests for WebSocket URI parsing."""

    def test_parse_uri_basic(self):
        """parse_uri handles ws:// and wss:// schemes with paths and queries."""
        from websockets.uri import parse_uri

        uri = parse_uri("ws://example.com/chat?room=1")
        assert uri.secure is False
        assert uri.host == "example.com"
        assert uri.port == 80
        assert uri.path == "/chat"
        assert uri.query == "room=1"
        assert uri.resource_name == "/chat?room=1"

        uri2 = parse_uri("wss://secure.example.com:8443/ws")
        assert uri2.secure is True
        assert uri2.port == 8443
        assert uri2.path == "/ws"

    def test_parse_uri_with_userinfo(self):
        """parse_uri extracts username and password from URI."""
        from websockets.uri import parse_uri

        uri = parse_uri("ws://user:pass@example.com/")
        assert uri.username == "user"
        assert uri.password == "pass"
        assert uri.user_info == ("user", "pass")

    def test_parse_uri_invalid(self):
        """parse_uri raises InvalidURI for bad schemes."""
        from websockets.uri import parse_uri
        from websockets.exceptions import InvalidURI

        with pytest.raises(InvalidURI):
            parse_uri("http://example.com")  # wrong scheme


# =============================================================================
# HTTP/1.1 Request/Response
# =============================================================================


class TestHTTP:
    """Tests for HTTP/1.1 request/response serialization used in WebSocket handshake."""

    def test_request_and_response_serialize(self):
        """HTTP request and response serialize with correct status lines and headers."""
        from websockets.http11 import Request, Response
        from websockets.datastructures import Headers

        # Request serialization
        req_headers = Headers([("Host", "example.com"), ("Upgrade", "websocket")])
        req = Request(path="/ws", headers=req_headers)
        req_bytes = req.serialize()
        assert b"GET /ws HTTP/1.1\r\n" in req_bytes
        assert b"Host: example.com\r\n" in req_bytes

        # Response serialization
        resp_headers = Headers([("Upgrade", "websocket"), ("Connection", "Upgrade")])
        resp = Response(status_code=101, reason_phrase="Switching Protocols", headers=resp_headers)
        resp_bytes = resp.serialize()
        assert b"HTTP/1.1 101 Switching Protocols\r\n" in resp_bytes


# =============================================================================
# Utils (handshake key generation / accept-key derivation)
# =============================================================================


class TestUtils:
    """Tests for the RFC 6455 opening-handshake key utilities."""

    def test_generate_and_accept_key(self):
        """generate_key creates the base64 nonce; accept_key computes the RFC 6455 accept value."""
        from websockets.utils import GUID, accept_key, generate_key

        # The magic GUID is fixed by RFC 6455 section 1.3.
        assert GUID == "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

        # RFC 6455 section 4.1: the key is a randomly selected 16-byte nonce, base64-encoded,
        # freshly chosen for each connection.
        key = generate_key()
        assert isinstance(key, str)
        assert len(base64.b64decode(key)) == 16
        assert generate_key() != key

        # RFC 6455 section 4.2.2: Sec-WebSocket-Accept is base64(sha1(key + GUID)). Checked
        # against an independent recomputation rather than against the implementation's own
        # handshake, so a wrong digest/encoding cannot pass by self-consistency.
        expected = base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()
        assert accept_key(key) == expected


# =============================================================================
# Sans-I/O Protocol State Machine
# =============================================================================


class TestProtocol:
    """Tests for the Sans-I/O protocol state machine."""

    def test_server_client_handshake(self):
        """ServerProtocol and ClientProtocol complete WebSocket handshake."""
        from websockets.server import ServerProtocol
        from websockets.client import ClientProtocol
        from websockets.uri import parse_uri

        server = ServerProtocol()
        client = ClientProtocol(parse_uri("ws://localhost/"))

        # Client generates handshake request
        request = client.connect()
        client.send_request(request)
        client_data = b"".join(client.data_to_send())

        # Server receives and processes handshake
        server.receive_data(client_data)
        events = server.events_received()
        assert len(events) == 1  # Should receive the Request

        # Server accepts handshake
        response = server.accept(events[0])
        server.send_response(response)
        server_data = b"".join(server.data_to_send())

        # Client processes response
        client.receive_data(server_data)
        events = client.events_received()

        # Both should be in OPEN state
        from websockets.protocol import State
        assert server.state == State.OPEN
        assert client.state == State.OPEN

    def test_send_receive_text_message(self):
        """Send a text message through the protocol layer and receive it."""
        from websockets.server import ServerProtocol
        from websockets.client import ClientProtocol
        from websockets.uri import parse_uri
        from websockets.protocol import State

        # Set up handshake
        server = ServerProtocol()
        client = ClientProtocol(parse_uri("ws://localhost/"))

        request = client.connect()
        client.send_request(request)
        server.receive_data(b"".join(client.data_to_send()))
        response = server.accept(server.events_received()[0])
        server.send_response(response)
        client.receive_data(b"".join(server.data_to_send()))
        client.events_received()  # drain

        assert server.state == State.OPEN
        assert client.state == State.OPEN

        # Client sends text message
        client.send_text(b"Hello from client")
        msg_data = b"".join(client.data_to_send())

        # Server receives
        server.receive_data(msg_data)
        events = server.events_received()
        assert len(events) == 1
        # Event is a Frame with text data
        from websockets.frames import Frame
        assert isinstance(events[0], Frame)
        assert bytes(events[0].data) == b"Hello from client"

    def test_close_handshake(self):
        """Protocol performs proper close handshake."""
        from websockets.server import ServerProtocol
        from websockets.client import ClientProtocol
        from websockets.uri import parse_uri
        from websockets.protocol import State

        # Handshake
        server = ServerProtocol()
        client = ClientProtocol(parse_uri("ws://localhost/"))
        request = client.connect()
        client.send_request(request)
        server.receive_data(b"".join(client.data_to_send()))
        response = server.accept(server.events_received()[0])
        server.send_response(response)
        client.receive_data(b"".join(server.data_to_send()))
        client.events_received()

        from websockets.frames import CloseCode

        # Client initiates close
        client.send_close(1000, "bye")
        close_data = b"".join(client.data_to_send())

        # Server receives close
        server.receive_data(close_data)
        server.events_received()
        # Server should auto-respond and be closing
        server_close = b"".join(server.data_to_send())

        # Client receives close response
        client.receive_data(server_close)
        client.events_received()

        # Drive both sides to the CLOSED state
        client.receive_eof()
        server.receive_eof()

        # Both endpoints fully closed, echoing the negotiated close code/reason
        assert server.state == State.CLOSED
        assert client.state == State.CLOSED
        assert server.close_code == CloseCode.NORMAL_CLOSURE
        assert server.close_reason == "bye"
        assert client.close_code == CloseCode.NORMAL_CLOSURE
        assert client.close_reason == "bye"

    def test_ping_pong(self):
        """Protocol automatically responds to pings with pongs containing the same data."""
        from websockets.server import ServerProtocol
        from websockets.client import ClientProtocol
        from websockets.uri import parse_uri
        from websockets.frames import Frame, Opcode
        from websockets.streams import StreamReader

        # Handshake
        server = ServerProtocol()
        client = ClientProtocol(parse_uri("ws://localhost/"))
        request = client.connect()
        client.send_request(request)
        server.receive_data(b"".join(client.data_to_send()))
        response = server.accept(server.events_received()[0])
        server.send_response(response)
        client.receive_data(b"".join(server.data_to_send()))
        client.events_received()

        # Client sends ping with specific data
        client.send_ping(b"ping data")
        ping_data = b"".join(client.data_to_send())

        # Server receives ping, should auto-generate pong
        server.receive_data(ping_data)
        server.events_received()
        pong_bytes = b"".join(server.data_to_send())

        # Parse the pong frame — verify it's a PONG with the same data
        reader = StreamReader()
        reader.feed_data(pong_bytes)
        reader.feed_eof()
        parser = Frame.parse(reader.read_exact, mask=False)
        try:
            next(parser)
        except StopIteration as e:
            pong_frame = e.value
        else:
            pytest.fail("Parser didn't complete")
        assert pong_frame.opcode == Opcode.PONG
        assert bytes(pong_frame.data) == b"ping data"


# =============================================================================
# End-to-End: Sync Server + Client
# =============================================================================


class TestSyncE2E:
    """End-to-end tests using sync server and client."""

    @staticmethod
    def _run_sync_server(handler, **kwargs):
        """Helper: run sync server in background thread."""
        import contextlib
        from websockets.sync.server import serve

        @contextlib.contextmanager
        def server_ctx():
            with serve(handler, "localhost", 0, **kwargs) as server:
                thread = threading.Thread(target=server.serve_forever)
                thread.start()
                try:
                    yield server
                finally:
                    server.shutdown()
                    thread.join()

        return server_ctx()

    def test_sync_server_client_echo(self):
        """Sync server echoes messages back to client."""
        from websockets.sync.client import connect

        def handler(websocket):
            for message in websocket:
                websocket.send(f"echo: {message}")

        with self._run_sync_server(handler) as server:
            host, port = server.socket.getsockname()
            with connect(f"ws://{host}:{port}") as client:
                client.send("hello")
                assert client.recv() == "echo: hello"
                client.send("world")
                assert client.recv() == "echo: world"

    def test_sync_binary_messages(self):
        """Sync server/client exchange binary messages."""
        from websockets.sync.client import connect

        def handler(websocket):
            data = websocket.recv()
            websocket.send(data)

        with self._run_sync_server(handler) as server:
            host, port = server.socket.getsockname()
            with connect(f"ws://{host}:{port}") as client:
                client.send(b"\x00\x01\x02\xff")
                assert client.recv() == b"\x00\x01\x02\xff"

    def test_sync_close_with_code(self):
        """Client closes connection with a specific close code."""
        from websockets.sync.client import connect
        from websockets.frames import CloseCode

        close_info = {}

        def handler(websocket):
            try:
                websocket.recv()
            except Exception:
                pass
            close_info["code"] = websocket.close_code

        with self._run_sync_server(handler) as server:
            host, port = server.socket.getsockname()
            with connect(f"ws://{host}:{port}") as client:
                client.close(CloseCode.NORMAL_CLOSURE, "goodbye")
            time.sleep(0.5)  # let handler complete

        assert close_info.get("code") == CloseCode.NORMAL_CLOSURE


# =============================================================================
# End-to-End: Asyncio Server + Client
# =============================================================================


class TestAsyncE2E:
    """End-to-end tests using asyncio server and client."""

    def test_asyncio_server_client_echo(self):
        """Asyncio server echoes messages back to client."""
        from websockets.asyncio.server import serve
        from websockets.asyncio.client import connect

        async def handler(websocket):
            async for message in websocket:
                await websocket.send(f"echo: {message}")

        async def run():
            async with serve(handler, "localhost", 0) as server:
                port = server.sockets[0].getsockname()[1]
                async with connect(f"ws://localhost:{port}") as client:
                    await client.send("async hello")
                    response = await client.recv()
                    assert response == "echo: async hello"

        asyncio.run(run())

    def test_asyncio_binary_message(self):
        """Asyncio server/client exchange a binary message (recv returns bytes)."""
        from websockets.asyncio.server import serve
        from websockets.asyncio.client import connect

        async def handler(websocket):
            data = await websocket.recv()
            await websocket.send(data)

        async def run():
            async with serve(handler, "localhost", 0) as server:
                port = server.sockets[0].getsockname()[1]
                async with connect(f"ws://localhost:{port}") as client:
                    payload = b"\x00\x01\x02\xff\xab\xcd"
                    await client.send(payload)
                    response = await client.recv()
                    assert response == payload

        asyncio.run(run())


# =============================================================================
# Extensions: PerMessageDeflate
# =============================================================================


class TestPerMessageDeflate:
    """Tests for the permessage-deflate compression extension."""

    def test_deflate_compress_decompress(self):
        """PerMessageDeflate compresses and decompresses frames."""
        from websockets.extensions.permessage_deflate import PerMessageDeflate
        from websockets.frames import Frame, Opcode

        ext = PerMessageDeflate(True, True, 15, 15)

        # Create a text frame
        frame = Frame(opcode=Opcode.TEXT, data=b"Hello " * 100, fin=True)
        original_data = bytes(frame.data)

        # Encode (compress)
        encoded = ext.encode(frame)
        assert encoded.rsv1 is True  # RSV1 indicates compression

        # Decode (decompress)
        decoded = ext.decode(encoded)
        assert bytes(decoded.data) == original_data

    def test_deflate_negotiation_params(self):
        """Extension factory generates and processes the exact negotiated parameters."""
        from websockets.extensions.permessage_deflate import (
            ClientPerMessageDeflateFactory,
            ServerPerMessageDeflateFactory,
        )

        # A default client offer advertises support for client_max_window_bits with no value.
        client_factory = ClientPerMessageDeflateFactory()
        params = client_factory.get_request_params()
        assert list(params) == [("client_max_window_bits", None)]

        # A default server accepts the offer; with no constraints configured on either side the
        # negotiated response carries no parameters at all.
        server_factory = ServerPerMessageDeflateFactory()
        accepted_params, extension = server_factory.process_request_params(params, [])
        assert list(accepted_params) == []
        assert extension.name == "permessage-deflate"
        assert extension.remote_max_window_bits == 15
        assert extension.local_max_window_bits == 15

        # Client processes the server response into the matching extension instance.
        client_ext = client_factory.process_response_params(accepted_params, [])
        assert client_ext.name == "permessage-deflate"
        assert client_ext.remote_max_window_bits == 15
        assert client_ext.local_max_window_bits == 15

    def test_sync_echo_with_compression(self):
        """Sync server/client communicate with permessage-deflate compression."""
        from websockets.sync.client import connect

        def handler(websocket):
            msg = websocket.recv()
            websocket.send(msg)

        with TestSyncE2E._run_sync_server(handler, compression="deflate") as server:
            host, port = server.socket.getsockname()
            with connect(f"ws://{host}:{port}", compression="deflate") as client:
                data = "compressed data " * 100
                client.send(data)
                assert client.recv() == data


# =============================================================================
# Large Payload Edge Cases
# =============================================================================


class TestLargePayloads:
    """Tests for binary protocol edge cases with different payload lengths."""

    def test_large_payload_16bit_length(self):
        """Payloads >125 bytes use 16-bit extended length field."""
        from websockets.sync.client import connect

        def handler(websocket):
            msg = websocket.recv()
            websocket.send(msg)

        with TestSyncE2E._run_sync_server(handler) as server:
            host, port = server.socket.getsockname()
            with connect(f"ws://{host}:{port}") as client:
                # 200 bytes — requires 16-bit extended length
                data = "x" * 200
                client.send(data)
                assert client.recv() == data

    def test_large_payload_64bit_length(self):
        """Payloads >65535 bytes use 64-bit extended length field."""
        from websockets.sync.client import connect

        def handler(websocket):
            msg = websocket.recv()
            websocket.send(msg)

        with TestSyncE2E._run_sync_server(handler) as server:
            host, port = server.socket.getsockname()
            with connect(f"ws://{host}:{port}") as client:
                # 70000 bytes — requires 64-bit extended length
                data = b"\xab" * 70000
                client.send(data)
                assert client.recv() == data


# =============================================================================
# CLI Tool
# =============================================================================


class TestCLI:
    """Tests for the websockets CLI tool."""

    def test_cli_connects_to_server(self):
        """websockets CLI connects to a server, and --version prints the banner."""
        from websockets.sync.server import serve

        # --version prints "websockets <version>" (e.g. "websockets 16.1").
        version_result = subprocess.run(
            ["websockets", "--version"],
            capture_output=True, text=True, timeout=10,
        )
        assert version_result.returncode == 0
        assert re.match(r"^websockets \d+\.\d+", version_result.stdout)

        def handler(websocket):
            for msg in websocket:
                websocket.send(f"echo: {msg}")

        with serve(handler, "localhost", 0) as server:
            t = threading.Thread(target=server.serve_forever)
            t.start()
            host, port = server.socket.getsockname()

            try:
                # Run CLI, pipe a message via stdin
                result = subprocess.run(
                    ["websockets", f"ws://{host}:{port}"],
                    input="hello\n",
                    capture_output=True, text=True, timeout=5,
                )
                # CLI should connect successfully, printing the banner for the target uri.
                assert f"Connected to ws://{host}:{port}." in result.stdout
            finally:
                server.shutdown()
                t.join()


# =============================================================================
# Frame Validation
# =============================================================================


class TestFrameValidation:
    """Tests for frame-level protocol validation."""

    def test_frame_check_reserved_bits(self):
        """Frame.check() rejects frames with reserved bits set (without extensions)."""
        from websockets.frames import Frame, Opcode
        from websockets.exceptions import ProtocolError

        frame = Frame(opcode=Opcode.TEXT, data=b"hello", fin=True, rsv1=True)
        with pytest.raises(ProtocolError):
            frame.check()

    def test_control_frame_too_long(self):
        """Control frames must not exceed 125 bytes."""
        from websockets.frames import Frame, Opcode
        from websockets.exceptions import ProtocolError

        frame = Frame(opcode=Opcode.CLOSE, data=b"x" * 200, fin=True)
        with pytest.raises(ProtocolError):
            frame.check()

    def test_close_frame_truncated_code(self):
        """Close frame with only 1 byte is invalid (code requires 2 bytes)."""
        from websockets.frames import Close
        from websockets.exceptions import ProtocolError

        with pytest.raises(ProtocolError):
            Close.parse(b"\x03")


# =============================================================================
# HTTP/1.1 Request/Response Parsing (generator-based)
# =============================================================================


class TestHTTPParsing:
    """Tests for HTTP/1.1 request and response parsing via generators."""

    def test_parse_http_request_and_response(self):
        """Parse raw HTTP request and response from bytes using the generator protocol."""
        from websockets.http11 import Request, Response
        from websockets.streams import StreamReader

        # Parse request
        req_raw = b"GET /ws HTTP/1.1\r\nHost: example.com\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n"
        reader = StreamReader()
        reader.feed_data(req_raw)
        reader.feed_eof()

        gen = Request.parse(reader.read_line)
        try:
            next(gen)
        except StopIteration as e:
            req = e.value
        else:
            pytest.fail("Parser didn't complete")

        assert req.path == "/ws"
        assert req.headers["Host"] == "example.com"
        assert req.headers["Upgrade"] == "websocket"

        # Parse response
        resp_raw = b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n"
        reader2 = StreamReader()
        reader2.feed_data(resp_raw)
        reader2.feed_eof()

        gen2 = Response.parse(reader2.read_line, reader2.read_exact, reader2.read_to_eof)
        try:
            next(gen2)
        except StopIteration as e:
            resp = e.value
        else:
            pytest.fail("Parser didn't complete")

        assert resp.status_code == 101
        assert resp.reason_phrase == "Switching Protocols"
        assert resp.headers["Upgrade"] == "websocket"


# =============================================================================
# Protocol: Fragmented Messages and Close Properties
# =============================================================================


class TestProtocolAdvanced:
    """Tests for advanced protocol behaviors: fragmentation, close properties."""

    @staticmethod
    def _handshake():
        from websockets.server import ServerProtocol
        from websockets.client import ClientProtocol
        from websockets.uri import parse_uri

        server = ServerProtocol()
        client = ClientProtocol(parse_uri("ws://localhost/"))
        request = client.connect()
        client.send_request(request)
        server.receive_data(b"".join(client.data_to_send()))
        response = server.accept(server.events_received()[0])
        server.send_response(response)
        client.receive_data(b"".join(server.data_to_send()))
        client.events_received()
        return server, client

    def test_fragmented_text_message(self):
        """Protocol handles fragmented text messages via continuation frames."""
        from websockets.frames import Opcode

        server, client = self._handshake()

        client.send_text(b"Hello ", fin=False)
        server.receive_data(b"".join(client.data_to_send()))
        events1 = server.events_received()
        assert len(events1) == 1
        assert events1[0].opcode == Opcode.TEXT
        assert events1[0].fin is False

        client.send_continuation(b"World!", fin=True)
        server.receive_data(b"".join(client.data_to_send()))
        events2 = server.events_received()
        assert len(events2) == 1
        assert events2[0].opcode == Opcode.CONT
        assert events2[0].fin is True
        assert bytes(events2[0].data) == b"World!"

    def test_close_handshake_without_status_code(self):
        """A close with no status code negotiates the NO_STATUS_RCVD (1005) close code.

        Unlike a close that carries an explicit code+reason, sending close with no arguments
        emits an empty-payload close frame; both endpoints surface NO_STATUS_RCVD and an empty
        reason once the handshake completes.
        """
        from websockets.frames import CloseCode

        server, client = self._handshake()

        # Client initiates a close with no status code (empty close payload).
        client.send_close()
        server.receive_data(b"".join(client.data_to_send()))
        server.events_received()
        client.receive_data(b"".join(server.data_to_send()))
        client.events_received()
        client.receive_eof()
        server.receive_eof()

        assert server.close_code == CloseCode.NO_STATUS_RCVD
        assert server.close_reason == ""
        assert client.close_code == CloseCode.NO_STATUS_RCVD
        assert client.close_reason == ""

    def test_sync_server_ping(self):
        """Sync server supports ping/pong keep-alive round trip."""
        from websockets.sync.client import connect

        def handler(websocket):
            for msg in websocket:
                websocket.send(msg)

        with TestSyncE2E._run_sync_server(handler) as server:
            host, port = server.socket.getsockname()
            with connect(f"ws://{host}:{port}") as client:
                pong_event = client.ping(b"keepalive")
                assert pong_event.wait(timeout=5)
                client.send("after ping")
                assert client.recv() == "after ping"
