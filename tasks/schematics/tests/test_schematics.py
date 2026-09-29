"""
Integration tests for the schematics data validation library.

Tests focus on realistic workflows: model declaration with typed fields,
validation with error handling, serialization with roles, nested models,
compound types, model inheritance, and custom validators.
"""

import datetime
import decimal
import uuid

import pytest


# ============================================================================
# 1. Model lifecycle — declare, instantiate, validate, serialize
# ============================================================================


class TestModelLifecycle:
    """Integration tests for the full model lifecycle."""

    def test_model_full_lifecycle_with_mixed_types(self):
        """A user declares a model with multiple types, validates, serializes, and checks equality/repr."""
        from schematics.models import Model
        from schematics.types import (
            StringType,
            IntType,
            BooleanType,
            FloatType,
            DecimalType,
            UUIDType,
            DateTimeType,
            DateType,
        )

        class Record(Model):
            name = StringType(required=True, min_length=1, max_length=50)
            age = IntType(min_value=0, max_value=200)
            score = FloatType()
            active = BooleanType(default=True)
            price = DecimalType()
            uid = UUIDType()
            created = DateTimeType()
            birthday = DateType()

        test_uuid = str(uuid.uuid4())
        data = {
            "name": "Alice",
            "age": 30,
            "score": "3.14",
            "active": True,
            "price": "19.99",
            "uid": test_uuid,
            "created": "2024-06-15T10:30:00.000000",
            "birthday": "1994-03-21",
        }
        rec = Record(data)
        rec.validate()

        # Type coercion verified
        native = rec.to_native()
        assert native["name"] == "Alice"
        assert native["age"] == 30
        assert abs(native["score"] - 3.14) < 0.01
        assert native["active"] is True
        assert isinstance(native["price"], decimal.Decimal)
        assert native["price"] == decimal.Decimal("19.99")
        assert isinstance(native["uid"], uuid.UUID)
        assert isinstance(native["created"], datetime.datetime)
        assert native["created"].year == 2024
        assert isinstance(native["birthday"], datetime.date)
        assert native["birthday"].day == 21

        # Primitive round-trip
        prim = rec.to_primitive()
        assert prim["uid"] == test_uuid
        assert prim["created"].startswith("2024-06-15T10:30:00")
        assert prim["birthday"] == "1994-03-21"

        # Equality and repr
        rec2 = Record(data)
        assert rec == rec2
        assert "Record" in repr(rec)

        # Iteration
        keys = list(rec)
        assert "name" in keys and "age" in keys and "score" in keys
        assert len(rec.items()) == 8

    def test_model_auto_validate_on_construction(self):
        """A user passes validate=True with partial=False to auto-validate during construction."""
        from schematics.models import Model
        from schematics.types import StringType, IntType
        from schematics.exceptions import DataError

        class Strict(Model):
            name = StringType(required=True)
            count = IntType(required=True)

        # validate=True with partial=False triggers full validation at init
        with pytest.raises(DataError):
            Strict({"name": "ok"}, validate=True, partial=False)  # missing 'count'

        # Valid data doesn't raise
        s = Strict({"name": "ok", "count": 5}, validate=True, partial=False)
        assert s.name == "ok"

    def test_model_import_data_flat_and_recursive(self):
        """import_data updates existing instance; recursive=True updates nested models."""
        from schematics.models import Model
        from schematics.types import StringType, IntType, ModelType

        class Profile(Model):
            name = StringType(required=True)
            score = IntType(default=0)

        profile = Profile({"name": "Bob", "score": 10})
        profile.validate()
        profile.import_data({"score": 42})
        profile.validate()
        assert profile.score == 42
        assert profile.name == "Bob"

        class Address(Model):
            city = StringType()
            zip_code = StringType()

        class Person(Model):
            name = StringType()
            address = ModelType(Address)

        person = Person(
            {"name": "Alice", "address": {"city": "NYC", "zip_code": "10001"}}
        )
        person.validate()
        person.import_data({"address": {"city": "LA"}}, recursive=True)
        person.validate()
        assert person.address.city == "LA"

    def test_model_defaults_and_init_options(self):
        """A user creates models with defaults and various init options."""
        from schematics.models import Model
        from schematics.types import IntType, StringType
        from schematics.exceptions import UndefinedValueError

        class Config(Model):
            retries = IntType(default=3)
            mode = StringType(default="fast")
            label = StringType()

        c = Config()
        assert c.retries == 3
        assert c.mode == "fast"
        assert c.label is None

        c2 = Config(init=False)
        with pytest.raises(UndefinedValueError):
            _ = c2.retries

    def test_model_field_access_and_dict_protocol(self):
        """Attribute and dict-like access, set, delete, contains, keys, values."""
        from schematics.models import Model
        from schematics.types import StringType, IntType
        from schematics.exceptions import UndefinedValueError, UnknownFieldError

        class Item(Model):
            name = StringType()
            qty = IntType()

        item = Item({"name": "Widget", "qty": 5})
        assert item.name == "Widget"
        assert item["name"] == "Widget"

        item.name = "Gadget"
        assert item.name == "Gadget"

        del item.name
        with pytest.raises(UndefinedValueError):
            _ = item.name

        with pytest.raises(UnknownFieldError):
            _ = item["nonexistent"]

        # Dict protocol: contains, keys, values, setitem
        item2 = Item({"name": "test", "qty": 5})
        item2.validate()
        assert "name" in item2
        assert "missing" not in item2
        assert "name" in item2.keys()
        assert "test" in item2.values()

        item2["name"] = "updated"
        assert item2.name == "updated"

        with pytest.raises(UnknownFieldError):
            item2["nonexistent"] = "bad"

        # Dict-style deletion
        item3 = Item({"name": "Widget", "qty": 5})
        del item3["name"]
        with pytest.raises(Exception):
            _ = item3["name"]

        with pytest.raises(UnknownFieldError):
            del item3["nonexistent"]


# ============================================================================
# 2. Validation and error handling
# ============================================================================


