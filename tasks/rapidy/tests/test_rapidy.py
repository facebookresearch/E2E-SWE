"""
Behavioral test suite for rAPIdy 1.1.2 (import name ``rapidy``).

rAPIdy is an async web framework: aiohttp transport + pydantic v2 validation,
with its own parameter-extraction taxonomy, validation-error envelope, decorator
routing model, response auto-serialization, a ``jsonify`` encoder, and dishka DI.

The suite is integration-first: it drives a real ``Rapidy`` / ``web.Application``
over HTTP via the ``pytest-aiohttp`` ``aiohttp_client`` fixture, exercising the
full request->validation->handler->response pipeline end to end, plus direct unit
tests of ``jsonify``. Assertions pin the documented contracts (the
``{"errors": [...]}`` 422 envelope, ``loc == [param_type, name]`` and its
cross-source ordering, content-type enforcement, registration model, response
pipeline + content-type mapping, DI/middleware wiring), not incidental surface
form.
"""

import datetime
from dataclasses import dataclass
from decimal import Decimal
from http import HTTPStatus
from typing import Any, List, Optional
from uuid import UUID
from typing_extensions import Annotated

import pytest
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# 1. Full request lifecycle (success) -- the deep integration path
# ---------------------------------------------------------------------------


async def test_full_request_lifecycle_success(aiohttp_client) -> None:
    """One request threading every extraction source + DI + middleware end to end.

    A single handler pulls a PathParam, a QueryParam, a Header (aliased), a Cookie
    (aliased), a nested-model JSON Body, and a ``FromDishka[...]`` dependency. It
    sits behind a ``@middleware`` that itself extracts a Header and receives an
    injected ``FromDishka[...]`` value, stashes a composed value on the request,
    awaits ``call_next(request)`` to obtain the downstream response, and adds a
    response header AFTER ``call_next`` returns.

    A valid request must thread all of these: the handler observes every
    extracted/coerced value and the injected dependency, the middleware-composed
    value reaches the handler, and the response carries the header the middleware
    set after ``call_next`` -- proving the response flows back through the chain.
    """
    from rapidy import Rapidy
    from rapidy.http import Body, Cookie, Header, PathParam, QueryParam, post
    from rapidy.web import middleware
    from dishka import FromDishka, Provider, provide, Scope

    class Config:
        def __init__(self, value: int) -> None:
            self.value = value

    class ConfigProvider(Provider):
        scope = Scope.REQUEST

        @provide
        async def config(self) -> Config:
            return Config(value=7)

    class Item(BaseModel):
        name: str
        qty: int

    @middleware
    async def compose_mw(
        request,
        call_next,
        trace: Annotated[str, Header(alias="X-Trace")],
        config: FromDishka[Config],
    ) -> Any:
        request["mw_trace"] = f"{trace}-{config.value}"
        response = await call_next(request)
        response.headers["X-Mw-After"] = "post"
        return response

    @post("/items/{uid}")
    async def handler(
        request,
        uid: Annotated[int, PathParam()],
        page: Annotated[int, QueryParam()],
        token: Annotated[str, Header(alias="X-Token")],
        sid: Annotated[str, Cookie(alias="sid")],
        item: Annotated[Item, Body()],
        config: FromDishka[Config],
    ) -> dict:
        return {
            "uid": uid,
            "page": page,
            "token": token,
            "sid": sid,
            "item": {"name": item.name, "qty": item.qty},
            "cfg": config.value,
            "mw_trace": request["mw_trace"],
            "types": [type(uid).__name__, type(page).__name__, type(item.qty).__name__],
        }

    app = Rapidy(
        http_route_handlers=[handler],
        middlewares=[compose_mw],
        di_providers=[ConfigProvider()],
    )
    client = await aiohttp_client(app)

    resp = await client.post(
        "/items/42",
        params={"page": "3"},
        headers={"X-Token": "tk", "X-Trace": "tr"},
        cookies={"sid": "abc"},
        json={"name": "bolt", "qty": 9},
    )
    assert resp.status == HTTPStatus.OK
    assert await resp.json() == {
        "uid": 42,
        "page": 3,
        "token": "tk",
        "sid": "abc",
        "item": {"name": "bolt", "qty": 9},
        "cfg": 7,
        "mw_trace": "tr-7",  # middleware-extracted header + injected DI value
        "types": ["int", "int", "int"],  # path/query/body all coerced to int
    }
    # header added AFTER awaiting call_next is on the handler's response, proving
    # the response flowed back through the middleware chain.
    assert resp.headers.get("X-Mw-After") == "post"


