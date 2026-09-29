"""Tests for griffe — a Python API signature extraction library using AST analysis."""

import json
import textwrap


class TestVisitorFunctionSignatures:
    """Test extraction of function signatures via the AST visitor."""

    def test_extract_simple_function_with_typed_parameters(self):
        """Extract a function with type-annotated parameters and return type, verifying
        parameter names, kinds, annotations, defaults, and the return annotation."""
        from griffe import temporary_visited_module, ParameterKind

        code = '''
        def greet(name: str, greeting: str = "hello", *, loud: bool = False) -> str:
            """Greet someone."""
            if loud:
                return f"{greeting.upper()}, {name.upper()}!"
            return f"{greeting}, {name}!"
        '''
        with temporary_visited_module(code) as module:
            func = module["greet"]
            assert func.is_function
            assert func.name == "greet"

            params = list(func.parameters)
            assert len(params) == 3

            assert params[0].name == "name"
            assert str(params[0].annotation) == "str"
            assert params[0].kind == ParameterKind.positional_or_keyword
            assert params[0].default is None

            assert params[1].name == "greeting"
            assert str(params[1].annotation) == "str"
            assert params[1].kind == ParameterKind.positional_or_keyword
            assert str(params[1].default) == "'hello'"

            assert params[2].name == "loud"
            assert str(params[2].annotation) == "bool"
            assert params[2].kind == ParameterKind.keyword_only
            assert str(params[2].default) == "False"

            assert func.returns is not None
            assert str(func.returns) == "str"
            assert func.has_docstring

    def test_extract_variadic_and_positional_only_parameters(self):
        """Extract a function using positional-only (/), *args, and **kwargs,
        verifying all five parameter kinds are correctly classified."""
        from griffe import temporary_visited_module, ParameterKind

        code = '''
        def complex_sig(a: int, b: float, /, c: str = "x", *args: int, d: bool = True, **kwargs: str) -> None:
            """A function with all parameter kinds."""
            pass
        '''
        with temporary_visited_module(code) as module:
            func = module["complex_sig"]
            params = {p.name: p for p in func.parameters}

            assert params["a"].kind == ParameterKind.positional_only
            assert params["b"].kind == ParameterKind.positional_only
            assert params["c"].kind == ParameterKind.positional_or_keyword
            assert params["args"].kind == ParameterKind.var_positional
            assert params["d"].kind == ParameterKind.keyword_only
            assert params["kwargs"].kind == ParameterKind.var_keyword

            assert str(params["args"].annotation) == "int"
            assert str(params["kwargs"].annotation) == "str"


class TestVisitorClassHierarchy:
    """Test extraction of class definitions, inheritance, and nested structures."""

    def test_extract_class_with_bases_methods_and_attributes(self):
        """Extract a class with base classes, methods, a class variable, and instance
        attributes set in __init__, verifying the full member hierarchy."""
        from griffe import temporary_visited_module, Kind

        code = '''
        class Animal:
            """Base animal class."""
            kingdom: str = "Animalia"

            def __init__(self, name: str, legs: int = 4) -> None:
                """Initialize animal."""
                self.name = name
                self.legs = legs

            def speak(self) -> str:
                """Make a sound."""
                return ""

        class Dog(Animal):
            """A dog."""
            def speak(self) -> str:
                """Bark."""
                return "Woof!"

            def fetch(self, item: str) -> str:
                """Fetch an item."""
                return item
        '''
        with temporary_visited_module(code) as module:
            animal = module["Animal"]
            assert animal.is_class
            assert animal.kind == Kind.CLASS
            assert "kingdom" in animal.members
            assert "__init__" in animal.members
            assert "speak" in animal.members

            init = animal.members["__init__"]
            assert init.is_function
            init_params = list(init.parameters)
            assert init_params[0].name == "self"
            assert init_params[1].name == "name"
            assert init_params[2].name == "legs"
            assert str(init_params[2].default) == "4"

            dog = module["Dog"]
            assert dog.is_class
            bases = [str(b) for b in dog.bases]
            assert "Animal" in bases
            assert "speak" in dog.members
            assert "fetch" in dog.members

    def test_extract_nested_classes(self):
        """Extract nested class definitions, verifying that an inner class is accessible
        as a member of its enclosing class and exposes its own members."""
        from griffe import temporary_visited_module

        code = '''
        class Outer:
            """Outer class."""

            class Inner:
                """Inner class."""
                value: int = 42

                def method(self) -> int:
                    """An inner method."""
                    return self.value
        '''
        with temporary_visited_module(code) as module:
            outer = module["Outer"]
            assert outer.is_class
            assert "Inner" in outer.members

            inner = outer.members["Inner"]
            assert inner.is_class
            assert inner.path == "module.Outer.Inner"
            assert "value" in inner.members
            assert "method" in inner.members
            assert inner.members["method"].is_function


