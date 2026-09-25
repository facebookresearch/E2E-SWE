"""
Tests for the RPyC (Remote Python Call) library.

Tests cover user-facing functionality: services, connections, servers,
classic mode, helpers, registry, authenticators, decorators, and async results.
"""

import os
import subprocess
import sys
import threading
import time

import pytest


def _start_server_bg(server):
    """Start an rpyc server in a daemon thread and wait until it is listening.
    Returns the thread handle."""
    t = threading.Thread(target=server.start, daemon=True)
    t.start()
    time.sleep(0.3)
    return t


def _safe_close(obj, timeout=5):
    """Close an object in a daemon thread with a timeout to avoid hanging."""
    t = threading.Thread(target=obj.close, daemon=True)
    t.start()
    t.join(timeout=timeout)


# =============================================================================
# Service tests
# =============================================================================

class TestServiceCore:
    """Tests for rpyc.Service — exposed methods, lifecycle hooks, and classic mode."""

    def test_exposed_methods_and_non_exposed_blocked(self):
        """Verify that exposed_ prefixed methods are accessible to remote clients
        and that non-prefixed methods raise AttributeError when accessed remotely."""
        import rpyc

        class CalcService(rpyc.Service):
            def exposed_add(self, x, y):
                return x + y

            def exposed_greet(self, name):
                return f"Hello, {name}!"

            def internal_secret(self):
                return "hidden"

        conn = rpyc.connect_thread(service=rpyc.VoidService, remote_service=CalcService)
        try:
            assert conn.root.add(3, 4) == 7
            assert conn.root.greet("world") == "Hello, world!"
            with pytest.raises(AttributeError):
                conn.root.internal_secret()
        finally:
            conn.close()

    def test_on_connect_and_on_disconnect_hooks(self):
        """Verify that Service.on_connect() fires on connection establishment and
        on_disconnect() fires after close, allowing lifecycle tracking."""
        import rpyc

        events = []

        class TrackingService(rpyc.Service):
            def on_connect(self, conn):
                events.append("connected")

            def on_disconnect(self, conn):
                events.append("disconnected")

            def exposed_ping(self):
                return "pong"

        conn = rpyc.connect_thread(
            service=rpyc.VoidService,
            remote_service=TrackingService,
        )
        try:
            assert conn.root.ping() == "pong"
            assert events == ["connected"]
        finally:
            conn.close()
        time.sleep(0.3)
        assert "disconnected" in events

    def test_classic_service_execute_eval_namespace(self):
        """Verify that ClassicService supports remote execute/eval and that the
        namespace dict reflects variables defined via execute, including the
        ability to retrieve them via conn.namespace."""
        import rpyc

        conn = rpyc.classic.connect_thread()
        try:
            conn.execute("x = 42")
            assert conn.eval("x * 2") == 84

            conn.execute("class Point:\n    def __init__(self, a, b):\n        self.a = a\n        self.b = b")
            Point = conn.namespace["Point"]
            p = Point(3, 4)
            assert p.a == 3
            assert p.b == 4
        finally:
            conn.close()

    def test_classic_module_namespace_full(self):
        """Verify that ClassicService's ModuleNamespace supports attribute access,
        bracket access with dotted names, and the 'in' operator for checking
        module availability."""
        import rpyc

        conn = rpyc.classic.connect_thread()
        try:
            # Attribute access
            remote_os = conn.modules.os
            assert remote_os.getpid() == os.getpid()

            # 'in' operator
            assert "os" in conn.modules
            assert "sys" in conn.modules

            # Bracket access with dotted name
            remote_os_path = conn.modules["os.path"]
            assert remote_os_path.sep == os.path.sep

            # Slave.getmodule with tuple — confirm it returns a usable json module. Pass a
            # by-value immutable (int) so the remote encoder receives a real object, not a netref.
            remote_json = conn.root.getmodule(("json",))
            assert str(remote_json.dumps(42)) == "42"
        finally:
            conn.close()

    def test_service_with_stateful_counter(self):
        """Verify that a custom service maintains state across multiple calls
        from the same client, exercising the full service lifecycle."""
        import rpyc

        class CounterService(rpyc.Service):
            def __init__(self):
                super().__init__()
                self._counter = 0

            def exposed_increment(self):
                self._counter += 1
                return self._counter

            def exposed_get_count(self):
                return self._counter

        conn = rpyc.connect_thread(
            service=rpyc.VoidService,
            remote_service=CounterService,
        )
        try:
            assert conn.root.increment() == 1
            assert conn.root.increment() == 2
            assert conn.root.increment() == 3
            assert conn.root.get_count() == 3

            # classpartial: bind arguments to a class constructor
            from rpyc.utils.helpers import classpartial

            class MyClass:
                def __init__(self, x, y):
                    self.x = x
                    self.y = y

            BoundClass = classpartial(MyClass, 10, 20)
            obj = BoundClass()
            assert obj.x == 10
            assert obj.y == 20
        finally:
            conn.close()


