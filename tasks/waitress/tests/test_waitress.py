"""
Integration tests for waitress — multi-threaded WSGI server.
Tests start a real server, make HTTP requests, and verify WSGI compliance.
"""

import email.utils
import http.client
import json
import socket
import subprocess
import threading
import time

import pytest


def _echo_app(environ, start_response):
    """WSGI app that returns environ info as JSON."""
    body = json.dumps(
        {
            "method": environ["REQUEST_METHOD"],
            "path": environ.get("PATH_INFO", "/"),
            "query": environ.get("QUERY_STRING", ""),
            "content_type": environ.get("CONTENT_TYPE", ""),
            "content_length": environ.get("CONTENT_LENGTH", ""),
            "server_name": environ.get("SERVER_NAME", ""),
            "server_port": environ.get("SERVER_PORT", ""),
            "http_host": environ.get("HTTP_HOST", ""),
            "wsgi_url_scheme": environ.get("wsgi.url_scheme", ""),
            "script_name": environ.get("SCRIPT_NAME", ""),
        }
    ).encode("utf-8")
    start_response(
        "200 OK",
        [
            ("Content-Type", "application/json"),
            ("Content-Length", str(len(body))),
        ],
    )
    return [body]


def _large_body_app(environ, start_response):
    """WSGI app that reads request body and echoes its length."""
    body_len = 0
    inp = environ["wsgi.input"]
    while True:
        chunk = inp.read(8192)
        if not chunk:
            break
        body_len += len(chunk)
    resp = json.dumps({"body_length": body_len}).encode()
    start_response(
        "200 OK",
        [
            ("Content-Type", "application/json"),
            ("Content-Length", str(len(resp))),
        ],
    )
    return [resp]


def _error_app(environ, start_response):
    """WSGI app that raises an exception."""
    raise RuntimeError("Intentional error")


def _chunked_response_app(environ, start_response):
    """WSGI app that returns response in chunks (no Content-Length)."""
    start_response("200 OK", [("Content-Type", "text/plain")])
    yield b"chunk1"
    yield b"chunk2"
    yield b"chunk3"


def _start_server(app, **kwargs):
    """Start a waitress server in a background thread, return (host, port, server)."""
    import waitress

    server = waitress.create_server(app, host="127.0.0.1", port=0, **kwargs)
    host = server.effective_host
    port = server.effective_port
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    # Wait for server to be ready
    for _ in range(50):
        try:
            s = socket.create_connection((host, port), timeout=0.1)
            s.close()
            break
        except (ConnectionRefusedError, OSError):
            time.sleep(0.05)
    return host, port, server


# =============================================================================
# Server Lifecycle
# =============================================================================


class TestServerLifecycle:
    """Tests for server creation, running, and shutdown."""

    def test_create_server_and_serve_request(self):
        """Create a server, make a GET request, verify the full WSGI environ contract."""
        host, port, server = _start_server(_echo_app)
        try:
            conn = http.client.HTTPConnection(host, port, timeout=5)
            conn.request("GET", "/hello?q=test")
            resp = conn.getresponse()
            assert resp.status == 200
            data = json.loads(resp.read())
            assert data["method"] == "GET"
            assert data["path"] == "/hello"
            assert data["query"] == "q=test"
            assert data["wsgi_url_scheme"] == "http"
            assert data["server_port"] == str(port)
            conn.close()
        finally:
            server.close()

    def test_multiple_requests_keep_alive(self):
        """HTTP/1.1 keep-alive: multiple requests on same connection."""
        host, port, server = _start_server(_echo_app)
        try:
            conn = http.client.HTTPConnection(host, port, timeout=5)
            for i in range(3):
                conn.request("GET", f"/req{i}")
                resp = conn.getresponse()
                assert resp.status == 200
                data = json.loads(resp.read())
                assert data["path"] == f"/req{i}"
            conn.close()
        finally:
            server.close()


# =============================================================================
# WSGI Compliance
# =============================================================================