class TestVisitorModuleStructure:
    """Test extraction of module-level constructs: imports, __all__, attributes."""

    def test_extract_module_level_attributes_and_docstrings(self):
        """Extract module-level constants, type annotations, and the module docstring,
        verifying values and the module's member enumeration."""
        from griffe import temporary_visited_module, Kind

        code = '''
        """A sample module for testing."""

        VERSION: str = "1.0.0"
        MAX_RETRIES: int = 3
        DEBUG = False

        def helper() -> None:
            """A helper function."""
            pass

        class Config:
            """Configuration class."""
            timeout: float = 30.0
        '''
        with temporary_visited_module(code) as module:
            assert module.is_module
            assert module.kind == Kind.MODULE
            assert module.has_docstring
            assert module.docstring.value == "A sample module for testing."

            assert "VERSION" in module.members
            assert "MAX_RETRIES" in module.members
            assert "DEBUG" in module.members
            assert "helper" in module.members
            assert "Config" in module.members

            version_attr = module.members["VERSION"]
            assert version_attr.is_attribute
            assert str(version_attr.annotation) == "str"

    def test_extract_package_with_submodules(self):
        """Load a temporary package with submodules, verifying the module
        hierarchy and cross-module member accessibility."""
        from griffe import temporary_visited_package

        with temporary_visited_package(
            "mypkg",
            modules={
                "__init__.py": "from mypkg.utils import helper",
                "utils.py": textwrap.dedent('''
                    def helper(x: int) -> int:
                        """Double x."""
                        return x * 2
                '''),
                "models.py": textwrap.dedent('''
                    class User:
                        """A user model."""
                        def __init__(self, name: str) -> None:
                            self.name = name
                '''),
            },
        ) as module:
            assert module.is_module
            assert "utils" in module.members
            assert "models" in module.members

            utils = module.members["utils"]
            assert "helper" in utils.members
            helper_func = utils.members["helper"]
            assert helper_func.is_function
            params = list(helper_func.parameters)
            assert params[0].name == "x"
            assert str(params[0].annotation) == "int"

            models = module.members["models"]
            assert "User" in models.members