# =============================================================================
# Connection tests
# =============================================================================

class TestConnection:
    """Tests for Connection — the RPC protocol layer."""

    def test_connection_lifecycle_and_context_manager(self):
        """Verify connection ping, close/closed property, context manager
        protocol for automatic cleanup, and BgServingThread start/stop."""
        import rpyc

        # Context manager
        with rpyc.classic.connect_thread() as conn:
            assert not conn.closed
            conn.ping()
        assert conn.closed

        # BgServingThread: background thread keeps connection alive for serving
        conn2 = rpyc.connect_thread(
            service=rpyc.VoidService,
            remote_service=rpyc.VoidService,
        )
        bg = None
        try:
            bg = rpyc.BgServingThread(conn2)
            conn2.ping()
        finally:
            if bg is not None:
                stop_thread = threading.Thread(target=bg.stop, daemon=True)
                stop_thread.start()
                stop_thread.join(timeout=5)
            close_thread = threading.Thread(target=conn2.close, daemon=True)
            close_thread.start()
            close_thread.join(timeout=5)

    def test_remote_exception_propagation(self):
        """Verify that exceptions raised on the remote side are propagated to
        the caller with proper exception type preservation, both via custom
        service and via classic eval."""
        import rpyc

        class FailService(rpyc.Service):
            def exposed_fail(self):
                raise ValueError("intentional error")

        conn = rpyc.connect_thread(service=rpyc.VoidService, remote_service=FailService)
        try:
            with pytest.raises(ValueError, match="intentional error"):
                conn.root.fail()
        finally:
            conn.close()

        # Also via classic eval
        conn2 = rpyc.classic.connect_thread()
        try:
            with pytest.raises(ZeroDivisionError):
                conn2.eval("1/0")
        finally:
            conn2.close()

    def test_remote_attribute_access_and_mutation(self):
        """Verify transparent remote attribute access on netref proxy objects,
        including getting and setting attributes on remote objects."""
        import rpyc

        conn = rpyc.classic.connect_thread()
        try:
            conn.execute("class Obj: pass")
            conn.execute("obj = Obj()")
            conn.execute("obj.x = 42")
            assert conn.eval("obj.x") == 42
            conn.execute("obj.x = 99")
            assert conn.eval("obj.x") == 99
        finally:
            conn.close()

    def test_protocol_config_allow_all_attrs(self):
        """Verify that protocol_config allow_all_attrs enables access to
        non-exposed methods, and that without it they are blocked."""
        import rpyc

        class ConfigService(rpyc.Service):
            def exposed_get_value(self):
                return 42

            def non_exposed_method(self):
                return "secret"

        # Without allow_all_attrs
        server_restricted = rpyc.ThreadedServer(
            ConfigService, port=0, auto_register=False,
            protocol_config={},
        )
        _start_server_bg(server_restricted)

        try:
            conn = rpyc.connect("localhost", server_restricted.port)
            try:
                assert conn.root.get_value() == 42
                with pytest.raises(AttributeError):
                    conn.root.non_exposed_method()
            finally:
                conn.close()
        finally:
            server_restricted.close()

        # With allow_all_attrs
        config = {"allow_all_attrs": True}
        server = rpyc.ThreadedServer(
            ConfigService, port=0, auto_register=False,
            protocol_config=config,
        )
        _start_server_bg(server)

        try:
            conn = rpyc.connect("localhost", server.port, config={"allow_all_attrs": True})
            try:
                assert conn.root.get_value() == 42
                assert conn.root.non_exposed_method() == "secret"
            finally:
                conn.close()
        finally:
            server.close()


# =============================================================================
# Server tests
# =============================================================================

