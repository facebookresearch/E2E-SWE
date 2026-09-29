# A type-safe REST client for .NET

This library turns an annotated C# interface into a REST client. A caller declares an interface whose
methods carry HTTP attributes; your library produces an implementation that builds an
`HttpRequestMessage` from those attributes, sends it with `HttpClient`, and deserializes the response
into the method's return type.

```csharp
public interface IUserApi
{
    [Get("/users/{user}")]
    Task<User> GetUser(string user);
}

var api = RestlyClient.For<IUserApi>("https://api.example.com");
var alice = await api.GetUser("alice");   // GET https://api.example.com/users/alice
```

All public types live in the `Restly` namespace.

## How your library is consumed

A separate C# project (which you don't see) declares its own annotated interfaces, references your
assemblies, and calls `RestlyClient.For<T>(...)`. Two consequences follow:

- The library has no runtime proxy. The interface implementation is emitted at compile time by a Roslyn
  source generator that you ship: it runs inside the consumer's build and generates an implementing class
  for each annotated interface, which `RestlyClient.For<T>` then finds and instantiates.
- The consumer compiles against your assemblies, so the "Public API shapes" below must match exactly; the
  behavior behind that API is yours to design.

Deliver build outputs in this layout, produced by an executable `/app/setup.sh` that builds offline:

- `/app/dist/lib/*.dll` — runtime assemblies (RestlyClient, the attributes, RestlySettings, …), which the
  consumer references.
- `/app/dist/analyzers/*.dll` — your source generator(s), which the consumer loads as analyzers.

## Environment

There is no network. The .NET 10 SDK and a local NuGet feed are installed; build offline. Target
`net10.0` for the runtime library and `netstandard2.0` for the generator. The feed has
`Microsoft.CodeAnalysis.CSharp` 5.0.0 and `Microsoft.CodeAnalysis.Analyzers` 5.6.0 (for the generator).
`System.Text.Json`, `System.Net.Http.Json`, and `System.Net.ServerSentEvents` ship with the
net10 framework — no package needed. System.Text.Json is the default serializer.

## Public API shapes

Match these by name and signature so the consumer compiles; the behavior is described in later sections.

- Enums: `CollectionFormat { Csv, Ssv, Tsv, Pipes, Multi }` (plus a default member),
  `BodySerializationMethod { Default, Json, UrlEncoded, JsonLines, Serialized }`,
  `UrlResolutionMode { RestlyLegacy, Rfc3986 }`. `[QueryUriFormat]` takes `System.UriFormat` — do not
  define your own.
- `RestlySettings`: a parameterless constructor; settable `UrlResolution`, `CollectionFormat`,
  `ValidateHeaders`, `AllowUnmatchedRouteParameters`, `HttpRequestMessageOptions`
  (`Dictionary<string, object>`), `UrlParameterFormatterMap` (`IDictionary<Type, IUrlParameterFormatter>`),
  `AuthorizationHeaderValueGetter` (`Func<HttpRequestMessage, CancellationToken, ValueTask<string>>`),
  `ExceptionFactory` (`Func<HttpResponseMessage, ValueTask<Exception?>>`); and static factories
  `SnakeCase()`, `KebabCase()`, `CamelCase()`.
- `IUrlParameterFormatter`:
  `string? Format(object? value, System.Reflection.ICustomAttributeProvider attributeProvider, Type type)`.
- Multipart wrappers, ctor `(value, string fileName, string? contentType = null, string? name = null)`:
  `StreamPart(Stream …)`, `ByteArrayPart(byte[] …)`, `FileInfoPart(FileInfo …)`.
- `ApiResponse<T>` / `IApiResponse<T>` / `IApiResponse` and `ProblemDetails` — members are listed under
  Responses and Errors.

## Creating clients

`RestlyClient.For<T>` returns an implementation of `T`:

- `For<T>(HttpClient client)` and `For<T>(HttpClient client, RestlySettings? settings)` use the client's
  `BaseAddress` as the base URL.
- `For<T>(string hostUrl)` and `For<T>(string hostUrl, RestlySettings? settings)` build an `HttpClient` for
  that base address.

Each method needs exactly one HTTP method attribute.

## URLs

The method attributes `[Get] [Post] [Put] [Delete] [Patch] [Head] [Options]` take a relative path and map
to the matching HTTP method.

A path may contain `{placeholder}` blocks bound to parameters by name (case-insensitive). A parameter not
consumed by the path or another binding becomes a query parameter.

- A normal `{placeholder}` percent-escapes its value (space → `%20`, `/` → `%2F`, and so on).
- Before escaping, a `{placeholder}` value is passed through the same URL-parameter value formatter as a
  query value — a matching `UrlParameterFormatterMap[type]` entry (by exact runtime type), else
  `UrlParameterFormatter` (see Query strings) — falling back to the default rendering when neither is set.
- `[AliasAs("name")]` maps a parameter to a differently named placeholder or query key.
- `{obj.Prop}` binds to a property of an object parameter; dotted chains like `{obj.A.B}` work, and a null
  link in the chain renders that segment empty (e.g. `/repos/me/`).
