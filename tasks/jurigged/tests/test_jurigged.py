"""End-to-end tests for the jurigged live-code-reloading library.

Each test models a realistic live-coding workflow: define a module, then redefine
parts of it *while it is running* and assert that the already-existing objects
(functions, classes, instances, closures, captured references) pick up the new
behaviour in place. Patches are driven through the public API; the only filesystem
interaction is editing a file on disk and asking jurigged to reload it (via the
``Watcher``/``CodeFile`` refresh path) — the background watchdog observer thread is
never started, so every test is deterministic and in-process.
"""

import asyncio
import gc
import importlib
import linecache
import sys
import textwrap
import types
from itertools import count

import pytest

# Public facade: everything below is importable from the top-level package.
from jurigged import (
    Watcher,
    glob_filter,
    make_recoder,
    registry,
    virtual_file,
    watch,
)
from jurigged.recode import OutOfSyncException
from jurigged.rescript import redirect, redirect_code

_counter = count()


def _make_module(tmp_path, source):
    """Write `source` to a uniquely-named module under tmp_path; import and return it."""
    name = f"jtest_mod_{next(_counter)}"
    path = tmp_path / f"{name}.py"
    path.write_text(textwrap.dedent(source))
    sys.path.insert(0, str(tmp_path))
    importlib.invalidate_caches()
    try:
        return importlib.import_module(name)
    finally:
        sys.path.remove(str(tmp_path))


def _rewrite(module, source):
    """Overwrite a module's source file on disk (simulates an external editor)."""
    with open(module.__file__, "w") as f:
        f.write(textwrap.dedent(source))


# ----------------------------------------------------------------------------
# Core in-place redefinition
# ----------------------------------------------------------------------------
def test_live_function_redefinition_preserves_references(tmp_path):
    """Redefining a function reroutes it in place for every held reference, identity intact."""
    mod = _make_module(
        tmp_path,
        """
        def scale(x):
            return x * 2
        """,
    )
    # Capture the function through several independent live pointers before patching.
    saved_ref = mod.scale
    alias = mod.scale
    container = [mod.scale]

    def caller(fn=mod.scale):
        return fn(5)  # binds the original as a default argument

    assert mod.scale(5) == 10
    assert saved_ref(5) == 10 and alias(5) == 10 and container[0](5) == 10 and caller() == 10

    make_recoder(mod.scale).patch("def scale(x):\n    return x * 100\n")
    # Rerouted in place: identity is preserved and EVERY existing pointer — the bound
    # name, a captured reference, a plain alias, a container entry, a captured default —
    # observes the new behaviour without being rebound.
    assert saved_ref is mod.scale and alias is mod.scale and container[0] is mod.scale
    assert mod.scale(5) == 500
    assert saved_ref(5) == 500
    assert alias(5) == 500
    assert container[0](5) == 500
    assert caller() == 500

    # A recoder addressed by a function's code object reaches that function.
    mod2 = _make_module(tmp_path, "def grow(x):\n    return x + 1\n")
    grow_ref = mod2.grow
    make_recoder(mod2.grow.__code__).patch("def grow(x):\n    return x + 1000\n")
    assert mod2.grow(5) == 1005
    assert grow_ref is mod2.grow


def test_method_and_class_redefinition_update_live_instances(tmp_path):
    """Redefining a method, then a whole class, updates already-built instances."""
    mod = _make_module(
        tmp_path,
        """
        class Counter:
            def __init__(self, start):
                self.value = start

            def step(self):
                return self.value + 1
        """,
    )
    inst = mod.Counter(10)
    original_class = mod.Counter
    assert inst.step() == 11

    make_recoder(mod.Counter.step).patch(
        "def step(self):\n    return self.value + 100\n"
    )
    assert inst.step() == 110

    make_recoder(mod.Counter).patch(
        textwrap.dedent(
            """
            class Counter:
                def __init__(self, start):
                    self.value = start

                def step(self):
                    return self.value + 1

                def double(self):
                    return self.value * 2
            """
        )
    )
    # The class object is updated in place: same class, same instance, retained
    # state; the existing instance gains the new method.
    assert mod.Counter is original_class
    assert inst.__class__ is original_class
    assert inst.value == 10
    assert inst.step() == 11
    assert inst.double() == 20
    assert mod.Counter(3).double() == 6