class TestDocstringParsing:
    """Test parsing of docstrings in Google, NumPy, and Sphinx styles."""

    def test_parse_google_style_docstring(self):
        """Parse a Google-style docstring extracting parameters, return type,
        raises section, and examples, verifying each section's kind and content."""
        from griffe import Docstring, DocstringSectionKind

        docstring = Docstring(
            textwrap.dedent('''
                Compute the factorial of n.

                This function uses an iterative approach for efficiency.

                Args:
                    n (int): The non-negative integer.
                    validate (bool): Whether to validate input. Defaults to True.

                Returns:
                    result (int): The factorial value.

                Raises:
                    ValueError: If n is negative.

                Examples:
                    >>> factorial(5)
                    120
                    >>> factorial(0)
                    1
            '''),
            parser="google",
        )

        sections = docstring.parse()
        kinds = [s.kind for s in sections]
        assert DocstringSectionKind.text in kinds
        assert DocstringSectionKind.parameters in kinds
        assert DocstringSectionKind.returns in kinds
        assert DocstringSectionKind.raises in kinds
        assert DocstringSectionKind.examples in kinds

        param_section = next(s for s in sections if s.kind == DocstringSectionKind.parameters)
        param_names = [p.name for p in param_section.value]
        assert param_names == ["n", "validate"]
        assert str(param_section.value[0].annotation) == "int"
        assert "non-negative" in param_section.value[0].description

        returns_section = next(s for s in sections if s.kind == DocstringSectionKind.returns)
        assert str(returns_section.value[0].annotation) == "int"

        raises_section = next(s for s in sections if s.kind == DocstringSectionKind.raises)
        assert str(raises_section.value[0].annotation) == "ValueError"

    def test_parse_numpy_style_docstring(self):
        """Parse a NumPy-style docstring with Parameters, Returns, and Raises sections,
        verifying parameter annotations and descriptions."""
        from griffe import Docstring, DocstringSectionKind

        docstring = Docstring(
            textwrap.dedent('''
                Transform data using the given matrix.

                Parameters
                ----------
                data : list of float
                    The input data vector.
                matrix : list of list of float
                    The transformation matrix.
                inplace : bool, optional
                    Whether to modify in place. Default is False.

                Returns
                -------
                list of float
                    The transformed data vector.

                Raises
                ------
                ValueError
                    If dimensions do not match.
            '''),
            parser="numpy",
        )

        sections = docstring.parse()
        kinds = [s.kind for s in sections]
        assert DocstringSectionKind.parameters in kinds
        assert DocstringSectionKind.returns in kinds
        assert DocstringSectionKind.raises in kinds

        param_section = next(s for s in sections if s.kind == DocstringSectionKind.parameters)
        param_names = [p.name for p in param_section.value]
        assert param_names == ["data", "matrix", "inplace"]
        assert "list of float" in str(param_section.value[0].annotation)
        assert "input data" in param_section.value[0].description

    def test_parse_sphinx_style_docstring(self):
        """Parse a Sphinx-style docstring with :param:, :type:, :returns:, and :raises:
        directives, verifying structured extraction of each field."""
        from griffe import Docstring, DocstringSectionKind

        docstring = Docstring(
            textwrap.dedent('''
                Connect to a remote server.

                :param host: The hostname or IP address.
                :type host: str
                :param port: The port number.
                :type port: int
                :param timeout: Connection timeout in seconds.
                :type timeout: float
                :returns: A connection object.
                :rtype: Connection
                :raises ConnectionError: If the connection fails.
            '''),
            parser="sphinx",
        )

        sections = docstring.parse()
        kinds = [s.kind for s in sections]
        assert DocstringSectionKind.parameters in kinds
        assert DocstringSectionKind.returns in kinds
        assert DocstringSectionKind.raises in kinds

        param_section = next(s for s in sections if s.kind == DocstringSectionKind.parameters)
        param_names = [p.name for p in param_section.value]
        assert "host" in param_names
        assert "port" in param_names
        assert "timeout" in param_names

        host_param = next(p for p in param_section.value if p.name == "host")
        assert str(host_param.annotation) == "str"
        assert "hostname" in host_param.description


class TestTypeAnnotationExtraction:
    """Test extraction of complex type annotations from source code."""

    def test_extract_complex_generic_annotations(self):
        """Extract functions with generic type annotations (Optional, Union, Dict, List,
        Callable), verifying the annotation string representations."""
        from griffe import temporary_visited_module

        code = '''
        from typing import Optional, Union, Dict, List, Callable, Tuple

        def process(
            items: List[Dict[str, int]],
            callback: Callable[[str, int], bool],
            default: Optional[Union[str, int]] = None,
        ) -> Tuple[List[str], int]:
            """Process items with a callback."""
            pass
        '''
        with temporary_visited_module(code) as module:
            func = module["process"]
            params = {p.name: p for p in func.parameters}

            assert str(params["items"].annotation) == "List[Dict[str, int]]"
            assert str(params["callback"].annotation) == "Callable[[str, int], bool]"
            assert str(params["default"].annotation) == "Optional[Union[str, int]]"
            assert str(func.returns) == "Tuple[List[str], int]"

    def test_extract_modern_type_syntax_annotations(self):
        """Extract functions using PEP 604 union syntax (X | Y) and PEP 585 built-in
        generics (list[str], dict[str, int]), verifying correct representation."""
        from griffe import temporary_visited_module

        code = '''
        def modern(
            names: list[str],
            mapping: dict[str, int],
            value: int | str | None = None,
        ) -> list[int] | None:
            """Modern type hints."""
            pass
        '''
        with temporary_visited_module(code) as module:
            func = module["modern"]
            params = {p.name: p for p in func.parameters}

            assert str(params["names"].annotation) == "list[str]"
            assert str(params["mapping"].annotation) == "dict[str, int]"
            assert str(params["value"].annotation) == "int | str | None"
            assert str(func.returns) == "list[int] | None"


