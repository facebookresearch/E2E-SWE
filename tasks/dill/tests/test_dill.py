"""
Tests for dill — extended pickle serialization library.

Each test exercises a distinct user-facing behavior. Tests are consolidated
so that each piece of implementation work is credited exactly once.
"""

import contextlib
import functools
import io
import os
import sys
import tempfile
import threading
import types
from collections import defaultdict
from dataclasses import dataclass, field

import pytest


def _roundtrip(obj, **kwargs):
    """Serialize with dill.dumps() then deserialize with dill.loads()."""
    import dill
    return dill.loads(dill.dumps(obj, **kwargs))


# ============================================================
# 1. Function/closure dispatch (one comprehensive test)
# ============================================================


class TestFunctionDispatch:
    """Consolidated function dispatch tests — one per distinct path."""

    def test_function_closure_generator_decorator(self):
        """Lambda, closure with mutation, decorator, and generator in one workflow."""
        import dill

        def make_transform(scale):
            offset = [0]
            def transform(x, bias=1):
                offset[0] += 1
                return x * scale + bias + offset[0]
            return transform

        t = make_transform(3)
        t(0)  # offset becomes 1
        t(0)  # offset becomes 2

        result = _roundtrip(t)
        assert result(10, bias=0) == 33  # 10*3 + 0 + 3

        def logged(fn):
            @functools.wraps(fn)
            def wrapper(*args, **kwargs):
                return fn(*args, **kwargs)
            return wrapper

        def make_range(start):
            @logged
            def gen(stop):
                n = start
                while n < stop:
                    yield n
                    n += 1
            return gen

        g = make_range(5)
        result_gen = _roundtrip(g)
        assert list(result_gen(8)) == [5, 6, 7]

    def test_recursive_function(self):
        """Recursive function that references itself in globals."""
        def factorial(n):
            if n <= 1:
                return 1
            return n * factorial(n - 1)

        result = _roundtrip(factorial)
        assert result(5) == 120


# ============================================================
# 2. Function metadata
# ============================================================


class TestFunctionMetadata:
    """Function attribute and mode tests."""

    def test_kwdefaults_annotations_and_recurse(self):
        """kwdefaults, annotations preserved; recurse=True captures globals."""
        import dill

        def greet(name, *, greeting: str = "Hello", punct: str = "!") -> str:
            return f"{greeting}, {name}{punct}"

        result = _roundtrip(greet)
        assert result("World") == "Hello, World!"
        assert result.__kwdefaults__ == {"greeting": "Hello", "punct": "!"}
        assert result.__annotations__ == {"greeting": str, "punct": str, "return": str}

        MULTIPLIER = 7
        def multiply(x):
            return x * MULTIPLIER
        result2 = dill.loads(dill.dumps(multiply, recurse=True))
        assert result2(6) == 42

    def test_function_with_dict_attributes(self):
        """Function with custom __dict__ attributes preserved."""
        import dill

        def worker(x):
            return x + worker.offset

        worker.offset = 10
        worker.metadata = {"version": 2}

        result = _roundtrip(worker)
        assert result.offset == 10
        assert result.metadata == {"version": 2}
        assert result(5) == 15


# ============================================================
# 3. Class type dispatch
# ============================================================


