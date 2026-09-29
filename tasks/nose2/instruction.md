# nose2: A Test Framework Extending unittest

## Overview

Build `nose2`, a Python test framework that extends the standard `unittest` module with a plugin-based architecture. nose2 provides test discovery, parameterized testing, BDD-style test definition, layered test organization, and configurable reporting — all through a pluggable system.

**Version**: `0.16.0`

## Dependencies

The environment is **offline** and every dependency is **already installed** — do not attempt to install anything (there is no network).

- **Runtime**: none. nose2's own code uses only the Python standard library.
- **`coverage`**: required only by the Coverage plugin (see Plugins below). It is already installed in the environment; treat it as an available optional dependency rather than something to install.

The project is installed by a `setup.sh` that runs **offline** in this environment — the package ships a `pyproject.toml` / `setup.py` installable with `pip install -e . --no-build-isolation` (the build backend is pre-installed).

## Package Structure

The package is called `nose2`. The top-level `nose2` package exports `nose2.discover(**kwargs)` as its main programmatic entry point.

## Core Entry Point: `nose2.discover()`

```python
nose2.discover(argv=None, exit=True, plugins=None, excludePlugins=None)
```

Loads configuration and plugins, discovers and runs tests, and returns an object whose `.result.wasSuccessful()` reports overall pass/fail.

- `argv`: Command-line arguments list. Format: `["nose2", "-s", start_dir, "-t", top_dir, ...]`
- `exit`: If `True`, calls `sys.exit()` after running. Set to `False` for programmatic use.
- `plugins`: Additional plugin module paths to load
- `excludePlugins`: Plugin module paths to exclude

## CLI Entry Point: `python -m nose2`

Invokable via `python -m nose2`. Accepts `-s`, `-t`, `-F` (failfast), `-B` (buffer), `--plugin MODULE`, `-X` / `--activate-plugin` (boolean switch, takes no argument — force-activates a plugin loaded via `--plugin` that would otherwise stay registered-but-dormant; see Plugins below for which plugins require it), `-A ATTR`, `-c FILE` (additional config file appended to the default auto-loaded list), `--log-capture`, `--junit-xml-path PATH`, and positional test names. Positional test names can identify a test at any granularity — `module`, `module.TestClass`, or `module.TestClass.test_method`; selecting at the class level runs every test method in that class. Also accepts verbosity controls: `-v` / `--verbose` (increase verbosity; repeat for more), `-q` / `--quiet` (decrease verbosity; repeat for less), `--verbosity N` (set initial integer verbosity), and `--log-level LEVEL` (set the console logging threshold, e.g. `DEBUG`, `INFO`, `WARNING`). nose2 emits its own internal debug-level log records as part of normal operation (during startup, plugin loading, and test discovery/loading), so at `--log-level DEBUG` at least one such internal debug record is written to stderr even for an ordinary all-passing run with no import or load errors, while at `WARNING` and higher those debug records are suppressed. These records use Python's standard `logging` module, so each is rendered on stderr in the stdlib default format (a `LEVELNAME:logger:message` line, e.g. one beginning with `DEBUG:`). Exits with 0 on success, non-zero on failure. Summary printed to stderr; per-test names appear in stderr at verbosity ≥ 2. The summary follows the standard `unittest` test-runner report format.

## Configuration

Reads INI-style `.cfg` files. By default, nose2 auto-loads both `unittest.cfg` and `nose2.cfg` from the start directory if they exist (settings from both apply). Additional config files can be added with `-c FILE` (appended to the auto-load list). The `[unittest]` section supports `verbosity` and `test-file-pattern` (default: `test*.py`). Plugin sections use the plugin's config name.

## Parameterized Testing

```python
from nose2.tools import params, cartesian_params
```

`@params(*args)` — each argument becomes a separate test case. Tuples are unpacked as arguments. Works on methods and standalone functions.

`@cartesian_params(*args_lists)` — generates test cases for the Cartesian product of argument lists.

## BDD-Style Testing: `nose2.tools.such`

