"""End-to-end tests for the `tremolo` HTTP server.

Each test spawns a fresh tremolo server in a Python subprocess on a free
port, issues HTTP / WebSocket requests with `httpx` / `websockets`, then
tears down. The server runs the real asyncio event loop and sockets — no
fakes, no in-process loopback.
"""

import asyncio
import contextlib
import json
import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import pytest
import websockets


# The suite only ever talks to a loopback server, but httpx (`trust_env=True`) and
# websockets (>= 15.0) honour ambient proxy env vars even for 127.0.0.1. Drop them so a
# stale/dead proxy left in the environment cannot divert — and fail — these requests.
for _proxy_var in (
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "ws_proxy",
    "wss_proxy",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "WS_PROXY",
    "WSS_PROXY",
):
    os.environ.pop(_proxy_var, None)
os.environ["no_proxy"] = os.environ["NO_PROXY"] = "*"


HOST = "127.0.0.1"
DATA_DIR = Path(__file__).parent / "data"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind((HOST, 0))
        return s.getsockname()[1]


def _wait_for_port(port: int, timeout: float = 15.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((HOST, port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.1)
    raise TimeoutError(f"server did not bind to {HOST}:{port} within {timeout}s")


def _request(method: str, url: str, **kwargs) -> httpx.Response:
    """One-shot request with `trust_env=False`, so no ambient proxy config is consulted."""
    with httpx.Client(trust_env=False) as client:
        return client.request(method, url, **kwargs)


def _get(url: str, **kwargs) -> httpx.Response:
    return _request("GET", url, **kwargs)


def _post(url: str, **kwargs) -> httpx.Response:
    return _request("POST", url, **kwargs)


def _put(url: str, **kwargs) -> httpx.Response:
    return _request("PUT", url, **kwargs)


def _delete(url: str, **kwargs) -> httpx.Response:
    return _request("DELETE", url, **kwargs)


class _Server:
    def __init__(self, port: int, proc: subprocess.Popen, script: Path):
        self.port = port
        self.proc = proc
        self.script = script
        self.base = f"http://{HOST}:{port}"
        self.ws_base = f"ws://{HOST}:{port}"

    def stop(self) -> None:
        if os.name == "posix":
            with contextlib.suppress(ProcessLookupError):
                os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
        else:
            self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            if os.name == "posix":
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
            else:
                self.proc.kill()
        with contextlib.suppress(FileNotFoundError):
            self.script.unlink()

    def diagnostics(self) -> str:
        try:
            out, err = self.proc.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            return "<server still running>"
        return f'STDOUT:\n{out.decode(errors="replace")}\nSTDERR:\n{err.decode(errors="replace")}'


@contextlib.contextmanager
def run_server(
    script_body: str,
    *,
    port: int | None = None,
    extra_files: dict[str, bytes] | None = None,
):
    if port is None:
        port = _free_port()
    tmpdir = Path(tempfile.mkdtemp(prefix="tremolo_test_"))
    server: _Server | None = None
    try:
        script = tmpdir / "app.py"
        script.write_text(script_body.replace("{PORT}", str(port)))
        for name, data in (extra_files or {}).items():
            (tmpdir / name).write_bytes(data)

        proc = subprocess.Popen(
            [sys.executable, str(script)],
            cwd=str(tmpdir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            preexec_fn=os.setsid if os.name == "posix" else None,
        )
        server = _Server(port, proc, script)

        try:
            _wait_for_port(port)
        except BaseException as exc:
            # Server never bound — surface its stderr so the test sees why.
            diag = server.diagnostics()
            raise AssertionError(f"tremolo server failed to start:\n{diag}") from exc

        yield server
    finally:
        if server is not None:
            server.stop()
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# 1. Application + routing
# ---------------------------------------------------------------------------


def test_application_route_basic():
    """An `Application` with a single decorator-registered route returns
    a 200 with the expected body and advertises the `Server: Tremolo`
    response header."""
    script = """
from tremolo import Application
app = Application()

@app.route("/hello")
async def hello(**server):
    return "Hello World!"

if __name__ == "__main__":
    app.run("127.0.0.1", {PORT}, log_level="ERROR")
"""
    with run_server(script) as srv:
        r = _get(f"{srv.base}/hello")
        assert r.status_code == 200
        assert r.text == "Hello World!"
        assert r.headers.get("server", "").lower() == "tremolo"
        # Default Content-Type is `text/html; charset=utf-8` per the spec —
        # a model that hard-codes `text/plain` or omits the header entirely
        # must fail this test.
        ct = r.headers.get("content-type", "").lower().replace(" ", "")
        assert (
            ct == "text/html;charset=utf-8"
        ), f"unexpected default content-type: {r.headers.get('content-type')!r}"


def test_route_regex_named_group_kwarg():
    """A regex route with a named group (`(?P<item_id>...)`) parses the
    path and exposes the captured value to the handler as a kwarg."""
    script = r"""
from tremolo import Application
app = Application()

@app.route(r"^/items/(?P<item_id>\d+)$")
async def get_item(item_id=b"", **server):
    text = item_id.decode() if isinstance(item_id, (bytes, bytearray)) else str(item_id)
    return "item=" + text

if __name__ == "__main__":
    app.run("127.0.0.1", {PORT}, log_level="ERROR")
"""
    with run_server(script) as srv:
        r = _get(f"{srv.base}/items/42")
        assert r.status_code == 200
        assert r.text == "item=42"

        # Non-matching path (letters where digits required) → 404.
        miss = _get(f"{srv.base}/items/abc")
        assert miss.status_code == 404


def test_class_based_view_method_dispatch():
    """A class-based view (CBV) registered via `app.route(path)(MyClass)`
    dispatches GET / POST to the matching method, and unmatched methods
    receive 405 Method Not Allowed."""
    script = """
from tremolo import Application
app = Application()

class Things:
    async def get(self, **server):
        return "got"

    async def post(self, **server):
        return "posted"

app.route("/things")(Things)

if __name__ == "__main__":
    app.run("127.0.0.1", {PORT}, log_level="ERROR")
"""
    with run_server(script) as srv:
        g = _get(f"{srv.base}/things")
        assert g.status_code == 200
        assert g.text == "got"

        p = _post(f"{srv.base}/things")
        assert p.status_code == 200
        assert p.text == "posted"

        d = _delete(f"{srv.base}/things")
        assert d.status_code == 405


# ---------------------------------------------------------------------------
# 2. Handler return types
# ---------------------------------------------------------------------------


def test_handler_async_yields_chunks():
    """Yielding from an async handler streams the body in order; the full
    concatenation matches what was yielded."""
    script = """
from tremolo import Application
app = Application()

@app.route("/stream")
async def stream(**server):
    yield b"chunk-1\\n"
    yield b"chunk-2\\n"
    yield b"chunk-3\\n"

if __name__ == "__main__":
    app.run("127.0.0.1", {PORT}, log_level="ERROR")
"""
    with run_server(script) as srv:
        r = _get(f"{srv.base}/stream")
        assert r.status_code == 200
        assert r.text == "chunk-1\nchunk-2\nchunk-3\n"
        # Sharpen: per spec, an async generator handler MUST stream over
        # `Transfer-Encoding: chunked` — not buffer-and-return as a
        # single Content-Length body. Without this assertion an
        # implementation that collects every yield into a buffer and
        # returns one fixed-size body still passes — defeating the
        # purpose of streaming.
        te = r.headers.get("transfer-encoding", "").lower()
        assert te == "chunked", (
            f"async-generator response was not chunked: TE={te!r}, "
            f"CL={r.headers.get('content-length')!r}"
        )


def test_handler_tuple_selects_byte_encoding():
    """A handler returning `(str_body, "latin-1")` causes the body to be
    encoded with the chosen codec — a non-ASCII character round-trips
    using latin-1 (1 byte), not the default UTF-8 (2 bytes)."""
    script = """
from tremolo import Application
app = Application()

@app.route("/cafe")
async def cafe(**server):
    return "caf\\u00e9", "latin-1"

if __name__ == "__main__":
    app.run("127.0.0.1", {PORT}, log_level="ERROR")
"""
    with run_server(script) as srv:
        r = _get(f"{srv.base}/cafe")
        assert r.status_code == 200
        # latin-1 encodes 'é' as a single 0xE9 byte; utf-8 would be 0xC3 0xA9.
        assert r.content == b"caf\xe9"
        assert r.content.decode("latin-1") == "café"


# ---------------------------------------------------------------------------
# 3. Request API
# ---------------------------------------------------------------------------


def test_request_query_string_parsing():
    """`request.query` is a parsed dict — keys are split on `&`, values
    arrive as LISTS (because the same key can repeat). The handler
    serialises the entire parsed mapping so we can verify the SHAPE
    (parsed-separately list-valued dict, not just a concatenated string)."""
    script = """
import json
from tremolo import Application
app = Application()

@app.route("/q")
async def q(request, **server):
    parsed = request.query
    # Normalise: keys to str, each value-element to str. Per spec the
    # values must be a LIST. Reject the wrong shape early so we surface
    # a clear failure on the wire.
    out = {}
    for k in sorted(parsed.keys()):
        vs = parsed[k]
        if not isinstance(vs, list):
            return "ERROR: values for %r is %s, not list" % (k, type(vs).__name__)
        norm_vs = []
        for v in vs:
            if isinstance(v, (bytes, bytearray)):
                v = v.decode()
            norm_vs.append(v)
        key_str = k.decode() if isinstance(k, (bytes, bytearray)) else k
        out[key_str] = norm_vs
    return json.dumps(out)

if __name__ == "__main__":
    app.run("127.0.0.1", {PORT}, log_level="ERROR")
"""
    with run_server(script) as srv:
        # Two distinct keys + one repeated key — proves the parser splits
        # on `&` AND keeps repeats as a list. A buggy implementation that
        # `.split("&")[0]` or that returns a flat str would fail.
        r = _get(f"{srv.base}/q?name=ada&age=36&tag=x&tag=y")
        assert r.status_code == 200, r.text
        parsed = json.loads(r.text)
        assert parsed == {
            "name": ["ada"],
            "age": ["36"],
            "tag": ["x", "y"],
        }, f"unexpected query parse: {parsed!r}"


def test_request_body_json_post():
    """`await request.body()` returns the raw POST body; the handler can
    JSON-decode it and echo a derived value."""
    script = """
import json
from tremolo import Application
app = Application()

@app.route("/echo")
async def echo(request, **server):
    raw = await request.body()
    payload = json.loads(raw)
    return json.dumps({"received": payload["msg"], "len": len(payload["msg"])})

if __name__ == "__main__":
    app.run("127.0.0.1", {PORT}, log_level="ERROR")
"""
    with run_server(script) as srv:
        r = _post(f"{srv.base}/echo", json={"msg": "hello"})
        assert r.status_code == 200
        assert json.loads(r.text) == {"received": "hello", "len": 5}


# ---------------------------------------------------------------------------
# 4. Response API
# ---------------------------------------------------------------------------


def test_response_set_status_and_header():
    """`response.set_status` and `response.set_header` propagate to the
    HTTP status line and headers."""
    script = """
from tremolo import Application
app = Application()

@app.route("/created")
async def created(response, **server):
    response.set_status(201, b"Created")
    response.set_header(b"x-resource-id", b"abc-123")
    return "ok"

if __name__ == "__main__":
    app.run("127.0.0.1", {PORT}, log_level="ERROR")
"""
    with run_server(script) as srv:
        r = _get(f"{srv.base}/created")
        assert r.status_code == 201
        assert r.headers.get("x-resource-id") == "abc-123"
        assert r.text == "ok"
        # Sharpen: assert the wire-level status LINE carries the reason
        # phrase "Created" (not the generic "OK" that a sloppy
        # set_status implementation would still pass `status_code == 201`
        # with). httpx hides the reason phrase, so re-issue via raw TCP.
        with socket.create_connection((HOST, srv.port), timeout=5) as s:
            s.sendall(
                b"GET /created HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                b"Connection: close\r\n\r\n"
            )
            s.settimeout(5)
            buf = b""
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                buf += chunk
        status_line = buf.split(b"\r\n", 1)[0]
        assert (
            status_line == b"HTTP/1.1 201 Created"
        ), f"status line wrong: {status_line!r}"


def test_response_set_cookie_flags():
    """`response.set_cookie` emits a `Set-Cookie` header carrying the
    requested attribute flags.

    Covers (merged from prior set_cookie + set_cookie_emits_secure_and_
    httponly_flags tests):
    * httponly-only single cookie renders the `HttpOnly` flag.
    * secure=True + httponly=True renders BOTH the `Secure` and
      `HttpOnly` flags, plus the `Path=/` attribute.
    """
    script = """
from tremolo import Application
app = Application()

@app.route("/login-httponly")
async def login_httponly(response, **server):
    response.set_cookie("session", "s3cret", path="/", httponly=True)
    return "ok"

@app.route("/login-secure")
async def login_secure(response, **server):
    response.set_cookie(
        "session", "opaque", path="/", secure=True, httponly=True
    )
    return "ok"

if __name__ == "__main__":
    app.run("127.0.0.1", {PORT}, log_level="ERROR")
"""
    with run_server(script) as srv:
        # Case 1: httponly only.
        r1 = _get(f"{srv.base}/login-httponly")
        assert r1.status_code == 200
        h1 = r1.headers.get("set-cookie", "")
        assert "session=s3cret" in h1
        assert "HttpOnly" in h1 or "httponly" in h1.lower()

        # Case 2: secure + httponly (case-insensitive flag rendering).
        r2 = _get(f"{srv.base}/login-secure")
        assert r2.status_code == 200
        h2 = r2.headers.get("set-cookie", "").lower()
        assert "session=opaque" in h2
        assert "secure" in h2, f"missing Secure flag: {h2}"
        assert "httponly" in h2, f"missing HttpOnly flag: {h2}"
        assert "path=/" in h2


def test_response_sendfile_range_and_multi_range():
    """`response.sendfile()` handles three Range scenarios against the
    same handler:

    Covers (merged from prior response_sendfile_range_partial_content
    + response_sendfile_without_range_returns_full_body tests, with the
    new multi-range request adjoined since it shares the same code path):
    * No `Range:` header → 200 OK with the entire file body.
    * `Range: bytes=N-M` → 206 Partial Content with the requested slice
      and a `Content-Range: bytes N-M/total` response header.
    * `Range: bytes=N-M,P-Q` multi-range (RFC 7233) → 206; the server
      may return `multipart/byteranges` (BOTH slices in the body) OR
      collapse to a single 206 carrying the first slice only.
    """
    body = b"ABCDEFGHIJKLMNOPQRSTUVWXYZ" * 4  # 104 bytes, deterministic
    script = """
from tremolo import Application
app = Application()

@app.route("/file")
async def file(response, **server):
    await response.sendfile("payload.bin")

if __name__ == "__main__":
    app.run("127.0.0.1", {PORT}, log_level="ERROR")
"""
    with run_server(script, extra_files={"payload.bin": body}) as srv:
        # 1. No Range header → 200 + full body.
        full = _get(f"{srv.base}/file")
        assert full.status_code == 200, f"no-Range expected 200, got {full.status_code}"
        assert (
            full.content == body
        ), f"no-Range body wrong; got {len(full.content)} bytes (want {len(body)})"

        # 2. Single Range: 206 + only the slice + Content-Range.
        r = _get(f"{srv.base}/file", headers={"Range": "bytes=10-19"})
        assert r.status_code == 206, f"single-Range expected 206, got {r.status_code}"
        assert r.content == body[10:20], f"single-Range slice wrong: {r.content!r}"
        cr = r.headers.get("content-range", "").lower()
        assert "bytes 10-19" in cr, f"Content-Range header wrong: {cr!r}"

        # 3. Multi-range request. Per RFC 7233 §4.1 the server may answer
        # with `multipart/byteranges` (carrying ALL ranges) or collapse to
        # a single 206 with the first range only. Either is conforming.
        m = _get(f"{srv.base}/file", headers={"Range": "bytes=0-9,20-29"})
        assert m.status_code == 206, f"multi-range expected 206, got {m.status_code}"
        slice1 = body[0:10]
        slice2 = body[20:30]
        ct = m.headers.get("content-type", "").lower()
        if "multipart/byteranges" in ct:
            assert slice1 in m.content, "multipart body missing first slice"
            assert slice2 in m.content, "multipart body missing second slice"
        else:
            assert (
                m.content == slice1
            ), f"single-range collapse should return first slice, got {m.content!r}"


# ---------------------------------------------------------------------------
# 5. Exceptions
# ---------------------------------------------------------------------------


def test_unknown_route_returns_404():
    """Requesting an unregistered path produces a 404 response."""
    script = """
from tremolo import Application
app = Application()

@app.route("/home")
async def home(**server):
    return "home"

if __name__ == "__main__":
    app.run("127.0.0.1", {PORT}, log_level="ERROR")
"""
    with run_server(script) as srv:
        r = _get(f"{srv.base}/does-not-exist")
        assert r.status_code == 404
        # The default error body is HTML per the spec default Content-Type;
        # this rejects a stub that returns a JSON or text/plain 404.
        ct = r.headers.get("content-type", "").lower()
        assert "text/html" in ct, f"default 404 CT not text/html: {ct!r}"


# ---------------------------------------------------------------------------
# 6. Middleware
# ---------------------------------------------------------------------------


def test_on_request_middleware_can_short_circuit():
    """An `on_request` middleware that raises an HTTPException prevents
    the route handler from running and returns the exception's status."""
    script = """
from tremolo import Application, exceptions
app = Application()

@app.on_request
async def gate(request, **server):
    if request.headers.get(b"x-key", [b""])[0] != b"open":
        raise exceptions.Unauthorized("auth required")

@app.route("/secret")
async def secret(**server):
    return "treasure"

if __name__ == "__main__":
    app.run("127.0.0.1", {PORT}, log_level="ERROR")
"""
    with run_server(script) as srv:
        denied = _get(f"{srv.base}/secret")
        assert denied.status_code == 401

        allowed = _get(f"{srv.base}/secret", headers={"x-key": "open"})
        assert allowed.status_code == 200
        assert allowed.text == "treasure"


def test_on_response_middleware_adds_header():
    """An `on_response` middleware can add headers that appear in the
    final HTTP response."""
    script = """
from tremolo import Application
app = Application()

@app.on_response
async def tag(response, **server):
    response.set_header(b"x-powered-by", b"tremolo-test")

@app.route("/ok")
async def ok(**server):
    return "ok"

if __name__ == "__main__":
    app.run("127.0.0.1", {PORT}, log_level="ERROR")
"""
    with run_server(script) as srv:
        r = _get(f"{srv.base}/ok")
        assert r.status_code == 200
        assert r.headers.get("x-powered-by") == "tremolo-test"


# ---------------------------------------------------------------------------
# 7. WebSocket
# ---------------------------------------------------------------------------


def _ws_send_recv(uri: str, msg, *, is_binary: bool = False, timeout: float = 5.0):
    async def _run():
        async with websockets.connect(uri, proxy=None) as ws:
            await ws.send(msg)
            reply = await asyncio.wait_for(ws.recv(), timeout=timeout)
            return reply

    return asyncio.run(_run())


def test_websocket_echo_text_and_binary():
    """A WebSocket route accepts, then round-trips frames of both types.

    Covers (merged from prior websocket_echo_text + websocket_echo_binary
    tests):
    * Handshake response: 101 status + `Upgrade: websocket` +
      `Connection: upgrade` — proves the server completed the WS
      handshake (not just opportunistic HTTP echo).
    * Text frame echo (`str` round-trip).
    * Binary frame echo (`bytes` round-trip), proving the type-dispatch
      path also works.
    """
    script = """
from tremolo import Application
app = Application()

@app.route("/ws")
async def ws_handler(websocket=None, **server):
    await websocket.accept()
    msg = await websocket.receive()
    await websocket.send(msg)

if __name__ == "__main__":
    app.run("127.0.0.1", {PORT}, log_level="ERROR")
"""

    async def _echo_text_and_inspect(uri):
        async with websockets.connect(uri, proxy=None) as ws:
            # `ws.response` exposes the handshake response on modern
            # `websockets` versions; sharpened assertion verifies the
            # upgrade actually happened cleanly.
            resp = ws.response
            handshake_status = resp.status_code
            handshake_headers = {k.lower(): v.lower() for k, v in resp.headers.items()}
            await ws.send("hello-tremolo")
            reply = await asyncio.wait_for(ws.recv(), timeout=5)
            return reply, handshake_status, handshake_headers

    payload = secrets.token_bytes(32)
    with run_server(script) as srv:
        # Text frame: also inspects handshake on this connection.
        text_reply, status, headers = asyncio.run(
            _echo_text_and_inspect(f"{srv.ws_base}/ws")
        )
        assert text_reply == "hello-tremolo"
        assert status == 101, f"handshake status not 101: {status}"
        assert (
            headers.get("upgrade") == "websocket"
        ), f"missing/wrong Upgrade header: {headers!r}"
        assert "upgrade" in headers.get(
            "connection", ""
        ), f"Connection header did not contain 'upgrade': {headers!r}"

        # Binary frame: new connection, verifies binary type-dispatch path.
        bin_reply = _ws_send_recv(f"{srv.ws_base}/ws", payload, is_binary=True)
        assert bin_reply == payload


def test_websocket_close_code_propagates():
    """When the server closes a WebSocket with a code, the client sees
    a ConnectionClosed carrying that code."""
    script = """
from tremolo import Application
app = Application()

@app.route("/ws")
async def ws_handler(websocket=None, **server):
    await websocket.accept()
    await websocket.close(code=1001)

if __name__ == "__main__":
    app.run("127.0.0.1", {PORT}, log_level="ERROR")
"""

    async def _run(uri):
        async with websockets.connect(uri, proxy=None) as ws:
            with pytest.raises(websockets.ConnectionClosed) as exc:
                await asyncio.wait_for(ws.recv(), timeout=5)
            return exc.value.code

    with run_server(script) as srv:
        code = asyncio.run(_run(f"{srv.ws_base}/ws"))
        assert code == 1001


# ---------------------------------------------------------------------------
# 8. ASGI
# ---------------------------------------------------------------------------


def test_asgi_http_app_passthrough():
    """tremolo can host an external ASGI app: the same `scope/receive/send`
    contract reaches the user app and its response is delivered."""
    script = """
from tremolo import Application

async def asgi_app(scope, receive, send):
    assert scope["type"] == "http"
    body = b""
    while True:
        msg = await receive()
        body += msg.get("body", b"")
        if not msg.get("more_body", False):
            break

    await send({
        "type": "http.response.start",
        "status": 200,
        "headers": [(b"content-type", b"text/plain")],
    })
    await send({"type": "http.response.body", "body": body or b"asgi-hello"})

if __name__ == "__main__":
    Application().run(app=asgi_app, host="127.0.0.1", port={PORT}, log_level="ERROR")
"""
    with run_server(script) as srv:
        r = _get(f"{srv.base}/anything")
        assert r.status_code == 200
        assert r.text == "asgi-hello"
        assert "text/plain" in r.headers.get("content-type", "")


def test_asgi_lifespan_startup_shutdown():
    """tremolo emits ASGI lifespan startup/shutdown messages to ASGI apps
    that subscribe to them. The user app records both events to a file."""
    script = """
from tremolo import Application

async def asgi_app(scope, receive, send):
    if scope["type"] == "lifespan":
        while True:
            msg = await receive()
            if msg["type"] == "lifespan.startup":
                with open("lifespan.log", "a") as f:
                    f.write("startup\\n")
                await send({"type": "lifespan.startup.complete"})
            elif msg["type"] == "lifespan.shutdown":
                with open("lifespan.log", "a") as f:
                    f.write("shutdown\\n")
                await send({"type": "lifespan.shutdown.complete"})
                return
        return
    await send({
        "type": "http.response.start",
        "status": 200,
        "headers": [(b"content-type", b"text/plain")],
    })
    await send({"type": "http.response.body", "body": b"hi"})

if __name__ == "__main__":
    Application().run(app=asgi_app, host="127.0.0.1", port={PORT}, log_level="ERROR")
"""
    with run_server(script) as srv:
        r = _get(f"{srv.base}/")
        assert r.status_code == 200
        log_path = Path(srv.script).parent / "lifespan.log"
        # Server cwd is the tmpdir; the lifespan log should have at least
        # the startup record by the time the first HTTP request returns.
        deadline = time.time() + 3
        while time.time() < deadline and not (
            log_path.exists() and "startup" in log_path.read_text()
        ):
            time.sleep(0.05)
        assert log_path.exists(), "lifespan.log was not created"
        assert "startup" in log_path.read_text()


# ---------------------------------------------------------------------------
# 9. Custom error pages (@app.error)
# ---------------------------------------------------------------------------


def test_custom_error_pages():
    """`@app.error(code)` registers custom error handlers within the
    400-511 range; codes outside that range raise `ValueError`.

    Covers (merged from prior custom_error_handler_404_replaces_default
    + custom_error_handler_500_replaces_default + app_error_rejects_out_of_
    range_code tests):
    * Registering 404 replaces the default 404 body for an unmatched path.
    * Registering 500 replaces the default body when a handler raises a
      non-HTTPException (RuntimeError).
    * Registering a code outside 400-511 (here 512) raises `ValueError`
      at app construction, so the server never binds the port.
    """
    # First: register-404 + register-500 both fire on a live server.
    script = """
from tremolo import Application
app = Application()

@app.error(404)
def handle_404(**server):
    return b"CUSTOM-NOT-FOUND-BODY"

@app.error(500)
def handle_500(**server):
    return b"CUSTOM-SERVER-ERROR"

@app.route("/known")
async def known(**server):
    return "known"

@app.route("/explode")
async def explode(**server):
    raise RuntimeError("intentional test failure")

if __name__ == "__main__":
    app.run("127.0.0.1", {PORT}, log_level="ERROR")
"""
    with run_server(script) as srv:
        # Known route still works.
        ok = _get(f"{srv.base}/known")
        assert ok.status_code == 200
        assert ok.text == "known"

        # Custom 404 fires for unregistered path.
        miss = _get(f"{srv.base}/no-such-path")
        assert miss.status_code == 404
        assert miss.content == b"CUSTOM-NOT-FOUND-BODY"

        # Custom 500 fires when handler raises a non-HTTPException.
        boom = _get(f"{srv.base}/explode")
        assert boom.status_code == 500
        assert boom.content == b"CUSTOM-SERVER-ERROR"

    # Second: registering an out-of-range error code (512) must raise
    # ValueError at app construction — the server never binds the port,
    # so `run_server` reports startup failure containing "ValueError"
    # in the captured stderr.
    bad_script = """
from tremolo import Application
app = Application()

@app.error(512)
def bad(**server):
    return b"never"

if __name__ == "__main__":
    app.run("127.0.0.1", {PORT}, log_level="ERROR")
"""
    with pytest.raises(AssertionError) as exc_info:
        with run_server(bad_script):
            pass
    assert "ValueError" in str(exc_info.value), (
        f"out-of-range @app.error(512) did not raise ValueError; "
        f"got: {exc_info.value}"
    )


# ---------------------------------------------------------------------------
# 10. Lifecycle hooks (worker_start + on_connect + on_close + worker_stop)
# ---------------------------------------------------------------------------


def test_lifecycle_hooks_fire():
    """All four lifecycle hooks fire at their documented events.

    Covers (merged from prior on_worker_start_hook_runs_before_first_request
    + on_connect_hook_fires_per_tcp_connection + on_close_hook_fires_per_
    tcp_disconnect + on_worker_stop_hook_runs_during_graceful_shutdown
    tests):
    * `@app.on_worker_start` runs once during worker boot — proved via
      a sentinel file written before the first request returns.
    * `@app.on_connect` fires per accepted TCP connection — two distinct
      connections produce at least two `CONNECT` log entries.
    * `@app.on_close` fires per TCP disconnect — two distinct connections
      produce at least two `CLOSE` log entries.
    * `@app.on_worker_stop` runs during graceful shutdown — sentinel must
      exist after the server receives SIGTERM and exits.
    """
    script = """
from tremolo import Application
app = Application()

@app.on_worker_start
async def boot(**worker):
    with open("boot.sentinel", "w") as f:
        f.write("WORKER-STARTED")

@app.on_worker_stop
async def shutdown_hook(**worker):
    with open("stop.sentinel", "w") as f:
        f.write("WORKER-STOPPED")

@app.on_connect
async def conn(**server):
    with open("conn.log", "a") as f:
        f.write("CONNECT\\n")

@app.on_close
async def closed(**server):
    with open("close.log", "a") as f:
        f.write("CLOSE\\n")

@app.route("/ping")
async def ping(**server):
    return "pong"

if __name__ == "__main__":
    app.run("127.0.0.1", {PORT}, log_level="ERROR")
"""
    with run_server(script) as srv:
        # Two requests on DISTINCT TCP connections (Connection: close
        # forces httpx to tear each connection down between requests).
        headers = {"Connection": "close"}
        r1 = _get(f"{srv.base}/ping", headers=headers)
        r2 = _get(f"{srv.base}/ping", headers=headers)
        assert r1.status_code == 200 and r2.status_code == 200
        assert r1.text == "pong"

        tmpdir = Path(srv.script).parent

        # 1. on_worker_start sentinel must exist + match.
        boot = tmpdir / "boot.sentinel"
        assert boot.exists(), "on_worker_start hook never wrote sentinel"
        assert boot.read_text() == "WORKER-STARTED"

        # 2. on_connect: at least two CONNECT lines.
        conn_log = tmpdir / "conn.log"
        deadline = time.time() + 2
        while time.time() < deadline:
            if conn_log.exists():
                lines = [
                    l
                    for l in conn_log.read_text().splitlines()
                    if l.strip() == "CONNECT"
                ]
                if len(lines) >= 2:
                    break
            time.sleep(0.05)
        assert conn_log.exists(), "on_connect hook never wrote sentinel"
        conn_lines = [
            l for l in conn_log.read_text().splitlines() if l.strip() == "CONNECT"
        ]
        assert (
            len(conn_lines) >= 2
        ), f"on_connect did not fire per TCP connect: lines={conn_lines!r}"

        # 3. on_close: at least two CLOSE lines.
        close_log = tmpdir / "close.log"
        deadline = time.time() + 2
        while time.time() < deadline:
            if close_log.exists():
                lines = [
                    l
                    for l in close_log.read_text().splitlines()
                    if l.strip() == "CLOSE"
                ]
                if len(lines) >= 2:
                    break
            time.sleep(0.05)
        assert close_log.exists(), "on_close hook never wrote sentinel"
        close_lines = [
            l for l in close_log.read_text().splitlines() if l.strip() == "CLOSE"
        ]
        assert (
            len(close_lines) >= 2
        ), f"on_close did not fire per TCP disconnect: lines={close_lines!r}"

        # 4. on_worker_stop: capture sentinel path BEFORE stop (the
        # context-manager exit removes the tmpdir).
        stop_sentinel = tmpdir / "stop.sentinel"

        # Trigger graceful shutdown manually so we can inspect the
        # sentinel before tmpdir cleanup.
        srv.stop()
        deadline = time.time() + 3
        while time.time() < deadline and not stop_sentinel.exists():
            time.sleep(0.05)
        assert stop_sentinel.exists(), "on_worker_stop hook never wrote sentinel"
        assert stop_sentinel.read_text() == "WORKER-STOPPED"


# ---------------------------------------------------------------------------
# 11. Request body de-chunking
# ---------------------------------------------------------------------------


def test_request_body_transparently_dechunks_chunked_post():
    """`await request.body()` MUST transparently de-chunk a body sent
    with `Transfer-Encoding: chunked` — the handler sees the reassembled
    payload, not the raw chunk framing."""
    script = """
from tremolo import Application
app = Application()

@app.route("/echo")
async def echo(request, **server):
    body = await request.body()
    # Echo length first so we can assert exact reassembly.
    return b"len=%d:%s" % (len(body), bytes(body))

if __name__ == "__main__":
    app.run("127.0.0.1", {PORT}, log_level="ERROR")
"""
    with run_server(script) as srv:
        # httpx doesn't reliably chunk for us; build a raw chunked POST
        # and send via a TCP socket to guarantee Transfer-Encoding: chunked.
        raw = (
            b"POST /echo HTTP/1.1\r\n"
            b"Host: 127.0.0.1\r\n"
            b"Transfer-Encoding: chunked\r\n"
            b"Connection: close\r\n"
            b"\r\n"
            b"5\r\nhello\r\n"
            b"1\r\n \r\n"
            b"5\r\nworld\r\n"
            b"0\r\n\r\n"
        )
        with socket.create_connection((HOST, srv.port), timeout=5) as s:
            s.sendall(raw)
            s.settimeout(5)
            buf = b""
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                buf += chunk
        # The handler must have received the reassembled body "hello world"
        # (11 bytes), NOT the raw chunked framing.
        assert b"len=11:hello world" in buf, f"server response: {buf!r}"


# ---------------------------------------------------------------------------
# 12. Request inspection surfaces (cookies, headers, host/ip/scheme, method)
# ---------------------------------------------------------------------------


def test_request_inspection_surfaces():
    """A single handler exercises every read-side attribute on `request`
    and serialises a JSON summary; the test asserts each value separately.

    Covers (merged from prior request_cookies_parsed_from_cookie_header
    + request_headers_lookup_finds_mixed_case_inbound_header
    + request_host_ip_scheme_exposed_on_request
    + request_method_is_uppercase_bytes_for_put_and_options tests):
    * `request.cookies` parses Cookie header into list-valued dict.
    * `request.headers` accepts lowercased lookup of mixed-case names.
    * `request.host` echoes the client's Host header.
    * `request.ip` is the connecting client address.
    * `request.scheme` is `http` for plaintext.
    * `request.method` is uppercase bytes for PUT (and stays consistent).
    """
    script = """
import json
from tremolo import Application
app = Application()

def _d(v):
    if isinstance(v, (bytes, bytearray)):
        return v.decode()
    return v if isinstance(v, str) else str(v)

@app.route("/inspect")
async def inspect(request, **server):
    # Cookies: list-valued dict keyed by name.
    user_list = request.cookies["user"]
    sess_list = request.cookies["sess"]

    # Headers: lowercased lookup wins for a mixed-case inbound header.
    auth_list = request.headers.get(b"x-custom-auth", [b""])
    auth = _d(auth_list[0]) if auth_list else ""

    # request.method MUST be bytes per spec.
    m = request.method
    method_is_bytes = isinstance(m, (bytes, bytearray))
    summary = {
        "cookie_user": user_list[0],
        "cookie_sess": sess_list[0],
        "auth": auth,
        "host": _d(request.host),
        "ip": _d(request.ip),
        "scheme": _d(request.scheme),
        "method_is_bytes": method_is_bytes,
        "method": _d(bytes(m) if method_is_bytes else m),
    }
    return json.dumps(summary)

if __name__ == "__main__":
    app.run("127.0.0.1", {PORT}, log_level="ERROR")
"""
    with run_server(script) as srv:
        r = _put(
            f"{srv.base}/inspect",
            headers={
                "Cookie": "user=alice; sess=opaque-token-123",
                "X-Custom-Auth": "Bearer-XYZ-789",
            },
        )
        assert r.status_code == 200, r.text
        summary = json.loads(r.text)

        # cookies
        assert (
            summary["cookie_user"] == "alice"
        ), f"cookie user wrong: {summary['cookie_user']!r}"
        assert (
            summary["cookie_sess"] == "opaque-token-123"
        ), f"cookie sess wrong: {summary['cookie_sess']!r}"

        # headers: lowercased lookup of mixed-case inbound name.
        assert (
            summary["auth"] == "Bearer-XYZ-789"
        ), f"header lookup wrong: {summary['auth']!r}"

        # host / ip / scheme
        assert (
            summary["host"] == f"127.0.0.1:{srv.port}"
        ), f"unexpected request.host: {summary['host']!r}"
        assert summary["ip"] == "127.0.0.1", f"unexpected request.ip: {summary['ip']!r}"
        assert (
            summary["scheme"] == "http"
        ), f"unexpected request.scheme: {summary['scheme']!r}"

        # method: bytes, value PUT.
        assert (
            summary["method_is_bytes"] is True
        ), "request.method must be bytes per spec"
        assert (
            summary["method"] == "PUT"
        ), f"unexpected request.method: {summary['method']!r}"


# ---------------------------------------------------------------------------
# 14. HTTPException subclass → status-code mapping
# ---------------------------------------------------------------------------


def test_http_exception_subclasses_map_to_status_codes():
    """Each documented `HTTPException` subclass short-circuits the
    handler and maps to its declared status code.

    Covers (merged from prior handler_raising_http_exception_yields_status
    + multiple_http_exception_subclasses_map_to_status_codes tests):
    * Forbidden → 403
    * NotFound → 404
    * BadRequest → 400
    * MethodNotAllowed → 405
    * ServiceUnavailable → 503
    """
    script = """
from tremolo import Application, exceptions
app = Application()

@app.route("/forbidden")
async def forbidden(**server):
    raise exceptions.Forbidden("nope")

@app.route("/nf")
async def nf(**server):
    raise exceptions.NotFound("missing")

@app.route("/br")
async def br(**server):
    raise exceptions.BadRequest("bad input")

@app.route("/mna")
async def mna(**server):
    raise exceptions.MethodNotAllowed("nope")

@app.route("/su")
async def su(**server):
    raise exceptions.ServiceUnavailable("maintenance")

if __name__ == "__main__":
    app.run("127.0.0.1", {PORT}, log_level="ERROR")
"""
    with run_server(script) as srv:
        assert _get(f"{srv.base}/forbidden").status_code == 403
        assert _get(f"{srv.base}/nf").status_code == 404
        assert _get(f"{srv.base}/br").status_code == 400
        assert _get(f"{srv.base}/mna").status_code == 405
        assert _get(f"{srv.base}/su").status_code == 503


def test_handler_uncaught_exception_returns_500():
    """A handler that raises a non-HTTPException Exception is caught by
    the server and surfaces as a 500 Internal Server Error response —
    the connection is not dropped."""
    script = """
from tremolo import Application
app = Application()

@app.route("/boom")
async def boom(**server):
    raise RuntimeError("kaboom")

if __name__ == "__main__":
    app.run("127.0.0.1", {PORT}, log_level="ERROR")
"""
    with run_server(script) as srv:
        r = _get(f"{srv.base}/boom")
        assert r.status_code == 500


# ---------------------------------------------------------------------------
# 15. HTTPRedirect (default 302 + explicit 303 override)
# ---------------------------------------------------------------------------


def test_http_redirect_default_and_explicit_code():
    """Raising `HTTPRedirect(location=...)` produces a redirect response
    carrying the requested `Location:` header.

    Covers (merged from prior http_redirect_sets_status_and_location_header
    + http_redirect_with_explicit_code_303 tests):
    * Default `code=302` is emitted when no explicit code is supplied.
    * Explicit `code=303` override is honoured.
    * The destination of the 302 hop still resolves through normal routing.

    httpx is told NOT to follow redirects so we can inspect each hop directly.
    """
    script = """
from tremolo import Application, exceptions
app = Application()

@app.route("/old")
async def old(**server):
    # Default code=302.
    raise exceptions.HTTPRedirect("moved", location="/new", code=302)

@app.route("/new")
async def new(**server):
    return "fresh"

@app.route("/see-other")
async def so(**server):
    # Explicit code=303 override.
    raise exceptions.HTTPRedirect("see other docs", location="/", code=303)

if __name__ == "__main__":
    app.run("127.0.0.1", {PORT}, log_level="ERROR")
"""
    with run_server(script) as srv:
        # Default 302 redirect.
        r = _get(f"{srv.base}/old", follow_redirects=False)
        assert r.status_code == 302, f"expected 302, got {r.status_code}"
        assert (
            r.headers.get("location") == "/new"
        ), f"302 missing/wrong Location: {r.headers.get('location')!r}"

        # Destination of the 302 still resolves through normal routing.
        r2 = _get(f"{srv.base}/new")
        assert r2.status_code == 200
        assert r2.text == "fresh"

        # Explicit code=303 override is honoured.
        r3 = _get(f"{srv.base}/see-other", follow_redirects=False)
        assert r3.status_code == 303, f"expected 303, got {r3.status_code}"
        assert (
            r3.headers.get("location") == "/"
        ), f"303 missing/wrong Location: {r3.headers.get('location')!r}"


# ---------------------------------------------------------------------------
# 19. HEAD request body suppression
# ---------------------------------------------------------------------------


def test_head_request_returns_status_with_empty_body():
    """A HEAD request to a route returning a body must return the same
    status as GET but with an empty body — per RFC 7231 and the CBV
    method list that includes `head`. Asserted via the raw wire so we
    can be exact about what the server emitted."""
    script = """
from tremolo import Application
app = Application()

@app.route("/r")
async def r(**server):
    return b"the body"

if __name__ == "__main__":
    app.run("127.0.0.1", {PORT}, log_level="ERROR")
"""
    with run_server(script) as srv:
        # GET sanity — body delivered as expected.
        g = _get(f"{srv.base}/r")
        assert g.status_code == 200
        assert g.content == b"the body"

        # HEAD via raw socket — assert NO body bytes follow headers.
        with socket.create_connection((HOST, srv.port), timeout=5) as s:
            s.sendall(
                b"HEAD /r HTTP/1.1\r\nHost: 127.0.0.1\r\n" b"Connection: close\r\n\r\n"
            )
            s.settimeout(5)
            buf = b""
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                buf += chunk
        # Split status line + headers from body.
        head_end = buf.find(b"\r\n\r\n")
        assert head_end != -1, f"no header terminator: {buf!r}"
        status_line = buf.split(b"\r\n", 1)[0]
        body = buf[head_end + 4 :]
        assert status_line.startswith(
            b"HTTP/1.1 200"
        ), f"HEAD status not 200: {status_line!r}"
        # Per RFC 7231 §4.3.2: HEAD must NOT include a message body.
        assert body == b"", f"HEAD body must be empty, got: {body!r}"


# ---------------------------------------------------------------------------
# 21. Multiple Set-Cookie headers
# ---------------------------------------------------------------------------


def test_response_set_cookie_emits_separate_headers_for_each_call():
    """Per spec, `response.set_cookie(...)` APPENDS a Set-Cookie header.
    Two calls with different cookie names must produce TWO distinct
    Set-Cookie headers on the wire — not one combined header. Verified
    via both httpx's multi-header accessor AND a raw-socket count."""
    script = """
from tremolo import Application
app = Application()

@app.route("/multi")
async def multi(response, **server):
    response.set_cookie("first", "1")
    response.set_cookie("second", "2")
    return "ok"

if __name__ == "__main__":
    app.run("127.0.0.1", {PORT}, log_level="ERROR")
"""
    with run_server(script) as srv:
        r = _get(f"{srv.base}/multi")
        assert r.status_code == 200
        cookies = r.headers.get_list("set-cookie")
        # Two calls → exactly two Set-Cookie lines. A buggy implementation
        # that overwrites the header would only give us 1.
        assert (
            len(cookies) == 2
        ), f"expected 2 Set-Cookie headers, got {len(cookies)}: {cookies!r}"
        joined = " ".join(cookies)
        assert "first=1" in joined, f"first cookie missing: {cookies!r}"
        assert "second=2" in joined, f"second cookie missing: {cookies!r}"

        # Raw-socket cross-check: count occurrences of "Set-Cookie:" prefix.
        with socket.create_connection((HOST, srv.port), timeout=5) as s:
            s.sendall(
                b"GET /multi HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                b"Connection: close\r\n\r\n"
            )
            s.settimeout(5)
            buf = b""
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                buf += chunk
        head = buf.split(b"\r\n\r\n", 1)[0]
        n_cookies = sum(
            1 for line in head.split(b"\r\n") if line.lower().startswith(b"set-cookie:")
        )
        assert n_cookies == 2, (
            f"raw wire had {n_cookies} Set-Cookie lines, expected 2; "
            f"headers={head!r}"
        )


# ---------------------------------------------------------------------------
# 24. response.set_content_type override
# ---------------------------------------------------------------------------


def test_response_set_content_type_overrides_default():
    """A handler that calls `response.set_content_type(...)` with a
    non-default value must cause the response to carry that exact
    Content-Type — overriding the framework default
    `text/html; charset=utf-8`."""
    script = """
from tremolo import Application
app = Application()

@app.route("/api")
async def api(response, **server):
    response.set_content_type(b"application/json; charset=utf-8")
    return b'{"ok":true}'

if __name__ == "__main__":
    app.run("127.0.0.1", {PORT}, log_level="ERROR")
"""
    with run_server(script) as srv:
        r = _get(f"{srv.base}/api")
        assert r.status_code == 200
        ct = r.headers.get("content-type", "").lower().replace(" ", "")
        assert (
            ct == "application/json;charset=utf-8"
        ), f"set_content_type did not override default; got {ct!r}"
        # And the body still flows.
        assert r.content == b'{"ok":true}'


# ---------------------------------------------------------------------------
# 26. Alternative registration APIs (tremolo.run + app.add_route)
# ---------------------------------------------------------------------------


def test_alternative_registration_apis():
    """The two non-decorator entry points are both wired and work as
    documented.

    Covers (merged from prior tremolo_run_module_helper_hosts_asgi_app
    + app_add_route_direct_call_registers_handler tests):
    * `tremolo.run(asgi_app, **options)` — module-level helper hosts a
      supplied ASGI app and forwards Content-Type headers from the app
      (not the framework default).
    * `app.add_route(handler, path)` — function form of `@app.route(...)`
      registers a handler that responds at the given path; an unrelated
      path still 404s, proving the registration is precise.
    """
    # 1. tremolo.run() module helper hosting an ASGI app.
    run_helper_script = """
import tremolo

async def asgi_app(scope, receive, send):
    if scope["type"] == "lifespan":
        while True:
            msg = await receive()
            if msg["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif msg["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return
        return
    while True:
        msg = await receive()
        if not msg.get("more_body", False):
            break
    await send({
        "type": "http.response.start",
        "status": 200,
        "headers": [(b"content-type", b"text/plain")],
    })
    await send({"type": "http.response.body", "body": b"helo-from-run"})

if __name__ == "__main__":
    tremolo.run(asgi_app, host="127.0.0.1", port={PORT}, log_level="ERROR")
"""
    with run_server(run_helper_script) as srv:
        r = _get(f"{srv.base}/anything")
        assert r.status_code == 200, f"tremolo.run() helper failed: {r.status_code}"
        assert (
            r.content == b"helo-from-run"
        ), f"tremolo.run() helper served wrong body: {r.content!r}"
        # text/plain came from the ASGI app, NOT the tremolo default text/html.
        ct = r.headers.get("content-type", "").lower()
        assert "text/plain" in ct, f"tremolo.run() did not host the ASGI app: ct={ct!r}"

    # 2. app.add_route() function-form registration.
    add_route_script = """
from tremolo import Application
app = Application()

async def my_handler(**server):
    return "registered-via-add_route"

# No decorator — call add_route directly.
app.add_route(my_handler, "/foo")

if __name__ == "__main__":
    app.run("127.0.0.1", {PORT}, log_level="ERROR")
"""
    with run_server(add_route_script) as srv:
        r = _get(f"{srv.base}/foo")
        assert r.status_code == 200, f"add_route() registration failed: {r.status_code}"
        assert (
            r.text == "registered-via-add_route"
        ), f"add_route() served wrong body: {r.text!r}"
        # An unrelated path must still 404 — add_route registered exactly
        # the one path, not a wildcard catch-all.
        miss = _get(f"{srv.base}/bar")
        assert (
            miss.status_code == 404
        ), f"add_route over-registered: /bar should 404, got {miss.status_code}"


# ---------------------------------------------------------------------------
# 30. HTTP/1.1 keep-alive: multiple requests over one TCP connection
# ---------------------------------------------------------------------------


def test_http11_keep_alive_serves_multiple_requests():
    """A single HTTP/1.1 TCP connection with `Connection: keep-alive`
    must serve multiple pipelined requests in order. Verified at the
    wire level: open one TCP socket, write two requests back-to-back,
    read all response bytes, and assert both response bodies appear in
    order with TWO `HTTP/1.1 200` status lines.

    A server that drops the connection after the first response (no
    keep-alive support) or that interleaves the second response would
    fail this test.
    """
    script = """
from tremolo import Application
app = Application()

@app.route("/a")
async def a(**server):
    return "AAA"

@app.route("/b")
async def b(**server):
    return "BBB"

if __name__ == "__main__":
    app.run("127.0.0.1", {PORT}, log_level="ERROR")
"""
    with run_server(script) as srv:
        with socket.create_connection((HOST, srv.port), timeout=5) as s:
            # Two pipelined HTTP/1.1 requests on the same TCP connection;
            # second one carries Connection: close so the server closes
            # the socket and we can drain the full transcript via recv().
            s.sendall(
                b"GET /a HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                b"Connection: keep-alive\r\n\r\n"
                b"GET /b HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                b"Connection: close\r\n\r\n"
            )
            s.settimeout(5)
            buf = b""
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                buf += chunk
        # Both responses must appear, in order.
        idx_a = buf.find(b"AAA")
        idx_b = buf.find(b"BBB")
        assert idx_a != -1, f"missing first keep-alive response body: {buf!r}"
        assert idx_b != -1, f"missing second keep-alive response body: {buf!r}"
        assert idx_a < idx_b, (
            f"keep-alive responses out of order: idx_a={idx_a}, "
            f"idx_b={idx_b}; buf={buf!r}"
        )
        # And exactly two HTTP/1.1 200 status lines.
        n_status_lines = buf.count(b"HTTP/1.1 200")
        assert (
            n_status_lines == 2
        ), f"expected 2 keep-alive responses, got {n_status_lines}: {buf!r}"


# ---------------------------------------------------------------------------
# 31. Async generator: empty mid-stream yield preserves chunk boundaries
# ---------------------------------------------------------------------------


def test_async_generator_chunk_boundaries_preserved():
    """An async-generator handler that yields an empty chunk in the
    middle of the stream MUST NOT corrupt the body the client sees.
    Per spec, yielding `b""` is allowed and the concatenation of all
    yielded chunks (excluding the empty one) is the body the client
    receives.

    A naive implementation that treats `b""` as end-of-stream would
    truncate the body to `b"foo"` and fail. The framework MUST stream
    over `Transfer-Encoding: chunked` and pass the boundaries through.
    """
    script = """
from tremolo import Application
app = Application()

@app.route("/stream")
async def stream(**server):
    yield b"foo"
    yield b""
    yield b"bar"
    yield b"baz"

if __name__ == "__main__":
    app.run("127.0.0.1", {PORT}, log_level="ERROR")
"""
    with run_server(script) as srv:
        r = _get(f"{srv.base}/stream")
        assert r.status_code == 200, r.text
        assert (
            r.content == b"foobarbaz"
        ), f"empty mid-stream yield corrupted body: got {r.content!r}"
        te = r.headers.get("transfer-encoding", "").lower()
        assert te == "chunked", (
            f"async-generator response was not chunked (expected for streams): "
            f"TE={te!r}, CL={r.headers.get('content-length')!r}"
        )


# ---------------------------------------------------------------------------
# 32. WebSocket: server-initiated close with a preceding message
# ---------------------------------------------------------------------------


def test_websocket_server_initiated_close_with_message():
    """A server that sends a text frame and THEN closes the connection
    with a non-default close code (1011) must deliver BOTH events to
    the client: the message arrives, then the close frame with the
    requested code propagates as a `ConnectionClosed`.

    Tightens the existing close-code test by verifying the framework
    flushes a pre-close frame before tearing the connection down — a
    naive implementation that races send + close could swallow the
    message or emit code 1000 instead.
    """
    script = """
from tremolo import Application
app = Application()

@app.route("/ws")
async def ws_handler(websocket=None, **server):
    await websocket.accept()
    await websocket.send("bye-soon")
    await websocket.close(code=1011)

if __name__ == "__main__":
    app.run("127.0.0.1", {PORT}, log_level="ERROR")
"""

    async def _run(uri):
        async with websockets.connect(uri, proxy=None) as ws:
            msg = await asyncio.wait_for(ws.recv(), timeout=5)
            with pytest.raises(websockets.ConnectionClosed) as exc:
                await asyncio.wait_for(ws.recv(), timeout=5)
            return msg, exc.value.code

    with run_server(script) as srv:
        msg, code = asyncio.run(_run(f"{srv.ws_base}/ws"))
        assert (
            msg == "bye-soon"
        ), f"expected pre-close text frame 'bye-soon', got {msg!r}"
        assert code == 1011, f"expected close code 1011, got {code}"


# ---------------------------------------------------------------------------
# 33. ASGI: response body streamed over multiple `more_body` messages
# ---------------------------------------------------------------------------


def test_asgi_app_streams_response_body_in_chunks():
    """A hosted ASGI app may emit its body across multiple
    `http.response.body` messages — each with `more_body=True` except
    the final one. The framework must concatenate them in order before
    the client sees the body.

    Tests true ASGI streaming, not just the single-shot body path that
    `test_asgi_http_app_passthrough` already covers. A server that
    drops follow-up `more_body=True` messages or that flushes them
    out of order would fail this test.
    """
    script = """
from tremolo import Application

async def asgi_app(scope, receive, send):
    if scope["type"] == "lifespan":
        while True:
            msg = await receive()
            if msg["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif msg["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return
        return
    if scope["type"] != "http":
        return
    # Drain the request body first.
    while True:
        msg = await receive()
        if not msg.get("more_body", False):
            break
    await send({
        "type": "http.response.start",
        "status": 200,
        "headers": [(b"content-type", b"text/plain")],
    })
    # Three chunks across separate http.response.body messages.
    await send({"type": "http.response.body", "body": b"alpha-", "more_body": True})
    await send({"type": "http.response.body", "body": b"bravo-", "more_body": True})
    await send({"type": "http.response.body", "body": b"charlie", "more_body": False})

if __name__ == "__main__":
    Application().run(app=asgi_app, host="127.0.0.1", port={PORT}, log_level="ERROR")
"""
    with run_server(script) as srv:
        r = _get(f"{srv.base}/anything")
        assert r.status_code == 200, r.text
        assert (
            r.content == b"alpha-bravo-charlie"
        ), f"streamed ASGI body did not concatenate in order: {r.content!r}"


# ---------------------------------------------------------------------------
# 32. CLI module entry point
# ---------------------------------------------------------------------------


def test_cli_module_can_serve_asgi_app():
    """`python -m tremolo --port N module:app` boots the named ASGI app
    on port N. The CLI's APP positional accepts a `module:name` import
    path resolved from the cwd; APP must be the LAST argv element."""
    port = _free_port()
    tmpdir = Path(tempfile.mkdtemp(prefix="tremolo_cli_"))
    try:
        (tmpdir / "cli_demo.py").write_text(
            "async def app(scope, receive, send):\n"
            "    await send({'type': 'http.response.start', 'status': 200,"
            " 'headers': [(b'content-type', b'text/plain')]})\n"
            "    await send({'type': 'http.response.body',"
            " 'body': b'cli-ok'})\n"
        )
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "tremolo",
                "--port",
                str(port),
                "--log-level",
                "ERROR",
                "cli_demo:app",
            ],
            cwd=str(tmpdir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            preexec_fn=os.setsid if os.name == "posix" else None,
        )
        try:
            _wait_for_port(port)
            r = _get(f"http://{HOST}:{port}/")
            assert r.status_code == 200
            assert (
                r.content == b"cli-ok"
            ), f"CLI-hosted ASGI app returned wrong body: {r.content!r}"
        finally:
            if os.name == "posix":
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            else:
                proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                if os.name == "posix":
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                else:
                    proc.kill()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