def test_super_resync(tmp_path):
    """Redefining a method that calls super() preserves the implicit __class__ cell."""
    mod = _make_module(
        tmp_path,
        """
        class Base:
            def name(self):
                return "base"

        class Child(Base):
            def name(self):
                return "child-" + super().name()
        """,
    )
    child = mod.Child()
    assert child.name() == "child-base"

    make_recoder(mod.Child.name).patch(
        'def name(self):\n    return "kid-" + super().name()\n'
    )
    assert child.name() == "kid-base"


def test_closure_factory_resync(tmp_path):
    """Redefining a closure factory syncs new inner code onto existing closures."""
    mod = _make_module(
        tmp_path,
        """
        def make_adder(n):
            def add(x):
                return x + n
            return add
        """,
    )
    add5 = mod.make_adder(5)
    add9 = mod.make_adder(9)
    assert add5(10) == 15 and add9(10) == 19

    make_recoder(mod.make_adder).patch(
        textwrap.dedent(
            """
            def make_adder(n):
                def add(x):
                    return x + n * 1000
                return add
            """
        )
    )
    # Every already-created closure runs the new inner body while keeping its own
    # captured value.
    assert add5(10) == 5010
    assert add9(10) == 9010
    assert mod.make_adder(2)(10) == 2010


def test_definition_forms_redefinition(tmp_path):
    """Redefinition applies across decorated, nested, async, and descriptor forms."""
    mod = _make_module(
        tmp_path,
        """
        def deco(f):
            def wrapper(*a, **k):
                return f(*a, **k) + 1
            return wrapper

        @deco
        def decorated(x):
            return x * 2

        def outer():
            def inner():
                return 1
            return inner()

        async def afn(x):
            return x * 2

        class Box:
            def __init__(self, v):
                self._v = v

            @property
            def val(self):
                return self._v

            @classmethod
            def tag(cls):
                return "t1"

            @staticmethod
            def kind():
                return "k1"
        """,
    )
    box = mod.Box(10)
    assert mod.decorated(10) == 21 and mod.outer() == 1
    assert asyncio.new_event_loop().run_until_complete(mod.afn(5)) == 10
    assert box.val == 10 and mod.Box.tag() == "t1" and mod.Box.kind() == "k1"

    # Decorated functions update via on-disk reload (the code inside the wrapper).
    codefile, _ = registry.find(mod)
    _rewrite(
        mod,
        """
        def deco(f):
            def wrapper(*a, **k):
                return f(*a, **k) + 1
            return wrapper

        @deco
        def decorated(x):
            return x * 100

        def outer():
            def inner():
                return 999
            return inner()

        async def afn(x):
            return x * 7

        class Box:
            def __init__(self, v):
                self._v = v

            @property
            def val(self):
                return self._v * 100

            @classmethod
            def tag(cls):
                return "t2"

            @staticmethod
            def kind():
                return "k2"
        """,
    )
    codefile.refresh()

    assert mod.decorated(10) == 1001       # (10 * 100) + 1
    assert mod.outer() == 999
    assert asyncio.new_event_loop().run_until_complete(mod.afn(5)) == 35
    assert box.val == 1000                 # property update on the live instance
    assert mod.Box.tag() == "t2"
    assert mod.Box.kind() == "k2"


def test_inflight_generator_and_coroutine(tmp_path):
    """A generator/coroutine already created keeps its old code; fresh ones use the new.

    A suspended frame is bound to the code object it started with, so redefining
    the function does not retarget an in-flight instance.
    """
    mod = _make_module(
        tmp_path,
        """
        def gen():
            yield 1
            yield 2
            yield 3
        """,
    )
    g = mod.gen()
    assert next(g) == 1  # now suspended, in flight

    make_recoder(mod.gen).patch("def gen():\n    yield 10\n    yield 20\n    yield 30\n")
    assert list(g) == [2, 3]               # in-flight generator finishes on old code
    assert list(mod.gen()) == [10, 20, 30]  # a fresh generator uses the new code

    cmod = _make_module(tmp_path, "async def co(x):\n    return x * 2\n")
    coro = cmod.co(5)  # created, not yet awaited
    make_recoder(cmod.co).patch("async def co(x):\n    return x * 1000\n")
    assert asyncio.new_event_loop().run_until_complete(coro) == 10    # old code
    assert asyncio.new_event_loop().run_until_complete(cmod.co(5)) == 5000  # new code