class TestValidation:
    """Integration tests for validation with DataError handling."""

    def test_validation_required_and_coercion_errors(self):
        """Missing required fields and type coercion failures produce DataError."""
        from schematics.models import Model
        from schematics.types import StringType, IntType
        from schematics.exceptions import DataError
        import json

        class Order(Model):
            product = StringType(required=True)
            quantity = IntType(required=True)

        # Missing required field
        order = Order({"product": "Widget"})
        with pytest.raises(DataError) as exc_info:
            order.validate()
        assert "quantity" in exc_info.value.errors

        # DataError.to_primitive is JSON-serializable
        prim = exc_info.value.to_primitive()
        json.dumps(prim)  # should not raise

        # Coercion error
        with pytest.raises(DataError) as exc_info:
            Order({"product": "Widget", "quantity": "not_a_number"})
        assert "quantity" in exc_info.value.errors

    def test_validation_partial_and_strict(self):
        """partial=True skips required checks; strict=True rejects rogue fields."""
        from schematics.models import Model
        from schematics.types import StringType, IntType
        from schematics.exceptions import DataError

        class Doc(Model):
            title = StringType(required=True)
            pages = IntType(required=True)

        # partial=True
        doc = Doc({"title": "Test"})
        doc.validate(partial=True)
        assert doc.title == "Test"

        # strict=True
        with pytest.raises(DataError) as exc_info:
            Doc({"title": "ok", "pages": 1, "rogue": "bad"}, strict=True)
        assert "rogue" in exc_info.value.errors

    def test_string_and_int_range_constraints(self):
        """StringType min/max_length and IntType min/max_value constraints."""
        from schematics.models import Model
        from schematics.types import StringType, IntType
        from schematics.exceptions import DataError

        class Constrained(Model):
            label = StringType(min_length=2, max_length=10, required=True)
            score = IntType(min_value=0, max_value=100, required=True)

        Constrained({"label": "Bob", "score": 50}).validate()

        with pytest.raises(DataError):
            Constrained({"label": "A", "score": 50}).validate()  # too short

        with pytest.raises(DataError):
            Constrained({"label": "A" * 11, "score": 50}).validate()  # too long

        with pytest.raises(DataError):
            Constrained({"label": "ok", "score": -1}).validate()  # below min

        with pytest.raises(DataError):
            Constrained({"label": "ok", "score": 101}).validate()  # above max

    def test_deep_nested_error_aggregation(self):
        """Errors across deeply nested structures are aggregated in one DataError."""
        from schematics.models import Model
        from schematics.types import StringType, IntType, ModelType, ListType
        from schematics.exceptions import DataError

        class Item(Model):
            name = StringType(required=True)
            qty = IntType(required=True)

        class Order(Model):
            customer = StringType(required=True)
            items = ListType(ModelType(Item), required=True)

        order = Order(
            {
                "items": [
                    {"name": "Widget"},  # missing qty
                    {},  # missing both
                ]
            }
        )
        with pytest.raises(DataError) as exc_info:
            order.validate()

        errors = exc_info.value.errors
        # Should have errors for 'customer' (missing) and 'items' (nested errors)
        assert "customer" in errors
        assert "items" in errors


# ============================================================================
# 4. Compound types — ListType, DictType, ModelType
# ============================================================================


class TestCompoundTypes:
    """Integration tests for compound types with nested structures."""

    def test_list_and_dict_type_with_constraints(self):
        """ListType enforces min/max size; DictType coerces keys and validates values."""
        from schematics.models import Model
        from schematics.types import StringType, IntType, ListType, DictType
        from schematics.exceptions import DataError

        class Inventory(Model):
            tags = ListType(StringType, required=True)
            values = ListType(IntType, min_size=1, max_size=3, required=True)
            scores = DictType(IntType, coerce_key=str, required=True)

        inv = Inventory(
            {
                "tags": ["a", "b"],
                "values": [1, 2],
                "scores": {"math": 90, "science": 85},
            }
        )
        inv.validate()
        prim = inv.to_primitive()
        assert prim["tags"] == ["a", "b"]
        assert prim["values"] == [1, 2]
        assert prim["scores"]["math"] == 90

        with pytest.raises(DataError):
            Inventory({"tags": [], "values": [], "scores": {}}).validate()

        with pytest.raises(DataError):
            Inventory({"tags": [], "values": [1, 2, 3, 4], "scores": {}}).validate()

    def test_nested_model_type_validates_recursively(self):
        """ModelType validates nested model structures recursively."""
        from schematics.models import Model
        from schematics.types import StringType, IntType, ModelType
        from schematics.exceptions import DataError

        class Address(Model):
            street = StringType(required=True)
            city = StringType(required=True)

        class Person(Model):
            name = StringType(required=True)
            address = ModelType(Address, required=True)

        person = Person(
            {
                "name": "Alice",
                "address": {"street": "123 Main St", "city": "Springfield"},
            }
        )
        person.validate()
        prim = person.to_primitive()
        assert prim["address"]["city"] == "Springfield"
        assert isinstance(person.address, Address)

        # Nested validation error propagates
        outer = Person({"name": "Bob", "address": {}})
        with pytest.raises(DataError) as exc_info:
            outer.validate()
        assert "address" in exc_info.value.errors

    def test_list_and_dict_of_model_type(self):
        """ListType(ModelType) and DictType(ModelType) validate nested collections."""
        from schematics.models import Model
        from schematics.types import StringType, IntType, ModelType, ListType, DictType

        class Item(Model):
            name = StringType(required=True)
            price = IntType(required=True)

        class Config(Model):
            value = IntType(required=True)

        class Store(Model):
            items = ListType(ModelType(Item), required=True)
            settings = DictType(ModelType(Config))

        store = Store(
            {
                "items": [
                    {"name": "Widget", "price": 10},
                    {"name": "Gadget", "price": 20},
                ],
                "settings": {"timeout": {"value": 30}, "retries": {"value": 3}},
            }
        )
        store.validate()
        prim = store.to_primitive()
        assert len(prim["items"]) == 2
        assert prim["items"][0]["name"] == "Widget"
        assert prim["settings"]["timeout"]["value"] == 30


# ============================================================================
# 5. Role-based serialization
# ============================================================================


class TestRoles:
    """Integration tests for role-based field filtering."""

    def test_whitelist_and_blacklist_roles(self):
        """Whitelist exports only listed fields; blacklist excludes listed fields."""
        from schematics.models import Model
        from schematics.types import StringType
        from schematics.transforms import whitelist, blacklist

        class User(Model):
            name = StringType()
            email = StringType()
            password = StringType()

            class Options:
                roles = {
                    "public": whitelist("name"),
                    "owner": whitelist("name", "email"),
                    "safe": blacklist("password"),
                }

        user = User({"name": "Alice", "email": "alice@test.com", "password": "secret"})
        user.validate()

        public = user.to_primitive(role="public")
        assert public == {"name": "Alice"}

        owner = user.to_primitive(role="owner")
        assert owner == {"name": "Alice", "email": "alice@test.com"}

        safe = user.to_primitive(role="safe")
        assert safe == {"name": "Alice", "email": "alice@test.com"}

    def test_undefined_role_raises_error(self):
        """Accessing an undefined role raises ValueError."""
        from schematics.models import Model
        from schematics.types import StringType

        class Simple(Model):
            name = StringType()

        s = Simple({"name": "test"})
        s.validate()
        with pytest.raises(ValueError):
            s.to_primitive(role="nonexistent")

    def test_export_composing_roles_export_level_serialize_when_none(self):
        """Roles + export_level + serialize_when_none compose on nested models."""
        from schematics.models import Model
        from schematics.types import StringType, IntType, ModelType
        from schematics.transforms import whitelist
        from schematics.common import ALL

        class Inner(Model):
            visible = StringType()
            hidden = StringType()

            class Options:
                roles = {"api": whitelist("visible")}
                serialize_when_none = False

        class Outer(Model):
            label = StringType(export_level=ALL)
            detail = StringType()
            child = ModelType(Inner)

            class Options:
                roles = {"api": whitelist("label", "child")}

        outer = Outer(
            {
                "label": None,
                "detail": "secret",
                "child": {"visible": "yes", "hidden": "no"},
            }
        )
        outer.validate()

        api = outer.to_primitive(role="api")
        assert api == {"label": None, "child": {"visible": "yes"}}