```python
from nose2.tools import such

with such.A('system name') as it:
    @it.has_setup
    def setup(): ...

    @it.has_teardown
    def teardown(): ...

    @it.should('do something')
    def test(case):
        case.assertEqual(1 + 1, 2)

    with it.having('a subsystem'):
        @it.has_setup
        def sub_setup(): ...

        @it.should('work in subsystem')
        def test_sub(case): ...

    it.createTests(globals())
```

Requires the layers plugin to be active (load it with `--plugin nose2.plugins.layers`; no `-X` needed).

Fixtures are **scoped to the group that defines them**. A group's `has_setup` runs once, before any of the tests in *that* group, and its `has_teardown` runs once, after all of the tests in *that* group. A nested `having(...)` block is a child group: its `has_setup` runs only around its own tests, and it inherits its parent's setup (the parent's `has_setup` runs before the child's when the child group's tests run). Consequently a `should` test in an outer group runs with only its own (and its ancestors') setup applied and does **not** observe any side effects of a nested child group's `has_setup` — the child group's fixtures take effect only for the child group's own tests and are torn down before control returns to a different group's tests.

## Layers Plugin

`nose2.plugins.layers` — test layers with shared `setUp`/`tearDown`. Activate by loading it with `--plugin nose2.plugins.layers` (it has no flag of its own and needs no `-X`). Tests assign themselves via `layer` class attribute. Child layers inherit from parents (parent setUp runs first). Each layer's tests run as a group bracketed by that layer's `setUp`/`tearDown`: the layer's `setUp` fires before its group of tests and its `tearDown` fires after them, before tests belonging to a different layer run. A child layer's `setUp` therefore takes effect only while the child layer's tests run and is undone before control returns to a parent (or sibling) layer's tests — so a test in a parent layer does not observe any state established by a child layer's `setUp`.

Layer classes may also define `testSetUp(cls, test)` and `testTearDown(cls, test)` classmethods that fire before/after each individual test in the layer (in addition to once-per-layer `setUp`/`tearDown`). Each accepts the test instance as a second argument.

## Plugins

nose2 uses a plugin-based architecture. Key plugins:

**Activation contract.** A plugin loaded with `--plugin MODULE` becomes active depending on the plugin: most plugins below carry their own activation flag (e.g. `-B`, `-F`, `-A`, `--with-doctest`, `--with-coverage`, `--profile`, `--pretty-assert`, `--with-id`, `--set-outcomes`, `--print-hooks`, `--collect-only`, `--log-capture`, `-N`) and are activated by passing that flag. The loader plugins (`nose2.plugins.loader.functions`, `nose2.plugins.loader.generators`, `nose2.plugins.loader.testclasses`) and the `nose2.plugins.layers` plugin have **no activation flag of their own** and are active simply by being loaded — `--plugin nose2.plugins.loader.functions` on its own enables standalone-function discovery, `--plugin nose2.plugins.layers` on its own enables layer `setUp`/`tearDown`, and so on (no `-X` needed). `-X` / `--activate-plugin` is required only for a plugin whose own activation is gated behind `-X` rather than a dedicated flag — JUnit XML is such a plugin (`--plugin nose2.plugins.junitxml -X --junit-xml-path PATH`).