def test_redefine_recursive_function_on_call_stack(tmp_path):
    """A frame already executing finishes on its old code; only new calls use the new."""
    mod = _make_module(
        tmp_path,
        """
        HOOK = [None]

        def fact(n):
            if n == 3 and HOOK[0]:
                h = HOOK[0]
                HOOK[0] = None
                h()
            if n <= 1:
                return 1
            return n * fact(n - 1)
        """,
    )

    def do_patch():
        make_recoder(mod.fact).patch(
            "def fact(n):\n"
            "    if n == 3 and HOOK[0]:\n"
            "        h = HOOK[0]\n"
            "        HOOK[0] = None\n"
            "        h()\n"
            "    if n <= 1:\n"
            "        return 1\n"
            "    return 1000 * fact(n - 1)\n"
        )

    mod.HOOK[0] = do_patch
    # Frames for n=5,4,3 are already running old code (n*...) when the patch
    # fires at n=3; the new calls n=2,1 use the new code (1000*...).
    assert mod.fact(5) == 60000
    # A fresh top-level call runs entirely on the new code.
    assert mod.fact(4) == 1_000_000_000


def test_decorator_returning_non_function(tmp_path):
    """Reloading a decorated def updates the inner code even when the wrapper isn't a function."""
    mod = _make_module(
        tmp_path,
        """
        class Wrapper:
            def __init__(self, fn):
                self.fn = fn

            def __call__(self, *a, **k):
                return self.fn(*a, **k) + 1

        def deco(fn):
            return Wrapper(fn)

        @deco
        def decorated(x):
            return x * 2
        """,
    )
    assert mod.decorated(10) == 21
    assert type(mod.decorated).__name__ == "Wrapper"  # bound name is not a function

    codefile, _ = registry.find(mod)
    _rewrite(
        mod,
        """
        class Wrapper:
            def __init__(self, fn):
                self.fn = fn

            def __call__(self, *a, **k):
                return self.fn(*a, **k) + 1

        def deco(fn):
            return Wrapper(fn)

        @deco
        def decorated(x):
            return x * 100
        """,
    )
    codefile.refresh()
    assert mod.decorated(10) == 1001                  # inner code swapped in place
    assert type(mod.decorated).__name__ == "Wrapper"  # wrapper object intact


def test_shared_code_object_updates_all_functions(tmp_path):
    """Redefining a function updates every live function that shares its code object."""
    mod = _make_module(
        tmp_path,
        """
        def f(x):
            return x + 1
        """,
    )
    alias = types.FunctionType(mod.f.__code__, mod.f.__globals__, "alias")
    assert alias(1) == 2

    make_recoder(mod.f).patch("def f(x):\n    return x + 1000\n")
    assert mod.f(1) == 1001
    assert alias(1) == 1001  # the separate function sharing the code object also updates


def test_closure_structure_change_fallback(tmp_path):
    """A redefinition that changes a nested function's free variables still applies.

    The new inner code object cannot ``conform`` to the old one (their free
    variables differ), so the implementation must fall back to re-adding the
    definition rather than propagating the conform failure.
    """
    mod = _make_module(
        tmp_path,
        """
        def outer():
            def inner():
                return 1
            return inner()
        """,
    )
    assert mod.outer() == 1

    make_recoder(mod.outer).patch(
        textwrap.dedent(
            """
            def outer():
                k = 5
                def inner():
                    return k
                return inner()
            """
        )
    )
    assert mod.outer() == 5


