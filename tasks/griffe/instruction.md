# Griffe -- Python API Signature Extractor

Build `griffe`, a Python library that extracts complete API signatures from Python source code using AST analysis. The library parses Python files statically, builds a rich object model of modules, classes, functions, attributes, and their type annotations, and supports docstring parsing in Google, NumPy, and Sphinx styles. It can also detect breaking API changes between two versions of a module.

## Dependencies

The environment is **offline** — there is no network access, and every dependency is already installed. Do **not** install anything (no `pip install`, no network calls). `griffe` itself requires **no external runtime dependencies beyond the Python standard library**: the entire implementation uses only `ast`, `inspect`, `enum`, `dataclasses`, `json`, and other stdlib modules. The project is installed for you by a `setup.sh` script that runs offline (it performs an editable install of your package against the pre-installed build backend); your job is to implement the package so that install and the test suite succeed.

## Package Structure

All public API is accessible from the top-level `griffe` package. Key categories:

- **Loading/visiting**: `GriffeLoader`, `load`, `temporary_visited_module`, `temporary_visited_package`, `temporary_pyfile`, `temporary_pypackage`
- **Object model**: `Module`, `Class`, `Function`, `Attribute`, `Object`, `Decorator`, `Docstring`, `Parameter`, `Parameters`
- **Expressions**: `ExprName`, `ExprAttribute`, `ExprSubscript`, and other `Expr*` classes for type annotations
- **Enumerations**: `Kind`, `ParameterKind`, `DocstringSectionKind`, `BreakageKind`
- **Docstring models**: `DocstringSection` and typed section classes for each section kind
- **Breaking changes**: `find_breaking_changes`, `Breakage`
- **Serialization**: `JSONEncoder`, `json_decoder`

## 1. Static Analysis Visitor

The core capability: parse Python source code into AST and visit it to build a structured model. The `temporary_visited_module(code, module_name="module", docstring_parser=None)` context manager creates a temporary file with the given code, visits it, and yields a `Module` object. `temporary_visited_package(name, modules={...})` does the same for multi-file packages. These helpers **dedent the supplied source** (equivalent to `textwrap.dedent`) before writing the temporary file and visiting it, so source given as an indented multi-line triple-quoted block — e.g. a code literal indented inside a calling function or test method — is normalized to column 0 prior to `ast.parse`. Source already at column 0 is unaffected (dedent is idempotent).

The visitor must handle: function definitions (sync and async) with all five parameter kinds (positional-only, positional-or-keyword, var-positional, keyword-only, var-keyword), type annotations (including generics, unions, PEP 604 `X | Y` syntax, PEP 585 built-in generics), class definitions with base classes and decorators, nested classes, `@staticmethod`/`@classmethod`/`@property` labels, `@abstractmethod` labels, `@dataclass` labels, `@typing.overload` with collected `.overloads` on the implementation, `__all__` export lists, module-level attributes and constants, and `import` / `from ... import ...` statements.

Imported names are surfaced as members too: visiting an `import x as y` or `from package import Name` statement adds a member to the enclosing module under the **bound name** (`y`, `Name`) — i.e. names a module imports or re-exports appear in its `.members` alongside the names it defines directly, keyed by the name they are bound to in that module's namespace.

An `async def` gets the `"async"` label (a plain `def` does not), so `async_func.has_labels("async")` is `True`. Each collected overload in `.overloads` is itself a `Function` carrying its own `parameters` and `returns` (the per-overload signature, not the implementation body).

## 2. Object Model

`Object` is the abstract base. Concrete subclasses: `Module`, `Class`, `Function`, `Attribute`. Each has: `name`, `path` (dotted), `parent`, `members` dict, `kind` (a `Kind` enum), `labels` set, `lineno`/`endlineno`, `docstring`, `exports`. An `Object` also supports subscript access to its members by name: `obj["name"]` is equivalent to `obj.members["name"]` (mirroring the `Parameters` string indexing in Section 3). Boolean properties: `is_module`, `is_class`, `is_function`, `is_attribute`. Method `filter_members(*predicates)` returns a dict-like members collection keyed by member name (the same mapping type as `members`, so `.keys()` and mapping access work on the result) containing only the members matching all predicates. `has_labels(*labels)` checks membership. `has_docstring` returns `True` if docstring is set (non-None).

`Function` additionally has: `parameters` (a `Parameters` container), `returns` (type annotation expression or None), `decorators` (list of `Decorator`), `overloads` (list of `Function` or None).

`Class` additionally has: `bases` (list of base class expressions), `decorators`.

`Attribute` additionally has: `value` — the assigned/default value as an expression (or None when unassigned), whose `str()` renders the Python source of that value following the convention in Section 6.

`Decorator` has: `value` (expression or string), `lineno`, `endlineno`. `str(decorator.value)` returns the decorator text (e.g. `"my_decorator"`).

## 3. Parameters

`Parameter` represents a function parameter with `name`, `annotation`, `kind`, and `default`. The `ParameterKind` enum has: `positional_only`, `positional_or_keyword`, `var_positional`, `keyword_only`, `var_keyword`. `parameter.required` is `True` when `default is None`.