async def test_singular_param_default_when_absent(aiohttp_client) -> None:
    """A singular param with a python default is optional: when the value is absent
    the default is used and the request succeeds (no validation error)."""
    from rapidy import web
    from rapidy.http import QueryParam

    async def handler(
        limit: Annotated[int, QueryParam()] = 10,
    ) -> dict:
        return {"limit": limit}

    app = web.Application()
    app.add_routes([web.get("/", handler)])
    client = await aiohttp_client(app)

    resp = await client.get("/")
    assert resp.status == HTTPStatus.OK
    assert await resp.json() == {"limit": 10}


# ---------------------------------------------------------------------------
# 2. The 422 validation-error envelope (+ cross-source ordering)
# ---------------------------------------------------------------------------


async def test_validation_error_envelope_constraint(aiohttp_client) -> None:
    """A failing pydantic constraint produces HTTP 422 with the rapidy envelope:
    a top-level ``errors`` list whose single entry has ``loc == [param_type,
    alias]`` plus the pydantic ``type``/``msg``/``ctx`` fields."""
    from rapidy import web
    from rapidy.http import QueryParam

    async def handler(
        value: Annotated[int, QueryParam(ge=10)],
    ) -> dict:
        return {"value": value}

    app = web.Application()
    app.add_routes([web.get("/", handler)])
    client = await aiohttp_client(app)

    resp = await client.get("/", params={"value": "3"})
    assert resp.status == HTTPStatus.UNPROCESSABLE_ENTITY
    body = await resp.json()
    # Assert the documented envelope contract keys (type/loc/msg/ctx) rather than
    # exact whole-dict equality, which would also pin the absence of pydantic's
    # undocumented `url`/`input` keys.
    assert len(body["errors"]) == 1
    err = body["errors"][0]
    assert err["type"] == "greater_than_equal"
    assert err["loc"] == ["query", "value"]
    assert "greater than or equal to 10" in err["msg"]
    assert err["ctx"] == {"ge": 10}


async def test_validation_error_cross_source_ordering(aiohttp_client) -> None:
    """All failing sources in one request are collected into the single ``errors``
    list, ordered by the **handler signature** (the order each source first
    appears), NOT alphabetically. A nested body-model failure carries the
    source-prefixed pydantic path ``[body, field, subfield]``.

    Handler signature order here is path, then query, then body, so the errors
    must appear in exactly that order."""
    from rapidy import Rapidy
    from rapidy.http import Body, PathParam, QueryParam, post

    class Inner(BaseModel):
        n: int

    class B(BaseModel):
        inner: Inner

    async def handler(
        p: Annotated[int, PathParam(alias="p")],
        q: Annotated[int, QueryParam(alias="q")],
        b: Annotated[B, Body()],
    ) -> dict:
        return {}

    app = Rapidy(http_route_handlers=[post.reg("/{p}", handler)])
    client = await aiohttp_client(app)

    # path non-int, query non-int, nested body field non-int -> three failures
    resp = await client.post(
        "/notint", params={"q": "alsonot"}, json={"inner": {"n": "x"}}
    )
    assert resp.status == HTTPStatus.UNPROCESSABLE_ENTITY
    body = await resp.json()
    locs = [err["loc"] for err in body["errors"]]
    types = [err["type"] for err in body["errors"]]
    # exact handler-signature source order; nested body loc reads [body, inner, n]
    assert locs == [
        ["path", "p"],
        ["query", "q"],
        ["body", "inner", "n"],
    ]
    assert types == ["int_parsing", "int_parsing", "int_parsing"]


# ---------------------------------------------------------------------------
# 3. Plural params (whole-source -> one model)
# ---------------------------------------------------------------------------


