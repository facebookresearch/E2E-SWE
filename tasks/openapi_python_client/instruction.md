# pyclientgen

Build `pyclientgen`, a command-line tool that reads an **OpenAPI 3.0 / 3.1**
document and generates a complete, ready-to-use **Python HTTP client package** for
that API. The generated package contains typed model classes for every schema, one
callable function per API operation (built on `httpx`), and a small runtime support
layer.

Your project must install a console-script entry point named **`pyclientgen`** (so
that, after `pip install -e .`, running `pyclientgen` on the command line works).

The generated client code imports **`httpx`** (HTTP transport) and uses
value-equality data classes for models. The generator must read both JSON and YAML documents.

## Dependencies

The environment is **fully offline** — there is no network access, and you **must not install
anything** (no `pip install`, no downloads). All dependencies you need are **already installed**;
just `import` them. The project is installed by a `setup.sh` that also runs offline (see *setup.sh*
below). Available runtime libraries include:

- **`httpx`** — HTTP transport used by the generated client code.
- **`attrs`** — convenient value-equality data classes (the standard-library `dataclasses` module
  is also available if you prefer it for the models).
- **`ruamel.yaml`** — a YAML parser/loader, for reading YAML OpenAPI documents (JSON documents are
  read with the standard-library `json` module). `pyyaml` is **not** installed; use `ruamel.yaml`.
- **`pydantic`**, **`jinja2`**, **`typer`** (with `shellingham`), and **`ruff`** — also installed and
  available should your generator implementation make use of templating, structured parsing, a CLI
  framework, or a code formatter.

Declare these as your project's runtime dependencies in your packaging metadata as appropriate;
they are already present in the environment, so `setup.sh` will not need to fetch them.

## Command line

```
pyclientgen generate [OPTIONS]
```

Options:

- `--path PATH` — read the OpenAPI document from a local file.
- `--url URL` — read it from a URL. Exactly one of `--path` / `--url` is required;
  giving both, or neither, is an error (non-zero exit).
- `--output-path PATH` — where to write the generated code (see *Output layout*).
- `--meta {none,poetry,setup,pdm,uv}` — what project metadata to emit (default
  `poetry`).
- `--config PATH` — a JSON or YAML configuration file (see *Configuration*).
- `--overwrite` — overwrite an existing output directory (otherwise an existing
  directory is an error).
- `--fail-on-warning` — exit non-zero if any warning was produced (by default
  warnings do not change the exit code).

A `.json` source is parsed as JSON; anything else is parsed as YAML.

## Output layout

The generated package and project names are derived from the document's
`info.title`:

- **project name** = kebab-case(title) + `-client` (e.g. title `My Cool API` →
  `my-cool-api-client`).
- **package name** = the project name with `-` replaced by `_` (e.g.
  `my_cool_api_client`). This is the importable Python package.

Where files land depends on `--meta` and `--output-path`:

- With `--meta none`: only the importable package is emitted (no project metadata).
  If `--output-path P` is given, the package's contents are written directly into
  `P`; otherwise they are written into `./<package_name>`.
- With any other `--meta`: a **project directory** is emitted (named `<project>` by
  default, or `--output-path` if given) containing project metadata plus the
  package in a `<package_name>/` subdirectory.

The package contains:

- `<package>/__init__.py`
- `<package>/types.py` — shared runtime types (below).
- `<package>/client.py` — `Client` and `AuthenticatedClient`.
- `<package>/errors.py` — `UnexpectedStatus`.
- `<package>/models/__init__.py` and one module per schema. Each schema module is
  named in snake_case and defines a class named in PascalCase; `models/__init__.py`
  re-exports every model/enum class.
- `<package>/api/__init__.py`, and for each tag a package `<package>/api/<tag>/`
  with one module per operation. The operation module is named after the
  operation's `operationId` in snake_case. Operations without a tag go under the tag
  `default`.

### Naming

- A schema's class name is the PascalCase of its `components/schemas` key; its
  module is the snake_case of that name. This class-naming rule applies to **object**
  and **enum** schemas — the ones that become a generated class. A `oneOf`/`anyOf`/
  multi-type (union) schema does **not** become its own generated class referenced by
  name (see *Unions*).
- An **inline** schema (an object/enum defined directly under a property rather than
  referenced) is named after its owning class followed by the PascalCase of the
  property name — e.g. property `inlineEnumProp` of `MyModel` → class
  `MyModelInlineEnumProp`.
- An **inline request-body** schema (defined directly under
  `requestBody.content.<media>.schema` rather than referenced) becomes a model class
  named after the operation's `operationId` in PascalCase with a `Body` suffix — e.g.
  operation `operationId: uploadThing` → class `UploadThingBody`, module
  `upload_thing_body`.