class TestServers:
    """Tests for rpyc.ThreadedServer and rpyc.OneShotServer."""

    def test_threaded_server_multiple_clients(self):
        """Verify that a ThreadedServer accepts multiple simultaneous client
        connections and serves requests correctly to each."""
        import rpyc

        class HelloService(rpyc.Service):
            def exposed_hello(self, name):
                return f"hello {name}"

        server = rpyc.ThreadedServer(HelloService, port=0, auto_register=False)
        _start_server_bg(server)

        try:
            conns = []
            for i in range(3):
                conn = rpyc.connect("localhost", server.port)
                conns.append(conn)

            for i, conn in enumerate(conns):
                assert conn.root.hello(f"client{i}") == f"hello client{i}"

            for conn in conns:
                conn.close()
        finally:
            server.close()

    def test_oneshot_server_serves_one_client(self):
        """Verify that OneShotServer accepts exactly one connection, serves it,
        and then terminates — so a second connection attempt is refused. This
        one-shot termination is the sole behavior distinguishing it from a plain
        ThreadedServer."""
        import rpyc
        import socket

        class PingService(rpyc.Service):
            def exposed_ping(self):
                return "pong"

        server = rpyc.OneShotServer(PingService, port=0, auto_register=False)
        _start_server_bg(server)
        port = server.port

        conn = rpyc.connect("localhost", port)
        try:
            assert conn.root.ping() == "pong"
        finally:
            conn.close()

        # After the single connection is served and closed, the server has
        # terminated, so a second connect to the same port fails.
        time.sleep(0.5)
        with pytest.raises((ConnectionError, socket.error, EOFError)):
            conn2 = rpyc.connect("localhost", port, config={"sync_request_timeout": 3})
            conn2.root.ping()
            conn2.close()

    def test_server_with_authenticator_rejects(self):
        """Verify that when a server uses an authenticator that raises
        AuthenticationError, the client cannot call remote methods."""
        import rpyc
        from rpyc.utils.authenticators import AuthenticationError

        def rejecting_authenticator(sock):
            raise AuthenticationError("access denied")

        class SimpleService(rpyc.Service):
            def exposed_hello(self):
                return "hi"

        server = rpyc.ThreadedServer(
            SimpleService, port=0, auto_register=False,
            authenticator=rejecting_authenticator,
        )
        _start_server_bg(server)

        try:
            conn = rpyc.connect("localhost", server.port)
            time.sleep(0.3)
            # Server closes connection after auth failure; client gets EOFError
            with pytest.raises(EOFError):
                conn.root.hello()
            conn.close()
        finally:
            server.close()


# =============================================================================
# Helpers tests
# =============================================================================

class TestHelpers:
    """Tests for rpyc.utils.helpers — async_, timed, restricted, BgServingThread, classpartial."""

    def test_async_proxy_and_result(self):
        """Verify that rpyc.async_() wraps a remote callable to return an
        AsyncResult, and that value, ready, error, expired, and callback
        work correctly."""
        import rpyc
        from rpyc.core.async_ import AsyncResult, AsyncResultTimeout

        conn = rpyc.classic.connect_thread()
        try:
            async_eval = rpyc.async_(conn.root.eval)
            res = async_eval("2 + 2")
            assert isinstance(res, AsyncResult)
            assert res.value == 4
            assert res.ready

            # Error case
            res_err = async_eval("1/0")
            res_err.wait()
            assert res_err.error
            with pytest.raises(ZeroDivisionError):
                _ = res_err.value

            # Callback
            callback_values = []
            res2 = async_eval("42")
            res2.add_callback(lambda r: callback_values.append(r.value))
            res2.wait()
            assert res2.value == 42
            assert 42 in callback_values

            # Expired check
            res3 = async_eval("__import__('time').sleep(0.5) or 99")
            res3.set_expiry(0.01)
            time.sleep(0.1)
            assert res3.expired
            with pytest.raises(AsyncResultTimeout):
                _ = res3.value
        finally:
            conn.close()

    def test_timed_proxy(self):
        """Verify rpyc.timed()'s defining contract: a call completing within the timeout returns
        its value, while a call exceeding the timeout raises AsyncResultTimeout when the result
        is accessed."""
        import rpyc
        from rpyc.core.async_ import AsyncResultTimeout

        conn = rpyc.classic.connect_thread()
        try:
            # Fast path: completes well within the timeout, returns the value.
            timed_eval = rpyc.timed(conn.root.eval, 5)
            res = timed_eval("3 + 3")
            assert res.value == 6

            # Timeout path: the remote call sleeps longer than the (short) timeout, so the result
            # expires and accessing .value raises AsyncResultTimeout.
            slow_eval = rpyc.timed(conn.root.eval, 0.1)
            slow_res = slow_eval("__import__('time').sleep(0.5) or 99")
            with pytest.raises(AsyncResultTimeout):
                _ = slow_res.value
        finally:
            conn.close()

    def test_restricted_read_and_write_control(self):
        """Verify that rpyc.restricted() limits attribute access, and that
        separate read/write attribute sets work independently."""
        import rpyc

        class FullObj:
            x = 10
            y = 20
            def read(self):
                return "data"
            def secret(self):
                return "hidden"

        obj = FullObj()

        # Read-only restriction
        restricted_ro = rpyc.restricted(obj, {"read", "x", "y"}, wattrs={"x"})
        assert restricted_ro.read() == "data"
        assert restricted_ro.x == 10
        assert restricted_ro.y == 20
        with pytest.raises(AttributeError):
            restricted_ro.secret()
        restricted_ro.x = 99
        assert obj.x == 99
        with pytest.raises(AttributeError):
            restricted_ro.y = 99



