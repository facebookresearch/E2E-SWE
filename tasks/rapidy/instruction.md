# rapidy

Build **rAPIdy**, an asynchronous Python web framework. It uses **aiohttp** as the
HTTP transport/server layer and **pydantic v2** as the validation engine, giving
FastAPI-like ergonomics on top of aiohttp-native routing. Distribution name `rAPIdy`,
import name `rapidy`.

## Project Setup

The environment is **offline**: there is no network access and all runtime dependencies are
**already installed**. Do **not** install anything (no `pip install` of dependencies, no network
fetches) — installing is impossible and unnecessary.

The runtime dependencies provided in the environment are `aiohttp`, `pydantic` (**v2**), and
`dishka` (dependency injection). The package build backend is also pre-installed.

Create a `setup.sh` at the repository root (this file is sourced by `tests/test.sh`) that installs
**only your project** offline, against the pre-installed dependencies:

    #!/bin/bash
    pip install -e . --no-build-isolation

Declare the package so that this install exposes the import name `rapidy`. `--no-build-isolation`
is required because the environment is offline and the build backend is already present.
`rapidy.__version__` is "1.1.2".

The application class is exported as `Rapidy` from the top-level package
(`from rapidy import Rapidy`) and is a subclass of aiohttp's `web.Application`. The
module `rapidy.web` re-exports aiohttp's `web` surface (e.g. `web.Application`,
`web.Response`, `web.View`, `web.get`, `web.post`, `web.middleware`) extended with
rapidy behavior, so `from rapidy import web` works as an aiohttp-compatible namespace.
Within `rapidy.web`, `web.Application` **is** the rapidy application class — it is the
same object as `Rapidy` (not aiohttp's bare `Application`). It therefore accepts the
full rapidy application pipeline, including `http_route_handlers=[...]`, `di_providers`,
and `middlewares`, exactly as `Rapidy` does.
Handlers registered through this aiohttp-style surface — `web.get(path, handler)` /
`web.post(path, handler)` added via `app.add_routes([...])` — run the **same** rapidy
parameter-extraction, validation-error, and response-serialization pipeline as the
standalone decorators. The `web` namespace is rapidy-behavior-extended, not a plain
aiohttp passthrough.

## Public API surface

`rapidy.http` is the primary import hub and re-exports: the parameter classes; the
routing decorators and router; request/response types (`Request`, `Response`,
`StreamResponse`); middleware helpers; the enums (`ContentType`, `Charset`,
`HeaderName`); and the full set of aiohttp-style HTTP exception classes
(`HTTPBadRequest`, `HTTPNotFound`, ... following aiohttp's standard naming). The
`jsonify` encoder lives in `rapidy.encoders`. Enums live in `rapidy.enums`.

`rapidy.enums.ContentType` is a string-enum of standard MIME types, with members
named by type (e.g. `json`, `text_plain`). It subclasses `str` so a member
compares/serializes as its value, and it includes a wildcard member for `*/*`.

## 1. Request parameters

A handler declares where each argument comes from using **parameter marker classes**.
A marker may be attached either as `Annotated[T, Marker(...)]` or as the parameter's
default value (`arg: T = Marker(...)`). Both styles are equivalent.

Every marker forwards the standard pydantic `Field` constraint/metadata keyword
arguments (`alias`, `default`, `default_factory`, `ge`, `gt`, `le`, `lt`,
`min_length`, `max_length`, `pattern`, `strict`, ...). These constraints participate
in validation exactly as pydantic fields.

Markers come in **singular** and **plural** variants per source:

| Source | Singular (one named value) | Plural (whole source -> one model) |
|---|---|---|
| URL path | `PathParam` | `PathParams` |
| Query string | `QueryParam` | `QueryParams` |
| Header | `Header` | `Headers` |
| Cookie | `Cookie` | `Cookies` |
| Body | `Body` (no plural) | |

- **Singular** markers extract a single value identified by the parameter name (or by
  `alias` if given) and validate/coerce it to the annotated type `T`.
- **Plural** markers bind the *entire* source (all query params / all headers / etc.)
  into a single pydantic `BaseModel` given as the annotated type. Model field
  defaults apply.
- A singular marker with a Python default value (or a `default`/`default_factory`)
  is optional; when the value is absent the default is used.

A handler may also receive the raw request directly: rapidy passes the aiohttp
`web.Request` to the handler's **first parameter** when that parameter has no type
annotation or is annotated as `web.Request` (i.e. it carries no parameter marker).
All other parameters use markers as described above.

### Body and content-type enforcement

`Body(...)` reads the request body. It additionally accepts:
- `content_type` (default `ContentType.json`): the expected request `Content-Type`.
  When JSON, the body is parsed as JSON and validated against the annotated model.
  For form content types (`application/x-www-form-urlencoded`, `multipart/form-data`)
  the form fields are parsed and validated against the annotated model the same way.
  For text content types the raw decoded string is provided; for binary, bytes.
- `check_content_type` (default `True`): when true, a request whose `Content-Type`
  does not match `content_type` is rejected before the handler runs (see the error
  envelope below, located at `["body"]`). When false, the guard is skipped and the
  body is parsed regardless of the incoming `Content-Type`.

Content-type matching treats the wildcard forms (`*/*`, `type/*`, `*/subtype`) as
matching the corresponding family. `content_type` may be given as a `ContentType`
enum member or as a raw string (e.g. `content_type="text/*"`); both are parsed and
matched the same way.

## 2. Validation-error envelope

When request validation fails, rapidy responds with HTTP **422 Unprocessable Entity**
and a JSON body of this exact shape:

```json
{"errors": [ {error}, {error}, ... ]}
```

The top-level key is **`errors`** (a list). Each entry is a pydantic v2 error dict
(`type`, `loc`, `msg`, and `ctx` when the error carries context), with one rapidy
adaptation: the `loc` is **prefixed** so it reads `[<param_type>, <name>]`:

- `<param_type>` is the source string: `"path"`, `"query"`, `"header"`, `"cookie"`,
  or `"body"`.
- `<name>` is the parameter's resolved name — the `alias` when one is set, otherwise
  the field name. For whole-model (plural / body) params, the source string is prefixed
  onto pydantic's own error `loc`, so a failing model field reads
  `[<param_type>, <field>]` and a failure nested deeper in the model reads
  `[<param_type>, <field>, <subfield>, ...]`.

All failing sources in one request are collected into the single `errors` list. The
errors are ordered by **handler-signature source order** — the order in which each
source first appears across the handler's parameters (not alphabetically/sorted).
Within a single source, errors preserve pydantic's own ordering (model field
declaration order).

The pydantic `type`/`msg`/`ctx` values are pydantic v2's own (e.g.
`type="greater_than_equal"` with `ctx={"ge": 10}`; `type="missing"` /
`msg="Field required"` for a required value that is absent; `type="int_parsing"` for
a non-integer; `type="list_type"`). Do not invent these — they are produced by
pydantic.

