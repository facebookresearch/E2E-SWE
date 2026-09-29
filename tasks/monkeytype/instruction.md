# MonkeyType — Runtime Type Collection and Stub Generation

Implement **MonkeyType**: collect runtime types via tracing, store in SQLite, generate type stubs or apply annotations to source.

## Dependencies

The environment is **offline** — all dependencies are already installed and you must **not**
install anything. The project itself is installed by a `setup.sh` that runs offline (an editable
install against the pre-baked dependencies). The pre-installed runtime dependencies are:

- `mypy_extensions`, `libcst>=0.4.4`

## Package Structure

```python
import monkeytype
from monkeytype.tracing import CallTrace, CallTraceLogger, trace_calls
from monkeytype.typing import get_type, shrink_types, DEFAULT_REWRITER, NoOpRewriter
from monkeytype.encoding import CallTraceRow, type_to_json, type_from_json
from monkeytype.stubs import (FunctionStub, FunctionKind, FunctionDefinition,
                               ClassStub, ModuleStub, build_module_stubs,
                               build_module_stubs_from_traces,
                               StubIndexBuilder, render_annotation,
                               ExistingAnnotationStrategy)
from monkeytype.config import Config, DefaultConfig, default_code_filter
from monkeytype.db.base import CallTraceStore, CallTraceThunk, CallTraceStoreLogger
from monkeytype.db.sqlite import SQLiteStore, create_call_trace_table
from monkeytype.exceptions import MonkeyTypeError, NameLookupError, InvalidTypeError
from monkeytype.util import get_name_in_module, pascal_case
from monkeytype.type_checking_imports_transformer import MoveImportsToTypeCheckingBlockVisitor
```

## 1. Runtime Tracing

Uses `sys.setprofile` to intercept function calls/returns, collecting argument and return types.

`CallTrace`: `func`, `arg_types` (dict), `return_type` (None if raised), `yield_type`. Supports equality, hashing. `funcname` property: `func.__module__ + "." + func.__qualname__`.

`CallTraceLogger`: abstract base class. `log(trace)` is abstract; `flush()` has a default empty implementation.

`trace_calls(logger, max_typed_dict_size, code_filter=None, sample_rate=None)`: context manager. `code_filter` is `Callable[[CodeType], bool]`. Calls `logger.flush()` on exit.

`sample_rate` is an integer down-sampling rate: each intercepted call is independently traced with probability `1/sample_rate` (drawn at random). `sample_rate=1` (or `None`) traces every call; a value `N > 1` traces only a random subset (roughly 1 in N), so larger `N` captures strictly fewer calls.

`monkeytype.trace(config=None)`: convenience wrapper using Config's `trace_logger()`, `code_filter()`, `sample_rate()`, `max_typed_dict_size()`.

## 2. Type Inference

`get_type(obj, max_typed_dict_size)` maps a runtime value to its static type annotation. Uses `typing` module generics where applicable:
- Type objects: `int` → `Type[int]`
- Containers infer element types: `(1, "a")` → `Tuple[int, str]`
- Empty containers: `[]` → `List[Any]`, `{}` → `Dict[Any, Any]`, `()` → `Tuple[()]`
- Callables → `Callable`

`shrink_types(types, max_typed_dict_size)` reduces an iterable (set or list) of types to a minimal type: deduplicates, produces `Union` for different types, collapses `Union[T, None]` to `Optional[T]`.

**Type rewriters** normalize types. `DEFAULT_REWRITER` is a chain that: converts `Generator[T, None, None]` to `Iterator[T]`, removes empty containers from Unions when concrete alternatives exist, and merges dictionaries with the same key type. `NoOpRewriter` is the identity rewriter.

## 3. Type Encoding (JSON Serialization)

`type_to_json(typ)` / `type_from_json(s)`: round-trip encoding of Python types including generics and `NoneType`. Given input that is not a valid encoded type, `type_from_json` raises rather than returning — either the lookup/value error surfaced by the malformed input, or one of the Section 9 `MonkeyTypeError` types.

`CallTraceRow`: serializes `CallTrace` to/from storable format. `from_trace(trace)` → row with `module`, `qualname`, encoded types. `to_trace()` → reconstructed `CallTrace`.

## 4. Storage

`CallTraceStore`: abstract with `add(traces)` and `filter(module, qualname_prefix=None, limit=2000)` → list of `CallTraceThunk` (has `to_trace()`).

`SQLiteStore(conn)`: SQLite-backed store. `create_call_trace_table(conn)` sets up schema. Deduplicates via GROUP BY. `qualname_prefix` uses LIKE matching. `list_modules()` returns modules by recency.

`CallTraceStoreLogger(store)`: buffers traces, writes on `flush()`. Skips `__main__` module functions.

## 5. Stub Generation

`build_module_stubs_from_traces(traces, max_typed_dict_size, existing_annotation_strategy, rewriter)`: groups traces by function, shrinks types, applies rewriter → dict of module name → `ModuleStub`.

`ExistingAnnotationStrategy`:
- `REPLICATE` — preserve existing annotations, fill traced types for unannotated params
- `IGNORE` — use traced types everywhere, replacing existing annotations
- `OMIT` — drop annotations for already-annotated params, fill only unannotated

