# protobuf-to-pydantic

Build `protobuf_to_pydantic`, a Python library that turns Protobuf (proto3) messages into
`pydantic` v2 `BaseModel` classes whose fields carry validation rules transcribed from Protobuf field
options. The library supports three generation flows and two rule dialects (described below). Target
**pydantic v2** only.

The validation rules live in Protobuf *field options* defined by two extension proto files that are
given to you verbatim at the end of this document (`protos/validate.proto` and
`protos/p2p_validate.proto`). You must reproduce both files exactly and compile them (see *Build*).

## Dependencies

The environment is **offline** and every dependency is **already installed** — do not install
anything (there is no network). The pre-installed runtime dependencies are: `pydantic>=2` (a 2.x that
is not 2.5.0 or 2.9.0), `protobuf>=5`, `grpcio-tools`, `mypy-protobuf`, and `email-validator` (needed
for the string `email` rule). `toml` and `lark` are **not** installed and are **not** required by the
behaviour specified here. The build backend (`poetry-core` + `poetry-dynamic-versioning`) and the test
harness are also pre-installed. Your project is installed by a `setup.sh` that runs offline (see
*Build*).

## Build (`setup.sh`)

Your `setup.sh` must compile the two rule protos into the package and install the package. It runs
**offline** against the pre-installed dependencies, so it must not install anything. Specifically it
must produce importable modules `protobuf_to_pydantic.protos.p2p_validate_pb2` and
`protobuf_to_pydantic.protos.validate_pb2` (the protoc plugin imports them). For example:

```bash
python -m grpc_tools.protoc -I. --python_out=. protos/p2p_validate.proto protos/validate.proto
# arrange the generated modules so that `from protobuf_to_pydantic.protos import p2p_validate_pb2, validate_pb2` works
pip install -e . --no-build-isolation
```

(`--no-build-isolation` is required: the build backend is pre-installed and the environment has no
network, so pip must not try to fetch an isolated build environment.)

`pyproject.toml` must declare a console-script entry point named `protoc-gen-protobuf-to-pydantic`
pointing at the plugin's `main` (see *Flow 3*), so that `protoc`/`grpc_tools.protoc` can invoke the
plugin via `--protobuf-to-pydantic_out`.

## Public API

`protobuf_to_pydantic/__init__.py` must export exactly:

```python
from .gen_code import pydantic_model_to_py_code, pydantic_model_to_py_file
from .gen_model import msg_to_pydantic_model
```

Tests import `msg_to_pydantic_model`, `pydantic_model_to_py_code`, `pydantic_model_to_py_file` from the
top-level package, and import `clear_create_model_cache` from `protobuf_to_pydantic.gen_model` (see
*Model cache*).

## The three generation flows

### Flow 1 — runtime conversion: `msg_to_pydantic_model`

```python
def msg_to_pydantic_model(
    msg,                                   # a protobuf Message subclass (or Descriptor)
    default_field=FieldInfo,               # FieldInfo subclass for the top-level model's fields
    comment_prefix="p2p",
    parse_msg_desc_method=None,            # rule source selector, see below
    local_dict=None,                       # variables for `p2p@local|...` template references
    pydantic_base=None,                    # base class the generated model should inherit
    pydantic_module=None,
    template=None,                         # a Template subclass (see Templates)
    message_type_dict_by_type_name=None,
    message_default_factory_dict_by_type_name=None,
    all_field_set_optional=False,
    create_model_cache=None,
    enable_enum_name_value_desc=False,
) -> Type[BaseModel]
```

It dynamically creates and returns a pydantic model class whose fields mirror the message fields, with a
`FieldInfo` (or subclass) per field carrying the validation rules read from that field's options.

`parse_msg_desc_method` selects which rule dialect to read from the message's field options:
- `None` (default) → read **P2P** rules (the `p2p_validate` extension; see *Rule dialects*).
- `"PGV"` → read **PGV** rules (the `validate` extension).
- `"ignore"` → ignore all rules.

(Other values selecting comment/`.pyi` rule sources are out of scope.)

`pydantic_base`: the generated model must be a subclass of this class (so user-defined methods/config are
inherited). `all_field_set_optional=True`: independently of base optionality (see *Field optionality and
defaults* below), additionally make the type of every field `Optional[...]` with default `None`, except
fields carrying an explicit `required`/`miss_default` rule, which stay non-`None`.
`enable_enum_name_value_desc=True`: the docstring of each generated `IntEnum` lists its members as
`- <name> = <number>` lines.

### Flow 2 — code generation: `pydantic_model_to_py_code` / `pydantic_model_to_py_file`

```python
def pydantic_model_to_py_code(*model, ...) -> str       # returns Python source text
def pydantic_model_to_py_file(filename, *model, ...) -> None   # writes that source to a file
```

Given one or more models produced by Flow 1, serialise them back into runnable Python source that, when
executed, defines equivalent pydantic models (same class names, same fields, same validation behaviour).
The emitted source must be self-contained: it imports everything it references (pydantic, typing,
datetime, custom `FieldInfo` subclasses from their defining module, etc.) and inlines nested
message/enum definitions. Constrained types must be emitted as `Annotated[...]` types (use
`Annotated[tuple(parts)]` rather than `Annotated.__class_getitem__(...)` so it works on Python 3.13).

### Flow 3 — protoc plugin

A `protoc` plugin (console script `protoc-gen-protobuf-to-pydantic`, whose entry point is the plugin's
`main`) that reads a `CodeGeneratorRequest` from stdin and writes generated pydantic-model source files.
Invoked as:

```bash
python -m grpc_tools.protoc -I<dir> --python_out=<out> \
    --protobuf-to-pydantic_out=config_path=<config.py>:<out> demo.proto
```

For an input `demo.proto` it writes `demo_p2p.py` (suffix `_p2p` by default) into `<out>`, containing one
pydantic model class per message (named after the message) plus inlined enums, with the same validation
behaviour as Flow 1. It must declare support for proto3 optional fields. Packages listed in the config's
`ignore_pkg_list` (e.g. `validate`, `p2p_validate`) are not emitted. The plugin reads field options using
the compiled `protobuf_to_pydantic.protos.{p2p_validate_pb2,validate_pb2}` modules.

The config module referenced by `config_path=<config.py>` may define: `local_dict` (dict of `p2p@local`
variables), `template` (a `Template` subclass), `comment_prefix` (str), `ignore_pkg_list` (list of str),
`file_name_suffix` (str, default `"_p2p"`). The config-loader must accept a Python module exposing those
names (`local_dict`, `template`, `comment_prefix`, `ignore_pkg_list`, `file_name_suffix`) and apply them
when generating the model source.

## Rule dialects

Two Protobuf extensions define the rules (full definitions provided at the end of this document):

- **PGV** — `protos/validate.proto`, package `validate`, field-option extension `validate.rules`. This is
  the well-known protoc-gen-validate rule set.
- **P2P** — `protos/p2p_validate.proto`, package `p2p_validate`, field-option extension
  `p2p_validate.rules`. A superset of PGV adding pydantic-specific knobs (`enable`, `default`,
  `default_factory`, `default_template`, `required`, `miss_default`, `alias`, `title`, `description`,
  `example`, `example_factory`, `field`, `type`, `extra`, `pydantic_type`), plus the message-level
  `p2p_validate.ignored` option and the oneof-level `p2p_validate.required` /
  `p2p_validate.oneof_extend` options.

Rules are read from a field's options. A rule group is named after the field's protobuf type, e.g.
`(p2p_validate.rules).string.<rule>`, `(p2p_validate.rules).int32.<rule>`,
`(p2p_validate.rules).repeated.<rule>`, etc. The PGV dialect uses `(validate.rules)` with the
protoc-gen-validate names (`gte`/`lte`/`gt`/`lt`, `min_len`/`max_len`, `pattern`, `unique`, etc.); map
those onto the same pydantic constraints as the P2P names.

### Rule semantics (apply to both dialects unless noted)

**Field optionality and defaults.** Following proto3 semantics, every scalar field is optional by default:
its generated pydantic field gets the proto3 zero value as its default (`0` / `0.0` for numbers, `""` for
strings, `b""` for bytes, `False` for bool, the `0` member for enums), so omitting the field from the
constructor is always valid. A proto3 `optional` (explicit-presence) scalar field additionally has its
type widened to `Optional[...]` so that an explicit `None` is accepted at construction (as well as being
omittable); a plain, non-`optional` scalar field is typed as the bare scalar and does **not** accept an
explicit `None`. Because pydantic v2 does not run validators on a field's default, a
constraint is enforced only on a value the caller actually supplies — a field is made *required* (no
default, so omission is rejected) only by an explicit `required` rule (PGV `miss_default`). In particular
a `const` (or any other) constraint does **not** by itself make a field required: a field with only a
`const` rule still defaults to the zero value and may be omitted. (`default` / `default_factory` /
`default_template` override the zero default with the configured value; `all_field_set_optional` is a
separate knob that only widens the field *type* to `Optional[...]` — see Flow 1.)

Numeric types (`float`, `double`, `int32/64`, `uint32/64`, `sint32/64`, `fixed32/64`, `sfixed32/64`):
- `const` → only that exact value is accepted.
- `lt` / `le` / `gt` / `ge` (PGV: `lt`/`lte`/`gt`/`gte`) → strict/inclusive bounds.
- `in` / `not_in` → value must be / must not be in the given list.
- `multiple_of` → value must be an integer multiple.

`bool`: `const` → field is pinned to the given truth value.

`string`:
- `const`, `len` (exact length), `min_length`/`max_length` (PGV `min_len`/`max_len`), `pattern` (regex),
  `prefix`, `suffix`, `contains`, `not_contains`, `in`, `not_in`.
- Format flags producing the corresponding pydantic types: `email`, `hostname`, `ip`, `ipv4`, `ipv6`,
  `uri`, `uri_ref`, `address`, `uuid`. `pydantic_type` names a pydantic type to use directly (e.g.
  `"UUID1"`).

`bytes`: `const`, `len`, `min_length`/`max_length`, `prefix`, `suffix`, `contains`, `in`, `not_in`.

`enum`: the field becomes an `IntEnum`; `const`, `in`, `not_in` constrain its integer value.

`repeated`: `min_items`/`max_items` (PGV `min_items`/`max_items`) bound the item count; `unique` (no-op
under pydantic v2); `items.<type>.<rule>` applies the per-item rules of that element type to every item.

`map`: `min_pairs`/`max_pairs` bound the entry count; `keys.<type>.<rule>` and `values.<type>.<rule>`
constrain keys and values respectively.

`any` (`google.protobuf.Any`): `required`; `in`/`not_in` test the message's `type_url` against the given
list (entries may be a `type_url` string or a `p2p@import_instance|...` Any instance).

`duration` (`google.protobuf.Duration` → `datetime.timedelta`): `const`, `lt`/`le`/`gt`/`ge`,
`in`/`not_in` (durations are specified as `{seconds, nanos}` in the proto).

`timestamp` (`google.protobuf.Timestamp` → `datetime.datetime`): `const`, `lt`/`le`/`gt`/`ge`, `lt_now`,
`gt_now`, `within` (a duration window around now). Timestamps are `{seconds}` in the proto. A
`Timestamp` rule value converts to a timezone-naive `datetime`, and `lt_now`/`gt_now`/`within` compare
against a timezone-naive current time.