# ============================================================================
# 6. Model inheritance
# ============================================================================


class TestModelInheritance:
    """Integration tests for model inheritance."""

    def test_multi_level_inheritance_with_override(self):
        """Fields, roles, and validators accumulate through inheritance chain."""
        from schematics.models import Model
        from schematics.types import StringType, IntType, BooleanType
        from schematics.transforms import whitelist
        from schematics.exceptions import DataError, ValidationError

        class Base(Model):
            name = StringType(required=True)

            class Options:
                roles = {"public": whitelist("name")}

        class Mid(Base):
            score = IntType()

        class Child(Mid):
            active = BooleanType()
            score = IntType(required=True)  # override: now required

            def validate_score(self, data, value):
                if value < 0:
                    raise ValidationError("Must be non-negative")

        c = Child({"name": "Test", "score": 10, "active": True})
        c.validate()
        prim = c.to_primitive()
        assert prim == {"name": "Test", "score": 10, "active": True}

        # Inherited role
        public = c.to_primitive(role="public")
        assert "name" in public
        assert "score" not in public

        # Validator from Child
        with pytest.raises(DataError):
            Child({"name": "Bad", "score": -5}).validate()


# ============================================================================
# 7. Custom validators
# ============================================================================


class TestCustomValidators:
    """Integration tests for field-level and model-level validators."""

    def test_field_and_model_level_validators(self):
        """Field validators and model-level validate_<field> methods work together."""
        from schematics.models import Model
        from schematics.types import IntType
        from schematics.exceptions import DataError, ValidationError

        def check_even(value):
            if value % 2 != 0:
                raise ValidationError("Must be even")

        class RangeModel(Model):
            min_val = IntType(required=True, validators=[check_even])
            max_val = IntType(required=True)

            def validate_max_val(self, data, value):
                if value < data.get("min_val", 0):
                    raise ValidationError("max must be >= min")

        RangeModel({"min_val": 2, "max_val": 10}).validate()

        with pytest.raises(DataError):
            RangeModel({"min_val": 3, "max_val": 10}).validate()  # odd min_val

        with pytest.raises(DataError):
            RangeModel({"min_val": 10, "max_val": 5}).validate()  # max < min


# ============================================================================
# 9. Serialized/deserialized names
# ============================================================================


class TestSerializedName:
    """Integration tests for field name remapping."""

    def test_serialized_and_deserialized_names(self):
        """serialized_name remaps output; deserialize_from accepts alternate input."""
        from schematics.models import Model
        from schematics.types import StringType

        class ApiModel(Model):
            internal_id = StringType(serialized_name="id")
            user_name = StringType(deserialize_from=["username", "user_name"])

        m = ApiModel({"internal_id": "abc", "username": "alice"})
        m.validate()
        prim = m.to_primitive()
        assert prim["id"] == "abc"
        assert m.user_name == "alice"


# ============================================================================
# 10. PolyModelType
# ============================================================================


class TestPolyModelType:
    """Integration tests for polymorphic model type."""

    def test_poly_model_type_with_claim_function(self):
        """PolyModelType resolves the correct model using a claim function."""
        from schematics.models import Model
        from schematics.types import StringType, IntType, PolyModelType

        class Cat(Model):
            name = StringType(required=True)
            lives = IntType(default=9)

        class Dog(Model):
            name = StringType(required=True)
            breed = StringType()

        def claim(field, data):
            return Cat if "lives" in data else Dog

        class Pet(Model):
            animal = PolyModelType([Cat, Dog], claim_function=claim)

        pet1 = Pet({"animal": {"name": "Whiskers", "lives": 7}})
        pet1.validate()
        assert isinstance(pet1.animal, Cat)

        pet2 = Pet({"animal": {"name": "Rex", "breed": "Lab"}})
        pet2.validate()
        assert isinstance(pet2.animal, Dog)


# ============================================================================
# 11. Export level + Union type
# ============================================================================


class TestExportLevelAndUnionType:
    """Integration tests for export levels and union types."""

    def test_union_type_accepts_multiple_types(self):
        """UnionType accepts values matching any specified type."""
        from schematics.models import Model
        from schematics.types import UnionType, StringType, IntType

        class Flex(Model):
            value = UnionType(types=(IntType, StringType))

        m = Flex({"value": 42})
        m.validate()
        assert m.value == 42
        assert isinstance(m.value, int)

        m2 = Flex({"value": "hello"})
        m2.validate()
        assert m2.value == "hello"
        assert isinstance(m2.value, str)


# ============================================================================
# 12. Complex integration workflows
# ============================================================================


class TestComplexWorkflows:
    """Complex integration tests combining multiple features."""

    def test_full_api_workflow(self):
        """Full workflow: nested models + roles + validators + error handling."""
        from schematics.models import Model
        from schematics.types import StringType, IntType, EmailType, ModelType, ListType
        from schematics.transforms import whitelist, blacklist
        from schematics.exceptions import DataError, ValidationError

        class Address(Model):
            street = StringType(required=True)
            city = StringType(required=True)

            class Options:
                roles = {"public": whitelist("city"), "admin": blacklist()}

        class User(Model):
            name = StringType(required=True, min_length=1)
            email = EmailType(required=True)
            age = IntType(min_value=0)
            address = ModelType(Address)
            tags = ListType(StringType)

            class Options:
                roles = {"public": whitelist("name", "tags"), "admin": blacklist()}

            def validate_age(self, data, value):
                if value is not None and value < 13:
                    raise ValidationError("Must be at least 13")

        user = User(
            {
                "name": "Alice",
                "email": "alice@example.com",
                "age": 25,
                "address": {"street": "123 Main", "city": "NYC"},
                "tags": ["python"],
            }
        )
        user.validate()

        public = user.to_primitive(role="public")
        assert public == {"name": "Alice", "tags": ["python"]}

        admin = user.to_primitive(role="admin")
        assert admin["name"] == "Alice"
        assert admin["email"] == "alice@example.com"
        assert admin["address"] == {"street": "123 Main", "city": "NYC"}

        with pytest.raises(DataError):
            User({"name": "Kid", "email": "kid@test.com", "age": 10}).validate()

    def test_deeply_nested_validation_and_serialization(self):
        """3+ level nested models validate and serialize correctly."""
        from schematics.models import Model
        from schematics.types import StringType, IntType, ModelType, ListType

        class Skill(Model):
            name = StringType(required=True)
            level = IntType(min_value=1, max_value=10, required=True)

        class Employee(Model):
            name = StringType(required=True)
            skills = ListType(ModelType(Skill))

        class Company(Model):
            name = StringType(required=True)
            employees = ListType(ModelType(Employee), required=True)

        company = Company(
            {
                "name": "Acme",
                "employees": [
                    {"name": "Alice", "skills": [{"name": "Python", "level": 9}]},
                    {"name": "Bob", "skills": [{"name": "SQL", "level": 7}]},
                ],
            }
        )
        company.validate()
        prim = company.to_primitive()
        assert prim["employees"][0]["skills"][0]["name"] == "Python"