# =============================================================================
# Registry tests
# =============================================================================

class TestRegistry:
    """Tests for rpyc.utils.registry — service discovery via UDP/TCP."""

    def test_registry_register_discover_unregister(self):
        """Verify the register -> discover -> unregister round-trip over both the UDP and TCP
        registry transports. The register/discover/unregister contract lives in the shared
        RegistryServer/RegistryClient base; UDP and TCP differ only in the wire transport, so both
        are exercised in one test to confirm each transport carries the same contract end-to-end."""
        from rpyc.utils.registry import (
            TCPRegistryClient,
            TCPRegistryServer,
            UDPRegistryClient,
            UDPRegistryServer,
        )

        transports = [
            (UDPRegistryServer, UDPRegistryClient, "UDPTEST", 12345),
            (TCPRegistryServer, TCPRegistryClient, "TCPTEST", 54321),
        ]

        for server_cls, client_cls, alias, svc_port in transports:
            server = server_cls(host="127.0.0.1", port=0, allow_listing=True)
            actual_port = server.port

            server_thread = threading.Thread(target=server.start, daemon=True)
            server_thread.start()
            time.sleep(0.2)

            try:
                client = client_cls(ip="127.0.0.1", port=actual_port)
                # Register
                assert client.register((alias,), svc_port) is True

                # Discover
                servers = client.discover(alias)
                assert len(servers) > 0
                found = any(port == svc_port for _, port in servers)
                assert found, f"[{alias}] Expected port {svc_port} in {servers}"

                # Unregister
                client.unregister(svc_port)
                time.sleep(0.2)
                servers_after = client.discover(alias)
                found_after = any(port == svc_port for _, port in servers_after)
                assert not found_after, f"[{alias}] Port {svc_port} should be unregistered, got {servers_after}"
            finally:
                server.close()
                server_thread.join(timeout=3)

    def test_registry_listing_with_filter(self):
        """Verify that the registry server supports listing all registered
        services when allow_listing is True, including host-based filtering."""
        from rpyc.utils.registry import UDPRegistryServer, UDPRegistryClient

        server = UDPRegistryServer(host="127.0.0.1", port=0, allow_listing=True)
        actual_port = server.port

        server_thread = threading.Thread(target=server.start, daemon=True)
        server_thread.start()
        time.sleep(0.2)

        try:
            client = UDPRegistryClient(ip="127.0.0.1", port=actual_port)
            client.register(("SVC_A",), 1111)
            time.sleep(0.1)
            client.register(("SVC_B",), 2222)
            time.sleep(0.1)

            services = client.list()
            assert "SVC_A" in services
            assert "SVC_B" in services

            # Host-based filtering: the client registers from 127.0.0.1, so filtering on that
            # host returns the services, while filtering on an unrelated host returns none.
            filtered_match = client.list(filter_host="127.0.0.1")
            assert "SVC_A" in filtered_match
            assert "SVC_B" in filtered_match

            filtered_miss = client.list(filter_host="10.255.255.1")
            assert "SVC_A" not in filtered_miss
            assert "SVC_B" not in filtered_miss
        finally:
            server.close()
            server_thread.join(timeout=3)


