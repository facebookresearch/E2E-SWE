"""
Comprehensive test suite for graphql-core v3.2.8.

Tests the public API surface through integration and cross-feature tests:
execution workflows, validation rule coverage, visitor editing, introspection,
directive handling, custom scalars, and null propagation edge cases.
"""

import unittest
from datetime import datetime


# ---------------------------------------------------------------------------
# AST Visitor (REMOVE/SKIP sentinels + enter/leave ordering)
# ---------------------------------------------------------------------------


class TestASTVisitor(unittest.TestCase):

    def test_ast_visitor_edit_and_traversal(self):
        """Visitor enter/leave fire in depth-first order. REMOVE sentinel
        deletes a node. Returning a new node replaces it. Verify via
        print_ast on the modified trees."""
        from graphql import parse, visit, Visitor, REMOVE, print_ast
        from graphql import FieldNode, NameNode

        # Part 1: verify enter/leave ordering
        doc = parse("{ a { b } }")
        events = []

        class Recorder(Visitor):
            def enter(self, node, *args):
                events.append(("enter", type(node).__name__))

            def leave(self, node, *args):
                events.append(("leave", type(node).__name__))

        visit(doc, Recorder())

        expected_events = [
            ("enter", "DocumentNode"),
            ("enter", "OperationDefinitionNode"),
            ("enter", "SelectionSetNode"),
            ("enter", "FieldNode"),
            ("enter", "NameNode"),
            ("leave", "NameNode"),
            ("enter", "SelectionSetNode"),
            ("enter", "FieldNode"),
            ("enter", "NameNode"),
            ("leave", "NameNode"),
            ("leave", "FieldNode"),
            ("leave", "SelectionSetNode"),
            ("leave", "FieldNode"),
            ("leave", "SelectionSetNode"),
            ("leave", "OperationDefinitionNode"),
            ("leave", "DocumentNode"),
        ]
        self.assertEqual(events, expected_events)

        # Part 2: REMOVE sentinel deletes node 'b'
        doc2 = parse("{ a b c }")

        class RemoveB(Visitor):
            def enter_field(self, node, *args):
                if node.name.value == "b":
                    return REMOVE

        result = visit(doc2, RemoveB())
        self.assertEqual(print_ast(result), "{\n  a\n  c\n}")

        # Part 3: Returning a new node replaces it
        doc3 = parse("{ a b c }")

        class RenameA(Visitor):
            def enter_field(self, node, *args):
                if node.name.value == "a":
                    return FieldNode(
                        name=NameNode(value="renamed"),
                        alias=node.alias,
                        arguments=node.arguments,
                        directives=node.directives,
                        selection_set=node.selection_set,
                    )

        result2 = visit(doc3, RenameA())
        self.assertEqual(print_ast(result2), "{\n  renamed\n  b\n  c\n}")

        # Part 4: print round-trip fidelity
        original = """\
query GetUser($id: ID!) {
  user(id: $id) {
    name
    age
    address {
      city
    }
  }
}"""
        doc_rt1 = parse(original)
        printed_rt1 = print_ast(doc_rt1)
        doc_rt2 = parse(printed_rt1)
        printed_rt2 = print_ast(doc_rt2)
        self.assertEqual(printed_rt1, printed_rt2)
        self.assertEqual(doc_rt1, doc_rt2)


# ---------------------------------------------------------------------------
# Introspection (merged)
# ---------------------------------------------------------------------------


class TestIntrospection(unittest.TestCase):

    def test_introspection_queries(self):
        """__type returns field info, __schema returns queryType, __typename
        returns correct type name. All exercised on one schema."""
        from graphql import build_schema, graphql_sync

        schema = build_schema(
            """
            type Query { user: User }
            type User { name: String, age: Int }
            """
        )

        # __type query
        r1 = graphql_sync(
            schema,
            '{ __type(name: "User") { name fields { name type { name } } } }',
        )
        type_info = r1.data["__type"]
        self.assertEqual(type_info["name"], "User")
        field_names = {f["name"] for f in type_info["fields"]}
        self.assertEqual(field_names, {"name", "age"})

        # __schema query
        r2 = graphql_sync(schema, "{ __schema { queryType { name } } }")
        self.assertEqual(r2.data["__schema"]["queryType"]["name"], "Query")

        # __typename
        r3 = graphql_sync(schema, "{ __typename }")
        self.assertEqual(r3.data, {"__typename": "Query"})


# ---------------------------------------------------------------------------
# Execution (consolidated)
# ---------------------------------------------------------------------------