# ============================================================================
# 13. Contrib modules — EnumType, ObjectIdType, ModelHelpTextMixin
# ============================================================================


class TestContribModules:
    """Integration tests for contrib extensions."""

    def test_enum_type_by_name_and_value(self):
        """EnumType converts between enum members, names, and values."""
        from enum import Enum
        from schematics.models import Model
        from schematics.contrib.enum_type import EnumType
        from schematics.exceptions import DataError

        class Color(Enum):
            RED = 1
            GREEN = 2
            BLUE = 3

        class Config(Model):
            color = EnumType(Color, required=True)
            mode = EnumType(Color, use_values=True)

        # By name
        c = Config({"color": "RED"})
        c.validate()
        assert c.color == Color.RED

        # Serialize back to name
        prim = c.to_primitive()
        assert prim["color"] == "RED"

        # By value (use_values=True)
        c2 = Config({"color": "GREEN", "mode": 2})
        c2.validate()
        assert c2.mode == Color.GREEN

        # use_values serializes to value
        prim2 = c2.to_primitive()
        assert prim2["mode"] == 2

        # Invalid name raises
        with pytest.raises(DataError):
            Config({"color": "INVALID"}).validate()

    def test_objectid_type_converts_and_validates(self):
        """ObjectIdType converts strings to/from BSON ObjectId."""
        from bson.objectid import ObjectId
        from schematics.models import Model
        from schematics.contrib.mongo import ObjectIdType
        from schematics.exceptions import DataError

        class Doc(Model):
            oid = ObjectIdType(required=True)

        fake_oid = ObjectId()

        # From ObjectId instance
        d = Doc({"oid": fake_oid})
        d.validate()
        assert d.oid == fake_oid

        # From string
        d2 = Doc({"oid": str(fake_oid)})
        d2.validate()
        assert d2.oid == fake_oid

        # Serialize to string
        prim = d2.to_primitive()
        assert prim["oid"] == str(fake_oid)

        # Invalid OID raises
        with pytest.raises(DataError):
            Doc({"oid": "not-a-valid-oid"}).validate()

    def test_model_help_text_mixin(self):
        """ModelHelpTextMixin generates help text from model field metadata."""
        from schematics.models import Model
        from schematics.types import StringType, IntType
        from schematics.extensions.model_help_text_mixin import (
            ModelHelpTextMixin,
            help_text_metadata,
        )

        class Person(Model, ModelHelpTextMixin):
            """A person model."""

            name = StringType(
                required=True,
                metadata=help_text_metadata(
                    label="Name",
                    description="The person's full name",
                    example="John Doe",
                ),
            )
            age = IntType(
                metadata=help_text_metadata(
                    label="Age", description="Age in years", example="30"
                )
            )

        # help_text_metadata returns a dict
        meta = help_text_metadata(label="X", description="Y", example="Z")
        assert meta == {"label": "X", "description": "Y", "example": "Z"}

        # get_helptext returns formatted help string containing field labels and descriptions
        helptext = Person.get_helptext()
        assert isinstance(helptext, str)
        assert "Name" in helptext
        assert "The person's full name" in helptext
        assert "Age" in helptext


# ============================================================================
# 14. Serializable (computed) fields
# ============================================================================


class TestSerializableFields:
    """Integration tests for @serializable computed fields."""

    def test_serializable_computed_and_typed(self):
        """@serializable creates computed fields; with custom type controls export."""
        from schematics.models import Model
        from schematics.types import StringType, IntType
        from schematics.types.serializable import serializable

        class Product(Model):
            name = StringType(required=True)
            price = IntType(required=True)
            quantity = IntType(required=True)

            @serializable
            def total(self):
                return self.price * self.quantity

        p = Product({"name": "Widget", "price": 10, "quantity": 3})
        p.validate()
        assert p.total == 30
        prim = p.to_primitive()
        assert prim["total"] == 30

        class Greeting(Model):
            first = StringType()
            last = StringType()

            @serializable(StringType())
            def full_name(self):
                return "%s %s" % (self.first, self.last)

        g = Greeting({"first": "John", "last": "Doe"})
        g.validate()
        assert g.full_name == "John Doe"


# ============================================================================
# 15. Basic type coercion, constraints, and serialization
# ============================================================================


class TestBasicTypeCoercionAndSerialization:
    """Bundled tests for BooleanType, StringType regex, DecimalType, and DateType formats."""

    def test_boolean_regex_decimal_and_date_format(self):
        """BooleanType coercion, StringType regex, DecimalType serialization, DateType custom format."""
        from schematics.models import Model
        from schematics.types import BooleanType, StringType, DecimalType, DateType
        from schematics.exceptions import DataError

        class Mixed(Model):
            flag = BooleanType(required=True)
            code = StringType(regex=r"^[A-Z]{3}-\d{3}$", required=True)
            price = DecimalType(required=True)
            event_date = DateType(formats=["%d/%m/%Y"], required=True)

        m = Mixed(
            {
                "flag": "True",
                "code": "ABC-123",
                "price": "19.99",
                "event_date": "25/12/2024",
            }
        )
        m.validate()
        assert m.flag is True
        assert m.code == "ABC-123"
        assert m.price == decimal.Decimal("19.99")
        assert m.event_date == datetime.date(2024, 12, 25)

        prim = m.to_primitive()
        assert prim["price"] == "19.99"
        assert isinstance(prim["price"], str)

        for truthy in ["true", "1", 1]:
            assert (
                Mixed(
                    {
                        "flag": truthy,
                        "code": "ABC-123",
                        "price": "1",
                        "event_date": "01/01/2024",
                    }
                ).flag
                is True
            )
        for falsy in ["False", "0", 0]:
            assert (
                Mixed(
                    {
                        "flag": falsy,
                        "code": "ABC-123",
                        "price": "1",
                        "event_date": "01/01/2024",
                    }
                ).flag
                is False
            )

        with pytest.raises(DataError):
            Mixed(
                {
                    "flag": True,
                    "code": "abc-123",
                    "price": "1",
                    "event_date": "01/01/2024",
                }
            ).validate()

        with pytest.raises(DataError):
            Mixed(
                {
                    "flag": True,
                    "code": "ABC-123",
                    "price": "not-a-number",
                    "event_date": "01/01/2024",
                }
            ).validate()

        with pytest.raises(DataError):
            Mixed(
                {
                    "flag": True,
                    "code": "ABC-123",
                    "price": "1",
                    "event_date": "2024-12-25",
                }
            ).validate()


# ============================================================================
# 17. DateTimeType advanced — timezone and timestamp parsing
# ============================================================================


