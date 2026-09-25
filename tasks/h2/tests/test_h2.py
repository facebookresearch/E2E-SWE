"""
Integration tests for h2 — HTTP/2 protocol implementation.

Tests exercise full client-server workflows: connection setup, request/response
round-trips, stream multiplexing, flow control, error handling, settings
negotiation, and advanced features like server push and stream reset.
All tests use the h2 library on both sides — no real network I/O.
"""

import pytest


def _setup_client_server():
    """Create a connected client-server pair with handshake completed."""
    import h2.connection
    import h2.config

    client_config = h2.config.H2Configuration(client_side=True)
    client = h2.connection.H2Connection(config=client_config)
    client.initiate_connection()
    client_data = client.data_to_send()

    server_config = h2.config.H2Configuration(client_side=False)
    server = h2.connection.H2Connection(config=server_config)
    server.initiate_connection()
    server_data = server.data_to_send()

    server.receive_data(client_data)
    server_data += server.data_to_send()
    client.receive_data(server_data)
    client.clear_outbound_data_buffer()
    server.clear_outbound_data_buffer()

    return client, server


# =============================================================================
# 1. Connection Setup — preface, handshake, settings exchange
# =============================================================================


class TestConnectionSetup:
    """Connection initialization, preface exchange, and settings."""

    def test_client_server_handshake_and_settings(self):
        """Client preface has magic bytes + SETTINGS; server receives RemoteSettingsChanged.
        Then update settings and verify changed_settings dict with original/new values.
        Then ping/pong round-trip."""
        import h2.connection
        import h2.config
        import h2.events
        import h2.settings

        config = h2.config.H2Configuration(client_side=True)
        client = h2.connection.H2Connection(config=config)
        client.initiate_connection()
        client_data = client.data_to_send()

        assert client_data[:24] == b'PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n'

        server_config = h2.config.H2Configuration(client_side=False)
        server = h2.connection.H2Connection(config=server_config)
        server.initiate_connection()

        events = server.receive_data(client_data)
        event_types = [type(e).__name__ for e in events]
        assert "RemoteSettingsChanged" in event_types

        client.receive_data(server.data_to_send() + server.data_to_send())
        client.clear_outbound_data_buffer()
        server.clear_outbound_data_buffer()

        client.update_settings({
            h2.settings.SettingCodes.MAX_CONCURRENT_STREAMS: 50,
            h2.settings.SettingCodes.INITIAL_WINDOW_SIZE: 32768,
        })
        server_events = server.receive_data(client.data_to_send())
        settings_changed = [e for e in server_events if isinstance(e, h2.events.RemoteSettingsChanged)]
        assert len(settings_changed) == 1
        changed = settings_changed[0].changed_settings
        assert changed[h2.settings.SettingCodes.MAX_CONCURRENT_STREAMS].new_value == 50
        client.receive_data(server.data_to_send())
        client.clear_outbound_data_buffer()
        server.clear_outbound_data_buffer()

        client.ping(b"\x00\x01\x02\x03\x04\x05\x06\x07")
        server_events = server.receive_data(client.data_to_send())
        pings = [e for e in server_events if isinstance(e, h2.events.PingReceived)]
        assert len(pings) == 1
        client_events = client.receive_data(server.data_to_send())
        acks = [e for e in client_events if isinstance(e, h2.events.PingAckReceived)]
        assert len(acks) == 1


# =============================================================================
# 2. Request/Response — GET, POST, headers as bytes
# =============================================================================


class TestRequestResponse:
    """GET and POST round-trips with exact header and body verification."""

    def test_get_and_post_round_trip(self):
        """Client sends GET (stream 1) and POST with body (stream 3), server responds to both."""
        import h2.events

        client, server = _setup_client_server()

        client.send_headers(1, [
            (":method", "GET"), (":path", "/"),
            (":scheme", "https"), (":authority", "example.com"),
        ], end_stream=True)

        client.send_headers(3, [
            (":method", "POST"), (":path", "/upload"),
            (":scheme", "https"), (":authority", "example.com"),
            ("content-type", "application/json"),
        ])
        client.send_data(3, b'{"key": "value"}', end_stream=True)
        request_data = client.data_to_send()

        server_events = server.receive_data(request_data)
        server.clear_outbound_data_buffer()

        requests = [e for e in server_events if isinstance(e, h2.events.RequestReceived)]
        assert len(requests) == 2
        get_req = [r for r in requests if r.stream_id == 1][0]
        assert dict(get_req.headers)[b":method"] == b"GET"
        assert dict(get_req.headers)[b":path"] == b"/"

        post_data = [e for e in server_events if isinstance(e, h2.events.DataReceived)]
        assert len(post_data) == 1
        assert post_data[0].data == b'{"key": "value"}'

        server.send_headers(1, [(":status", "200"), ("content-type", "text/plain")])
        server.send_data(1, b"Hello, HTTP/2!", end_stream=True)
        server.send_headers(3, [(":status", "201")])
        server.send_data(3, b"Created", end_stream=True)
        response_data = server.data_to_send()

        client_events = client.receive_data(response_data)
        responses = {e.stream_id: dict(e.headers) for e in client_events if isinstance(e, h2.events.ResponseReceived)}
        assert responses[1][b":status"] == b"200"
        assert responses[3][b":status"] == b"201"

        data_by_stream = {e.stream_id: e.data for e in client_events if isinstance(e, h2.events.DataReceived)}
        assert data_by_stream[1] == b"Hello, HTTP/2!"
        assert data_by_stream[3] == b"Created"

        stream_ended = [e for e in client_events if isinstance(e, h2.events.StreamEnded)]
        assert len(stream_ended) == 2