`Parameters(*parameters)` collects its initial `Parameter` objects from positional variadic arguments; the container supports indexed access (by int or string name), iteration, membership checks, `add(param)` (raises `ValueError` on duplicate), and deletion.

## 4. Docstring Parsing

`Docstring(value, parser=None, parser_options=None)`. The `value` is cleaned with `inspect.cleandoc`. Property `lines` returns `value.split("\n")`. Method `parse(parser=None)` returns `list[DocstringSection]`.

Supported parsers (pass as string): `"google"`, `"numpy"`, `"sphinx"`. Each returns sections with `.kind` (a `DocstringSectionKind` enum) and `.value`. Section kinds include: `text`, `parameters`, `returns`, `raises`, `warns`, `yields`, `receives`, `examples`, `attributes`, `deprecated`, `admonition`.

Google-style sections are identified by headers like `Args:`, `Returns:`, `Raises:`, `Yields:`, `Receives:`, `Attributes:`, `Warns:`, `Examples:`. Parameters have `name`, `annotation`, `description`. For Returns/Yields/Receives, use `name (type): description` format to get the annotation parsed (e.g., `result (int): The value.`). Raises and Warns section entries expose the exception/warning type under `.annotation` (with an optional `.description`), mirroring the parameter entry model — e.g. a `Raises:` block of `ValueError: ...` yields an entry where `str(entry.annotation) == "ValueError"`. NumPy sections use underlined headers (`Parameters`, `Returns`, etc.). Sphinx uses `:param name:`, `:type name:`, `:returns:`, `:rtype:`, `:raises ExcType:` directives.

## 5. Breaking Changes Detection

`find_breaking_changes(old_obj, new_obj)` yields `Breakage` objects comparing two versions. `Breakage` has `.kind` (a `BreakageKind` enum), `.obj`, `.old_value`, `.new_value`. Breakage kinds include: `OBJECT_REMOVED`, `PARAMETER_REMOVED`, `PARAMETER_MOVED`, `PARAMETER_CHANGED_KIND`, `PARAMETER_CHANGED_DEFAULT`, `PARAMETER_CHANGED_REQUIRED`, `PARAMETER_ADDED_REQUIRED`, `RETURN_CHANGED_TYPE`, `ATTRIBUTE_CHANGED_TYPE`, `ATTRIBUTE_CHANGED_VALUE`, `CLASS_REMOVED_BASE`.

## 6. Expressions

Annotations and values are stored as expression trees. Key classes: `ExprName` for identifiers, `ExprAttribute` for dotted attribute access, `ExprSubscript` for generics like `List[int]`. All have `__str__` returning the Python source representation. String literal defaults use single quotes in their `str()` representation (e.g., `str(param.default) == "'hello'"`).

## 7. JSON Serialization

`JSONEncoder` handles griffe objects for `json.dumps`. `json_decoder` is an `object_hook` for `json.loads`. Objects have `.as_dict(full=False)` returning a serializable dictionary. Round-trip: members are keyed by name. The round-trip preserves signature content, not just member names and kinds — a deserialized `Function` exposes the same `parameters` (names and annotations) and `returns` as the original.

## 8. Loader

`GriffeLoader(search_paths=None, docstring_parser=None, ...)` finds and loads installed packages. `loader.load("module_name")` returns an `Object`. Convenience: `griffe.load("module_name")` does the same. The loader supports both source-based (visiting) and runtime (inspection) analysis.

A loaded module/package surfaces not only the names **defined** in its source but also the names it **imports or re-exports** (per the import contract in Section 1): when a package's top-level `__init__.py` brings a name into its namespace with `from .submodule import Name`, that `Name` is a member of the loaded package object, keyed by its bound name.

## 9. Enumerations

`Kind`: `MODULE="module"`, `CLASS="class"`, `FUNCTION="function"`, `ATTRIBUTE="attribute"`. `ParameterKind`: `positional_only="positional-only"`, `positional_or_keyword="positional or keyword"`, `var_positional="variadic positional"`, `keyword_only="keyword-only"`, `var_keyword="variadic keyword"`. `DocstringSectionKind`: `text="text"`, `parameters="parameters"`, `returns="returns"`, `raises="raises"`, `warns="warns"`, `yields="yields"`, `receives="receives"`, `examples="examples"`, `attributes="attributes"`, `deprecated="deprecated"`, `admonition="admonition"`. `BreakageKind`: `OBJECT_REMOVED="Public object was removed"`, `PARAMETER_REMOVED="Parameter was removed"`, etc.

## 10. Test Helpers

`temporary_visited_module(code, module_name="module", docstring_parser=None)` - context manager yielding `Module`. `temporary_visited_package(name, modules={filename: code})` - context manager yielding the top `Module` with submodules as members. `temporary_pyfile(code)` and `temporary_pypackage(name, modules)` create temp files without visiting.

All four helpers **dedent the source they are given** (`textwrap.dedent`) before writing it to the temporary file: `temporary_visited_module` and `temporary_pyfile` dedent their `code` argument, and `temporary_visited_package` and `temporary_pypackage` dedent each module's contents in the `modules` mapping. This means indented multi-line triple-quoted source (such as a code literal embedded inside a calling function or test method body) is accepted and visited as if written at column 0; passing already-unindented source is equally valid since dedent leaves it unchanged.