class TestDateTimeAdvanced:
    """Integration tests for DateTimeType timezone and timestamp features."""

    def test_datetime_timezone_utc_conversion_and_timestamp(self):
        """DateTimeType and variants: TZ parsing, UTC conversion, timestamp input, UTCDateTimeType, TimestampType."""
        from schematics.models import Model
        from schematics.types import DateTimeType, UTCDateTimeType, TimestampType

        class Event(Model):
            ts = DateTimeType(required=True)

        e = Event({"ts": "2024-06-15T10:30:00Z"})
        e.validate()
        assert e.ts.tzinfo is not None

        e2 = Event({"ts": "2024-06-15T10:30:00+05:30"})
        e2.validate()
        assert e2.ts.tzinfo is not None
        assert e2.ts.hour == 10

        class StrictEvent(Model):
            ts = DateTimeType(convert_tz=True, required=True)

        e3 = StrictEvent({"ts": "2024-06-15T10:30:00+05:00"})
        e3.validate()
        assert e3.ts.hour == 5
        assert e3.ts.minute == 30

        log = Event({"ts": 0})
        log.validate()
        assert log.ts.year == 1970
        assert log.ts.month == 1
        assert log.ts.day == 1

        # UTCDateTimeType normalizes to UTC and drops tzinfo
        class UtcEvent(Model):
            ts = UTCDateTimeType(required=True)

        eu = UtcEvent({"ts": "2024-06-15T10:30:00+05:00"})
        eu.validate()
        assert eu.ts.hour == 5
        assert eu.ts.minute == 30
        assert eu.ts.tzinfo is None
        eu_prim = UtcEvent({"ts": "2024-06-15T10:30:00+05:00"}).to_primitive()["ts"]
        assert eu_prim.startswith("2024-06-15T05:30:00")
        assert eu_prim.endswith("Z")

        # TimestampType exports as Unix timestamp float
        class LogEntry(Model):
            ts = TimestampType(required=True)

        entry = LogEntry({"ts": "2024-01-01T00:00:00Z"})
        entry.validate()
        prim = entry.to_primitive()
        assert isinstance(prim["ts"], float)
        assert prim["ts"] == 1704067200.0


# ============================================================================
# 18. Export level constants — NONEMPTY, DEFAULT, DROP
# ============================================================================


class TestExportLevels:
    """Integration tests for all export level constants."""

    def test_export_levels_drop_nonempty_default_not_none(self):
        """DROP never exports; NONEMPTY drops empty compounds; DEFAULT includes None; NOT_NONE excludes None."""
        from schematics.models import Model
        from schematics.types import StringType, ListType
        from schematics.common import DROP, NONEMPTY, DEFAULT, NOT_NONE

        class MultiLevel(Model):
            dropped = StringType(export_level=DROP)
            items = ListType(StringType, export_level=NONEMPTY)
            always = StringType(export_level=DEFAULT)
            selective = StringType(export_level=NOT_NONE)

        m = MultiLevel({"dropped": "hidden", "items": [], "always": None})
        m.validate()
        prim = m.to_primitive()

        assert "dropped" not in prim
        assert "items" not in prim
        assert "always" in prim and prim["always"] is None
        assert "selective" not in prim

        m2 = MultiLevel({"dropped": "x", "items": ["a"], "selective": "yes"})
        m2.validate()
        prim2 = m2.to_primitive()
        assert "items" in prim2 and prim2["items"] == ["a"]
        assert prim2["selective"] == "yes"


# ============================================================================
# 20. Specialized types — TimedeltaType, GeoPointType, MultilingualStringType
# ============================================================================


class TestSpecializedTypes:
    """Bundled tests for specialized types that require non-trivial conversion."""

    def test_timedelta_geopoint_and_multilingual(self):
        """TimedeltaType precision, GeoPointType range validation, MultilingualStringType locale export."""
        from schematics.models import Model
        from schematics.types import TimedeltaType, GeoPointType, MultilingualStringType
        from schematics.exceptions import DataError

        class Record(Model):
            duration = TimedeltaType(precision="seconds", required=True)
            interval = TimedeltaType(precision="minutes", required=True)
            coords = GeoPointType(required=True)
            title = MultilingualStringType(default_locale="en", required=True)

        r = Record(
            {
                "duration": 3600,
                "interval": 90,
                "coords": [40.7128, -74.0060],
                "title": {"en": "Hello", "fr": "Bonjour"},
            }
        )
        r.validate()
        assert r.duration == datetime.timedelta(seconds=3600)
        assert r.interval == datetime.timedelta(minutes=90)
        assert r.coords == [40.7128, -74.0060]
        assert r.title == {"en": "Hello", "fr": "Bonjour"}

        prim = r.to_primitive()
        assert prim["duration"] == 3600
        assert prim["interval"] == 90
        assert prim["title"] == "Hello"

        with pytest.raises(DataError):
            Record(
                {
                    "duration": 1,
                    "interval": 1,
                    "coords": [91.0, 0.0],
                    "title": {"en": "x"},
                }
            ).validate()

        with pytest.raises(DataError):
            Record(
                {"duration": 1, "interval": 1, "coords": "bad", "title": {"en": "x"}}
            ).validate()


# ============================================================================
# 21. Format validation types — URL, Email, IPv4, MAC, MD5, SHA1
# ============================================================================


class TestFormatValidationTypes:
    """Bundled tests for types that validate string format patterns."""

    def test_url_email_ipv4_mac_md5_sha1(self):
        """All format-validating types: accept valid, reject invalid."""
        from schematics.models import Model
        from schematics.types import URLType, EmailType, MD5Type, SHA1Type
        from schematics.types.net import IPv4Type, MACAddressType
        from schematics.exceptions import DataError

        valid_md5 = "d41d8cd98f00b204e9800998ecf8427e"
        valid_sha1 = "da39a3ee5e6b4b0d3255bfef95601890afd80709"

        class AllFormats(Model):
            url = URLType(required=True)
            email = EmailType(required=True)
            ip = IPv4Type(required=True)
            mac = MACAddressType(required=True)
            md5 = MD5Type(required=True)
            sha1 = SHA1Type(required=True)

        af = AllFormats(
            {
                "url": "https://example.com",
                "email": "user@example.com",
                "ip": "192.168.1.1",
                "mac": "AA:BB:CC:DD:EE:FF",
                "md5": valid_md5,
                "sha1": valid_sha1,
            }
        )
        af.validate()
        prim = af.to_primitive()
        assert prim["mac"] == "AA:BB:CC:DD:EE:FF"
        assert prim["md5"] == valid_md5

        for bad_field, bad_val in [
            ("url", "not-a-url"),
            ("email", "invalid"),
            ("ip", "999.999.999.999"),
            ("mac", "invalid-mac"),
            ("md5", "tooshort"),
            ("sha1", "xyz"),
        ]:
            data = {
                "url": "https://x.com",
                "email": "a@b.com",
                "ip": "10.0.0.1",
                "mac": "AA:BB:CC:DD:EE:FF",
                "md5": valid_md5,
                "sha1": valid_sha1,
            }
            data[bad_field] = bad_val
            with pytest.raises(DataError):
                AllFormats(data).validate()


# ============================================================================
# 33. Harder compositions — multi-feature interactions
# ============================================================================