# ----------------------------------------------------------------------------
# Recoder targeting, addition and deletion
# ----------------------------------------------------------------------------
def test_recoder_targeting_and_name_guard(tmp_path):
    """A module recoder adds names; a focused recoder rejects a foreign name."""
    mod = _make_module(
        tmp_path,
        """
        def inflate(x):
            return x * 2
        """,
    )
    assert mod.inflate(4) == 8

    make_recoder(mod).patch_module(
        textwrap.dedent(
            """
            FACTOR = 3

            def inflate(x):
                return x * 2

            def shrink(x):
                return x // FACTOR
            """
        )
    )
    assert mod.FACTOR == 3
    assert mod.shrink(9) == 3

    with pytest.raises(ValueError):
        make_recoder(mod.inflate).patch("def deflate(x):\n    return x * 2\n")


def test_deletable_recoder_delete_and_readd(tmp_path):
    """A deletable recoder removes its focus on an empty patch, then re-creates it."""
    mod = _make_module(
        tmp_path,
        """
        def inflate(x):
            return x * 2
        """,
    )
    assert mod.inflate(4) == 8

    delrec = make_recoder(mod.inflate, deletable=True)
    delrec.patch("")
    assert not hasattr(mod, "inflate")

    delrec.patch("def inflate(x):\n    return x * 9\n")
    assert mod.inflate(4) == 36


def test_multi_change_module_patch(tmp_path):
    """One module patch may change a definition and add a new one together."""
    mod = _make_module(
        tmp_path,
        """
        def keep(x):
            return x

        def change(x):
            return x + 1
        """,
    )
    saved_keep = mod.keep
    assert mod.keep(5) == 5 and mod.change(5) == 6

    make_recoder(mod).patch_module(
        textwrap.dedent(
            """
            def keep(x):
                return x

            def change(x):
                return x + 100

            def added(x):
                return x * 3
            """
        )
    )
    assert saved_keep is mod.keep  # unchanged definition keeps its identity
    assert mod.change(5) == 105
    assert mod.added(5) == 15


# ----------------------------------------------------------------------------
# Persistence: commit / revert / out-of-sync
# ----------------------------------------------------------------------------
def test_commit_and_revert(tmp_path):
    """commit() writes live changes to disk; revert() restores the last saved state."""
    mod = _make_module(
        tmp_path,
        """
        def inflate(x):
            return x * 2
        """,
    )
    path = mod.__file__
    rec = make_recoder(mod.inflate)

    # Revert with no prior commit restores the original behaviour.
    rec.patch("def inflate(x):\n    return x * 9\n")
    assert mod.inflate(4) == 36
    rec.revert()
    assert mod.inflate(4) == 8

    # Commit persists to disk; a later patch+revert returns to the committed state.
    rec.patch("def inflate(x):\n    return x * 10\n")
    assert "x * 10" not in open(path).read()
    rec.commit()
    assert "x * 10" in open(path).read()
    rec.patch("def inflate(x):\n    return x * 99\n")
    assert mod.inflate(4) == 396
    rec.revert()
    assert mod.inflate(4) == 40


def test_concurrent_recoders_out_of_sync(tmp_path):
    """A second recoder's patch makes the first out-of-sync; repatch resyncs it."""
    mod = _make_module(
        tmp_path,
        """
        def inflate(x):
            return x * 2
        """,
    )
    rec1 = make_recoder(mod.inflate)
    rec2 = make_recoder(mod.inflate)

    rec1.patch("def inflate(x):\n    return x * 10\n")
    rec2.patch("def inflate(x):\n    return x * 20\n")
    assert mod.inflate(4) == 80

    rec2.commit()
    with pytest.raises(OutOfSyncException):
        rec1.commit()

    rec1.repatch()
    assert mod.inflate(4) == 40
    rec1.commit()
    assert "x * 10" in open(mod.__file__).read()