- Catch-all `{**name}` keeps the slashes in its value (each segment is still escaped).
- Optional `{name?}`: a null value drops the segment and its leading slash, collapsing interior gaps (no
  `//`); a non-null value, including empty string, renders like a normal placeholder.
- `[Encoded]` passes a value through verbatim, with no escaping, for path segments (including `{**name}`)
  and query values.
- `[PathPrefix("/api/v2")]` on the interface prepends a prefix to every route with a single `/` between
  them. A method uses the prefix of the interface that declares it; prefixes are not concatenated across
  inheritance.
- `[Url]` on a `string`/`Uri` parameter is the entire absolute URI (the base address is ignored); the
  route template must be empty and `[Query]` parameters are still appended.
- A placeholder with no matching parameter throws `ArgumentException`, unless
  `AllowUnmatchedRouteParameters` is set, which leaves the `{token}` in the path.

`UrlResolution` chooses how the base address and route combine. `RestlyLegacy` (default) trims a trailing
slash from the base and prepends its path. `Rfc3986` follows `System.Uri` rules: a route without a leading
slash appends to the base path, one with a leading slash replaces it, and the base's trailing slash is
significant.

## Query strings

- A complex object parameter flattens to its public, non-null properties. Key name precedence:
  `[AliasAs]`, else the serializer's JSON name (e.g. `[JsonPropertyName]`), else the key formatter, else
  the CLR property name.
- An `IDictionary` parameter emits one `key=value` per entry. Nested objects and dictionaries flatten with
  a `.` between segments (e.g. `Address.City`, `Meta.k`).
- `[Query(delimiter, prefix)]` on a complex parameter names keys `{prefix}{delimiter}{name}` (so
  `[Query(".", "f")]` gives `f.order=…`). `[Query(Format = "0.00")]` applies a .NET format string to the
  value. `[Query(SerializeNull = true)]` on a property emits `key=` for a null value instead of dropping
  it.
- Collections use `[Query(CollectionFormat.X)]`: `Multi` emits one pair per element; `Csv`/`Ssv`/`Tsv`/
  `Pipes` join with `,`/space/tab/`|` and then escape the joined value. `RestlySettings.CollectionFormat`
  supplies the default when a parameter has no explicit `[Query]`; that default member joins multiple
  values with a comma (like `Csv`). A per-parameter `[Query]` overrides it.
- `[QueryUriFormat(System.UriFormat.Unescaped)]` on a method leaves the query string unescaped.
- `[QueryName]` renders the value as a valueless flag (`?archived`); a collection yields one flag per
  element (`?a&b`).
- Enum values render by name, or by `[EnumMember(Value="…")]` when present, in query values.
- `UrlParameterKeyFormatter`, and the `SnakeCase()`/`KebabCase()`/`CamelCase()` presets, reformat
  query-object property keys (not bare parameter names); `CamelCase()` uses the System.Text.Json
  camelCase policy (the leading run of uppercase letters is lowercased, e.g. `APIKey`→`apiKey`).
  `UrlParameterFormatter` and
  `UrlParameterFormatterMap[type]` (matched by exact runtime type) customize value rendering; a formatter
  that returns null drops the parameter.

## Headers and authorization

- `[Headers("Name: Value", …)]` on the interface and/or a method sets static headers; a method value
  overrides the interface for the same name. A line with no colon removes the header; a colon with an
  empty value sends an empty one.
- `[Header("Name")]` sets a header from a parameter: null omits it, empty sends an empty header, and a
  non-string uses `ToString()`.
- `[Authorize("scheme")]` sets `Authorization: <scheme> <token>` (the scheme defaults to `Bearer`).
- `[HeaderCollection]` on an `IDictionary<string,string>` merges each entry (a null dictionary is a
  no-op). When it and a `[Header]`/`[Authorize]` set the same header, the later parameter wins.
- `AuthorizationHeaderValueGetter`: when a request's `Authorization` header is only a scheme (e.g. from
  `[Headers("Authorization: Bearer")]`), the getter supplies the token; a null/empty/whitespace result
  omits the header, and an explicit token is left untouched.
- Each method carries the `[Headers]` of the interface that declares it.
- Content headers such as `Content-Type` are applied to the request content, including when set via
  `[Header("Content-Type")]` or a static header.
- `ValidateHeaders` (default false): off, values are sent verbatim; on, a malformed value throws
  `FormatException`.

## Request body

Use `[Body]`, or on `POST`/`PUT`/`PATCH` a single complex reference-type parameter (not `string`, not a
value type, not one carrying `[Query]`/`[Header*]`/`[Property]`/`[Url]`) becomes the body implicitly. More
than one candidate, or more than one `[Body]`, throws `ArgumentException`.

- `Stream` streams as-is; `HttpContent` is used directly.
- A `string` is sent verbatim as `text/plain; charset=utf-8`, or as a JSON string with
  `[Body(BodySerializationMethod.Json)]`.