class TestCompoundTypeClassVsInstance:
    """Tests that compound types accept type classes (not just instances)."""

    def test_list_and_dict_accept_type_class_or_instance(self):
        """ListType(StringType) and ListType(StringType()) both work correctly."""
        from schematics.models import Model
        from schematics.types import StringType, IntType, ListType, DictType
        from schematics.exceptions import DataError

        class WithClass(Model):
            tags = ListType(StringType, required=True)
            scores = DictType(IntType, required=True)

        class WithInstance(Model):
            tags = ListType(StringType(), required=True)
            scores = DictType(IntType(), required=True)

        data = {"tags": ["a", "b"], "scores": {"x": 1, "y": 2}}

        for Cls in [WithClass, WithInstance]:
            m = Cls(data)
            m.validate()
            prim = m.to_primitive()
            assert prim["tags"] == ["a", "b"]
            assert prim["scores"]["x"] == 1

        with pytest.raises(DataError):
            WithClass({"tags": ["a"], "scores": {"x": "bad"}}).validate()


class TestNestedRolesThreeLevels:
    """Tests that roles propagate correctly through 3+ levels of nesting."""

    def test_roles_propagate_through_three_nested_levels(self):
        """Each nested model applies its own role definition recursively."""
        from schematics.models import Model
        from schematics.types import StringType, ModelType
        from schematics.transforms import whitelist, blacklist

        class Geo(Model):
            lat = StringType()
            lng = StringType()
            internal_code = StringType()

            class Options:
                roles = {"api": whitelist("lat", "lng")}

        class Address(Model):
            street = StringType()
            city = StringType()
            geo = ModelType(Geo)

            class Options:
                roles = {"api": whitelist("city", "geo")}

        class Company(Model):
            name = StringType()
            secret_key = StringType()
            hq = ModelType(Address)

            class Options:
                roles = {"api": blacklist("secret_key")}

        company = Company(
            {
                "name": "Acme",
                "secret_key": "sk-123",
                "hq": {
                    "street": "123 Main",
                    "city": "NYC",
                    "geo": {"lat": "40.7", "lng": "-74.0", "internal_code": "X99"},
                },
            }
        )
        company.validate()

        api = company.to_primitive(role="api")
        assert api["name"] == "Acme"
        assert "secret_key" not in api
        assert "street" not in api["hq"]
        assert api["hq"]["city"] == "NYC"
        assert api["hq"]["geo"]["lat"] == "40.7"
        assert "internal_code" not in api["hq"]["geo"]


class TestSerializedNameWithRolesAndNested:
    """Tests serialized_name + deserialize_from interacting with roles and nesting."""

    def test_serialized_name_survives_role_filtering(self):
        """serialized_name remaps keys even when roles filter other fields."""
        from schematics.models import Model
        from schematics.types import StringType, IntType, ModelType
        from schematics.transforms import whitelist

        class Detail(Model):
            internal_score = IntType(serialized_name="score")
            notes = StringType()

            class Options:
                roles = {"public": whitelist("internal_score")}

        class Record(Model):
            ref_id = StringType(
                serialized_name="id",
                deserialize_from=["ref_id", "reference_id"],
            )
            detail = ModelType(Detail)

            class Options:
                roles = {"public": whitelist("ref_id", "detail")}

        r = Record(
            {
                "reference_id": "abc-123",
                "detail": {"internal_score": 95, "notes": "secret"},
            }
        )
        r.validate()

        prim = r.to_primitive(role="public")
        assert prim["id"] == "abc-123"
        assert "notes" not in prim["detail"]
        assert prim["detail"]["score"] == 95


class TestValidateModifyRevalidate:
    """Tests the validated/converted layer separation across mutations."""

    def test_modify_after_validate_requires_revalidation(self):
        """Changing a field after validate() moves data back to converted layer."""
        from schematics.models import Model
        from schematics.types import StringType, IntType
        from schematics.exceptions import DataError, ValidationError

        class Bounded(Model):
            name = StringType(required=True)
            value = IntType(min_value=0, max_value=100, required=True)

            def validate_value(self, data, value):
                if value == 42:
                    raise ValidationError("42 is not allowed")

        b = Bounded({"name": "test", "value": 50})
        b.validate()
        native1 = b.to_native()
        assert native1["value"] == 50

        b.value = 75
        b.validate()
        assert b.value == 75

        b.value = 42
        with pytest.raises(DataError):
            b.validate()

        b.value = 200
        with pytest.raises(DataError):
            b.validate()


class TestExportLevelWithSerializeWhenNoneInteraction:
    """Tests the interaction between per-field export_level and model-level serialize_when_none."""

    def test_export_level_overrides_model_serialize_when_none(self):
        """Per-field export_level takes precedence over Options.serialize_when_none."""
        from schematics.models import Model
        from schematics.types import StringType, IntType, ListType
        from schematics.common import ALL, DROP, NOT_NONE, NONEMPTY

        class Hybrid(Model):
            always_show = StringType(export_level=ALL)
            never_show = StringType(export_level=DROP)
            not_none_show = IntType(export_level=NOT_NONE)
            nonempty_list = ListType(StringType, export_level=NONEMPTY)
            normal = StringType()

            class Options:
                serialize_when_none = False

        h = Hybrid(
            {
                "always_show": None,
                "never_show": "hidden",
                "not_none_show": None,
                "nonempty_list": [],
                "normal": None,
            }
        )
        h.validate()
        prim = h.to_primitive()

        assert "always_show" in prim and prim["always_show"] is None
        assert "never_show" not in prim
        assert "not_none_show" not in prim
        assert "nonempty_list" not in prim
        assert "normal" not in prim

        h2 = Hybrid({"always_show": "x", "not_none_show": 5, "nonempty_list": ["a"]})
        h2.validate()
        prim2 = h2.to_primitive()
        assert prim2["not_none_show"] == 5
        assert prim2["nonempty_list"] == ["a"]
        assert "never_show" not in prim2


class TestPolyModelWithValidationAndRoles:
    """Tests PolyModelType combined with validation and roles."""

    def test_poly_model_validates_and_serializes_with_roles(self):
        """PolyModelType dispatches, validates nested, and applies roles."""
        from schematics.models import Model
        from schematics.types import StringType, IntType, PolyModelType
        from schematics.transforms import whitelist
        from schematics.exceptions import DataError

        class EmailNotif(Model):
            channel = StringType(required=True)
            address = StringType(required=True)
            internal_id = StringType()

            class Options:
                roles = {"safe": whitelist("channel", "address")}

        class SmsNotif(Model):
            channel = StringType(required=True)
            phone = StringType(required=True)
            carrier_code = StringType()

            class Options:
                roles = {"safe": whitelist("channel", "phone")}

        def route(field, data):
            return EmailNotif if data.get("channel") == "email" else SmsNotif

        class Alert(Model):
            label = StringType(required=True)
            notif = PolyModelType([EmailNotif, SmsNotif], claim_function=route)

            class Options:
                roles = {"safe": whitelist("label", "notif")}

        alert = Alert(
            {
                "label": "Urgent",
                "notif": {"channel": "email", "address": "a@b.com", "internal_id": "x"},
            }
        )
        alert.validate()
        assert isinstance(alert.notif, EmailNotif)

        safe = alert.to_primitive(role="safe")
        assert safe["label"] == "Urgent"
        assert "internal_id" not in safe["notif"]
        assert safe["notif"]["address"] == "a@b.com"