class TestWSGICompliance:
    """Tests for WSGI specification compliance."""

    def test_chunked_response(self):
        """Server handles WSGI app returning iterator (chunked transfer)."""
        host, port, server = _start_server(_chunked_response_app)
        try:
            conn = http.client.HTTPConnection(host, port, timeout=5)
            conn.request("GET", "/")
            resp = conn.getresponse()
            assert resp.status == 200
            body = resp.read().decode()
            assert "chunk1" in body
            assert "chunk2" in body
            assert "chunk3" in body
            conn.close()
        finally:
            server.close()

    def test_server_error_handling(self):
        """Server returns 500 when WSGI app raises an exception."""
        host, port, server = _start_server(_error_app)
        try:
            conn = http.client.HTTPConnection(host, port, timeout=5)
            conn.request("GET", "/")
            resp = conn.getresponse()
            assert resp.status == 500
            resp.read()
            conn.close()
        finally:
            server.close()


# =============================================================================
# Adjustments / Configuration
# =============================================================================


class TestAdjustments:
    """Tests for server configuration via Adjustments."""

    def test_custom_threads_and_ident(self):
        """Server respects threads and ident configuration."""
        host, port, server = _start_server(_echo_app, threads=2, ident="TestServer")
        try:
            conn = http.client.HTTPConnection(host, port, timeout=5)
            conn.request("GET", "/")
            resp = conn.getresponse()
            assert resp.status == 200
            # Check Server header contains custom ident
            server_header = resp.getheader("Server", "")
            assert "TestServer" in server_header
            resp.read()
            conn.close()
        finally:
            server.close()

    def test_url_prefix(self):
        """Server with url_prefix sets SCRIPT_NAME in environ."""
        host, port, server = _start_server(_echo_app, url_prefix="/api")
        try:
            conn = http.client.HTTPConnection(host, port, timeout=5)
            conn.request("GET", "/api/hello")
            resp = conn.getresponse()
            assert resp.status == 200
            data = json.loads(resp.read())
            assert data["script_name"] == "/api"
            conn.close()
        finally:
            server.close()

    def test_adjustments_invalid_raises(self):
        """Invalid adjustment parameters raise ValueError via the public API."""
        import waitress

        with pytest.raises(ValueError):
            # mutual exclusion: host/port may not be set together with listen
            waitress.create_server(_echo_app, host="0.0.0.0", listen="0.0.0.0:9999")

        with pytest.raises(ValueError):
            # unknown adjustment keyword
            waitress.create_server(_echo_app, unknown_param="value")


# =============================================================================
# Proxy Headers
# =============================================================================


class TestProxyHeaders:
    """Tests for proxy header middleware."""

    def test_trusted_proxy_x_forwarded_for(self):
        """With trusted_proxy, X-Forwarded-For sets REMOTE_ADDR in environ."""

        def proxy_echo_app(environ, start_response):
            body = json.dumps(
                {
                    "remote_addr": environ.get("REMOTE_ADDR", ""),
                    "url_scheme": environ.get("wsgi.url_scheme", ""),
                    "http_host": environ.get("HTTP_HOST", ""),
                }
            ).encode()
            start_response(
                "200 OK",
                [
                    ("Content-Type", "application/json"),
                    ("Content-Length", str(len(body))),
                ],
            )
            return [body]

        host, port, server = _start_server(
            proxy_echo_app,
            trusted_proxy="*",
            trusted_proxy_headers={
                "x-forwarded-for",
                "x-forwarded-proto",
                "x-forwarded-host",
            },
        )
        try:
            conn = http.client.HTTPConnection(host, port, timeout=5)
            conn.request(
                "GET",
                "/",
                headers={
                    "X-Forwarded-For": "10.0.0.1",
                    "X-Forwarded-Proto": "https",
                    "X-Forwarded-Host": "public.example.com",
                },
            )
            resp = conn.getresponse()
            assert resp.status == 200
            data = json.loads(resp.read())
            assert data["remote_addr"] == "10.0.0.1"
            assert data["url_scheme"] == "https"
            conn.close()
        finally:
            server.close()


# =============================================================================
# HTTP Edge Cases
# =============================================================================