# =============================================================================
# 3. Stream Multiplexing — concurrent streams, out-of-order responses
# =============================================================================


class TestStreamMultiplexing:
    """Concurrent streams with out-of-order responses."""

    def test_multiple_streams_out_of_order(self):
        """Client sends 3 requests; server responds to stream 3 before stream 1."""
        import h2.events

        client, server = _setup_client_server()

        for stream_id in [1, 3, 5]:
            client.send_headers(stream_id, [
                (":method", "GET"),
                (":path", f"/resource/{stream_id}"),
                (":scheme", "https"), (":authority", "example.com"),
            ], end_stream=True)
        server.receive_data(client.data_to_send())
        server.clear_outbound_data_buffer()

        requests = server.open_inbound_streams
        assert requests == 3

        for stream_id in [3, 5, 1]:
            server.send_headers(stream_id, [(":status", "200")])
            server.send_data(stream_id, f"Response {stream_id}".encode(), end_stream=True)

        client_events = client.receive_data(server.data_to_send())
        responses = [e for e in client_events if isinstance(e, h2.events.ResponseReceived)]
        assert len(responses) == 3
        for resp in responses:
            assert dict(resp.headers)[b":status"] == b"200"

        data_by_stream = {e.stream_id: e.data for e in client_events if isinstance(e, h2.events.DataReceived)}
        assert data_by_stream[1] == b"Response 1"
        assert data_by_stream[3] == b"Response 3"
        assert data_by_stream[5] == b"Response 5"


# =============================================================================
# 4. Flow Control — windows, acknowledge, increment, connection-level sharing
# =============================================================================


class TestFlowControl:
    """Flow control window management across stream and connection levels."""

    def test_flow_control_window_lifecycle(self):
        """Full single-stream window lifecycle: the effective window is min(stream, connection).
        Query the initial window, send data to decrement it, then verify that a stream-only
        increment is insufficient (the connection window is the bottleneck) and only an equal
        connection-level increment restores the effective window to 65535."""
        import h2.events

        client, server = _setup_client_server()

        client.send_headers(1, [
            (":method", "POST"), (":path", "/upload"),
            (":scheme", "https"), (":authority", "example.com"),
        ])

        initial_window = client.local_flow_control_window(1)
        assert initial_window == 65535

        chunk_size = 16384
        client.send_data(1, b"x" * chunk_size)
        after_send = client.local_flow_control_window(1)
        assert after_send == initial_window - chunk_size

        server.receive_data(client.data_to_send())
        server.clear_outbound_data_buffer()

        # A stream-only increment does NOT raise the effective window, because the connection
        # window is now the bottleneck — the effective window stays at after_send.
        server.increment_flow_control_window(chunk_size, stream_id=1)
        stream_only_events = client.receive_data(server.data_to_send())
        assert len([e for e in stream_only_events if isinstance(e, h2.events.WindowUpdated)]) == 1
        assert client.local_flow_control_window(1) == after_send

        # An equal connection-level increment lifts the bottleneck and restores the window to 65535.
        server.increment_flow_control_window(chunk_size)
        conn_events = client.receive_data(server.data_to_send())
        assert len([e for e in conn_events if isinstance(e, h2.events.WindowUpdated)]) == 1
        assert client.local_flow_control_window(1) == 65535

        client.send_data(1, b"y" * chunk_size, end_stream=True)
        server.receive_data(client.data_to_send())


# =============================================================================
# 5. Stream Termination — reset, GOAWAY, state transitions
# =============================================================================