class TestExecution(unittest.TestCase):

    def test_execution_workflow(self):
        """Build schema with nested types, execute with args and variables,
        verify data for nested objects, lists, and variable-driven queries."""
        from graphql import (
            graphql_sync,
            GraphQLSchema,
            GraphQLObjectType,
            GraphQLField,
            GraphQLString,
            GraphQLInt,
            GraphQLList,
            GraphQLNonNull,
            GraphQLArgument,
        )

        address_type = GraphQLObjectType(
            "Address",
            {
                "city": GraphQLField(GraphQLString),
                "zip": GraphQLField(GraphQLString),
            },
        )
        person_type = GraphQLObjectType(
            "Person",
            {
                "name": GraphQLField(GraphQLString),
                "age": GraphQLField(GraphQLInt),
                "address": GraphQLField(address_type),
                "tags": GraphQLField(GraphQLList(GraphQLString)),
            },
        )
        schema = GraphQLSchema(
            query=GraphQLObjectType(
                "Query",
                {
                    "person": GraphQLField(
                        person_type,
                        args={"id": GraphQLArgument(GraphQLNonNull(GraphQLInt))},
                        resolve=lambda obj, info, id: {
                            "name": f"User{id}",
                            "age": 25 + id,
                            "address": {"city": "NYC", "zip": "10001"},
                            "tags": ["admin", "active"],
                        },
                    ),
                    "greet": GraphQLField(
                        GraphQLString,
                        args={"name": GraphQLArgument(GraphQLNonNull(GraphQLString))},
                        resolve=lambda obj, info, name: f"Hello, {name}!",
                    ),
                },
            )
        )

        # Direct arg execution
        result = graphql_sync(schema, '{ greet(name: "Alice") }')
        self.assertEqual(result.data, {"greet": "Hello, Alice!"})
        self.assertIsNone(result.errors)

        # Nested + list fields
        result2 = graphql_sync(
            schema, "{ person(id: 1) { name age address { city zip } tags } }"
        )
        self.assertEqual(
            result2.data,
            {
                "person": {
                    "name": "User1",
                    "age": 26,
                    "address": {"city": "NYC", "zip": "10001"},
                    "tags": ["admin", "active"],
                }
            },
        )

        # Variable-driven query
        result3 = graphql_sync(
            schema,
            "query G($n: String!) { greet(name: $n) }",
            variable_values={"n": "Bob"},
        )
        self.assertEqual(result3.data, {"greet": "Hello, Bob!"})

    def test_execution_edge_cases(self):
        """NonNull error propagation, interface/union resolution with
        is_type_of, serial mutation ordering."""
        from graphql import (
            graphql_sync,
            GraphQLSchema,
            GraphQLObjectType,
            GraphQLField,
            GraphQLString,
            GraphQLInt,
            GraphQLNonNull,
            GraphQLInterfaceType,
        )

        # 1. NonNull null propagation
        schema_nn = GraphQLSchema(
            query=GraphQLObjectType(
                "Query",
                {
                    "required": GraphQLField(
                        GraphQLNonNull(GraphQLString),
                        resolve=lambda obj, info: None,
                    )
                },
            )
        )
        result = graphql_sync(schema_nn, "{ required }")
        # NonNull field returning null bubbles to root -> data is None, one
        # error recorded. Message wording is not asserted.
        self.assertIsNone(result.data)
        self.assertEqual(len(result.errors), 1)

        # 2. Abstract type resolution via is_type_of
        animal_iface = GraphQLInterfaceType(
            "Animal",
            {
                "name": GraphQLField(GraphQLString),
                "sound": GraphQLField(GraphQLString),
            },
        )
        dog_type = GraphQLObjectType(
            "Dog",
            {
                "name": GraphQLField(GraphQLString),
                "sound": GraphQLField(GraphQLString),
            },
            interfaces=[animal_iface],
            is_type_of=lambda obj, info: obj.get("type") == "dog",
        )
        cat_type = GraphQLObjectType(
            "Cat",
            {
                "name": GraphQLField(GraphQLString),
                "sound": GraphQLField(GraphQLString),
            },
            interfaces=[animal_iface],
            is_type_of=lambda obj, info: obj.get("type") == "cat",
        )
        schema_abs = GraphQLSchema(
            query=GraphQLObjectType(
                "Query",
                {
                    "animal": GraphQLField(
                        animal_iface,
                        resolve=lambda obj, info: {
                            "type": "dog",
                            "name": "Rex",
                            "sound": "Woof",
                        },
                    )
                },
            ),
            types=[dog_type, cat_type],
        )
        result2 = graphql_sync(schema_abs, "{ animal { name sound } }")
        self.assertEqual(result2.data, {"animal": {"name": "Rex", "sound": "Woof"}})
        self.assertIsNone(result2.errors)

        # 3. Serial mutation execution order
        order = []

        def make_resolver(name):
            def resolver(obj, info):
                order.append(name)
                return name
            return resolver

        schema_mut = GraphQLSchema(
            query=GraphQLObjectType(
                "Query",
                {"dummy": GraphQLField(GraphQLString, resolve=lambda o, i: "ok")},
            ),
            mutation=GraphQLObjectType(
                "Mutation",
                {
                    "first": GraphQLField(GraphQLString, resolve=make_resolver("first")),
                    "second": GraphQLField(GraphQLString, resolve=make_resolver("second")),
                    "third": GraphQLField(GraphQLString, resolve=make_resolver("third")),
                },
            ),
        )
        result3 = graphql_sync(schema_mut, "mutation { first second third }")
        self.assertEqual(
            result3.data, {"first": "first", "second": "second", "third": "third"}
        )
        self.assertEqual(order, ["first", "second", "third"])

    def test_fragment_merging_during_execution(self):
        """Field collection during execution merges selections that reach the
        same response key via multiple paths (fragment spread + direct
        selection). When an object field is selected more than once, the
        executor merges the sub-selection sets and resolves the field ONCE
        with the combined selection; a scalar reached twice appears once; and
        @skip/@include on fragment spreads is evaluated before merging so the
        merged output reflects only the included selections."""
        from graphql import (
            graphql_sync,
            GraphQLSchema,
            GraphQLObjectType,
            GraphQLField,
            GraphQLString,
            GraphQLInt,
        )

        # The profile resolver records how many times it runs so we can assert
        # that overlapping selections produce a SINGLE resolution, not two.
        profile_calls = []

        def resolve_profile(obj, info):
            profile_calls.append(1)
            return {"bio": "hi there", "age": 42}

        profile_type = GraphQLObjectType(
            "Profile",
            {
                "bio": GraphQLField(GraphQLString),
                "age": GraphQLField(GraphQLInt),
            },
        )
        user_type = GraphQLObjectType(
            "User",
            {
                "name": GraphQLField(GraphQLString),
                "profile": GraphQLField(profile_type, resolve=resolve_profile),
            },
        )
        schema = GraphQLSchema(
            query=GraphQLObjectType(
                "Query",
                {
                    "user": GraphQLField(
                        user_type,
                        resolve=lambda o, i: {"name": "Alice"},
                    )
                },
            )
        )

        # Scenario 1 & 2: `profile` is reached via the fragment (sub-selection
        # { bio }) AND directly (sub-selection { age }); the merged resolution
        # must return BOTH. `name` is reached via the fragment and directly but
        # appears exactly once.
        query_merge = """
        query {
          user {
            ...UserName
            name
            profile { age }
          }
        }
        fragment UserName on User { name profile { bio } }
        """
        r1 = graphql_sync(schema, query_merge)
        self.assertIsNone(r1.errors)
        self.assertEqual(
            r1.data,
            {"user": {"name": "Alice", "profile": {"bio": "hi there", "age": 42}}},
        )
        # The merged object field resolves exactly once despite two selections.
        self.assertEqual(profile_calls, [1])

        # Scenario 3: @skip/@include on fragment spreads is applied during
        # field collection, BEFORE merging same-response-key selections.
        query_dir = """
        query M($withAge: Boolean!, $withBio: Boolean!) {
          user {
            name
            profile {
              ...BioFrag @include(if: $withBio)
            }
            ...AgeWrap @skip(if: $withAge)
          }
        }
        fragment BioFrag on Profile { bio }
        fragment AgeWrap on User { profile { age } }
        """

        # Age wrapper kept (skip=false), bio included -> both merge.
        ra = graphql_sync(
            schema, query_dir, variable_values={"withAge": False, "withBio": True}
        )
        self.assertIsNone(ra.errors)
        self.assertEqual(
            ra.data,
            {"user": {"name": "Alice", "profile": {"bio": "hi there", "age": 42}}},
        )

        # Age wrapper skipped, bio excluded -> profile resolves with an empty
        # merged selection set.
        rb = graphql_sync(
            schema, query_dir, variable_values={"withAge": True, "withBio": False}
        )
        self.assertIsNone(rb.errors)
        self.assertEqual(rb.data, {"user": {"name": "Alice", "profile": {}}})

        # Age wrapper skipped, bio included -> only bio survives the merge.
        rc = graphql_sync(
            schema, query_dir, variable_values={"withAge": True, "withBio": True}
        )
        self.assertIsNone(rc.errors)
        self.assertEqual(
            rc.data, {"user": {"name": "Alice", "profile": {"bio": "hi there"}}}
        )