# =============================================================================
# Exposed/Service decorator tests
# =============================================================================

class TestExposedDecorator:
    """Tests for @rpyc.exposed and @rpyc.service decorators."""

    def test_service_and_exposed_decorator_with_nested_class(self):
        """Verify that @rpyc.service and @rpyc.exposed decorators work over a
        real connection, including exposed nested classes with exposed methods."""
        import rpyc

        @rpyc.service
        class DecoratedService(rpyc.Service):
            @rpyc.exposed
            def multiply(self, x, y):
                return x * y

            @rpyc.exposed
            class Inner:
                def __init__(self, val):
                    self.val = val

                @rpyc.exposed
                def get_val(self):
                    return self.val

        conn = rpyc.connect_thread(
            service=rpyc.VoidService,
            remote_service=DecoratedService,
        )
        try:
            assert conn.root.multiply(5, 6) == 30
            inner = conn.root.Inner(77)
            assert inner.get_val() == 77
        finally:
            conn.close()


# =============================================================================
# Classic utility tests
# =============================================================================

class TestClassicUtils:
    """Tests for rpyc.utils.classic — classic mode utility functions."""

    def test_obtain_and_deliver(self):
        """Verify that rpyc.classic.obtain() copies a remote object by value
        to the local process, and rpyc.classic.deliver() sends a local object
        to the remote side as a proxy."""
        import rpyc

        conn = rpyc.classic.connect_thread()
        try:
            # obtain: remote -> local copy
            remote_list = conn.eval("[1, 2, 3, 4, 5]")
            local_list = rpyc.classic.obtain(remote_list)
            assert local_list == [1, 2, 3, 4, 5]
            assert type(local_list) is list

            # deliver: local -> remote proxy
            local_data = {"key": "value", "num": 42}
            remote_proxy = rpyc.classic.deliver(conn, local_data)
            assert remote_proxy["key"] == "value"
            assert remote_proxy["num"] == 42
        finally:
            conn.close()

    def test_mock_classic_connection(self):
        """Verify the contract unique to MockClassicConnection: it provides the classic interface
        purely in-process, with no underlying connection object, and its modules namespace resolves
        to the real local module objects of the current process (no remoting/netref involved)."""
        from rpyc.utils.classic import MockClassicConnection

        mock = MockClassicConnection()

        # There is no socket / connection behind the mock: the slave's connection is None.
        assert mock.root.getconn() is None

        # The mock shares one local namespace: code run via the mock's execute lands in the same
        # namespace dict that eval reads, and that namespace IS the slave's own dict (in-process,
        # no transfer over a connection).
        mock.execute("y = 21")
        assert mock.eval("y * 2") == 42
        assert mock.namespace is mock.root.namespace
        assert mock.namespace["y"] == 21

        # mock.modules resolves to the real, usable local module objects of THIS process — not a
        # remote proxy. os from the mock is the same module running locally, so its pid matches.
        assert mock.modules.os.getpid() == os.getpid()

    def test_redirected_stdio(self):
        """Verify that redirected_stdio context manager redirects remote stdio
        to local stdout, so remote print() calls appear locally."""
        import rpyc
        from io import StringIO

        conn = rpyc.classic.connect_thread()
        try:
            captured = StringIO()
            old_stdout = sys.stdout
            sys.stdout = captured
            try:
                with rpyc.classic.redirected_stdio(conn):
                    conn.execute("import sys; sys.stdout.write('hello from remote')")
            finally:
                sys.stdout = old_stdout

            output = captured.getvalue()
            assert "hello from remote" in output, f"Expected 'hello from remote' in: {output!r}"
        finally:
            conn.close()

    def test_teleport_function_over_connection(self):
        """Verify that teleport_function sends a function to the remote side
        and it executes correctly there using bytecode serialization."""
        import rpyc

        conn = rpyc.classic.connect_thread()
        try:
            def remote_add(a, b):
                return a + b

            remote_fn = rpyc.classic.teleport_function(conn, remote_add)
            assert remote_fn(10, 20) == 30
        finally:
            conn.close()


# =============================================================================
# Netref (remote object transparency) tests
# =============================================================================