- A model **attribute** name is the snake_case of the JSON property name, while the
  original JSON name is preserved for serialization (so `stringProp` ⇄ attribute
  `string_prop`). An operation parameter keyword is the snake_case of the parameter
  name.

## `types.py`

- `Unset` — a class whose instances are falsy; `UNSET` is its singleton instance,
  used as the default for every optional value (meaning "not provided").
- `File` — a value class constructed as
  `File(payload=<binary stream>, file_name=<str|None>, mime_type=<str|None>)`, with a
  method `to_tuple()` returning `(file_name, payload, mime_type)`.
- `Response` — a generic class with attributes `status_code`, `content`, `headers`,
  `parsed`.

## Models

Each object schema becomes a data class supporting **value-based equality** with:

- A constructor taking the properties. **Required** properties have no default;
  **optional** properties default to `UNSET`. Additional/free-form properties (see
  below) are *not* constructor parameters.
- `to_dict() -> dict` — serialize to a JSON-ready dict, using the original JSON
  property names. Optional properties whose value is `UNSET` are omitted.
- `from_dict(data: Mapping) -> Model` (classmethod) — parse a JSON dict. A missing
  **required** property raises `KeyError`. A non-mapping argument raises.

Each property is declared as a **class-level attribute annotation** on the model
class (i.e. `attr_name: <annotation>` in the class body, as attrs/dataclass models
do), so every property is discoverable in the class's `__annotations__` — not carried
only on the `__init__` signature. Model attribute **annotations are strings** (PEP 563
/ `from __future__ import annotations`). For an optional property the annotation is
`<type> | Unset`; for a required property it is just `<type>`. (The order of members in
a union annotation is not significant.)

### Property types

| Schema | Python type (annotation) | Decode/encode |
|--------|--------------------------|---------------|
| `boolean` | `bool` | as-is |
| `string` | `str` | as-is |
| `integer` | `int` | as-is |
| `number` | `float` | as-is |
| `"null"` | `None` | as-is |
| empty schema `{}` | `Any` | as-is |
| `string`,`format: date` | `datetime.date` | ISO 8601 string ⇄ `date` |
| `string`,`format: date-time` | `datetime.datetime` | ISO 8601 string ⇄ `datetime` |
| `string`,`format: uuid` | `UUID` | string ⇄ `uuid.UUID` |
| `string`, unknown format | `str` | as-is (unknown formats fall back to string) |
| `$ref` to an object schema | that class | nested `to_dict`/`from_dict` |
| `array` with `items: S` | `list[<S>]` | element-wise |
| `array` with `items: {}` | `list[Any]` | as-is |

`$ref` chains (a schema that is only `{$ref: ...}` pointing at another, etc.) resolve
to the final concrete schema. `allOf` **merges** the listed schemas' properties into
one class (so an `allOf` of a base object plus extra properties yields a class with
all of them).

An `array` with `prefixItems` (with or without `items`) is decoded as a `list` whose
element annotation is the **union of all the prefix/item element types**, e.g.
`prefixItems: [ObjA, string]` → `list[ObjA | str]`.

### Additional properties

Unless a schema sets `additionalProperties: false`, a model also accepts unknown
keys, stored in an `additional_properties` dict (parsed per the
`additionalProperties` schema if one is given, otherwise kept as-is). It is **not** a
constructor parameter. Models expose a mapping-style interface over it:
`instance[key]`, `instance[key] = value`, `key in instance`, and an
`additional_keys` property. `to_dict` includes these entries; `from_dict` routes
unknown keys into it.

### Docstrings

Docstrings use Google style (sections introduced by a `Header:` line, each entry on
its own line, sections separated by a blank line).

A model's docstring starts with the schema's `description` (if any), followed by an
`Attributes:` section with one line per property formatted `name (type): description`.
When a property has no description the line ends right after the colon
(`name (type):`) — the colon is always present, and the `type` is the same string
annotation used for the attribute.

An endpoint function's docstring starts with the operation's `description`, then:

- an `Args:` section with one `name (type): description` line **per OpenAPI parameter
  and for the request `body`**. The `client` argument is **not** listed. A parameter
  with no description ends right after the colon (`name (type):`).
- a `Returns:` section. For `sync` / `asyncio` it names the **parsed success type**
  (e.g. `GoodResponse`, or `GoodResponse | ErrorResponse` when several status codes
  are documented); the `*_detailed` variants instead name `Response[...]`.

## Enums and consts