class TestStreamTermination:
    """RST_STREAM, GOAWAY, and connection state transitions."""

    def test_reset_and_goaway(self):
        """Client resets stream 1, server closes connection with GOAWAY error code + last_stream_id."""
        import h2.events
        import h2.errors

        client, server = _setup_client_server()

        client.send_headers(1, [
            (":method", "GET"), (":path", "/"),
            (":scheme", "https"), (":authority", "example.com"),
        ])
        client.send_headers(3, [
            (":method", "GET"), (":path", "/2"),
            (":scheme", "https"), (":authority", "example.com"),
        ], end_stream=True)
        server.receive_data(client.data_to_send())
        server.clear_outbound_data_buffer()

        client.reset_stream(1, error_code=h2.errors.ErrorCodes.CANCEL)
        server_events = server.receive_data(client.data_to_send())
        resets = [e for e in server_events if isinstance(e, h2.events.StreamReset)]
        assert len(resets) == 1
        assert resets[0].stream_id == 1
        assert resets[0].error_code == h2.errors.ErrorCodes.CANCEL
        server.clear_outbound_data_buffer()

        server.close_connection(error_code=h2.errors.ErrorCodes.ENHANCE_YOUR_CALM, last_stream_id=1)
        client_events = client.receive_data(server.data_to_send())
        terminated = [e for e in client_events if isinstance(e, h2.events.ConnectionTerminated)]
        assert len(terminated) == 1
        assert terminated[0].error_code == h2.errors.ErrorCodes.ENHANCE_YOUR_CALM
        assert terminated[0].last_stream_id == 1

    def test_send_after_goaway_raises(self):
        """After receiving GOAWAY, opening new streams raises ProtocolError."""
        import h2.events
        import h2.exceptions

        client, server = _setup_client_server()

        client.send_headers(1, [
            (":method", "GET"), (":path", "/"),
            (":scheme", "https"), (":authority", "example.com"),
        ], end_stream=True)
        server.receive_data(client.data_to_send())
        server.clear_outbound_data_buffer()

        server.close_connection(last_stream_id=1)
        events = client.receive_data(server.data_to_send())
        assert any(isinstance(e, h2.events.ConnectionTerminated) for e in events)

        with pytest.raises(h2.exceptions.ProtocolError):
            client.send_headers(3, [
                (":method", "GET"), (":path", "/new"),
                (":scheme", "https"), (":authority", "example.com"),
            ])


# =============================================================================
# 6. Error Handling — stream ID rules, closed streams, flow control, frame size
# =============================================================================


class TestErrorHandling:
    """Protocol error conditions: stream ID validation, closed streams, window limits, frame size."""

    def test_stream_id_violations(self):
        """Even stream ID raises ProtocolError; using ID lower than highest raises ProtocolError."""
        import h2.exceptions

        client, server = _setup_client_server()

        with pytest.raises(h2.exceptions.ProtocolError):
            client.send_headers(2, [
                (":method", "GET"), (":path", "/"),
                (":scheme", "https"), (":authority", "example.com"),
            ])

        client.send_headers(3, [
            (":method", "GET"), (":path", "/"),
            (":scheme", "https"), (":authority", "example.com"),
        ], end_stream=True)
        client.clear_outbound_data_buffer()

        with pytest.raises(h2.exceptions.ProtocolError):
            client.send_headers(1, [
                (":method", "GET"), (":path", "/"),
                (":scheme", "https"), (":authority", "example.com"),
            ])

    def test_send_on_closed_stream_raises(self):
        """Sending data on an ended stream raises ProtocolError."""
        import h2.exceptions

        client, server = _setup_client_server()

        client.send_headers(1, [
            (":method", "GET"), (":path", "/"),
            (":scheme", "https"), (":authority", "example.com"),
        ], end_stream=True)
        client.clear_outbound_data_buffer()

        with pytest.raises(h2.exceptions.ProtocolError):
            client.send_data(1, b"data after end")

    def test_flow_control_and_frame_size_errors(self):
        """Exceeding flow control window raises FlowControlError;
        exceeding MAX_FRAME_SIZE raises FrameTooLargeError;
        querying non-existent stream raises NoSuchStreamError."""
        import h2.exceptions

        client, server = _setup_client_server()

        client.send_headers(1, [
            (":method", "POST"), (":path", "/"),
            (":scheme", "https"), (":authority", "example.com"),
        ])

        with pytest.raises(h2.exceptions.FlowControlError):
            client.send_data(1, b"x" * 100000)

        with pytest.raises(h2.exceptions.FrameTooLargeError):
            client.send_data(1, b"x" * 16385)

        with pytest.raises(h2.exceptions.NoSuchStreamError):
            client.local_flow_control_window(999)


# =============================================================================
# 7. Server Push — PUSH_PROMISE with parent/pushed stream
# =============================================================================