class TestObjectModel:
    """Test the Object model hierarchy: path resolution, member access, kind checks."""

    def test_object_path_and_parent_chain(self):
        """Load a module with nested class and method, verifying the dotted path and
        parent chain for each object in the hierarchy."""
        from griffe import temporary_visited_module

        code = '''
        class Engine:
            """Database engine."""
            class Connection:
                """A database connection."""
                def execute(self, query: str) -> list:
                    """Execute a query."""
                    return []
        '''
        with temporary_visited_module(code, module_name="db") as module:
            engine = module["Engine"]
            assert engine.path == "db.Engine"
            assert engine.parent is module

            conn = engine.members["Connection"]
            assert conn.path == "db.Engine.Connection"
            assert conn.parent is engine

            execute = conn.members["execute"]
            assert execute.path == "db.Engine.Connection.execute"
            assert execute.parent is conn

    def test_object_kind_checks_and_member_filtering(self):
        """Verify is_module, is_class, is_function, is_attribute for different
        object types, and use filter_members to select only classes."""
        from griffe import temporary_visited_module, Kind

        code = '''
        CONSTANT: int = 42

        def func() -> None:
            """A function."""
            pass

        class MyClass:
            """A class."""
            pass

        class AnotherClass:
            """Another class."""
            pass
        '''
        with temporary_visited_module(code) as module:
            assert module.members["CONSTANT"].is_attribute
            assert module.members["func"].is_function
            assert module.members["MyClass"].is_class
            assert module.members["AnotherClass"].is_class

            classes = module.filter_members(lambda m: m.is_class)
            assert set(classes.keys()) == {"MyClass", "AnotherClass"}


class TestParametersContainer:
    """Test the Parameters container: indexed access, name lookup, add, delete, contains."""

    def test_parameters_container_operations(self):
        """Create a Parameters container, access parameters by index and name,
        add and delete parameters, and verify membership checks."""
        from griffe import Parameter, Parameters, ParameterKind

        p1 = Parameter("x", annotation="int", kind=ParameterKind.positional_or_keyword)
        p2 = Parameter("y", annotation="str", kind=ParameterKind.positional_or_keyword, default='"hi"')
        p3 = Parameter("z", annotation="bool", kind=ParameterKind.keyword_only, default="True")

        params = Parameters(p1, p2, p3)

        assert len(params) == 3
        assert params[0] is p1
        assert params["x"] is p1
        assert params["y"] is p2
        assert "z" in params
        assert "w" not in params

        p4 = Parameter("w", annotation="float", kind=ParameterKind.keyword_only)
        params.add(p4)
        assert len(params) == 4
        assert params["w"] is p4

        del params["y"]
        assert len(params) == 3
        assert "y" not in params

        import pytest
        with pytest.raises(ValueError):
            params.add(Parameter("x", annotation="int", kind=ParameterKind.positional_or_keyword))