# ---------------------------------------------------------------------------
# Validation (consolidated)
# ---------------------------------------------------------------------------


class TestValidation(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from graphql import build_schema

        cls.schema = build_schema(
            """
            type Query {
                hello: String
                greet(name: String!): String
                user: User
                search: [SearchResult]
            }
            type User {
                name: String
                age: Int
            }
            type Post {
                title: String
                content: String
            }
            union SearchResult = User | Post
            """
        )

    def test_validation_catches_errors(self):
        """Single schema, multiple invalid queries each hitting a different
        validation rule: unknown field, missing required arg, wrong type,
        unknown type, undefined variable, unused variable, scalar leafs."""
        from graphql import validate, parse

        # Each case asserts: (1) exactly one error fired (right detection),
        # (2) the error names the offending entity from the query/schema
        # (right target), and (3) the error carries a source location
        # (right place). Message *wording* is not asserted -- the spec does
        # not dictate phrasing, only that the rule fires and locates the issue.

        # Unknown field (FieldsOnCorrectType)
        e1 = validate(self.schema, parse("{ unknownField }"))
        self.assertEqual(len(e1), 1)
        self.assertIn("unknownField", e1[0].message)
        self.assertTrue(e1[0].locations)

        # Missing required arg (ProvidedRequiredArguments)
        e2 = validate(self.schema, parse("{ greet }"))
        self.assertEqual(len(e2), 1)
        self.assertIn("name", e2[0].message)
        self.assertTrue(e2[0].locations)

        # Wrong type for arg (ValuesOfCorrectType) -- echoes the bad value
        e3 = validate(self.schema, parse("{ greet(name: 42) }"))
        self.assertEqual(len(e3), 1)
        self.assertIn("42", e3[0].message)
        self.assertTrue(e3[0].locations)

        # Unknown type in variable definition (KnownTypeNames)
        e4 = validate(self.schema, parse("query($x: UnknownType) { hello }"))
        type_errors = [e for e in e4 if "UnknownType" in e.message]
        self.assertEqual(len(type_errors), 1)
        self.assertTrue(type_errors[0].locations)

        # Undefined variable (NoUndefinedVariables)
        e5 = validate(self.schema, parse("{ greet(name: $undeclared) }"))
        self.assertEqual(len(e5), 1)
        self.assertIn("$undeclared", e5[0].message)
        self.assertTrue(e5[0].locations)

        # Unused variable (NoUnusedVariables)
        e6 = validate(self.schema, parse("query Q($x: String) { hello }"))
        self.assertEqual(len(e6), 1)
        self.assertIn("$x", e6[0].message)
        self.assertTrue(e6[0].locations)

        # Scalar with sub-selection (ScalarLeafs) -- names the scalar field
        e7 = validate(self.schema, parse("{ hello { sub } }"))
        self.assertEqual(len(e7), 1)
        self.assertIn("hello", e7[0].message)
        self.assertTrue(e7[0].locations)

        # Object without sub-selection (ScalarLeafs) -- names the object field
        e8 = validate(self.schema, parse("{ user }"))
        self.assertEqual(len(e8), 1)
        self.assertIn("user", e8[0].message)
        self.assertTrue(e8[0].locations)

    def test_validation_complex_rules(self):
        """Fragment cycles and overlapping fields with conflicting types --
        algorithmically hard validation rules."""
        from graphql import validate, parse, build_schema

        # Fragment cycle detection
        e1 = validate(
            self.schema,
            parse(
                """
                { ...A }
                fragment A on Query { ...B }
                fragment B on Query { ...A }
                """
            ),
        )
        # Cycle A -> B -> A: exactly one cycle error naming a fragment in the
        # cycle, with a source location. Wording is not asserted.
        cycle_errors = [e for e in e1 if "A" in e.message and "B" in e.message]
        self.assertEqual(len(cycle_errors), 1)
        self.assertTrue(cycle_errors[0].locations)

        # Overlapping fields with conflicting return types
        schema2 = build_schema(
            """
            type Query { a: A, b: B }
            type A { x: String }
            type B { x: Int }
            """
        )
        e2 = validate(
            schema2,
            parse("{ field: a { x } field: b { x } }"),
        )
        # Exactly one conflict error naming the aliased response key, located.
        self.assertEqual(len(e2), 1)
        self.assertIn("field", e2[0].message)
        self.assertTrue(e2[0].locations)


# ---------------------------------------------------------------------------
# Cross-feature integration (kept as-is, these are complex workflows)
# ---------------------------------------------------------------------------


class TestCrossFeatureIntegration(unittest.TestCase):

    def test_custom_scalar_end_to_end(self):
        """Define a custom DateTime scalar with serialize/parse_value/
        parse_literal, use in a schema, and execute successfully."""
        from graphql import (
            graphql_sync,
            GraphQLSchema,
            GraphQLObjectType,
            GraphQLField,
            GraphQLScalarType,
            GraphQLArgument,
            StringValueNode,
        )

        def serialize_dt(value):
            if isinstance(value, datetime):
                return value.isoformat()
            return str(value)

        def parse_dt_value(value):
            return datetime.fromisoformat(value)

        def parse_dt_literal(ast, _variables=None):
            if isinstance(ast, StringValueNode):
                return datetime.fromisoformat(ast.value)
            return None

        dt_type = GraphQLScalarType(
            "DateTime",
            serialize=serialize_dt,
            parse_value=parse_dt_value,
            parse_literal=parse_dt_literal,
        )

        schema = GraphQLSchema(
            query=GraphQLObjectType(
                "Query",
                {
                    "now": GraphQLField(
                        dt_type,
                        resolve=lambda o, i: datetime(2024, 1, 15, 10, 30, 0),
                    ),
                    "echo": GraphQLField(
                        dt_type,
                        args={"dt": GraphQLArgument(dt_type)},
                        resolve=lambda o, i, dt=None: dt,
                    ),
                },
            )
        )
        result = graphql_sync(schema, "{ now }")
        self.assertEqual(result.data, {"now": "2024-01-15T10:30:00"})

        result2 = graphql_sync(
            schema, '{ echo(dt: "2024-06-15T12:00:00") }'
        )
        self.assertEqual(result2.data, {"echo": "2024-06-15T12:00:00"})

    def test_enum_input_output(self):
        """Enum values flow correctly through input args and output fields."""
        from graphql import (
            graphql_sync,
            GraphQLSchema,
            GraphQLObjectType,
            GraphQLField,
            GraphQLString,
            GraphQLEnumType,
            GraphQLEnumValue,
            GraphQLArgument,
        )

        color_enum = GraphQLEnumType(
            "Color",
            {
                "RED": GraphQLEnumValue(0),
                "GREEN": GraphQLEnumValue(1),
                "BLUE": GraphQLEnumValue(2),
            },
        )

        schema = GraphQLSchema(
            query=GraphQLObjectType(
                "Query",
                {
                    "favoriteColor": GraphQLField(
                        color_enum, resolve=lambda o, i: 1
                    ),
                    "colorName": GraphQLField(
                        GraphQLString,
                        args={"color": GraphQLArgument(color_enum)},
                        resolve=lambda o, i, color=None: f"color-{color}",
                    ),
                },
            )
        )
        result = graphql_sync(schema, "{ favoriteColor }")
        self.assertEqual(result.data, {"favoriteColor": "GREEN"})

        result2 = graphql_sync(schema, "{ colorName(color: RED) }")
        self.assertEqual(result2.data, {"colorName": "color-0"})

    def test_complex_validation_and_execution(self):
        """Complex query with fragments, variables, and directives: validate
        then execute, verify directive @include controls field presence."""
        from graphql import (
            graphql_sync,
            validate,
            parse,
            GraphQLSchema,
            GraphQLObjectType,
            GraphQLField,
            GraphQLString,
            GraphQLInt,
            GraphQLNonNull,
            GraphQLArgument,
        )

        user_type = GraphQLObjectType(
            "User",
            {
                "name": GraphQLField(GraphQLString),
                "age": GraphQLField(GraphQLInt),
                "email": GraphQLField(GraphQLString),
            },
        )
        schema = GraphQLSchema(
            query=GraphQLObjectType(
                "Query",
                {
                    "user": GraphQLField(
                        user_type,
                        args={"id": GraphQLArgument(GraphQLNonNull(GraphQLInt))},
                        resolve=lambda o, i, id: {
                            "name": f"User{id}",
                            "age": 30 + id,
                            "email": f"user{id}@test.com",
                        },
                    )
                },
            )
        )

        query = """
        query GetUser($userId: Int!, $includeEmail: Boolean!) {
            user(id: $userId) {
                ...UserBasic
                email @include(if: $includeEmail)
            }
        }
        fragment UserBasic on User {
            name
            age
        }
        """

        errors = validate(schema, parse(query))
        self.assertEqual(errors, [])

        result = graphql_sync(
            schema, query, variable_values={"userId": 1, "includeEmail": True}
        )
        self.assertEqual(
            result.data,
            {"user": {"name": "User1", "age": 31, "email": "user1@test.com"}},
        )

        result2 = graphql_sync(
            schema, query, variable_values={"userId": 2, "includeEmail": False}
        )
        self.assertEqual(
            result2.data, {"user": {"name": "User2", "age": 32}}
        )


# ---------------------------------------------------------------------------
# Difficult flavors (kept as-is, genuinely hard)
# ---------------------------------------------------------------------------


class TestDifficultFlavors(unittest.TestCase):

    def test_deep_nested_fragment_validation(self):
        """Deeply nested fragments with type conditions on interface
        implementations validate without errors."""
        from graphql import validate, parse, build_schema

        schema = build_schema(
            """
            interface Node { id: ID! }
            type User implements Node { id: ID!, name: String, friends: [User] }
            type Admin implements Node { id: ID!, name: String, level: Int }
            type Query { node: Node, users: [User] }
            """
        )

        errors = validate(
            schema,
            parse(
                """
                query {
                    node {
                        ...nodeFields
                    }
                }
                fragment nodeFields on Node {
                    id
                    ... on User {
                        name
                        friends {
                            ...friendFields
                        }
                    }
                    ... on Admin {
                        name
                        level
                    }
                }
                fragment friendFields on User {
                    id
                    name
                }
                """
            ),
        )
        self.assertEqual(errors, [])

    def test_overlapping_fields_with_fragments(self):
        """OverlappingFieldsCanBeMerged detects conflicting return types across
        inline fragments on sibling concrete types."""
        from graphql import validate, parse, build_schema

        schema = build_schema(
            """
            type Query { a: SomeBox }
            interface SomeBox { unrelatedField: String }
            type StringBox implements SomeBox {
                scalar: String
                unrelatedField: String
            }
            type IntBox implements SomeBox {
                scalar: Int
                unrelatedField: String
            }
            """
        )

        errors = validate(
            schema,
            parse(
                """
                {
                    a {
                        ... on IntBox { scalar }
                        ... on StringBox { scalar }
                    }
                }
                """
            ),
        )
        # Exactly one conflict error naming the conflicting field, located.
        self.assertEqual(len(errors), 1)
        self.assertIn("scalar", errors[0].message)
        self.assertTrue(errors[0].locations)

    def test_null_bubble_through_list(self):
        """When a non-null field inside a list item returns null the item
        becomes null, an error is recorded with the correct path, and the
        remaining items are preserved."""
        from graphql import (
            graphql_sync,
            GraphQLSchema,
            GraphQLObjectType,
            GraphQLField,
            GraphQLString,
            GraphQLNonNull,
            GraphQLList,
        )

        item_type = GraphQLObjectType(
            "Item", {"name": GraphQLField(GraphQLNonNull(GraphQLString))}
        )
        schema = GraphQLSchema(
            query=GraphQLObjectType(
                "Query",
                {
                    "items": GraphQLField(
                        GraphQLList(item_type),
                        resolve=lambda o, i: [
                            {"name": "a"},
                            {"name": None},
                            {"name": "c"},
                        ],
                    )
                },
            )
        )
        result = graphql_sync(schema, "{ items { name } }")
        self.assertEqual(
            result.data,
            {"items": [{"name": "a"}, None, {"name": "c"}]},
        )
        self.assertEqual(len(result.errors), 1)
        # Message wording is not asserted; the error path pins the offending
        # non-nullable field precisely without dictating arbitrary phrasing.
        self.assertEqual(result.errors[0].path, ["items", 1, "name"])

    def test_execution_with_middleware(self):
        """MiddlewareManager wraps field resolution, and middleware functions
        are called in order around each resolver."""
        from graphql import (
            graphql_sync,
            GraphQLSchema,
            GraphQLObjectType,
            GraphQLField,
            GraphQLString,
            MiddlewareManager,
        )

        calls = []

        def log_middleware(next_fn, root, info, **args):
            calls.append(f"before:{info.field_name}")
            result = next_fn(root, info, **args)
            calls.append(f"after:{info.field_name}")
            return result

        schema = GraphQLSchema(
            query=GraphQLObjectType(
                "Query",
                {
                    "hello": GraphQLField(
                        GraphQLString, resolve=lambda o, i: "world"
                    ),
                    "goodbye": GraphQLField(
                        GraphQLString, resolve=lambda o, i: "farewell"
                    ),
                },
            )
        )
        result = graphql_sync(
            schema,
            "{ hello goodbye }",
            middleware=MiddlewareManager(log_middleware),
        )
        self.assertEqual(
            result.data, {"hello": "world", "goodbye": "farewell"}
        )
        self.assertEqual(
            calls,
            [
                "before:hello",
                "after:hello",
                "before:goodbye",
                "after:goodbye",
            ],
        )


# ---------------------------------------------------------------------------
# NEW: Weakness-targeting tests
# ---------------------------------------------------------------------------


class TestWeaknessTargeting(unittest.TestCase):

    def test_directive_handling_in_execution(self):
        """@skip and @include directives affect field collection during
        execution. Test both with literal and variable-driven conditions,
        including nested fragments with directives."""
        from graphql import (
            graphql_sync,
            GraphQLSchema,
            GraphQLObjectType,
            GraphQLField,
            GraphQLString,
            GraphQLInt,
        )

        user_type = GraphQLObjectType(
            "User",
            {
                "name": GraphQLField(GraphQLString),
                "age": GraphQLField(GraphQLInt),
                "secret": GraphQLField(GraphQLString),
            },
        )
        schema = GraphQLSchema(
            query=GraphQLObjectType(
                "Query",
                {
                    "user": GraphQLField(
                        user_type,
                        resolve=lambda o, i: {
                            "name": "Alice",
                            "age": 30,
                            "secret": "s3cret",
                        },
                    )
                },
            )
        )

        # @skip with literal true -- field excluded
        r1 = graphql_sync(
            schema, "{ user { name age @skip(if: true) } }"
        )
        self.assertEqual(r1.data, {"user": {"name": "Alice"}})

        # @include with literal false -- field excluded
        r2 = graphql_sync(
            schema, "{ user { name secret @include(if: false) } }"
        )
        self.assertEqual(r2.data, {"user": {"name": "Alice"}})

        # Variable-driven @skip on a fragment spread
        query = """
        query U($hideAge: Boolean!, $showSecret: Boolean!) {
            user {
                name
                ...AgeFields @skip(if: $hideAge)
                secret @include(if: $showSecret)
            }
        }
        fragment AgeFields on User { age }
        """
        r3 = graphql_sync(
            schema, query,
            variable_values={"hideAge": True, "showSecret": True},
        )
        self.assertEqual(
            r3.data, {"user": {"name": "Alice", "secret": "s3cret"}}
        )

        r4 = graphql_sync(
            schema, query,
            variable_values={"hideAge": False, "showSecret": False},
        )
        self.assertEqual(r4.data, {"user": {"name": "Alice", "age": 30}})

    def test_type_coercion_pipeline(self):
        """Build schema with custom scalar, enum input, list/non-null nesting.
        Execute with edge case inputs. Tests the full coerce_input_value
        pipeline depth."""
        from graphql import (
            graphql_sync,
            GraphQLSchema,
            GraphQLObjectType,
            GraphQLField,
            GraphQLString,
            GraphQLInt,
            GraphQLList,
            GraphQLNonNull,
            GraphQLEnumType,
            GraphQLEnumValue,
            GraphQLInputObjectType,
            GraphQLInputField,
            GraphQLArgument,
            GraphQLScalarType,
        )

        # Custom scalar: PositiveInt
        def serialize_pos(value):
            v = int(value)
            if v <= 0:
                raise ValueError("Must be positive")
            return v

        def parse_pos(value):
            v = int(value)
            if v <= 0:
                raise ValueError("Must be positive")
            return v

        pos_int = GraphQLScalarType(
            "PositiveInt", serialize=serialize_pos, parse_value=parse_pos
        )

        priority_enum = GraphQLEnumType(
            "Priority",
            {
                "LOW": GraphQLEnumValue(1),
                "MEDIUM": GraphQLEnumValue(2),
                "HIGH": GraphQLEnumValue(3),
            },
        )

        task_input = GraphQLInputObjectType(
            "TaskInput",
            {
                "title": GraphQLInputField(GraphQLNonNull(GraphQLString)),
                "priority": GraphQLInputField(priority_enum),
                "scores": GraphQLInputField(
                    GraphQLList(GraphQLNonNull(pos_int))
                ),
            },
        )

        schema = GraphQLSchema(
            query=GraphQLObjectType(
                "Query",
                {
                    "createTask": GraphQLField(
                        GraphQLString,
                        args={"input": GraphQLArgument(GraphQLNonNull(task_input))},
                        resolve=lambda o, i, input: (
                            f"{input['title']}|p={input.get('priority')}|"
                            f"scores={input.get('scores')}"
                        ),
                    )
                },
            )
        )

        # Full input with enum and custom scalar list
        r1 = graphql_sync(
            schema,
            '{ createTask(input: {title: "Test", priority: HIGH, scores: [1, 5, 10]}) }',
        )
        self.assertIsNone(r1.errors)
        self.assertEqual(
            r1.data["createTask"], "Test|p=3|scores=[1, 5, 10]"
        )

        # Minimal input -- optional fields omitted
        r2 = graphql_sync(
            schema,
            '{ createTask(input: {title: "Min"}) }',
        )
        self.assertIsNone(r2.errors)
        self.assertEqual(
            r2.data["createTask"], "Min|p=None|scores=None"
        )

        # Variable-driven with nested input
        r3 = graphql_sync(
            schema,
            "query C($t: TaskInput!) { createTask(input: $t) }",
            variable_values={
                "t": {"title": "Var", "priority": "MEDIUM", "scores": [3, 7]},
            },
        )
        self.assertIsNone(r3.errors)
        self.assertEqual(
            r3.data["createTask"], "Var|p=2|scores=[3, 7]"
        )

    def test_schema_validation_errors(self):
        """Build schemas with invalid interface implementations and verify
        schema validation catches them: missing interface fields and
        incompatible interface field types."""
        from graphql import (
            GraphQLSchema,
            GraphQLObjectType,
            GraphQLField,
            GraphQLString,
            GraphQLInt,
            GraphQLInterfaceType,
        )
        from graphql.type import validate_schema

        # Missing interface field implementation
        node_iface = GraphQLInterfaceType(
            "Node",
            {
                "id": GraphQLField(GraphQLString),
                "label": GraphQLField(GraphQLString),
            },
        )
        bad_impl = GraphQLObjectType(
            "BadNode",
            {
                "id": GraphQLField(GraphQLString),
                # missing 'label' field
            },
            interfaces=[node_iface],
        )
        schema1 = GraphQLSchema(
            query=GraphQLObjectType(
                "Query",
                {"node": GraphQLField(node_iface)},
            ),
            types=[bad_impl],
        )
        errors1 = validate_schema(schema1)
        self.assertGreater(len(errors1), 0)
        label_errors = [e for e in errors1 if "label" in e.message]
        self.assertGreater(len(label_errors), 0)

        # Interface field type mismatch
        node_iface2 = GraphQLInterfaceType(
            "Node2",
            {"value": GraphQLField(GraphQLString)},
        )
        bad_impl2 = GraphQLObjectType(
            "BadNode2",
            {"value": GraphQLField(GraphQLInt)},  # String expected
            interfaces=[node_iface2],
        )
        schema2 = GraphQLSchema(
            query=GraphQLObjectType(
                "Query",
                {"node": GraphQLField(node_iface2)},
            ),
            types=[bad_impl2],
        )
        errors2 = validate_schema(schema2)
        self.assertGreater(len(errors2), 0)
        type_mismatch = [e for e in errors2 if "value" in e.message]
        self.assertGreater(len(type_mismatch), 0)


# ---------------------------------------------------------------------------
# NEW: Round 2 hard tests
# ---------------------------------------------------------------------------


class TestRound2Hard(unittest.TestCase):

    def test_variable_type_compatibility(self):
        """VariablesInAllowedPositionRule: variable typed as nullable used where
        non-null is required, and list element nullability mismatches."""
        from graphql import validate, parse, build_schema

        schema = build_schema(
            """
            type Query {
                greet(name: String!): String
                tags(values: [String!]): String
            }
            """
        )

        # String variable used where String! is required -- invalid
        e1 = validate(
            schema,
            parse("query Q($n: String) { greet(name: $n) }"),
        )
        self.assertEqual(len(e1), 1)
        self.assertIn("$n", e1[0].message)
        self.assertTrue(e1[0].locations)

        # String! variable used where String! is required -- valid
        e2 = validate(
            schema,
            parse("query Q($n: String!) { greet(name: $n) }"),
        )
        self.assertEqual(e2, [])

        # [String] variable used where [String!] is required -- invalid
        e3 = validate(
            schema,
            parse("query Q($v: [String]) { tags(values: $v) }"),
        )
        self.assertEqual(len(e3), 1)
        self.assertIn("$v", e3[0].message)
        self.assertTrue(e3[0].locations)

        # [String!] variable used where [String!] is required -- valid
        e4 = validate(
            schema,
            parse("query Q($v: [String!]) { tags(values: $v) }"),
        )
        self.assertEqual(e4, [])

    def test_fragment_type_condition_validation(self):
        """PossibleFragmentSpreadsRule: spreading a fragment on an impossible
        type is caught; valid spreads on interfaces pass."""
        from graphql import validate, parse, build_schema

        schema = build_schema(
            """
            interface Animal { name: String }
            type Cat implements Animal { name: String, purrs: Boolean }
            type Dog implements Animal { name: String, barks: Boolean }
            type Fish { name: String, fins: Int }
            type Query {
                cat: Cat
                animal: Animal
            }
            """
        )

        # Spread fragment on Fish inside Cat field -- impossible
        e1 = validate(
            schema,
            parse(
                """
                { cat { ...fishFrag } }
                fragment fishFrag on Fish { name }
                """
            ),
        )
        self.assertGreaterEqual(len(e1), 1)
        fish_errors = [e for e in e1 if "Fish" in e.message]
        self.assertGreaterEqual(len(fish_errors), 1)

        # Spread fragment on Dog inside Cat field -- impossible (no shared interface means disjoint)
        e2 = validate(
            schema,
            parse(
                """
                { cat { ...dogFrag } }
                fragment dogFrag on Dog { name }
                """
            ),
        )
        self.assertGreaterEqual(len(e2), 1)

        # Spread fragment on Cat inside Animal field -- valid (Cat implements Animal)
        e3 = validate(
            schema,
            parse(
                """
                { animal { ...catFrag } }
                fragment catFrag on Cat { name purrs }
                """
            ),
        )
        self.assertEqual(e3, [])

        # Spread fragment on Animal inside Animal field -- valid
        e4 = validate(
            schema,
            parse(
                """
                { animal { ...animalFrag } }
                fragment animalFrag on Animal { name }
                """
            ),
        )
        self.assertEqual(e4, [])

    def test_provided_required_args_on_directives(self):
        """ProvidedRequiredArgumentsRule applied to directive arguments:
        built-in @deprecated without reason is valid (has default);
        custom directive missing required arg is invalid."""
        from graphql import validate, parse, build_schema

        # @deprecated without explicit reason is valid (has default)
        schema1 = build_schema(
            """
            type Query {
                oldField: String @deprecated
                newField: String
            }
            """
        )
        # Schema itself should be valid
        from graphql.type import validate_schema
        self.assertEqual(validate_schema(schema1), [])

        # Query against that schema is valid
        e1 = validate(schema1, parse("{ oldField newField }"))
        self.assertEqual(e1, [])

        # Custom directive with required arg -- missing it in query
        schema2 = build_schema(
            """
            directive @auth(role: String!) on FIELD
            type Query {
                secret: String
                public: String
            }
            """
        )
        e2 = validate(
            schema2,
            parse("{ secret @auth public }"),
        )
        self.assertGreaterEqual(len(e2), 1)
        role_errors = [e for e in e2 if "role" in e.message]
        self.assertGreaterEqual(len(role_errors), 1)

        # Custom directive with required arg provided -- valid
        e3 = validate(
            schema2,
            parse('{ secret @auth(role: "ADMIN") public }'),
        )
        self.assertEqual(e3, [])

    def test_error_location_and_path_reporting(self):
        """Errors from execution include correct path and location info.
        A nested NonNull field returning null produces error with full path."""
        from graphql import (
            graphql_sync,
            GraphQLSchema,
            GraphQLObjectType,
            GraphQLField,
            GraphQLString,
            GraphQLNonNull,
        )

        profile_type = GraphQLObjectType(
            "Profile",
            {
                "name": GraphQLField(GraphQLNonNull(GraphQLString)),
                "bio": GraphQLField(GraphQLString),
            },
        )
        user_type = GraphQLObjectType(
            "User",
            {
                "profile": GraphQLField(profile_type),
            },
        )
        schema = GraphQLSchema(
            query=GraphQLObjectType(
                "Query",
                {
                    "user": GraphQLField(
                        user_type,
                        resolve=lambda o, i: {
                            "profile": {"name": None, "bio": "hello"},
                        },
                    )
                },
            )
        )

        result = graphql_sync(schema, "{ user { profile { name bio } } }")

        # name is NonNull but resolved to None -> profile becomes null.
        # The error is identified by its response path (right place in the
        # tree), not by message wording.
        self.assertEqual(len(result.errors), 1)
        err = result.errors[0]
        self.assertEqual(err.path, ["user", "profile", "name"])

        # Profile becomes null due to null propagation from NonNull name
        self.assertEqual(
            result.data, {"user": {"profile": None}}
        )

        # Verify location info is present
        self.assertIsNotNone(err.locations)
        self.assertGreater(len(err.locations), 0)
        loc = err.locations[0]
        self.assertIsInstance(loc.line, int)
        self.assertIsInstance(loc.column, int)

    def test_input_object_coercion_edge_cases(self):
        """InputObjectType with required, optional-with-defaults, and nested
        input objects. Tests defaults applied, required field error, unknown
        field rejected."""
        from graphql import (
            graphql_sync,
            validate,
            parse,
            build_schema,
        )

        schema = build_schema(
            """
            input AddressInput {
                street: String!
                city: String = "Unknown"
            }
            input PersonInput {
                name: String!
                age: Int = 25
                address: AddressInput
            }
            type Query {
                register(person: PersonInput!): String
            }
            """
        )

        # Valid with defaults applied
        r1 = graphql_sync(
            schema,
            '{ register(person: {name: "Alice", address: {street: "123 Main"}}) }',
            root_value={
                "register": lambda info, person: (
                    f"{person['name']}|age={person.get('age')}|"
                    f"city={person.get('address', {}).get('city')}"
                ),
            },
        )
        self.assertIsNone(r1.errors)
        self.assertEqual(
            r1.data["register"], "Alice|age=25|city=Unknown"
        )

        # Missing required field 'name' -> validation error
        e1 = validate(
            schema,
            parse('{ register(person: {age: 30}) }'),
        )
        self.assertGreaterEqual(len(e1), 1)
        name_errors = [e for e in e1 if "name" in e.message]
        self.assertGreaterEqual(len(name_errors), 1)

        # Missing required nested field 'street' -> validation error
        e2 = validate(
            schema,
            parse('{ register(person: {name: "Bob", address: {city: "NYC"}}) }'),
        )
        self.assertGreaterEqual(len(e2), 1)
        street_errors = [e for e in e2 if "street" in e.message]
        self.assertGreaterEqual(len(street_errors), 1)

        # Unknown field in input -> validation error
        e3 = validate(
            schema,
            parse('{ register(person: {name: "Eve", unknown: "x"}) }'),
        )
        self.assertGreaterEqual(len(e3), 1)
        unknown_errors = [e for e in e3 if "unknown" in e.message]
        self.assertGreaterEqual(len(unknown_errors), 1)


if __name__ == "__main__":
    unittest.main()
