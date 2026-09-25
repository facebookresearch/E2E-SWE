"""Tests for the import_tracker library covering all three public APIs
(track_module, lazy_import_errors, setup_tools.parse_requirements) and the CLI.

Each test exercises a distinct behavioral contract of the library using sample
libraries with known dependency graphs as fixtures.
"""

import json
import sys
import tempfile
from contextlib import contextmanager

import pytest

from import_tracker import track_module, lazy_import_errors, setup_tools


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@contextmanager
def cli_args(*args):
    """Temporarily replace sys.argv for CLI testing."""
    prev = sys.argv
    sys.argv = ["dummy"] + list(args)
    yield
    sys.argv = prev


# ---------------------------------------------------------------------------
# track_module — basic tracking
# ---------------------------------------------------------------------------


def test_track_basic_usage():
    """Track single modules using both absolute and relative import syntax.
    Exercises the fundamental bytecode-analysis pipeline: importing the module,
    disassembling with `dis`, parsing IMPORT_NAME opcodes, filtering out
    standard-library modules, and returning sorted dependency lists.
    """
    result = track_module("mylib.submod1")
    assert result == {"mylib.submod1": ["yaml"]}

    result_rel = track_module(".submod2", "mylib")
    assert result_rel == {"mylib.submod2": ["alog"]}


def test_track_recursive_submodules():
    """Track a module with submodules=True and verify that every submodule's
    third-party deps are broken out separately. The parent module should
    contain the union of all submodule deps. Exercises the recursive
    module-walking logic and per-submodule dependency aggregation.
    """
    result = track_module("mylib", submodules=True)
    assert set(result.keys()) == {
        "mylib",
        "mylib.submod1",
        "mylib.submod2",
        "mylib.nested",
        "mylib.nested.submod3",
    }
    assert set(result["mylib.submod1"]) == {"yaml"}
    assert set(result["mylib.submod2"]) == {"alog"}
    assert set(result["mylib.nested.submod3"]) == {"alog", "yaml"}
    assert set(result["mylib"]) == {"alog", "yaml"}


def test_track_limited_submodules():
    """Track with a specific list of submodules and verify only those appear
    in the output alongside the root module. Exercises the submodule-filtering
    path in track_module.
    """
    result = track_module("mylib", submodules=["mylib.submod1"])
    assert set(result.keys()) == {"mylib", "mylib.submod1"}
    assert result["mylib.submod1"] == ["yaml"]


# ---------------------------------------------------------------------------
# track_module — sibling/transitive dependency resolution
# ---------------------------------------------------------------------------


def test_track_sibling_dependencies():
    """Track a library where one submodule imports a sibling submodule and
    verify that third-party deps are correctly attributed through sibling
    imports. child2 imports child1 (which imports alog), so child2 should
    list both yaml (direct) and alog (transitive through child1).
    """
    result = track_module("sibling_deps", submodules=True)
    assert set(result["sibling_deps.child1"]) == {"alog"}
    assert set(result["sibling_deps.child2"]) == {"alog", "yaml"}
    assert set(result["sibling_deps"]) == {"alog", "yaml"}


def test_track_full_depth():
    """Track a module that depends on another sample lib (deep_lib -> mylib)
    and verify that full_depth=True follows into mylib's third-party deps
    (yaml, alog) while full_depth=False (default) stops at the mylib boundary.
    Exercises the full_depth traversal flag.
    """
    result_shallow = track_module("deep_lib")
    assert result_shallow["deep_lib"] == ["mylib"]

    result_deep = track_module("deep_lib", full_depth=True)
    assert set(result_deep["deep_lib"]) == {"mylib", "yaml", "alog"}


def test_track_conditional_imports():
    """Track a module with try/except around a missing import and verify the
    tracker handles it gracefully without crashing. cond_lib's only import is a
    missing package behind try/except, which never resolves to an on-disk module
    and so cannot be classified as a third-party dependency. The correct,
    well-defined result is therefore that cond_lib has no tracked deps at all.
    """
    result = track_module("cond_lib")
    assert result == {"cond_lib": []}


# ---------------------------------------------------------------------------
# track_module — detect_transitive and track_import_stack info flags
# ---------------------------------------------------------------------------


