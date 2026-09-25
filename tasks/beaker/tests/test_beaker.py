"""
Tests for the beaker caching and session library.

Each test exercises a realistic end-to-end workflow combining multiple
beaker components: Cache, CacheManager, Session, middleware, crypto.
"""

import os
import threading
import time

import pytest
from webtest import TestApp



# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clean_cache_regions():
    """Reset global cache_regions between tests."""
    from beaker.cache import Cache, CacheManager, cache_regions, cache_region, region_invalidate
    from beaker.session import Session, SignedCookie
    from beaker.middleware import SessionMiddleware, CacheMiddleware
    from beaker.exceptions import BeakerException
    old = cache_regions.copy()
    yield
    cache_regions.clear()
    cache_regions.update(old)


@pytest.fixture
def data_dir(tmp_path):
    """Provide a temporary data directory for file-based backends."""
    d = str(tmp_path / "beaker_data")
    os.makedirs(d, exist_ok=True)
    yield d


# ---------------------------------------------------------------------------
# Cache integration tests
# ---------------------------------------------------------------------------


class TestCacheIntegration:
    """Integration tests for Cache with multiple backends and features."""

    def test_cache_expiration_with_createfunc(self):
        """A user sets up a cache with expiration and a createfunc that auto-populates on miss."""
        from beaker.cache import Cache, CacheManager, cache_regions, cache_region, region_invalidate
        from beaker.session import Session, SignedCookie
        from beaker.middleware import SessionMiddleware, CacheMiddleware
        from beaker.exceptions import BeakerException
        cache = Cache('expire_ns', type='memory', expire=1)
        call_count = [0]

        def creator():
            call_count[0] += 1
            return f"created_{call_count[0]}"

        # First access triggers createfunc
        val = cache.get('auto_key', createfunc=creator)
        assert val == 'created_1'
        assert call_count[0] == 1

        # Second access within TTL returns cached value
        val = cache.get('auto_key', createfunc=creator)
        assert val == 'created_1'
        assert call_count[0] == 1

        # Wait for expiration, then access again
        time.sleep(1.5)
        val = cache.get('auto_key', createfunc=creator)
        assert val == 'created_2'
        assert call_count[0] == 2


# ---------------------------------------------------------------------------
# CacheManager and region decorator tests
# ---------------------------------------------------------------------------


class TestCacheManagerIntegration:
    """Integration tests for CacheManager, region decorators, and invalidation."""

    def test_cache_region_decorator_and_invalidation(self):
        """A user decorates a function with @cache_region and invalidates cached results."""
        from beaker.cache import Cache, CacheManager, cache_regions, cache_region, region_invalidate
        from beaker.session import Session, SignedCookie
        from beaker.middleware import SessionMiddleware, CacheMiddleware
        from beaker.exceptions import BeakerException
        cache_regions.update({
            'test_region': {'type': 'memory', 'expire': 60}
        })

        call_count = [0]

        @cache_region('test_region', 'my_func')
        def compute(x, y):
            """Add x and y."""
            call_count[0] += 1
            return x + y

        # The decorator is transparent: it preserves the wrapped function's identity.
        assert compute.__name__ == 'compute'
        assert compute.__doc__ == 'Add x and y.'

        # First call computes
        assert compute(1, 2) == 3
        assert call_count[0] == 1

        # Second call with same args returns cached
        assert compute(1, 2) == 3
        assert call_count[0] == 1

        # Different args compute again
        assert compute(3, 4) == 7
        assert call_count[0] == 2

        # Invalidate
        region_invalidate(compute, 'test_region', 'my_func', 1, 2)
        assert compute(1, 2) == 3
        assert call_count[0] == 3  # recomputed

    def test_cache_manager_region_and_manager_invalidate(self):
        """A user decorates with CacheManager.region() and invalidates via CacheManager.region_invalidate()."""
        from beaker.cache import Cache, CacheManager, cache_regions, cache_region, region_invalidate
        from beaker.session import Session, SignedCookie
        from beaker.middleware import SessionMiddleware, CacheMiddleware
        from beaker.exceptions import BeakerException

        cache_regions.update({
            'quick': {'type': 'memory', 'expire': 60}
        })
        cm = CacheManager(cache_regions=cache_regions.copy())

        region_call_count = [0]

        @cm.region('quick', 'load_data')
        def load(term):
            region_call_count[0] += 1
            return f"result_{term}"

        assert load("hello") == "result_hello"
        assert region_call_count[0] == 1
        assert load("hello") == "result_hello"
        assert region_call_count[0] == 1  # cached

        # Invalidate via the manager-bound region_invalidate (distinct from the
        # module-level region_invalidate): the cached value is cleared and recomputed.
        cm.region_invalidate(load, 'quick', 'load_data', 'hello')
        assert load("hello") == "result_hello"
        assert region_call_count[0] == 2  # recomputed after manager-level invalidation

        # A different argument is unaffected by the invalidation above.
        assert load("world") == "result_world"
        assert region_call_count[0] == 3
        assert load("world") == "result_world"
        assert region_call_count[0] == 3  # cached

    def test_unconfigured_region_raises(self):
        """A user tries to use an unconfigured region and gets BeakerException."""
        from beaker.cache import Cache, CacheManager, cache_regions, cache_region, region_invalidate
        from beaker.session import Session, SignedCookie
        from beaker.middleware import SessionMiddleware, CacheMiddleware
        from beaker.exceptions import BeakerException
        cm = CacheManager(cache_regions={})
        with pytest.raises(BeakerException):
            cm.get_cache_region('data', 'nonexistent_region')


# ---------------------------------------------------------------------------
# Session integration tests
# ---------------------------------------------------------------------------


class TestSessionIntegration:
    """Integration tests for Session lifecycle — create, save, load, invalidate."""

    def test_session_full_lifecycle(self, data_dir):
        """A user exercises the full session lifecycle: create, save, load, revert, regenerate_id."""
        from beaker.cache import Cache, CacheManager, cache_regions, cache_region, region_invalidate
        from beaker.session import Session, SignedCookie
        from beaker.middleware import SessionMiddleware, CacheMiddleware
        from beaker.exceptions import BeakerException

        # -- Phase 1: Create and save a session with data --
        sess = Session({}, type='file', data_dir=data_dir, key='test.session',
                       use_cookies=False)
        sess['username'] = 'Alice'
        sess['role'] = 'admin'
        sess.save()
        session_id = sess.id

        # -- Phase 2: Load the session by ID and verify data round-trips --
        sess2 = Session({}, type='file', data_dir=data_dir, key='test.session',
                        id=session_id, use_cookies=False)
        sess2.load()
        assert sess2['username'] == 'Alice'
        assert sess2['role'] == 'admin'

        # -- Phase 3: Modify data, then revert unsaved changes --
        sess2['username'] = 'Bob'
        assert sess2['username'] == 'Bob'

        sess2.revert()
        assert sess2['username'] == 'Alice'  # reverted to saved state

        # -- Phase 4: Regenerate session ID — new ID, data preserved --
        old_id = sess2.id
        sess2['token'] = 'secret'
        sess2.save()

        sess2.regenerate_id()
        new_id = sess2.id
        assert new_id != old_id
        assert sess2['username'] == 'Alice'  # data preserved
        assert sess2['token'] == 'secret'    # data preserved
        sess2.save()

        # -- Phase 5: Load with regenerated ID and verify final state --
        sess3 = Session({}, type='file', data_dir=data_dir, key='test.session',
                        id=new_id, use_cookies=False)
        sess3.load()
        assert sess3['username'] == 'Alice'
        assert sess3['role'] == 'admin'
        assert sess3['token'] == 'secret'

    def test_session_timeout_and_invalidation(self, data_dir):
        """A user verifies session timeout expiration and invalidation behavior."""
        from beaker.cache import Cache, CacheManager, cache_regions, cache_region, region_invalidate
        from beaker.session import Session, SignedCookie
        from beaker.middleware import SessionMiddleware, CacheMiddleware
        from beaker.exceptions import BeakerException

        # -- Phase 1: Create session with short timeout, verify it expires --
        sess = Session({}, type='file', data_dir=data_dir, key='test.session',
                       timeout=1, use_cookies=False)
        sess['data'] = 'temp'
        sess.save()
        session_id = sess.id

        time.sleep(1.5)

        sess2 = Session({}, type='file', data_dir=data_dir, key='test.session',
                        id=session_id, use_cookies=False, timeout=1)
        sess2.load()
        # After timeout, session data should be cleared (new session)
        assert 'data' not in sess2

        # -- Phase 2: Create a new session, add data, save --
        sess3 = Session({}, type='file', data_dir=data_dir, key='test.session',
                        use_cookies=False)
        sess3['data'] = 'important'
        sess3.save()
        old_id = sess3.id

        # -- Phase 3: Invalidate — creates new session with new ID, data cleared --
        sess3.invalidate()
        assert sess3.id != old_id
        assert 'data' not in sess3