class TestClassDispatch:
    """Each test exercises a distinct class dispatch path."""

    def test_dynamic_class_hierarchy(self):
        """Multi-level type()-created class hierarchy with methods."""
        import dill

        Base = type("Base", (object,), {"kind": lambda self: "base"})
        Child = type("Child", (Base,), {
            "__init__": lambda self, v: setattr(self, 'v', v),
            "kind": lambda self: f"child-{self.v}",
        })

        result_cls = _roundtrip(Child)
        obj = result_cls(42)
        assert obj.kind() == "child-42"

    def test_class_with_methods_and_classmethod(self):
        """Locally-defined class with instance, class, and static methods."""
        import dill

        class Toolkit:
            name = "tools"

            def __init__(self, x):
                self.x = x

            def compute(self):
                return self.x * 2

            @classmethod
            def get_name(cls):
                return cls.name

            @staticmethod
            def helper(x):
                return x + 1

        result_cls = _roundtrip(Toolkit)
        obj = result_cls(5)
        assert obj.compute() == 10
        assert result_cls.get_name() == "tools"
        assert result_cls.helper(3) == 4

    def test_class_with_slots(self):
        """Class with __slots__ — both class and instance round-trip."""
        import dill

        class Coord:
            __slots__ = ("x", "y", "z")
            def __init__(self, x, y, z):
                self.x = x
                self.y = y
                self.z = z
            def magnitude(self):
                return (self.x**2 + self.y**2 + self.z**2) ** 0.5

        result_cls = _roundtrip(Coord)
        p = result_cls(3, 4, 0)
        assert p.magnitude() == 5.0

        obj = Coord(1, 2, 3)
        result_inst = dill.loads(dill.dumps(obj))
        assert (result_inst.x, result_inst.y, result_inst.z) == (1, 2, 3)

    def test_abc_with_concrete_subclass(self):
        """ABCMeta class with abstract methods and concrete subclass."""
        import dill
        from abc import ABCMeta, abstractmethod

        class Shape(metaclass=ABCMeta):
            @abstractmethod
            def area(self):
                pass

        class Circle(Shape):
            def __init__(self, r):
                self.r = r
            def area(self):
                return 3.14159 * self.r ** 2

        result_cls = _roundtrip(Circle)
        assert abs(result_cls(5).area() - 78.5398) < 0.01

    def test_class_inheriting_builtin(self):
        """Class inheriting from a builtin type round-trips."""
        import dill

        class NamedList(list):
            def __init__(self, name, *args):
                super().__init__(*args)
                self.name = name

        obj = NamedList("mylist", [1, 2, 3])
        result = _roundtrip(obj)
        assert list(result) == [1, 2, 3]
        assert result.name == "mylist"


# ============================================================
# 4. Exotic type reducers
# ============================================================