def test_track_detect_transitive():
    """Use detect_transitive=True and verify each dependency is classified as
    'direct' (imported in the module's own source) or 'transitive' (pulled in
    through an internal sub-import). Exercises the stack-depth classification
    logic in track_module at both submodule and parent levels. Also enables
    track_import_stack in the same call to verify the output-schema merging
    logic: when multiple info flags are set, both the 'type' and 'stack' keys
    coexist on a single dependency's info dict.
    """
    result = track_module("sibling_deps", submodules=True, detect_transitive=True)
    assert result["sibling_deps.child1"]["alog"]["type"] == "direct"
    assert result["sibling_deps.child2"]["yaml"]["type"] == "direct"
    assert result["sibling_deps.child2"]["alog"]["type"] == "transitive"
    assert result["sibling_deps"]["alog"]["type"] == "transitive"
    assert result["sibling_deps"]["yaml"]["type"] == "transitive"

    # detect_transitive + track_import_stack together: the two info flags are
    # additive and both keys must appear on the same dependency info dict.
    combined = track_module(
        "sibling_deps",
        submodules=True,
        detect_transitive=True,
        track_import_stack=True,
    )
    child2_alog = combined["sibling_deps.child2"]["alog"]
    assert child2_alog["type"] == "transitive"
    assert "stack" in child2_alog
    child2_yaml = combined["sibling_deps.child2"]["yaml"]
    assert child2_yaml["type"] == "direct"
    assert "stack" in child2_yaml


def test_track_import_stack():
    """Use track_import_stack=True and verify the import chain for a
    transitively-reached dependency. Exercises the stack-trace recording
    logic that tracks how each dependency reaches the target module.
    """
    result = track_module("sibling_deps", submodules=True, track_import_stack=True)
    assert "stack" in result["sibling_deps.child1"]["alog"]
    child1_alog_stacks = result["sibling_deps.child1"]["alog"]["stack"]
    assert any(stack == ["sibling_deps.child1"] for stack in child1_alog_stacks)

    assert "stack" in result["sibling_deps.child2"]["yaml"]
    child2_yaml_stacks = result["sibling_deps.child2"]["yaml"]["stack"]
    assert any(stack == ["sibling_deps.child2"] for stack in child2_yaml_stacks)


# ---------------------------------------------------------------------------
# lazy_import_errors — deferred ModuleNotFoundError
# ---------------------------------------------------------------------------


def test_lazy_import_errors_deferred_and_operators():
    """Verify that lazy_import_errors defers ModuleNotFoundError from import
    time to actual usage time, and that all meaningful operations on the lazy
    proxy object trigger the error. Exercises the meta path finder, the lazy
    error module, and the _LazyErrorAttr metaclass with its comprehensive
    operator overrides.
    """
    with lazy_import_errors():
        import foobarbaz_missing

    with pytest.raises(ModuleNotFoundError):
        foobarbaz_missing.some_function()

    with lazy_import_errors():
        import fake_ops_module

    Proxy = fake_ops_module.SomeClass

    for fn in [
        lambda: Proxy(),
        lambda: Proxy + 1,
        lambda: Proxy - 1,
        lambda: Proxy * 2,
        lambda: str(Proxy),
        lambda: int(Proxy),
        lambda: float(Proxy),
        lambda: Proxy == Proxy,
        lambda: Proxy[0],
        lambda: hash(Proxy),
        lambda: 1 in Proxy,
        lambda: Proxy > 1,
        lambda: Proxy < 1,
        lambda: abs(Proxy),
        lambda: ~Proxy,
        lambda: -Proxy,
        lambda: next(Proxy),
    ]:
        with pytest.raises(ModuleNotFoundError):
            fn()


def test_lazy_import_errors_params():
    """Verify that the make_error_message callback produces custom error
    messages, and that passing both get_extras_modules and make_error_message
    raises TypeError (mutually exclusive parameters).
    """
    msg = "Custom: install pkg-xyz to use this feature"

    def make_msg(*_, **__):
        return msg

    with lazy_import_errors(make_error_message=make_msg):
        import another_missing_pkg

    with pytest.raises(ModuleNotFoundError, match=msg):
        another_missing_pkg.do_something()

    with pytest.raises(TypeError):
        lazy_import_errors(
            make_error_message=lambda x: "err",
            get_extras_modules=lambda: {"mod"},
        )


def test_lazy_import_context_manager_cleanup():
    """Verify the observable scoping contract of nested lazy_import_errors
    contexts: a missing module imported inside a context has its
    ModuleNotFoundError deferred to usage time, and that deferral holds
    independently for an import made in an inner nested context. Exercises the
    context-manager lifecycle through its user-visible behavior (deferred
    errors), not through the internal sys.meta_path bookkeeping.
    """
    with lazy_import_errors():
        import yet_another_missing_pkg

        with lazy_import_errors():
            import inner_missing_pkg

        # The inner import is deferred: it does not raise at import time, and
        # using the proxy raises ModuleNotFoundError.
        with pytest.raises(ModuleNotFoundError):
            inner_missing_pkg.inner_call()

    # After both contexts exit, the import made in the outer context is still
    # deferred and raises only when the proxy is actually used.
    with pytest.raises(ModuleNotFoundError):
        yet_another_missing_pkg.call_something()