A `string`/`integer` schema with an `enum` becomes an enum class whose **values** are
the enum values: `MyEnum(value)` returns the member, and an unknown value raises
`ValueError`. The model attribute holds an enum member; `to_dict` writes its value.

Member **names** are derived as follows:

- **String enums:** if the value is a valid Python identifier it is upper-cased
  (`"a"` → `A`, `"B"` → `B`, `"a23"` → `A23`); otherwise the member is named
  `VALUE_<i>` where `i` is the value's zero-based position in the `enum` list
  (`"123"` at index 3 → `VALUE_3`, `""` at index 6 → `VALUE_6`). Other non-identifier
  characters (spaces, symbols) become underscores and the result is upper-cased
  (`"a Thing WIth spaces"` → `A_THING_WITH_SPACES`).
- **Integer enums:** a value `n` is named `VALUE_<n>`, and a negative value `-n` is
  named `VALUE_NEGATIVE_<n>` (`2` → `VALUE_2`, `-4` → `VALUE_NEGATIVE_4`).
- **`x-enum-varnames`:** if present, this list supplies the member names. Each varname
  is run through the **same snake_case word-splitting used elsewhere** (split on
  whitespace and non-identifier characters **and** on lowercase→uppercase / acronym
  case boundaries), the resulting words are joined with single underscores, and the
  whole thing is upper-cased — so `"One"` → `ONE`, `"More than OnE"` →
  `MORE_THAN_ON_E` (the `On|E` case boundary adds an underscore), `"not_quite_four"` →
  `NOT_QUITE_FOUR`, and `"Negative Four"` → `NEGATIVE_FOUR`.

A schema combining an enum with `"null"` (via `oneOf` with `type: "null"`, or a type
list including `"null"`) makes the property nullable: annotation `<Enum> | None`,
accepting and round-tripping `None`. An enum of only `[null]` is just `None`.

A property with a `const` value is fixed to that value: `from_dict` accepts the const
value and rejects anything else with `ValueError`.

### `literal_enums` mode

When the configuration sets `literal_enums: true`, enums are generated as
`typing.Literal[...]` **type aliases** instead of enum classes (so the generated
`MyEnum` equals `Literal[<values...>]`), and the model attribute holds the raw value.
An invalid value passed to `from_dict` raises `TypeError` (rather than `ValueError`).

## Unions

`oneOf`, `anyOf`, and multi-type schemas (`type: ["string", "integer"]`) become a
union. The annotation is the union of the member type spellings (plus `None` if
nullable, plus `Unset` if optional). A union schema is **inlined as this member union
wherever it is referenced**, including through a `$ref` (or an `allOf` wrapper): a
`$ref` that resolves to a `oneOf`/`anyOf`/multi-type schema is expanded into the union
of its member type spellings at the reference site — it is **not** referenced by the
union schema's own generated name. For example, a top-level union schema
`ThingAOrB: {oneOf: [$ref ThingA, $ref ThingB]}` referenced by a property
`thing: {$ref: ThingAOrB}` yields the annotation `ThingA | ThingB` (plus `| Unset` if
`thing` is optional), never `ThingAOrB`. On decode, the matching member is chosen:
objects are disambiguated by their **required properties**, an object is told apart
from a scalar by the JSON value's shape, and nested unions are flattened. On encode,
the concrete value's type selects how it is serialized.

## Defaults

A property's `default` becomes the attribute's default value, converted to the
property's Python type, so a model constructed with no arguments carries those
defaults. Conversions include: `date`/`date-time`/`uuid` strings parsed to their
objects; a numeric string default for an `integer`/`number` parsed to `int`/`float`
(`"4"` → `4`, `"5.5"` → `5.5`); a string default for a `boolean` (`"True"`/`"true"` →
`True`, `"False"`/`"false"` → `False`). An enum default may be given via an `allOf`
wrapper around the enum `$ref`.

## Client

`<package>.client` defines `Client` and `AuthenticatedClient` (value classes):

- Both take `base_url` and an optional keyword `raise_on_unexpected_status`
  (default `False`). `AuthenticatedClient` additionally takes `token`, and optional
  `prefix` (default `"Bearer"`) and `auth_header_name` (default `"Authorization"`).
- `set_httpx_client(httpx_client)` installs an explicit `httpx.Client`;
  `get_httpx_client()` returns it, constructing one from the stored settings if none
  was set. (`AuthenticatedClient.get_httpx_client()` adds the header
  `auth_header_name: "<prefix> <token>"`.) The matching
  `set_async_httpx_client(async_client)` / `get_async_httpx_client()` manage an
  `httpx.AsyncClient` the same way, for the async endpoint functions.