# ---------------------------------------------------------------------------
# SignedCookie tests
# ---------------------------------------------------------------------------


class TestSignedCookieIntegration:
    """Integration tests for SignedCookie HMAC signing and verification."""

    def test_signed_cookie_round_trip(self):
        """A user creates a SignedCookie, sets a value, serializes via output(), parses back, and asserts value matches."""
        from beaker.cache import Cache, CacheManager, cache_regions, cache_region, region_invalidate
        from beaker.session import Session, SignedCookie
        from beaker.middleware import SessionMiddleware, CacheMiddleware
        from beaker.exceptions import BeakerException

        secret = 'my-secret-key'

        cookie = SignedCookie(secret)
        cookie['session_id'] = 'abc123'
        cookie_str = cookie.output(header='')

        cookie2 = SignedCookie(secret, cookie_str)
        assert cookie2['session_id'].value == 'abc123'

    def test_signed_cookie_tamper_detection(self):
        """A user creates a SignedCookie, serializes it, tampers the string, parses it, and asserts InvalidSignature (falsy)."""
        from beaker.cache import Cache, CacheManager, cache_regions, cache_region, region_invalidate
        from beaker.session import Session, SignedCookie
        from beaker.middleware import SessionMiddleware, CacheMiddleware
        from beaker.exceptions import BeakerException
        from beaker.session import InvalidSignature

        import re

        secret = 'my-secret-key'

        cookie = SignedCookie(secret)
        cookie['token'] = 'valid_data'
        cookie_str = cookie.output(header='')

        # Tamper the signed region in a serialization-agnostic way: flip a character inside the
        # coded 'token=<coded>' morsel value (the value runs until ';' or whitespace), regardless
        # of whether the value is stored plaintext or otherwise encoded. Any byte-level change to
        # the signed region must fail verification.
        m = re.search(r'token=([^;\s]+)', cookie_str)
        assert m, f"expected a token= morsel in cookie output, got: {cookie_str!r}"
        coded = m.group(1)
        mid = len(coded) // 2
        flipped = 'X' if coded[mid] != 'X' else 'Y'
        tampered_coded = coded[:mid] + flipped + coded[mid + 1:]
        tampered = cookie_str[:m.start(1)] + tampered_coded + cookie_str[m.end(1):]

        cookie2 = SignedCookie(secret, tampered)
        assert not cookie2['token'].value  # InvalidSignature is falsy


# ---------------------------------------------------------------------------
# Session encryption tests
# ---------------------------------------------------------------------------


class TestSessionEncryption:
    """Integration tests for encrypted sessions."""

    def test_encrypted_session_via_middleware(self, data_dir):
        """A user uses encrypted sessions with default pycrypto backend via WSGI middleware."""
        from beaker.cache import Cache, CacheManager, cache_regions, cache_region, region_invalidate
        from beaker.session import Session, SignedCookie
        from beaker.middleware import SessionMiddleware, CacheMiddleware
        from beaker.exceptions import BeakerException

        def app(environ, start_response):
            session = environ['beaker.session']
            if 'secret' not in session:
                session['secret'] = 'classified_data'
                session.save()
            start_response('200 OK', [('Content-type', 'text/plain')])
            return [session.get('secret', 'none').encode('utf-8')]

        wrapped = SessionMiddleware(app, config={},
                                    **{'session.type': 'file',
                                       'session.data_dir': data_dir,
                                       'session.key': 'enc.session',
                                       'session.encrypt_key': 'a' * 32,
                                       'session.validate_key': 'validation_secret'})
        test_app = TestApp(wrapped)

        resp = test_app.get('/')
        assert resp.text == 'classified_data'

        resp2 = test_app.get('/')
        assert resp2.text == 'classified_data'


# ---------------------------------------------------------------------------
# Crypto backend tests
# ---------------------------------------------------------------------------


class TestCryptoBackends:
    """Integration tests for different cryptographic backends."""

    def test_pyca_cryptography_encrypted_session(self, data_dir):
        """A user uses encrypted sessions with the pyca cryptography backend via WSGI middleware."""
        from beaker.cache import Cache, CacheManager, cache_regions, cache_region, region_invalidate
        from beaker.session import Session, SignedCookie
        from beaker.middleware import SessionMiddleware, CacheMiddleware
        from beaker.exceptions import BeakerException

        def app(environ, start_response):
            session = environ['beaker.session']
            if 'secret' not in session:
                session['secret'] = 'pyca_encrypted_data'
                session.save()
            start_response('200 OK', [('Content-type', 'text/plain')])
            return [session.get('secret', 'none').encode('utf-8')]

        wrapped = SessionMiddleware(app, config={},
                                    **{'session.type': 'file',
                                       'session.data_dir': data_dir,
                                       'session.key': 'pyca.session',
                                       'session.encrypt_key': 'c' * 32,
                                       'session.validate_key': 'pyca_validate',
                                       'session.crypto_type': 'cryptography'})
        test_app = TestApp(wrapped)

        resp = test_app.get('/')
        assert resp.text == 'pyca_encrypted_data'

        resp2 = test_app.get('/')
        assert resp2.text == 'pyca_encrypted_data'


# ---------------------------------------------------------------------------
# Serializer tests
# ---------------------------------------------------------------------------


class TestSerializerIntegration:
    """Integration tests for session data serialization."""

    def test_json_serializer_session(self, data_dir):
        """A user creates a session with JSON serializer for non-pickle storage."""
        from beaker.cache import Cache, CacheManager, cache_regions, cache_region, region_invalidate
        from beaker.session import Session, SignedCookie
        from beaker.middleware import SessionMiddleware, CacheMiddleware
        from beaker.exceptions import BeakerException
        sess = Session({}, type='file', data_dir=data_dir, key='json.session',
                       data_serializer='json')
        sess['name'] = 'Alice'
        sess['items'] = [1, 2, 3]
        sess.save()
        session_id = sess.id

        # Load with JSON serializer
        sess2 = Session({}, type='file', data_dir=data_dir, key='json.session',
                        id=session_id, use_cookies=False, data_serializer='json')
        sess2.load()
        assert sess2['name'] == 'Alice'
        assert sess2['items'] == [1, 2, 3]