class TestHTTPEdgeCases:
    """Tests for HTTP protocol edge cases."""

    def test_head_request(self):
        """HEAD request returns headers but no body."""
        host, port, server = _start_server(_echo_app)
        try:
            conn = http.client.HTTPConnection(host, port, timeout=5)
            conn.request("HEAD", "/")
            resp = conn.getresponse()
            assert resp.status == 200
            body = resp.read()
            assert len(body) == 0  # HEAD should have no body
            conn.close()
        finally:
            server.close()

    def test_concurrent_requests(self):
        """Server handles concurrent requests via thread pool."""
        host, port, server = _start_server(_echo_app, threads=4)
        results = []

        def make_request(i):
            try:
                conn = http.client.HTTPConnection(host, port, timeout=5)
                conn.request("GET", f"/concurrent/{i}")
                resp = conn.getresponse()
                data = json.loads(resp.read())
                results.append(data["path"])
                conn.close()
            except Exception as e:
                results.append(f"error: {e}")

        try:
            threads = [
                threading.Thread(target=make_request, args=(i,)) for i in range(8)
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=10)

            assert len(results) == 8
            for i in range(8):
                assert f"/concurrent/{i}" in results
        finally:
            server.close()


# =============================================================================
# CLI
# =============================================================================


class TestCLI:
    """Tests for the waitress-serve CLI."""

    def test_cli_serve_binary(self):
        """waitress-serve binary loads a module:callable target and serves HTTP requests."""
        import os
        import shutil
        import tempfile

        app_dir = tempfile.mkdtemp(dir="/tmp")
        app_code = (
            "def app(environ, start_response):\n"
            '    body = b"binary cli works"\n'
            '    start_response("200 OK", [("Content-Type", "text/plain"), '
            '("Content-Length", str(len(body)))])\n'
            "    return [body]\n"
        )
        module_name = "cli_target_app"
        with open(os.path.join(app_dir, module_name + ".py"), "w") as f:
            f.write(app_code)

        # Find a free port.
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()

        # Spawn the actual waitress-serve console script against module:callable.
        # The runner appends os.getcwd() to sys.path, so run from app_dir.
        proc = subprocess.Popen(
            ["waitress-serve", f"--listen=127.0.0.1:{port}", f"{module_name}:app"],
            cwd=app_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            for _ in range(50):
                try:
                    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=0.2)
                    conn.request("GET", "/")
                    resp = conn.getresponse()
                    assert resp.status == 200
                    assert resp.read() == b"binary cli works"
                    conn.close()
                    break
                except (
                    ConnectionRefusedError,
                    OSError,
                    http.client.RemoteDisconnected,
                ):
                    time.sleep(0.1)
            else:
                pytest.fail("waitress-serve binary didn't serve in time")
        finally:
            proc.terminate()
            proc.wait(timeout=5)
            shutil.rmtree(app_dir, ignore_errors=True)

    def test_cli_serve_call_factory(self):
        """waitress-serve --call resolves MODULE:OBJECT as a WSGI app factory and calls it."""
        import os
        import shutil
        import tempfile

        app_dir = tempfile.mkdtemp(dir="/tmp")
        # `make_app` is a factory: it RETURNS the WSGI callable. `--call` must invoke it
        # (resolve_wsgi_app(..., call=True)); without --call the server would try to use the
        # factory itself as the app and fail. This exercises a distinct runner path from
        # test_cli_serve_binary, which passes a plain WSGI object with no --call.
        app_code = (
            "def make_app():\n"
            "    def app(environ, start_response):\n"
            '        body = b"factory cli works"\n'
            '        start_response("200 OK", [("Content-Type", "text/plain"), '
            '("Content-Length", str(len(body)))])\n'
            "        return [body]\n"
            "    return app\n"
        )
        module_name = "cli_factory_app"
        with open(os.path.join(app_dir, module_name + ".py"), "w") as f:
            f.write(app_code)

        # Find a free port.
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()

        # Spawn the actual waitress-serve console script with --call against the factory.
        # The runner appends os.getcwd() to sys.path, so run from app_dir.
        proc = subprocess.Popen(
            [
                "waitress-serve",
                "--call",
                f"--listen=127.0.0.1:{port}",
                f"{module_name}:make_app",
            ],
            cwd=app_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            for _ in range(50):
                try:
                    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=0.2)
                    conn.request("GET", "/")
                    resp = conn.getresponse()
                    assert resp.status == 200
                    assert resp.read() == b"factory cli works"
                    conn.close()
                    break
                except (
                    ConnectionRefusedError,
                    OSError,
                    http.client.RemoteDisconnected,
                ):
                    time.sleep(0.1)
            else:
                pytest.fail("waitress-serve --call factory didn't serve in time")
        finally:
            proc.terminate()
            proc.wait(timeout=5)
            shutil.rmtree(app_dir, ignore_errors=True)