class TestNetref:
    """Tests for transparent network references — remote object proxies."""

    def test_remote_list_and_dict_operations(self):
        """Verify that operations on remote list and dict objects work
        transparently through netref proxies, including mutation, and that
        repr() and str() delegate correctly to the remote side."""
        import rpyc

        conn = rpyc.classic.connect_thread()
        try:
            # List operations
            remote_list = conn.eval("[1, 2, 3]")
            remote_list.append(4)
            assert len(remote_list) == 4
            assert remote_list[3] == 4
            assert list(remote_list) == [1, 2, 3, 4]

            # repr/str delegation
            remote_list2 = conn.eval("[1, 2, 3]")
            assert str(remote_list2) == "[1, 2, 3]"
            assert repr(remote_list2) == "[1, 2, 3]"

            # Dict operations
            remote_dict = conn.eval("{}")
            remote_dict["key"] = "value"
            assert remote_dict["key"] == "value"
            assert len(remote_dict) == 1
            remote_dict["num"] = 42
            assert remote_dict["num"] == 42

            # Context manager protocol on remote objects
            import tempfile
            tmpfile = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False)
            tmpfile.write("test data")
            tmpfile.close()
            try:
                remote_open = conn.modules.builtins.open
                with remote_open(tmpfile.name, "r") as f:
                    content = f.read()
                assert str(content) == "test data"
            finally:
                os.unlink(tmpfile.name)
        finally:
            conn.close()

    def test_remote_string_and_iteration(self):
        """Verify that string methods and iteration over remote iterables
        work correctly through netref proxies."""
        import rpyc

        conn = rpyc.classic.connect_thread()
        try:
            # String methods
            remote_str = conn.eval("'hello world'")
            assert str(remote_str.upper()) == "HELLO WORLD"
            assert str(remote_str.replace('world', 'rpyc')) == "hello rpyc"

            # Iteration
            result = list(conn.eval("range(5)"))
            assert result == [0, 1, 2, 3, 4]
        finally:
            conn.close()

    def test_passing_complex_arguments(self):
        """Verify that complex argument types can be passed to remote methods
        and processed correctly, including return value verification."""
        import rpyc

        class DataService(rpyc.Service):
            def exposed_process(self, data):
                return sum(data)

            def exposed_concat(self, items):
                return "-".join(str(x) for x in items)

        conn = rpyc.connect_thread(
            service=rpyc.VoidService,
            remote_service=DataService,
        )
        try:
            assert conn.root.process([1, 2, 3, 4, 5]) == 15
            assert conn.root.concat([1, 2, 3]) == "1-2-3"
        finally:
            conn.close()


# =============================================================================
# Authenticator tests
# =============================================================================