async def test_plural_params_bind_whole_model(aiohttp_client) -> None:
    """Plural param classes (PathParams/QueryParams) bind the ENTIRE source into
    one pydantic model rather than a single named value. Model field defaults
    apply."""
    from rapidy import web
    from rapidy.http import PathParams, QueryParams

    class Query(BaseModel):
        page: int
        size: int = 25

    class Path(BaseModel):
        org: str
        repo: str

    async def handler(
        path: Annotated[Path, PathParams()],
        query: Annotated[Query, QueryParams()],
    ) -> dict:
        return {
            "org": path.org,
            "repo": path.repo,
            "page": query.page,
            "size": query.size,
        }

    app = web.Application()
    app.add_routes([web.get("/{org}/{repo}", handler)])
    client = await aiohttp_client(app)

    resp = await client.get("/acme/widget", params={"page": "2"})
    assert resp.status == HTTPStatus.OK
    assert await resp.json() == {
        "org": "acme",
        "repo": "widget",
        "page": 2,
        "size": 25,
    }


async def test_plural_headers_and_cookies_whole_model(aiohttp_client) -> None:
    """The Headers/Cookies plural markers also bind their whole source into a model
    (aliases select header/cookie names, model defaults apply). A missing required
    model field yields the 422 envelope located at ``[param_type, alias]``."""
    from rapidy import Rapidy
    from rapidy.http import Cookies, Headers, get

    class H(BaseModel):
        token: str = Field(alias="X-Token")
        trace: str = Field(alias="X-Trace")

    class C(BaseModel):
        sid: str
        theme: str = "light"

    async def handler(
        h: Annotated[H, Headers()],
        c: Annotated[C, Cookies()],
    ) -> dict:
        return {"token": h.token, "trace": h.trace, "sid": c.sid, "theme": c.theme}

    app = Rapidy(http_route_handlers=[get.reg("/", handler)])
    client = await aiohttp_client(app)

    # all present (cookie `theme` defaults) -> whole-source models populated
    ok = await client.get(
        "/", headers={"X-Token": "tk", "X-Trace": "tr"}, cookies={"sid": "s1"}
    )
    assert ok.status == HTTPStatus.OK
    assert await ok.json() == {"token": "tk", "trace": "tr", "sid": "s1", "theme": "light"}

    # one required header field missing (X-Trace present, X-Token absent) -> the
    # whole-model validation reports it at [header, X-Token], type missing
    missing = await client.get(
        "/", headers={"X-Trace": "tr"}, cookies={"sid": "s1"}
    )
    assert missing.status == HTTPStatus.UNPROCESSABLE_ENTITY
    body = await missing.json()
    assert len(body["errors"]) == 1
    assert body["errors"][0]["loc"] == ["header", "X-Token"]
    assert body["errors"][0]["type"] == "missing"


# ---------------------------------------------------------------------------
# 4. Body extraction + content-type enforcement
# ---------------------------------------------------------------------------


async def test_body_content_type_mismatch_rejected(aiohttp_client) -> None:
    """With check_content_type on (the default), sending a body whose Content-Type
    does not match the Body's declared content_type yields a 422 body-extraction
    error located at ``[body]`` -- the request never reaches the handler with
    parsed data."""
    from rapidy import web
    from rapidy.http import Body

    class Item(BaseModel):
        name: str

    async def handler(item: Annotated[Item, Body()]) -> dict:
        return {"name": item.name}

    app = web.Application()
    app.add_routes([web.post("/", handler)])
    client = await aiohttp_client(app)

    resp = await client.post(
        "/", data="name=bolt", headers={"Content-Type": "text/plain"}
    )
    assert resp.status == HTTPStatus.UNPROCESSABLE_ENTITY
    body = await resp.json()
    assert len(body["errors"]) == 1
    assert body["errors"][0]["loc"] == ["body"]


async def test_body_content_type_override_text(aiohttp_client) -> None:
    """Body(content_type=...) overrides the default JSON expectation. Declaring
    text/plain causes the raw text body to be passed through as a string."""
    from rapidy import web
    from rapidy.enums import ContentType
    from rapidy.http import Body

    async def handler(
        raw: Annotated[str, Body(content_type=ContentType.text_plain)],
    ) -> dict:
        return {"echo": raw}

    app = web.Application()
    app.add_routes([web.post("/", handler)])
    client = await aiohttp_client(app)

    resp = await client.post(
        "/", data="plain words", headers={"Content-Type": "text/plain"}
    )
    assert resp.status == HTTPStatus.OK
    assert await resp.json() == {"echo": "plain words"}


