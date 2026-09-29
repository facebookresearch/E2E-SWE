# Schematics — Data Structure Validation Library

Implement `schematics`, a Python library for defining data structures with typed fields, validation, and serialization. Models are declared using a Django-like pattern: subclass `Model`, declare fields as class attributes using type classes, then validate and serialize instances.

## Dependencies

- The environment is **offline** — there is no network access. All dependencies are **already
  installed**; do not install anything (no `pip install`, no `apt-get`).
- The project is installed for you by a `setup.sh` that runs offline (it performs an editable
  install of your implementation). You do not need to write or modify it.
- `schematics` itself has **no external runtime dependencies** — the core library, all field types,
  roles, validation, serialization, and the contrib/extensions modules are implemented using only
  the Python standard library. The one exception is `ObjectIdType` (see §8), which uses the `bson`
  module (already available in the environment).

---

## 1. Model

`Model` is the base class for all data models. Models are declared by subclassing `Model` and defining fields as class attributes.

```python
from schematics.models import Model
from schematics.types import StringType, IntType

class User(Model):
    name = StringType(required=True)
    age = IntType()
```

### Creating instances

`Model(raw_data=None, ...)` — Creates an instance, converting raw data into typed values. Raises `DataError` if any field value cannot be coerced to the declared type. When more than one field fails to coerce during construction, the raised `DataError.errors` aggregates **all** of the failing top-level fields (each keyed by its field name) — construction does not stop at the first failing field, mirroring how `validate()` reports every field's error. Supports options: `init` (apply defaults/init values), `strict` (reject unknown keys), `validate` (if `True`, calls `validate()` during construction — raises `DataError` on invalid data), `partial` (skip required checks). With `init=True` (the default), unset optional fields return `None`. Setting `init=False` skips default application — unset fields raise `UndefinedValueError`.

### Field access

Fields are accessed as attributes (`user.name`) or via dict-like syntax (`user["name"]`). Setting and deleting work the same way. Deleting a field leaves it undefined regardless of the `init` setting used at construction. Accessing an undefined field raises `UndefinedValueError`. Accessing a nonexistent field via `[]` raises `UnknownFieldError`. Setting/deleting a nonexistent field via `[]` also raises `UnknownFieldError`.

### Core methods

- `validate(partial=False, convert=True)` — Validates the model state. Raises `DataError` on validation errors. `partial=True` skips required-field checks. A field mutated after a successful `validate()` is re-validated on the next `validate()` call (a subsequently invalid value raises `DataError`).
- `to_primitive(role=None)` — Serializes to a dict of primitive types (strings, ints, etc.). `role` selects a named export role for field filtering.
- `to_native(role=None)` — Serializes to a dict of native Python types (e.g., datetime objects stay as datetime).
- `import_data(raw_data, recursive=False, **kwargs)` — Imports new data into an existing instance (like a PATCH update). `recursive=True` merges nested model data. Returns self.

### Iteration and equality

Models support `__iter__` (yields field names), `keys()` → list, `items()` → list of (name, value) tuples, `values()` → list, `__contains__` (`"name" in model`), `__len__`, `__delitem__` (`del model["field"]`). `atoms()` yields `(field_name, field_type_instance, value)` tuples. Two models of the same type with the same field values are equal. `repr(model)` includes the class name.

### Model Options

An inner `Options` class configures model behavior:

```python
class MyModel(Model):
    class Options:
        roles = {"public": whitelist("name"), "safe": blacklist("password")}
        serialize_when_none = False  # exclude None-valued fields from output
```

---

## 2. Field Types

All types inherit from `BaseType`. Common constructor parameters: `required`, `default` (may be a callable — invoked per-instance), `validators` (list of callables), `serialized_name`, `deserialize_from` (list of alternate input names), `export_level`, `choices` (list of valid values — rejects anything not in the list), `serialize_when_none` (per-field control: `True` always includes, `False` excludes when None), `metadata` (dict for custom metadata).

