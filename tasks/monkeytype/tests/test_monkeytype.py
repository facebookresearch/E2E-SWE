"""
Integration tests for MonkeyType — a runtime type collection and stub generation tool.

Tests exercise the full pipeline: trace functions → store traces → retrieve →
generate stubs, as well as type encoding round-trips, type inference/shrinking,
CLI via subprocess, and the TYPE_CHECKING import transformer.
"""
import inspect
import io
import os
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import unittest
from typing import Any, Callable, Dict, Iterator, List, Optional, Set, Tuple, Union
from pathlib import Path


# Module-level functions for tests that need resolvable qualnames
def _sample_add(x, y):
    return x + y

def _sample_greet(name, greeting="hello"):
    return f"{greeting}, {name}!"

def _sample_flexible(x):
    return str(x)

def _partially_annotated(x: int, y):
    """Has annotation on x but not y."""
    return str(x) + str(y)

def _fully_annotated(x: int) -> str:
    """Has annotations on both x and return."""
    return str(x)


def _may_throw(x):
    """Raises ValueError for negative input, otherwise doubles."""
    if x < 0:
        raise ValueError("negative")
    return x * 2


class _CLITestBase(unittest.TestCase):
    """Base for tests that drive the public ``monkeytype`` CLI (run/stub/apply).

    Each test gets a fresh scratch dir + SQLite db. ``_write`` drops a module/script
    into the scratch dir; ``_cli`` invokes ``python -m monkeytype`` there with
    ``MT_DB_PATH`` pointed at the test db; ``_run_and_stub`` traces a script and
    returns the rendered stub text for a module; ``_run_and_apply`` traces a script,
    applies inferred annotations to a module in place, and returns the rewritten source.
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "mt.sqlite3")
        self.env = os.environ.copy()
        self.env['MT_DB_PATH'] = self.db_path

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write(self, name, content):
        path = os.path.join(self.tmpdir, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            f.write(textwrap.dedent(content))
        return path

    def _cli(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "monkeytype", *args],
            capture_output=True, text=True, cwd=self.tmpdir, env=self.env,
        )

    def _run_and_stub(self, script_path, module, *stub_args):
        run_res = self._cli("run", script_path)
        self.assertEqual(run_res.returncode, 0, f"run failed: {run_res.stderr}")
        stub_res = self._cli("stub", module, *stub_args)
        self.assertEqual(stub_res.returncode, 0, f"stub failed: {stub_res.stderr}")
        return stub_res.stdout

    def _run_and_apply(self, script_path, module, source_name, *apply_args):
        run_res = self._cli("run", script_path)
        self.assertEqual(run_res.returncode, 0, f"run failed: {run_res.stderr}")
        apply_res = self._cli("apply", *apply_args, module)
        self.assertEqual(apply_res.returncode, 0, f"apply failed: {apply_res.stderr}")
        with open(os.path.join(self.tmpdir, source_name)) as f:
            return f.read()


# ===========================================================================
# 1. Tracing → Collecting runtime types
# ===========================================================================
class TestTracingIntegration(unittest.TestCase):
    """Trace function calls and verify collected argument/return types."""

    def test_tracing_core(self):
        """Trace simple functions capturing arg/return types, trace call chains
        (including a recursive one, where several frames of the same function are
        live at once), apply code filters, and verify exception sets return_type
        to None."""
        from monkeytype.tracing import CallTraceLogger, trace_calls

        # --- Simple function tracing ---
        class Collector(CallTraceLogger):
            def __init__(self):
                self.traces = []
                self.flushed = False
            def log(self, trace):
                self.traces.append(trace)
            def flush(self):
                self.flushed = True

        def add(a, b):
            return a + b

        collector = Collector()
        with trace_calls(collector, max_typed_dict_size=0):
            result = add(1, 2)

        self.assertEqual(result, 3)
        self.assertTrue(collector.flushed)
        self.assertEqual(len(collector.traces), 1)

        trace = collector.traces[0]
        self.assertEqual(trace.arg_types, {'a': int, 'b': int})
        self.assertEqual(trace.return_type, type(None).__mro__[0] if result is None else int)
        self.assertIs(trace.func, add)

        # --- Call chain tracing ---
        class Collector2(CallTraceLogger):
            def __init__(self):
                self.traces = []
            def log(self, trace):
                self.traces.append(trace)

        def outer(x):
            return inner(x + 1)

        def inner(y):
            return y * 2

        collector2 = Collector2()
        with trace_calls(collector2, max_typed_dict_size=0):
            result2 = outer(5)

        self.assertEqual(result2, 12)
        traced_funcs = {t.func for t in collector2.traces}
        self.assertIn(outer, traced_funcs)
        self.assertIn(inner, traced_funcs)

        # --- Code filter ---
        class Collector3(CallTraceLogger):
            def __init__(self):
                self.traces = []
            def log(self, trace):
                self.traces.append(trace)

        def included(x):
            return x + 1

        def excluded(x):
            return x - 1

        collector3 = Collector3()
        with trace_calls(collector3, max_typed_dict_size=0,
                         code_filter=lambda code: 'included' in code.co_name):
            included(1)
            excluded(2)

        func_names = [t.func.__name__ for t in collector3.traces]
        self.assertIn('included', func_names)
        self.assertNotIn('excluded', func_names)

        # --- Exception sets return_type to None ---
        class Collector4(CallTraceLogger):
            def __init__(self):
                self.traces = []
            def log(self, trace):
                self.traces.append(trace)

        collector4 = Collector4()
        with trace_calls(collector4, max_typed_dict_size=0):
            try:
                _may_throw(-1)
            except ValueError:
                pass
            _may_throw(5)

        mt_traces = [t for t in collector4.traces if t.func is _may_throw]
        self.assertEqual(len(mt_traces), 2)

        exc_trace = [t for t in mt_traces if t.return_type is None]
        self.assertEqual(len(exc_trace), 1)
        self.assertEqual(exc_trace[0].arg_types, {'x': int})

        ok_trace = [t for t in mt_traces if t.return_type is int]
        self.assertEqual(len(ok_trace), 1)
        self.assertEqual(ok_trace[0].arg_types, {'x': int})

        # --- Recursion: one trace per invocation ---
        # factorial(5) invokes the SAME function five times with five frames alive
        # simultaneously, so in-flight call bookkeeping keyed by anything coarser
        # than the frame (a single pending slot, or a map keyed by code object or
        # function) loses all but one of the five traces.
        class Collector5(CallTraceLogger):
            def __init__(self):
                self.traces = []
            def log(self, trace):
                self.traces.append(trace)

        def factorial(n):
            if n <= 1:
                return 1
            return n * factorial(n - 1)

        collector5 = Collector5()
        with trace_calls(collector5, max_typed_dict_size=0):
            fact_result = factorial(5)

        self.assertEqual(fact_result, 120)
        fact_traces = [t for t in collector5.traces if t.func is factorial]
        self.assertEqual(len(fact_traces), 5)
        for fact_trace in fact_traces:
            self.assertEqual(fact_trace.arg_types, {'n': int})
        fact_returns = [t.return_type for t in fact_traces if t.return_type is not None]
        self.assertTrue(len(fact_returns) >= 1)
        self.assertEqual(fact_returns[0], int)

    def test_trace_context_manager(self):
        """The top-level monkeytype.trace() context manager works with a custom config."""
        from monkeytype.tracing import CallTraceLogger, CallTrace
        from monkeytype.config import Config
        from monkeytype.db.base import CallTraceStore, CallTraceStoreLogger
        import monkeytype

        traces_collected = []

        class InMemoryLogger(CallTraceLogger):
            def log(self, trace):
                traces_collected.append(trace)

        class TestConfig(Config):
            def trace_store(self):
                raise NotImplementedError
            def trace_logger(self):
                return InMemoryLogger()
            def code_filter(self):
                return None
            def max_typed_dict_size(self):
                return 0

        def multiply(a, b):
            return a * b

        with monkeytype.trace(config=TestConfig()):
            multiply(3, 4)

        self.assertTrue(len(traces_collected) >= 1)
        mul_traces = [t for t in traces_collected if t.func is multiply]
        self.assertEqual(len(mul_traces), 1)
        self.assertEqual(mul_traces[0].arg_types, {'a': int, 'b': int})
        self.assertEqual(mul_traces[0].return_type, int)

    def test_trace_generator_function(self):
        """Tracing a generator function records it and captures its argument
        types (not just that a trace object exists)."""
        from monkeytype.tracing import CallTraceLogger, trace_calls

        class Collector(CallTraceLogger):
            def __init__(self):
                self.traces = []
            def log(self, trace):
                self.traces.append(trace)
            def flush(self):
                pass

        def gen_ints(n):
            for i in range(n):
                yield i

        collector = Collector()
        with trace_calls(collector, max_typed_dict_size=0):
            list(gen_ints(3))

        gen_traces = [t for t in collector.traces if t.func.__name__ == 'gen_ints']
        self.assertTrue(len(gen_traces) >= 1)
        self.assertIs(gen_traces[0].func, gen_ints)
        # The generator's argument type is actually captured, so an
        # implementation that records the trace but drops arg types fails.
        self.assertEqual(gen_traces[0].arg_types, {'n': int})

    def test_trace_with_sample_rate(self):
        """sample_rate=1 captures every call, while sample_rate>1 probabilistically
        skips calls so strictly fewer than all of them are traced."""
        from monkeytype.tracing import CallTraceLogger, trace_calls

        class Collector(CallTraceLogger):
            def __init__(self):
                self.traces = []
            def log(self, trace):
                self.traces.append(trace)
            def flush(self):
                pass

        def inc(x):
            return x + 1

        # sample_rate=1 never skips: all calls are traced and arg types captured.
        collector = Collector()
        with trace_calls(collector, max_typed_dict_size=0, sample_rate=1):
            for i in range(5):
                inc(i)

        inc_traces = [t for t in collector.traces if t.func.__name__ == 'inc']
        self.assertEqual(len(inc_traces), 5)
        self.assertEqual(inc_traces[0].arg_types['x'], int)

        # sample_rate>1 must exercise the skip branch: over many calls, a sampling
        # implementation captures a proper subset (strictly fewer than every call).
        # An implementation that ignores sample_rate would trace all N and fail.
        # N is large enough that an all-traced or zero-traced outcome is
        # effectively impossible, so the assertion does not flake.
        N = 200
        sampled = Collector()
        with trace_calls(sampled, max_typed_dict_size=0, sample_rate=2):
            for i in range(N):
                inc(i)

        sampled_traces = [t for t in sampled.traces if t.func.__name__ == 'inc']
        self.assertGreater(len(sampled_traces), 0)
        self.assertLess(len(sampled_traces), N)
        self.assertEqual(sampled_traces[0].arg_types['x'], int)

    def test_call_trace_identity(self):
        """CallTrace supports equality, hashing, and funcname property."""
        from monkeytype.tracing import CallTrace

        t1 = CallTrace(func=_sample_add, arg_types={'x': int, 'y': int}, return_type=int)
        t2 = CallTrace(func=_sample_add, arg_types={'x': int, 'y': int}, return_type=int)
        t3 = CallTrace(func=_sample_add, arg_types={'x': str, 'y': int}, return_type=int)

        # Equal traces
        self.assertEqual(t1, t2)
        self.assertEqual(hash(t1), hash(t2))

        # Different traces
        self.assertNotEqual(t1, t3)

        # Dedup in sets: t1 == t2, so set should have 2 elements
        trace_set = {t1, t2, t3}
        self.assertEqual(len(trace_set), 2)

        # funcname property
        trace = CallTrace(func=_sample_add, arg_types={'x': int}, return_type=int)
        expected = _sample_add.__module__ + '.' + _sample_add.__qualname__
        self.assertEqual(trace.funcname, expected)


# ===========================================================================
# 2. Type encoding round-trips
# ===========================================================================
class TestEncodingIntegration(unittest.TestCase):
    """Serialize and deserialize types through JSON encoding, including
    complex generics and TypedDicts."""

    def test_encoding_round_trips(self):
        """Round-trip encoding for primitive/generic types and CallTrace-to-CallTraceRow
        serialization preserving all fields."""
        from monkeytype.encoding import type_to_json, type_from_json, CallTraceRow
        from monkeytype.tracing import CallTrace

        # Primitive and generic type round-trips
        test_types = [
            int, str, float, bool, type(None),
            List[int], Dict[str, int], Set[float],
            Tuple[int, str], Optional[int],
            List[Dict[str, int]],
            Dict[str, List[Tuple[int, float]]],
        ]
        for typ in test_types:
            encoded = type_to_json(typ)
            decoded = type_from_json(encoded)
            self.assertEqual(decoded, typ, f"Round-trip failed for {typ}")

        # CallTrace row round-trip
        trace = CallTrace(
            func=_sample_add,
            arg_types={'x': int, 'y': str},
            return_type=str,
            yield_type=None,
        )

        row = CallTraceRow.from_trace(trace)
        self.assertEqual(row.module, _sample_add.__module__)
        self.assertIn('_sample_add', row.qualname)

        restored = row.to_trace()
        self.assertEqual(restored.arg_types, {'x': int, 'y': str})
        self.assertEqual(restored.return_type, str)
        self.assertIs(restored.func, _sample_add)


# ===========================================================================
# 3. SQLite store integration
# ===========================================================================
class TestSQLiteStoreIntegration(unittest.TestCase):
    """Store traces in SQLite, retrieve them, verify filtering and dedup."""

    def test_store_operations(self):
        """Store and retrieve traces from SQLite; deduplicates identical traces;
        qualname_prefix filtering uses LIKE prefix matching."""
        from monkeytype.db.sqlite import SQLiteStore, create_call_trace_table
        from monkeytype.tracing import CallTrace

        conn = sqlite3.connect(":memory:")
        create_call_trace_table(conn)
        store = SQLiteStore(conn)

        # Store and retrieve
        trace = CallTrace(
            func=_sample_add,
            arg_types={'x': int, 'y': int},
            return_type=int,
        )

        store.add([trace])
        thunks = store.filter(module=_sample_add.__module__)
        self.assertTrue(len(thunks) >= 1)

        restored = thunks[0].to_trace()
        self.assertEqual(restored.arg_types, {'x': int, 'y': int})
        self.assertEqual(restored.return_type, int)

        # Deduplication: adding same trace 4x only returns 1 result
        conn2 = sqlite3.connect(":memory:")
        create_call_trace_table(conn2)
        store2 = SQLiteStore(conn2)

        trace2 = CallTrace(func=_sample_add, arg_types={'x': int, 'y': int}, return_type=int)
        store2.add([trace2, trace2, trace2, trace2])

        thunks2 = store2.filter(module=_sample_add.__module__,
                                qualname_prefix=_sample_add.__qualname__)
        self.assertEqual(len(thunks2), 1)

        # Qualname prefix filtering
        conn3 = sqlite3.connect(":memory:")
        create_call_trace_table(conn3)
        store3 = SQLiteStore(conn3)

        store3.add([
            CallTrace(func=_sample_add, arg_types={'x': int, 'y': int}, return_type=int),
            CallTrace(func=_sample_greet, arg_types={'name': str}, return_type=str),
        ])

        thunks3 = store3.filter(
            module=_sample_add.__module__,
            qualname_prefix=_sample_add.__qualname__,
        )
        self.assertEqual(len(thunks3), 1)

    def test_store_logger(self):
        """CallTraceStoreLogger stores traces for non-__main__ modules."""
        from monkeytype.db.base import CallTraceStoreLogger
        from monkeytype.db.sqlite import SQLiteStore, create_call_trace_table
        from monkeytype.tracing import CallTrace, trace_calls

        conn = sqlite3.connect(":memory:")
        create_call_trace_table(conn)
        store = SQLiteStore(conn)
        logger = CallTraceStoreLogger(store)

        # Trace a module-level function (not in __main__) so the persisted row
        # can be decoded back to a resolvable function via to_trace().
        with trace_calls(logger, max_typed_dict_size=0):
            _sample_add(3, 4)

        # Should have traces for our module
        thunks = store.filter(module=_sample_add.__module__,
                              qualname_prefix=_sample_add.__qualname__)
        self.assertTrue(len(thunks) >= 1)

        # The persisted trace round-trips with the correct captured types,
        # not just a row of the right shape.
        restored = thunks[0].to_trace()
        self.assertIs(restored.func, _sample_add)
        self.assertEqual(restored.arg_types, {'x': int, 'y': int})
        self.assertEqual(restored.return_type, int)


# ===========================================================================
# 4. End-to-end: trace → store → stub generation
# ===========================================================================
class TestTraceToStubPipeline(unittest.TestCase):
    """Full pipeline: trace functions, store, retrieve, generate stubs."""

    def test_trace_store_generate_stub(self):
        """Trace a module-level function, store in SQLite, retrieve, and
        generate a stub string containing the function with type annotations."""
        from monkeytype.tracing import CallTrace, trace_calls
        from monkeytype.db.sqlite import SQLiteStore, create_call_trace_table
        from monkeytype.db.base import CallTraceStoreLogger
        from monkeytype.stubs import build_module_stubs_from_traces
        from monkeytype.typing import NoOpRewriter

        conn = sqlite3.connect(":memory:")
        create_call_trace_table(conn)
        store = SQLiteStore(conn)
        logger = CallTraceStoreLogger(store)

        with trace_calls(logger, max_typed_dict_size=0):
            _sample_greet("world")
            _sample_greet("alice", greeting="hi")

        # Retrieve traces and build stubs
        thunks = store.filter(module=_sample_greet.__module__)
        traces = [t.to_trace() for t in thunks]
        self.assertTrue(len(traces) >= 1)

        stubs = build_module_stubs_from_traces(
            traces,
            max_typed_dict_size=0,
            existing_annotation_strategy=None,
            rewriter=NoOpRewriter(),
        )

        # Should have a stub for our module with the concretely inferred
        # signature (def _sample_greet(name: str, greeting: str = ...) -> str: ...).
        # Asserting 'name: str' (not just a bare 'str' token, which the return
        # annotation alone would satisfy) verifies the argument type was actually
        # inferred from the traced call.
        self.assertIn(_sample_greet.__module__, stubs)
        rendered = stubs[_sample_greet.__module__].render()
        self.assertIn('_sample_greet', rendered)
        self.assertIn('name: str', rendered)
        self.assertIn('-> str', rendered)

    def test_type_shrinking_across_multiple_traces(self):
        """Multiple traces with different types produce Union in the stub."""
        from monkeytype.tracing import CallTrace
        from monkeytype.stubs import build_module_stubs_from_traces
        from monkeytype.typing import NoOpRewriter

        traces = [
            CallTrace(func=_sample_flexible, arg_types={'x': int}, return_type=str),
            CallTrace(func=_sample_flexible, arg_types={'x': float}, return_type=str),
            CallTrace(func=_sample_flexible, arg_types={'x': str}, return_type=str),
        ]

        stubs = build_module_stubs_from_traces(
            traces,
            max_typed_dict_size=0,
            existing_annotation_strategy=None,
            rewriter=NoOpRewriter(),
        )

        rendered = stubs[_sample_flexible.__module__].render()
        self.assertIn('_sample_flexible', rendered)
        # The three observed argument types shrink to a Union carried by the
        # argument 'x' (def _sample_flexible(x: Union[...]) -> str). Assert the
        # Union is on the argument and contains all three members, order-independent
        # (Union member order is non-deterministic: it comes from set iteration). A
        # bare 'Union'/'str' check would be satisfied by a wrong-but-Union-shaped
        # argument type or by the '-> str' return alone.
        self.assertIn('x: Union[', rendered)
        for member in ('int', 'float', 'str'):
            self.assertIn(member, rendered)


# ===========================================================================
# 5. Type inference and rewriting
# ===========================================================================
class TestTypeInferenceIntegration(unittest.TestCase):
    """Test get_type for runtime values, shrink_types for merging, and
    type rewriters for normalization."""

    def test_get_type_all_values(self):
        """get_type correctly maps runtime values to their static types for
        primitives, containers, nested containers, callables, and tuples."""
        from monkeytype.typing import get_type
        from typing import Type, Any

        # Primitives
        self.assertEqual(get_type(42, 0), int)
        self.assertEqual(get_type("hello", 0), str)
        self.assertEqual(get_type(3.14, 0), float)
        self.assertEqual(get_type(True, 0), bool)
        self.assertEqual(get_type(None, 0), type(None))
        self.assertEqual(get_type(int, 0), Type[int])

        # Simple containers
        self.assertEqual(get_type([1, 2, 3], 0), List[int])
        self.assertEqual(get_type({1, 2}, 0), Set[int])
        self.assertEqual(get_type((1, "a"), 0), Tuple[int, str])
        self.assertEqual(get_type({"a": 1}, 0), Dict[str, int])

        # Empty containers
        self.assertEqual(get_type([], 0), List[Any])
        self.assertEqual(get_type({}, 0), Dict[Any, Any])

        # Nested containers
        self.assertEqual(get_type([{'a': 1}], 0), List[Dict[str, int]])
        self.assertEqual(get_type({'k': [1, 2]}, 0), Dict[str, List[int]])

        # Callables
        self.assertEqual(get_type(lambda x: x, 0), Callable)
        self.assertEqual(get_type(len, 0), Callable)

        # Tuples
        self.assertEqual(get_type((), 0), Tuple[()])
        self.assertEqual(get_type((1,), 0), Tuple[int])

    def test_type_shrinking_and_rewriting(self):
        """shrink_types produces minimal unions and Optional; DEFAULT_REWRITER
        normalizes Generator to Iterator and removes empty-container unions."""
        from monkeytype.typing import shrink_types, DEFAULT_REWRITER
        from typing import Generator, Any

        # shrink_types: dedup
        self.assertEqual(shrink_types({int, int}, 0), int)
        # shrink_types: Union
        result = shrink_types({int, str}, 0)
        self.assertEqual(result, Union[int, str])
        # shrink_types: Optional
        result = shrink_types({int, type(None)}, 0)
        self.assertEqual(result, Optional[int])
        # shrink_types: single type
        self.assertEqual(shrink_types({float}, 0), float)

        # Rewriter: Generator[int, None, None] -> Iterator[int]
        gen_type = Generator[int, None, None]
        rewritten = DEFAULT_REWRITER.rewrite(gen_type)
        self.assertEqual(rewritten, Iterator[int])

        # Rewriter: Generator with non-None send/return stays as Generator
        gen_type2 = Generator[int, str, float]
        rewritten2 = DEFAULT_REWRITER.rewrite(gen_type2)
        self.assertEqual(rewritten2, Generator[int, str, float])

        # Rewriter: removes empty-container types from Unions
        self.assertEqual(
            DEFAULT_REWRITER.rewrite(Union[List[int], List[Any]]),
            List[int],
        )
        self.assertEqual(
            DEFAULT_REWRITER.rewrite(Union[Dict[str, int], Dict[Any, Any]]),
            Dict[str, int],
        )
        self.assertEqual(
            DEFAULT_REWRITER.rewrite(Union[Set[int], Set[Any]]),
            Set[int],
        )
        # Non-container union stays unchanged
        self.assertEqual(
            DEFAULT_REWRITER.rewrite(Union[int, str]),
            Union[int, str],
        )


# ===========================================================================
# 6. Stub rendering (via the public CLI 'stub')
# ===========================================================================
class TestStubRendering(_CLITestBase):
    """Verify rendered stub text through the public 'monkeytype stub' surface:
    module-level function signatures (incl. nested generics), method-kind
    decorators, and class-stub indentation/sorting."""

    def test_function_stub_basic_rendering(self):
        """'monkeytype stub' renders module-level function signatures with the
        concretely inferred argument and return types, including a nested generic."""
        self._write("basic_mod.py", """\
            def add(a, b):
                return a + b

            def transform(items):
                return {"k": items}
        """)
        script = self._write("run_basic.py", """\
            from basic_mod import add, transform
            add(1, 2)
            transform([1, 2, 3])
        """)

        stub = self._run_and_stub(script, "basic_mod")
        # Simple inferred signature.
        self.assertIn('def add(a: int, b: int) -> int', stub)
        # Nested generic rendered exactly (not just the 'Dict'/'List' tokens), so a
        # mis-nested or partial render does not pass.
        self.assertIn('def transform(items: List[int]) -> Dict[str, List[int]]', stub)

    def test_function_stub_kind_decorators(self):
        """'monkeytype stub' renders @classmethod / @staticmethod / @property and
        'async def' for the corresponding method/function kinds."""
        self._write("kinds_mod.py", """\
            class Widget:
                def inst_method(self, x):
                    return str(x)
                @classmethod
                def make(cls, val):
                    return cls()
                @staticmethod
                def helper(n):
                    return n + 1
                @property
                def size(self):
                    return 3

            async def fetch(x):
                return str(x)
        """)
        script = self._write("run_kinds.py", """\
            import asyncio
            from kinds_mod import Widget, fetch
            w = Widget()
            w.inst_method(5)
            Widget.make("a")
            Widget.helper(2)
            _ = w.size
            asyncio.new_event_loop().run_until_complete(fetch(7))
        """)

        stub = self._run_and_stub(script, "kinds_mod")
        # Each method kind renders its decorator and inferred signature.
        self.assertIn('@classmethod', stub)
        self.assertIn('def make(cls, val: str)', stub)
        self.assertIn('@staticmethod', stub)
        self.assertIn('def helper(n: int) -> int', stub)
        self.assertIn('@property', stub)
        self.assertIn('def size(self)', stub)
        self.assertIn('def inst_method(self, x: int) -> str', stub)
        # Module-level async function renders with 'async def'.
        self.assertIn('async def fetch(x: int) -> str', stub)

    def test_class_stub_rendering(self):
        """'monkeytype stub' renders a class with its methods indented one level and
        sorted by name within the class body."""
        self._write("class_mod.py", """\
            class MyClass:
                def process(self, x):
                    return str(x)
                def absorb(self, n):
                    return n + 1
        """)
        script = self._write("run_class.py", """\
            from class_mod import MyClass
            m = MyClass()
            m.process(5)
            m.absorb(2)
        """)

        stub = self._run_and_stub(script, "class_mod")
        # Class header plus methods indented inside the body.
        self.assertIn('class MyClass:', stub)
        self.assertIn('    def process(self, x: int) -> str', stub)
        self.assertIn('    def absorb(self, n: int) -> int', stub)
        # Methods are emitted in sorted order: 'absorb' before 'process'.
        self.assertLess(stub.index('def absorb'), stub.index('def process'))


# ===========================================================================
# 6a. Stubs built from introspected function definitions (no traces)
# ===========================================================================
class TestStubsFromDefinitions(unittest.TestCase):
    """Build stubs from FunctionDefinitions introspected off live callables —
    the non-trace stub path, which reads each callable's own signature instead
    of merging recorded types."""

    def test_build_module_stubs_from_callables(self):
        """FunctionDefinition.from_callable introspects a callable's signature and
        build_module_stubs renders those definitions into a per-module stub."""
        from monkeytype.stubs import FunctionDefinition, build_module_stubs

        stubs = build_module_stubs([
            FunctionDefinition.from_callable(_sample_add),
            FunctionDefinition.from_callable(_partially_annotated),
            FunctionDefinition.from_callable(_fully_annotated),
        ])

        self.assertIn(_sample_add.__module__, stubs)
        rendered = stubs[_sample_add.__module__].render()
        # An unannotated function keeps its parameter names and gains no annotations.
        self.assertIn('def _sample_add(x, y)', rendered)
        # Annotations already present on the callable are carried into the stub.
        self.assertIn('def _partially_annotated(x: int, y)', rendered)
        self.assertIn('def _fully_annotated(x: int) -> str', rendered)


# ===========================================================================
# 6b. ExistingAnnotationStrategy
# ===========================================================================
class TestExistingAnnotationStrategy(unittest.TestCase):
    """Test how ExistingAnnotationStrategy controls interaction between
    traced types and pre-existing annotations."""

    def test_existing_annotation_strategies(self):
        """REPLICATE preserves existing annotations, IGNORE replaces them with
        traced types, OMIT drops already-annotated params; all three produce
        different output for the same traces."""
        from monkeytype.tracing import CallTrace
        from monkeytype.stubs import build_module_stubs_from_traces, ExistingAnnotationStrategy
        from monkeytype.typing import NoOpRewriter

        traces_partial = [CallTrace(func=_partially_annotated, arg_types={'x': float, 'y': str}, return_type=str)]

        # REPLICATE
        stubs = build_module_stubs_from_traces(
            traces_partial, max_typed_dict_size=0,
            existing_annotation_strategy=ExistingAnnotationStrategy.REPLICATE,
            rewriter=NoOpRewriter(),
        )
        rendered_rep = list(stubs.values())[0].render()
        self.assertIn('x: int', rendered_rep)
        self.assertIn('y: str', rendered_rep)
        self.assertIn('-> str', rendered_rep)

        # IGNORE
        stubs = build_module_stubs_from_traces(
            traces_partial, max_typed_dict_size=0,
            existing_annotation_strategy=ExistingAnnotationStrategy.IGNORE,
            rewriter=NoOpRewriter(),
        )
        rendered_ign = list(stubs.values())[0].render()
        self.assertIn('x: float', rendered_ign)
        self.assertIn('y: str', rendered_ign)

        # OMIT
        stubs = build_module_stubs_from_traces(
            traces_partial, max_typed_dict_size=0,
            existing_annotation_strategy=ExistingAnnotationStrategy.OMIT,
            rewriter=NoOpRewriter(),
        )
        rendered_omit = list(stubs.values())[0].render()
        self.assertNotIn('x: int', rendered_omit)
        self.assertNotIn('x: float', rendered_omit)
        self.assertIn('y: str', rendered_omit)

        # All three strategies produce different output for fully-annotated function
        traces_full = [CallTrace(func=_fully_annotated, arg_types={'x': float}, return_type=str)]
        outputs = {}
        for strategy in ExistingAnnotationStrategy:
            stubs = build_module_stubs_from_traces(
                traces_full, max_typed_dict_size=0,
                existing_annotation_strategy=strategy,
                rewriter=NoOpRewriter(),
            )
            outputs[strategy.name] = list(stubs.values())[0].render()

        self.assertIn('x: int', outputs['REPLICATE'])
        self.assertIn('x: float', outputs['IGNORE'])
        self.assertNotIn('x: int', outputs['OMIT'])
        self.assertNotIn('x: float', outputs['OMIT'])


# ===========================================================================
# 7. CLI integration via subprocess
# ===========================================================================
class TestCLIIntegration(unittest.TestCase):
    """Test the monkeytype CLI: run, stub, apply, list-modules."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "mt.sqlite3")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir)

    def _write_file(self, name, content):
        path = os.path.join(self.tmpdir, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            f.write(textwrap.dedent(content))
        return path

    def test_cli_run_and_stub(self):
        """Use 'monkeytype run' to trace scripts, then 'monkeytype stub' to
        generate type stubs; also verify multiple types produce Union stubs."""
        # Create a target module
        self._write_file("target_mod.py", """\
            def add(a, b):
                return a + b

            def greet(name):
                return "hello " + name
        """)

        # Create a script that exercises the module
        script = self._write_file("run_script.py", """\
            from target_mod import add, greet
            add(1, 2)
            add(3, 4)
            greet("world")
        """)

        env = os.environ.copy()
        env['MT_DB_PATH'] = self.db_path

        # Run tracing
        result = subprocess.run(
            [sys.executable, "-m", "monkeytype", "run", script],
            capture_output=True, text=True, cwd=self.tmpdir, env=env,
        )
        self.assertEqual(result.returncode, 0, f"run failed: {result.stderr}")
        self.assertTrue(os.path.exists(self.db_path))

        # Generate stub
        result = subprocess.run(
            [sys.executable, "-m", "monkeytype", "stub", "target_mod"],
            capture_output=True, text=True, cwd=self.tmpdir, env=env,
        )
        self.assertEqual(result.returncode, 0, f"stub failed: {result.stderr}")
        stub_output = result.stdout
        # Assert the concretely inferred signatures the CLI must emit, so that
        # argument-type inference (not just return types) is verified end-to-end.
        # A bare 'int'/'str' token check would pass on a stub that infers returns
        # but drops or mis-infers the argument types.
        self.assertIn('def add(a: int, b: int) -> int', stub_output)
        self.assertIn('def greet(name: str) -> str', stub_output)

        # --- Also test multiple types producing Union stubs ---
        self._write_file("multi_type.py", """\
            def process(x):
                return str(x)
        """)
        script2 = self._write_file("run_multi.py", """\
            from multi_type import process
            process(1)
            process("hello")
            process(3.14)
        """)

        db_path2 = os.path.join(self.tmpdir, "mt2.sqlite3")
        env2 = os.environ.copy()
        env2['MT_DB_PATH'] = db_path2

        subprocess.run(
            [sys.executable, "-m", "monkeytype", "run", script2],
            capture_output=True, text=True, cwd=self.tmpdir, env=env2,
        )

        result2 = subprocess.run(
            [sys.executable, "-m", "monkeytype", "stub", "multi_type"],
            capture_output=True, text=True, cwd=self.tmpdir, env=env2,
        )
        self.assertEqual(result2.returncode, 0, f"stub failed: {result2.stderr}")
        # Tracing process(x) over int/str/float must infer the argument annotation
        # def process(x: Union[int, float, str]) -> str. Assert the Union is on the
        # argument and contains all three members, order-independent (inferred Union
        # member order is not stable). A bare 'Union' substring would pass on a
        # wrong-but-Union-shaped argument type.
        self.assertIn('process(x: Union[', result2.stdout)
        for member in ('int', 'float', 'str'):
            self.assertIn(member, result2.stdout)

    def test_cli_apply_and_list(self):
        """Use 'monkeytype apply' to add annotations to source and
        'monkeytype list-modules' to list traced modules."""
        # --- apply ---
        self._write_file("apply_target.py", """\
            def double(x):
                return x * 2
        """)

        script = self._write_file("run_apply.py", """\
            from apply_target import double
            double(5)
            double(10)
        """)

        env = os.environ.copy()
        env['MT_DB_PATH'] = self.db_path

        subprocess.run(
            [sys.executable, "-m", "monkeytype", "run", script],
            capture_output=True, text=True, cwd=self.tmpdir, env=env,
        )

        result = subprocess.run(
            [sys.executable, "-m", "monkeytype", "apply", "apply_target"],
            capture_output=True, text=True, cwd=self.tmpdir, env=env,
        )
        self.assertEqual(result.returncode, 0, f"apply failed: {result.stderr}")

        with open(os.path.join(self.tmpdir, "apply_target.py")) as f:
            modified = f.read()
        # Pin the exact inferred-and-applied signature: tracing double(5)/double(10)
        # over 'def double(x): return x * 2' must annotate both the argument and the
        # return as int. A bare 'int' substring would match many wrong-but-right-shaped
        # outputs (e.g. a return-only annotation, or 'int' appearing anywhere).
        self.assertIn('def double(x: int) -> int:', modified)

        # --- list-modules ---
        self._write_file("list_target.py", """\
            def noop():
                pass
        """)
        script2 = self._write_file("run_list.py", """\
            from list_target import noop
            noop()
        """)

        subprocess.run(
            [sys.executable, "-m", "monkeytype", "run", script2],
            capture_output=True, text=True, cwd=self.tmpdir, env=env,
        )

        result2 = subprocess.run(
            [sys.executable, "-m", "monkeytype", "list-modules"],
            capture_output=True, text=True, cwd=self.tmpdir, env=env,
        )
        self.assertEqual(result2.returncode, 0)
        self.assertIn('list_target', result2.stdout)


# ===========================================================================
# 8. StubIndexBuilder — trace logger that builds stubs
# ===========================================================================
class TestStubIndexBuilder(unittest.TestCase):
    """StubIndexBuilder: a CallTraceLogger that collects traces and builds
    a stub index filtered by module regex."""

    def test_stub_index_builder_filters_by_module(self):
        """StubIndexBuilder includes only traces whose funcname matches the
        regex, excludes non-matching ones, and renders a stub for the match."""
        from monkeytype.stubs import StubIndexBuilder
        from monkeytype.tracing import trace_calls

        # Regex matches _sample_add's funcname (module.qualname) but not
        # _sample_greet's, so filtering must keep one and drop the other.
        builder = StubIndexBuilder(
            module_re=r'.*\._sample_add$',
            max_typed_dict_size=0,
        )

        with trace_calls(builder, max_typed_dict_size=0):
            _sample_add(1, 2)
            _sample_greet("world")

        stubs = builder.get_stubs()
        # The matching function's module is present...
        self.assertIn(_sample_add.__module__, stubs)
        rendered = stubs[_sample_add.__module__].render()
        self.assertIn('_sample_add', rendered)
        # ...while the non-matching function was filtered out entirely.
        self.assertNotIn('_sample_greet', rendered)


# ===========================================================================
# 9. Config system
# ===========================================================================
class TestConfigIntegration(unittest.TestCase):
    """Config: DefaultConfig creates SQLite store, code filter excludes stdlib."""

    def test_config_defaults(self):
        """default_code_filter excludes stdlib; DefaultConfig.trace_store() creates a SQLiteStore."""
        from monkeytype.config import default_code_filter, DefaultConfig
        from monkeytype.db.sqlite import SQLiteStore
        import sysconfig

        # stdlib code is excluded
        self.assertFalse(default_code_filter(sysconfig.get_path.__code__))

        # DefaultConfig creates SQLiteStore
        tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(tmpdir, "test.sqlite3")
        os.environ['MT_DB_PATH'] = db_path
        try:
            config = DefaultConfig()
            store = config.trace_store()
            self.assertIsInstance(store, SQLiteStore)
        finally:
            os.environ.pop('MT_DB_PATH', None)
            import shutil
            shutil.rmtree(tmpdir)


# ===========================================================================
# 10. Exceptions
# ===========================================================================
class TestExceptions(unittest.TestCase):
    """Exception hierarchy and error handling in encoding."""

    def test_exception_handling(self):
        """type_from_json raises a MonkeyType/value error on malformed input."""
        from monkeytype.encoding import type_to_json, type_from_json
        from monkeytype.exceptions import MonkeyTypeError

        # Invalid JSON raises a JSON or MonkeyType error
        with self.assertRaises((ValueError, KeyError, MonkeyTypeError)):
            type_from_json("not valid json")

        # Empty/garbage dict raises a lookup or type error
        with self.assertRaises((ValueError, KeyError, MonkeyTypeError)):
            type_from_json('{"garbage": true}')


# ===========================================================================
# 11. TYPE_CHECKING import relocation ('monkeytype apply --pep_563')
# ===========================================================================
class TestTypeCheckingApply(_CLITestBase):
    """'monkeytype apply --pep_563' relocates newly-introduced annotation imports
    into an if TYPE_CHECKING: block."""

    def test_apply_pep_563_moves_imports_to_type_checking_block(self):
        """When the inferred annotations reference a class from another module,
        'apply --pep_563' adds 'from typing import TYPE_CHECKING' and moves the new
        import into the guarded block instead of leaving it at module top level."""
        # A separate module supplies a custom class so the inferred signature
        # references an import that did not previously exist in the target source.
        self._write("thing_mod.py", """\
            class Thing:
                pass
        """)
        self._write("uses_thing.py", """\
            def make_thing(t):
                return t
        """)
        script = self._write("run_thing.py", """\
            from thing_mod import Thing
            from uses_thing import make_thing
            make_thing(Thing())
        """)

        modified = self._run_and_apply(script, "uses_thing", "uses_thing.py", "--pep_563")

        # TYPE_CHECKING is imported and a guarded block exists.
        self.assertIn('from typing import TYPE_CHECKING', modified)
        self.assertIn('if TYPE_CHECKING:', modified)
        # The annotation was applied to the function.
        self.assertIn('def make_thing(t: Thing) -> Thing:', modified)

        # The newly-introduced import is moved *inside* the block (indented), and
        # is no longer present at module top level.
        before_block, _, block = modified.partition('if TYPE_CHECKING:')
        self.assertIn('    from thing_mod import Thing', block)
        self.assertNotIn('from thing_mod import Thing', before_block)


if __name__ == '__main__':
    unittest.main()