# =============================================================================
# WSGI write() callable
# =============================================================================


class TestWSGIWrite:
    """Tests for the write() callable returned by start_response."""

    def test_start_response_write_callable(self):
        """start_response returns a write() callable for legacy WSGI apps."""

        def write_app(environ, start_response):
            write = start_response("200 OK", [("Content-Type", "text/plain")])
            write(b"written via write()")
            return []

        host, port, server = _start_server(write_app)
        try:
            conn = http.client.HTTPConnection(host, port, timeout=5)
            conn.request("GET", "/")
            resp = conn.getresponse()
            assert resp.status == 200
            body = resp.read()
            assert b"written via write()" in body
            conn.close()
        finally:
            server.close()


# =============================================================================
# Additional Environ Keys
# =============================================================================


class TestEnvironKeys:
    """Tests for additional WSGI environ keys."""

    def test_environ_http_headers(self):
        """HTTP headers are mapped to HTTP_* environ keys."""

        def header_app(environ, start_response):
            body = json.dumps(
                {
                    "accept": environ.get("HTTP_ACCEPT", ""),
                    "user_agent": environ.get("HTTP_USER_AGENT", ""),
                    "x_custom": environ.get("HTTP_X_CUSTOM", ""),
                    "request_method": environ.get("REQUEST_METHOD", ""),
                }
            ).encode()
            start_response(
                "200 OK",
                [
                    ("Content-Type", "application/json"),
                    ("Content-Length", str(len(body))),
                ],
            )
            return [body]

        host, port, server = _start_server(header_app)
        try:
            conn = http.client.HTTPConnection(host, port, timeout=5)
            conn.request(
                "GET",
                "/",
                headers={
                    "Accept": "text/html",
                    "User-Agent": "TestAgent/1.0",
                    "X-Custom": "custom-value",
                },
            )
            resp = conn.getresponse()
            assert resp.status == 200
            data = json.loads(resp.read())
            assert data["accept"] == "text/html"
            assert data["user_agent"] == "TestAgent/1.0"
            assert data["x_custom"] == "custom-value"
            conn.close()
        finally:
            server.close()

    def test_environ_wsgi_input(self):
        """wsgi.input delivers a Content-Length-framed request body (also for a non-GET/POST method)."""

        def input_app(environ, start_response):
            body_data = environ["wsgi.input"].read()
            resp = json.dumps(
                {
                    "body": body_data.decode("utf-8"),
                    "content_length": environ.get("CONTENT_LENGTH", ""),
                }
            ).encode()
            start_response(
                "200 OK",
                [
                    ("Content-Type", "application/json"),
                    ("Content-Length", str(len(resp))),
                ],
            )
            return [resp]

        host, port, server = _start_server(input_app)
        try:
            conn = http.client.HTTPConnection(host, port, timeout=5)
            body = b"test body content"
            # Use PUT (a non-GET/POST method carrying a body) to exercise body
            # delivery through wsgi.input independent of the request method.
            conn.request(
                "PUT",
                "/",
                body=body,
                headers={
                    "Content-Type": "text/plain",
                    "Content-Length": str(len(body)),
                },
            )
            resp = conn.getresponse()
            assert resp.status == 200
            data = json.loads(resp.read())
            assert data["body"] == "test body content"
            assert data["content_length"] == str(len(body))
            conn.close()
        finally:
            server.close()


# =============================================================================
# Additional Adjustments
# =============================================================================