# ----------------------------------------------------------------------------
# On-disk reload: the watch/refresh path
# ----------------------------------------------------------------------------
def test_watch_refresh_with_line_shift_and_hooks(tmp_path):
    """A Watcher's refresh re-reads an edited file (even with moved lines) and fires hooks."""
    mod = _make_module(
        tmp_path,
        """
        def greet():
            return "hello"

        def shout():
            return greet().upper()
        """,
    )
    assert mod.shout() == "HELLO"

    registry.find(mod)  # ensure the file is registered
    # Obtain a Watcher through the public entry point (no observer thread).
    watcher = watch(str(tmp_path / "*.py"), autostart=False)
    assert isinstance(watcher, Watcher)
    pre, post = [], []
    watcher.prerun.register(lambda path, cf: pre.append(path))
    watcher.postrun.register(lambda path, cf: post.append(path))

    # Insert lines above the functions (shifting their line numbers) and edit them.
    _rewrite(
        mod,
        """
        # a new banner comment
        MARK = 7

        def greet():
            return "bonjour"

        def shout():
            return greet().upper() + "!"
        """,
    )
    watcher.refresh(mod.__file__)

    assert mod.MARK == 7
    assert mod.greet() == "bonjour"
    assert mod.shout() == "BONJOUR!"
    assert pre == [mod.__file__] and post == [mod.__file__]


def test_refresh_deletes_removed_definitions(tmp_path):
    """Reloading a file whose source dropped a definition removes it from the module."""
    mod = _make_module(
        tmp_path,
        """
        def a():
            return 1

        def b():
            return 2
        """,
    )
    assert mod.a() == 1 and mod.b() == 2

    codefile, _ = registry.find(mod)
    _rewrite(
        mod,
        """
        def a():
            return 100
        """,
    )
    codefile.refresh()

    assert mod.a() == 100
    assert not hasattr(mod, "b")


def test_init_redefinition_does_not_reinitialise_instances(tmp_path):
    """Redefining __init__ leaves existing instances as-is; new instances use it.

    A changed *method*, however, is live on the old instance.
    """
    mod = _make_module(
        tmp_path,
        """
        class Obj:
            def __init__(self, x):
                self.x = x

            def get(self):
                return self.x
        """,
    )
    old = mod.Obj(5)

    make_recoder(mod.Obj.__init__).patch(
        "def __init__(self, x):\n    self.x = x * 100\n    self.y = 1\n"
    )
    assert old.x == 5 and not hasattr(old, "y")   # existing instance NOT re-initialised
    new = mod.Obj(5)
    assert new.x == 500 and new.y == 1            # new instance uses the new __init__

    make_recoder(mod.Obj.get).patch("def get(self):\n    return self.x + 7\n")
    assert old.get() == 12                         # but a changed method is live on it


def test_module_statement_reexecution_on_refresh(tmp_path):
    """Reloading re-runs only the top-level statements whose source changed."""
    mod = _make_module(
        tmp_path,
        """
        COUNTER = 0
        SIDE = []
        SIDE.append("once")

        def f():
            return COUNTER + 1
        """,
    )
    mod.COUNTER = 999  # runtime mutation before reload

    codefile, _ = registry.find(mod)
    _rewrite(
        mod,
        """
        COUNTER = 0
        SIDE = []
        SIDE.append("once")

        def f():
            return COUNTER + 2
        """,
    )
    codefile.refresh()

    # Unchanged statements are not re-run: the mutation survives and the
    # side-effecting append did not run again.
    assert mod.COUNTER == 999
    assert mod.SIDE == ["once"]
    assert mod.f() == 1001  # f closes over the live globals (999 + 2)


def test_refresh_preserves_identity_on_reorder(tmp_path):
    """Reordering definitions (bodies unchanged) does not disturb their identities."""
    mod = _make_module(
        tmp_path,
        """
        def a():
            return "a"

        def b():
            return "b"
        """,
    )
    saved_a, saved_b = mod.a, mod.b

    codefile, _ = registry.find(mod)
    _rewrite(
        mod,
        """
        def b():
            return "b"

        def a():
            return "a"
        """,
    )
    codefile.refresh()

    assert mod.a() == "a" and mod.b() == "b"
    assert saved_a is mod.a and saved_b is mod.b