# ---------------------------------------------------------------------------
# Complex scenarios
# ---------------------------------------------------------------------------


class TestComplexScenarios:
    """End-to-end tests combining multiple beaker features."""

    def test_cache_manager_cache_decorator_with_type(self):
        """A user uses CacheManager.cache() decorator with explicit type and expire parameters."""
        from beaker.cache import Cache, CacheManager, cache_regions, cache_region, region_invalidate
        from beaker.session import Session, SignedCookie
        from beaker.middleware import SessionMiddleware, CacheMiddleware
        from beaker.exceptions import BeakerException

        cm = CacheManager(cache_regions={})
        cache_call_count = [0]

        @cm.cache('my_cache_ns', type='memory', expire=60)
        def compute(x):
            cache_call_count[0] += 1
            return x * 2

        assert compute(5) == 10
        assert cache_call_count[0] == 1
        assert compute(5) == 10
        assert cache_call_count[0] == 1  # cached

        # Different args recompute
        assert compute(7) == 14
        assert cache_call_count[0] == 2

    def test_cache_region_with_file_backend_and_expiration(self, data_dir):
        """A user uses @cache_region with a file backend and expiration, verifying caching and re-computation after expiry."""
        from beaker.cache import Cache, CacheManager, cache_regions, cache_region, region_invalidate
        from beaker.session import Session, SignedCookie
        from beaker.middleware import SessionMiddleware, CacheMiddleware
        from beaker.exceptions import BeakerException

        cache_regions.update({
            'file_cache': {
                'type': 'file',
                'data_dir': data_dir,
                'expire': 1,
            }
        })

        exp_call_count = [0]

        @cache_region('file_cache', 'compute')
        def expensive_compute(x):
            exp_call_count[0] += 1
            return x ** 2

        assert expensive_compute(5) == 25
        assert exp_call_count[0] == 1
        assert expensive_compute(5) == 25
        assert exp_call_count[0] == 1  # cached

        time.sleep(1.5)
        assert expensive_compute(5) == 25
        assert exp_call_count[0] == 2  # recomputed after expiration

    def test_cache_kwargs_normalization(self):
        """A user verifies that kwargs are normalized to positional order so different call styles hit the same cache entry."""
        from beaker.cache import Cache, CacheManager, cache_regions, cache_region, region_invalidate
        from beaker.session import Session, SignedCookie
        from beaker.middleware import SessionMiddleware, CacheMiddleware
        from beaker.exceptions import BeakerException

        cache_regions.update({
            'norm_cache': {'type': 'memory', 'expire': 60}
        })

        norm_call_count = [0]

        @cache_region('norm_cache', 'normalize_test')
        def fetch(a, b, c):
            norm_call_count[0] += 1
            return a + b + c

        assert fetch(1, 2, 3) == 6
        assert norm_call_count[0] == 1

        # Kwargs in different orderings hit the same cache entry
        assert fetch(1, c=3, b=2) == 6
        assert norm_call_count[0] == 1  # cached: kwargs normalized to positional

        assert fetch(a=1, b=2, c=3) == 6
        assert norm_call_count[0] == 1  # cached: all kwargs normalized

        assert fetch(1, b=2, c=3) == 6
        assert norm_call_count[0] == 1  # cached: mixed positional + kwargs

        # Different values recompute
        assert fetch(4, c=6, b=5) == 15
        assert norm_call_count[0] == 2

    def test_class_method_caching_excludes_self(self):
        """A user verifies that self/cls is excluded from the cache key so different instances share cached results."""
        from beaker.cache import Cache, CacheManager, cache_regions, cache_region, region_invalidate
        from beaker.session import Session, SignedCookie
        from beaker.middleware import SessionMiddleware, CacheMiddleware
        from beaker.exceptions import BeakerException

        cache_regions.update({
            'method_cache': {'type': 'memory', 'expire': 60}
        })

        method_call_count = [0]

        class DataService:
            @cache_region('method_cache', 'service_load')
            def load(self, query):
                method_call_count[0] += 1
                return f"result_{query}"

        svc1 = DataService()
        svc2 = DataService()

        assert svc1.load("foo") == "result_foo"
        assert method_call_count[0] == 1

        # Different instance, same args: cached because self excluded from key
        assert svc2.load("foo") == "result_foo"
        assert method_call_count[0] == 1

    def test_cookie_session_via_middleware(self, data_dir):
        """A user uses cookie-only sessions (type='cookie') with encryption via WSGI middleware."""
        from beaker.cache import Cache, CacheManager, cache_regions, cache_region, region_invalidate
        from beaker.session import Session, SignedCookie
        from beaker.middleware import SessionMiddleware, CacheMiddleware
        from beaker.exceptions import BeakerException
        def app(environ, start_response):
            session = environ['beaker.session']
            if 'visits' not in session:
                session['visits'] = 0
            session['visits'] += 1
            session['user'] = 'Bob'
            session.save()
            start_response('200 OK', [('Content-type', 'text/plain')])
            return [f"{session['user']}:{session['visits']}".encode('utf-8')]

        wrapped = SessionMiddleware(app, config={},
                                    **{'session.type': 'cookie',
                                       'session.validate_key': 'validate_secret_key',
                                       'session.encrypt_key': 'b' * 32,
                                       'session.key': 'cookie.session'})
        test_app = TestApp(wrapped)

        resp1 = test_app.get('/')
        assert resp1.text == 'Bob:1'

        resp2 = test_app.get('/')
        assert resp2.text == 'Bob:2'

        resp3 = test_app.get('/')
        assert resp3.text == 'Bob:3'

        # Verify the Set-Cookie header uses the correct cookie key and contains data
        set_cookie_header = resp1.headers.get('Set-Cookie', '')
        assert set_cookie_header, "First response must include a Set-Cookie header"
        assert 'cookie.session=' in set_cookie_header, (
            f"Set-Cookie must use the configured key 'cookie.session', got: {set_cookie_header}"
        )
        # Extract cookie value and verify it's non-empty (contains encrypted session data)
        for part in set_cookie_header.split(';'):
            part = part.strip()
            if part.startswith('cookie.session='):
                cookie_value = part.split('=', 1)[1]
                assert len(cookie_value) > 0, "Cookie value must be non-empty (encrypted session data)"
                break
        else:
            raise AssertionError(f"Could not find cookie.session= in Set-Cookie header: {set_cookie_header}")

    def test_concurrent_file_cache_access(self, data_dir):
        """A user accesses a file-backed cache from multiple threads, verifying synchronization."""
        from beaker.cache import Cache, CacheManager, cache_regions, cache_region, region_invalidate
        from beaker.session import Session, SignedCookie
        from beaker.middleware import SessionMiddleware, CacheMiddleware
        from beaker.exceptions import BeakerException
        cache = Cache('concurrent_ns', type='file', data_dir=data_dir)
        errors = []
        results = []

        def worker(thread_id):
            try:
                for i in range(20):
                    key = f"key_{thread_id}_{i}"
                    cache.put(key, f"value_{thread_id}_{i}")
                    val = cache.get(key)
                    if val != f"value_{thread_id}_{i}":
                        errors.append(f"Thread {thread_id}: expected value_{thread_id}_{i}, got {val}")
                results.append(thread_id)
            except Exception as e:
                errors.append(f"Thread {thread_id}: {e}")

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Errors: {errors}"
        assert len(results) == 4

    def test_session_with_corrupt_data_handling(self, data_dir):
        """A user loads a session whose backend data is corrupted; verifies graceful handling with invalidate_corrupt=True."""
        from beaker.cache import Cache, CacheManager, cache_regions, cache_region, region_invalidate
        from beaker.session import Session, SignedCookie
        from beaker.middleware import SessionMiddleware, CacheMiddleware
        from beaker.exceptions import BeakerException
        sess = Session({}, type='file', data_dir=data_dir, key='corrupt.session',
                       invalidate_corrupt=True, use_cookies=False)
        sess['data'] = 'important'
        sess.save()
        session_id = sess.id

        # Find and corrupt the session file
        import glob
        session_files = glob.glob(os.path.join(data_dir, '**', '*'), recursive=True)
        data_files = [f for f in session_files if os.path.isfile(f) and 'container_file' in f.lower()
                      or (os.path.isfile(f) and not f.endswith('.lock'))]
        # Corrupt any data files we find
        for f in data_files:
            if os.path.isfile(f) and not f.endswith('.lock'):
                with open(f, 'wb') as fh:
                    fh.write(b'CORRUPTED_DATA_HERE')

        # Loading with invalidate_corrupt=True should succeed (no exception)
        # and discard the corrupted data, giving a fresh empty session
        sess2 = Session({}, type='file', data_dir=data_dir, key='corrupt.session',
                        id=session_id, use_cookies=False, invalidate_corrupt=True)
        sess2.load()

        # The old data must be GONE — corrupt session was invalidated and replaced
        assert 'data' not in sess2, "Corrupted session data should have been discarded"

        # Session should be usable: write new data, save, reload, verify persistence
        sess2['new_data'] = 'recovered'
        sess2.save()
        new_id = sess2.id

        sess3 = Session({}, type='file', data_dir=data_dir, key='corrupt.session',
                        id=new_id, use_cookies=False, invalidate_corrupt=True)
        sess3.load()
        assert sess3['new_data'] == 'recovered', "New data written after corruption should persist"

    def test_session_nosave_no_cookie(self, data_dir):
        """A user accesses a session but doesn't call save(); no Set-Cookie header should be sent. Saving later produces a cookie and persists data."""
        from beaker.cache import Cache, CacheManager, cache_regions, cache_region, region_invalidate
        from beaker.session import Session, SignedCookie
        from beaker.middleware import SessionMiddleware, CacheMiddleware
        from beaker.exceptions import BeakerException
        state = {'action': 'no_save'}

        def app(environ, start_response):
            session = environ['beaker.session']
            if state['action'] == 'no_save':
                # Access session but DON'T call save()
                _ = session.get('data', 'none')
                body = b'ok'
            elif state['action'] == 'save':
                session['data'] = 'persisted_value'
                session.save()
                body = session['data'].encode('utf-8')
            elif state['action'] == 'read':
                body = session.get('data', 'missing').encode('utf-8')
            start_response('200 OK', [('Content-type', 'text/plain')])
            return [body]

        wrapped = SessionMiddleware(app, config={},
                                    **{'session.type': 'file',
                                       'session.data_dir': data_dir,
                                       'session.key': 'nosave.session'})
        test_app = TestApp(wrapped)

        # Request 1: access session without saving — no Set-Cookie
        state['action'] = 'no_save'
        resp1 = test_app.get('/')
        assert resp1.text == 'ok'
        assert 'Set-Cookie' not in resp1.headers, "No Set-Cookie should be sent when session is not saved"

        # Request 2: save session data — Set-Cookie MUST be present now
        state['action'] = 'save'
        resp2 = test_app.get('/')
        assert resp2.text == 'persisted_value'
        assert 'Set-Cookie' in resp2.headers, "Set-Cookie must be sent when session is saved"

        # Request 3: read back the saved data — it must persist
        state['action'] = 'read'
        resp3 = test_app.get('/')
        assert resp3.text == 'persisted_value', "Saved session data must persist across requests"