- `with_headers(mapping)` returns a **new** client like this one but with the given
  headers merged in. (Equivalent `with_cookies` / `with_timeout` also exist.)

## Endpoints

Each operation module defines four functions, all keyword-only, taking `client=`
plus the operation's parameters and (if there is a request body) `body=`:

- `sync_detailed(...) -> Response[...]` — make the request and return a full
  `Response` (`status_code` as an `http.HTTPStatus`, `content`, `headers`, and
  `parsed`).
- `sync(...)` — return just `Response.parsed`.
- `asyncio_detailed(...)` / `asyncio(...)` — the async equivalents.

Request building:

- The URL is the path template with `{param}` placeholders replaced by the path
  arguments, **percent-encoding** characters that are not allowed unescaped in a path
  segment (`/` → `%2F`, space → `%20`, `#` → `%23`, `?` → `%3F`, `&` → `%26`, etc.).
- Query parameters go in a `params` dict (an enum value is serialized to its value;
  an array value is passed through as a `list` so the key repeats; optional
  parameters left unset are omitted).
- A request body is sent according to its media type: `application/json` →
  `json=body.to_dict()`; `multipart/form-data` → `files=body.to_multipart()` (a list
  of `(field-name, file-tuple)` pairs, where a binary `File` property contributes its
  `to_tuple()` and scalar fields contribute `(None, <bytes>, "text/plain")`);
  `application/x-www-form-urlencoded` → `data=body.to_dict()`;
  `application/octet-stream` → `content=<bytes>`.
- When there is a request body, the request also carries a `Content-Type` request
  header equal to the body's media type (e.g. `application/x-www-form-urlencoded`, or a
  `multipart/form-data` value for a multipart body).
- The request is issued via `client.get_httpx_client().request(method=..., url=...,
  ...)`; the async functions instead await
  `client.get_async_httpx_client().request(...)`.

Response handling: for each **documented** status code the body is parsed to the
declared type (a model via `from_dict`, a `list` of such, etc.) and returned as
`Response.parsed`. For an **undocumented** status code, `parsed` is `None`, unless the
client was created with `raise_on_unexpected_status=True`, in which case
`errors.UnexpectedStatus` is raised.

## Configuration file

`--config` accepts JSON or YAML with these keys (all optional):

- `post_hooks` — a list of shell commands run in the output directory after
  generation (e.g. a code formatter). An **empty list disables** post-processing. A
  command that is not found produces a warning, not a failure.
- `literal_enums` — boolean (see *literal_enums mode*).
- `class_overrides` — a map from a schema's generated class name to
  `{class_name, module_name}`, renaming both the class and its module.
- `field_prefix` — a string (default `"field_"`) prepended to property names that are
  not valid Python identifiers (e.g. those starting with a digit or underscore), to
  form the attribute name.

(Other passthrough options such as `project_name_override`, `package_name_override`,
and `package_version_override` may also be supported but are not required here.)

## Project metadata (`--meta`)

- `poetry` (default): emit a `pyproject.toml` (with the project `name`, a `version`
  taken from the document's `info.version`, and the runtime dependencies), a
  `README.md`, a `.gitignore`, and the package in its subdirectory.
- `setup`: as `poetry` plus a `setup.py`.
- `pdm` / `uv`: `pyproject.toml` variants.
- `none`: emit only the package (no project metadata).

## Diagnostics

- A schema the generator cannot process is reported as a **warning** on the
  generator's output (stdout/stderr) that **names the schema** (by its name, e.g. in a
  `/components/schemas/<Name>` reference); that schema is omitted from the output, the
  rest of the client is still generated, and the command exits **0** (unless
  `--fail-on-warning` is given, which makes it exit non-zero). Schemas treated as
  unprocessable include an `enum` whose values are not all of one type (e.g. mixing a
  string and an integer) and an `array` schema with neither `items` nor `prefixItems`.
- A **circular** `$ref` chain reached through a property is detected and reported
  (the message contains `Circular`); the affected schema is dropped and generation
  still completes (exit 0).
- The following are **fatal** (non-zero exit) with a message containing the quoted
  text: invalid JSON in a `.json` source → `Invalid JSON`; invalid YAML →
  `Invalid YAML`; a document that is not a valid OpenAPI document or is missing a
  required field (`openapi`, `info.title`, `info.version`, or `paths`) →
  `Failed to parse OpenAPI document`; a Swagger/OpenAPI 2.0 document → a message
  mentioning `Swagger`.

## setup.sh

Write a `setup.sh` that installs your package so the `pyclientgen` command is
available. The environment is offline and the build backend is pre-installed, so install
**without** build isolation:

```bash
pip install -e . --no-build-isolation
```