class TestInheritanceOptionsAndValidatorMerge:
    """Tests that Options and validators compose correctly through inheritance."""

    def test_child_merges_parent_roles_and_adds_own_validators(self):
        """Child inherits parent roles, can add new roles, and validators accumulate."""
        from schematics.models import Model
        from schematics.types import StringType, IntType
        from schematics.transforms import whitelist, blacklist
        from schematics.exceptions import DataError, ValidationError

        class Base(Model):
            name = StringType(required=True)
            internal = StringType()

            class Options:
                roles = {"public": whitelist("name")}

        class Mid(Base):
            score = IntType(required=True)

            class Options:
                roles = {"admin": blacklist("internal")}

            def validate_score(self, data, value):
                if value is not None and value < 0:
                    raise ValidationError("Score must be non-negative")

        class Leaf(Mid):
            rank = StringType(choices=["A", "B", "C"], required=True)

        leaf = Leaf({"name": "Alice", "score": 10, "rank": "A", "internal": "x"})
        leaf.validate()

        public = leaf.to_primitive(role="public")
        assert "name" in public
        assert "score" not in public
        assert "rank" not in public

        admin = leaf.to_primitive(role="admin")
        assert "name" in admin
        assert "score" in admin
        assert "internal" not in admin

        with pytest.raises(DataError):
            Leaf({"name": "Bob", "score": -1, "rank": "A"}).validate()

        with pytest.raises(DataError):
            Leaf({"name": "Bob", "score": 5, "rank": "X"}).validate()


class TestConstructionCoercionErrors:
    """Tests that coercion errors during construction raise DataError."""

    def test_multiple_coercion_errors_at_construction(self):
        """Multiple invalid fields during construction produce aggregated DataError."""
        from schematics.models import Model
        from schematics.types import IntType, FloatType, DateTimeType
        from schematics.exceptions import DataError

        class Metrics(Model):
            count = IntType(required=True)
            ratio = FloatType(required=True)
            timestamp = DateTimeType(required=True)

        with pytest.raises(DataError) as exc_info:
            Metrics({"count": "not_int", "ratio": "not_float", "timestamp": "not_date"})
        errs = exc_info.value.errors
        assert "count" in errs
        assert "ratio" in errs or "timestamp" in errs


class TestListOfModelsWithValidationErrors:
    """Tests error propagation through ListType(ModelType(...))."""

    def test_list_of_models_propagates_nested_errors(self):
        """Validation errors in items of ListType(ModelType) are reported per-index."""
        from schematics.models import Model
        from schematics.types import (
            StringType,
            IntType,
            ModelType,
            ListType,
            EmailType,
        )
        from schematics.transforms import whitelist
        from schematics.exceptions import DataError

        class Contact(Model):
            name = StringType(required=True, min_length=2)
            email = EmailType(required=True)
            priority = IntType(min_value=1, max_value=5)

            class Options:
                roles = {"brief": whitelist("name")}

        class Team(Model):
            title = StringType(required=True)
            members = ListType(ModelType(Contact), min_size=1, required=True)

            class Options:
                roles = {"brief": whitelist("title", "members")}

        team = Team(
            {
                "title": "Engineering",
                "members": [
                    {"name": "Alice", "email": "alice@co.com", "priority": 1},
                    {"name": "Bob", "email": "bob@co.com", "priority": 3},
                ],
            }
        )
        team.validate()

        brief = team.to_primitive(role="brief")
        assert len(brief["members"]) == 2
        assert "email" not in brief["members"][0]
        assert brief["members"][0]["name"] == "Alice"

        bad_team = Team(
            {
                "title": "Broken",
                "members": [
                    {"email": "a@b.com"},
                    {"name": "X", "email": "invalid", "priority": 10},
                ],
            }
        )
        with pytest.raises(DataError) as exc_info:
            bad_team.validate()
        assert "members" in exc_info.value.errors


class TestImportDataPreservesUnchangedFields:
    """Tests that import_data only affects specified fields."""

    def test_import_data_with_serialized_names_and_validation(self):
        """import_data uses deserialize_from, preserves other fields, and re-validates."""
        from schematics.models import Model
        from schematics.types import StringType, IntType
        from schematics.exceptions import DataError, ValidationError

        class Config(Model):
            app_name = StringType(
                required=True,
                deserialize_from=["app_name", "appName"],
            )
            version = IntType(min_value=1, required=True)
            env = StringType(default="prod")

            def validate_version(self, data, value):
                if value is not None and value > 100:
                    raise ValidationError("Version too high")

        c = Config({"appName": "myapp", "version": 1})
        c.validate()
        assert c.app_name == "myapp"
        assert c.env == "prod"

        c.import_data({"version": 2})
        c.validate()
        assert c.app_name == "myapp"
        assert c.version == 2
        assert c.env == "prod"

        c.import_data({"version": 200})
        with pytest.raises(DataError):
            c.validate()


class TestUnsetFieldReturnsNone:
    """Tests that unset non-required fields return None (not raise)."""

    def test_unset_optional_field_is_none_after_init(self):
        """With init=True (default), an unset optional field returns None."""
        from schematics.models import Model
        from schematics.types import StringType, IntType
        from schematics.exceptions import UndefinedValueError

        class Sparse(Model):
            name = StringType(required=True)
            bio = StringType()
            count = IntType()

        s = Sparse({"name": "Alice"})
        assert s.name == "Alice"
        assert s.bio is None
        assert s.count is None

        s2 = Sparse({"name": "Bob"}, init=False)
        assert s2.name == "Bob"
        with pytest.raises(UndefinedValueError):
            _ = s2.bio


# ============================================================================
# 34. Scope expansion — round 1
# ============================================================================


class TestWholelistRole:
    """Tests the wholelist role factory."""

    def test_wholelist_includes_all_fields(self):
        """wholelist() never excludes any field — explicit allow-all."""
        from schematics.models import Model
        from schematics.types import StringType, IntType
        from schematics.transforms import wholelist, whitelist

        class Secret(Model):
            name = StringType()
            password = StringType()
            score = IntType()

            class Options:
                roles = {
                    "all": wholelist(),
                    "limited": whitelist("name"),
                }

        s = Secret({"name": "Alice", "password": "s3cret", "score": 10})
        s.validate()

        full = s.to_primitive(role="all")
        assert full == {"name": "Alice", "password": "s3cret", "score": 10}

        limited = s.to_primitive(role="limited")
        assert limited == {"name": "Alice"}


class TestRoleSetOperations:
    """Tests role arithmetic: adding and subtracting field sets."""

    def test_role_add_and_subtract(self):
        """whitelist + fields expands it; whitelist - fields narrows it."""
        from schematics.models import Model
        from schematics.types import StringType, IntType
        from schematics.transforms import whitelist

        base_role = whitelist("name", "email")
        expanded = base_role + whitelist("age")
        narrowed = base_role - whitelist("email")

        class User(Model):
            name = StringType()
            email = StringType()
            age = IntType()

            class Options:
                roles = {
                    "expanded": expanded,
                    "narrowed": narrowed,
                }

        u = User({"name": "Alice", "email": "a@b.com", "age": 30})
        u.validate()

        exp = u.to_primitive(role="expanded")
        assert "name" in exp and "email" in exp and "age" in exp

        nar = u.to_primitive(role="narrowed")
        assert nar == {"name": "Alice"}