async def test_body_check_content_type_disabled(aiohttp_client) -> None:
    """Body(check_content_type=False) skips the content-type guard so a JSON body
    sent without a matching Content-Type is still parsed and validated."""
    from rapidy import web
    from rapidy.http import Body

    class Item(BaseModel):
        name: str

    async def handler(
        item: Annotated[Item, Body(check_content_type=False)],
    ) -> dict:
        return {"name": item.name}

    app = web.Application()
    app.add_routes([web.post("/", handler)])
    client = await aiohttp_client(app)

    resp = await client.post(
        "/", data='{"name": "bolt"}', headers={"Content-Type": "text/plain"}
    )
    assert resp.status == HTTPStatus.OK
    assert await resp.json() == {"name": "bolt"}


async def test_body_content_type_wildcard_family(aiohttp_client) -> None:
    """A Body content_type with a wildcard subtype (``text/*``) matches any request
    Content-Type in that type family but rejects one outside it. A ``text/html``
    body is accepted (raw text passed through); an ``application/json`` body is
    rejected before the handler with the 422 body error located at ``[body]``."""
    from rapidy import web
    from rapidy.http import Body

    async def handler(
        raw: Annotated[str, Body(content_type="text/*")],
    ) -> dict:
        return {"echo": raw}

    app = web.Application()
    app.add_routes([web.post("/", handler)])
    client = await aiohttp_client(app)

    # text/html is within the text/* family -> accepted, raw text passed through
    accept = await client.post(
        "/", data="<h1>hi</h1>", headers={"Content-Type": "text/html"}
    )
    assert accept.status == HTTPStatus.OK
    assert await accept.json() == {"echo": "<h1>hi</h1>"}

    # application/json is outside the text/* family -> rejected at [body]
    reject = await client.post(
        "/", data="anything", headers={"Content-Type": "application/json"}
    )
    assert reject.status == HTTPStatus.UNPROCESSABLE_ENTITY
    body = await reject.json()
    assert len(body["errors"]) == 1
    assert body["errors"][0]["loc"] == ["body"]


async def test_body_form_urlencoded_extract_and_validate(aiohttp_client) -> None:
    """Body(content_type="application/x-www-form-urlencoded") parses a url-encoded
    form body (key=value pairs) into the annotated pydantic model, coercing field
    types (e.g. the form string ``qty=5`` -> int 5). The content_type is given as a
    raw MIME string (the documented raw-string form)."""
    from rapidy import web
    from rapidy.http import Body

    class Form(BaseModel):
        name: str
        qty: int

    async def handler(
        form: Annotated[Form, Body(content_type="application/x-www-form-urlencoded")],
    ) -> dict:
        return {"name": form.name, "qty": form.qty, "qty_type": type(form.qty).__name__}

    app = web.Application()
    app.add_routes([web.post("/", handler)])
    client = await aiohttp_client(app)

    # aiohttp sends a dict `data=` as application/x-www-form-urlencoded
    resp = await client.post("/", data={"name": "bolt", "qty": "5"})
    assert resp.status == HTTPStatus.OK
    assert await resp.json() == {"name": "bolt", "qty": 5, "qty_type": "int"}


# ---------------------------------------------------------------------------
# 5. Routing & registration model (distinct registration paths)
# ---------------------------------------------------------------------------


async def test_decorator_route_registration(aiohttp_client) -> None:
    """A handler decorated with @get/@post is a route object registered by passing
    it in Rapidy(http_route_handlers=[...]). Method and path bind as declared; the
    wrong method on the path is 405 and an unknown path is 404."""
    from rapidy import Rapidy
    from rapidy.http import get, post

    @get("/ping")
    async def ping() -> dict:
        return {"pong": True}

    @post("/echo")
    async def echo() -> dict:
        return {"ok": True}

    app = Rapidy(http_route_handlers=[ping, echo])
    client = await aiohttp_client(app)

    assert (await client.get("/ping")).status == HTTPStatus.OK
    assert await (await client.get("/ping")).json() == {"pong": True}
    assert (await client.post("/echo")).status == HTTPStatus.OK
    assert (await client.get("/echo")).status == HTTPStatus.METHOD_NOT_ALLOWED
    assert (await client.get("/missing")).status == HTTPStatus.NOT_FOUND