class TestJSONSerialization:
    """Test JSON serialization and deserialization of griffe objects."""

    def test_serialize_and_deserialize_module(self):
        """Serialize a visited module to JSON and deserialize it back, verifying
        that the round-tripped object retains function signatures and class structure."""
        from griffe import temporary_visited_module, JSONEncoder, json_decoder

        code = '''
        """My library."""

        def add(a: int, b: int) -> int:
            """Add two numbers."""
            return a + b

        class Point:
            """A 2D point."""
            def __init__(self, x: float, y: float) -> None:
                self.x = x
                self.y = y
        '''
        with temporary_visited_module(code) as module:
            data_dict = module.as_dict(full=True)
            json_str = json.dumps(data_dict, cls=JSONEncoder, indent=2)
            assert isinstance(json_str, str)

            assert data_dict["name"] == module.name
            assert "add" in data_dict["members"]
            assert "Point" in data_dict["members"]

            restored = json.loads(json_str, object_hook=json_decoder)
            assert restored.name == module.name
            assert "add" in restored.members
            assert "Point" in restored.members
            assert restored.members["add"].is_function
            assert restored.members["Point"].is_class

            # The round-trip must preserve actual signature content, not just member
            # presence and kind: parameter names, annotations, and the return type.
            restored_add = restored.members["add"]
            assert [p.name for p in restored_add.parameters] == ["a", "b"]
            assert str(restored_add.parameters["a"].annotation) == "int"
            assert str(restored_add.parameters["b"].annotation) == "int"
            assert str(restored_add.returns) == "int"


class TestBreakingChangesDetection:
    """Test API diff / breaking change detection between two versions of a module."""

    def test_detect_removed_function_and_changed_parameter(self):
        """Load two versions of a module where a function was removed and a parameter
        changed from optional to required, verifying the detected breakages."""
        from griffe import temporary_visited_module, find_breaking_changes, BreakageKind

        old_code = '''
        def compute(x: int, y: int = 0) -> int:
            """Compute sum."""
            return x + y

        def deprecated_func() -> None:
            """Will be removed."""
            pass
        '''
        new_code = '''
        def compute(x: int, y: int) -> int:
            """Compute sum."""
            return x + y
        '''
        with temporary_visited_module(old_code, module_name="api") as old_mod:
            with temporary_visited_module(new_code, module_name="api") as new_mod:
                breakages = list(find_breaking_changes(old_mod, new_mod))

                breakage_kinds = [b.kind for b in breakages]
                assert BreakageKind.OBJECT_REMOVED in breakage_kinds
                assert BreakageKind.PARAMETER_CHANGED_REQUIRED in breakage_kinds

                removed = next(b for b in breakages if b.kind == BreakageKind.OBJECT_REMOVED)
                assert "deprecated_func" in removed.obj.path

    def test_detect_parameter_kind_change_and_added_required(self):
        """Detect when a parameter is moved, its kind changes, and a new required
        parameter is added, covering multiple breakage types simultaneously."""
        from griffe import temporary_visited_module, find_breaking_changes, BreakageKind

        old_code = '''
        def connect(host: str, port: int = 80) -> None:
            """Connect to server."""
            pass
        '''
        new_code = '''
        def connect(host: str, port: int = 80, *, auth_token: str) -> None:
            """Connect to server."""
            pass
        '''
        with temporary_visited_module(old_code, module_name="net") as old_mod:
            with temporary_visited_module(new_code, module_name="net") as new_mod:
                breakages = list(find_breaking_changes(old_mod, new_mod))
                breakage_kinds = [b.kind for b in breakages]
                assert BreakageKind.PARAMETER_ADDED_REQUIRED in breakage_kinds