A failure of the body content-type guard is reported as a single error located at
`["body"]` (its `type`/`msg` describe the content-type extraction failure).

## 3. Routing and registration

Routing uses **standalone decorators**, one per HTTP method:
`get`, `post`, `put`, `patch`, `delete`, `head`, `options` (in `rapidy.http`).

- `@get(path)` / `@post(path)` / ... wrap an async handler into a *route object*.
  Applying a method decorator to a non-async callable is an error raised at
  decoration time.
- Route objects are registered by passing them to the application:
  `Rapidy(http_route_handlers=[route1, route2, ...])`. The same iterable also accepts
  bare async functions, controllers, and routers.
- Each decorator also exposes a classmethod **`.reg(path, handler, **kwargs)`** that
  registers an undecorated async handler, equivalent to decorating it then adding it.

`controller(path)` is a **class decorator** for class-based grouping. Methods of the
class decorated with `@get(...)`/`@post(...)`/... become sub-routes whose paths are
**concatenated** onto the controller's base `path`. The class itself is passed to
`http_route_handlers`. Controller methods take `self`.

`HTTPRouter(prefix, route_handlers=[...])` groups route handlers under a path
**prefix** and is itself registered via `http_route_handlers=[router]`. The prefix
concatenates with each contained handler's path. `HTTPRouter` accepts the same kinds
of entries as `http_route_handlers` (decorated handlers and `.reg(...)` results).

Method decorators and the `controller` accept response-shaping keyword arguments
described next (e.g. `status_code`, `response_type`, `response_content_type`, the
pydantic dump flags like `response_by_alias`/`response_exclude_none`).

