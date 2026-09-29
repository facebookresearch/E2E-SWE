# import_tracker

Build a Python library called `import_tracker` that tracks third-party dependencies of Python modules by analyzing their bytecode. The library identifies which third-party packages each module and submodule depends on, classifies dependencies as direct or transitive, detects optional dependencies guarded by try/except blocks, and can generate `install_requires` / `extras_require` mappings for `setup.py`.

The package has zero runtime dependencies — it uses only the Python standard library.

## Dependencies and environment

The environment is **offline**: there is no network access, and every dependency you need is
**already installed**. Do **not** attempt to install anything (no `pip install`, no network
fetches) — installation will fail.

`import_tracker` itself has **zero runtime dependencies** (Python standard library only). The build
toolchain (`setuptools`, `wheel`) and the test-time libraries that the test fixtures rely on
(`alchemy-logging`, `PyYAML`) are pre-installed in the environment.

## Installation

The package must be installable via `pip install -e .` and requires a `RELEASE_VERSION` environment
variable to be set (any value, e.g. `0.0.0`). Provide a `setup.py` using setuptools. The project is
installed by a `setup.sh` script that runs **offline** against the pre-installed dependencies (it
invokes `pip install -e . --no-build-isolation`, since the build backend is already present and the
environment has no package index).

## Public API

The package exposes three names at the top level:

```python
from import_tracker import track_module
from import_tracker import lazy_import_errors
from import_tracker import setup_tools
```

### `track_module`

```python
def track_module(
    module_name: str,
    package_name: Optional[str] = None,
    submodules: Union[List[str], bool] = False,
    track_import_stack: bool = False,
    full_depth: bool = False,
    detect_transitive: bool = False,
    show_optional: bool = False,
) -> Union[Dict[str, List[str]], Dict[str, Dict[str, Dict[str, Any]]]]:
```

Tracks the third-party dependencies of a Python module by importing it and analyzing its bytecode.

**Core behavior (observable contract):**

1. Import the target module (relative names such as `.submod1` are resolved against `package_name` when it is given).
2. Discover the imports performed by each module's own source.
3. Classify each discovered import as standard-library or third-party; standard-library modules and the `import_tracker` package itself are excluded, so only third-party packages appear in the output. Imported names that cannot be resolved to an on-disk module (e.g. an import guarded by try/except that raises `ModuleNotFoundError`) are skipped and never appear in the dependency output.
4. Recursively follow imports that belong to the same root package as the target module (e.g. when tracking `mylib`, follow `mylib.submod1` → `mylib.submod2`) but stop at third-party boundaries unless `full_depth` is set.
5. For each output module, collect all third-party dependencies reachable through those internal imports, as a sorted list of names.
6. Return a dict mapping fully-qualified module names to their dependency information.

**Parameters:**