class TestModelAtoms:
    """Tests Model.atoms() iteration."""

    def test_atoms_yields_name_type_value(self):
        """atoms() yields (field_name, field_type, value) for each field."""
        from schematics.models import Model
        from schematics.types import StringType, IntType

        class Record(Model):
            name = StringType(required=True)
            count = IntType()

        r = Record({"name": "test", "count": 5})
        r.validate()

        atom_list = list(r.atoms())
        names = [a[0] for a in atom_list]
        assert "name" in names
        assert "count" in names

        for field_name, field_type, value in atom_list:
            if field_name == "name":
                assert isinstance(field_type, StringType)
                assert value == "test"
            elif field_name == "count":
                assert isinstance(field_type, IntType)
                assert value == 5


class TestDataErrorStringAndEquality:
    """Tests DataError's string representation and equality."""

    def test_data_error_str_is_json_and_supports_equality(self):
        """str(DataError) is JSON; two DataErrors with same errors are equal."""
        import json
        from schematics.exceptions import DataError

        e1 = DataError({"field": ["error message"]})
        e2 = DataError({"field": ["error message"]})
        e3 = DataError({"other": ["different"]})

        s = str(e1)
        parsed = json.loads(s)
        assert "field" in parsed

        assert e1 == e2
        assert e1 != e3


class TestUnionTypeErrorHandling:
    """Tests UnionType when no type matches the input."""

    def test_union_type_rejects_when_no_type_matches(self):
        """UnionType raises when value doesn't match any specified type."""
        from schematics.models import Model
        from schematics.types import UnionType, IntType, BooleanType
        from schematics.exceptions import DataError

        class Strict(Model):
            value = UnionType(types=(IntType, BooleanType), required=True)

        Strict({"value": 42}).validate()
        Strict({"value": True}).validate()

        with pytest.raises((DataError, Exception)):
            Strict({"value": {"nested": "dict"}}).validate()


class TestDateTimeDropTzinfo:
    """Tests DateTimeType with drop_tzinfo=True."""

    def test_drop_tzinfo_strips_timezone(self):
        """DateTimeType(drop_tzinfo=True) removes timezone info from parsed values."""
        from schematics.models import Model
        from schematics.types import DateTimeType

        class Event(Model):
            ts = DateTimeType(drop_tzinfo=True, required=True)

        e = Event({"ts": "2024-06-15T10:30:00+05:00"})
        e.validate()
        assert e.ts.tzinfo is None
        # drop_tzinfo strips the offset without converting to UTC (convert_tz defaults to False),
        # so the parsed local time is preserved exactly.
        assert e.ts.hour == 10 and e.ts.minute == 30

        e2 = Event({"ts": "2024-06-15T10:30:00Z"})
        e2.validate()
        assert e2.ts.tzinfo is None


# ============================================================================
# 35. Scope expansion — round 2 (compound.py gaps)
# ============================================================================


class TestListTypeCoercion:
    """Tests ListType accepting non-list iterables."""

    def test_list_type_accepts_tuple_input(self):
        """ListType coerces tuples (and other sequences) into lists."""
        from schematics.models import Model
        from schematics.types import IntType, ListType
        from schematics.exceptions import DataError

        class Data(Model):
            values = ListType(IntType, required=True)

        d = Data({"values": (1, 2, 3)})
        d.validate()
        prim = d.to_primitive()
        assert prim["values"] == [1, 2, 3]

        with pytest.raises((DataError, Exception)):
            Data({"values": "not-a-sequence"}).validate()


class TestCompoundTypeItemErrors:
    """Tests per-item error collection in ListType and DictType."""

    def test_list_and_dict_collect_per_item_errors(self):
        """Invalid items in ListType/DictType produce errors keyed by index/key."""
        from schematics.models import Model
        from schematics.types import IntType, ListType, DictType
        from schematics.exceptions import DataError

        class Batch(Model):
            nums = ListType(IntType, required=True)
            lookup = DictType(IntType, required=True)

        with pytest.raises(DataError) as exc_info:
            Batch(
                {
                    "nums": [1, "bad", 3, "worse"],
                    "lookup": {"a": 1, "b": "bad"},
                }
            ).validate()
        errors = exc_info.value.errors
        # Both compound fields aggregate their per-item failures: ListType keys errors by item
        # index, DictType by item key (CompoundError flattens each field's nested error dict).
        assert "nums" in errors and "lookup" in errors
        assert 1 in errors["nums"] and 3 in errors["nums"]
        assert "b" in errors["lookup"]


class TestCompoundExportLevelsAndRoles:
    """Tests export level and role filtering within List/DictType(ModelType)."""

    def test_list_and_dict_of_models_respect_inner_export_levels_and_roles(self):
        """Export levels filter list items; roles filter dict values."""
        from schematics.models import Model
        from schematics.types import StringType, ModelType, ListType, DictType
        from schematics.transforms import whitelist
        from schematics.common import NOT_NONE

        class Entry(Model):
            label = StringType(required=True)
            note = StringType(export_level=NOT_NONE)

        class Container(Model):
            entries = ListType(ModelType(Entry), required=True)

        c = Container({"entries": [{"label": "A", "note": "has note"}, {"label": "B"}]})
        c.validate()
        prim = c.to_primitive()
        assert prim["entries"][0].get("note") == "has note"
        assert "note" not in prim["entries"][1]

        class Setting(Model):
            value = StringType(required=True)
            internal = StringType()

            class Options:
                roles = {"api": whitelist("value")}

        class Config(Model):
            settings = DictType(ModelType(Setting), required=True)

            class Options:
                roles = {"api": whitelist("settings")}

        cfg = Config(
            {
                "settings": {
                    "timeout": {"value": "30", "internal": "x"},
                    "retries": {"value": "3", "internal": "y"},
                }
            }
        )
        cfg.validate()
        api = cfg.to_primitive(role="api")
        assert api["settings"]["timeout"] == {"value": "30"}
        assert "internal" not in api["settings"]["retries"]


class TestPolyModelWithClaimPolymorphic:
    """Tests PolyModelType auto-dispatch via _claim_polymorphic class method."""

    def test_poly_model_auto_dispatch_without_claim_function(self):
        """PolyModelType resolves model via _claim_polymorphic when no claim_function given."""
        from schematics.models import Model
        from schematics.types import StringType, IntType, PolyModelType

        class Circle(Model):
            shape = StringType(required=True)
            radius = IntType(required=True)

            @classmethod
            def _claim_polymorphic(cls, data):
                return data.get("shape") == "circle"

        class Square(Model):
            shape = StringType(required=True)
            side = IntType(required=True)

            @classmethod
            def _claim_polymorphic(cls, data):
                return data.get("shape") == "square"

        class Drawing(Model):
            element = PolyModelType([Circle, Square])

        d1 = Drawing({"element": {"shape": "circle", "radius": 5}})
        d1.validate()
        assert isinstance(d1.element, Circle)
        assert d1.element.radius == 5

        d2 = Drawing({"element": {"shape": "square", "side": 10}})
        d2.validate()
        assert isinstance(d2.element, Square)
        assert d2.element.side == 10
