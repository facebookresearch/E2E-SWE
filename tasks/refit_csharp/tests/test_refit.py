"""Restly WRG test driver.

Each test invokes a per-aspect C# harness with a scenario id, parses the single-line JSON
"observation" it prints, and asserts on the observed request and/or outcome. The harness is split into
independent group projects (built by test.sh); a manifest maps each scenario id to its group's built
DLL. A scenario whose group failed to build is absent from the manifest, so only its own test fails —
the rest of the suite still grades (fractional f2p).
"""

import functools
import json
import os
import re
import subprocess

MANIFEST = os.environ.get("HARNESS_MANIFEST", "/tmp/harness_manifest.txt")


@functools.lru_cache(maxsize=1)
def _manifest() -> dict:
    """Load the scenario -> harness-DLL map written by test.sh."""
    mapping: dict = {}
    with open(MANIFEST) as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line:
                continue
            scenario, dll = line.split("\t", 1)
            mapping[scenario] = dll
    return mapping


def run(scenario: str) -> dict:
    """Run one harness scenario (via its group's DLL) and return its parsed observation."""
    dll = _manifest().get(scenario)
    assert dll is not None, (
        f"scenario '{scenario}' is unavailable — its harness group failed to build "
        f"(the aspect it covers is unimplemented or does not compile against the solution)."
    )
    proc = subprocess.run(
        ["dotnet", dll, scenario],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, (
        f"harness exited {proc.returncode} for '{scenario}'\n"
        f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    )
    line = proc.stdout.strip().splitlines()[-1]
    obs = json.loads(line)
    assert "harnessError" not in obs, f"harness error for '{scenario}': {obs['harnessError']}"
    return obs


def _cd_param(disposition: str, key: str) -> str | None:
    """Extract a Content-Disposition parameter (name/filename), tolerant of quoted or bare values."""
    m = re.search(rf'(?:^|;|\s){key}=("([^"]*)"|([^;]+))', disposition)
    if not m:
        return None
    return (m.group(2) if m.group(2) is not None else m.group(3)).strip()


def _parse_multipart(obs: dict) -> list:
    """Parse a multipart/form-data body into its ordered parts using the boundary from the content type.

    Returns a list of {name, filename, content_type, content} dicts. The boundary is read from the
    Content-Type header (not hard-coded), so an implementation using any valid boundary still parses.
    """
    ctype = obs["contentType"]
    assert ctype and ctype.startswith("multipart/form-data"), f"not multipart/form-data: {ctype}"
    m = re.search(r'boundary="?([^";]+)"?', ctype)
    assert m, f"no boundary in content type: {ctype}"
    delim = "--" + m.group(1)
    parts = []
    for seg in obs["body"].split(delim):
        if "\r\n\r\n" not in seg:
            continue  # preamble or closing delimiter, not a part
        head, content = seg.split("\r\n\r\n", 1)
        if content.endswith("\r\n"):
            content = content[:-2]  # strip the CRLF that precedes the next delimiter
        headers = {}
        for hline in head.split("\r\n"):
            if ":" in hline:
                k, v = hline.split(":", 1)
                headers[k.strip().lower()] = v.strip()
        cd = headers.get("content-disposition", "")
        parts.append(
            {
                "name": _cd_param(cd, "name"),
                "filename": _cd_param(cd, "filename"),
                "content_type": headers.get("content-type", ""),
                "content": content,
            }
        )
    return parts


def test_url_and_query():
    """GET with a path parameter and an implicit query parameter builds the right URL and body."""
    obs = run("url_and_query")
    req = obs["request"]
    assert req["method"] == "GET"
    assert req["target"] == "/users/octocat?sort=desc"
    assert obs["result"] == {"id": 7, "name": "octo"}


def test_query_collection_formats():
    """CollectionFormat controls collection joining: Multi = one pair per element; Csv = comma-joined then escaped."""
    assert run("query_collection_multi")["request"]["target"] == "/users/list?ages=10&ages=20&ages=30"
    assert run("query_csv")["target"] == "/q?ages=10%2C20%2C30"


def test_body_json_camelcase():
    """A [Body] object serializes as camelCase JSON with an application/json content type."""
    obs = run("body_json_camelcase")
    req = obs["request"]
    assert req["method"] == "POST"
    assert req["body"] == '{"name":"octo","age":5}'
    assert req["contentHeaders"]["Content-Type"] == ["application/json; charset=utf-8"]


def test_exception_apiexception():
    """A non-2xx on Task<T> throws ApiException carrying the status and body."""
    ex = run("exception_apiexception")["exception"]
    assert ex["type"] == "ApiException"
    assert ex["statusCode"] == 400
    assert ex["content"] == "bad input"


def test_exception_validation_problem():
    """application/problem+json on a non-2xx throws ValidationApiException with ProblemDetails: title,
    status, errors, the RFC 7807 `about:blank` Type default, and unknown members captured in Extensions."""
    ex = run("exception_validation_problem")["exception"]
    assert ex["type"] == "ValidationApiException"
    pd = ex["problemDetails"]
    assert pd["title"] == "invalid"
    assert pd["status"] == 400
    assert pd["errors"]["Name"] == ["Required"]
    assert pd["type"] == "about:blank"  # RFC 7807 default when the payload omits "type"
    ext = run("edge_problemdetails_extensions")["exception"]["problemDetails"]["extensions"]
    assert ext["traceId"] == "t-1"
    assert ext["retryAfter"] == "5"


def test_options_metadata():
    """Restly stamps interface/method metadata onto HttpRequestMessage.Options: the method name, the raw
    route template (placeholders intact), and the top-level interface type."""
    opts = run("options_metadata")["request"]["options"]
    assert opts["Restly.MethodName"] == "GetUser"
    assert opts["Restly.RelativePathTemplate"] == "/users/{user}"
    assert opts["Restly.InterfaceType"] == "Harness.IUsersApi"


# ===== URL / routing =====
def test_http_verbs():
    """Each HTTP method attribute dispatches with the matching HttpMethod."""
    assert run("http_verbs")["methods"] == ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"]


def test_route_escaped():
    """A normal {placeholder} percent-escapes its value, including reserved chars and slashes."""
    assert run("route_escaped")["target"] == "/search/a%20b%2Fc"


def test_route_catchall():
    """A {**catch-all} segment preserves the slashes in the value."""
    assert run("route_catchall")["target"] == "/search/admin/products"


def test_route_optional():
    """An optional {name?} segment renders when supplied and drops (with its slash) when null, including
    an interior segment that collapses without leaving a doubled slash."""
    obs = run("route_optional")
    assert obs["withValue"] == "/push/dev1/m42"
    assert obs["withNull"] == "/push/dev1"
    interior = run("edge_optional_interior")
    assert interior["withValue"] == "/a/x/b"
    assert interior["withNull"] == "/a/b"


def test_route_aliased_and_object():
    """[AliasAs] maps a param to a path token; a dotted {obj.prop} binds against an object's props."""
    obs = run("route_aliased_and_object")
    assert obs["aliased"] == "/group/4/users"
    assert obs["obj"] == "/group/1/users/2"


def test_route_pathprefix():
    """[PathPrefix] on the interface is prepended to each method's route."""
    assert run("route_pathprefix")["target"] == "/api/v2/users"


def test_route_url_absolute():
    """[Url] supplies the absolute URI (base ignored); [Query] params are still appended."""
    assert run("route_url_absolute")["uri"] == "https://cdn.example.com/data?token=abc"


def test_route_rfc3986():
    """Under Rfc3986 resolution, a leading-slash-less route appends and a leading slash replaces."""
    obs = run("route_rfc3986")
    assert obs["append"] == "http://api.example.com/api/v1/values"
    assert obs["replace"] == "http://api.example.com/values"


# ===== query strings =====
def test_query_flatten():
    """A query parameter flattens to key=value pairs: a complex object to its non-null props ([AliasAs]
    and [EnumMember] applied), and an IDictionary to one pair per entry."""
    assert run("query_object")["target"] == "/q?order=desc&Limit=10&Kind=bar"
    assert run("query_dictionary")["target"] == "/q?status=active&page=2"


def test_query_unescaped():
    """[QueryUriFormat(Unescaped)] leaves the query string unescaped."""
    assert run("query_unescaped")["target"] == "/q?expr=Select+Id,Name"


def test_query_deep_nested():
    """A deep query object flattens a nested object (dot keys), a collection, and a dictionary in one call."""
    assert run("query_deep_nested")["target"] == "/dq?Name=x&Address.City=NYC&Address.Zip=10001&Tags=1%2C2&Meta.k=v"


def test_query_key_formatting():
    """The settings key presets reformat query-object property keys: SnakeCase() -> sort_order/page_size;
    CamelCase() applies the JSON camelCase policy, lowercasing the leading uppercase run (APIKey->apiKey,
    IOSize->ioSize), not just the first character."""
    assert run("query_snakecase")["target"] == "/q?sort_order=desc&page_size=50"
    assert run("query_camelcase")["target"] == "/q?apiKey=k&ioSize=4"


# ===== headers / auth =====
def test_headers_static_and_override():
    """Static [Headers] are emitted; a method [Headers] value overrides the interface for the same name."""
    assert run("headers_static")["headers"] == {"User-Agent": "RestlyTest", "X-Static": "iface"}
    assert run("headers_method_override")["headers"]["X-Static"] == "method"


def test_headers_dynamic():
    """A [Header] param emits when non-null and is omitted when null."""
    obs = run("headers_dynamic")
    assert obs["withValue"]["X-Trace"] == "abc"
    assert "X-Trace" not in obs["withNull"]


def test_headers_authorize():
    """[Authorize(\"scheme\")] sets Authorization: <scheme> <token>; the scheme defaults to Bearer."""
    assert run("headers_authorize")["headers"]["Authorization"] == "Bearer TOK"
    assert run("headers_authorize_default")["headers"]["Authorization"] == "Bearer TOK"


def test_headers_collection():
    """[HeaderCollection] merges each dictionary entry into the request headers."""
    h = run("headers_collection")["headers"]
    assert h["Authorization"] == "Bearer x"
    assert h["X-Tenant-Id"] == "123"


def test_headers_auth_getter():
    """AuthorizationHeaderValueGetter fills the empty 'Authorization: Bearer' placeholder, and omits it when the token is empty."""
    assert run("headers_auth_getter")["headers"]["Authorization"] == "Bearer TOKEN123"
    assert "Authorization" not in run("headers_auth_getter_empty")["headers"]


def test_headers_inheritance():
    """Each method carries the [Headers] of the interface that declares it."""
    obs = run("headers_inheritance")
    assert obs["ping"]["X-Level"] == "base"
    assert obs["pong"]["X-Level"] == "derived"


def test_headers_content_type():
    """A [Header(\"Content-Type\")] value routes onto the content headers."""
    obs = run("headers_content_type")
    assert obs["contentType"] == "application/xml"
    assert obs["body"] == "<x/>"


# ===== body / content =====
def test_body_string():
    """A plain string [Body] is sent verbatim as text/plain; [Body(Json)] serializes it as a JSON string."""
    raw = run("body_raw_string")
    assert raw["body"] == "hello"
    assert raw["contentType"] == "text/plain; charset=utf-8"
    js = run("body_json_string")
    assert js["body"] == '"hello"'
    assert js["contentType"] == "application/json; charset=utf-8"


def test_body_urlencoded():
    """[Body(UrlEncoded)] over its three input forms: an object (CLR field names verbatim, [AliasAs]
    applies, nulls omitted), an IDictionary (key=value pairs), and a string (percent-escaped)."""
    obj = run("body_form")
    assert obj["body"] == "UserName=neo&years=5"
    assert obj["contentType"] == "application/x-www-form-urlencoded"
    assert run("body_form_dict")["body"] == "v=1&t=event"
    s = run("body_urlencoded_string")
    assert s["body"] == "a%20b%26c%3Dd"
    assert s["contentType"].startswith("application/x-www-form-urlencoded")


def test_body_jsonlines():
    """[Body(JsonLines)] streams one JSON document per line as application/x-ndjson."""
    obs = run("body_jsonlines")
    assert obs["body"] == '{"name":"a","age":1}\n{"name":"b","age":2}'
    assert obs["contentType"] == "application/x-ndjson"


def test_body_multipart():
    """[Multipart] builds one form-data part per argument with the right field name, filename, content
    type, and content — a StreamPart file + string field, and a file + string + DateTime workflow."""
    obs = run("body_multipart")
    assert 'boundary="----MyGreatBoundary"' in obs["contentType"]  # documented default boundary
    parts = _parse_multipart(obs)
    assert [(p["name"], p["filename"]) for p in parts] == [("file", "f.txt"), ("note", None)]
    file_part, note_part = parts
    assert file_part["content"] == "filedata"
    assert file_part["content_type"].startswith("text/plain")
    assert note_part["content"] == "hi"

    wf = _parse_multipart(run("workflow_multipart"))
    assert [(p["name"], p["filename"]) for p in wf] == [("file", "p.jpg"), ("label", None), ("takenAt", None)]
    assert wf[0]["content"] == "img"
    assert wf[0]["content_type"].startswith("image/jpeg")
    assert wf[1]["content"] == "vacation"
    assert "2024" in wf[2]["content"] and not wf[2]["content"].startswith('"')  # date plain text, not JSON


# ===== responses / return types =====
def test_resp_return_types():
    """The return type drives response handling: a 204/empty body yields default(T); Task<string>
    returns the raw body; Task<HttpResponseMessage> passes a non-2xx response through without throwing."""
    assert run("resp_204_null")["result"] is None
    assert run("resp_raw_string")["raw"] == "raw text"
    assert run("resp_message_nothrow")["status"] == 404


def test_resp_apiresponse():
    """ApiResponse<T> exposes content + status metadata on success and captures a non-2xx into .Error
    (never throwing) — the two symmetric sides of the wrapper's capture semantics."""
    ok = run("resp_apiresponse_success")["apiResponse"]
    assert ok["statusCode"] == 200
    assert ok["isSuccessStatusCode"] is True
    assert ok["isSuccessful"] is True
    assert ok["content"] == {"id": 3, "name": "ok"}
    err = run("apiresponse_error_capture")["apiResponse"]
    assert err["statusCode"] == 404
    assert err["isSuccessStatusCode"] is False
    assert err["errorType"] == "ApiException"


def test_resp_ensure_variants():
    """On a 2xx with a deserialization error: EnsureSuccessStatusCode passes, EnsureSuccessful throws."""
    obs = run("resp_ensure_variants")
    assert obs["isSuccessStatusCode"] is True
    assert obs["isSuccessful"] is False
    assert obs["threwEnsureStatus"] is False
    assert obs["threwEnsureful"] is True


def test_stream_formats():
    """IAsyncEnumerable<T> auto-detects JSON array, JSON Lines, and SSE framing."""
    obs = run("stream_formats")
    expected = [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]
    assert obs["array"] == expected
    assert obs["ndjson"] == expected
    assert obs["sse"] == expected


# ===== exceptions =====
def test_stream_factory_null():
    """A custom ExceptionFactory returning null lets IAsyncEnumerable stream a non-2xx body instead of throwing."""
    assert run("stream_factory_null")["items"] == [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]


def test_exc_deserialization_success():
    """A deserialization failure on a 2xx (Task<T>) throws ApiException with an inner JsonException."""
    ex = run("exc_deserialization_success")["exception"]
    assert ex["type"] == "ApiException"
    assert ex["innerType"] == "JsonException"
    assert ex["statusCode"] == 200


def test_exc_transport():
    """A transport failure surfaces as ApiRequestException wrapping the HttpRequestException."""
    ex = run("exc_transport")["exception"]
    assert ex["type"] == "ApiRequestException"
    assert ex["innerType"] == "HttpRequestException"


def test_exc_factory():
    """ExceptionFactory drives the throw on a non-2xx: returning null suppresses it (the body
    deserializes normally), and a returned exception is the one thrown (not a default ApiException)."""
    assert run("exc_factory_null")["result"] == {"id": 9, "name": "z"}
    ex = run("exc_factory_custom")["exception"]
    assert ex["type"] == "InvalidOperationException"
    assert ex["message"] == "custom-from-factory"


def test_deser_factory():
    """A custom DeserializationExceptionFactory maps a 2xx deserialization failure to its own exception."""
    ex = run("deser_factory")["exception"]
    assert ex["type"] == "InvalidOperationException"
    assert ex["message"] == "custom-deser"


# ===== settings / cross-cutting =====
def test_settings_property():
    """[Property] on a parameter and on an interface property both stamp their value onto HttpRequestMessage.Options."""
    assert run("settings_property_param")["request"]["options"]["trace-id"] == "t123"
    assert run("settings_property_interface")["request"]["options"]["tenant"] == "acme"


def test_settings_timeout():
    """[Timeout] cancels a response that exceeds the deadline."""
    assert run("settings_timeout")["exception"]["type"] == "TaskCanceledException"


def test_settings_cancellation():
    """A pre-cancelled CancellationToken parameter cancels the call."""
    assert run("settings_cancellation")["exception"]["type"] == "TaskCanceledException"


def test_generics():
    """The generator closes over a type argument: a closed generic interface and a generic method each
    route and deserialize to their concrete type argument."""
    assert run("generic_interface")["result"] == {"id": 11, "name": "gen"}
    assert run("edge_generic_method")["result"] == {"id": 7, "status": "done"}


# ===== generated-only features =====
def test_encoded():
    """[Encoded] passes a value through verbatim (no escaping) in query, path, and catch-all segments."""
    assert run("encoded")["target"] == "/e?raw=a+b%20c"
    assert run("encoded_path")["target"] == "/e/a%2Fb"
    assert run("edge_encoded_catchall")["target"] == "/files/a/b%20c"


def test_composition():
    """Methods inherited from base interfaces are implemented: a diamond composition routes methods from
    each base, and an inherited base method with no HTTP attribute throws NotImplementedException."""
    obs = run("composition_diamond")
    assert obs["pets"] == "/pets"
    assert obs["owners"] == "/owners"
    assert obs["all"] == "/all"
    nonrefit = run("composition_nonrefit")
    assert nonrefit["d"] == "/d"
    assert nonrefit["plainException"] == "NotImplementedException"


def test_multipart_parts():
    """Multipart supports ByteArrayPart, FileInfoPart, and IEnumerable<StreamPart> — exactly one part
    each, in parameter order, with the wrapper's filename, content type, and content."""
    parts = _parse_multipart(run("multipart_parts"))
    assert [(p["name"], p["filename"], p["content"]) for p in parts] == [
        ("data", "d.bin", "BYTES"),
        ("doc", "report.txt", "filecontent"),
        ("files", "a.txt", "one"),
        ("files", "b.txt", "two"),
    ]
    assert parts[0]["content_type"].startswith("application/octet-stream")
    assert all(p["content_type"].startswith("text/plain") for p in parts[1:])


def test_multipart_name_precedence():
    """Part name precedence: explicit StreamPart name > [AliasAs] > parameter name — exactly these
    three parts, in order, each keeping its own filename and content."""
    parts = _parse_multipart(run("multipart_name_precedence"))
    assert [(p["name"], p["filename"], p["content"]) for p in parts] == [
        ("chosen", "x.txt", "1"),
        ("aliased", "y.txt", "2"),
        ("plain", "z.txt", "3"),
    ]


def test_multipart_raw_types():
    """Raw byte[]/Stream parts default their filename to the parameter name; a raw FileInfo uses the
    file's own name; a plain-object part is application/json with no filename."""
    parts = {p["name"]: p for p in _parse_multipart(run("multipart_raw_types"))}
    assert parts["payload"]["filename"] == "payload" and parts["payload"]["content"] == "BYTES"
    assert parts["blob"]["filename"] == "blob" and parts["blob"]["content"] == "STREAMED"
    assert parts["doc"]["filename"] == "mp_raw.txt" and parts["doc"]["content"] == "docdata"
    assert parts["meta"]["filename"] is None
    assert parts["meta"]["content_type"].startswith("application/json")
    assert parts["meta"]["content"] == '{"name":"m","age":9}'


def test_queryname():
    """[QueryName] renders the value as a bare presence flag (one per element for collections)."""
    obs = run("queryname")
    assert obs["single"] == "/qn?archived"
    assert obs["multi"] == "/qn?a&b"


# ===== composed realistic workflows =====
def test_workflow_get():
    """A GET composing a path param + object query ([AliasAs]+enum) + static & dynamic headers."""
    obs = run("workflow_get")
    assert obs["target"] == "/orgs/acme/orders?sort=date&Limit=20&Priority=hi"
    assert obs["headers"]["X-Client"] == "shop"
    assert obs["headers"]["X-Request-ID"] == "req-99"


def test_workflow_post_auth():
    """A POST composing a path param + JSON body + static header + [Authorize] token."""
    obs = run("workflow_post_auth")
    assert obs["method"] == "POST"
    assert obs["target"] == "/orgs/acme/orders"
    assert obs["body"] == '{"sku":"ABC","qty":3}'
    assert obs["contentType"] == "application/json; charset=utf-8"
    assert obs["headers"]["Authorization"] == "Bearer TOK123"
    assert obs["headers"]["Accept"] == "application/json"


# ===== tricky edge branches =====
def test_edge_nested_null_intermediate():
    """A dotted {a.b.c} placeholder with a null intermediate renders an empty segment."""
    obs = run("edge_nested_null_intermediate")
    assert obs["full"] == "/repos/me/acme"
    assert obs["nullMid"] == "/repos/me/"


def test_edge_query_prefix_nested():
    """[Query(delimiter, prefix)] flattens a complex object under a prefixed, delimited key."""
    assert run("edge_query_prefix_nested")["target"] == "/q?f.order=desc&f.Limit=10&f.Kind=bar"


def test_edge_query_format_numeric():
    """[Query(Format=\"0.00\")] applies the numeric format string to the value."""
    assert run("edge_query_format_numeric")["target"] == "/q?amount=5.00"


def test_edge_query_serializenull():
    """[Query(SerializeNull=true)] emits key= for a null property instead of omitting it."""
    assert run("edge_query_serializenull")["target"] == "/q?Note=&Count=3"


def test_edge_urlparam_formatter_map():
    """UrlParameterFormatterMap applies a per-type formatter to a path value by exact runtime type."""
    assert run("edge_urlparam_formatter_map")["target"] == "/at/20240102"


def test_edge_header_lastwrite():
    """When [HeaderCollection] and a [Header] set the same name, the later param wins."""
    assert run("edge_header_lastwrite")["headers"]["X-Dup"] == "fromParam"


def test_edge_validateheaders():
    """ValidateHeaders=true raises FormatException on a malformed header value."""
    assert run("edge_validateheaders")["exception"]["type"] == "FormatException"


def test_edge_implicit_body_multiple_complex():
    """Two complex candidates for the implicit body raise ArgumentException."""
    assert run("edge_implicit_body_multiple_complex")["exception"]["type"] == "ArgumentException"


def test_edge_multipart_date_guid():
    """Multipart DateTime/Guid parts are sent as plain-text parts (not JSON-quoted), one each in order."""
    parts = _parse_multipart(run("edge_multipart_date_guid"))
    assert [p["name"] for p in parts] == ["when", "id"]
    when_part, id_part = parts
    assert "2024" in when_part["content"] and not when_part["content"].startswith('"')  # date, not JSON-quoted
    assert id_part["content"] == "d1e9ea6b-2e8b-4699-93e0-0bcbd26c206c"  # Guid plain text, not quoted


def test_edge_body_buffered_contentlength():
    """[Body(buffered:true)] buffers the body so Content-Length is set. For an unknown-length (non-
    seekable) stream body this is observable as a contrast: buffered yields a Content-Length while the
    default (streamed) leaves it unset — so an impl that treats `buffered` as a no-op fails."""
    assert run("edge_body_buffered_contentlength")["hasContentLength"] is True
    obs = run("edge_body_buffered_stream_contentlength")
    assert obs["buffered"] is True
    assert obs["streamed"] is False