# ---------------------------------------------------------------------------
# Auto-save session tests
# ---------------------------------------------------------------------------


class TestAutoSaveSession:
    """Integration tests for sessions with auto=True that persist without explicit save()."""

    def test_auto_save_session_via_middleware(self, data_dir):
        """A user configures SessionMiddleware with auto=True; modified session data persists across requests without explicit save(), and a later read-only request neither loses the data nor changes it."""
        from beaker.cache import Cache, CacheManager, cache_regions, cache_region, region_invalidate
        from beaker.session import Session, SignedCookie
        from beaker.middleware import SessionMiddleware, CacheMiddleware
        from beaker.exceptions import BeakerException

        state = {'action': 'modify'}

        def app(environ, start_response):
            session = environ['beaker.session']
            if state['action'] == 'modify':
                count = session.get('count', 0)
                session['count'] = count + 1
                # Deliberately NOT calling session.save() — rely on auto=True
            elif state['action'] == 'read_only':
                # Pure read: don't modify the session and don't call save()
                _ = session.get('count', 0)
            start_response('200 OK', [('Content-type', 'text/plain')])
            return [str(session.get('count', 0)).encode('utf-8')]

        wrapped = SessionMiddleware(app, config={},
                                    **{'session.type': 'file',
                                       'session.data_dir': data_dir,
                                       'session.key': 'auto.session',
                                       'session.auto': True})
        test_app = TestApp(wrapped)

        # First request: count goes from 0 to 1, auto-saved without explicit save()
        state['action'] = 'modify'
        resp1 = test_app.get('/')
        assert resp1.text == '1'

        # Second request: session was persisted without explicit save, count increments
        resp2 = test_app.get('/')
        assert resp2.text == '2'

        # Read-only request: the persisted data survives and the counter does not change
        state['action'] = 'read_only'
        resp3 = test_app.get('/')
        assert resp3.text == '2', "read-only access must not lose session data"
        resp4 = test_app.get('/')
        assert resp4.text == '2', "session data must survive repeated read-only access"

        # A subsequent modifying request resumes incrementing from the persisted value
        state['action'] = 'modify'
        resp5 = test_app.get('/')
        assert resp5.text == '3'


# ---------------------------------------------------------------------------
# Cookie domain/path settings tests
# ---------------------------------------------------------------------------


class TestCookieSettings:
    """Integration tests for cookie_domain and cookie_path on SessionMiddleware."""

    def test_cookie_domain_and_path(self, data_dir):
        """A user configures SessionMiddleware with cookie_domain and cookie_path and verifies Set-Cookie attributes and session persistence."""
        from beaker.cache import Cache, CacheManager, cache_regions, cache_region, region_invalidate
        from beaker.session import Session, SignedCookie
        from beaker.middleware import SessionMiddleware, CacheMiddleware
        from beaker.exceptions import BeakerException

        def app(environ, start_response):
            session = environ['beaker.session']
            if 'username' not in session:
                session['username'] = 'Charlie'
                session.save()
            start_response('200 OK', [('Content-type', 'text/plain')])
            return [session.get('username', 'anonymous').encode('utf-8')]

        wrapped = SessionMiddleware(app, config={},
                                    **{'session.type': 'file',
                                       'session.data_dir': data_dir,
                                       'session.key': 'domain.session',
                                       'session.cookie_domain': '.example.com',
                                       'session.cookie_path': '/app'})
        test_app = TestApp(wrapped)

        # First request: session is created, Set-Cookie header should contain Domain and Path
        resp1 = test_app.get('/app')
        assert resp1.text == 'Charlie'

        set_cookie_header = resp1.headers.get('Set-Cookie', '')
        set_cookie_lower = set_cookie_header.lower()
        assert 'domain=.example.com' in set_cookie_lower, (
            f"Expected Domain=.example.com in Set-Cookie header, got: {set_cookie_header}"
        )
        assert 'path=/app' in set_cookie_lower, (
            f"Expected Path=/app in Set-Cookie header, got: {set_cookie_header}"
        )

        # Second request: cookie path matches /app so cookie is sent back, session persists
        resp2 = test_app.get('/app')
        assert resp2.text == 'Charlie'