def test_lazy_import_class_inheritance():
    """Verify that a class inheriting from a lazy-imported attribute defers
    the error until the derived class is instantiated. Exercises the
    _LazyErrorAttr metaclass's __new__ and __call__ behavior at import time.
    """
    with lazy_import_errors():
        import fake_base_module

    BaseWidget = fake_base_module.BaseWidget

    class MyWidget(BaseWidget):
        def __init__(self, val):
            super().__init__(val)

    with pytest.raises(ModuleNotFoundError):
        MyWidget(42)


# ---------------------------------------------------------------------------
# CLI — python -m import_tracker
# ---------------------------------------------------------------------------


def test_cli_output(capsys):
    """Invoke the CLI entry point with various flag combinations and verify
    the JSON output. Tests basic --name, --submodules + --detect_transitive,
    and --full_depth + --indent. Exercises the argparse CLI, JSON
    serialization, and end-to-end pipeline.
    """
    from import_tracker.__main__ import main

    with cli_args("--name", "mylib.submod1"):
        main()
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert parsed == {"mylib.submod1": ["yaml"]}

    with cli_args("--name", "sibling_deps", "--submodules", "--detect_transitive"):
        main()
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert parsed["sibling_deps.child1"]["alog"]["type"] == "direct"
    assert parsed["sibling_deps.child2"]["yaml"]["type"] == "direct"
    assert parsed["sibling_deps.child2"]["alog"]["type"] == "transitive"

    with cli_args("--name", "deep_lib", "--full_depth", "--indent", "2"):
        main()
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    deep_deps = parsed["deep_lib"]
    assert set(deep_deps) == {"mylib", "yaml", "alog"}


# ---------------------------------------------------------------------------
# setup_tools.parse_requirements
# ---------------------------------------------------------------------------


def test_parse_requirements_with_extras():
    """Call parse_requirements with a requirements list and specific
    extras_modules, and verify the partitioning of common requirements
    vs per-module extras is correct. Also tests file input and invalid
    type rejection. Exercises the full setup_tools pipeline.
    """
    # List input with an explicit extras subset (submod1, submod2). Both
    # remaining (untracked-as-extras) modules — mylib, mylib.nested,
    # mylib.nested.submod3 — pull in BOTH yaml and alog, so both deps are
    # common to every module and get factored out of the per-extra sets,
    # leaving submod1/submod2 with empty unique extras. Assert the exact
    # partition (not just key presence) so a mis-partitioning implementation
    # that leaves deps in the per-module sets, or drops the common factoring,
    # fails.
    reqs = ["alchemy-logging", "PyYaml"]
    requirements, extras_require = setup_tools.parse_requirements(
        reqs, "mylib", ["mylib.submod1", "mylib.submod2"]
    )
    assert sorted(requirements) == sorted(["PyYaml", "alchemy-logging"])
    assert extras_require == {
        "all": sorted(["PyYaml", "alchemy-logging"]),
        "mylib.submod1": [],
        "mylib.submod2": [],
    }

    # File input with no explicit extras_modules: every tracked module becomes
    # an extra, so the per-module partitioning is exercised distinctly. The two
    # leaf submodules each own exactly one dep (submod1 -> yaml -> PyYaml,
    # submod2 -> alog -> alchemy-logging), while the parent and nested modules
    # own both. The original requirement strings (with version specifiers) are
    # preserved in the output.
    reqs_content = "# Core deps\nalchemy-logging>=1.0\nPyYaml>=6.0\n"
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write(reqs_content)
        f.flush()
        requirements, extras_require = setup_tools.parse_requirements(f.name, "mylib")
    assert extras_require == {
        "all": sorted(["PyYaml>=6.0", "alchemy-logging>=1.0"]),
        "mylib": sorted(["PyYaml>=6.0", "alchemy-logging>=1.0"]),
        "mylib.nested": sorted(["PyYaml>=6.0", "alchemy-logging>=1.0"]),
        "mylib.nested.submod3": sorted(["PyYaml>=6.0", "alchemy-logging>=1.0"]),
        "mylib.submod1": ["PyYaml>=6.0"],
        "mylib.submod2": ["alchemy-logging>=1.0"],
    }

    with pytest.raises(ValueError):
        setup_tools.parse_requirements({"not": "a list"}, "mylib")
