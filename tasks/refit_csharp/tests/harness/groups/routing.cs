using System;
using System.Collections.Generic;
using System.Net.Http;
using System.Threading.Tasks;
using System.Runtime.CompilerServices;
using Restly;
using static Harness.H;

namespace Harness;

public interface IVerbsApi
{
    [Get("/r")] Task Get();
    [Post("/r")] Task Post();
    [Put("/r")] Task Put();
    [Delete("/r")] Task Delete();
    [Patch("/r")] Task Patch();
    [Head("/r")] Task Head();
    [Options("/r")] Task Options();
}

public interface IRouteApi
{
    [Get("/search/{q}")]
    Task<User> SearchEscaped(string q);

    [Get("/search/{**page}")]
    Task<User> CatchAll(string page);

    [Get("/push/{deviceId}/{msgId?}")]
    Task<User> Optional(string deviceId, string? msgId);

    [Get("/group/{id}/users")]
    Task<User> Aliased([AliasAs("id")] int groupId);

    [Get("/group/{req.groupId}/users/{req.userId}")]
    Task<User> ByObject(UserGroupRequest req);
}

[PathPrefix("/api/v2")]
public interface IPrefixApi
{
    [Get("/users")]
    Task<User> All();
}

public interface IUrlApi
{
    [Get("")]
    Task<User> Fetch([Url] string absoluteUrl, [Query] string token);
}

public interface IRfcApi
{
    [Get("values")]
    Task<User> Append();

    [Get("/values")]
    Task<User> Replace();
}

public interface IEdgeRouteApi
{
    [Get("/a/{mid?}/b")]
    Task<Order> Interior(string? mid);

    [Get("/repos/{owner.Login}/{owner.Org.Name}")]
    Task<Order> Nested(Owner owner);

    [Get("/files/{**path}")]
    Task<Order> EncodedCatchAll([Encoded] string path);
}

internal static class G_routing
{
    [ModuleInitializer]
    internal static void Register()
    {
        var S = Registry.Scenarios;

        S["http_verbs"] = async () =>
        {
            var (client, handler) = Client(_ => Responses.Ok("{}"));
            var api = RestlyClient.For<IVerbsApi>(client);
            var methods = new List<string>();
            await api.Get(); methods.Add(handler.Request!.Method.Method);
            await api.Post(); methods.Add(handler.Request!.Method.Method);
            await api.Put(); methods.Add(handler.Request!.Method.Method);
            await api.Delete(); methods.Add(handler.Request!.Method.Method);
            await api.Patch(); methods.Add(handler.Request!.Method.Method);
            await api.Head(); methods.Add(handler.Request!.Method.Method);
            await api.Options(); methods.Add(handler.Request!.Method.Method);
            return Env(handler, "multi", ("methods", methods));
        };

        S["route_escaped"] = async () =>
        {
            var (client, handler) = Client(_ => Responses.Ok("{}"));
            var api = RestlyClient.For<IRouteApi>(client);
            await api.SearchEscaped("a b/c");
            return Env(handler, "route", ("target", handler.Request!.RequestUri!.PathAndQuery));
        };

        S["route_catchall"] = async () =>
        {
            var (client, handler) = Client(_ => Responses.Ok("{}"));
            var api = RestlyClient.For<IRouteApi>(client);
            await api.CatchAll("admin/products");
            return Env(handler, "route", ("target", handler.Request!.RequestUri!.PathAndQuery));
        };

        S["route_optional"] = async () =>
        {
            var (client, handler) = Client(_ => Responses.Ok("{}"));
            var api = RestlyClient.For<IRouteApi>(client);
            await api.Optional("dev1", "m42");
            var withValue = handler.Request!.RequestUri!.PathAndQuery;
            await api.Optional("dev1", null);
            var withNull = handler.Request!.RequestUri!.PathAndQuery;
            return Env(handler, "route", ("withValue", withValue), ("withNull", withNull));
        };

        S["route_aliased_and_object"] = async () =>
        {
            var (client, handler) = Client(_ => Responses.Ok("{}"));
            var api = RestlyClient.For<IRouteApi>(client);
            await api.Aliased(4);
            var aliased = handler.Request!.RequestUri!.PathAndQuery;
            await api.ByObject(new UserGroupRequest { GroupId = 1, UserId = 2 });
            var obj = handler.Request!.RequestUri!.PathAndQuery;
            return Env(handler, "route", ("aliased", aliased), ("obj", obj));
        };

        S["route_pathprefix"] = async () =>
        {
            var (client, handler) = Client(_ => Responses.Ok("{}"));
            var api = RestlyClient.For<IPrefixApi>(client);
            await api.All();
            return Env(handler, "route", ("target", handler.Request!.RequestUri!.PathAndQuery));
        };

        S["route_url_absolute"] = async () =>
        {
            var (client, handler) = Client(_ => Responses.Ok("{}"));
            var api = RestlyClient.For<IUrlApi>(client);
            await api.Fetch("https://cdn.example.com/data", "abc");
            return Env(handler, "route", ("uri", handler.Request!.RequestUri!.ToString()));
        };

        S["route_rfc3986"] = async () =>
        {
            var settings = new RestlySettings { UrlResolution = UrlResolutionMode.Rfc3986 };
            var (client, handler) = ClientWithBase("http://api.example.com/api/v1/", _ => Responses.Ok("{}"));
            var api = RestlyClient.For<IRfcApi>(client, settings);
            await api.Append();
            var append = handler.Request!.RequestUri!.ToString();
            await api.Replace();
            var replace = handler.Request!.RequestUri!.ToString();
            return Env(handler, "route", ("append", append), ("replace", replace));
        };

        S["edge_optional_interior"] = async () =>
        {
            var (client, handler) = Client(_ => Responses.Ok("{}"));
            var api = RestlyClient.For<IEdgeRouteApi>(client);
            await api.Interior("x");
            var withValue = handler.Request!.RequestUri!.PathAndQuery;
            await api.Interior(null);
            var withNull = handler.Request!.RequestUri!.PathAndQuery;
            return Env(handler, "route", ("withValue", withValue), ("withNull", withNull));
        };

        S["edge_nested_null_intermediate"] = async () =>
        {
            var (client, handler) = Client(_ => Responses.Ok("{}"));
            var api = RestlyClient.For<IEdgeRouteApi>(client);
            await api.Nested(new Owner { Login = "me", Org = new Org { Name = "acme" } });
            var full = handler.Request!.RequestUri!.PathAndQuery;
            await api.Nested(new Owner { Login = "me", Org = null });
            var nullMid = handler.Request!.RequestUri!.PathAndQuery;
            return Env(handler, "route", ("full", full), ("nullMid", nullMid));
        };

        S["edge_encoded_catchall"] = async () =>
        {
            var (client, handler) = Client(_ => Responses.Ok("{}"));
            var api = RestlyClient.For<IEdgeRouteApi>(client);
            await api.EncodedCatchAll("a/b%20c");
            return Env(handler, "route", ("target", handler.Request!.RequestUri!.PathAndQuery));
        };
    }
}