# ---------------------------------------------------------------------------
# Accessed time session tests
# ---------------------------------------------------------------------------


class TestAccessedTimeSession:
    """Integration tests for sessions with accessed_time=True that persist on read access."""

    def test_accessed_time_persists_on_read(self, data_dir):
        """A user configures SessionMiddleware with accessed_time=True; session data persists even on read-only access."""
        from beaker.cache import Cache, CacheManager, cache_regions, cache_region, region_invalidate
        from beaker.session import Session, SignedCookie
        from beaker.middleware import SessionMiddleware, CacheMiddleware
        from beaker.exceptions import BeakerException

        state = {'action': 'write'}

        def app(environ, start_response):
            session = environ['beaker.session']
            if state['action'] == 'write':
                session['payload'] = 'important_data'
                session.save()  # explicitly save on write
            elif state['action'] == 'read':
                # Only READ session data, don't modify or save
                _ = session.get('payload', 'missing')
            start_response('200 OK', [('Content-type', 'text/plain')])
            return [session.get('payload', 'missing').encode('utf-8')]

        wrapped = SessionMiddleware(app, config={},
                                    **{'session.type': 'file',
                                       'session.data_dir': data_dir,
                                       'session.key': 'accessed.session',
                                       'session.timeout': 2,
                                       'session.accessed_time': True,
                                       'session.auto': False})
        test_app = TestApp(wrapped)

        # First request: write session data (explicitly saved)
        state['action'] = 'write'
        resp1 = test_app.get('/')
        assert resp1.text == 'important_data'

        # Wait, then read — accessed_time should update the access timestamp, keeping session alive
        time.sleep(1.2)
        state['action'] = 'read'
        resp2 = test_app.get('/')
        assert resp2.text == 'important_data'

        # Wait again, then read — total time since first write is ~2.4s (> timeout of 2s),
        # but since we read at ~1.2s (updating accessed_time), session should still be alive
        time.sleep(1.2)
        state['action'] = 'read'
        resp3 = test_app.get('/')
        assert resp3.text == 'important_data'


# ---------------------------------------------------------------------------
# Session get_by_id tests
# ---------------------------------------------------------------------------


class TestSessionGetById:
    """Integration tests for Session.get_by_id() — loading another session by ID within middleware."""

    def test_get_by_id_loads_other_session(self, data_dir):
        """A user creates a session via middleware, then uses get_by_id() in a second request to load that session and verify its data."""
        from beaker.cache import Cache, CacheManager, cache_regions, cache_region, region_invalidate
        from beaker.session import Session, SignedCookie
        from beaker.middleware import SessionMiddleware, CacheMiddleware
        from beaker.exceptions import BeakerException

        def app(environ, start_response):
            session = environ['beaker.session']
            action = environ.get('HTTP_X_ACTION', 'create')
            if action == 'create':
                session['username'] = 'Alice'
                session['role'] = 'admin'
                session.save()
                body = session.id.encode('utf-8')
            elif action == 'lookup':
                target_id = environ.get('HTTP_X_TARGET_ID', '')
                other = session.get_by_id(target_id)
                body = f"{other['username']}:{other['role']}".encode('utf-8')
            else:
                body = b'unknown'
            start_response('200 OK', [('Content-type', 'text/plain')])
            return [body]

        wrapped = SessionMiddleware(app, config={},
                                    **{'session.type': 'file',
                                       'session.data_dir': data_dir,
                                       'session.key': 'getbyid.session'})
        test_app = TestApp(wrapped)

        # First request: create a session with data
        resp1 = test_app.get('/', headers={'X-Action': 'create'})
        saved_id = resp1.text

        # Second request (different client, fresh TestApp = no cookies): use get_by_id to load the first session
        other_client = TestApp(wrapped)
        resp2 = other_client.get('/', headers={'X-Action': 'lookup', 'X-Target-Id': saved_id})
        assert resp2.text == 'Alice:admin'


# ---------------------------------------------------------------------------
# Cookie session with signing only (no encryption) tests
# ---------------------------------------------------------------------------


class TestCookieSessionSigningOnly:
    """Integration tests for cookie sessions with HMAC signing but no AES encryption."""

    def test_cookie_session_signed_no_encryption(self, data_dir):
        """A user configures a cookie session with validate_key (signing) but no encrypt_key (no encryption), and verifies data persistence."""
        from beaker.cache import Cache, CacheManager, cache_regions, cache_region, region_invalidate
        from beaker.session import Session, SignedCookie
        from beaker.middleware import SessionMiddleware, CacheMiddleware
        from beaker.exceptions import BeakerException

        def app(environ, start_response):
            session = environ['beaker.session']
            if 'visits' not in session:
                session['visits'] = 0
            session['visits'] += 1
            session['user'] = 'Dave'
            session.save()
            start_response('200 OK', [('Content-type', 'text/plain')])
            return [f"{session['user']}:{session['visits']}".encode('utf-8')]

        wrapped = SessionMiddleware(app, config={},
                                    **{'session.type': 'cookie',
                                       'session.validate_key': 'hmac_signing_secret',
                                       'session.key': 'signed.cookie.session'})
        test_app = TestApp(wrapped)

        resp1 = test_app.get('/')
        assert resp1.text == 'Dave:1'

        resp2 = test_app.get('/')
        assert resp2.text == 'Dave:2'

        resp3 = test_app.get('/')
        assert resp3.text == 'Dave:3'


# ---------------------------------------------------------------------------
# Config parsing tests
# ---------------------------------------------------------------------------