class TestExoticTypeReducers:
    """Types requiring specific custom reducers."""

    def test_file_handle(self):
        """Open file handle round-trips with content preserved."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("dill test content")
            tmp_path = f.name
        try:
            fh = open(tmp_path, "r")
            result = _roundtrip(fh)
            fh.close()
            assert result.read() == "dill test content"
            result.close()
        finally:
            os.unlink(tmp_path)

    def test_dict_views(self):
        """dict_keys, dict_values, dict_items all round-trip."""
        d = {"a": 1, "b": 2, "c": 3}
        assert sorted(_roundtrip(d.keys())) == ["a", "b", "c"]
        assert sorted(_roundtrip(d.values())) == [1, 2, 3]
        assert sorted(_roundtrip(d.items())) == [("a", 1), ("b", 2), ("c", 3)]

    def test_property_with_getter_and_setter(self):
        """property with fget, fset, and fdel all round-trips."""
        import dill
        prop = property(
            fget=lambda self: self._val,
            fset=lambda self, v: setattr(self, '_val', v),
            fdel=lambda self: setattr(self, '_val', None),
        )
        result = dill.loads(dill.dumps(prop))
        cls = type("Obj", (object,), {"val": result})
        obj = cls()
        obj.val = 99
        assert obj.val == 99

    def test_lock_roundtrip(self):
        """Threading Lock preserves locked state."""
        import dill
        lock = threading.Lock()
        lock.acquire()
        result = dill.loads(dill.dumps(lock))
        assert not result.acquire(blocking=False)
        result.release()
        lock.release()

    def test_rlock_roundtrip(self):
        """Threading RLock preserves reentrant acquisition count."""
        import dill
        rlock = threading.RLock()
        rlock.acquire()
        rlock.acquire()
        result = dill.loads(dill.dumps(rlock))
        result.release()
        result.release()
        assert result.acquire(blocking=False)
        result.release()
        rlock.release()
        rlock.release()

    def test_lru_cache_roundtrip(self):
        """@lru_cache preserves cache_parameters including maxsize and typed."""
        import dill

        @functools.lru_cache(maxsize=64, typed=True)
        def square(x):
            return x * x

        square(3)
        result = _roundtrip(square)
        assert result(4) == 16
        params = result.cache_parameters()
        assert params["maxsize"] == 64
        assert params["typed"] is True

    def test_super_object(self):
        """super() object round-trips and delegates correctly."""
        import dill

        class Base:
            def method(self):
                return "base"
        class Child(Base):
            def method(self):
                return "child"

        s = super(Child, Child())
        result = dill.loads(dill.dumps(s))
        assert result.method() == "base"

    def test_staticmethod_and_classmethod_descriptors(self):
        """Bare staticmethod and classmethod descriptors round-trip with their wrapped functions."""
        import dill

        sm = staticmethod(lambda x: x * 3)
        sm_result = dill.loads(dill.dumps(sm))
        assert sm_result.__func__(7) == 21

        cm = classmethod(lambda cls: cls.__name__)
        cm_result = dill.loads(dill.dumps(cm))
        assert isinstance(cm_result, classmethod)
        cls = type("C", (object,), {"__name__": "C"})
        assert cm_result.__func__(cls) == "C"

    def test_operator_getters_on_dataclass(self):
        """operator.itemgetter / attrgetter round-trip and a dataclass preserves its fields."""
        import operator

        @dataclass
        class Point:
            x: int
            y: int
            tags: list = field(default_factory=list)

        get_x = operator.attrgetter("x")
        assert _roundtrip(get_x)(Point(3, 4)) == 3

        get_first = operator.itemgetter(0)
        assert _roundtrip(get_first)([10, 20, 30]) == 10

        p = Point(1, 2, tags=["a", "b"])
        result = _roundtrip(p)
        assert (result.x, result.y, result.tags) == (1, 2, ["a", "b"])

    def test_mapping_proxy(self):
        """types.MappingProxyType round-trips."""
        proxy = types.MappingProxyType({"a": 1, "b": 2})
        result = _roundtrip(proxy)
        assert isinstance(result, types.MappingProxyType)
        assert dict(result) == {"a": 1, "b": 2}

    def test_code_object(self):
        """Code object from compile() round-trips with fields preserved."""
        code = compile("x = 1 + 2", "<test>", "exec")
        result = _roundtrip(code)
        assert result.co_filename == "<test>"
        ns = {}
        exec(result, ns)
        assert ns["x"] == 3

    def test_weakref_in_container(self):
        """weakref.ref inside a container round-trips with live referent."""
        import dill
        import weakref

        class Target:
            def __init__(self, v):
                self.value = v

        obj = Target(42)
        data = {"target": obj, "ref": weakref.ref(obj)}
        result = dill.loads(dill.dumps(data))
        assert result["ref"]() is not None
        assert result["ref"]().value == 42


# ============================================================
# 5. Settings, extension, and pickleability
# ============================================================


class TestSettingsAndExtension:
    """Tests for dill.settings, dill.extend, dill.pickles, dill.check."""

    def test_pickles_exact_mode(self):
        """dill.pickles exact=True rejects objects whose round-trip is not == equal."""
        import dill

        # A lambda serializes fine (default mode => True) but the restored lambda is
        # never == the original, so exact mode must reject it. This is the only behavior
        # unique to exact=True; an equality-comparable object passes both modes.
        f = lambda x: x + 1  # noqa: E731
        assert dill.pickles(f) is True
        assert dill.pickles(f, exact=True) is False
        assert dill.pickles([1, 2, 3], exact=True) is True

    def test_extend_and_revert(self):
        """dill.extend(False) removes dill types from the stock pickle registry; extend(True) restores."""
        import io
        import pickle

        import dill

        # extend() mutates the *stock* pickle dispatch table, so verify it
        # there (via the pure-Python pickler, whose dispatch extend() targets)
        # rather than through dill's own Pickler, which is independent of it.
        def stock_dumps(obj):
            buf = io.BytesIO()
            pickle._Pickler(buf).dump(obj)
            return buf.getvalue()

        f = lambda x: x + 1
        try:
            dill.extend(True)
            stock_dumps(f)  # stock pickle can now serialize a lambda via dill's reducer
            dill.extend(False)
            with pytest.raises(pickle.PicklingError):
                stock_dumps(f)  # reducer removed -> stock pickle cannot handle a lambda
        finally:
            dill.extend(True)  # leave the dispatch table extended (the import-time default)
        stock_dumps(f)  # restored: serializable again

    def test_check_roundtrip(self):
        """dill.check verifies an object survives cross-process round-trip."""
        import dill

        # check() does the real round-trip in a subprocess and, with verbose=True,
        # prints "SUCCESS" (or "LOAD FAILED") at the Python level once it returns.
        # Asserting "SUCCESS" pins the actual cross-process outcome: a check() that
        # skipped or failed the subprocess load would print "LOAD FAILED" instead.
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            result = dill.check([1, 2, 3], verbose=True)
        assert "SUCCESS" in out.getvalue()
        assert "LOAD FAILED" not in out.getvalue()
        assert result is None  # check() prints its result and returns None


# ============================================================
# 6. Session save/restore
# ============================================================


class TestSession:
    """Tests for dill session management."""

    def test_dump_and_load_module_with_closures(self):
        """Save and restore a module namespace containing closures."""
        import dill

        mod = types.ModuleType("test_mod")
        mod.x = 42
        mod.data = [1, 2, 3]
        mod.add5 = (lambda n: (lambda x: x + n))(5)

        with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as f:
            tmp = f.name
        try:
            dill.dump_module(tmp, module=mod)
            fresh = types.ModuleType("test_mod")
            dill.load_module(tmp, module=fresh)
            assert fresh.x == 42
            assert fresh.data == [1, 2, 3]
            assert fresh.add5(10) == 15
        finally:
            os.unlink(tmp)

    def test_load_module_asdict(self):
        """load_module_asdict loads a saved module's namespace into a plain dict."""
        import dill

        with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as f:
            tmp = f.name
        # Save a controlled module namespace (like the sibling test above) rather than the
        # live __main__: under a test runner __main__ holds arbitrary ambient runtime objects
        # the test never sets, and load_module_asdict resolves the target module by the name
        # recorded in the file, so a module registered in sys.modules round-trips cleanly.
        mod = types.ModuleType("test_session_mod")
        mod._test_val = 99
        # Bindings to objects that are reachable by name from another module must stay
        # by reference, while a function defined *in* the saved module makes the namespace
        # self-referential (its __globals__ is the very dict being saved).
        mod.joiner = os.path.join
        mod.Holder = types.SimpleNamespace
        exec("def countdown(n):\n    return 0 if n <= 0 else 1 + countdown(n - 1)\n", mod.__dict__)
        sys.modules["test_session_mod"] = mod
        try:
            dill.dump_module(tmp, module=mod)
            result = dill.session.load_module_asdict(tmp)
            assert isinstance(result, dict)
            assert result["_test_val"] == 99
            assert result["joiner"] is os.path.join
            assert result["Holder"] is types.SimpleNamespace
            assert result["countdown"](3) == 3
        finally:
            sys.modules.pop("test_session_mod", None)
            os.unlink(tmp)


