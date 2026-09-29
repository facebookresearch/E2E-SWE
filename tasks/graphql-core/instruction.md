# graphql-core

Python reference implementation of the GraphQL specification. Pure Python, zero runtime dependencies. Importable as `graphql`. Package name `graphql-core`.

## Dependencies

- This package has **no runtime dependencies** — it is pure Python and uses only the standard library.
- The environment is **offline**: everything needed (the Python toolchain and the project's build backend) is already installed. Do **not** attempt to install anything — there is no network.
- The project is installed/built by a `setup.sh` that runs **offline**. Provide a `pyproject.toml` (or `setup.cfg`/`setup.py`) that declares the package as `graphql-core` with the import name `graphql`, installable via `pip install -e . --no-build-isolation` against the pre-installed build backend.

The package exposes version information: `graphql.version` (string like "3.3.0a12"), `graphql.version_info` (a VersionInfo named tuple with major, minor, micro, releaselevel, serial).

## Package Structure

Top-level `graphql` package with sub-packages: `language`, `type`, `validation`, `execution`, `error`, `utilities`, `pyutils`. All public names are re-exported from `graphql.__init__`.

## 1. Error (`graphql.error`)

`GraphQLError(message, nodes=None, source=None, positions=None, path=None, original_error=None, extensions=None)` -- subclass of Exception. Uses `__slots__`. Attributes: `message` (str), `locations` (list of SourceLocation or None), `path` (list of str|int or None), `nodes` (list of Node or None), `source` (Source or None), `positions` (collection of int or None), `original_error` (Exception or None), `extensions` (dict or empty dict).

Has `__eq__` comparing all slots except original_error. Has `__hash__` from Exception. The `formatted` property returns a `GraphQLFormattedError` TypedDict with keys: `message`, optionally `locations` (list of `{"line": int, "column": int}`), `path`, `extensions`.

`__str__` returns the message followed by printed source locations.

`GraphQLSyntaxError(source, position, description)` -- subclass of GraphQLError. Stores `description` attribute. Message: `"Syntax Error: {description}"`.

`located_error(original_error, nodes=None, path=None)` -- wraps exception as GraphQLError with location info. If already a GraphQLError with path, returns unchanged.

## 2. Python Utilities (`graphql.pyutils`)

**Undefined**: singleton of UndefinedType. Represents missing/invalid values. `bool(Undefined)` is False. `Undefined == None` is True. `repr(Undefined)` is `"Undefined"`.

**Path**: NamedTuple `(prev: Path|None, key: str|int, typename: str|None)`. `as_list()` returns list of keys root-to-current. `add_key(key, typename=None)` returns new Path.

**resolve_thunk(thunk)**: if callable, calls it; otherwise returns as-is. Used for lazy circular type references.

**suggestion_list(input_, options)**: returns options similar to `input_`, ordered by lexical (Damerau-Levenshtein) edit distance, keeping only those within a small distance-based cutoff of the input.

**did_you_mean(suggestions, sub_message=None)**: returns string like `" Did you mean 'A', 'B', or 'C'?"`. Max 5 suggestions. Empty string if none.

**inspect(value)**: string representation for error messages. Not `repr()`. Strings/ints are repr'd and truncated. GraphQL types via `str()`. Recurses collections up to depth 2.

**is_iterable/is_collection**: True for iterables/collections excluding str, bytes, bytearray, memoryview, Mapping.

**camel_to_snake/snake_to_camel**: `camel_to_snake("FooBar")` -> `"foo_bar"`. `snake_to_camel("foo_bar")` -> `"FooBar"`.

Other utilities: `identity_func`, `or_list`, `and_list`, `print_path_list`, `FrozenError`, `natural_comparison_key`, `cached_property` (works with `__slots__` classes by storing in `__dict__`).

## 3. Language (`graphql.language`)

### Source and Tokens

`Source(body, name="GraphQL request", location_offset=SourceLocation(1,1))` wraps a source string. `SourceLocation` is NamedTuple `(line, column)` with `formatted` property returning dict.

`TokenKind` enum with all GraphQL punctuators, keywords, and literals: SOF, EOF, BANG, QUESTION_MARK, DOLLAR, AMP, PAREN_L/R, SPREAD, COLON, EQUALS, AT, BRACKET_L/R, BRACE_L/R, PIPE, NAME, INT, FLOAT, STRING, BLOCK_STRING, COMMENT.

`Token` uses `__slots__`, forms doubly-linked list via `prev`/`next`. Fields: `kind` (TokenKind), `start`, `end`, `line`, `column`, `value` (str or None). The `desc` property returns `"{kind_value} {value!r}"` if value else `"{kind_value}"`.

`Lexer(source)` -- stateful. `advance()` returns next non-ignored token. `lookahead()` peeks without changing state. Attributes: `source`, `token`, `last_token`, `line`, `line_start`.

Whitespace: space, tab, comma, BOM (U+FEFF), newline (LF, CR, CRLF) are ignored. Comments start with `#` to end of line. Strings support escapes: `\"`, `\\`, `\/`, `\b`, `\f`, `\n`, `\r`, `\t`, `\uXXXX` (fixed-width), `\u{XXXX}` (variable-width). Block strings use `"""..."""` with dedentation removing common leading whitespace.

Numbers: optional `-`, then `0` or non-zero digits. Float if `.` or exponent present. No leading zeros.

### AST Nodes

All AST nodes are frozen dataclasses (kw_only=True) with class variable `kind` (snake_case from class name minus "Node" suffix, via camel_to_snake) and optional `loc` (Location or None). `Node` base class has `keys` class property returning field names, `to_dict()`, `__repr__`. `__init_subclass__` auto-sets `kind`.

Node equality is structural and independent of source position: two nodes are equal iff they are the same node kind and every one of their `keys` child fields is equal (recursively), with any difference in `loc` ignored. As a result two ASTs parsed from equivalent source compare equal even though each parse produced distinct `Location`/`Token` objects (e.g. `parse(s) == parse(print_ast(parse(s)))`). Equivalently, `Location` compares by value on its `(start, end)` offsets.

**QUERY_DOCUMENT_KEYS** maps node kind strings to tuples of child attribute names for visitor traversal (e.g., `"document": ("definitions",)`, `"field": ("alias", "name", "arguments", "directives", "selection_set", ...)`).

AST node types follow the GraphQL spec grammar productions. Key structural details:
- Value nodes store values as strings where applicable: `IntValueNode.value` is str `"42"`, `FloatValueNode.value` is str `"3.14"`. `StringValueNode` has optional `block: bool`. `BooleanValueNode.value` is bool.
- Tuple attributes default to empty tuple `()`, optional attributes default to None.
- Const variants (ConstListValueNode, ConstObjectValueNode, ConstArgumentNode, ConstDirectiveNode) exist for constant positions.

`OperationType` enum: QUERY ("query"), MUTATION ("mutation"), SUBSCRIPTION ("subscription"). `DirectiveLocation` enum covers all request and type system locations per spec.

`Location`: `start`, `end`, `start_token`, `end_token`, `source`. Constructor takes `(start_token, end_token, source)`.

### Parsing

`parse(source, no_location=False, max_tokens=None)` returns DocumentNode. Raises GraphQLSyntaxError on syntax errors. When `no_location=True`, nodes have `loc=None`. Also: `parse_value`, `parse_type`, `parse_const_value`.

### Visitor Pattern

**VisitorAction sentinels**: `BREAK` = True (stop visiting entirely), `SKIP` = False (skip visiting children), `REMOVE` = Ellipsis (remove this node), `IDLE` = None (no action).

**Visitor** base class. For each visited node the visitor dispatches to an `enter_{kind}` / `leave_{kind}` method if one is defined, otherwise to a generic `enter` / `leave`. Handler method names are validated against the real AST node kinds when a `Visitor` subclass is defined.

**visit(root, visitor, visitor_keys=None)** -- depth-first traversal. Returns the (possibly modified) root via immutable editing (a new tree without mutating the original). Default `visitor_keys` is QUERY_DOCUMENT_KEYS.

Callbacks receive `(node, key, parent, path, ancestors)`. Return values:
- enter: IDLE=continue, SKIP=skip children, BREAK=stop, REMOVE=delete, any Node=replace
- leave: IDLE/SKIP=continue, BREAK=stop, REMOVE=delete, any Node=replace

**ParallelVisitor(visitors)** -- runs multiple visitors in parallel. If a visitor SKIPs, it won't see leave for that node. BREAK stops that visitor only. If any visitor returns a replacement, later visitors don't see that node.

### print_ast(ast)

Converts AST back to GraphQL source string. Uses 2-space indentation for blocks. Anonymous queries without directives/variables use short form (no `query` keyword).

The returned string has **no trailing newline** — it ends immediately after the last token (e.g. `print_ast(parse("{ a }"))` returns `"{\n  a\n}"`), so exact-string comparisons against printed output are well-defined.

### Node Predicates

`is_definition_node`, `is_executable_definition_node`, `is_selection_node`, `is_value_node`, `is_const_value_node`, `is_type_node`, `is_type_system_definition_node`, `is_type_definition_node`, `is_type_extension_node` -- isinstance checks against corresponding base classes.

## 4. Type System (`graphql.type`)

`GraphQLWrappingType(Generic[GT_co])` base for List/NonNull with `of_type`. `GraphQLNamedType` has `name`, `description`, `extensions`, `ast_node`, `extension_ast_nodes`. Constructor validates name via `assert_name`. Has `to_kwargs()`. `reserved_types` class dict prevents redefinition of built-in types.

**GraphQLScalarType**: `serialize(value)`, `parse_value(value)`, `parse_literal(node, variables=None)`. Default serialize/parse_value are identity. Default parse_literal delegates to `parse_value(value_from_ast_untyped(node, variables))`. If parse_literal is custom, parse_value must also be provided. Optional `specified_by_url`.

**GraphQLObjectType**: `fields` (dict[str, GraphQLField], lazy via cached_property and thunk), `interfaces` (tuple of GraphQLInterfaceType, lazy via thunk), `is_type_of` (callable or None). Fields and interfaces resolved lazily on first access using `resolve_thunk`. This supports circular type references.

**GraphQLInterfaceType**: like ObjectType with `fields`, `interfaces`, `resolve_type`.

**GraphQLUnionType**: `types` (tuple of GraphQLObjectType, lazy via thunk), `resolve_type`.

**GraphQLEnumType**: `values` (dict[str, GraphQLEnumValue]). Constructor accepts dict of name->value or name->GraphQLEnumValue, or a Python Enum class. `serialize(output_value)` looks up internal value, returns enum name string. `parse_value(input_value)` takes string name, returns internal value. `parse_literal` expects EnumValueNode.

**GraphQLInputObjectType**: `fields` (dict[str, GraphQLInputField], lazy), `out_type` (callable, default identity), `is_one_of` (bool).

**GraphQLList/GraphQLNonNull**: wrapping types. `str()` returns `"[T]"` / `"T!"`. NonNull cannot wrap NonNull.

**GraphQLField**: `type` (output type), `args` (dict[str, GraphQLArgument]), `resolve`, `subscribe`, `description`, `deprecation_reason`, `extensions`, `ast_node`.

**GraphQLArgument**: `type` (input type), `default_value` (any, Undefined if not set), `description`, `deprecation_reason`, `out_name` (str or None), `extensions`.

**GraphQLInputField**: same shape as Argument. **GraphQLEnumValue**: `value`, `description`, `deprecation_reason`, `extensions`.

**GraphQLResolveInfo**: NamedTuple with `field_name`, `field_nodes`, `return_type`, `parent_type`, `path`, `schema`, `fragments`, `root_value`, `operation`, `variable_values`, `context`, `is_awaitable`.

Five built-in scalars: `GraphQLInt` (32-bit signed), `GraphQLFloat` (IEEE 754), `GraphQLString`, `GraphQLBoolean`, `GraphQLID`. Each has `serialize`, `parse_value`, `parse_literal` following GraphQL spec coercion rules. `specified_scalar_types` mapping exported.

**GraphQLDirective**: `name`, `locations` (tuple of DirectiveLocation), `args`, `is_repeatable`. Built-in directives follow the GraphQL specification: `@skip`, `@include`, `@deprecated`, `@specifiedBy`, `@oneOf`. `specified_directives` tuple exported. `DEFAULT_DEPRECATION_REASON = 'No longer supported'`.

**GraphQLSchema**: constructor `(query=None, mutation=None, subscription=None, types=None, directives=None, description=None, extensions=None, assume_valid=False)`. If `directives` is None, defaults to `specified_directives`. Collects all types reachable from root types, directive args, and introspection types into `type_map`. Types in `types` param included first. Tracks, for each interface, which object and interface types implement it (queryable via `get_possible_types` and `is_sub_type`).

Methods: `get_type(name)`, `get_possible_types(abstract_type)`, `is_sub_type(abstract, maybe_sub)`, `get_directive(name)`, `get_field(parent_type, field_name)` (special-cases `__schema`, `__type`, `__typename`), `get_root_type(operation)`.

`validate_schema(schema)` returns list of GraphQLError. `assert_valid_schema(schema)` raises.

`validate_schema` checks the schema against the type-validation rules of the GraphQL specification and returns a `GraphQLError` for each problem found (an empty list means the schema is valid). When a problem concerns a particular field, the error message names that field.

Type predicates/unwrappers/assertions. `assert_name` validates `[_A-Za-z][_0-9A-Za-z]*` and rejects `__` prefix. `assert_enum_value_name` also rejects `true`/`false`/`null`. `is_required_argument`/`is_required_input_field`: True if NonNull AND default_value is Undefined.

### Introspection

Implements the standard GraphQL introspection system per the spec. Meta-fields `__schema`, `__type(name: String!)`, and `__typename` are handled in the field resolution pipeline via `get_field` special-casing. `TypeKind` enum and all standard introspection types (`__Schema`, `__Type`, `__Field`, etc.) must be implemented as actual GraphQLObjectType instances with resolvers.

## 5. Execution (`graphql.execution`)

**ExecutionResult**: `data` (dict or None), `errors` (list of GraphQLError or None), `extensions` (dict or None). Has `__eq__` and `formatted` property.

**execute(schema, document, root_value=None, context_value=None, variable_values=None, operation_name=None, field_resolver=None, type_resolver=None, middleware=None, ...)**: execute parsed document. Validates schema first (assert_valid_schema). Builds ExecutionContext, then executes.

**execute_sync**: synchronous version. Same args plus `check_sync=False`. Raises RuntimeError if execution produces awaitable.

**graphql/graphql_sync(schema, source, ...)**: parse + validate + execute in one call. `source` can be str or Source. Returns errors immediately on schema/parse/validation failure.

**ExecutionContext.build**: extracts operation and fragments from document. Coerces variables. Handles operation selection by name.

**Field Resolution Pipeline**:
1. Look up field def via `schema.get_field(parent_type, field_name)`. Skip if no def.
2. Get resolver: `field_def.resolve` or default. Wrap with middleware if present.
3. Build GraphQLResolveInfo. Coerce arguments from AST + variables.
4. Call `resolve_fn(source, info, **args)` (args as keyword arguments).
5. Complete the value.

**complete_value dispatch**: NonNull -> recurse on inner, raise if null. Null/Undefined -> None. List -> complete each item. Leaf (Scalar/Enum) -> `serialize(result)`. Abstract (Interface/Union) -> resolve runtime type, complete as object. Object -> collect sub-fields, execute them.

**Null propagation**: NonNull field returning null or throwing propagates up to nearest nullable parent (which becomes null). Errors collected in result. If all ancestors NonNull up to root, `data` becomes null.

**Mutations execute serially** (left to right). **Queries execute concurrently**.

**default_field_resolver(source, info)**: dicts -> `source.get(field_name)`, objects -> `getattr(source, field_name, None)`. If callable, calls with `(info, **args)`.

**default_type_resolver**: checks `__typename` attr/key first, falls back to `is_type_of` on each possible type.

**MiddlewareManager(*middlewares)**: each middleware is a function or an object with a `resolve` method. `get_field_resolver(field_resolver)` returns the given resolver wrapped by the middleware chain, so that for each field the middlewares run in registration order around the underlying resolver. Middleware signature: `middleware(next_fn, source, info, **args)`.

**get_argument_values/get_variable_values/get_directive_values**: coerce from AST + variables, apply defaults, use `out_name` if present.

### End-to-end example

The two ways to build a schema and run a query end-to-end:

```python
from graphql import build_schema, graphql_sync

# Build a schema from SDL and run a query against it.
schema = build_schema("type Query { hello: String }")
result = graphql_sync(schema, "{ hello }")
# No resolver is supplied, so the default resolver returns None for `hello`.
result.data    # {"hello": None}
result.errors  # None
```

```python
from graphql import (
    graphql_sync, GraphQLSchema, GraphQLObjectType, GraphQLField, GraphQLString,
)

# Equivalent schema built programmatically, with an explicit resolver.
schema = GraphQLSchema(
    query=GraphQLObjectType(
        "Query",
        {"hello": GraphQLField(GraphQLString, resolve=lambda obj, info: "world")},
    )
)
result = graphql_sync(schema, "{ hello }")
result.data    # {"hello": "world"}
result.errors  # None
```

`graphql_sync(schema, source)` parses `source`, validates it against `schema`, then executes it, returning an `ExecutionResult` whose `data` holds the resolved result and whose `errors` is `None` when nothing went wrong (otherwise a list of `GraphQLError`).

## 6. Validation (`graphql.validation`)

`validate(schema, document_ast, rules=None, max_errors=None, type_info=None)` returns list of GraphQLError. Default max_errors=100. Uses `specified_rules` if none provided. Creates ValidationContext, instantiates rule visitors, wraps in ParallelVisitor inside TypeInfoVisitor, runs visit().

**ValidationContext**: extends ASTValidationContext. Provides schema, type info, fragments, variable usages. `report_error(error)` collects errors. Methods: `get_fragment(name)`, `get_recursive_variable_usages(operation)`, `get_variable_usages(node)`.

**ASTValidationRule / SDLValidationRule / ValidationRule**: Visitor subclasses with `context` and `report_error`.

**TypeInfo(schema, initial_type=None)**: tracks current type, field, argument, input type during AST traversal. Call `enter(node)`/`leave(node)` to maintain type stacks. Methods: `get_type()`, `get_parent_type()`, `get_input_type()`, `get_parent_input_type()`, `get_field_def()`, `get_default_value()`, `get_directive()`, `get_argument()`, `get_enum_value()`.

**TypeInfoVisitor(type_info, visitor)**: wraps another visitor, calling type_info.enter/leave around callbacks.

Validation rules implement the specified rules from the GraphQL spec (`specified_rules` tuple). Each rule is a Visitor subclass that reports errors via `context.report_error`:

- **ExecutableDefinitionsRule**: document must only contain operations and fragments
- **UniqueOperationNamesRule**: operation names must be unique
- **LoneAnonymousOperationRule**: anonymous operation must be the only operation
- **SingleFieldSubscriptionsRule**: subscriptions must have exactly one root field
- **KnownTypeNamesRule**: type references must exist; suggests similar names
- **FragmentsOnCompositeTypesRule**: fragments only on Object, Interface, Union
- **VariablesAreInputTypesRule**: variable types must be input types
- **ScalarLeafsRule**: scalars must not have sub-selections; composites must have them
- **FieldsOnCorrectTypeRule**: fields must exist on parent type; suggests similar fields and types
- **UniqueFragmentNamesRule**: fragment names must be unique
- **KnownFragmentNamesRule**: spreads must reference defined fragments
- **NoUnusedFragmentsRule**: all fragments must be used
- **PossibleFragmentSpreadsRule**: type conditions must be compatible with parent type
- **NoFragmentCyclesRule**: fragments must not form cycles (spreading path tracking). Each distinct cycle is reported exactly once (not once per fragment participating in it), and the reported error carries a source location
- **UniqueVariableNamesRule**: variable names must be unique per operation
- **NoUndefinedVariablesRule**: used variables must be defined
- **NoUnusedVariablesRule**: defined variables must be used
- **KnownDirectivesRule**: directives must exist; used in valid locations
- **UniqueDirectivesPerLocationRule**: non-repeatable directives appear at most once
- **KnownArgumentNamesRule**: arguments must exist on field/directive; suggests similar
- **UniqueArgumentNamesRule**: no duplicate arguments
- **ValuesOfCorrectTypeRule**: deep type checking for input objects, lists, scalars, enums. When a value does not fit its expected type, the reported error message includes the offending input value (formatted via `inspect`), e.g. `"Expected value of type 'String', found 42."`
- **ProvidedRequiredArgumentsRule**: required args (non-null without default) must be provided
- **VariablesInAllowedPositionRule**: variable usages must be type-compatible
- **OverlappingFieldsCanBeMergedRule**: fields with same response name must have same name, args, compatible return types, recursively merged selection sets
- **UniqueInputFieldNamesRule**: input object literal fields must be unique
- **MaxIntrospectionDepthRule**: limits introspection query depth

## 7. Utilities (`graphql.utilities`)

**build_schema(source, assume_valid=False, assume_valid_sdl=False, no_location=False)**: parse SDL, build GraphQLSchema. If no schema definition, uses types named Query/Mutation/Subscription. Missing specified directives added automatically.

**build_ast_schema(document_ast)**: build schema from DocumentNode.

**value_from_ast(value_node, type_, variables=None)**: convert AST value to Python value using type. Returns Undefined if cannot coerce. For InputObject: creates dict using `out_name`, applies defaults, validates OneOf, calls `type_.out_type(dict)`.

**value_from_ast_untyped(value_node, variables=None)**: convert without type. Dispatches via dict mapping kind strings to handler functions.

**ast_from_value(value, type_)**: convert Python value to AST node. Returns None if not representable. For leaf types: bools->BooleanValueNode, ints->IntValueNode, floats->FloatValueNode, strings->StringValueNode (or EnumValueNode for enums, IntValueNode for ID with integer strings).

**coerce_input_value(input_value, type_, on_error=default_on_error, path=None)**: coerce runtime value against input type. Default on_error raises. List handles iterables or single->list-of-one. InputObject requires dict, validates OneOf, calls out_type. Leaf calls parse_value.

**type_from_ast(schema, type_node)**: convert type AST node to GraphQLType via schema lookup.

Other: `is_equal_type`, `is_type_sub_type_of`, `do_types_overlap`, `get_operation_ast`, `concat_ast`, `separate_operations`, `strip_ignored_characters`, `ast_to_dict`.

## 8. Key Behavioral Details

### Thunk-based Lazy References

Object types, interface types, union types, and input object types accept thunks (zero-argument callables) for their `fields`, `interfaces`, and `types` parameters. These are resolved on first access via `cached_property`. This enables circular type references (e.g., User has friends field returning [User]).

### Null Propagation

When a field with a NonNull return type resolves to null or throws an error, the null propagates to the nearest nullable ancestor field. Errors are collected in the result's `errors` list. If all ancestor fields are NonNull up to the root, `data` becomes null.

### Execution of Mutations

Mutation root fields are executed serially (one after another), while query root fields may execute concurrently. This is specified by the GraphQL spec.

### Schema Type Collection

When a GraphQLSchema is constructed, it traverses all types reachable from root types, directive arguments, and introspection types to build the `type_map`. Types explicitly passed via the `types` parameter are included first (preserving order), then types discovered through traversal.

### Response Path

The execution engine uses `Path` (linked list) to track the current position in the response for error reporting. Paths are converted to lists via `as_list()` for inclusion in error objects.