async def test_reg_classmethod_registration(aiohttp_client) -> None:
    """Each method decorator exposes a ``.reg(path, handler)`` classmethod that
    registers an undecorated async handler, equivalent to decorating it."""
    from rapidy import Rapidy
    from rapidy.http import get

    async def status_handler() -> dict:
        return {"status": "up"}

    app = Rapidy(http_route_handlers=[get.reg("/status", status_handler)])
    client = await aiohttp_client(app)

    resp = await client.get("/status")
    assert resp.status == HTTPStatus.OK
    assert await resp.json() == {"status": "up"}


async def test_controller_class_registration(aiohttp_client) -> None:
    """@controller(path) defines a class whose @get/@post-decorated methods are
    sub-routes mounted under the controller's base path. Sub-paths concatenate
    onto the base path; controller methods take ``self``."""
    from rapidy import Rapidy
    from rapidy.http import Body, PathParam, controller, get, post

    @controller("/users")
    class Users:
        @get("/{uid}")
        async def get_one(self, uid: Annotated[int, PathParam()]) -> dict:
            return {"uid": uid}

        @post("/")
        async def create(self, data: Annotated[dict, Body()]) -> dict:
            return {"created": data}

    app = Rapidy(http_route_handlers=[Users])
    client = await aiohttp_client(app)

    r1 = await client.get("/users/42")
    assert r1.status == HTTPStatus.OK
    assert await r1.json() == {"uid": 42}

    r2 = await client.post("/users/", json={"name": "ada"})
    assert r2.status == HTTPStatus.OK
    assert await r2.json() == {"created": {"name": "ada"}}


async def test_httprouter_prefix_mount(aiohttp_client) -> None:
    """HTTPRouter(prefix, route_handlers=[...]) groups handlers under a prefix and
    is itself registered via Rapidy(http_route_handlers=[router]). The prefix
    concatenates with each handler's path; the unprefixed path is not registered."""
    from rapidy import Rapidy
    from rapidy.http import HTTPRouter, get

    @get("/health")
    async def health() -> dict:
        return {"ok": True}

    async def version_handler() -> dict:
        return {"version": "1.1.2"}

    router = HTTPRouter(
        "/api",
        route_handlers=[health, get.reg("/version", version_handler)],
    )
    app = Rapidy(http_route_handlers=[router])
    client = await aiohttp_client(app)

    assert await (await client.get("/api/health")).json() == {"ok": True}
    assert await (await client.get("/api/version")).json() == {"version": "1.1.2"}
    assert (await client.get("/health")).status == HTTPStatus.NOT_FOUND


def test_non_async_handler_rejected() -> None:
    """A method decorator applied to a non-async callable raises at decoration time
    (handlers must be coroutine functions)."""
    from rapidy.http import get

    with pytest.raises(Exception):

        @get("/sync")
        def sync_handler() -> dict:  # noqa: ASYNC -- intentional
            return {}


# ---------------------------------------------------------------------------
# 6. Response serialization + the response pipeline
# ---------------------------------------------------------------------------


async def test_response_auto_content_type(aiohttp_client) -> None:
    """The runtime type of the returned value drives serialization and the response
    Content-Type: dict/BaseModel serialize to application/json, str to text/plain.
    A BaseModel is dumped via its fields."""
    from rapidy import Rapidy
    from rapidy.http import get

    class Out(BaseModel):
        x: int
        y: str

    @get("/json")
    async def as_json() -> dict:
        return {"a": 1}

    @get("/model")
    async def as_model() -> Out:
        return Out(x=5, y="z")

    @get("/text")
    async def as_text() -> str:
        return "hello"

    app = Rapidy(http_route_handlers=[as_json, as_model, as_text])
    client = await aiohttp_client(app)

    r1 = await client.get("/json")
    assert r1.content_type == "application/json"
    assert await r1.json() == {"a": 1}

    r2 = await client.get("/model")
    assert r2.content_type == "application/json"
    assert await r2.json() == {"x": 5, "y": "z"}

    r3 = await client.get("/text")
    assert r3.content_type == "text/plain"
    assert await r3.text() == "hello"