class TestAdjustmentsAdvanced:
    """Tests for additional adjustment parameters."""

    def test_url_scheme(self):
        """url_scheme setting affects wsgi.url_scheme in environ."""
        host, port, server = _start_server(_echo_app, url_scheme="https")
        try:
            conn = http.client.HTTPConnection(host, port, timeout=5)
            conn.request("GET", "/")
            resp = conn.getresponse()
            data = json.loads(resp.read())
            assert data["wsgi_url_scheme"] == "https"
            conn.close()
        finally:
            server.close()

    def test_listen_parameter(self):
        """Server accepts listen parameter as alternative to host/port."""
        import waitress

        server = waitress.create_server(_echo_app, listen="127.0.0.1:0")
        port = server.effective_port
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        for _ in range(50):
            try:
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=0.2)
                conn.request("GET", "/test")
                resp = conn.getresponse()
                assert resp.status == 200
                resp.read()
                conn.close()
                break
            except (ConnectionRefusedError, OSError):
                time.sleep(0.05)
        else:
            pytest.fail("Server didn't start in time")
        server.close()


# =============================================================================
# Response Headers
# =============================================================================


class TestResponseHeaders:
    """Tests for response header handling."""

    def test_content_type_preserved(self):
        """Content-Type from WSGI app is preserved in response."""

        def json_app(environ, start_response):
            body = b'{"key": "value"}'
            start_response(
                "200 OK",
                [
                    ("Content-Type", "application/json; charset=utf-8"),
                    ("Content-Length", str(len(body))),
                ],
            )
            return [body]

        host, port, server = _start_server(json_app)
        try:
            conn = http.client.HTTPConnection(host, port, timeout=5)
            conn.request("GET", "/")
            resp = conn.getresponse()
            assert resp.status == 200
            ct = resp.getheader("Content-Type")
            # The app-supplied header value is passed through verbatim (only the
            # header NAME is re-capitalized), so the charset parameter must survive.
            assert ct == "application/json; charset=utf-8"
            resp.read()
            conn.close()
        finally:
            server.close()

    def test_custom_status_codes(self):
        """Server handles various HTTP status codes from WSGI app."""

        def status_app(environ, start_response):
            path = environ.get("PATH_INFO", "/")
            if path == "/created":
                start_response("201 Created", [("Content-Length", "0")])
            elif path == "/redirect":
                start_response(
                    "302 Found",
                    [("Location", "/new"), ("Content-Length", "0")],
                )
            elif path == "/not_found":
                start_response("404 Not Found", [("Content-Length", "0")])
            else:
                start_response("200 OK", [("Content-Length", "0")])
            return [b""]

        host, port, server = _start_server(status_app)
        try:
            conn = http.client.HTTPConnection(host, port, timeout=5)

            conn.request("GET", "/created")
            resp = conn.getresponse()
            assert resp.status == 201
            resp.read()

            conn.request("GET", "/redirect")
            resp = conn.getresponse()
            assert resp.status == 302
            assert resp.getheader("Location") == "/new"
            resp.read()

            conn.request("GET", "/not_found")
            resp = conn.getresponse()
            assert resp.status == 404
            resp.read()

            conn.close()
        finally:
            server.close()

    def test_response_includes_date_header(self):
        """Every HTTP response must include a Date header with a valid HTTP-date value."""
        host, port, server = _start_server(_echo_app)
        try:
            conn = http.client.HTTPConnection(host, port, timeout=5)
            conn.request("GET", "/")
            resp = conn.getresponse()
            assert resp.status == 200
            date = resp.getheader("Date")
            assert date is not None
            # Value must be a well-formed RFC 7231 HTTP-date, not just any string.
            assert email.utils.parsedate(date) is not None, f"Malformed Date header: {date!r}"
            resp.read()
            conn.close()
        finally:
            server.close()


# =============================================================================
# HTTP/1.0 Protocol Correctness
# =============================================================================