class TestDecoratorExtraction:
    """Test extraction and representation of decorators."""

    def test_extract_decorated_functions_and_properties(self):
        """Extract functions with various decorators (@staticmethod, @classmethod,
        @property, custom decorators with arguments), verifying labels and decorator values."""
        from griffe import temporary_visited_module

        code = '''
        import functools

        def my_decorator(func):
            """A custom decorator."""
            return func

        class Service:
            """A service class."""

            @staticmethod
            def get_version() -> str:
                """Return version."""
                return "1.0"

            @classmethod
            def from_config(cls, path: str) -> "Service":
                """Create from config."""
                return cls()

            @property
            def status(self) -> str:
                """Return status."""
                return "ok"

            @my_decorator
            def process(self) -> None:
                """Process data."""
                pass
        '''
        with temporary_visited_module(code) as module:
            svc = module["Service"]

            get_ver = svc.members["get_version"]
            assert get_ver.has_labels("staticmethod")

            from_cfg = svc.members["from_config"]
            assert from_cfg.has_labels("classmethod")

            status = svc.members["status"]
            assert status.has_labels("property")

            process = svc.members["process"]
            assert len(process.decorators) == 1
            assert str(process.decorators[0].value) == "my_decorator"


class TestAsyncAndGeneratorExtraction:
    """Test extraction of async functions and generator functions."""

    def test_extract_async_functions_and_coroutines(self):
        """Extract async def functions and verify they are correctly marked as
        coroutines with their parameters and return types intact."""
        from griffe import temporary_visited_module

        code = '''
        import asyncio

        async def fetch_data(url: str, timeout: float = 30.0) -> bytes:
            """Fetch data from a URL."""
            return b""

        async def stream_items(source: str) -> list:
            """Stream items from source."""
            return []

        def load_cache(path: str) -> bytes:
            """Load cached data synchronously."""
            return b""

        class AsyncClient:
            """An async HTTP client."""
            async def get(self, url: str) -> bytes:
                """Perform GET request."""
                return b""
        '''
        with temporary_visited_module(code) as module:
            fetch = module["fetch_data"]
            assert fetch.is_function
            params = list(fetch.parameters)
            assert params[0].name == "url"
            assert str(fetch.returns) == "bytes"
            # The distinguishing behavior of async extraction: the coroutine carries an
            # "async" label. A plain sync def with the same signature would not.
            assert fetch.has_labels("async")

            client = module["AsyncClient"]
            get_method = client.members["get"]
            assert get_method.is_function
            get_params = list(get_method.parameters)
            assert get_params[0].name == "self"
            assert get_params[1].name == "url"
            assert get_method.has_labels("async")

            # Negative control: an ordinary def must NOT be marked async.
            assert not module["load_cache"].has_labels("async")


class TestLoaderIntegration:
    """Test the GriffeLoader for loading real installed packages."""

    def test_load_installed_module_and_convenience_wrapper(self):
        """Load an installed stdlib module via GriffeLoader, verify its well-known public
        members, and confirm the top-level griffe.load() shortcut yields the same members."""
        from griffe import GriffeLoader, load

        loader = GriffeLoader()
        json_mod = loader.load("json")

        assert json_mod.is_module
        members = set(json_mod.members)
        assert {"JSONEncoder", "JSONDecoder", "dumps", "loads", "dump", "load"} <= members

        # griffe.load(...) is documented as a shortcut for GriffeLoader(...).load(...);
        # verify the convenience wrapper surfaces the identical member set.
        assert set(load("json").members.keys()) == members


class TestDocstringModel:
    """Test the Docstring model object directly."""

    def test_docstring_value_cleaned_and_parsed(self):
        """Create a Docstring with extra whitespace, verify it is cleaned by
        inspect.cleandoc, and parse it to get structured sections."""
        from griffe import Docstring, DocstringSectionKind

        raw = """
            This is the summary.

            This is a detailed description
            spanning multiple lines.

            Args:
                x: The x value.
                y: The y value.
        """
        ds = Docstring(raw, parser="google")
        assert ds.value.startswith("This is the summary.")
        assert "\n" in ds.value

        lines = ds.lines
        assert lines[0] == "This is the summary."

        sections = ds.parse()
        assert len(sections) >= 2
        text_section = sections[0]
        assert text_section.kind == DocstringSectionKind.text

        param_section = next(s for s in sections if s.kind == DocstringSectionKind.parameters)
        assert len(param_section.value) == 2
        assert param_section.value[0].name == "x"
        assert param_section.value[1].name == "y"