async def test_response_pipeline_dict_coerced_status_and_dump_controls(aiohttp_client) -> None:
    """The full response pipeline on a single route: a handler typed ``-> Model``
    returns a raw ``dict`` that must be validated/coerced THROUGH the model, then
    serialized honoring the route's dump controls and status code.

    With ``status_code=CREATED``, ``response_by_alias=True`` and
    ``response_exclude_none=True``, a returned dict with an aliased field and a
    ``None`` optional field is built into the model and dumped as JSON using the
    field ALIAS with the ``None`` key DROPPED, and the response status is 201."""
    from rapidy import Rapidy
    from rapidy.http import post

    class Out(BaseModel):
        item_id: int = Field(alias="itemId")
        note: Optional[str] = None
        model_config = {"populate_by_name": True}

    @post(
        "/r",
        status_code=HTTPStatus.CREATED,
        response_by_alias=True,
        response_exclude_none=True,
    )
    async def handler() -> Out:
        # raw dict -> coerced through Out, then dumped per the route controls
        return {"item_id": 7, "note": None}

    app = Rapidy(http_route_handlers=[handler])
    client = await aiohttp_client(app)

    resp = await client.post("/r")
    assert resp.status == HTTPStatus.CREATED
    assert resp.content_type == "application/json"
    # alias used (itemId), None `note` excluded
    assert await resp.json() == {"itemId": 7}


async def test_response_content_type_override(aiohttp_client) -> None:
    """``response_content_type`` forces the response Content-Type regardless of the
    runtime value type: a dict return forced to ``text/plain`` is sent with that
    Content-Type (body still JSON-serialized), and a dict forced to
    ``application/json`` keeps JSON."""
    from rapidy import Rapidy
    from rapidy.http import get

    @get("/forced-text", response_content_type="text/plain")
    async def forced_text() -> dict:
        return {"a": 1}

    @get("/forced-json", response_content_type="application/json")
    async def forced_json() -> dict:
        return {"a": 1}

    app = Rapidy(http_route_handlers=[forced_text, forced_json])
    client = await aiohttp_client(app)

    rt = await client.get("/forced-text")
    assert rt.status == HTTPStatus.OK
    # dict would default to application/json, but the override forces text/plain
    assert rt.content_type == "text/plain"

    rj = await client.get("/forced-json")
    assert rj.status == HTTPStatus.OK
    assert rj.content_type == "application/json"
    assert await rj.json() == {"a": 1}


async def test_response_explicit_response_object(aiohttp_client) -> None:
    """A handler returning an explicit web.Response is passed through unchanged: its
    body, status, and content type are honored without re-serialization."""
    from rapidy import Rapidy, web
    from rapidy.http import get

    @get("/raw")
    async def handler() -> web.Response:
        return web.Response(
            text="raw-body", status=202, content_type="text/x-custom"
        )

    app = Rapidy(http_route_handlers=[handler])
    client = await aiohttp_client(app)

    resp = await client.get("/raw")
    assert resp.status == 202
    assert await resp.text() == "raw-body"
    assert resp.content_type == "text/x-custom"


async def test_response_validation_against_return_annotation(aiohttp_client) -> None:
    """With response validation on by default and no ``response_type`` set, the
    handler RETURN ANNOTATION drives validation/casting. A handler typed
    ``-> Model`` that returns a dict missing a required model field is a
    response-validation failure: rather than serializing the bad payload as a 200
    success, the framework reports a server-side failure with HTTP 500."""
    from rapidy import Rapidy
    from rapidy.http import get

    class Resp(BaseModel):
        item_id: int = Field(alias="itemId")
        note: Optional[str] = None
        model_config = {"populate_by_name": True}

    @get("/bad")
    async def bad_handler() -> Resp:
        # missing required `item_id` -> response-validation failure
        return {"note": "x"}

    app = Rapidy(http_route_handlers=[bad_handler])
    client = await aiohttp_client(app)

    bad = await client.get("/bad")
    # a failed response validation is a server-side error, not a 200 carrying the
    # invalid payload nor a request-style 4xx
    assert bad.status == HTTPStatus.INTERNAL_SERVER_ERROR