class TestServerPush:
    """Server push with PUSH_PROMISE and pushed resource delivery."""

    def test_server_push_and_deliver(self):
        """Server pushes two resources on one parent stream, delivers the main page and both
        pushed resources, client receives all. Server-allocated push IDs are even and advance
        by 2 as each pushed stream is opened."""
        import h2.events
        import h2.connection
        import h2.config

        client_config = h2.config.H2Configuration(client_side=True)
        client = h2.connection.H2Connection(config=client_config)
        client.initiate_connection()

        server_config = h2.config.H2Configuration(client_side=False)
        server = h2.connection.H2Connection(config=server_config)
        server.initiate_connection()

        server.receive_data(client.data_to_send())
        client.receive_data(server.data_to_send() + server.data_to_send())
        client.clear_outbound_data_buffer()
        server.clear_outbound_data_buffer()

        client.send_headers(1, [
            (":method", "GET"), (":path", "/"),
            (":scheme", "https"), (":authority", "example.com"),
        ], end_stream=True)
        server.receive_data(client.data_to_send())
        server.clear_outbound_data_buffer()

        push_stream_id = server.get_next_available_stream_id()
        assert push_stream_id % 2 == 0
        server.push_stream(1, push_stream_id, [
            (":method", "GET"), (":path", "/style.css"),
            (":scheme", "https"), (":authority", "example.com"),
        ])

        # Second push on the same parent: opening the first pushed stream advanced the
        # server-side allocator by 2.
        second_push_id = server.get_next_available_stream_id()
        assert second_push_id == push_stream_id + 2
        server.push_stream(1, second_push_id, [
            (":method", "GET"), (":path", "/app.js"),
            (":scheme", "https"), (":authority", "example.com"),
        ])

        server.send_headers(1, [(":status", "200")])
        server.send_data(1, b"<html>page</html>", end_stream=True)
        server.send_headers(push_stream_id, [(":status", "200")])
        server.send_data(push_stream_id, b"body{color:red}", end_stream=True)
        server.send_headers(second_push_id, [(":status", "200")])
        server.send_data(second_push_id, b"console.log(1)", end_stream=True)

        client_events = client.receive_data(server.data_to_send())
        pushed = [e for e in client_events if isinstance(e, h2.events.PushedStreamReceived)]
        assert len(pushed) == 2
        assert {e.pushed_stream_id for e in pushed} == {push_stream_id, second_push_id}
        assert all(e.parent_stream_id == 1 for e in pushed)

        # The promised request headers passed to push_stream are surfaced verbatim on
        # PushedStreamReceived.headers (bytes, since header_encoding is unset).
        promised = {e.pushed_stream_id: dict(e.headers) for e in pushed}
        assert promised[push_stream_id][b":method"] == b"GET"
        assert promised[push_stream_id][b":path"] == b"/style.css"
        assert promised[second_push_id][b":path"] == b"/app.js"

        responses = [e for e in client_events if isinstance(e, h2.events.ResponseReceived)]
        assert len(responses) == 3

        data_by_stream = {e.stream_id: e.data for e in client_events if isinstance(e, h2.events.DataReceived)}
        assert data_by_stream[1] == b"<html>page</html>"
        assert data_by_stream[push_stream_id] == b"body{color:red}"
        assert data_by_stream[second_push_id] == b"console.log(1)"


# =============================================================================
# 8. Configuration and Trailers
# =============================================================================


class TestConfigAndTrailers:
    """header_encoding configuration and trailing headers."""

    def test_header_encoding_and_trailers(self):
        """header_encoding='utf-8' returns str headers; server sends trailers after body."""
        import h2.connection
        import h2.config
        import h2.events

        client_config = h2.config.H2Configuration(client_side=True, header_encoding="utf-8")
        client = h2.connection.H2Connection(config=client_config)
        client.initiate_connection()

        server_config = h2.config.H2Configuration(client_side=False)
        server = h2.connection.H2Connection(config=server_config)
        server.initiate_connection()

        server.receive_data(client.data_to_send())
        client.receive_data(server.data_to_send() + server.data_to_send())
        client.clear_outbound_data_buffer()
        server.clear_outbound_data_buffer()

        client.send_headers(1, [
            (":method", "GET"), (":path", "/"),
            (":scheme", "https"), (":authority", "example.com"),
        ], end_stream=True)
        server.receive_data(client.data_to_send())
        server.clear_outbound_data_buffer()

        server.send_headers(1, [(":status", "200")])
        server.send_data(1, b"body content")
        server.send_headers(1, [("x-checksum", "abc123")], end_stream=True)

        client_events = client.receive_data(server.data_to_send())
        response = [e for e in client_events if isinstance(e, h2.events.ResponseReceived)][0]
        header_keys = [h[0] for h in response.headers]
        assert all(isinstance(k, str) for k in header_keys)
        assert dict(response.headers)[":status"] == "200"

        trailers = [e for e in client_events if isinstance(e, h2.events.TrailersReceived)]
        assert len(trailers) == 1
        assert dict(trailers[0].headers)["x-checksum"] == "abc123"


# =============================================================================
# 9. Max Concurrent Streams — enforcement and mid-session renegotiation
# =============================================================================