class TestCrossFeatureIntegration:
    """Cross-feature integration tests combining multiple beaker subsystems."""

    def test_encrypted_cookie_session_roundtrip_and_validate_key_change(self):
        """A user stores a value in an encrypted cookie session and reads it back on a later request; a server configured with a different validate_key rejects the signed payload, so the prior value does not leak across a key rotation."""
        from beaker.cache import Cache, CacheManager, cache_regions, cache_region, region_invalidate
        from beaker.session import Session, SignedCookie
        from beaker.middleware import SessionMiddleware, CacheMiddleware
        from beaker.exceptions import BeakerException

        cookie_key = 'enc.roundtrip.session'
        state = {'phase': 'write'}

        def app(environ, start_response):
            session = environ['beaker.session']
            if state['phase'] == 'write':
                session['secret'] = 'top_secret_value'
                session.save()
                body = 'stored'
            else:  # read
                body = session.get('secret', 'MISSING')
            start_response('200 OK', [('Content-type', 'text/plain')])
            return [body.encode('utf-8')]

        common = {'session.type': 'cookie',
                  'session.encrypt_key': 'e' * 32,
                  'session.key': cookie_key}

        # Sign + encrypt with the original validate_key.
        wrapped = SessionMiddleware(app, config={},
                                    **{**common, 'session.validate_key': 'orig_validate_key'})
        client = TestApp(wrapped)

        state['phase'] = 'write'
        resp1 = client.get('/')
        assert resp1.text == 'stored'

        # Same client carries the cookie, so the encrypted value round-trips back.
        state['phase'] = 'read'
        resp2 = client.get('/')
        assert resp2.text == 'top_secret_value'

        # A server with a DIFFERENT validate_key must reject the signed cookie and see a fresh
        # empty session — the prior value must not leak across a key rotation.
        wrapped_rotated = SessionMiddleware(app, config={},
                                            **{**common,
                                               'session.validate_key': 'rotated_validate_key',
                                               'session.invalidate_corrupt': True})
        rotated_client = TestApp(wrapped_rotated)

        set_cookie = resp1.headers.get('Set-Cookie', '')
        assert set_cookie, "first response must set a cookie"
        cookie_value = None
        for part in set_cookie.split(';'):
            part = part.strip()
            if part.startswith(cookie_key + '='):
                cookie_value = part.split('=', 1)[1]
                break
        assert cookie_value, f"Could not find {cookie_key}= in Set-Cookie header: {set_cookie}"

        rotated_client.set_cookie(cookie_key, cookie_value)
        state['phase'] = 'read'
        resp3 = rotated_client.get('/')
        assert resp3.text == 'MISSING', (
            f"a changed validate_key must reject the signed payload, got: {resp3.text!r}"
        )

    def test_cache_and_session_middleware_stack(self, data_dir):
        """A user chains CacheMiddleware and SessionMiddleware on the same WSGI app; verifies both subsystems cooperate without interfering."""
        from beaker.cache import Cache, CacheManager, cache_regions, cache_region, region_invalidate
        from beaker.session import Session, SignedCookie
        from beaker.middleware import SessionMiddleware, CacheMiddleware
        from beaker.exceptions import BeakerException

        def app(environ, start_response):
            session = environ['beaker.session']
            cache_mgr = environ['beaker.cache']

            # Use cache subsystem
            cache = cache_mgr.get_cache('shared_ns')
            if not cache.has_key('cached_item'):
                cache.put('cached_item', 'from_cache')

            # Use session subsystem
            if 'visit_count' not in session:
                session['visit_count'] = 0
            session['visit_count'] += 1
            session.save()

            cached_val = cache.get('cached_item')
            body = f"{cached_val}:{session['visit_count']}"
            start_response('200 OK', [('Content-type', 'text/plain')])
            return [body.encode('utf-8')]

        inner = CacheMiddleware(app, config={}, **{'cache.type': 'memory'})
        wrapped = SessionMiddleware(inner, config={},
                                    **{'session.type': 'file',
                                       'session.data_dir': data_dir,
                                       'session.key': 'stack.session'})
        test_app = TestApp(wrapped)

        # First request: both cache and session are populated
        resp1 = test_app.get('/')
        assert resp1.text == 'from_cache:1'

        # Second request: cached value persists, session counter increments
        resp2 = test_app.get('/')
        assert resp2.text == 'from_cache:2'

    def test_config_parsing_to_region_decorator_pipeline(self, data_dir):
        """A user parses a flat config dict into regions, applies them, and uses @cache_region — testing the full config-to-runtime pipeline."""
        from beaker.cache import Cache, CacheManager, cache_regions, cache_region, region_invalidate
        from beaker.session import Session, SignedCookie
        from beaker.middleware import SessionMiddleware, CacheMiddleware
        from beaker.exceptions import BeakerException
        from beaker.util import parse_cache_config_options

        config = {
            'cache.type': 'memory',
            'cache.expire': '120',
            'cache.regions': 'fast, slow',
            'cache.fast.type': 'file',
            'cache.fast.expire': '30',
            'cache.fast.data_dir': data_dir,
            'cache.slow.type': 'memory',
            'cache.slow.expire': '3600',
        }
        options = parse_cache_config_options(config)

        # Top-level options: prefix stripped, string expire coerced to int
        assert options['type'] == 'memory'
        assert options['expire'] == 120, "Top-level string '120' should be coerced to int 120"

        # Every comma-separated region name becomes its own region config
        assert set(options['cache_regions']) >= {'fast', 'slow'}, (
            f"Both regions listed in cache.regions should be parsed, got: {sorted(options['cache_regions'])}"
        )

        # Verify per-region extraction and type coercion happened
        assert options['cache_regions']['fast']['expire'] == 30, (
            "String '30' should be coerced to int 30"
        )
        assert options['cache_regions']['fast']['type'] == 'file'
        assert options['cache_regions']['fast']['data_dir'] == data_dir
        assert options['cache_regions']['slow']['type'] == 'memory'
        assert options['cache_regions']['slow']['expire'] == 3600

        # Apply parsed regions to global cache_regions
        cache_regions.update(options['cache_regions'])

        call_count = [0]

        @cache_region('fast', 'pipeline_test')
        def transform(value):
            call_count[0] += 1
            return value.upper()

        # First call computes
        assert transform('hello') == 'HELLO'
        assert call_count[0] == 1

        # Second call is cached
        assert transform('hello') == 'HELLO'
        assert call_count[0] == 1

        # Invalidate and recompute
        region_invalidate(transform, 'fast', 'pipeline_test', 'hello')
        assert transform('hello') == 'HELLO'
        assert call_count[0] == 2

    def test_session_backend_isolation(self, data_dir):
        """A user creates two sessions with different backends but overlapping keys; verifies each backend's data is independent and invalidation is isolated."""
        from beaker.cache import Cache, CacheManager, cache_regions, cache_region, region_invalidate
        from beaker.session import Session, SignedCookie
        from beaker.middleware import SessionMiddleware, CacheMiddleware
        from beaker.exceptions import BeakerException

        # Session A: file backend
        sess_a = Session({}, type='file', data_dir=data_dir, key='iso.session',
                         use_cookies=False)
        sess_a['shared_key'] = 'file_value'
        sess_a['backend'] = 'file'
        sess_a.save()
        id_a = sess_a.id

        # Session B: memory backend, different data for the same key name
        sess_b = Session({}, type='memory', key='iso.session', use_cookies=False)
        sess_b['shared_key'] = 'memory_value'
        sess_b['backend'] = 'memory'
        sess_b.save()
        id_b = sess_b.id

        # Reload both and verify isolation
        sess_a2 = Session({}, type='file', data_dir=data_dir, key='iso.session',
                          id=id_a, use_cookies=False)
        sess_a2.load()
        assert sess_a2['shared_key'] == 'file_value'
        assert sess_a2['backend'] == 'file'

        sess_b2 = Session({}, type='memory', key='iso.session',
                          id=id_b, use_cookies=False)
        sess_b2.load()
        assert sess_b2['shared_key'] == 'memory_value'
        assert sess_b2['backend'] == 'memory'

        # Invalidate session A — session B must remain unaffected
        sess_a2.invalidate()
        assert 'shared_key' not in sess_a2

        sess_b3 = Session({}, type='memory', key='iso.session',
                          id=id_b, use_cookies=False)
        sess_b3.load()
        assert sess_b3['shared_key'] == 'memory_value', (
            "Invalidating file session must not affect memory session"
        )

    def test_concurrent_middleware_session_client_isolation(self, data_dir):
        """Two clients (separate TestApp instances) use the same SessionMiddleware; verifies each client gets its own session and data doesn't leak."""
        from beaker.cache import Cache, CacheManager, cache_regions, cache_region, region_invalidate
        from beaker.session import Session, SignedCookie
        from beaker.middleware import SessionMiddleware, CacheMiddleware
        from beaker.exceptions import BeakerException

        state = {'action': 'set'}

        def app(environ, start_response):
            session = environ['beaker.session']
            if state['action'] == 'set':
                user = environ.get('HTTP_X_USER', 'unknown')
                session['user'] = user
                session.save()
            body = session.get('user', 'empty')
            start_response('200 OK', [('Content-type', 'text/plain')])
            return [body.encode('utf-8')]

        wrapped = SessionMiddleware(app, config={},
                                    **{'session.type': 'file',
                                       'session.data_dir': data_dir,
                                       'session.key': 'multi.session'})

        # Two independent clients (separate cookie jars)
        client1 = TestApp(wrapped)
        client2 = TestApp(wrapped)

        # Client 1 sets user = Alice
        state['action'] = 'set'
        resp = client1.get('/', headers={'X-User': 'Alice'})
        assert resp.text == 'Alice'

        # Client 2 sets user = Bob
        resp = client2.get('/', headers={'X-User': 'Bob'})
        assert resp.text == 'Bob'

        # Client 1 reads back — should still be Alice, not Bob
        state['action'] = 'read'
        resp = client1.get('/')
        assert resp.text == 'Alice', (
            f"Client 1 should see 'Alice' but got '{resp.text}' — session data leaked between clients"
        )

        # Client 2 reads back — should still be Bob, not Alice
        resp = client2.get('/')
        assert resp.text == 'Bob', (
            f"Client 2 should see 'Bob' but got '{resp.text}' — session data leaked between clients"
        )