# ---------------------------------------------------------------------------
# 7. jsonify encoder (unit)
# ---------------------------------------------------------------------------


def test_jsonify_scalar_encoders() -> None:
    """jsonify maps non-JSON scalar types to JSON-safe representations: Decimal and
    UUID -> str, date/datetime -> ISO-8601 string, bytes -> decoded str,
    Enum -> its value."""
    from enum import Enum
    from rapidy.encoders import jsonify

    class Color(Enum):
        red = "RED"

    assert jsonify(Decimal("1.50")) == "1.50"
    u = UUID("12345678-1234-5678-1234-567812345678")
    assert jsonify(u) == "12345678-1234-5678-1234-567812345678"
    assert jsonify(datetime.date(2020, 1, 2)) == "2020-01-02"
    assert jsonify(datetime.datetime(2020, 1, 2, 3, 4, 5)) == "2020-01-02T03:04:05"
    assert jsonify(b"bytes") == "bytes"
    assert jsonify(Color.red) == "RED"


def test_jsonify_models_and_dataclasses() -> None:
    """jsonify converts BaseModel and dataclass instances to dicts, recursing into
    nested containers and encoding nested non-JSON scalars."""
    from rapidy.encoders import jsonify

    class Inner(BaseModel):
        when: datetime.date

    class Outer(BaseModel):
        name: str
        inner: Inner
        tags: List[str]

    out = Outer(name="n", inner=Inner(when=datetime.date(2021, 6, 1)), tags=["a", "b"])
    assert jsonify(out) == {
        "name": "n",
        "inner": {"when": "2021-06-01"},
        "tags": ["a", "b"],
    }

    @dataclass
    class DC:
        amount: Decimal
        label: str

    assert jsonify(DC(amount=Decimal("2.5"), label="x")) == {
        "amount": "2.5",
        "label": "x",
    }


def test_jsonify_field_controls() -> None:
    """jsonify honors the pydantic-style field controls: by_alias uses field aliases
    (default True), exclude_none drops None-valued fields, and dumps=True returns a
    JSON string instead of a structure."""
    from rapidy.encoders import jsonify

    class M(BaseModel):
        full_name: str = Field(alias="fullName")
        nickname: Optional[str] = None
        model_config = {"populate_by_name": True}

    m = M(full_name="Bob", nickname=None)

    assert jsonify(m) == {"fullName": "Bob", "nickname": None}
    assert jsonify(m, by_alias=False) == {"full_name": "Bob", "nickname": None}
    assert jsonify(m, exclude_none=True) == {"fullName": "Bob"}

    dumped = jsonify({"a": 1, "b": [2, 3]}, dumps=True)
    assert isinstance(dumped, str)
    import json

    assert json.loads(dumped) == {"a": 1, "b": [2, 3]}


# ---------------------------------------------------------------------------
# 8. dishka dependency injection (controller-method path)
# ---------------------------------------------------------------------------


async def test_di_into_controller_method(aiohttp_client) -> None:
    """FromDishka injection works on controller methods alongside rapidy request
    params: the DI value and the extracted path param both arrive."""
    from rapidy import Rapidy
    from rapidy.http import PathParam, controller, get
    from dishka import FromDishka, Provider, provide, Scope

    class Greeter(Provider):
        scope = Scope.REQUEST

        @provide
        async def prefix(self) -> str:
            return "hi-"

    @controller("/greet")
    class Greet:
        @get("/{name}")
        async def hello(
            self,
            prefix: FromDishka[str],
            name: Annotated[str, PathParam()],
        ) -> dict:
            return {"greeting": prefix + name}

    app = Rapidy(http_route_handlers=[Greet], di_providers=[Greeter()])
    client = await aiohttp_client(app)

    resp = await client.get("/greet/ada")
    assert resp.status == HTTPStatus.OK
    assert await resp.json() == {"greeting": "hi-ada"}