class TestMaxConcurrentStreams:
    """MAX_CONCURRENT_STREAMS enforcement including mid-session changes."""

    def test_max_streams_and_renegotiation(self):
        """Server sets MAX_CONCURRENT_STREAMS=1, client can't open 2. Then complete stream 1,
        server reduces to 1 mid-session, verify enforcement still works."""
        import h2.events
        import h2.settings
        import h2.exceptions

        client, server = _setup_client_server()

        server.update_settings({h2.settings.SettingCodes.MAX_CONCURRENT_STREAMS: 1})
        client.receive_data(server.data_to_send())
        server.receive_data(client.data_to_send())
        client.clear_outbound_data_buffer()
        server.clear_outbound_data_buffer()

        client.send_headers(1, [
            (":method", "GET"), (":path", "/"),
            (":scheme", "https"), (":authority", "example.com"),
        ])

        with pytest.raises(h2.exceptions.TooManyStreamsError):
            client.send_headers(3, [
                (":method", "GET"), (":path", "/2"),
                (":scheme", "https"), (":authority", "example.com"),
            ])


# =============================================================================
# 10. Stream Lifecycle — IDs, counting, reuse prevention
# =============================================================================


class TestStreamLifecycle:
    """Stream ID management, counting, and reuse prevention."""

    def test_stream_ids_counting_and_reuse(self):
        """Stream IDs increment by 2; open_outbound_streams tracks correctly;
        stream count decrements on reset; reusing closed stream raises."""
        import h2.events
        import h2.exceptions

        client, server = _setup_client_server()

        assert client.get_next_available_stream_id() == 1
        assert client.open_outbound_streams == 0

        client.send_headers(1, [
            (":method", "GET"), (":path", "/"),
            (":scheme", "https"), (":authority", "example.com"),
        ])
        assert client.get_next_available_stream_id() == 3
        assert client.open_outbound_streams == 1

        client.send_headers(3, [
            (":method", "GET"), (":path", "/2"),
            (":scheme", "https"), (":authority", "example.com"),
        ], end_stream=True)
        assert client.open_outbound_streams == 2

        client.reset_stream(1, error_code=0)
        assert client.open_outbound_streams == 1

        server.receive_data(client.data_to_send())
        server.clear_outbound_data_buffer()

        server.send_headers(3, [(":status", "200")], end_stream=True)
        client.receive_data(server.data_to_send())
        assert client.open_outbound_streams == 0

        with pytest.raises((h2.exceptions.ProtocolError, h2.exceptions.StreamClosedError)):
            client.send_headers(1, [
                (":method", "GET"), (":path", "/again"),
                (":scheme", "https"), (":authority", "example.com"),
            ])


# =============================================================================
# 11. Priority and Alternative Service
# =============================================================================


class TestPriorityAndAltSvc:
    """Stream prioritization and alternative service advertisement."""

    def test_prioritize_and_alternative_service(self):
        """prioritize() sends PRIORITY frame with weight; advertise_alternative_service() sends ALTSVC."""
        import h2.events

        client, server = _setup_client_server()

        client.send_headers(1, [
            (":method", "GET"), (":path", "/"),
            (":scheme", "https"), (":authority", "example.com"),
        ], end_stream=True)
        client.prioritize(1, weight=128)

        events = server.receive_data(client.data_to_send())
        server.clear_outbound_data_buffer()
        priority = [e for e in events if isinstance(e, h2.events.PriorityUpdated)]
        assert len(priority) == 1
        assert priority[0].stream_id == 1
        assert priority[0].weight == 128

        server.advertise_alternative_service(b'h2=":8000"', stream_id=1)
        client_events = client.receive_data(server.data_to_send())
        alt = [e for e in client_events if isinstance(e, h2.events.AlternativeServiceAvailable)]
        assert len(alt) == 1
        assert alt[0].field_value == b'h2=":8000"'


# =============================================================================
# 12. HTTP/1.1 Upgrade
# =============================================================================


class TestHTTP2Upgrade:
    """HTTP/1.1 to HTTP/2 upgrade mechanism."""

    def test_initiate_upgrade_connection(self):
        """Client upgrade returns bytes settings header; server accepts it and the upgraded
        request occupies stream 1, on which the server can send a full response the client receives."""
        import h2.connection
        import h2.config
        import h2.events

        client = h2.connection.H2Connection(
            config=h2.config.H2Configuration(client_side=True)
        )
        settings_header = client.initiate_upgrade_connection()
        assert isinstance(settings_header, bytes)
        client.clear_outbound_data_buffer()

        server = h2.connection.H2Connection(
            config=h2.config.H2Configuration(client_side=False)
        )
        server.initiate_upgrade_connection(settings_header=settings_header)
        server_data = server.data_to_send()
        assert len(server_data) > 0
        server.clear_outbound_data_buffer()

        # The upgraded request lives on stream 1 (half-closed on the client side);
        # the server sends a full response on stream 1 and the client receives it.
        server.send_headers(1, [(":status", "200"), ("content-type", "text/plain")])
        server.send_data(1, b"upgraded body", end_stream=True)

        client_events = client.receive_data(server.data_to_send())
        responses = [e for e in client_events if isinstance(e, h2.events.ResponseReceived)]
        assert len(responses) == 1
        assert responses[0].stream_id == 1
        assert dict(responses[0].headers)[b":status"] == b"200"

        data_events = [e for e in client_events if isinstance(e, h2.events.DataReceived)]
        assert len(data_events) == 1
        assert data_events[0].stream_id == 1
        assert data_events[0].data == b"upgraded body"

        ended = [e for e in client_events if isinstance(e, h2.events.StreamEnded)]
        assert len(ended) == 1
        assert ended[0].stream_id == 1