- **JUnit XML** (`nose2.plugins.junitxml`): Generate JUnit XML reports. Activate with `--plugin nose2.plugins.junitxml -X --junit-xml-path PATH`. Output: `<testsuite>` with `tests`, `failures`, `errors`, `skipped` attributes. Contains `<testcase>` elements with `<failure>`, `<error>`, or `<skipped>` children as appropriate.
- **Output Buffer** (`nose2.plugins.buffer`): Capture stdout/stderr, show only for failures. Activate with `-B`, or always-on via config `[output-buffer] always-on = True`.
- **Log Capture** (`nose2.plugins.logcapture`): Capture Python logging emitted during each test. On a test that fails or errors, the captured log records are appended to that test's failure report on stderr (so the logged message text is visible in the run output for failing tests); logs from passing tests are discarded. Activate with `--plugin nose2.plugins.logcapture --log-capture`.
- **Failfast** (`nose2.plugins.failfast`): Stop on first failure. Activate with `-F`.
- **Attributes** (`nose2.plugins.attrib`): Select tests by attribute. Activate with `--plugin nose2.plugins.attrib -A ATTR`. A bare `-A ATTR` selects only tests whose `ATTR` attribute is present and truthy; tests where the attribute is absent or set to a falsy value (e.g. `False`) are excluded.
- **Functions Loader** (`nose2.plugins.loader.functions`): Discover standalone test functions.
- **Generators Loader** (`nose2.plugins.loader.generators`): Support generator test methods that yield test cases. A generator test method (a test method that `yield`s) is *replaced* by the individual test cases it yields. Each yielded item is either a callable or a `(callable, *args)` tuple, and each becomes exactly one test case.
- **TestClasses Loader** (`nose2.plugins.loader.testclasses`): Discover plain classes with test methods.
- **Multiprocess** (`nose2.plugins.mp`): Distribute tests across worker processes. Activate with `--plugin nose2.plugins.mp -N COUNT` where COUNT is the number of worker processes. Worker failures are isolated — a failing test in one worker does not prevent other workers' tests from running, and overall results aggregate across all workers.
- **Collect Only** (`nose2.plugins.collect`): List discovered tests without executing them. Activate with `--plugin nose2.plugins.collect --collect-only`. Useful for verifying discovery.
- **Doctests** (`nose2.plugins.doctests`): Discover and run doctests in function, class, method, and module docstrings within source files, and in standalone `.txt`/`.rst` text files. Activate with `--plugin nose2.plugins.doctests --with-doctest`.
- **Coverage** (`nose2.plugins.coverage`): Generate a code-coverage report (requires the `coverage` package). Activate with `--plugin nose2.plugins.coverage --with-coverage --coverage MODULE`, where `MODULE` selects which package(s) to measure.
- **Profiler** (`nose2.plugins.prof`): Run tests under `cProfile` and print the profile to the test summary. The profile is introduced by a recognizable profiling-results header (a labeled section whose text contains the word `Profiling`/`Profile`, e.g. a `Profiling results` line) printed ahead of the `cProfile`/`pstats` output, so the profiling section is identifiable in the summary. Activate with `--plugin nose2.plugins.prof --profile`.
- **DunderTest** (`nose2.plugins.dundertest`): Always-on filter that excludes any test (function, method, or class) whose `__test__` attribute evaluates to `False`. No activation flag required.
- **PrettyAssert** (`nose2.plugins.prettyassert`): On failures from bare `assert` statements, includes the assertion's source line and local variable values in the failure output. Activate with `--plugin nose2.plugins.prettyassert --pretty-assert`.
- **TestID** (`nose2.plugins.testid`): Assigns a stable integer ID to each discovered test, prints it in front of the test name in verbose output (e.g. `#1`), and persists the id→name mapping in a `.noseids` file in the start directory. Subsequent runs can use these integer IDs as positional arguments to re-run a specific subset. Activate with `--plugin nose2.plugins.testid --with-id`.
- **Outcomes** (`nose2.plugins.outcomes`): Remap raised exceptions to different test outcomes. Activate with `--plugin nose2.plugins.outcomes --set-outcomes`. Configured via `[outcomes] treat-as-fail = ExceptionName, …` and `[outcomes] treat-as-skip = ExceptionName, …` in a `.cfg` file; exception names are matched by their unqualified `__name__` (e.g. `NotImplementedError`, not `builtins.NotImplementedError`).
- **PrintHooks** (`nose2.plugins.printhooks`): Debug aid that prints every plugin hook name as it fires during a test run. The framework's lifecycle hooks include `startTestRun`, `startTest`, `stopTest`, and `stopTestRun`. Activate with `--plugin nose2.plugins.printhooks --print-hooks`.
- **Parameters Loader** (`nose2.plugins.loader.parameters`): Expand `@params`/`@cartesian_params`. Active by default.
- **LoadTests Loader** (`nose2.plugins.loader.loadtests`): Support the standard unittest `load_tests(loader, tests, pattern)` protocol. Active by default — when a discovered module defines `load_tests`, nose2 honors it during default discovery (no `--plugin` flag required) and runs exactly the suite it returns.

## Function Test Decorators

```python
from nose2.tools.decorators import with_setup, with_teardown
```

`@with_setup(func)` and `@with_teardown(func)` register `func` to be invoked before / after the decorated standalone test function (used together with the functions loader plugin).