- Any other object serializes as JSON (`application/json; charset=utf-8`).
- `[Body(BodySerializationMethod.UrlEncoded)]` sends `application/x-www-form-urlencoded`: an object's field
  names are the CLR property names verbatim (not camelCased), `[AliasAs]` overrides, and nulls are
  omitted; an `IDictionary` emits `key=value` pairs; a `string` is sent percent-escaped
  (`Uri.EscapeDataString`).
- `[Body(BodySerializationMethod.JsonLines)]` on an enumerable sends the JSON documents joined by `\n`
  (one document per line, with no trailing newline after the last document), with content type
  `application/x-ndjson` and no `charset` parameter.
- `[Body(buffered: true)]` buffers the body so a `Content-Length` header is set.

JSON uses camelCase property names and case-insensitive deserialization.

`[Multipart]` sends `multipart/form-data` (default boundary `----MyGreatBoundary`). A part's field name
is, in order of precedence, the wrapper's `name`, then `[AliasAs]`, then the parameter name. Part
parameters may be the wrappers `StreamPart`/`ByteArrayPart`/`FileInfoPart` (each with a filename, an
optional content type, and an optional overriding name); a raw `byte[]` or `Stream` (whose part filename
defaults to the parameter name); a raw `FileInfo` (whose filename is the underlying file's own name); a
raw `string` or a JSON-serializable object (no filename); or `DateTime`/`Guid`, which are written as plain
text (not JSON-quoted). An `IEnumerable` of parts emits one part per element under the same field name.

## Responses

The return type drives response handling:

- `Task` sends and ignores the body.
- `Task<T>` deserializes the body; a 204 or empty body yields `default`.
- `Task<string>` returns the raw body, `Task<Stream>` the unbuffered stream, and
  `Task<HttpResponseMessage>` the raw response with no error handling (a non-success status is returned,
  not thrown).
- `Task<ApiResponse<T>>`, `Task<IApiResponse<T>>`, and `Task<IApiResponse>` never throw — HTTP and
  deserialization errors are captured (see Errors). `ValueTask<…>` behaves like `Task<…>`.
- `IAsyncEnumerable<T>` streams items, choosing the frame format from the response content type: a JSON
  array (default, or `application/json`), JSON Lines (`application/x-ndjson`), or Server-Sent Events
  (`text/event-stream`, one item per `data:` event). Before streaming, a non-success status is handled
  like `Task<T>` (including `ExceptionFactory`, whose null return suppresses the throw).

`ApiResponse<T>` exposes `Content`, `StatusCode`, `Headers`, `ContentHeaders`, `ReasonPhrase`,
`RequestMessage`, `IsSuccessStatusCode`, `IsSuccessful`, `HasContent`, `Error`, and
`EnsureSuccessStatusCodeAsync()` / `EnsureSuccessfulAsync()`. `IsSuccessStatusCode` reflects the HTTP
status; `IsSuccessful` is true only when the status is a success and no error was captured — so a 2xx
whose body fails to deserialize has `IsSuccessStatusCode == true`, `IsSuccessful == false`, and `Error`
set. `EnsureSuccessStatusCodeAsync` checks the status only (it won't throw in that case), while
`EnsureSuccessfulAsync` throws.

## Errors

- For `Task`/`Task<T>` and the raw returns, a non-success status throws `ApiException` carrying
  `StatusCode`, `Content` (the raw error body), `ReasonPhrase`, `Headers`, `HttpMethod`, `Uri`, and
  `GetContentAsAsync<T>()`. When the error content type is `application/problem+json`, it instead throws
  `ValidationApiException` (a subclass) whose `Content` is a `ProblemDetails` (`Title`, `Status`,
  `Detail`, `Type`, `Errors`, and `Extensions` for any unknown members). `Type` defaults to
  `"about:blank"` (RFC 7807) when the payload omits it.
- A deserialization failure on a 2xx response throws `ApiException` whose `InnerException` is the
  `JsonException`.
- The `ApiResponse`/`IApiResponse` wrappers capture all of the above into `Error` instead of throwing.
- A transport failure (the send itself throws) surfaces as `ApiRequestException` wrapping the original
  exception (captured into `Error` for the wrapper return types).
- `RestlySettings` hooks: `ExceptionFactory` (maps a response to an exception; returning null suppresses
  the throw) and `DeserializationExceptionFactory`
  (`Func<HttpResponseMessage, Exception, ValueTask<Exception?>>` — maps a deserialization failure and
  the response to an exception; the returned exception is thrown instead of the default).

## Other behavior

- `[Property("key")]` on a parameter stores its value in `HttpRequestMessage.Options` under that key.
  `[Property]` on an interface property stores that value on every request.
- Each request's `Options` also carries `Restly.MethodName`, `Restly.RelativePathTemplate` (the raw route
  template with `{placeholders}`, not the filled URL), and `Restly.InterfaceType` (the top-level
  interface).
- `[Timeout(ms)]` cancels the request after the given time (a cancellation such as
  `TaskCanceledException`). A `CancellationToken` parameter is honored: a pre-cancelled token cancels the
  call, surfacing as a `TaskCanceledException`.
- Generic interfaces and generic methods are supported. A client also exposes methods inherited from base
  interfaces; a base method that has no HTTP attribute is still implemented but throws
  `NotImplementedException` when called.