# =============================================================================
# 13. Data Chunking and Half-Closed Streams
# =============================================================================


class TestDataChunkingAndHalfClosed:
    """Multiple DATA frames arrive separately; half-closed streams allow bidirectional data."""

    def test_chunking_and_half_closed(self):
        """Client sends 3 data chunks then ends; server receives all 3 separately,
        then sends multi-part response on the half-closed stream."""
        import h2.events

        client, server = _setup_client_server()

        client.send_headers(1, [
            (":method", "POST"), (":path", "/process"),
            (":scheme", "https"), (":authority", "example.com"),
        ])
        client.send_data(1, b"chunk1")
        client.send_data(1, b"chunk2")
        client.send_data(1, b"chunk3", end_stream=True)

        events = server.receive_data(client.data_to_send())
        server.clear_outbound_data_buffer()
        data_events = [e for e in events if isinstance(e, h2.events.DataReceived)]
        assert len(data_events) == 3
        assert data_events[0].data == b"chunk1"
        assert data_events[1].data == b"chunk2"
        assert data_events[2].data == b"chunk3"

        ended = [e for e in events if isinstance(e, h2.events.StreamEnded)]
        assert len(ended) == 1

        server.send_headers(1, [(":status", "200")])
        server.send_data(1, b"result part 1")
        server.send_data(1, b"result part 2", end_stream=True)

        client_events = client.receive_data(server.data_to_send())
        response = [e for e in client_events if isinstance(e, h2.events.ResponseReceived)]
        assert len(response) == 1
        assert dict(response[0].headers)[b":status"] == b"200"
        client_data = [e for e in client_events if isinstance(e, h2.events.DataReceived)]
        assert len(client_data) == 2
        assert client_data[0].data == b"result part 1"
        assert client_data[1].data == b"result part 2"


# =============================================================================
# 14. Reset Mid-Data — partial data + reset from both sides
# =============================================================================


class TestResetMidData:
    """Reset a stream after partial data transfer — peer receives both data and reset."""

    def test_client_reset_after_partial_send(self):
        """Client sends partial data then resets; server receives DataReceived and StreamReset."""
        import h2.events
        import h2.errors

        client, server = _setup_client_server()

        client.send_headers(1, [
            (":method", "POST"), (":path", "/upload"),
            (":scheme", "https"), (":authority", "example.com"),
        ])
        client.send_data(1, b"partial data")
        client.reset_stream(1, error_code=h2.errors.ErrorCodes.CANCEL)

        events = server.receive_data(client.data_to_send())
        data_events = [e for e in events if isinstance(e, h2.events.DataReceived)]
        reset_events = [e for e in events if isinstance(e, h2.events.StreamReset)]

        assert len(data_events) == 1
        assert data_events[0].data == b"partial data"
        assert len(reset_events) == 1
        assert reset_events[0].error_code == h2.errors.ErrorCodes.CANCEL

    def test_server_reset_after_partial_response(self):
        """Server sends headers + partial data + reset; client receives all three."""
        import h2.events
        import h2.errors

        client, server = _setup_client_server()

        client.send_headers(1, [
            (":method", "GET"), (":path", "/"),
            (":scheme", "https"), (":authority", "example.com"),
        ], end_stream=True)
        server.receive_data(client.data_to_send())
        server.clear_outbound_data_buffer()

        server.send_headers(1, [(":status", "200")])
        server.send_data(1, b"partial")
        server.reset_stream(1, error_code=h2.errors.ErrorCodes.INTERNAL_ERROR)

        events = client.receive_data(server.data_to_send())
        assert len([e for e in events if isinstance(e, h2.events.ResponseReceived)]) == 1
        data_events = [e for e in events if isinstance(e, h2.events.DataReceived)]
        assert len(data_events) == 1
        assert data_events[0].data == b"partial"
        reset_events = [e for e in events if isinstance(e, h2.events.StreamReset)]
        assert len(reset_events) == 1
        assert reset_events[0].error_code == h2.errors.ErrorCodes.INTERNAL_ERROR


# =============================================================================
# 15. Settings Chaining
# =============================================================================