- `module_name`: The module to track. May be relative (e.g., `.submod1`) if `package_name` is provided.
- `package_name`: Parent package for relative imports.
- `submodules`: Controls which submodules are added to the output **in addition to** the target module. The queried top-level module is **always** present in the output regardless of this flag; `submodules` only governs which (if any) of its submodules are added: `True` adds all submodules of the target, a list of strings adds only those listed submodules, and `False` adds none (so the output contains just the target module itself).
- `track_import_stack`: Include a `"stack"` key for each dependency with the list of module chains through which the dependency is reached. Each chain is itself a list of fully-qualified module names, ordered from the module that performs the import down to (and including) the queried module. A dependency imported directly in a module's own source therefore yields the single-element chain `[<that module's fully-qualified name>]`.
- `full_depth`: Also recursively follow imports into third-party packages (not just same-package modules).
- `detect_transitive`: Include a `"type"` key for each dependency: `"direct"` if the dependency is imported directly in the module's own source (stack length == 1), `"transitive"` otherwise.
- `show_optional`: Include an `"optional"` key for each dependency: `True` if every import path to the dependency passes through a try/except block, `False` otherwise.

**Return value:**

- When none of `detect_transitive`, `track_import_stack`, or `show_optional` are enabled: `Dict[str, List[str]]` — module name → sorted list of third-party dependency names.
- When any info flag is enabled: `Dict[str, Dict[str, Dict[str, Any]]]` — module name → dep name → info dict with the requested keys (`"type"`, `"stack"`, `"optional"`).

**Direct vs transitive:** A dependency is "direct" for a module if any of its import stack paths has length 1 (imported directly in that module's source). Otherwise it is "transitive."

### `lazy_import_errors`

```python
def lazy_import_errors(
    *,
    get_extras_modules: Optional[Callable[[], Set[str]]] = None,
    make_error_message: Optional[Callable[[str], str]] = None,
):
```

Enables lazy import errors: imports that would raise `ModuleNotFoundError` are deferred until the imported name is actually used. Returns a context manager that disables lazy errors on exit.

Can also be called as a plain function (without `with`) to enable lazy errors globally until explicitly disabled.

**How it behaves (observable contract):**

While lazy errors are enabled, an import that would raise `ModuleNotFoundError` does not raise at import time; the name instead binds to a proxy object, and the error is deferred until the imported name is used in a meaningful way. Reading further attributes off the proxy keeps returning proxies (so chained attribute access never raises). Any meaningful operation on a proxy after import — calling it, indexing (`[]`), iteration, containment (`in`), arithmetic (`+`, `-`, `*`), bitwise (`~`), unary negation, comparison (`==`, `>`, `<`), and `str` / `int` / `float` / `abs` / `hash` / `next` — raises `ModuleNotFoundError`.

As an exception, *while the import is being processed at import time* (i.e. while the module that performs the import is still being loaded, inside the enabling `with` block), a proxy attribute may be called (to support decorators from a missing module) and may be used as a base class (`class Sub(proxy_attr): ...` defines successfully); the deferred `ModuleNotFoundError` is then raised only when the resulting object is actually called or the subclass is instantiated (e.g. `Sub(...)`). Equality (`==`) and `hash` on a proxy likewise behave as identity **only** during this import-time processing (they are used by the import machinery). This import-time carve-out for equality and hashing does **not** persist afterwards: once a proxy is used as an ordinary value after its import completes — in particular after the enabling `with` block has exited — `==` and `hash`, like every other meaningful operation above, raise `ModuleNotFoundError`.

On context-manager exit, new imports are no longer intercepted, while proxies already created remain deferred: they keep raising on the meaningful operations above (including `==`, comparison, and `hash`), and only the base-class exemption still holds. In particular, subclassing such a proxy defines the class successfully whether the `class Sub(proxy_attr): ...` statement runs inside or after the `with` block, with the deferred `ModuleNotFoundError` raised only when `Sub(...)` is instantiated.

When `lazy_import_errors()` contexts are nested, the import-time carve-out for a given proxy is scoped to the specific (innermost) context that was active at *that* proxy's import: "the enabling `with` block" for a proxy is the block in which its import was made. Once that block exits, the proxy leaves import-time mode and any meaningful operation on it — including **calling** it — raises `ModuleNotFoundError`, even if an enclosing (outer) `lazy_import_errors()` context is still open. A proxy created by an import made in the outer context keeps deferring until the outer context itself exits. (As above, only the base-class exemption survives a context's exit.)

The interception applies only to imports that originate from the same package that called `lazy_import_errors`; imports coming from any other package are left to the normal import machinery (they are not masked with lazy errors).

**Parameters are mutually exclusive** — passing both `get_extras_modules` and `make_error_message` raises `TypeError`.

- `make_error_message`: A callable taking the missing module name and returning a custom error string. If it returns `None`, the default message `"No module named '<name>'"` is used.
- `get_extras_modules`: A callable returning a `Set[str]` of module names managed as extras. When provided, the error message includes a `pip install <root_package>[<extras_module>]` hint if the import originates from one of those modules.

### `setup_tools.parse_requirements`

```python
def parse_requirements(
    requirements: Union[List[str], str],
    library_name: str,
    extras_modules: Optional[List[str]] = None,
    full_depth: bool = True,
    keep_optional: Union[bool, Dict[str, List[str]]] = False,
    **kwargs,
) -> Tuple[List[str], Dict[str, List[str]]]:
```

Generates `install_requires` and `extras_require` for `setup.py` by combining a requirements list with tracked import data.

**Parameters:**

- `requirements`: Either a list of requirement strings (e.g., `["PyYaml>=6.0", "alog"]`) or a file path to a `requirements.txt`. Comment lines (starting with `#`) and blank lines are ignored.
- `library_name`: The top-level package name to track.
- `extras_modules`: List of submodule names to generate extras for. If not provided, all tracked submodules are used.
- `full_depth`: Passed through to `track_module`. Defaults to `True`.
- `keep_optional`: Controls whether optional dependencies (behind try/except) are kept. `True` keeps all, `False` drops all, or a dict mapping module names to lists of optional dep names to keep selectively.