class TestAuthenticator:
    """Tests for rpyc.utils.authenticators."""

    def test_ssl_authenticator_cert_required_default_mutual_tls(self):
        """Verify the CERT_REQUIRED default end-to-end: an SSLAuthenticator built
        with ca_certs (and no explicit cert_reqs) demands mutual TLS, so a client
        presenting a CA-trusted client certificate connects and performs an RPC,
        while a client presenting no client certificate is rejected (EOFError)."""
        import rpyc
        from rpyc.utils.authenticators import SSLAuthenticator
        from rpyc.core.stream import SocketStream
        import ssl
        import subprocess
        import tempfile

        # Generate a self-signed certificate, used both as the server's cert/key
        # and as the CA both sides trust.
        td = tempfile.mkdtemp()
        key_path = os.path.join(td, "server.key")
        cert_path = os.path.join(td, "server.crt")
        subprocess.run(
            [
                "openssl", "req", "-x509", "-newkey", "rsa:2048",
                "-keyout", key_path, "-out", cert_path,
                "-days", "1", "-nodes", "-subj", "/CN=localhost",
            ],
            capture_output=True,
            check=True,
        )

        # ca_certs given, cert_reqs left unset -> defaults to CERT_REQUIRED (mutual TLS).
        auth = SSLAuthenticator(key_path, cert_path, ca_certs=cert_path)
        server = rpyc.ThreadedServer(
            rpyc.SlaveService, port=0, authenticator=auth,
        )
        _start_server_bg(server)

        try:
            # Client presenting a CA-trusted client cert: connection succeeds.
            ssl_kwargs = {
                "certfile": cert_path,
                "keyfile": key_path,
                "ca_certs": cert_path,
                "cert_reqs": ssl.CERT_NONE,
                "check_hostname": False,
            }
            stream = SocketStream.ssl_connect("localhost", server.port, ssl_kwargs)
            conn = rpyc.connect_stream(stream, service=rpyc.VoidService)
            try:
                assert conn.root.eval("2 + 2") == 4
            finally:
                conn.close()

            # Client presenting no client cert: CERT_REQUIRED rejects it.
            with pytest.raises(EOFError):
                bad_kwargs = {"cert_reqs": ssl.CERT_NONE, "check_hostname": False}
                bad_stream = SocketStream.ssl_connect("localhost", server.port, bad_kwargs)
                conn2 = rpyc.connect_stream(
                    bad_stream, service=rpyc.VoidService,
                    config={"sync_request_timeout": 3},
                )
                conn2.ping()
        finally:
            server.close()

    def test_ssl_authenticator_full_flow_with_self_signed_cert(self):
        """Verify that SSLAuthenticator works end-to-end: generate self-signed
        certs, start a ThreadedServer with SSL authentication, connect via an
        SSL-wrapped stream, perform RPC calls, and confirm that a plain
        (non-SSL) connection to the same server is rejected."""
        import rpyc
        from rpyc.utils.authenticators import SSLAuthenticator
        from rpyc.core.stream import SocketStream
        import ssl
        import subprocess
        import tempfile

        # Generate self-signed certificate
        td = tempfile.mkdtemp()
        key_path = os.path.join(td, "server.key")
        cert_path = os.path.join(td, "server.crt")
        subprocess.run(
            [
                "openssl", "req", "-x509", "-newkey", "rsa:2048",
                "-keyout", key_path, "-out", cert_path,
                "-days", "1", "-nodes", "-subj", "/CN=localhost",
            ],
            capture_output=True,
            check=True,
        )

        auth = SSLAuthenticator(key_path, cert_path)
        server = rpyc.ThreadedServer(
            rpyc.SlaveService, port=0, authenticator=auth,
        )
        _start_server_bg(server)

        try:
            # SSL connection should succeed
            ssl_kwargs = {
                "cert_reqs": ssl.CERT_NONE,
                "check_hostname": False,
            }
            stream = SocketStream.ssl_connect(
                "localhost", server.port, ssl_kwargs,
            )
            conn = rpyc.connect_stream(stream, service=rpyc.VoidService)
            try:
                assert conn.root.eval("2 + 2") == 4
                assert list(conn.root.eval("list(range(3))")) == [0, 1, 2]
            finally:
                conn.close()

            # Non-SSL connection should be rejected
            with pytest.raises(EOFError):
                conn2 = rpyc.connect(
                    "localhost", server.port,
                    config={"sync_request_timeout": 3},
                )
                conn2.ping()
        finally:
            server.close()


# =============================================================================
# Integration: bidirectional and advanced scenarios
# =============================================================================