### Middleware

`web.middleware` (also re-exported via `rapidy.http`) marks a rapidy middleware: an
async function whose first two parameters are the incoming `request` and the
`call_next` callable. The middleware continues the chain by awaiting
`call_next(request)` — passing the request positionally — which returns the downstream
response (a `StreamResponse`) that the middleware returns, optionally after inspecting
or mutating it. Beyond those two,
a rapidy middleware's parameters undergo the **same** request-parameter extraction
and dependency injection as a handler — i.e. they may be annotated with the marker
classes (`Header(...)`, `QueryParam(...)`, `Body(...)`, ...) or with `FromDishka[T]`,
and those values are extracted/injected and passed to the middleware before it runs.
A failed extraction in a middleware parameter raises the same 422 validation envelope.
Middlewares are registered on the application via `middlewares=[...]`.

## 4. Response serialization

A handler's return value becomes an HTTP response with an automatic `Content-Type`
**driven by the runtime type of the returned value**:

- `dict` and pydantic `BaseModel` (and other structured/container values) serialize
  to JSON with `Content-Type: application/json`. A `BaseModel` is dumped to its field
  values.
- `str` (and other scalar values) serialize with `Content-Type: text/plain`.
- bytes serialize as a binary body (`application/octet-stream`).
- `None` produces an empty body.
- Returning an explicit `web.Response`/`StreamResponse` passes it through unchanged
  (its status, body, and content type are honored without re-serialization).

The handler's **return annotation** (and `response_type` below) drives
validation/casting of the return value, not the content-type selection — the
content-type follows the type of the value that is actually returned. Response
validation is on by default: when the annotation is a pydantic model, the return
value is validated and coerced through it (a conforming `dict` is built into the
model and then serialized), and a return value that does not conform to the
annotation is a response-validation failure — it is **not** serialized as a normal
success body. A response-validation failure is a server-side error and is reported
with HTTP **500 Internal Server Error** (not the 422 request-validation envelope of
Section 2).

Route keyword arguments override the defaults:
- `status_code` sets the default success status code.
- `response_type` overrides the return-annotation logic: the raw return value is cast
  through this type (e.g. a returned `dict` is validated/built into the given model)
  before serialization.
- `response_content_type` forces a specific response `Content-Type`.
- The `response_*` pydantic dump controls (e.g. `response_by_alias`,
  `response_exclude_none`) are forwarded into the serialization step.

## 5. `jsonify` encoder

`rapidy.encoders.jsonify(obj, *, ...)` converts any object into a JSON-encodable
structure, and when `dumps=True` into a JSON string. It takes pydantic-style keyword
controls — notably `by_alias` (default `True`), the `exclude_*` filters such as
`exclude_none`, `include`/`exclude`, a `custom_encoder`, and `dumps`.

Behavior:
- `BaseModel` and dataclass instances become dicts (recursing into nested values).
- Mappings and sequences are encoded element-wise.
- Non-JSON scalar types are converted to JSON-safe forms following the common
  convention, e.g. `Decimal` and `UUID` -> `str`; `datetime.date`/`datetime` ->
  ISO-8601 string; `bytes` -> decoded string; `Enum` -> its `.value`. Other common
  non-JSON scalars follow the usual convention.
- The pydantic-style controls behave as in pydantic: `by_alias` (default `True`) uses
  field aliases; `exclude_none`/`exclude_unset`/`exclude_defaults`/`include`/`exclude`
  filter fields; `custom_encoder` maps a type to an encoder callable.
- With `dumps=True`, the prepared structure is serialized to a JSON string via
  `dumps_encoder`.

This is the same encoder rapidy uses internally for JSON responses.

## 6. Dependency injection (dishka)

rapidy integrates the **dishka** DI library. The application accepts providers:
`Rapidy(di_providers=[Provider(), ...])` (or a pre-built container via
`di_container=...`). Handler (and controller-method, and middleware) parameters
annotated with **`FromDishka[T]`** are resolved from the container at **request
scope** and injected automatically, alongside rapidy's own request-parameter
extraction. The application exposes the built container as the `di_container`
attribute.

(Uses standard dishka providers at `Scope.REQUEST`.)