# ============================================================
# 7. Source and detect (consolidated)
# ============================================================


class TestSourceAndDetect:
    """Source inspection and detect diagnostics — consolidated."""

    def test_source_inspection(self):
        """getsource returns source; importable returns executable code."""
        from dill.source import getsource, importable

        f = lambda x: x ** 2 + 1
        src = getsource(f)
        assert "lambda" in src and "x ** 2" in src

        imp = importable(len)
        assert "len" in imp
        ns = {}
        exec(imp, ns)
        assert ns["len"] is len

    def test_detect_diagnostics(self):
        """globalvars extracts globals; nestedcode finds nested code; baditems works."""
        from dill.detect import globalvars, nestedcode, baditems

        ns = {"FACTOR": 7}
        exec("def compute(x): return x * FACTOR", ns)
        assert globalvars(ns["compute"])["FACTOR"] == 7

        def outer():
            def inner():
                return 42
            return inner
        assert any(c.co_name == "inner" for c in nestedcode(outer))

        assert baditems([1, "hello", [2, 3]]) == []


# ============================================================
# 8. Integration (consolidated)
# ============================================================


class TestIntegration:
    """Integration tests combining multiple dispatch features."""

    def test_complex_integration(self):
        """Dynamic class with closure attrs, partial of closure, instance with closure."""
        import dill

        multiplier = 3
        cls = type("Processor", (object,), {
            "transform": lambda self, x: x * multiplier,
            "name": "proc",
        })
        result_cls = dill.loads(dill.dumps(cls))
        assert result_cls().transform(4) == 12

        def make_mul(factor):
            def mul(x, offset=0):
                return x * factor + offset
            return mul

        p = functools.partial(make_mul(3), offset=10)
        result_p = _roundtrip(p)
        assert result_p(5) == 25

    def test_defaultdict_with_nested_lambda(self):
        """defaultdict with lambda factory, including nested default."""
        dd = defaultdict(lambda: defaultdict(list))
        dd["users"]["admin"].append("root")
        result = _roundtrip(dd)
        assert result["users"]["admin"] == ["root"]
        assert result["new"]["sub"] == []