class TestHTTP10Protocol:
    """Tests for HTTP/1.0 version negotiation and connection semantics."""

    def test_http10_default_no_keepalive(self):
        """HTTP/1.0 with no keep-alive: HTTP/1.0 status line, Connection: close, and socket EOF."""
        host, port, server = _start_server(_echo_app)
        try:
            s = socket.create_connection((host, port), timeout=5)
            s.sendall(b"GET / HTTP/1.0\r\nHost: localhost\r\n\r\n")
            s.settimeout(5)
            response = b""
            closed_by_server = False
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    # Empty recv => the server closed the connection (EOF).
                    closed_by_server = True
                    break
                response += chunk
            s.close()
            assert response.startswith(
                b"HTTP/1.0 "
            ), f"Expected HTTP/1.0 response, got: {response[:30]}"
            headers = response.split(b"\r\n\r\n")[0].lower()
            assert b"connection: close" in headers
            # The defining HTTP/1.0 behavior: the server tears down the socket after
            # serving the single request, so the client observes EOF.
            assert closed_by_server, "Server did not close the HTTP/1.0 connection after one response"
        finally:
            server.close()


# =============================================================================
# Chunked Request Body
# =============================================================================


class TestChunkedRequest:
    """Tests for chunked transfer encoding in requests."""

    def test_chunked_request_body(self):
        """Server handles chunked transfer-encoded request bodies."""
        host, port, server = _start_server(_large_body_app)
        try:
            s = socket.create_connection((host, port), timeout=5)
            request = (
                b"POST /upload HTTP/1.1\r\n"
                b"Host: localhost\r\n"
                b"Transfer-Encoding: chunked\r\n"
                b"\r\n"
                b"5\r\nhello\r\n"
                b"6\r\n world\r\n"
                b"0\r\n\r\n"
            )
            s.sendall(request)
            response = b""
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                response += chunk
                if b"\r\n\r\n" in response and b"}" in response:
                    break
            s.close()
            assert b"200 OK" in response
            assert b'"body_length": 11' in response
        finally:
            server.close()


# =============================================================================
# Expose Tracebacks
# =============================================================================


class TestExposeTracebacks:
    """Tests for expose_tracebacks configuration."""

    def test_expose_tracebacks_toggle(self):
        """expose_tracebacks=True shows error details; False hides them."""
        host, port, server = _start_server(_error_app, expose_tracebacks=True)
        try:
            conn = http.client.HTTPConnection(host, port, timeout=5)
            conn.request("GET", "/")
            resp = conn.getresponse()
            assert resp.status == 500
            body = resp.read().decode("utf-8", errors="replace")
            assert "RuntimeError" in body or "Intentional error" in body
            conn.close()
        finally:
            server.close()

        host2, port2, server2 = _start_server(_error_app, expose_tracebacks=False)
        try:
            conn2 = http.client.HTTPConnection(host2, port2, timeout=5)
            conn2.request("GET", "/")
            resp2 = conn2.getresponse()
            assert resp2.status == 500
            body2 = resp2.read().decode("utf-8", errors="replace")
            assert "Intentional error" not in body2
            conn2.close()
        finally:
            server2.close()


# =============================================================================
# Implementation-Hard Protocol Tests
# =============================================================================


def _slow_echo_app(environ, start_response):
    """WSGI app that sleeps before responding, echoes path."""
    time.sleep(0.3)
    body = json.dumps({"path": environ.get("PATH_INFO", "/")}).encode()
    start_response(
        "200 OK",
        [("Content-Type", "application/json"), ("Content-Length", str(len(body)))],
    )
    return [body]