class TestExpressionModel:
    """Test expression/annotation model classes."""

    def test_annotation_expression_rendering_from_visited_code(self):
        """Extract annotations containing dotted attribute access and nested generics from
        visited code and verify the expression model renders the exact canonical source string."""
        from griffe import temporary_visited_module

        code = '''
        import os.path
        from typing import Dict, List

        def f(p: os.path.PathLike, mapping: Dict[str, List[int]]) -> None:
            """A function with dotted-attribute and nested-generic annotations."""
            pass
        '''
        with temporary_visited_module(code) as module:
            func = module["f"]
            params = {p.name: p for p in func.parameters}

            assert str(params["p"].annotation) == "os.path.PathLike"
            assert str(params["mapping"].annotation) == "Dict[str, List[int]]"


class TestGriffeLoaderDocstringParser:
    """Test GriffeLoader with docstring parser configuration."""

    def test_loader_with_google_docstring_parser(self):
        """Load a temporary package with the google docstring parser pre-configured
        and verify that docstrings are automatically parsed."""
        from griffe import temporary_visited_module, DocstringSectionKind

        code = '''
        def transform(data: list, factor: float = 1.0) -> list:
            """Transform data by a factor.

            Args:
                data: The input data.
                factor: The multiplication factor.

            Returns:
                The transformed data.
            """
            return [x * factor for x in data]
        '''
        with temporary_visited_module(code, docstring_parser="google") as module:
            func = module["transform"]
            assert func.has_docstring

            sections = func.docstring.parse()
            kinds = [s.kind for s in sections]
            assert DocstringSectionKind.text in kinds
            assert DocstringSectionKind.parameters in kinds
            assert DocstringSectionKind.returns in kinds

            # The google parser must be plumbed through the visitor and actually parse the
            # Args block: the two declared parameters, in order, with their descriptions.
            params_section = next(s for s in sections if s.kind == DocstringSectionKind.parameters)
            assert [p.name for p in params_section.value] == ["data", "factor"]
            assert params_section.value[0].description == "The input data."
            assert params_section.value[1].description == "The multiplication factor."


class TestComplexVisitorScenarios:
    """Test complex AST visitor scenarios: conditional imports, __all__, overloads."""

    def test_extract_overloaded_function_signatures(self):
        """Extract a function with @typing.overload decorators, verifying that
        the overloads are correctly collected alongside the implementation."""
        from griffe import temporary_visited_module

        code = '''
        from typing import overload

        @overload
        def process(x: int) -> int: ...

        @overload
        def process(x: str) -> str: ...

        def process(x):
            """Process an int or string."""
            return x
        '''
        with temporary_visited_module(code) as module:
            func = module["process"]
            assert func.is_function
            assert func.has_docstring
            overloads = func.overloads
            assert overloads is not None
            assert len(overloads) == 2

            # The two collected overloads must carry their own distinct signatures (not the
            # implementation body, and not swapped): (x: int) -> int and (x: str) -> str.
            assert str(overloads[0].parameters["x"].annotation) == "int"
            assert str(overloads[0].returns) == "int"
            assert str(overloads[1].parameters["x"].annotation) == "str"
            assert str(overloads[1].returns) == "str"

    def test_extract_module_with_all_export_list(self):
        """Extract a module with __all__ and verify the exports list is correctly
        populated with the declared public names."""
        from griffe import temporary_visited_module

        code = '''
        __all__ = ["PublicClass", "public_func"]

        class PublicClass:
            """Public."""
            pass

        class _PrivateClass:
            """Private."""
            pass

        def public_func() -> None:
            """Public function."""
            pass

        def _private_func() -> None:
            """Private function."""
            pass
        '''
        with temporary_visited_module(code) as module:
            assert module.exports is not None
            export_names = [str(e) for e in module.exports]
            assert "PublicClass" in export_names
            assert "public_func" in export_names
            assert "_PrivateClass" not in export_names
            assert "_private_func" not in export_names

    def test_extract_dataclass_fields_and_defaults(self):
        """Extract a dataclass and verify that fields with their types, defaults,
        and field() calls are correctly represented."""
        from griffe import temporary_visited_module

        code = '''
        from dataclasses import dataclass, field

        @dataclass
        class Config:
            """Application configuration."""
            host: str = "localhost"
            port: int = 8080
            debug: bool = False
            tags: list = field(default_factory=list)
        '''
        with temporary_visited_module(code) as module:
            config = module["Config"]
            assert config.is_class
            assert config.has_labels("dataclass")

            assert "host" in config.members
            host = config.members["host"]
            assert host.is_attribute
            assert str(host.annotation) == "str"
            assert str(host.value) == "'localhost'"

            assert "port" in config.members
            assert str(config.members["port"].value) == "8080"

            assert "debug" in config.members
            assert str(config.members["debug"].value) == "False"

            assert "tags" in config.members
            assert str(config.members["tags"].value) == "field(default_factory=list)"

    def test_extract_abstract_base_class(self):
        """Extract an abstract class with @abstractmethod decorators and verify
        the abstract methods are correctly marked."""
        from griffe import temporary_visited_module

        code = '''
        from abc import ABC, abstractmethod

        class Shape(ABC):
            """Abstract shape."""

            @abstractmethod
            def area(self) -> float:
                """Calculate area."""
                pass

            @abstractmethod
            def perimeter(self) -> float:
                """Calculate perimeter."""
                pass

            def describe(self) -> str:
                """Describe the shape."""
                return f"I am a {type(self).__name__}"
        '''
        with temporary_visited_module(code) as module:
            shape = module["Shape"]
            assert shape.is_class
            bases = [str(b) for b in shape.bases]
            assert "ABC" in bases

            area = shape.members["area"]
            assert area.has_labels("abstractmethod")

            perimeter = shape.members["perimeter"]
            assert perimeter.has_labels("abstractmethod")

            describe = shape.members["describe"]
            assert not describe.has_labels("abstractmethod")