**Returns:** A tuple of `(install_requires, extras_require)`.

The whole library is tracked first by running `track_module(library_name, submodules=True, full_depth=full_depth, ...)`, which yields a dependency set for every tracked submodule (including `library_name` itself and any nested submodules), **independent of** which subset is requested via `extras_modules`. `extras_modules` only selects which modules get their own `extras_require` entry; it does not restrict which modules participate in the common-dependency computation.

- `install_requires` is the sorted list of requirement strings for the **common** dependency set. The common set is the union of two parts:
  1. the **intersection** of the dependency sets across **all** tracked modules, and
  2. the **union** of the dependency sets of every tracked module that is **not** covered by `extras_modules` (a module is "covered" if it is one of the `extras_modules` entries or an ancestor/descendant of one along the dotted path).

  Consequently, when `extras_modules` is a strict subset, a dependency that is *not* common to literally every module can still land in `install_requires` because it appears in a non-extra module. (Special case: if exactly one module is requested as an extra, the intersection part is treated as empty.)
- `extras_require[<module>]`, for each module in `extras_modules`, is that module's own dependency set **minus** the common set (i.e. only its residual, non-common requirements). A module whose dependencies are all common therefore gets `[]`.
- `extras_require["all"]` is the union of all tracked modules' requirements (every dependency the library can pull in).
- Every `extras_require` list — each per-module entry **and** the `"all"` entry — is a **sorted** list of requirement strings, the same as `install_requires`.
- The original requirement strings — including version specifiers (e.g. `PyYaml>=6.0`) — are preserved verbatim in the output; the requirements list/file is only used to map a discovered import name back to its declared string.

The function resolves each discovered import name to the name of the installed distribution (pip package) that provides it, as recorded in the installed packages' distribution metadata. Package names are standardized (lowercased, hyphens → underscores) and matched case-insensitively, so an imported module such as `alog` is matched back to a declared requirement such as `alchemy-logging`.

Raises `ValueError` if `requirements` is not a string, list, tuple, or set.

## CLI

The package supports invocation as `python -m import_tracker` with these arguments:

- `--name` / `-n` (required): Module name to track.
- `--package` / `-p`: Package for relative imports.
- `--submodules` / `-s`: Track submodules. With no value, tracks all; with values, tracks only those listed.
- `--detect_transitive` / `-d`: Detect direct vs. transitive dependencies.
- `--show_optional` / `-o`: Show optional status.
- `--track_import_stack` / `-t`: Include import stacks.
- `--full_depth` / `-f`: Include transitive third-party deps.
- `--indent` / `-i`: JSON indent level.
- `--log_level` / `-l`: Log level (default: `warning`).

Output is JSON printed to stdout via `json.dumps`.

The CLI entry point is implemented as a `main()` function in `import_tracker/__main__.py` — that is, `__main__.py` defines `def main(): ...` (which parses the arguments above and prints the JSON) and invokes it under `if __name__ == "__main__":`. It is therefore importable as `from import_tracker.__main__ import main`.