class TestImplementationHard:
    """Tests targeting behaviors where the implementation is genuinely hard."""

    def test_pipelined_responses_serialized(self):
        """Pipelined requests produce responses in order, not interleaved."""
        host, port, server = _start_server(_slow_echo_app, threads=4)
        try:
            s = socket.create_connection((host, port), timeout=10)
            pipelined = (
                b"GET /first HTTP/1.1\r\nHost: localhost\r\n\r\n"
                b"GET /second HTTP/1.1\r\nHost: localhost\r\n\r\n"
            )
            s.sendall(pipelined)
            s.settimeout(10)
            response = b""
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                response += chunk
                # Read until BOTH echoed paths have fully arrived, so the order
                # assertion below is deterministic (a 200 OK status line can arrive
                # before its response body on a chunked HTTP/1.1 response).
                if b"/first" in response and b"/second" in response:
                    break
            s.close()
            decoded = response.decode("utf-8", errors="replace")
            assert decoded.count("200 OK") >= 2
            first_pos = decoded.find("/first")
            second_pos = decoded.find("/second")
            assert (
                first_pos < second_pos
            ), "Pipelined responses out of order: /second appeared before /first"
        finally:
            server.close()

    def test_http10_keepalive_second_request(self):
        """HTTP/1.0 with Connection: keep-alive keeps connection open for a second request."""
        host, port, server = _start_server(_echo_app)
        try:
            s = socket.create_connection((host, port), timeout=5)
            s.sendall(
                b"GET /first HTTP/1.0\r\n"
                b"Host: localhost\r\n"
                b"Connection: keep-alive\r\n"
                b"\r\n"
            )
            response1 = b""
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    pytest.fail(
                        "Connection closed after first request despite keep-alive"
                    )
                response1 += chunk
                if b"\r\n\r\n" in response1:
                    header_end = response1.index(b"\r\n\r\n") + 4
                    headers_text = (
                        response1[:header_end].decode("utf-8", errors="replace").lower()
                    )
                    if "content-length:" in headers_text:
                        for line in headers_text.split("\r\n"):
                            if line.startswith("content-length:"):
                                cl = int(line.split(":")[1].strip())
                                body_so_far = response1[header_end:]
                                while len(body_so_far) < cl:
                                    body_so_far += s.recv(4096)
                                response1 = response1[:header_end] + body_so_far[:cl]
                                break
                        break

            assert b"200 OK" in response1 or b"200 ok" in response1.lower()
            assert b"/first" in response1
            # Persistence must also be signalled back to the client: an HTTP/1.0
            # client only reuses the socket when the server echoes the header.
            assert (
                b"connection: keep-alive" in response1.split(b"\r\n\r\n")[0].lower()
            ), "Missing Connection: keep-alive header in response"

            s.sendall(b"GET /second HTTP/1.0\r\n" b"Host: localhost\r\n" b"\r\n")
            response2 = b""
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                response2 += chunk
            s.close()
            assert b"/second" in response2
        finally:
            server.close()

    def test_chunked_crlf_split_across_packets(self):
        """Chunked body where trailing CRLF arrives in a separate TCP segment."""
        host, port, server = _start_server(_large_body_app)
        try:
            s = socket.create_connection((host, port), timeout=5)
            s.sendall(
                b"POST /upload HTTP/1.1\r\n"
                b"Host: localhost\r\n"
                b"Transfer-Encoding: chunked\r\n"
                b"\r\n"
            )
            s.sendall(b"5\r\nhello")
            time.sleep(0.1)
            s.sendall(b"\r\n")
            time.sleep(0.1)
            s.sendall(b"6\r\n world\r\n0\r\n\r\n")

            s.settimeout(5)
            response = b""
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                response += chunk
                if b"}" in response:
                    break
            s.close()
            assert b"200 OK" in response
            assert b'"body_length": 11' in response
        finally:
            server.close()

    def test_error_after_partial_chunked_response(self):
        """WSGI app that raises after yielding one chunk: client gets data and clean close."""

        def failing_iter_app(environ, start_response):
            start_response("200 OK", [("Content-Type", "text/plain")])
            yield b"partial-data"
            raise RuntimeError("mid-stream failure")

        host, port, server = _start_server(failing_iter_app)
        try:
            s = socket.create_connection((host, port), timeout=5)
            s.sendall(b"GET / HTTP/1.1\r\nHost: localhost\r\n\r\n")
            s.settimeout(5)
            response = b""
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                response += chunk
            s.close()
            assert b"200 OK" in response
            assert b"partial-data" in response
        finally:
            server.close()


# =============================================================================
# Coverage — Proxy Headers Deep
# =============================================================================