# ----------------------------------------------------------------------------
# Registry, in-place rerouting, source fidelity, public utilities
# ----------------------------------------------------------------------------
def test_registry_find_dispatch(tmp_path):
    """registry.find resolves modules, functions, code objects and classes consistently."""
    mod = _make_module(
        tmp_path,
        """
        class Widget:
            def render(self):
                return "w"

        def build():
            return Widget()
        """,
    )
    cf_mod, _ = registry.find(mod)
    cf_fn, defn_fn = registry.find(mod.build)
    cf_code, defn_code = registry.find(mod.build.__code__)
    cf_cls, defn_cls = registry.find(mod.Widget)

    assert cf_mod is cf_fn is cf_code is cf_cls
    assert defn_fn is defn_code
    assert defn_fn.dotpath().endswith(".build")
    assert defn_cls.dotpath().endswith(".Widget")


def test_rescript_redirect(tmp_path):
    """redirect()/redirect_code() reroute a live function through a decorator."""

    def doubler(f):
        def wrap(*args, **kwargs):
            return f(*args, **kwargs) * 2

        return wrap

    def f(x):
        return x + 1

    orig = f
    assert f(10) == 11
    redirect(f, doubler)
    assert f is orig  # identity preserved; __code__ rerouted in place
    assert f(10) == 22

    def g(x):
        return x + 1

    code = g.__code__
    del g
    gc.collect()
    with pytest.raises(Exception, match="requires exactly one function"):
        redirect_code(code, doubler)


def test_source_reconstruction_fidelity(tmp_path):
    """Committing one changed function preserves all surrounding source verbatim."""
    source = (
        "# module header comment\n"
        "IMPORTANT = 1\n"
        "\n"
        "\n"
        "def alpha(x):\n"
        "    # alpha does a thing\n"
        "    return x + IMPORTANT\n"
        "\n"
        "\n"
        "def beta(x):\n"
        "    return x * 5\n"
    )
    mod = _make_module(tmp_path, source)
    assert mod.alpha(1) == 2 and mod.beta(3) == 15

    make_recoder(mod.beta).patch("def beta(x):\n    return x * 9\n")
    registry.find(mod)[0].commit()

    after = open(mod.__file__).read()
    # beta's body changed exactly once; everything else is byte-for-byte identical.
    assert after.count("def beta(x):") == 1
    assert "    return x * 9\n" in after
    assert "    return x * 5\n" not in after
    expected_prefix = (
        "# module header comment\n"
        "IMPORTANT = 1\n"
        "\n"
        "\n"
        "def alpha(x):\n"
        "    # alpha does a thing\n"
        "    return x + IMPORTANT\n"
    )
    assert after.startswith(expected_prefix)
    assert mod.alpha(1) == 2 and mod.beta(3) == 27


def test_public_facade_and_utilities(tmp_path):
    """The watch/glob/virtual-file helpers behave as documented."""
    # watch(..., autostart=False) builds a usable Watcher through the public entry point
    # without starting the background watch thread.
    w = watch(str(tmp_path / "*.py"), autostart=False)
    assert isinstance(w, Watcher)

    # glob_filter builds a path matcher: an absolute "*.py" pattern matches files
    # in that directory by extension and rejects both a wrong extension and a
    # same-named file in a different directory.
    match = glob_filter(str(tmp_path / "*.py"))
    assert match(str(tmp_path / "mod.py")) is True
    assert match(str(tmp_path / "sub" / "mod.py")) is True  # fnmatch '*' spans separators
    assert match(str(tmp_path / "mod.txt")) is False
    assert match(str(tmp_path.parent / "other_dir_xyz" / "mod.py")) is False

    # virtual_file registers synthetic source under a fresh linecache key each call:
    # the keys are distinct and the full multi-line contents round-trip through linecache.
    fname1 = virtual_file("snippet", "x = 41\ny = x + 1\n")
    fname2 = virtual_file("snippet", "z = 0\n")
    assert fname1.startswith("<snippet#") and fname2.startswith("<snippet#")
    assert fname1 != fname2
    assert "".join(linecache.getlines(fname1)) == "x = 41\ny = x + 1\n"
    assert "".join(linecache.getlines(fname2)) == "z = 0\n"