class TestDocstringGoogleAdvanced:
    """Test advanced Google-style docstring features: attributes, warns, yields."""

    def test_google_docstring_with_attributes_and_warns(self):
        """Parse a Google-style docstring with Attributes and Warns sections,
        verifying the structured extraction of each."""
        from griffe import Docstring, DocstringSectionKind

        docstring = Docstring(
            textwrap.dedent('''
                A class that manages connections.

                Attributes:
                    host (str): The server hostname.
                    port (int): The server port number.
                    connected (bool): Whether currently connected.

                Warns:
                    DeprecationWarning: If using legacy protocol.
            '''),
            parser="google",
        )

        sections = docstring.parse()
        kinds = [s.kind for s in sections]
        assert DocstringSectionKind.attributes in kinds
        assert DocstringSectionKind.warns in kinds

        attrs_section = next(s for s in sections if s.kind == DocstringSectionKind.attributes)
        attr_names = [a.name for a in attrs_section.value]
        assert attr_names == ["host", "port", "connected"]
        assert str(attrs_section.value[0].annotation) == "str"

    def test_google_docstring_yields_and_receives(self):
        """Parse a Google-style docstring with Yields and Receives sections for
        a generator function, verifying the generator-specific section types."""
        from griffe import Docstring, DocstringSectionKind

        docstring = Docstring(
            textwrap.dedent('''
                A generator that processes items.

                Yields:
                    item (str): The next processed item.

                Receives:
                    count (int): The number of items to skip.
            '''),
            parser="google",
        )

        sections = docstring.parse()
        kinds = [s.kind for s in sections]
        assert DocstringSectionKind.yields in kinds
        assert DocstringSectionKind.receives in kinds

        yields_section = next(s for s in sections if s.kind == DocstringSectionKind.yields)
        assert len(yields_section.value) == 1
        assert str(yields_section.value[0].annotation) == "str"
        assert yields_section.value[0].name == "item"

        receives_section = next(s for s in sections if s.kind == DocstringSectionKind.receives)
        assert len(receives_section.value) == 1
        assert receives_section.value[0].name == "count"
        assert str(receives_section.value[0].annotation) == "int"
