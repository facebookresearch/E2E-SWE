using System;
using System.Collections.Generic;
using System.Net.Http;
using System.Threading.Tasks;
using System.Runtime.CompilerServices;
using Restly;
using static Harness.H;

namespace Harness;

[Headers("User-Agent: RestlyTest", "X-Static: iface")]
public interface IHeaderApi
{
    [Get("/h")]
    Task<User> Static();

    [Headers("X-Static: method")]
    [Get("/h")]
    Task<User> MethodOverride();

    [Get("/h")]
    Task<User> Dynamic([Header("X-Trace")] string? trace);

    [Get("/h")]
    Task<User> Auth([Authorize("Bearer")] string token);

    [Get("/h")]
    Task<User> AuthDefault([Authorize] string token);

    [Get("/h")]
    Task<User> Collection([HeaderCollection] IDictionary<string, string> headers);

    [Post("/h")]
    Task<User> ContentTypeOverride([Header("Content-Type")] string contentType, [Body] string raw);
}

[Headers("Authorization: Bearer")]
public interface IAuthGetterApi
{
    [Get("/h")]
    Task<User> Get();
}

[Headers("X-Level: base")]
public interface IBaseHeaders
{
    [Get("/base")]
    Task<User> Ping();
}

[Headers("X-Level: derived")]
public interface IDerivedHeaders : IBaseHeaders
{
    [Get("/derived")]
    Task<User> Pong();
}

public interface IEdgeHeaderApi
{
    [Get("/h")]
    Task<Order> LastWrite([HeaderCollection] IDictionary<string, string> headers, [Header("X-Dup")] string dup);

    [Get("/h")]
    Task<Order> Malformed([Header("If-Modified-Since")] string value);
}

internal static class G_headers
{
    [ModuleInitializer]
    internal static void Register()
    {
        var S = Registry.Scenarios;

        S["headers_static"] = async () =>
        {
            var (client, handler) = Client(_ => Responses.Ok("{}"));
            var api = RestlyClient.For<IHeaderApi>(client);
            await api.Static();
            return Env(handler, "route", ("headers", HeadersOf(handler)));
        };

        S["headers_method_override"] = async () =>
        {
            var (client, handler) = Client(_ => Responses.Ok("{}"));
            var api = RestlyClient.For<IHeaderApi>(client);
            await api.MethodOverride();
            return Env(handler, "route", ("headers", HeadersOf(handler)));
        };

        S["headers_dynamic"] = async () =>
        {
            var (client, handler) = Client(_ => Responses.Ok("{}"));
            var api = RestlyClient.For<IHeaderApi>(client);
            await api.Dynamic("abc");
            var withValue = HeadersOf(handler);
            await api.Dynamic(null);
            var withNull = HeadersOf(handler);
            return Env(handler, "route", ("withValue", withValue), ("withNull", withNull));
        };

        S["headers_authorize"] = async () =>
        {
            var (client, handler) = Client(_ => Responses.Ok("{}"));
            var api = RestlyClient.For<IHeaderApi>(client);
            await api.Auth("TOK");
            return Env(handler, "route", ("headers", HeadersOf(handler)));
        };

        S["headers_authorize_default"] = async () =>
        {
            var (client, handler) = Client(_ => Responses.Ok("{}"));
            var api = RestlyClient.For<IHeaderApi>(client);
            await api.AuthDefault("TOK");
            return Env(handler, "route", ("headers", HeadersOf(handler)));
        };

        S["headers_collection"] = async () =>
        {
            var (client, handler) = Client(_ => Responses.Ok("{}"));
            var api = RestlyClient.For<IHeaderApi>(client);
            await api.Collection(new Dictionary<string, string> { ["Authorization"] = "Bearer x", ["X-Tenant-Id"] = "123" });
            return Env(handler, "route", ("headers", HeadersOf(handler)));
        };

        S["headers_auth_getter"] = async () =>
        {
            var settings = new RestlySettings { AuthorizationHeaderValueGetter = (_, _) => new ValueTask<string>("TOKEN123") };
            var (client, handler) = Client(_ => Responses.Ok("{}"));
            var api = RestlyClient.For<IAuthGetterApi>(client, settings);
            await api.Get();
            return Env(handler, "route", ("headers", HeadersOf(handler)));
        };

        S["headers_auth_getter_empty"] = async () =>
        {
            var settings = new RestlySettings { AuthorizationHeaderValueGetter = (_, _) => new ValueTask<string>("") };
            var (client, handler) = Client(_ => Responses.Ok("{}"));
            var api = RestlyClient.For<IAuthGetterApi>(client, settings);
            await api.Get();
            return Env(handler, "route", ("headers", HeadersOf(handler)));
        };

        S["headers_inheritance"] = async () =>
        {
            var (client, handler) = Client(_ => Responses.Ok("{}"));
            var api = RestlyClient.For<IDerivedHeaders>(client);
            await api.Ping();
            var ping = HeadersOf(handler);
            await api.Pong();
            var pong = HeadersOf(handler);
            return Env(handler, "route", ("ping", ping), ("pong", pong));
        };

        S["headers_content_type"] = async () =>
        {
            var (client, handler) = Client(_ => Responses.Ok("{}"));
            var api = RestlyClient.For<IHeaderApi>(client);
            await api.ContentTypeOverride("application/xml", "<x/>");
            return Env(handler, "route", ("contentType", ContentType(handler)), ("body", handler.Body));
        };

        S["edge_header_lastwrite"] = async () =>
        {
            var (client, handler) = Client(_ => Responses.Ok("{}"));
            var api = RestlyClient.For<IEdgeHeaderApi>(client);
            await api.LastWrite(new Dictionary<string, string> { ["X-Dup"] = "fromCollection" }, "fromParam");
            return Env(handler, "route", ("headers", HeadersOf(handler)));
        };

        S["edge_validateheaders"] = async () =>
        {
            var settings = new RestlySettings { ValidateHeaders = true };
            var (client, handler) = Client(_ => Responses.Ok("{}"));
            var api = RestlyClient.For<IEdgeHeaderApi>(client, settings);
            try
            {
                await api.Malformed("not a date");
                return new Dictionary<string, object?> { ["outcome"] = "exception", ["exception"] = new Dictionary<string, object?> { ["type"] = "NONE" } };
            }
            catch (Exception ex)
            {
                return new Dictionary<string, object?> { ["outcome"] = "exception", ["exception"] = new Dictionary<string, object?> { ["type"] = ex.GetType().Name } };
            }
        };
    }
}