### Basic types
- `StringType` — coerces to str. Supports `min_length`, `max_length`, `regex` (pattern string; validated via `re.match`).
- `IntType` — coerces to int. Supports `min_value`, `max_value`.
- `FloatType` — coerces to float.
- `BooleanType` — coerces to bool. Accepts `True`/`False`, strings `"True"`/`"true"`/`"1"` (→ True), `"False"`/`"false"`/`"0"` (→ False), and ints `0`/`1`.
- `DecimalType` — coerces to `decimal.Decimal`. `to_primitive` returns string representation.
- `UUIDType` — coerces to `uuid.UUID`. `to_primitive` returns string.
- `DateType` — coerces from ISO 8601 string (`YYYY-MM-DD`) to `datetime.date`. Supports `formats` param (list of `strptime` format strings for custom parsing). When `formats` is provided it **replaces** the default ISO 8601 parser — only the listed formats are accepted, so an otherwise-valid ISO string not matching any listed format raises a coercion error. `to_primitive` returns `YYYY-MM-DD` string.
- `DateTimeType` — coerces from ISO 8601 string to `datetime.datetime`. Supports timezone designators (`Z`, `+HH:MM`). Accepts Unix timestamps as numeric input (converted to UTC datetime). Like `DateType`, a `formats` param (list of `strptime` format strings) **replaces** the built-in ISO/timestamp parser when supplied. Options: `convert_tz=True` normalizes to UTC, `drop_tzinfo=True` removes timezone info. `to_primitive` returns ISO 8601 string.
- `UTCDateTimeType` — variant of `DateTimeType` that normalizes to UTC and drops `tzinfo`. Export format ends with `"Z"`. Default: `tzd='utc'`, `convert_tz=True`, `drop_tzinfo=True`.
- `TimestampType` — variant of `DateTimeType` that exports as Unix timestamp float. Default: `tzd='require'`, `convert_tz=True`.
- `TimedeltaType` — coerces numeric input to `datetime.timedelta`. Constructor takes `precision` parameter (`"seconds"`, `"minutes"`, `"hours"`, `"days"`, `"weeks"`, `"milliseconds"`, `"microseconds"`). `to_primitive` returns integer in the specified precision unit.
- `GeoPointType` — validates a `[latitude, longitude]` pair. Accepts list, tuple, or dict. Validates range: latitude -90..90, longitude -180..180.
- `MD5Type` — validates 32-character hexadecimal strings.
- `SHA1Type` — validates 40-character hexadecimal strings.
- `URLType` — validates URL format (http/https schemes).
- `EmailType` — validates email address format.
- `MultilingualStringType` — stores localized strings as `{"locale": "value"}` dict. Constructor takes `default_locale`. `to_primitive` returns the string for `default_locale` (or the context locale if set).

### Compound types
- `ListType(field_type, min_size=None, max_size=None)` — List of typed items. `field_type` accepts either a type class (`ListType(StringType)`) or a type instance (`ListType(StringType())`). Input can be a list or tuple (coerced to list).
- `DictType(field_type, coerce_key=None)` — Dict with typed values. `field_type` accepts either a type class or a type instance.
- `ModelType(model_class)` — Nested model. Input can be a dict or model instance.
- `PolyModelType(model_specs, claim_function=None)` — Polymorphic model field. If `claim_function` is provided, `claim_function(field, data)` returns the model class to use. Otherwise, each model in `model_specs` can define a `@classmethod _claim_polymorphic(cls, data)` that returns `True` if the model matches the data.
- `UnionType(types)` — Accepts values matching any of the specified type classes (pass type classes, not instances). Tries each type's conversion in order.

### Network types (`schematics.types.net`)
- `IPv4Type` — validates IPv4 address strings.
- `MACAddressType` — validates MAC address strings. `to_primitive` normalizes to colon-separated format (`AA:BB:CC:DD:EE:FF`).

### Serializable (computed) fields (`schematics.types.serializable`)
- `serializable` — decorator for computed read-only fields. The decorated method's return value appears in serialized output. Can specify a custom type: `@serializable(StringType())`.

---

## 3. Roles — Field Filtering

Roles control which fields appear in serialized output. The role factories `wholelist`, `whitelist`, and `blacklist` are importable from `schematics.transforms`.