class TestIntegration:
    """End-to-end integration tests exercising the full RPyC stack."""

    def test_bidirectional_classic_service(self):
        """Verify that ClassicService enables bidirectional communication where
        the client can use remote modules and evaluate expressions."""
        import rpyc

        conn = rpyc.classic.connect_thread()
        try:
            remote_platform = conn.modules.platform
            system = str(remote_platform.system())
            assert system in ("Linux", "Darwin", "Windows", "Java")

            assert conn.eval("2 ** 10") == 1024

            # builtins is a usable remote builtins namespace, not merely non-None
            assert conn.builtins.len([1, 2, 3]) == 3
            assert conn.builtins.abs(-5) == 5
        finally:
            conn.close()

    def test_buffiter_over_remote_iterator(self):
        """Verify that rpyc.buffiter fetches elements from a remote iterator
        in chunks, producing the correct results, and raises ValueError
        when factor < 1."""
        import rpyc

        conn = rpyc.classic.connect_thread()
        try:
            remote_range = conn.eval("list(range(20))")
            result = list(rpyc.buffiter(remote_range, chunk=5))
            assert result == list(range(20))

            # factor=0 must raise ValueError
            remote_range2 = conn.eval("range(10)")
            with pytest.raises(ValueError):
                list(rpyc.buffiter(remote_range2, factor=0))
        finally:
            conn.close()

    def test_bidirectional_callback(self):
        """Verify that a server can call back into the client's exposed method
        during a server call, testing re-entrant protocol handling. The client
        defines an exposed method; the server's on_connect stores the connection
        and calls back into the client during a server-side exposed method."""
        import rpyc

        class ClientService(rpyc.Service):
            def exposed_double(self, x):
                return x * 2

        class ServerService(rpyc.Service):
            def on_connect(self, conn):
                self.conn = conn

            def exposed_call_with_callback(self):
                result = self.conn.root.double(21)
                return result + 1

        conn = rpyc.connect_thread(
            service=ClientService,
            remote_service=ServerService,
        )
        try:
            result = conn.root.call_with_callback()
            assert result == 43
        finally:
            conn.close()

    def test_deep_netref_chain(self):
        """Verify that accessing attributes through 3+ levels of remote object
        nesting works correctly via netref delegation. Creates a chain of
        remote objects and accesses deeply nested attributes."""
        import rpyc

        conn = rpyc.classic.connect_thread()
        try:
            conn.execute(
                "class Level3:\n"
                "    value = 'deep'\n"
                "    count = 42\n"
                "\n"
                "class Level2:\n"
                "    child = Level3()\n"
                "    name = 'mid'\n"
                "\n"
                "class Level1:\n"
                "    child = Level2()\n"
                "    name = 'top'\n"
                "\n"
                "root_obj = Level1()\n"
            )
            remote_root = conn.eval("root_obj")
            # Level 1
            assert str(remote_root.name) == "top"
            # Level 2 (attribute.attribute)
            assert str(remote_root.child.name) == "mid"
            # Level 3 (attribute.attribute.attribute)
            assert str(remote_root.child.child.value) == "deep"
            assert remote_root.child.child.count == 42
        finally:
            conn.close()

    def test_concurrent_async_calls(self):
        """Verify that firing 5+ async calls simultaneously via async_() and
        collecting all AsyncResults returns correct values, testing that the
        request/reply multiplexing handles concurrent outstanding requests."""
        import rpyc
        from rpyc.core.async_ import AsyncResult

        conn = rpyc.classic.connect_thread()
        try:
            async_eval = rpyc.async_(conn.root.eval)
            # Fire 5 async calls simultaneously
            results = [async_eval(f"{i} * {i}") for i in range(5)]
            assert all(isinstance(r, AsyncResult) for r in results)
            # Collect all values
            values = []
            for r in results:
                r.wait()
                values.append(r.value)
            assert values == [0, 1, 4, 9, 16]
            # All should be ready with no errors
            assert all(r.ready for r in results)
            assert all(not r.error for r in results)
        finally:
            conn.close()

    def test_gevent_server_via_subprocess(self):
        """Verify that GeventServer (from rpyc.utils.server) handles client
        connections correctly, tested via subprocess isolation so that gevent's
        monkey-patching does not affect the main test process."""
        import subprocess

        code = (
            "import gevent.monkey; gevent.monkey.patch_all()\n"
            "import rpyc, time, gevent\n"
            "from rpyc.utils.server import GeventServer\n"
            "\n"
            "class SvcG(rpyc.Service):\n"
            "    def exposed_ping(self):\n"
            "        return 'pong'\n"
            "    def exposed_add(self, a, b):\n"
            "        return a + b\n"
            "\n"
            "server = GeventServer(SvcG, port=0, auto_register=False)\n"
            "g = gevent.spawn(server.start)\n"
            "time.sleep(0.5)\n"
            "port = server.port\n"
            "\n"
            "conn = rpyc.connect('localhost', port)\n"
            "assert conn.root.ping() == 'pong'\n"
            "assert conn.root.add(10, 20) == 30\n"
            "conn.close()\n"
            "\n"
            "# Multiple clients\n"
            "c1 = rpyc.connect('localhost', port)\n"
            "c2 = rpyc.connect('localhost', port)\n"
            "assert c1.root.add(1, 2) == 3\n"
            "assert c2.root.add(3, 4) == 7\n"
            "c1.close()\n"
            "c2.close()\n"
            "\n"
            "server.close()\n"
            "print('GEVENT_OK')\n"
        )

        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert result.returncode == 0, (
            f"GeventServer subprocess failed:\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )
        assert "GEVENT_OK" in result.stdout