# ---------------------------------------------------------------------------
# Workflow consolidation tests
# ---------------------------------------------------------------------------


class TestWorkflowConsolidation:
    """Tests that combine multiple always-passing individual tests into natural user workflows."""

    def test_app_bootstrap_workflow(self, data_dir):
        """A user bootstraps an app: sets up a CacheManager with named regions, serves data through
        get_cache_region, then wires the same backend into a WSGI app via CacheMiddleware."""
        from beaker.cache import Cache, CacheManager, cache_regions, cache_region, region_invalidate
        from beaker.session import Session, SignedCookie
        from beaker.middleware import SessionMiddleware, CacheMiddleware
        from beaker.exceptions import BeakerException

        # Phase 1: Build a CacheManager with named regions and serve data via get_cache_region
        cm = CacheManager(cache_regions={
            'short': {'type': 'memory', 'expire': 60},
            'long': {'type': 'memory', 'expire': 3600},
        })

        short_cache = cm.get_cache_region('my_data', 'short')
        short_cache.put('item', 'short_value')
        assert short_cache.get('item') == 'short_value'

        long_cache = cm.get_cache_region('my_data', 'long')
        long_cache.put('item', 'long_value')
        assert long_cache.get('item') == 'long_value'

        # Phase 2: Wrap a WSGI app with CacheMiddleware and serve through environ['beaker.cache']
        def app(environ, start_response):
            cache_mgr = environ['beaker.cache']
            cache = cache_mgr.get_cache('test')
            cache.put('val', 42)
            result = str(cache.get('val'))
            start_response('200 OK', [('Content-type', 'text/plain')])
            return [result.encode('utf-8')]

        wrapped = CacheMiddleware(app, config={},
                                   **{'cache.type': 'memory'})
        test_app = TestApp(wrapped)

        resp = test_app.get('/')
        assert resp.text == '42'

    def test_multi_backend_cache_operations(self, data_dir):
        """A user creates caches with memory, dbm, and file backends, exercises CRUD on each, and verifies backend independence."""
        from beaker.cache import Cache, CacheManager, cache_regions, cache_region, region_invalidate
        from beaker.session import Session, SignedCookie
        from beaker.middleware import SessionMiddleware, CacheMiddleware
        from beaker.exceptions import BeakerException

        # Phase 1: Memory backend — full CRUD + dict interface
        mem_cache = Cache('multi_ops_ns', type='memory')
        mem_cache.put('key1', 'value1')
        assert mem_cache.get('key1') == 'value1'
        mem_cache['key2'] = 'value2'
        assert mem_cache['key2'] == 'value2'
        assert 'key2' in mem_cache
        assert mem_cache.has_key('key2')
        del mem_cache['key1']
        with pytest.raises(KeyError):
            mem_cache['key1']
        mem_cache.clear()
        assert 'key2' not in mem_cache

        # Phase 2: DBM backend — persistence across instances
        dbm_cache1 = Cache('multi_ops_ns', type='dbm', data_dir=data_dir)
        dbm_cache1.put('persistent_key', 'persistent_value')
        assert dbm_cache1.get('persistent_key') == 'persistent_value'
        dbm_cache2 = Cache('multi_ops_ns', type='dbm', data_dir=data_dir)
        assert dbm_cache2.get('persistent_key') == 'persistent_value'

        # Phase 3: File backend — complex objects
        file_cache = Cache('multi_ops_ns', type='file', data_dir=data_dir)
        complex_value = {'nested': {'key': [1, 2, 3]}, 'tuple': (4, 5)}
        file_cache.put('complex', complex_value)
        assert file_cache.get('complex') == complex_value
        file_cache.put('number', 42)
        assert file_cache.get('number') == 42

        # Phase 4: Verify backend independence — same namespace, different types
        mem_cache2 = Cache('multi_ops_ns', type='memory')
        mem_cache2.put('shared_key', 'memory_data')
        file_cache.put('shared_key', 'file_data')
        dbm_cache2.put('shared_key', 'dbm_data')
        assert mem_cache2.get('shared_key') == 'memory_data'
        assert file_cache.get('shared_key') == 'file_data'
        assert dbm_cache2.get('shared_key') == 'dbm_data'

    def test_session_middleware_lifecycle(self, data_dir):
        """A user goes through a full session + middleware lifecycle: counter with signed cookies, user data persistence, session deletion and renewal."""
        from beaker.cache import Cache, CacheManager, cache_regions, cache_region, region_invalidate
        from beaker.session import Session, SignedCookie
        from beaker.middleware import SessionMiddleware, CacheMiddleware
        from beaker.exceptions import BeakerException

        state = {'phase': 'counter'}

        def app(environ, start_response):
            session = environ['beaker.session']
            if state['phase'] == 'counter':
                count = session.get('count', 0)
                session['count'] = count + 1
                if 'user' not in session:
                    session['user'] = 'Alice'
                session.save()
                body = f"{session['user']}:{session['count']}"
            elif state['phase'] == 'delete':
                session.delete()
                body = 'deleted'
            elif state['phase'] == 'check':
                body = session.get('user', 'empty') + ':' + str(session.get('count', 0))
            start_response('200 OK', [('Content-type', 'text/plain')])
            return [body.encode('utf-8')]

        # Use file backend with session.secret for cookie signing
        wrapped = SessionMiddleware(app, config={},
                                    **{'session.type': 'file',
                                       'session.data_dir': data_dir,
                                       'session.key': 'lifecycle.session',
                                       'session.secret': 'my-signing-secret'})
        test_app = TestApp(wrapped)

        # Phase 1: Counter increments across 3 requests, proving session persistence
        state['phase'] = 'counter'
        resp1 = test_app.get('/')
        assert resp1.text == 'Alice:1'
        resp2 = test_app.get('/')
        assert resp2.text == 'Alice:2'
        resp3 = test_app.get('/')
        assert resp3.text == 'Alice:3'

        # Phase 2: Verify user data 'Alice' persists with signed cookies
        assert 'Alice' in resp3.text

        # Phase 3: Delete session, verify next request gets empty session
        state['phase'] = 'delete'
        test_app.get('/')

        state['phase'] = 'check'
        resp_after_delete = test_app.get('/')
        assert resp_after_delete.text == 'empty:0'


# ---------------------------------------------------------------------------
# Difficult test flavors
# ---------------------------------------------------------------------------