`message` (sub-message fields): `skip` → do not validate the sub-message's own rules; `required` → the
sub-message field must be explicitly **provided** (present in the init payload). For a proto3 `optional`
message field, an explicit `None` counts as provided and is therefore accepted; for a non-`optional`
message field, the value must be present and non-`None`. A required message field that is omitted entirely
is rejected.

### Common P2P field knobs

- `enable=false` → the field is dropped from the generated model entirely (it carries neither rules
  nor a field definition; supplying it as an extra key is simply ignored by the model).
- `default` → static default value (field becomes optional). `default_factory` → callable default (via a
  template reference, e.g. `p2p@import|uuid|uuid4`, `p2p@builtin|list`). `default_template` → a default
  produced by a template hook (e.g. `p2p@timestamp|10`).
- `miss_default=true` and `required=true` → the field is required (PGV `miss_default` maps to required).
- `alias` → pydantic field alias; `title` → FieldInfo title; `description` → FieldInfo description.
- `example`/`example_factory` → example metadata, recorded in the field's `json_schema_extra` (an
  example value may be any Python object, not only a JSON-serialisable one); `field` → a custom
  `FieldInfo` subclass to use (template ref, usually `p2p@local|...`); `type` → a custom type for the
  field (template ref; a reference that resolves to a constrained-type factory, i.e. a callable
  returning a type, must be called to obtain the field's type); `extra` → a JSON object merged into
  the field's extra/`json_schema_extra`.

### oneof

- A oneof with `option (p2p_validate.required) = true;` requires exactly one member to be set (zero or
  more-than-one is a validation error). "Set" means the member name is present in the init payload,
  regardless of its value — so naming a member counts even when its value is `None`.
- `option (p2p_validate.oneof_extend) = {optional: ["x","y"]};` marks the listed members as allowed to be
  explicitly `None`. For a required oneof, naming one such optional member (even with value `None`)
  satisfies the "exactly one member set" requirement, whereas passing a non-optional member as `None` is a
  validation error. Passing two or more members, or none, is still an error.
- proto3 `optional` fields are supported.

## Well-known types

Map `google.protobuf.Timestamp`→`datetime.datetime`, `google.protobuf.Duration`→`datetime.timedelta`,
`google.protobuf.Any`→the protobuf `Any` message, `google.protobuf.Empty`→`None`,
`google.protobuf.Struct`→`Dict[str, Any]`. Nested messages, maps-of-messages, self-references and
cross-message references must resolve recursively (use forward refs / `model_rebuild()` where needed).

## Templates

Rule values may be template strings of the form `p2p@<kind>|<args>`:
- `p2p@local|<name>` → look `<name>` up in `local_dict`.
- `p2p@builtin|<name>` → a Python builtin (e.g. `list`, `dict`, `float`, `int`, `bytes`).
- `p2p@import|<module>|<attr>` → import `<module>` and resolve `<attr>` against it. `<attr>` may be a
  dotted attribute path resolved left-to-right (each segment fetched from the previous object), so
  `p2p@import|uuid|uuid4` resolves the `uuid4` function, `p2p@import|datetime|datetime.now` resolves the
  `now` method of the `datetime` class in the `datetime` module, and `p2p@import|datetime|datetime`
  resolves the `datetime` class itself.
- `p2p@import_instance|<module>|<attr>|<json>` → resolve `<module>`/`<attr>` the same way (dotted `<attr>`
  supported), then call/instantiate it with the JSON kwargs.
- `p2p@<method>|<args>` → call `template_<method>` on the active `Template` subclass. The
  `protobuf_to_pydantic.template.Template` base class is extensible by subclassing and adding
  `template_<name>(self, *args)` methods; e.g. a `template_timestamp(self, length_str)` hook resolves
  `p2p@timestamp|10`.

## Model cache

`msg_to_pydantic_model` may memoise generated models. If you implement such a cache, expose
`clear_create_model_cache()` in `protobuf_to_pydantic.gen_model` to reset it (tests call it to ensure each
conversion honours its own options).

## pydantic v1/v2

Target pydantic v2. You may keep a thin pydantic v1/v2 adapter indirection internally, but only
v2 behaviour is exercised.

---

## Provided interface files

Reproduce the following two files **verbatim** as `protos/validate.proto` and `protos/p2p_validate.proto`,
and compile them as described in *Build*. They define the rule extensions and the exact field
names/numbers the rules are keyed by.

### `protos/validate.proto`

```protobuf
syntax = "proto2";
package validate;

option go_package = "github.com/envoyproxy/protoc-gen-validate/validate";
option java_package = "io.envoyproxy.pgv.validate";

import "google/protobuf/descriptor.proto";
import "google/protobuf/duration.proto";
import "google/protobuf/timestamp.proto";

// Validation rules applied at the message level
extend google.protobuf.MessageOptions {
    // Disabled nullifies any validation rules for this message, including any
    // message fields associated with it that do support validation.
    optional bool disabled = 1071;
    // Ignore skips generation of validation methods for this message.
    optional bool ignored = 1072;
}

// Validation rules applied at the oneof level
extend google.protobuf.OneofOptions {
    // Required ensures that exactly one the field options in a oneof is set;
    // validation fails if no fields in the oneof are set.
    optional bool required = 1071;
}

// Validation rules applied at the field level
extend google.protobuf.FieldOptions {
    // Rules specify the validations to be performed on this field. By default,
    // no validation is performed against a field.
    optional FieldRules rules = 1071;
}

// FieldRules encapsulates the rules for each type of field. Depending on the
// field, the correct set should be used to ensure proper validations.
message FieldRules {
    optional MessageRules message = 17;
    oneof type {
        // Scalar Field Types
        FloatRules    float    = 1;
        DoubleRules   double   = 2;
        Int32Rules    int32    = 3;
        Int64Rules    int64    = 4;
        UInt32Rules   uint32   = 5;
        UInt64Rules   uint64   = 6;
        SInt32Rules   sint32   = 7;
        SInt64Rules   sint64   = 8;
        Fixed32Rules  fixed32  = 9;
        Fixed64Rules  fixed64  = 10;
        SFixed32Rules sfixed32 = 11;
        SFixed64Rules sfixed64 = 12;
        BoolRules     bool     = 13;
        StringRules   string   = 14;
        BytesRules    bytes    = 15;

        // Complex Field Types
        EnumRules     enum     = 16;
        RepeatedRules repeated = 18;
        MapRules      map      = 19;

        // Well-Known Field Types
        AnyRules       any       = 20;
        DurationRules  duration  = 21;
        TimestampRules timestamp = 22;
    }
}

// FloatRules describes the constraints applied to `float` values
message FloatRules {
    // Const specifies that this field must be exactly the specified value
    optional float const = 1;

    // Lt specifies that this field must be less than the specified value,
    // exclusive
    optional float lt = 2;

    // Lte specifies that this field must be less than or equal to the
    // specified value, inclusive
    optional float lte = 3;

    // Gt specifies that this field must be greater than the specified value,
    // exclusive. If the value of Gt is larger than a specified Lt or Lte, the
    // range is reversed.
    optional float gt = 4;

    // Gte specifies that this field must be greater than or equal to the
    // specified value, inclusive. If the value of Gte is larger than a
    // specified Lt or Lte, the range is reversed.
    optional float gte = 5;

    // In specifies that this field must be equal to one of the specified
    // values
    repeated float in = 6;

    // NotIn specifies that this field cannot be equal to one of the specified
    // values
    repeated float not_in = 7;

    // IgnoreEmpty specifies that the validation rules of this field should be
    // evaluated only if the field is not empty
    optional bool ignore_empty = 8;
}

// DoubleRules describes the constraints applied to `double` values
message DoubleRules {
    // Const specifies that this field must be exactly the specified value
    optional double const = 1;

    // Lt specifies that this field must be less than the specified value,
    // exclusive
    optional double lt = 2;

    // Lte specifies that this field must be less than or equal to the
    // specified value, inclusive
    optional double lte = 3;

    // Gt specifies that this field must be greater than the specified value,
    // exclusive. If the value of Gt is larger than a specified Lt or Lte, the
    // range is reversed.
    optional double gt = 4;

    // Gte specifies that this field must be greater than or equal to the
    // specified value, inclusive. If the value of Gte is larger than a
    // specified Lt or Lte, the range is reversed.
    optional double gte = 5;

    // In specifies that this field must be equal to one of the specified
    // values
    repeated double in = 6;

    // NotIn specifies that this field cannot be equal to one of the specified
    // values
    repeated double not_in = 7;

    // IgnoreEmpty specifies that the validation rules of this field should be
    // evaluated only if the field is not empty
    optional bool ignore_empty = 8;
}

// Int32Rules describes the constraints applied to `int32` values
message Int32Rules {
    // Const specifies that this field must be exactly the specified value
    optional int32 const = 1;

    // Lt specifies that this field must be less than the specified value,
    // exclusive
    optional int32 lt = 2;

    // Lte specifies that this field must be less than or equal to the
    // specified value, inclusive
    optional int32 lte = 3;

    // Gt specifies that this field must be greater than the specified value,
    // exclusive. If the value of Gt is larger than a specified Lt or Lte, the
    // range is reversed.
    optional int32 gt = 4;

    // Gte specifies that this field must be greater than or equal to the
    // specified value, inclusive. If the value of Gte is larger than a
    // specified Lt or Lte, the range is reversed.
    optional int32 gte = 5;

    // In specifies that this field must be equal to one of the specified
    // values
    repeated int32 in = 6;

    // NotIn specifies that this field cannot be equal to one of the specified
    // values
    repeated int32 not_in = 7;

    // IgnoreEmpty specifies that the validation rules of this field should be
    // evaluated only if the field is not empty
    optional bool ignore_empty = 8;
}

// Int64Rules describes the constraints applied to `int64` values
message Int64Rules {
    // Const specifies that this field must be exactly the specified value
    optional int64 const = 1;

    // Lt specifies that this field must be less than the specified value,
    // exclusive
    optional int64 lt = 2;

    // Lte specifies that this field must be less than or equal to the
    // specified value, inclusive
    optional int64 lte = 3;

    // Gt specifies that this field must be greater than the specified value,
    // exclusive. If the value of Gt is larger than a specified Lt or Lte, the
    // range is reversed.
    optional int64 gt = 4;

    // Gte specifies that this field must be greater than or equal to the
    // specified value, inclusive. If the value of Gte is larger than a
    // specified Lt or Lte, the range is reversed.
    optional int64 gte = 5;

    // In specifies that this field must be equal to one of the specified
    // values
    repeated int64 in = 6;

    // NotIn specifies that this field cannot be equal to one of the specified
    // values
    repeated int64 not_in = 7;

    // IgnoreEmpty specifies that the validation rules of this field should be
    // evaluated only if the field is not empty
    optional bool ignore_empty = 8;
}

// UInt32Rules describes the constraints applied to `uint32` values
message UInt32Rules {
    // Const specifies that this field must be exactly the specified value
    optional uint32 const = 1;

    // Lt specifies that this field must be less than the specified value,
    // exclusive
    optional uint32 lt = 2;

    // Lte specifies that this field must be less than or equal to the
    // specified value, inclusive
    optional uint32 lte = 3;

    // Gt specifies that this field must be greater than the specified value,
    // exclusive. If the value of Gt is larger than a specified Lt or Lte, the
    // range is reversed.
    optional uint32 gt = 4;

    // Gte specifies that this field must be greater than or equal to the
    // specified value, inclusive. If the value of Gte is larger than a
    // specified Lt or Lte, the range is reversed.
    optional uint32 gte = 5;

    // In specifies that this field must be equal to one of the specified
    // values
    repeated uint32 in = 6;

    // NotIn specifies that this field cannot be equal to one of the specified
    // values
    repeated uint32 not_in = 7;

    // IgnoreEmpty specifies that the validation rules of this field should be
    // evaluated only if the field is not empty
    optional bool ignore_empty = 8;
}

// UInt64Rules describes the constraints applied to `uint64` values
message UInt64Rules {
    // Const specifies that this field must be exactly the specified value
    optional uint64 const = 1;

    // Lt specifies that this field must be less than the specified value,
    // exclusive
    optional uint64 lt = 2;

    // Lte specifies that this field must be less than or equal to the
    // specified value, inclusive
    optional uint64 lte = 3;

    // Gt specifies that this field must be greater than the specified value,
    // exclusive. If the value of Gt is larger than a specified Lt or Lte, the
    // range is reversed.
    optional uint64 gt = 4;

    // Gte specifies that this field must be greater than or equal to the
    // specified value, inclusive. If the value of Gte is larger than a
    // specified Lt or Lte, the range is reversed.
    optional uint64 gte = 5;

    // In specifies that this field must be equal to one of the specified
    // values
    repeated uint64 in = 6;

    // NotIn specifies that this field cannot be equal to one of the specified
    // values
    repeated uint64 not_in = 7;

    // IgnoreEmpty specifies that the validation rules of this field should be
    // evaluated only if the field is not empty
    optional bool ignore_empty = 8;
}

// SInt32Rules describes the constraints applied to `sint32` values
message SInt32Rules {
    // Const specifies that this field must be exactly the specified value
    optional sint32 const = 1;

    // Lt specifies that this field must be less than the specified value,
    // exclusive
    optional sint32 lt = 2;

    // Lte specifies that this field must be less than or equal to the
    // specified value, inclusive
    optional sint32 lte = 3;

    // Gt specifies that this field must be greater than the specified value,
    // exclusive. If the value of Gt is larger than a specified Lt or Lte, the
    // range is reversed.
    optional sint32 gt = 4;

    // Gte specifies that this field must be greater than or equal to the
    // specified value, inclusive. If the value of Gte is larger than a
    // specified Lt or Lte, the range is reversed.
    optional sint32 gte = 5;

    // In specifies that this field must be equal to one of the specified
    // values
    repeated sint32 in = 6;

    // NotIn specifies that this field cannot be equal to one of the specified
    // values
    repeated sint32 not_in = 7;

    // IgnoreEmpty specifies that the validation rules of this field should be
    // evaluated only if the field is not empty
    optional bool ignore_empty = 8;
}

// SInt64Rules describes the constraints applied to `sint64` values
message SInt64Rules {
    // Const specifies that this field must be exactly the specified value
    optional sint64 const = 1;

    // Lt specifies that this field must be less than the specified value,
    // exclusive
    optional sint64 lt = 2;

    // Lte specifies that this field must be less than or equal to the
    // specified value, inclusive
    optional sint64 lte = 3;

    // Gt specifies that this field must be greater than the specified value,
    // exclusive. If the value of Gt is larger than a specified Lt or Lte, the
    // range is reversed.
    optional sint64 gt = 4;

    // Gte specifies that this field must be greater than or equal to the
    // specified value, inclusive. If the value of Gte is larger than a
    // specified Lt or Lte, the range is reversed.
    optional sint64 gte = 5;

    // In specifies that this field must be equal to one of the specified
    // values
    repeated sint64 in = 6;

    // NotIn specifies that this field cannot be equal to one of the specified
    // values
    repeated sint64 not_in = 7;

    // IgnoreEmpty specifies that the validation rules of this field should be
    // evaluated only if the field is not empty
    optional bool ignore_empty = 8;
}

// Fixed32Rules describes the constraints applied to `fixed32` values
message Fixed32Rules {
    // Const specifies that this field must be exactly the specified value
    optional fixed32 const = 1;

    // Lt specifies that this field must be less than the specified value,
    // exclusive
    optional fixed32 lt = 2;

    // Lte specifies that this field must be less than or equal to the
    // specified value, inclusive
    optional fixed32 lte = 3;

    // Gt specifies that this field must be greater than the specified value,
    // exclusive. If the value of Gt is larger than a specified Lt or Lte, the
    // range is reversed.
    optional fixed32 gt = 4;

    // Gte specifies that this field must be greater than or equal to the
    // specified value, inclusive. If the value of Gte is larger than a
    // specified Lt or Lte, the range is reversed.
    optional fixed32 gte = 5;

    // In specifies that this field must be equal to one of the specified
    // values
    repeated fixed32 in = 6;

    // NotIn specifies that this field cannot be equal to one of the specified
    // values
    repeated fixed32 not_in = 7;

    // IgnoreEmpty specifies that the validation rules of this field should be
    // evaluated only if the field is not empty
    optional bool ignore_empty = 8;
}

// Fixed64Rules describes the constraints applied to `fixed64` values
message Fixed64Rules {
    // Const specifies that this field must be exactly the specified value
    optional fixed64 const = 1;

    // Lt specifies that this field must be less than the specified value,
    // exclusive
    optional fixed64 lt = 2;

    // Lte specifies that this field must be less than or equal to the
    // specified value, inclusive
    optional fixed64 lte = 3;

    // Gt specifies that this field must be greater than the specified value,
    // exclusive. If the value of Gt is larger than a specified Lt or Lte, the
    // range is reversed.
    optional fixed64 gt = 4;

    // Gte specifies that this field must be greater than or equal to the
    // specified value, inclusive. If the value of Gte is larger than a
    // specified Lt or Lte, the range is reversed.
    optional fixed64 gte = 5;

    // In specifies that this field must be equal to one of the specified
    // values
    repeated fixed64 in = 6;

    // NotIn specifies that this field cannot be equal to one of the specified
    // values
    repeated fixed64 not_in = 7;

    // IgnoreEmpty specifies that the validation rules of this field should be
    // evaluated only if the field is not empty
    optional bool ignore_empty = 8;
}

// SFixed32Rules describes the constraints applied to `sfixed32` values
message SFixed32Rules {
    // Const specifies that this field must be exactly the specified value
    optional sfixed32 const = 1;

    // Lt specifies that this field must be less than the specified value,
    // exclusive
    optional sfixed32 lt = 2;

    // Lte specifies that this field must be less than or equal to the
    // specified value, inclusive
    optional sfixed32 lte = 3;

    // Gt specifies that this field must be greater than the specified value,
    // exclusive. If the value of Gt is larger than a specified Lt or Lte, the
    // range is reversed.
    optional sfixed32 gt = 4;

    // Gte specifies that this field must be greater than or equal to the
    // specified value, inclusive. If the value of Gte is larger than a
    // specified Lt or Lte, the range is reversed.
    optional sfixed32 gte = 5;

    // In specifies that this field must be equal to one of the specified
    // values
    repeated sfixed32 in = 6;

    // NotIn specifies that this field cannot be equal to one of the specified
    // values
    repeated sfixed32 not_in = 7;

    // IgnoreEmpty specifies that the validation rules of this field should be
    // evaluated only if the field is not empty
    optional bool ignore_empty = 8;
}

// SFixed64Rules describes the constraints applied to `sfixed64` values
message SFixed64Rules {
    // Const specifies that this field must be exactly the specified value
    optional sfixed64 const = 1;

    // Lt specifies that this field must be less than the specified value,
    // exclusive
    optional sfixed64 lt = 2;

    // Lte specifies that this field must be less than or equal to the
    // specified value, inclusive
    optional sfixed64 lte = 3;

    // Gt specifies that this field must be greater than the specified value,
    // exclusive. If the value of Gt is larger than a specified Lt or Lte, the
    // range is reversed.
    optional sfixed64 gt = 4;

    // Gte specifies that this field must be greater than or equal to the
    // specified value, inclusive. If the value of Gte is larger than a
    // specified Lt or Lte, the range is reversed.
    optional sfixed64 gte = 5;

    // In specifies that this field must be equal to one of the specified
    // values
    repeated sfixed64 in = 6;

    // NotIn specifies that this field cannot be equal to one of the specified
    // values
    repeated sfixed64 not_in = 7;

    // IgnoreEmpty specifies that the validation rules of this field should be
    // evaluated only if the field is not empty
    optional bool ignore_empty = 8;
}

// BoolRules describes the constraints applied to `bool` values
message BoolRules {
    // Const specifies that this field must be exactly the specified value
    optional bool const = 1;
}

// StringRules describe the constraints applied to `string` values
message StringRules {
    // Const specifies that this field must be exactly the specified value
    optional string const = 1;

    // Len specifies that this field must be the specified number of
    // characters (Unicode code points). Note that the number of
    // characters may differ from the number of bytes in the string.
    optional uint64 len = 19;

    // MinLen specifies that this field must be the specified number of
    // characters (Unicode code points) at a minimum. Note that the number of
    // characters may differ from the number of bytes in the string.
    optional uint64 min_len = 2;

    // MaxLen specifies that this field must be the specified number of
    // characters (Unicode code points) at a maximum. Note that the number of
    // characters may differ from the number of bytes in the string.
    optional uint64 max_len = 3;

    // LenBytes specifies that this field must be the specified number of bytes
    optional uint64 len_bytes = 20;

    // MinBytes specifies that this field must be the specified number of bytes
    // at a minimum
    optional uint64 min_bytes = 4;

    // MaxBytes specifies that this field must be the specified number of bytes
    // at a maximum
    optional uint64 max_bytes = 5;

    // Pattern specifes that this field must match against the specified
    // regular expression (RE2 syntax). The included expression should elide
    // any delimiters.
    optional string pattern  = 6;

    // Prefix specifies that this field must have the specified substring at
    // the beginning of the string.
    optional string prefix   = 7;

    // Suffix specifies that this field must have the specified substring at
    // the end of the string.
    optional string suffix   = 8;

    // Contains specifies that this field must have the specified substring
    // anywhere in the string.
    optional string contains = 9;

    // NotContains specifies that this field cannot have the specified substring
    // anywhere in the string.
    optional string not_contains = 23;

    // In specifies that this field must be equal to one of the specified
    // values
    repeated string in     = 10;

    // NotIn specifies that this field cannot be equal to one of the specified
    // values
    repeated string not_in = 11;

    // WellKnown rules provide advanced constraints against common string
    // patterns
    oneof well_known {
        // Email specifies that the field must be a valid email address as
        // defined by RFC 5322
        bool email    = 12;

        // Hostname specifies that the field must be a valid hostname as
        // defined by RFC 1034. This constraint does not support
        // internationalized domain names (IDNs).
        bool hostname = 13;

        // Ip specifies that the field must be a valid IP (v4 or v6) address.
        // Valid IPv6 addresses should not include surrounding square brackets.
        bool ip       = 14;

        // Ipv4 specifies that the field must be a valid IPv4 address.
        bool ipv4     = 15;

        // Ipv6 specifies that the field must be a valid IPv6 address. Valid
        // IPv6 addresses should not include surrounding square brackets.
        bool ipv6     = 16;

        // Uri specifies that the field must be a valid, absolute URI as defined
        // by RFC 3986
        bool uri      = 17;

        // UriRef specifies that the field must be a valid URI as defined by RFC
        // 3986 and may be relative or absolute.
        bool uri_ref  = 18;

        // Address specifies that the field must be either a valid hostname as
        // defined by RFC 1034 (which does not support internationalized domain
        // names or IDNs), or it can be a valid IP (v4 or v6).
        bool address  = 21;

        // Uuid specifies that the field must be a valid UUID as defined by
        // RFC 4122
        bool uuid     = 22;

        // WellKnownRegex specifies a common well known pattern defined as a regex.
        KnownRegex well_known_regex = 24;
    }

  // This applies to regexes HTTP_HEADER_NAME and HTTP_HEADER_VALUE to enable
  // strict header validation.
  // By default, this is true, and HTTP header validations are RFC-compliant.
  // Setting to false will enable a looser validations that only disallows
  // \r\n\0 characters, which can be used to bypass header matching rules.
  optional bool strict = 25 [default = true];

  // IgnoreEmpty specifies that the validation rules of this field should be
  // evaluated only if the field is not empty
  optional bool ignore_empty = 26;
}

// WellKnownRegex contain some well-known patterns.
enum KnownRegex {
  UNKNOWN = 0;

  // HTTP header name as defined by RFC 7230.
  HTTP_HEADER_NAME = 1;

  // HTTP header value as defined by RFC 7230.
  HTTP_HEADER_VALUE = 2;
}

// BytesRules describe the constraints applied to `bytes` values
message BytesRules {
    // Const specifies that this field must be exactly the specified value
    optional bytes const = 1;

    // Len specifies that this field must be the specified number of bytes
    optional uint64 len = 13;

    // MinLen specifies that this field must be the specified number of bytes
    // at a minimum
    optional uint64 min_len = 2;

    // MaxLen specifies that this field must be the specified number of bytes
    // at a maximum
    optional uint64 max_len = 3;

    // Pattern specifes that this field must match against the specified
    // regular expression (RE2 syntax). The included expression should elide
    // any delimiters.
    optional string pattern  = 4;

    // Prefix specifies that this field must have the specified bytes at the
    // beginning of the string.
    optional bytes  prefix   = 5;

    // Suffix specifies that this field must have the specified bytes at the
    // end of the string.
    optional bytes  suffix   = 6;

    // Contains specifies that this field must have the specified bytes
    // anywhere in the string.
    optional bytes  contains = 7;

    // In specifies that this field must be equal to one of the specified
    // values
    repeated bytes in     = 8;

    // NotIn specifies that this field cannot be equal to one of the specified
    // values
    repeated bytes not_in = 9;

    // WellKnown rules provide advanced constraints against common byte
    // patterns
    oneof well_known {
        // Ip specifies that the field must be a valid IP (v4 or v6) address in
        // byte format
        bool ip   = 10;

        // Ipv4 specifies that the field must be a valid IPv4 address in byte
        // format
        bool ipv4 = 11;

        // Ipv6 specifies that the field must be a valid IPv6 address in byte
        // format
        bool ipv6 = 12;
    }

    // IgnoreEmpty specifies that the validation rules of this field should be
    // evaluated only if the field is not empty
    optional bool ignore_empty = 14;
}

// EnumRules describe the constraints applied to enum values
message EnumRules {
    // Const specifies that this field must be exactly the specified value
    optional int32 const        = 1;

    // DefinedOnly specifies that this field must be only one of the defined
    // values for this enum, failing on any undefined value.
    optional bool  defined_only = 2;

    // In specifies that this field must be equal to one of the specified
    // values
    repeated int32 in           = 3;

    // NotIn specifies that this field cannot be equal to one of the specified
    // values
    repeated int32 not_in       = 4;
}

// MessageRules describe the constraints applied to embedded message values.
// For message-type fields, validation is performed recursively.
message MessageRules {
    // Skip specifies that the validation rules of this field should not be
    // evaluated
    optional bool skip     = 1;

    // Required specifies that this field must be set
    optional bool required = 2;
}

// RepeatedRules describe the constraints applied to `repeated` values
message RepeatedRules {
    // MinItems specifies that this field must have the specified number of
    // items at a minimum
    optional uint64 min_items = 1;

    // MaxItems specifies that this field must have the specified number of
    // items at a maximum
    optional uint64 max_items = 2;

    // Unique specifies that all elements in this field must be unique. This
    // contraint is only applicable to scalar and enum types (messages are not
    // supported).
    optional bool   unique    = 3;

    // Items specifies the contraints to be applied to each item in the field.
    // Repeated message fields will still execute validation against each item
    // unless skip is specified here.
    optional FieldRules items = 4;

    // IgnoreEmpty specifies that the validation rules of this field should be
    // evaluated only if the field is not empty
    optional bool ignore_empty = 5;
}

// MapRules describe the constraints applied to `map` values
message MapRules {
    // MinPairs specifies that this field must have the specified number of
    // KVs at a minimum
    optional uint64 min_pairs = 1;

    // MaxPairs specifies that this field must have the specified number of
    // KVs at a maximum
    optional uint64 max_pairs = 2;

    // NoSparse specifies values in this field cannot be unset. This only
    // applies to map's with message value types.
    optional bool no_sparse = 3;

    // Keys specifies the constraints to be applied to each key in the field.
    optional FieldRules keys   = 4;

    // Values specifies the constraints to be applied to the value of each key
    // in the field. Message values will still have their validations evaluated
    // unless skip is specified here.
    optional FieldRules values = 5;

    // IgnoreEmpty specifies that the validation rules of this field should be
    // evaluated only if the field is not empty
    optional bool ignore_empty = 6;
}

// AnyRules describe constraints applied exclusively to the
// `google.protobuf.Any` well-known type
message AnyRules {
    // Required specifies that this field must be set
    optional bool required = 1;

    // In specifies that this field's `type_url` must be equal to one of the
    // specified values.
    repeated string in     = 2;

    // NotIn specifies that this field's `type_url` must not be equal to any of
    // the specified values.
    repeated string not_in = 3;
}

// DurationRules describe the constraints applied exclusively to the
// `google.protobuf.Duration` well-known type
message DurationRules {
    // Required specifies that this field must be set
    optional bool required = 1;

    // Const specifies that this field must be exactly the specified value
    optional google.protobuf.Duration const = 2;

    // Lt specifies that this field must be less than the specified value,
    // exclusive
    optional google.protobuf.Duration lt = 3;

    // Lt specifies that this field must be less than the specified value,
    // inclusive
    optional google.protobuf.Duration lte = 4;

    // Gt specifies that this field must be greater than the specified value,
    // exclusive
    optional google.protobuf.Duration gt = 5;

    // Gte specifies that this field must be greater than the specified value,
    // inclusive
    optional google.protobuf.Duration gte = 6;

    // In specifies that this field must be equal to one of the specified
    // values
    repeated google.protobuf.Duration in = 7;

    // NotIn specifies that this field cannot be equal to one of the specified
    // values
    repeated google.protobuf.Duration not_in = 8;
}

// TimestampRules describe the constraints applied exclusively to the
// `google.protobuf.Timestamp` well-known type
message TimestampRules {
    // Required specifies that this field must be set
    optional bool required = 1;

    // Const specifies that this field must be exactly the specified value
    optional google.protobuf.Timestamp const = 2;

    // Lt specifies that this field must be less than the specified value,
    // exclusive
    optional google.protobuf.Timestamp lt = 3;

    // Lte specifies that this field must be less than the specified value,
    // inclusive
    optional google.protobuf.Timestamp lte = 4;

    // Gt specifies that this field must be greater than the specified value,
    // exclusive
    optional google.protobuf.Timestamp gt = 5;

    // Gte specifies that this field must be greater than the specified value,
    // inclusive
    optional google.protobuf.Timestamp gte = 6;

    // LtNow specifies that this must be less than the current time. LtNow
    // can only be used with the Within rule.
    optional bool lt_now  = 7;

    // GtNow specifies that this must be greater than the current time. GtNow
    // can only be used with the Within rule.
    optional bool gt_now  = 8;

    // Within specifies that this field must be within this duration of the
    // current time. This constraint can be used alone or with the LtNow and
    // GtNow rules.
    optional google.protobuf.Duration within = 9;
}
```

### `protos/p2p_validate.proto`

```protobuf
// fork from https://github.com/envoyproxy/protoc-gen-validate/blob/main/validate/validate.proto
syntax = "proto3";
package p2p_validate;

import "google/protobuf/descriptor.proto";
import "google/protobuf/duration.proto";
import "google/protobuf/timestamp.proto";

// Validation rules applied at the message level
extend google.protobuf.MessageOptions {
    // Ignore skips generation of validation methods for this message.
    optional bool ignored = 1073;
}

// Validation rules applied at the oneof level
extend google.protobuf.OneofOptions {
    // Required ensures that exactly one the field options in a oneof is set;
    // validation fails if no fields in the oneof are set.
    optional bool required = 1073;
    optional OneofRules oneof_extend = 1074;
}

// Validation rules applied at the field level
extend google.protobuf.FieldOptions {
    // Rules specify the validations to be performed on this field. By default,
    // no validation is performed against a field.
    optional FieldRules rules = 1073;
}

message OneofRules {
    // Define whether the field of oneof is optional
    repeated string optional = 1;
}

// FieldRules encapsulates the rules for each type of field. Depending on the
// field, the correct set should be used to ensure proper validations.
message FieldRules {
    optional MessageRules message = 17;
    oneof type {
        // Scalar Field Types
        FloatRules    float    = 1;
        DoubleRules   double   = 2;
        Int32Rules    int32    = 3;
        Int64Rules    int64    = 4;
        UInt32Rules   uint32   = 5;
        UInt64Rules   uint64   = 6;
        SInt32Rules   sint32   = 7;
        SInt64Rules   sint64   = 8;
        Fixed32Rules  fixed32  = 9;
        Fixed64Rules  fixed64  = 10;
        SFixed32Rules sfixed32 = 11;
        SFixed64Rules sfixed64 = 12;
        BoolRules     bool     = 13;
        StringRules   string   = 14;
        BytesRules    bytes    = 15;

        // Complex Field Types
        EnumRules     enum     = 16;
        RepeatedRules repeated = 18;
        MapRules      map      = 19;

        // Well-Known Field Types
        AnyRules       any       = 20;
        DurationRules  duration  = 21;
        TimestampRules timestamp = 22;
    }
}

// FloatRules describes the constraints applied to `float` values
message FloatRules {
    // Const specifies that this field must be exactly the specified value
    optional float const = 1;

    // Lt specifies that this field must be less than the specified value,
    // exclusive
    optional float lt = 2;

    // Lte specifies that this field must be less than or equal to the
    // specified value, inclusive
    optional float le = 3;

    // Gt specifies that this field must be greater than the specified value,
    // exclusive. If the value of Gt is larger than a specified Lt or Lte, the
    // range is reversed.
    optional float gt = 4;

    // Gte specifies that this field must be greater than or equal to the
    // specified value, inclusive. If the value of Gte is larger than a
    // specified Lt or Lte, the range is reversed.
    optional float ge = 5;

    // In specifies that this field must be equal to one of the specified
    // values
    repeated float in = 6;

    // NotIn specifies that this field cannot be equal to one of the specified
    // values
    repeated float not_in = 7;

    // Whether to enable this field, if not, the generated Model will not carry this field
    optional bool enable = 8;

    oneof default_config {
        // The default value corresponding to the field, if not set,
        // the default value is the default value of the corresponding type of the field
        float default = 9;
        // The default value factory function corresponding to the field, supports template variables,
        // such as `p2p@import|uuid|uuid4`
        string  default_factory = 10;
        // Set field required[Will be deprecated after version 1.0.0]
        bool miss_default = 11;
        // Set field required
        bool required = 21;
        // Similar meaning to `default`, but using template variables, such as `p2p@import|uuid|uuid4`
        string default_template = 22;
    }
    // Set the alias of the field in the pydantic.Base Model
    optional string alias = 12;
    // Set the description of the field
    optional string description = 13;
    // Corresponding multiple validation of the set value
    optional float multiple_of = 14;
    oneof example_config {
        // Set the corresponding sample value
        float example = 15;
        // Set the corresponding sample value factory function, support template variables
        string example_factory = 16;
    }
    // Set the Field object corresponding to the field, support template variables
    optional string field = 17;
    // Set the type object corresponding to the field, support template variables
    optional string type = 18;
    // The title corresponding to the field
    optional string title = 19;
    // Field's custom extension parameter in the format Json
    optional string extra = 20;
}

// DoubleRules describes the constraints applied to `double` values
message DoubleRules {
    // Const specifies that this field must be exactly the specified value
    optional double const = 1;

    // Lt specifies that this field must be less than the specified value,
    // exclusive
    optional double lt = 2;

    // Lte specifies that this field must be less than or equal to the
    // specified value, inclusive
    optional double le = 3;

    // Gt specifies that this field must be greater than the specified value,
    // exclusive. If the value of Gt is larger than a specified Lt or Lte, the
    // range is reversed.
    optional double gt = 4;

    // Gte specifies that this field must be greater than or equal to the
    // specified value, inclusive. If the value of Gte is larger than a
    // specified Lt or Lte, the range is reversed.
    optional double ge = 5;

    // In specifies that this field must be equal to one of the specified
    // values
    repeated double in = 6;

    // NotIn specifies that this field cannot be equal to one of the specified
    // values
    repeated double not_in = 7;

    // Whether to enable this field, if not, the generated Model will not carry this field
    optional bool enable = 8;

    oneof default_config {
        // The default value corresponding to the field, if not set,
        // the default value is the default value of the corresponding type of the field
        float default = 9;
        // The default value factory function corresponding to the field, supports template variables,
        // such as `p2p@import|uuid|uuid4`
        string  default_factory = 10;
        // Set field required[Will be deprecated after version 1.0.0]
        bool miss_default = 11;
        // Set field required
        bool required = 21;
        // Similar meaning to `default`, but using template variables, such as `p2p@import|uuid|uuid4`
        string default_template = 22;
    }
    // Set the alias of the field in the pydantic.Base Model
    optional string alias = 12;
    // Set the description of the field
    optional string description = 13;
    // Corresponding multiple validation of the set value
    optional float multiple_of = 14;
    oneof example_config {
        // Set the corresponding sample value
        float example = 15;
        // Set the corresponding sample value factory function, support template variables
        string example_factory = 16;
    }
    // Set the Field object corresponding to the field, support template variables
    optional string field = 17;
    // Set the type object corresponding to the field, support template variables
    optional string type = 18;
    // The title corresponding to the field
    optional string title = 19;
    // Field's custom extension parameter in the format Json
    optional string extra = 20;
}

// Int32Rules describes the constraints applied to `int32` values
message Int32Rules {
    // Const specifies that this field must be exactly the specified value
    optional int32 const = 1;

    // Lt specifies that this field must be less than the specified value,
    // exclusive
    optional int32 lt = 2;

    // Lte specifies that this field must be less than or equal to the
    // specified value, inclusive
    optional int32 le = 3;

    // Gt specifies that this field must be greater than the specified value,
    // exclusive. If the value of Gt is larger than a specified Lt or Lte, the
    // range is reversed.
    optional int32 gt = 4;

    // Gte specifies that this field must be greater than or equal to the
    // specified value, inclusive. If the value of Gte is larger than a
    // specified Lt or Lte, the range is reversed.
    optional int32 ge = 5;

    // In specifies that this field must be equal to one of the specified
    // values
    repeated int32 in = 6;

    // NotIn specifies that this field cannot be equal to one of the specified
    // values
    repeated int32 not_in = 7;

    // Whether to enable this field, if not, the generated Model will not carry this field
    optional bool enable = 8;

    oneof default_config {
        // The default value corresponding to the field, if not set,
        // the default value is the default value of the corresponding type of the field
        float default = 9;
        // The default value factory function corresponding to the field, supports template variables,
        // such as `p2p@import|uuid|uuid4`
        string  default_factory = 10;
        // Set field required[Will be deprecated after version 1.0.0]
        bool miss_default = 11;
        // Set field required
        bool required = 21;
        // Similar meaning to `default`, but using template variables, such as `p2p@import|uuid|uuid4`
        string default_template = 22;
    }
    // Set the alias of the field in the pydantic.Base Model
    optional string alias = 12;
    // Set the description of the field
    optional string description = 13;
    // Corresponding multiple validation of the set value
    optional float multiple_of = 14;
    oneof example_config {
        // Set the corresponding sample value
        float example = 15;
        // Set the corresponding sample value factory function, support template variables
        string example_factory = 16;
    }
    // Set the Field object corresponding to the field, support template variables
    optional string field = 17;
    // Set the type object corresponding to the field, support template variables
    optional string type = 18;
    // The title corresponding to the field
    optional string title = 19;
    // Field's custom extension parameter in the format Json
    optional string extra = 20;
}

// Int64Rules describes the constraints applied to `int64` values
message Int64Rules {
    // Const specifies that this field must be exactly the specified value
    optional int64 const = 1;

    // Lt specifies that this field must be less than the specified value,
    // exclusive
    optional int64 lt = 2;

    // Lte specifies that this field must be less than or equal to the
    // specified value, inclusive
    optional int64 le = 3;

    // Gt specifies that this field must be greater than the specified value,
    // exclusive. If the value of Gt is larger than a specified Lt or Lte, the
    // range is reversed.
    optional int64 gt = 4;

    // Gte specifies that this field must be greater than or equal to the
    // specified value, inclusive. If the value of Gte is larger than a
    // specified Lt or Lte, the range is reversed.
    optional int64 ge = 5;

    // In specifies that this field must be equal to one of the specified
    // values
    repeated int64 in = 6;

    // NotIn specifies that this field cannot be equal to one of the specified
    // values
    repeated int64 not_in = 7;

        // Whether to enable this field, if not, the generated Model will not carry this field
    optional bool enable = 8;

    oneof default_config {
        // The default value corresponding to the field, if not set,
        // the default value is the default value of the corresponding type of the field
        float default = 9;
        // The default value factory function corresponding to the field, supports template variables,
        // such as `p2p@import|uuid|uuid4`
        string  default_factory = 10;
        // Set field required[Will be deprecated after version 1.0.0]
        bool miss_default = 11;
        // Set field required
        bool required = 21;
        // Similar meaning to `default`, but using template variables, such as `p2p@import|uuid|uuid4`
        string default_template = 22;
    }
    // Set the alias of the field in the pydantic.Base Model
    optional string alias = 12;
    // Set the description of the field
    optional string description = 13;
    // Corresponding multiple validation of the set value
    optional float multiple_of = 14;
    oneof example_config {
        // Set the corresponding sample value
        float example = 15;
        // Set the corresponding sample value factory function, support template variables
        string example_factory = 16;
    }
    // Set the Field object corresponding to the field, support template variables
    optional string field = 17;
    // Set the type object corresponding to the field, support template variables
    optional string type = 18;
    // The title corresponding to the field
    optional string title = 19;
    // Field's custom extension parameter in the format Json
    optional string extra = 20;
}

// UInt32Rules describes the constraints applied to `uint32` values
message UInt32Rules {
    // Const specifies that this field must be exactly the specified value
    optional uint32 const = 1;

    // Lt specifies that this field must be less than the specified value,
    // exclusive
    optional uint32 lt = 2;

    // Lte specifies that this field must be less than or equal to the
    // specified value, inclusive
    optional uint32 le = 3;

    // Gt specifies that this field must be greater than the specified value,
    // exclusive. If the value of Gt is larger than a specified Lt or Lte, the
    // range is reversed.
    optional uint32 gt = 4;

    // Gte specifies that this field must be greater than or equal to the
    // specified value, inclusive. If the value of Gte is larger than a
    // specified Lt or Lte, the range is reversed.
    optional uint32 ge = 5;

    // In specifies that this field must be equal to one of the specified
    // values
    repeated uint32 in = 6;

    // NotIn specifies that this field cannot be equal to one of the specified
    // values
    repeated uint32 not_in = 7;

    // Whether to enable this field, if not, the generated Model will not carry this field
    optional bool enable = 8;

    oneof default_config {
        // The default value corresponding to the field, if not set,
        // the default value is the default value of the corresponding type of the field
        float default = 9;
        // The default value factory function corresponding to the field, supports template variables,
        // such as `p2p@import|uuid|uuid4`
        string  default_factory = 10;
        // Set field required[Will be deprecated after version 1.0.0]
        bool miss_default = 11;
        // Set field required
        bool required = 21;
        // Similar meaning to `default`, but using template variables, such as `p2p@import|uuid|uuid4`
        string default_template = 22;
    }
    // Set the alias of the field in the pydantic.Base Model
    optional string alias = 12;
    // Set the description of the field
    optional string description = 13;
    // Corresponding multiple validation of the set value
    optional float multiple_of = 14;
    oneof example_config {
        // Set the corresponding sample value
        float example = 15;
        // Set the corresponding sample value factory function, support template variables
        string example_factory = 16;
    }
    // Set the Field object corresponding to the field, support template variables
    optional string field = 17;
    // Set the type object corresponding to the field, support template variables
    optional string type = 18;
    // The title corresponding to the field
    optional string title = 19;
    // Field's custom extension parameter in the format Json
    optional string extra = 20;
}

// UInt64Rules describes the constraints applied to `uint64` values
message UInt64Rules {
    // Const specifies that this field must be exactly the specified value
    optional uint64 const = 1;

    // Lt specifies that this field must be less than the specified value,
    // exclusive
    optional uint64 lt = 2;

    // Lte specifies that this field must be less than or equal to the
    // specified value, inclusive
    optional uint64 le = 3;

    // Gt specifies that this field must be greater than the specified value,
    // exclusive. If the value of Gt is larger than a specified Lt or Lte, the
    // range is reversed.
    optional uint64 gt = 4;

    // Gte specifies that this field must be greater than or equal to the
    // specified value, inclusive. If the value of Gte is larger than a
    // specified Lt or Lte, the range is reversed.
    optional uint64 ge = 5;

    // In specifies that this field must be equal to one of the specified
    // values
    repeated uint64 in = 6;

    // NotIn specifies that this field cannot be equal to one of the specified
    // values
    repeated uint64 not_in = 7;

    // Whether to enable this field, if not, the generated Model will not carry this field
    optional bool enable = 8;

    oneof default_config {
        // The default value corresponding to the field, if not set,
        // the default value is the default value of the corresponding type of the field
        float default = 9;
        // The default value factory function corresponding to the field, supports template variables,
        // such as `p2p@import|uuid|uuid4`
        string  default_factory = 10;
        // Set field required[Will be deprecated after version 1.0.0]
        bool miss_default = 11;
        // Set field required
        bool required = 21;
        // Similar meaning to `default`, but using template variables, such as `p2p@import|uuid|uuid4`
        string default_template = 22;
    }
    // Set the alias of the field in the pydantic.Base Model
    optional string alias = 12;
    // Set the description of the field
    optional string description = 13;
    // Corresponding multiple validation of the set value
    optional float multiple_of = 14;
    oneof example_config {
        // Set the corresponding sample value
        float example = 15;
        // Set the corresponding sample value factory function, support template variables
        string example_factory = 16;
    }
    // Set the Field object corresponding to the field, support template variables
    optional string field = 17;
    // Set the type object corresponding to the field, support template variables
    optional string type = 18;
    // The title corresponding to the field
    optional string title = 19;
    // Field's custom extension parameter in the format Json
    optional string extra = 20;
}

// SInt32Rules describes the constraints applied to `sint32` values
message SInt32Rules {
    // Const specifies that this field must be exactly the specified value
    optional sint32 const = 1;

    // Lt specifies that this field must be less than the specified value,
    // exclusive
    optional sint32 lt = 2;

    // Lte specifies that this field must be less than or equal to the
    // specified value, inclusive
    optional sint32 le = 3;

    // Gt specifies that this field must be greater than the specified value,
    // exclusive. If the value of Gt is larger than a specified Lt or Lte, the
    // range is reversed.
    optional sint32 gt = 4;

    // Gte specifies that this field must be greater than or equal to the
    // specified value, inclusive. If the value of Gte is larger than a
    // specified Lt or Lte, the range is reversed.
    optional sint32 ge = 5;

    // In specifies that this field must be equal to one of the specified
    // values
    repeated sint32 in = 6;

    // NotIn specifies that this field cannot be equal to one of the specified
    // values
    repeated sint32 not_in = 7;

    // Whether to enable this field, if not, the generated Model will not carry this field
    optional bool enable = 8;

    oneof default_config {
        // The default value corresponding to the field, if not set,
        // the default value is the default value of the corresponding type of the field
        float default = 9;
        // The default value factory function corresponding to the field, supports template variables,
        // such as `p2p@import|uuid|uuid4`
        string  default_factory = 10;
        // Set field required[Will be deprecated after version 1.0.0]
        bool miss_default = 11;
        // Set field required
        bool required = 21;
        // Similar meaning to `default`, but using template variables, such as `p2p@import|uuid|uuid4`
        string default_template = 22;
    }
    // Set the alias of the field in the pydantic.Base Model
    optional string alias = 12;
    // Set the description of the field
    optional string description = 13;
    // Corresponding multiple validation of the set value
    optional float multiple_of = 14;
    oneof example_config {
        // Set the corresponding sample value
        float example = 15;
        // Set the corresponding sample value factory function, support template variables
        string example_factory = 16;
    }
    // Set the Field object corresponding to the field, support template variables
    optional string field = 17;
    // Set the type object corresponding to the field, support template variables
    optional string type = 18;
    // The title corresponding to the field
    optional string title = 19;
    // Field's custom extension parameter in the format Json
    optional string extra = 20;
}

// SInt64Rules describes the constraints applied to `sint64` values
message SInt64Rules {
    // Const specifies that this field must be exactly the specified value
    optional sint64 const = 1;

    // Lt specifies that this field must be less than the specified value,
    // exclusive
    optional sint64 lt = 2;

    // Lte specifies that this field must be less than or equal to the
    // specified value, inclusive
    optional sint64 le = 3;

    // Gt specifies that this field must be greater than the specified value,
    // exclusive. If the value of Gt is larger than a specified Lt or Lte, the
    // range is reversed.
    optional sint64 gt = 4;

    // Gte specifies that this field must be greater than or equal to the
    // specified value, inclusive. If the value of Gte is larger than a
    // specified Lt or Lte, the range is reversed.
    optional sint64 ge = 5;

    // In specifies that this field must be equal to one of the specified
    // values
    repeated sint64 in = 6;

    // NotIn specifies that this field cannot be equal to one of the specified
    // values
    repeated sint64 not_in = 7;

    // Whether to enable this field, if not, the generated Model will not carry this field
    optional bool enable = 8;

    oneof default_config {
        // The default value corresponding to the field, if not set,
        // the default value is the default value of the corresponding type of the field
        float default = 9;
        // The default value factory function corresponding to the field, supports template variables,
        // such as `p2p@import|uuid|uuid4`
        string  default_factory = 10;
        // Set field required[Will be deprecated after version 1.0.0]
        bool miss_default = 11;
        // Set field required
        bool required = 21;
        // Similar meaning to `default`, but using template variables, such as `p2p@import|uuid|uuid4`
        string default_template = 22;
    }
    // Set the alias of the field in the pydantic.Base Model
    optional string alias = 12;
    // Set the description of the field
    optional string description = 13;
    // Corresponding multiple validation of the set value
    optional float multiple_of = 14;
    oneof example_config {
        // Set the corresponding sample value
        float example = 15;
        // Set the corresponding sample value factory function, support template variables
        string example_factory = 16;
    }
    // Set the Field object corresponding to the field, support template variables
    optional string field = 17;
    // Set the type object corresponding to the field, support template variables
    optional string type = 18;
    // The title corresponding to the field
    optional string title = 19;
    // Field's custom extension parameter in the format Json
    optional string extra = 20;
}

// Fixed32Rules describes the constraints applied to `fixed32` values
message Fixed32Rules {
    // Const specifies that this field must be exactly the specified value
    optional fixed32 const = 1;

    // Lt specifies that this field must be less than the specified value,
    // exclusive
    optional fixed32 lt = 2;

    // Lte specifies that this field must be less than or equal to the
    // specified value, inclusive
    optional fixed32 le = 3;

    // Gt specifies that this field must be greater than the specified value,
    // exclusive. If the value of Gt is larger than a specified Lt or Lte, the
    // range is reversed.
    optional fixed32 gt = 4;

    // Gte specifies that this field must be greater than or equal to the
    // specified value, inclusive. If the value of Gte is larger than a
    // specified Lt or Lte, the range is reversed.
    optional fixed32 ge = 5;

    // In specifies that this field must be equal to one of the specified
    // values
    repeated fixed32 in = 6;

    // NotIn specifies that this field cannot be equal to one of the specified
    // values
    repeated fixed32 not_in = 7;

    // Whether to enable this field, if not, the generated Model will not carry this field
    optional bool enable = 8;

    oneof default_config {
        // The default value corresponding to the field, if not set,
        // the default value is the default value of the corresponding type of the field
        float default = 9;
        // The default value factory function corresponding to the field, supports template variables,
        // such as `p2p@import|uuid|uuid4`
        string  default_factory = 10;
        // Set field required[Will be deprecated after version 1.0.0]
        bool miss_default = 11;
        // Set field required
        bool required = 21;
        // Similar meaning to `default`, but using template variables, such as `p2p@import|uuid|uuid4`
        string default_template = 22;
    }
    // Set the alias of the field in the pydantic.Base Model
    optional string alias = 12;
    // Set the description of the field
    optional string description = 13;
    // Corresponding multiple validation of the set value
    optional float multiple_of = 14;
    oneof example_config {
        // Set the corresponding sample value
        float example = 15;
        // Set the corresponding sample value factory function, support template variables
        string example_factory = 16;
    }
    // Set the Field object corresponding to the field, support template variables
    optional string field = 17;
    // Set the type object corresponding to the field, support template variables
    optional string type = 18;
    // The title corresponding to the field
    optional string title = 19;
    // Field's custom extension parameter in the format Json
    optional string extra = 20;
}

// Fixed64Rules describes the constraints applied to `fixed64` values
message Fixed64Rules {
    // Const specifies that this field must be exactly the specified value
    optional fixed64 const = 1;

    // Lt specifies that this field must be less than the specified value,
    // exclusive
    optional fixed64 lt = 2;

    // Lte specifies that this field must be less than or equal to the
    // specified value, inclusive
    optional fixed64 le = 3;

    // Gt specifies that this field must be greater than the specified value,
    // exclusive. If the value of Gt is larger than a specified Lt or Lte, the
    // range is reversed.
    optional fixed64 gt = 4;

    // Gte specifies that this field must be greater than or equal to the
    // specified value, inclusive. If the value of Gte is larger than a
    // specified Lt or Lte, the range is reversed.
    optional fixed64 ge = 5;

    // In specifies that this field must be equal to one of the specified
    // values
    repeated fixed64 in = 6;

    // NotIn specifies that this field cannot be equal to one of the specified
    // values
    repeated fixed64 not_in = 7;

    // Whether to enable this field, if not, the generated Model will not carry this field
    optional bool enable = 8;

    oneof default_config {
        // The default value corresponding to the field, if not set,
        // the default value is the default value of the corresponding type of the field
        float default = 9;
        // The default value factory function corresponding to the field, supports template variables,
        // such as `p2p@import|uuid|uuid4`
        string  default_factory = 10;
        // Set field required[Will be deprecated after version 1.0.0]
        bool miss_default = 11;
        // Set field required
        bool required = 21;
        // Similar meaning to `default`, but using template variables, such as `p2p@import|uuid|uuid4`
        string default_template = 22;
    }
    // Set the alias of the field in the pydantic.Base Model
    optional string alias = 12;
    // Set the description of the field
    optional string description = 13;
    // Corresponding multiple validation of the set value
    optional float multiple_of = 14;
    oneof example_config {
        // Set the corresponding sample value
        float example = 15;
        // Set the corresponding sample value factory function, support template variables
        string example_factory = 16;
    }
    // Set the Field object corresponding to the field, support template variables
    optional string field = 17;
    // Set the type object corresponding to the field, support template variables
    optional string type = 18;
    // The title corresponding to the field
    optional string title = 19;
    // Field's custom extension parameter in the format Json
    optional string extra = 20;
}

// SFixed32Rules describes the constraints applied to `sfixed32` values
message SFixed32Rules {
    // Const specifies that this field must be exactly the specified value
    optional sfixed32 const = 1;

    // Lt specifies that this field must be less than the specified value,
    // exclusive
    optional sfixed32 lt = 2;

    // Lte specifies that this field must be less than or equal to the
    // specified value, inclusive
    optional sfixed32 le = 3;

    // Gt specifies that this field must be greater than the specified value,
    // exclusive. If the value of Gt is larger than a specified Lt or Lte, the
    // range is reversed.
    optional sfixed32 gt = 4;

    // Gte specifies that this field must be greater than or equal to the
    // specified value, inclusive. If the value of Gte is larger than a
    // specified Lt or Lte, the range is reversed.
    optional sfixed32 ge = 5;

    // In specifies that this field must be equal to one of the specified
    // values
    repeated sfixed32 in = 6;

    // NotIn specifies that this field cannot be equal to one of the specified
    // values
    repeated sfixed32 not_in = 7;

    // Whether to enable this field, if not, the generated Model will not carry this field
    optional bool enable = 8;

    oneof default_config {
        // The default value corresponding to the field, if not set,
        // the default value is the default value of the corresponding type of the field
        float default = 9;
        // The default value factory function corresponding to the field, supports template variables,
        // such as `p2p@import|uuid|uuid4`
        string  default_factory = 10;
        // Set field required[Will be deprecated after version 1.0.0]
        bool miss_default = 11;
        // Set field required
        bool required = 21;
        // Similar meaning to `default`, but using template variables, such as `p2p@import|uuid|uuid4`
        string default_template = 22;
    }
    // Set the alias of the field in the pydantic.Base Model
    optional string alias = 12;
    // Set the description of the field
    optional string description = 13;
    // Corresponding multiple validation of the set value
    optional float multiple_of = 14;
    oneof example_config {
        // Set the corresponding sample value
        float example = 15;
        // Set the corresponding sample value factory function, support template variables
        string example_factory = 16;
    }
    // Set the Field object corresponding to the field, support template variables
    optional string field = 17;
    // Set the type object corresponding to the field, support template variables
    optional string type = 18;
    // The title corresponding to the field
    optional string title = 19;
    // Field's custom extension parameter in the format Json
    optional string extra = 20;
}

// SFixed64Rules describes the constraints applied to `sfixed64` values
message SFixed64Rules {
    // Const specifies that this field must be exactly the specified value
    optional sfixed64 const = 1;

    // Lt specifies that this field must be less than the specified value,
    // exclusive
    optional sfixed64 lt = 2;

    // Lte specifies that this field must be less than or equal to the
    // specified value, inclusive
    optional sfixed64 le = 3;

    // Gt specifies that this field must be greater than the specified value,
    // exclusive. If the value of Gt is larger than a specified Lt or Lte, the
    // range is reversed.
    optional sfixed64 gt = 4;

    // Gte specifies that this field must be greater than or equal to the
    // specified value, inclusive. If the value of Gte is larger than a
    // specified Lt or Lte, the range is reversed.
    optional sfixed64 ge = 5;

    // In specifies that this field must be equal to one of the specified
    // values
    repeated sfixed64 in = 6;

    // NotIn specifies that this field cannot be equal to one of the specified
    // values
    repeated sfixed64 not_in = 7;

    // Whether to enable this field, if not, the generated Model will not carry this field
    optional bool enable = 8;

    oneof default_config {
        // The default value corresponding to the field, if not set,
        // the default value is the default value of the corresponding type of the field
        float default = 9;
        // The default value factory function corresponding to the field, supports template variables,
        // such as `p2p@import|uuid|uuid4`
        string  default_factory = 10;
        // Set field required[Will be deprecated after version 1.0.0]
        bool miss_default = 11;
        // Set field required
        bool required = 21;
        // Similar meaning to `default`, but using template variables, such as `p2p@import|uuid|uuid4`
        string default_template = 22;
    }
    // Set the alias of the field in the pydantic.Base Model
    optional string alias = 12;
    // Set the description of the field
    optional string description = 13;
    // Corresponding multiple validation of the set value
    optional float multiple_of = 14;
    oneof example_config {
        // Set the corresponding sample value
        float example = 15;
        // Set the corresponding sample value factory function, support template variables
        string example_factory = 16;
    }
    // Set the Field object corresponding to the field, support template variables
    optional string field = 17;
    // Set the type object corresponding to the field, support template variables
    optional string type = 18;
    // The title corresponding to the field
    optional string title = 19;
    // Field's custom extension parameter in the format Json
    optional string extra = 20;
}

// BoolRules describes the constraints applied to `bool` values
message BoolRules {
    // Const specifies that this field must be exactly the specified value
    optional bool const = 1;
    // Whether to enable this field, if not, the generated Model will not carry this field
    optional bool enable = 2;

    oneof default_config {
        // The default value corresponding to the field, if not set,
        // the default value is the default value of the corresponding type of the field
        bool default = 3;
        // Set field required[Will be deprecated after version 1.0.0]
        bool miss_default = 11;
        // Set field required
        bool required = 21;
        // Similar meaning to `default`, but using template variables, such as `p2p@import|uuid|uuid4`
        string default_template = 22;
    }
    // Set the alias of the field in the pydantic.Base Model
    optional string alias = 5;
    // Set the description of the field
    optional string description = 6;
    // Set the corresponding sample value
    optional bool example = 7;
    // Set the Field object corresponding to the field, support template variables
    optional string field = 8;
    // Set the type object corresponding to the field, support template variables
    optional string type = 9;
    // The title corresponding to the field
    optional string title = 19;
    // Field's custom extension parameter in the format Json
    optional string extra = 20;
}

// StringRules describe the constraints applied to `string` values
message StringRules {
    // Const specifies that this field must be exactly the specified value
    optional string const = 1;

    // Len specifies that this field must be the specified number of
    // characters (Unicode code points). Note that the number of
    // characters may differ from the number of bytes in the string.
    optional uint64 len = 2;

    // MinLen specifies that this field must be the specified number of
    // characters (Unicode code points) at a minimum. Note that the number of
    // characters may differ from the number of bytes in the string.
    optional uint64 min_length = 3;

    // MaxLen specifies that this field must be the specified number of
    // characters (Unicode code points) at a maximum. Note that the number of
    // characters may differ from the number of bytes in the string.
    optional uint64 max_length = 4;

    // Pattern specifes that this field must match against the specified
    // regular expression (RE2 syntax). The included expression should elide
    // any delimiters.
    optional string pattern  = 5;

    // Prefix specifies that this field must have the specified substring at
    // the beginning of the string.
    optional string prefix   = 6;

    // Suffix specifies that this field must have the specified substring at
    // the end of the string.
    optional string suffix   = 7;

    // Contains specifies that this field must have the specified substring
    // anywhere in the string.
    optional string contains = 8;

    // NotContains specifies that this field cannot have the specified substring
    // anywhere in the string.
    optional string not_contains = 9;

    // In specifies that this field must be equal to one of the specified
    // values
    repeated string in     = 10;

    // NotIn specifies that this field cannot be equal to one of the specified
    // values
    repeated string not_in = 11;

    // WellKnown rules provide advanced constraints against common string
    // patterns
    oneof well_known {
        // Email specifies that the field must be a valid email address as
        // defined by RFC 5322
        bool email    = 12;

        // Hostname specifies that the field must be a valid hostname as
        // defined by RFC 1034. This constraint does not support
        // internationalized domain names (IDNs).
        bool hostname = 13;

        // Ip specifies that the field must be a valid IP (v4 or v6) address.
        // Valid IPv6 addresses should not include surrounding square brackets.
        bool ip       = 14;

        // Ipv4 specifies that the field must be a valid IPv4 address.
        bool ipv4     = 15;

        // Ipv6 specifies that the field must be a valid IPv6 address. Valid
        // IPv6 addresses should not include surrounding square brackets.
        bool ipv6     = 16;

        // Uri specifies that the field must be a valid, absolute URI as defined
        // by RFC 3986
        bool uri      = 17;

        // UriRef specifies that the field must be a valid URI as defined by RFC
        // 3986 and may be relative or absolute.
        bool uri_ref  = 18;

        // Address specifies that the field must be either a valid hostname as
        // defined by RFC 1034 (which does not support internationalized domain
        // names or IDNs), or it can be a valid IP (v4 or v6).
        bool address  = 21;

        // Uuid specifies that the field must be a valid UUID as defined by
        // RFC 4122
        bool uuid     = 22;

        // If you want to use the property of pydantic.type, you can directly
        // set the value to the string of the corresponding property,
        // and then the program will automatically introduce the type of the corresponding string
        string pydantic_type = 99;
    }
    // Whether to enable this field, if not, the generated Model will not carry this field
    optional bool enable = 23;

    oneof default_config {
        // The default value corresponding to the field, if not set,
        // the default value is the default value of the corresponding type of the field
        string default = 24;
        // The default value factory function corresponding to the field, supports template variables,
        // such as `p2p@import|uuid|uuid4`
        string  default_factory = 25;
        // Set field required[Will be deprecated after version 1.0.0]
        bool miss_default = 26;
        // Set field required
        bool required = 35;
        // Similar meaning to `default`, but using template variables, such as `p2p@import|uuid|uuid4`
        string default_template = 36;
    }
    // Set the alias of the field in the pydantic.Base Model
    optional string alias = 27;
    // Set the description of the field
    optional string description = 28;
    oneof example_config {
        // Set the corresponding sample value
        string example = 30;
        // Set the corresponding sample value factory function, support template variables
        string example_factory = 31;
    }
    // Set the Field object corresponding to the field, support template variables
    optional string field = 32;
    // Set the type object corresponding to the field, support template variables
    optional string type = 33;
    // The title corresponding to the field
    optional string title = 34;
    // Field's custom extension parameter in the format Json
    optional string extra = 20;
}


// BytesRules describe the constraints applied to `bytes` values
message BytesRules {
    // Const specifies that this field must be exactly the specified value
    optional bytes const = 1;

    // MinLen specifies that this field must be the specified number of bytes
    // at a minimum
    optional uint64 min_length = 2;

    // MaxLen specifies that this field must be the specified number of bytes
    // at a maximum
    optional uint64 max_length = 3;

    // Prefix specifies that this field must have the specified bytes at the
    // beginning of the string.
    optional bytes  prefix   = 5;

    // Suffix specifies that this field must have the specified bytes at the
    // end of the string.
    optional bytes  suffix   = 6;

    // Contains specifies that this field must have the specified bytes
    // anywhere in the string.
    optional bytes  contains = 7;

    // In specifies that this field must be equal to one of the specified
    // values
    repeated bytes in     = 8;

    // NotIn specifies that this field cannot be equal to one of the specified
    // values
    repeated bytes not_in = 9;

    // Whether to enable this field, if not, the generated Model will not carry this field
    optional bool enable = 10;

    oneof default_config {
        // The default value corresponding to the field, if not set,
        // the default value is the default value of the corresponding type of the field
        bytes default = 11;
        // The default value factory function corresponding to the field, supports template variables,
        // such as `p2p@import|uuid|uuid4`
        string  default_factory = 12;
        // Set field required[Will be deprecated after version 1.0.0]
        bool miss_default = 13;
        // Set field required
        bool required = 26;
        // Similar meaning to `default`, but using template variables, such as `p2p@import|uuid|uuid4`
        string default_template = 36;
    }
    // Set the alias of the field in the pydantic.Base Model
    optional string alias = 14;
    // Set the description of the field
    optional string description = 15;
    // Corresponding multiple validation of the set value
    optional float multiple_of = 16;
    oneof example_config {
        // Set the corresponding sample value
        bytes example = 17;
        // Set the corresponding sample value factory function, support template variables
        string example_factory = 18;
    }
    // Set the Field object corresponding to the field, support template variables
    optional string field = 19;
    // Set the type object corresponding to the field, support template variables
    optional string type = 20;

    // WellKnown rules provide advanced constraints against common byte
    // patterns
    oneof well_known {
        // Ip specifies that the field must be a valid IP (v4 or v6) address in
        // byte format
        bool ip   = 21;

        // Ipv4 specifies that the field must be a valid IPv4 address in byte
        // format
        bool ipv4 = 22;

        // Ipv6 specifies that the field must be a valid IPv6 address in byte
        // format
        bool ipv6 = 23;
    }
    // The title corresponding to the field
    optional string title = 24;
    // Field's custom extension parameter in the format Json
    optional string extra = 25;
}

// EnumRules describe the constraints applied to enum values
message EnumRules {
    // Const specifies that this field must be exactly the specified value
    optional int32 const        = 1;

    // In specifies that this field must be equal to one of the specified
    // values
    repeated int32 in           = 3;

    // NotIn specifies that this field cannot be equal to one of the specified
    // values
    repeated int32 not_in       = 4;
    // Whether to enable this field, if not, the generated Model will not carry this field
    optional bool enable = 8;

    oneof default_config {
        // The default value corresponding to the field, if not set,
        // the default value is the default value of the corresponding type of the field
        int32 default = 9;
        // The default value factory function corresponding to the field, supports template variables,
        // such as `p2p@import|uuid|uuid4`
        string  default_factory = 10;
        // Set field required[Will be deprecated after version 1.0.0]
        bool miss_default = 11;
        // Set field required
        bool required = 21;
        // Similar meaning to `default`, but using template variables, such as `p2p@import|uuid|uuid4`
        string default_template = 22;
    }
    // Set the alias of the field in the pydantic.Base Model
    optional string alias = 12;
    // Set the description of the field
    optional string description = 13;
    oneof example_config {
        // Set the corresponding sample value
        int32 example = 15;
        // Set the corresponding sample value factory function, support template variables
        string example_factory = 16;
    }
    // Set the Field object corresponding to the field, support template variables
    optional string field = 17;
    // The title corresponding to the field
    optional string title = 18;
    // Field's custom extension parameter in the format Json
    optional string extra = 20;
}

// MessageRules describe the constraints applied to embedded message values.
// For message-type fields, validation is performed recursively.
message MessageRules {
    // Skip specifies that the validation rules of this field should not be
    // evaluated
    optional bool skip     = 1;


    // Whether to enable this field, if not, the generated Model will not carry this field
    optional bool enable = 8;

    oneof default_config {
        // The default value corresponding to the field, if not set,
        // the default value is the default value of the corresponding type of the field
        string  default = 9;
        // The default value factory function corresponding to the field, supports template variables,
        // such as `p2p@import|uuid|uuid4`
        string  default_factory = 10;
        // Set field required[Will be deprecated after version 1.0.0]
        bool miss_default = 11;
        // Set field required
        bool required = 2;
        // Similar meaning to `default`, but using template variables, such as `p2p@import|uuid|uuid4`
        string default_template = 22;
    }
    // Set the alias of the field in the pydantic.Base Model
    optional string alias = 12;
    // Set the description of the field
    optional string description = 13;
    oneof example_config {
        // Set the corresponding sample value
        float example = 15;
        // Set the corresponding sample value factory function, support template variables
        string example_factory = 16;
    }
    // Set the Field object corresponding to the field, support template variables
    optional string field = 17;
    // Set the type object corresponding to the field, support template variables
    optional string type = 18;
    // The title corresponding to the field
    optional string title = 19;
    // Field's custom extension parameter in the format Json
    optional string extra = 20;
}

// RepeatedRules describe the constraints applied to `repeated` values
message RepeatedRules {
    // MinItems specifies that this field must have the specified number of
    // items at a minimum
    optional uint64 min_items = 1;

    // MaxItems specifies that this field must have the specified number of
    // items at a maximum
    optional uint64 max_items = 2;

    // Unique specifies that all elements in this field must be unique. This
    // contraint is only applicable to scalar and enum types (messages are not
    // supported).
    optional bool   unique    = 3;

    // Items specifies the contraints to be applied to each item in the field.
    // Repeated message fields will still execute validation against each item
    // unless skip is specified here.
    optional FieldRules items = 4;

    // Whether to enable this field, if not, the generated Model will not carry this field
    optional bool enable = 8;

    oneof default_config {
        // The default value factory function corresponding to the field, supports template variables,
        // such as `p2p@import|uuid|uuid4`
        string  default_factory = 10;
        // Set field required[Will be deprecated after version 1.0.0]
        bool miss_default = 11;
        // Set field required
        bool required = 21;
        // Similar meaning to `default`, but using template variables, such as `p2p@import|uuid|uuid4`
        string default_template = 22;
    }
    // Set the alias of the field in the pydantic.Base Model
    optional string alias = 12;
    // Set the description of the field
    optional string description = 13;
    oneof example_config {
        // Set the corresponding sample value factory function, support template variables
        string example_factory = 16;
    }
    // Set the Field object corresponding to the field, support template variables
    optional string field = 17;
    // Set the type object corresponding to the field, support template variables
    optional string type = 18;
    // The title corresponding to the field
    optional string title = 19;
    // Field's custom extension parameter in the format Json
    optional string extra = 20;
}

// MapRules describe the constraints applied to `map` values
message MapRules {
    // MinPairs specifies that this field must have the specified number of
    // KVs at a minimum
    optional uint64 min_pairs = 1;

    // MaxPairs specifies that this field must have the specified number of
    // KVs at a maximum
    optional uint64 max_pairs = 2;

    // Keys specifies the constraints to be applied to each key in the field.
    optional FieldRules keys   = 4;

    // Values specifies the constraints to be applied to the value of each key
    // in the field. Message values will still have their validations evaluated
    // unless skip is specified here.
    optional FieldRules values = 5;

    // Whether to enable this field, if not, the generated Model will not carry this field
    optional bool enable = 8;

    oneof default_config {
        // The default value factory function corresponding to the field, supports template variables,
        // such as `p2p@import|uuid|uuid4`
        string  default_factory = 10;
        // Set field required[Will be deprecated after version 1.0.0]
        bool miss_default = 11;
        // Set field required
        bool required = 21;
        // Similar meaning to `default`, but using template variables, such as `p2p@import|uuid|uuid4`
        string default_template = 22;
    }
    // Set the alias of the field in the pydantic.Base Model
    optional string alias = 12;
    // Set the description of the field
    optional string description = 13;
    oneof example_config {
        // Set the corresponding sample value factory function, support template variables
        string example_factory = 16;
    }
    // Set the Field object corresponding to the field, support template variables
    optional string field = 17;
    // Set the type object corresponding to the field, support template variables
    optional string type = 18;
    // The title corresponding to the field
    optional string title = 19;
    // Field's custom extension parameter in the format Json
    optional string extra = 20;
}

// AnyRules describe constraints applied exclusively to the
// `google.protobuf.Any` well-known type
message AnyRules {

    // In specifies that this field's `type_url` must be equal to one of the
    // specified values.
    repeated string in     = 2;

    // NotIn specifies that this field's `type_url` must not be equal to any of
    // the specified values.
    repeated string not_in = 3;
    // Whether to enable this field, if not, the generated Model will not carry this field
    optional bool enable = 8;
    oneof default_config {
        // The default value corresponding to the field, if not set,
        // the default value is the default value of the corresponding type of the field
        string default = 9;
        // The default value factory function corresponding to the field, supports template variables,
        // such as `p2p@import|uuid|uuid4`
        string  default_factory = 10;
        // Set field required[Will be deprecated after version 1.0.0]
        bool miss_default = 11;
        // Set field required
        bool required = 1;
        // Similar meaning to `default`, but using template variables, such as `p2p@import|uuid|uuid4`
        string default_template = 22;
    }
    // Set the alias of the field in the pydantic.Base Model
    optional string alias = 12;
    // Set the description of the field
    optional string description = 13;
    oneof example_config {
        // Set the corresponding sample value
        string example = 14;
        // Set the corresponding sample value factory function, support template variables
        string example_factory = 15;
    }
    // Set the Field object corresponding to the field, support template variables
    optional string field = 16;
    // The title corresponding to the field
    optional string title = 17;
    // Field's custom extension parameter in the format Json
    optional string extra = 20;
}

// DurationRules describe the constraints applied exclusively to the
// `google.protobuf.Duration` well-known type
message DurationRules {
    // Const specifies that this field must be exactly the specified value
    optional google.protobuf.Duration const = 2;

    // Lt specifies that this field must be less than the specified value,
    // exclusive
    optional google.protobuf.Duration lt = 3;

    // Lt specifies that this field must be less than the specified value,
    // inclusive
    optional google.protobuf.Duration le = 4;

    // Gt specifies that this field must be greater than the specified value,
    // exclusive
    optional google.protobuf.Duration gt = 5;

    // Gte specifies that this field must be greater than the specified value,
    // inclusive
    optional google.protobuf.Duration ge = 6;

    // In specifies that this field must be equal to one of the specified
    // values
    repeated google.protobuf.Duration in = 7;

    // NotIn specifies that this field cannot be equal to one of the specified
    // values
    repeated google.protobuf.Duration not_in = 8;
    // Whether to enable this field, if not, the generated Model will not carry this field
    optional bool enable = 14;

    oneof default_config {
        // The default value corresponding to the field, if not set,
        // the default value is the default value of the corresponding type of the field
        google.protobuf.Duration default = 9;
        // The default value factory function corresponding to the field, supports template variables,
        // such as `p2p@import|uuid|uuid4`
        string  default_factory = 10;
        // Set field required[Will be deprecated after version 1.0.0]
        bool miss_default = 11;
        // Set field required
        bool required = 1;
        // Similar meaning to `default`, but using template variables, such as `p2p@import|uuid|uuid4`
        string default_template = 22;
    }
    // Set the alias of the field in the pydantic.Base Model
    optional string alias = 12;
    // Set the description of the field
    optional string description = 13;
    oneof example_config {
        // Set the corresponding sample value
        google.protobuf.Duration example = 15;
        // Set the corresponding sample value factory function, support template variables
        string example_factory = 16;
    }
    // Set the Field object corresponding to the field, support template variables
    optional string field = 17;
    // Set the type object corresponding to the field, support template variables
    optional string type = 18;
    // The title corresponding to the field
    optional string title = 19;
    // Field's custom extension parameter in the format Json
    optional string extra = 20;
}

// TimestampRules describe the constraints applied exclusively to the
// `google.protobuf.Timestamp` well-known type
message TimestampRules {
    // Const specifies that this field must be exactly the specified value
    optional google.protobuf.Timestamp const = 2;

    // Lt specifies that this field must be less than the specified value,
    // exclusive
    optional google.protobuf.Timestamp lt = 3;

    // Lte specifies that this field must be less than the specified value,
    // inclusive
    optional google.protobuf.Timestamp le = 4;

    // Gt specifies that this field must be greater than the specified value,
    // exclusive
    optional google.protobuf.Timestamp gt = 5;

    // Gte specifies that this field must be greater than the specified value,
    // inclusive
    optional google.protobuf.Timestamp ge = 6;

    // LtNow specifies that this must be less than the current time. LtNow
    // can only be used with the Within rule.
    optional bool lt_now  = 7;

    // GtNow specifies that this must be greater than the current time. GtNow
    // can only be used with the Within rule.
    optional bool gt_now  = 8;

    // Within specifies that this field must be within this duration of the
    // current time. This constraint can be used alone or with the LtNow and
    // GtNow rules.
    optional google.protobuf.Duration within = 9;

    // Whether to enable this field, if not, the generated Model will not carry this field
    optional bool enable = 10;

    oneof default_config {
        // The default value corresponding to the field, if not set,
        // the default value is the default value of the corresponding type of the field
        google.protobuf.Timestamp default = 11;
        // The default value factory function corresponding to the field, supports template variables,
        // such as `p2p@import|uuid|uuid4`
        string  default_factory = 12;
        // Set field required[Will be deprecated after version 1.0.0]
        bool miss_default = 13;
        // Set field required
        bool required = 1;
        // Similar meaning to `default`, but using template variables, such as `p2p@import|uuid|uuid4`
        string default_template = 22;
    }
    // Set the alias of the field in the pydantic.Base Model
    optional string alias = 14;
    // Set the description of the field
    optional string description = 15;
    oneof example_config {
        // Set the corresponding sample value
        google.protobuf.Timestamp example = 16;
        // Set the corresponding sample value factory function, support template variables
        string example_factory = 17;
    }
    // Set the Field object corresponding to the field, support template variables
    optional string field = 18;
    // Set the type object corresponding to the field, support template variables
    optional string type = 19;
    // The title corresponding to the field
    optional string title = 20;
    // Field's custom extension parameter in the format Json
    optional string extra = 21;
}
```