- `wholelist(*field_names)` — Include all fields (explicit allow-all). Equivalent to an empty blacklist but more explicit.
- `whitelist(*field_names)` — Only include listed fields.
- `blacklist(*field_names)` — Exclude listed fields. Empty blacklist includes everything.

Roles support set arithmetic: `whitelist("a", "b") + whitelist("c")` expands the set; `whitelist("a", "b") - whitelist("b")` narrows it.

Define in `Options.roles`. Applied recursively to nested models. Using an undefined role raises `ValueError`.

---

## 4. Validation

`model.validate()` validates all fields. Raises `DataError` with `errors` dict on failure.

- **Field validators**: `validators=[func]` on type constructors. Function receives value, raises `ValidationError`.
- **Model validators**: `validate_<field_name>(self, data, value)` methods raise `ValidationError`.
- **Strict mode**: `strict=True` on Model constructor rejects unknown input keys (keys that are not a declared field, nor any field's `serialized_name` / `deserialize_from` alias). Rejection raises `DataError` whose `errors` dict contains an entry for **each** offending unknown key, keyed by that key's own name (not under a generic catch-all key) — e.g. constructing with a stray `"rogue"` key yields `errors` containing a `"rogue"` entry.
- **Partial validation**: `partial=True` skips required-field checks.

---

## 5. Exceptions

- `DataError` — Has `errors` dict mapping field names to error details. For a nested-model field, the value is a sub-dict keyed by the inner field names. For a compound field with invalid items, the value is itself a dict aggregating the per-item failures, directly accessible on `errors[<field>]`: a `ListType` field keys it by the failing item's **index**, and a `DictType` field keys it by the failing item's **key** (so `index in errors[<field>]` / `key in errors[<field>]` works). A compound field collects **all** of its failing items — it does not stop at the first. `to_primitive()` returns a JSON-serializable representation. `str(DataError)` returns JSON. Two `DataError` instances with the same `errors` are equal.
- `ConversionError`, `ValidationError` — Field-level errors.
- `UndefinedValueError`, `UnknownFieldError` — Access errors.
- `BaseError` — Base class with `errors` property.

---

## 6. Export Levels and Serialized Names

Export level constants control field visibility in serialized output. They are importable from `schematics.common`:

- `ALL` — Always export, even if value is None or Undefined.
- `DEFAULT` — Export if value is set (includes None).
- `NOT_NONE` — Export only if value is not None.
- `NONEMPTY` — Export only if value is non-empty (for compound types: non-empty list/dict).
- `DROP` — Never export.

Set per-field via `export_level` parameter or per-model via `serialize_when_none` in Options. Per-field `serialize_when_none=True` maps to `DEFAULT`; `serialize_when_none=False` maps to `NONEMPTY`.

`serialized_name` remaps output keys. `deserialize_from` accepts alternate input names.

---

## 7. Model Inheritance

Subclasses inherit fields, roles, and validators from parents. Fields can be overridden. Multiple inheritance levels work correctly.

---

## 8. Contrib Modules

### EnumType (`schematics.contrib.enum_type`)
`EnumType(enum_class, use_values=False)` — Field type for Python `enum.Enum`. Converts between enum members, names (strings), and optionally values. `to_native` accepts enum member, name string, or (if `use_values=True`) value. `to_primitive` returns the name (or value if `use_values=True`).

### ObjectIdType (`schematics.contrib.mongo`)
`ObjectIdType()` — Field type for BSON ObjectId (requires `pymongo`/`bson`). Converts strings to `bson.objectid.ObjectId`. `to_primitive` returns string representation.

### ModelHelpTextMixin (`schematics.extensions.model_help_text_mixin`)
A mixin class for Model that provides `get_helptext()` class method, which returns a formatted **string** containing each field's label and description. Fields use `metadata=help_text_metadata(label, description, example)` to attach help text. `help_text_metadata(**kwargs)` returns a dict of the given keyword arguments.

## setup.sh

The project is installed offline via an editable install (the build backend is pre-installed and
the package index is disabled):

```bash
pip install -e . --no-build-isolation
```