class TestDifficultFlavors:
    """Logically distinct variations of currently-failing test areas that test different angles."""

    def test_cookie_session_complex_data_serialization(self):
        """A user stores complex data types (nested dict, list, unicode) in a cookie session and verifies round-trip serialization."""
        from beaker.cache import Cache, CacheManager, cache_regions, cache_region, region_invalidate
        from beaker.session import Session, SignedCookie
        from beaker.middleware import SessionMiddleware, CacheMiddleware
        from beaker.exceptions import BeakerException

        state = {'phase': 'write'}

        def app(environ, start_response):
            session = environ['beaker.session']
            if state['phase'] == 'write':
                session['nested'] = {'users': [{'name': 'Alice', 'age': 30}, {'name': 'Bob', 'age': 25}]}
                session['tags'] = ['python', 'web', 'cache']
                session['greeting'] = 'Hej varlden'
                session['count'] = 42
                session.save()
                body = 'stored'
            elif state['phase'] == 'read':
                nested = session.get('nested', {})
                tags = session.get('tags', [])
                greeting = session.get('greeting', '')
                count = session.get('count', 0)
                body = f"{len(nested.get('users', []))}:{len(tags)}:{greeting}:{count}"
            start_response('200 OK', [('Content-type', 'text/plain')])
            return [body.encode('utf-8')]

        wrapped = SessionMiddleware(app, config={},
                                    **{'session.type': 'cookie',
                                       'session.validate_key': 'complex_data_secret',
                                       'session.encrypt_key': 'd' * 32,
                                       'session.key': 'complex.cookie.session'})
        test_app = TestApp(wrapped)

        # Write complex data
        state['phase'] = 'write'
        resp1 = test_app.get('/')
        assert resp1.text == 'stored'

        # Read back and verify round-trip serialization of complex types
        state['phase'] = 'read'
        resp2 = test_app.get('/')
        assert resp2.text == '2:3:Hej varlden:42'

    def test_region_invalidation_selective_by_function(self):
        """A user has two decorated functions sharing the same region; invalidating one function's cache leaves the other's cache intact."""
        from beaker.cache import Cache, CacheManager, cache_regions, cache_region, region_invalidate
        from beaker.session import Session, SignedCookie
        from beaker.middleware import SessionMiddleware, CacheMiddleware
        from beaker.exceptions import BeakerException

        cache_regions.update({
            'shared_region': {'type': 'memory', 'expire': 60}
        })

        call_count_a = [0]
        call_count_b = [0]

        @cache_region('shared_region', 'func_a')
        def compute_a(x):
            call_count_a[0] += 1
            return x * 10

        @cache_region('shared_region', 'func_b')
        def compute_b(x):
            call_count_b[0] += 1
            return x + 100

        # Both functions cache their results
        assert compute_a(5) == 50
        assert call_count_a[0] == 1
        assert compute_b(5) == 105
        assert call_count_b[0] == 1

        # Cached on second call
        assert compute_a(5) == 50
        assert call_count_a[0] == 1
        assert compute_b(5) == 105
        assert call_count_b[0] == 1

        # Invalidate only func_a's cache for arg 5
        region_invalidate(compute_a, 'shared_region', 'func_a', 5)

        # func_a recomputes
        assert compute_a(5) == 50
        assert call_count_a[0] == 2

        # func_b's cache is untouched
        assert compute_b(5) == 105
        assert call_count_b[0] == 1  # still 1 — not recomputed


# ---------------------------------------------------------------------------
# External backend tests (Redis, Memcached, SQLAlchemy)
# ---------------------------------------------------------------------------


class TestRedisBackend:
    """Integration tests for Redis-backed cache and sessions."""

    def test_redis_full_workflow(self):
        """A user exercises the full Redis workflow: cache CRUD, session save/load, and expiration."""
        from beaker.cache import Cache, CacheManager, cache_regions, cache_region, region_invalidate
        from beaker.session import Session, SignedCookie
        from beaker.middleware import SessionMiddleware, CacheMiddleware
        from beaker.exceptions import BeakerException

        # -- Phase 1: Cache CRUD with put/get, dict interface, remove, clear --
        cache = Cache('redis_test_ns', type='ext:redis', url='redis://localhost:6379/13')
        cache.put('rkey', 'rvalue')
        assert cache.get('rkey') == 'rvalue'
        assert 'rkey' in cache

        cache['rkey2'] = 'rvalue2'
        assert cache['rkey2'] == 'rvalue2'

        cache.remove('rkey')
        assert 'rkey' not in cache
        cache.clear()

        # -- Phase 2: Session save and load by ID --
        sess = Session({}, type='ext:redis', url='redis://localhost:6379/14',
                       key='redis.session', use_cookies=False)
        sess['user'] = 'alice'
        sess['role'] = 'admin'
        sess.save()
        session_id = sess.id

        sess2 = Session({}, type='ext:redis', url='redis://localhost:6379/14',
                        key='redis.session', id=session_id, use_cookies=False)
        sess2.load()
        assert sess2['user'] == 'alice'
        assert sess2['role'] == 'admin'
        sess2.delete()

        # -- Phase 3: Cache expiration --
        cache_exp = Cache('redis_expire_ns', type='ext:redis',
                          url='redis://localhost:6379/13', expire=1)
        cache_exp.put('expiring', 'value')
        assert cache_exp.get('expiring') == 'value'
        time.sleep(1.5)
        with pytest.raises(KeyError):
            cache_exp.get('expiring')


class TestMemcachedBackend:
    """Integration tests for Memcached-backed cache."""

    def test_memcached_cache_crud(self):
        """A user uses Cache with ext:memcached backend for full CRUD operations."""
        from beaker.cache import Cache, CacheManager, cache_regions, cache_region, region_invalidate
        from beaker.session import Session, SignedCookie
        from beaker.middleware import SessionMiddleware, CacheMiddleware
        from beaker.exceptions import BeakerException
        cache = Cache('mc_test_ns', type='ext:memcached', url='127.0.0.1:11211')
        cache.put('mkey', 'mvalue')
        assert cache.get('mkey') == 'mvalue'

        cache['mkey2'] = 'mvalue2'
        assert cache['mkey2'] == 'mvalue2'

        cache.remove('mkey')
        assert 'mkey' not in cache
        cache.clear()


class TestSQLAlchemyBackend:
    """Integration tests for SQLAlchemy-backed cache."""

    def test_sqla_cache_crud(self, data_dir):
        """A user uses Cache with ext:sqla backend backed by SQLite."""
        from beaker.cache import Cache, CacheManager, cache_regions, cache_region, region_invalidate
        from beaker.session import Session, SignedCookie
        from beaker.middleware import SessionMiddleware, CacheMiddleware
        from beaker.exceptions import BeakerException
        import sqlalchemy as sa

        engine = sa.create_engine('sqlite://')
        metadata = sa.MetaData()
        cache_table = sa.Table('beaker_cache', metadata,
                               sa.Column('namespace', sa.String(255), primary_key=True),
                               sa.Column('accessed', sa.DateTime, nullable=False),
                               sa.Column('created', sa.DateTime, nullable=False),
                               sa.Column('data', sa.PickleType, nullable=False))
        metadata.create_all(engine)

        cache = Cache('sqla_test_ns', type='ext:sqla', bind=engine,
                      table=cache_table, data_dir=data_dir)
        cache.put('skey', 'svalue')
        assert cache.get('skey') == 'svalue'
        assert 'skey' in cache

        cache.remove('skey')
        assert 'skey' not in cache