class TestProxyHeadersDeep:
    """Tests for deeper proxy header processing paths."""

    def test_x_forwarded_port(self):
        """X-Forwarded-Port modifies SERVER_PORT in environ."""

        def port_echo_app(environ, start_response):
            body = json.dumps({"server_port": environ.get("SERVER_PORT", "")}).encode()
            start_response(
                "200 OK",
                [
                    ("Content-Type", "application/json"),
                    ("Content-Length", str(len(body))),
                ],
            )
            return [body]

        host, port, server = _start_server(
            port_echo_app,
            trusted_proxy="*",
            trusted_proxy_headers={"x-forwarded-port"},
        )
        try:
            conn = http.client.HTTPConnection(host, port, timeout=5)
            conn.request("GET", "/", headers={"X-Forwarded-Port": "443"})
            resp = conn.getresponse()
            assert resp.status == 200
            data = json.loads(resp.read())
            assert data["server_port"] == "443"
            conn.close()
        finally:
            server.close()

    def test_trusted_proxy_count(self):
        """trusted_proxy_count selects the correct IP from a proxy chain."""

        def addr_echo_app(environ, start_response):
            body = json.dumps({"remote_addr": environ.get("REMOTE_ADDR", "")}).encode()
            start_response(
                "200 OK",
                [
                    ("Content-Type", "application/json"),
                    ("Content-Length", str(len(body))),
                ],
            )
            return [body]

        host, port, server = _start_server(
            addr_echo_app,
            trusted_proxy="*",
            trusted_proxy_headers={"x-forwarded-for"},
            trusted_proxy_count=1,
        )
        try:
            conn = http.client.HTTPConnection(host, port, timeout=5)
            conn.request(
                "GET",
                "/",
                headers={
                    "X-Forwarded-For": "203.0.113.50, 70.41.3.18, 150.172.238.178"
                },
            )
            resp = conn.getresponse()
            assert resp.status == 200
            data = json.loads(resp.read())
            assert data["remote_addr"] == "150.172.238.178"
            conn.close()
        finally:
            server.close()


# =============================================================================
# Coverage — Large Body Buffer Overflow
# =============================================================================


class TestLargeBodyOverflow:
    """Tests for request body handling that triggers buffer overflow to tempfile."""

    def test_very_large_body(self):
        """1MB+ request body (exceeds default buffer threshold) is fully readable."""
        host, port, server = _start_server(_large_body_app)
        try:
            conn = http.client.HTTPConnection(host, port, timeout=30)
            body = b"X" * (1024 * 1024 + 1)
            conn.request(
                "POST",
                "/large",
                body=body,
                headers={
                    "Content-Type": "application/octet-stream",
                    "Content-Length": str(len(body)),
                },
            )
            resp = conn.getresponse()
            assert resp.status == 200
            data = json.loads(resp.read())
            assert data["body_length"] == len(body)
            conn.close()
        finally:
            server.close()


# =============================================================================
# Coverage — Request Size Limits
# =============================================================================


class TestRequestSizeLimits:
    """Tests for request size enforcement."""

    def test_oversized_header_rejected(self):
        """Request with headers exceeding max_request_header_size is rejected."""
        host, port, server = _start_server(_echo_app, max_request_header_size=1024)
        try:
            s = socket.create_connection((host, port), timeout=5)
            big_header = b"X-Big: " + b"A" * 2000 + b"\r\n"
            s.sendall(
                b"GET / HTTP/1.1\r\n" b"Host: localhost\r\n" + big_header + b"\r\n"
            )
            response = b""
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                response += chunk
            s.close()
            status_line = response.split(b"\r\n")[0]
            status_code = int(status_line.split(b" ")[1])
            assert 400 <= status_code < 500
        finally:
            server.close()

    def test_oversized_body_rejected(self):
        """Request with body exceeding max_request_body_size is rejected."""
        host, port, server = _start_server(_large_body_app, max_request_body_size=500)
        try:
            s = socket.create_connection((host, port), timeout=5)
            body = b"X" * 1000
            s.sendall(
                b"POST /upload HTTP/1.1\r\n"
                b"Host: localhost\r\n"
                b"Content-Length: 1000\r\n"
                b"Content-Type: application/octet-stream\r\n"
                b"\r\n" + body
            )
            response = b""
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                response += chunk
            s.close()
            status_line = response.split(b"\r\n")[0]
            status_code = int(status_line.split(b" ")[1])
            assert 400 <= status_code < 500
        finally:
            server.close()