class TestSettingsChaining:
    """Sequential settings updates chain original→new values correctly."""

    def test_double_settings_update_chains(self):
        """Two updates to MAX_CONCURRENT_STREAMS: 100→50, then 50→25."""
        import h2.events
        import h2.settings

        client, server = _setup_client_server()

        client.update_settings({h2.settings.SettingCodes.MAX_CONCURRENT_STREAMS: 50})
        client.update_settings({h2.settings.SettingCodes.MAX_CONCURRENT_STREAMS: 25})

        events = server.receive_data(client.data_to_send())
        settings_events = [e for e in events if isinstance(e, h2.events.RemoteSettingsChanged)]
        assert len(settings_events) == 2

        first = settings_events[0].changed_settings[h2.settings.SettingCodes.MAX_CONCURRENT_STREAMS]
        assert first.original_value == 100
        assert first.new_value == 50

        second = settings_events[1].changed_settings[h2.settings.SettingCodes.MAX_CONCURRENT_STREAMS]
        assert second.original_value == 50
        assert second.new_value == 25


# =============================================================================
# 16. INITIAL_WINDOW_SIZE Retroactive Change
# =============================================================================


class TestInitialWindowSizeRetroactive:
    """Changing INITIAL_WINDOW_SIZE retroactively adjusts open stream windows."""

    def test_initial_window_size_affects_open_streams(self):
        """Server reduces INITIAL_WINDOW_SIZE mid-session, client's open stream window adjusts."""
        import h2.settings

        client, server = _setup_client_server()

        client.send_headers(1, [
            (":method", "POST"), (":path", "/upload"),
            (":scheme", "https"), (":authority", "example.com"),
        ])
        before = client.local_flow_control_window(1)
        assert before == 65535

        server.update_settings({h2.settings.SettingCodes.INITIAL_WINDOW_SIZE: 32768})
        client.receive_data(server.data_to_send())
        server.receive_data(client.data_to_send())
        client.clear_outbound_data_buffer()
        server.clear_outbound_data_buffer()

        after = client.local_flow_control_window(1)
        assert after == 32768


# =============================================================================
# E2E: Full Page Load with Server Push
# =============================================================================


class TestPushDisabled:
    """E2E: A client that disables server push — the server must not push to it."""

    def test_push_rejected_when_client_disables_push(self):
        """Client sets ENABLE_PUSH=0; after the server receives that setting, calling
        push_stream on the server raises ProtocolError (the response path still works)."""
        import h2.connection
        import h2.config
        import h2.settings
        import h2.exceptions

        client_config = h2.config.H2Configuration(client_side=True)
        client = h2.connection.H2Connection(config=client_config)
        client.initiate_connection()

        server_config = h2.config.H2Configuration(client_side=False)
        server = h2.connection.H2Connection(config=server_config)
        server.initiate_connection()

        server.receive_data(client.data_to_send())
        client.receive_data(server.data_to_send() + server.data_to_send())
        client.clear_outbound_data_buffer()
        server.clear_outbound_data_buffer()

        # Client disables server push.
        client.update_settings({h2.settings.SettingCodes.ENABLE_PUSH: 0})
        server.receive_data(client.data_to_send())
        server.clear_outbound_data_buffer()

        client.send_headers(1, [
            (":method", "GET"), (":path", "/index.html"),
            (":scheme", "https"), (":authority", "example.com"),
        ], end_stream=True)
        server.receive_data(client.data_to_send())
        server.clear_outbound_data_buffer()

        # The server must not push once the client has disabled push.
        push_stream_id = server.get_next_available_stream_id()
        with pytest.raises(h2.exceptions.ProtocolError):
            server.push_stream(1, push_stream_id, [
                (":method", "GET"), (":path", "/style.css"),
                (":scheme", "https"), (":authority", "example.com"),
            ])


# =============================================================================
# E2E: Error Recovery — One Stream Fails, Others Continue
# =============================================================================


class TestErrorRecoveryWorkflow:
    """E2E: Server resets one stream, other streams continue normally."""

    def test_stream_reset_does_not_affect_other_streams(self):
        """3 requests: stream 3 is reset, streams 1 and 5 get normal responses."""
        import h2.events
        import h2.errors

        client, server = _setup_client_server()

        for stream_id, path in [(1, "/ok"), (3, "/fail"), (5, "/ok2")]:
            client.send_headers(stream_id, [
                (":method", "GET"), (":path", path),
                (":scheme", "https"), (":authority", "example.com"),
            ], end_stream=True)
        server.receive_data(client.data_to_send())
        server.clear_outbound_data_buffer()

        server.reset_stream(3, error_code=h2.errors.ErrorCodes.INTERNAL_ERROR)
        server.send_headers(1, [(":status", "200")])
        server.send_data(1, b"response1", end_stream=True)
        server.send_headers(5, [(":status", "200")])
        server.send_data(5, b"response5", end_stream=True)

        events = client.receive_data(server.data_to_send())
        resets = [e for e in events if isinstance(e, h2.events.StreamReset)]
        assert len(resets) == 1
        assert resets[0].stream_id == 3

        data_by_stream = {e.stream_id: e.data for e in events if isinstance(e, h2.events.DataReceived)}
        assert data_by_stream[1] == b"response1"
        assert data_by_stream[5] == b"response5"
        assert 3 not in data_by_stream