`ModuleStub.render()` → full stub text with imports, function stubs, class stubs.

`FunctionStub(name, signature, kind, strip_modules=None, is_async=False)`: renders a function stub. `FunctionKind`: `MODULE`, `CLASS`, `INSTANCE`, `STATIC`, `PROPERTY`. `FunctionKind.from_callable(func)` classifies callables.

`ClassStub(name, function_stubs)`: renders class with sorted, indented method stubs.

When a method stub is rendered, the receiver parameter is emitted **without** a type annotation —
`self` for an instance method (`FunctionKind.INSTANCE`) or a property getter
(`FunctionKind.PROPERTY`), and `cls` for a classmethod (`FunctionKind.CLASS`) — even when a type was
captured for it during tracing. Every other parameter carries its inferred annotation as usual, and
the return type is annotated as usual. So an instance method traced as
`process(self=<MyClass>, x=5) -> "str"` renders `def process(self, x: int) -> str`.

A rendered method stub is preceded by the decorator line that matches its `FunctionKind`, on its
own line at the method's indentation: `FunctionKind.CLASS` emits a `@classmethod` line above the
`def`, `FunctionKind.STATIC` emits `@staticmethod`, and `FunctionKind.PROPERTY` emits `@property`;
`FunctionKind.INSTANCE` and `FunctionKind.MODULE` emit no decorator line. An async function or
method (`is_async=True`) renders with the `async def` keyword instead of `def`.

`FunctionDefinition.from_callable(func)`: introspects a function. `build_module_stubs(entries)`: builds stubs from definitions.

`render_annotation(anno)`: type → string (`int` → `"int"`, `NoneType` → `"None"`).

A type defined in another module is rendered by its **bare** (unqualified) name — e.g. a class
`Thing` from module `thing_mod` renders as `Thing`, not `thing_mod.Thing` — and the import
needed for it is emitted in the `from <module> import <Name>` form (e.g. `from thing_mod import
Thing`), not `import <module>`. This is the import form that generated stubs declare and that
`apply` inserts into the target source (and, under `--pep_563`, relocates into the
`if TYPE_CHECKING:` block per Section 7/8).

`StubIndexBuilder(module_re, max_typed_dict_size)`: `CallTraceLogger` that builds stubs from logged traces, keeping only those whose `funcname` (i.e. `func.__module__ + "." + func.__qualname__`) matches `module_re` — so a pattern like `r'.*\.my_func$'` selects one specific function. `get_stubs()` retrieves them.

### End-to-end in-code usage

The pieces compose into this pipeline: open a SQLite store, wrap it in a logger, trace some
calls, query the traces back, then build and render stubs.

```python
import sqlite3
from monkeytype.tracing import trace_calls
from monkeytype.db.sqlite import SQLiteStore, create_call_trace_table
from monkeytype.db.base import CallTraceStoreLogger
from monkeytype.stubs import build_module_stubs_from_traces
from monkeytype.typing import NoOpRewriter

conn = sqlite3.connect(":memory:")
create_call_trace_table(conn)
store = SQLiteStore(conn)
logger = CallTraceStoreLogger(store)

with trace_calls(logger, max_typed_dict_size=0):
    my_function("world")  # traced; CallTraceStoreLogger.flush() persists on exit

traces = [t.to_trace() for t in store.filter(module=my_function.__module__)]
stubs = build_module_stubs_from_traces(traces, max_typed_dict_size=0,
                                       existing_annotation_strategy=None,
                                       rewriter=NoOpRewriter())
stub_text = stubs[my_function.__module__].render()
```

## 6. Configuration

`Config`: abstract base with `trace_store()` (abstract), `trace_logger()`, `code_filter()`, `sample_rate()`, `type_rewriter()`, `max_typed_dict_size()`, `query_limit()`, `cli_context(command)`.

`DefaultConfig`: SQLite store from `MT_DB_PATH` env var (default `"monkeytype.sqlite3"`), `default_code_filter`, `DEFAULT_REWRITER`.

`default_code_filter(code)`: True for user code, False for stdlib/site-packages.

## 7. CLI

`python -m monkeytype` subcommands: `run <script>`, `stub <module>`, `apply <module>`, `list-modules`. `MT_DB_PATH` controls database path.

`apply <module>` accepts a `--pep_563` flag. When passed, annotation imports newly introduced by the applied stub (i.e. imports the inferred signatures need but the target source did not already have) are relocated into an `if TYPE_CHECKING:` block rather than added at module top level: `from typing import TYPE_CHECKING` is inserted and each new import is indented inside the guarded block. Implemented via the Section 8 `MoveImportsToTypeCheckingBlockVisitor`.

## 8. TYPE_CHECKING Import Transformer

`MoveImportsToTypeCheckingBlockVisitor`: a libcst codemod (importable from
`monkeytype.type_checking_imports_transformer`) that, given a set of newly-introduced annotation
imports, inserts `from typing import TYPE_CHECKING`, moves each of those imports into an indented
`if TYPE_CHECKING:` block, and removes them from the module top level, leaving the module's other
content unchanged. This is the mechanism behind `apply --pep_563` (Section 7).

## 9. Exceptions

`MonkeyTypeError` (base), `NameLookupError`, `InvalidTypeError`.