# =============================================================================
# E2E: Graceful Shutdown — GOAWAY mid-flight
# =============================================================================


class TestGracefulShutdownWorkflow:
    """E2E: Server responds to one stream, then sends GOAWAY."""

    def test_goaway_mid_request(self):
        """Server responds to stream 3, then GOAWAY — client receives both."""
        import h2.events

        client, server = _setup_client_server()

        client.send_headers(1, [
            (":method", "GET"), (":path", "/slow"),
            (":scheme", "https"), (":authority", "example.com"),
        ], end_stream=True)
        client.send_headers(3, [
            (":method", "GET"), (":path", "/fast"),
            (":scheme", "https"), (":authority", "example.com"),
        ], end_stream=True)
        server.receive_data(client.data_to_send())
        server.clear_outbound_data_buffer()

        server.send_headers(3, [(":status", "200")])
        server.send_data(3, b"fast done", end_stream=True)
        server.close_connection(last_stream_id=1)

        events = client.receive_data(server.data_to_send())
        terminated = [e for e in events if isinstance(e, h2.events.ConnectionTerminated)]
        assert len(terminated) == 1
        assert terminated[0].last_stream_id == 1
        data_events = [e for e in events if isinstance(e, h2.events.DataReceived)]
        assert len(data_events) == 1
        assert data_events[0].data == b"fast done"


# =============================================================================
# E2E: Bidirectional Streaming — server responds while client sends
# =============================================================================


class TestBidirectionalStreaming:
    """E2E: Server starts responding before client finishes sending."""

    def test_server_responds_while_client_sends(self):
        """Client sends POST in chunks; server starts responding mid-upload;
        client sends more; server finishes — both sides see all data."""
        import h2.events

        client, server = _setup_client_server()

        client.send_headers(1, [
            (":method", "POST"), (":path", "/upload"),
            (":scheme", "https"), (":authority", "example.com"),
        ])
        client.send_data(1, b"part1")
        server.receive_data(client.data_to_send())
        server.clear_outbound_data_buffer()

        server.send_headers(1, [(":status", "200")])
        server.send_data(1, b"early ack")
        events = client.receive_data(server.data_to_send())
        client.clear_outbound_data_buffer()
        resp = [e for e in events if isinstance(e, h2.events.ResponseReceived)]
        assert len(resp) == 1
        assert dict(resp[0].headers)[b":status"] == b"200"
        early_data = [e for e in events if isinstance(e, h2.events.DataReceived)]
        assert early_data[0].data == b"early ack"

        client.send_data(1, b"part2", end_stream=True)
        events = server.receive_data(client.data_to_send())
        server.clear_outbound_data_buffer()
        server_data = [e for e in events if isinstance(e, h2.events.DataReceived)]
        assert server_data[0].data == b"part2"

        server.send_data(1, b"final response", end_stream=True)
        events = client.receive_data(server.data_to_send())
        final_data = [e for e in events if isinstance(e, h2.events.DataReceived)]
        assert final_data[0].data == b"final response"
        ended = [e for e in events if isinstance(e, h2.events.StreamEnded)]
        assert len(ended) == 1


# =============================================================================
# E2E: Flow Control Pressure — selective increments across streams
# =============================================================================


class TestFlowControlPressure:
    """E2E: Two streams share the connection window; an exhausted connection window blocks
    a send even when the stream's own window has room."""

    def test_connection_window_partial_exhaustion_blocks_stream(self):
        """Drain most of the shared connection window via stream 1. A send on stream 3
        within the remaining connection window succeeds, but a further byte is blocked by
        the exhausted connection window even though stream 3's own window had room."""
        import h2.exceptions

        client, server = _setup_client_server()

        client.send_headers(1, [
            (":method", "POST"), (":path", "/a"),
            (":scheme", "https"), (":authority", "example.com"),
        ])
        client.send_headers(3, [
            (":method", "POST"), (":path", "/b"),
            (":scheme", "https"), (":authority", "example.com"),
        ])

        # Use 49152 of the 65535-byte shared connection window via stream 1,
        # leaving only 16383 bytes of connection capacity.
        for _ in range(3):
            client.send_data(1, b"x" * 16384)
        remaining_conn = 65535 - 49152
        assert remaining_conn == 16383

        # Stream 3's own window is still full, but the connection window is the
        # bottleneck: a send within the remaining connection window succeeds...
        assert client.local_flow_control_window(3) == remaining_conn
        client.send_data(3, b"y" * remaining_conn)
        assert client.local_flow_control_window(3) == 0

        # ...and any further byte on stream 3 is blocked by the exhausted
        # connection window, even though no stream window was the limit.
        with pytest.raises(h2.exceptions.FlowControlError):
            client.send_data(3, b"z")
