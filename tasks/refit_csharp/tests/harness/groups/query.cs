using System;
using System.Collections.Generic;
using System.Net.Http;
using System.Threading.Tasks;
using System.Runtime.CompilerServices;
using Restly;
using static Harness.H;

namespace Harness;

public interface IQueryApi
{
    [Get("/q")]
    Task<User> Obj(MyQuery p);

    [Get("/q")]
    Task<User> Csv([Query(CollectionFormat.Csv)] int[] ages);

    [Get("/q")]
    Task<User> Dict(IDictionary<string, object> filters);

    [Get("/q")]
    [QueryUriFormat(System.UriFormat.Unescaped)]
    Task<User> Unescaped(string expr);
}

public interface ISnakeQueryApi
{
    [Get("/q")]
    Task<User> Search(SnakeQuery p);
}

public interface IAcroQueryApi
{
    [Get("/q")]
    Task<User> Search(AcroQuery p);
}

public interface IDeepQueryApi
{
    [Get("/dq")]
    Task<Order> Deep(DeepQuery q);
}

public interface IEdgeQueryApi
{
    [Get("/q")]
    Task<Order> Prefixed([Query(".", "f")] MyQuery p);

    [Get("/q")]
    Task<Order> Numeric([Query(Format = "0.00")] double amount);

    [Get("/q")]
    Task<Order> Nullable(NullableQuery p);

    [Get("/at/{when}")]
    Task<Order> At(DateTime when);
}

internal static class G_query
{
    [ModuleInitializer]
    internal static void Register()
    {
        var S = Registry.Scenarios;

        S["query_object"] = async () =>
        {
            var (client, handler) = Client(_ => Responses.Ok("{}"));
            var api = RestlyClient.For<IQueryApi>(client);
            await api.Obj(new MyQuery { SortOrder = "desc", Limit = 10, Kind = KindOptions.Bar });
            return Env(handler, "route", ("target", handler.Request!.RequestUri!.PathAndQuery));
        };

        S["query_csv"] = async () =>
        {
            var (client, handler) = Client(_ => Responses.Ok("{}"));
            var api = RestlyClient.For<IQueryApi>(client);
            await api.Csv([10, 20, 30]);
            return Env(handler, "route", ("target", handler.Request!.RequestUri!.PathAndQuery));
        };

        S["query_dictionary"] = async () =>
        {
            var (client, handler) = Client(_ => Responses.Ok("{}"));
            var api = RestlyClient.For<IQueryApi>(client);
            await api.Dict(new Dictionary<string, object> { ["status"] = "active", ["page"] = 2 });
            return Env(handler, "route", ("target", handler.Request!.RequestUri!.PathAndQuery));
        };

        S["query_unescaped"] = async () =>
        {
            var (client, handler) = Client(_ => Responses.Ok("{}"));
            var api = RestlyClient.For<IQueryApi>(client);
            await api.Unescaped("Select+Id,Name");
            return Env(handler, "route", ("target", handler.Request!.RequestUri!.PathAndQuery));
        };

        S["query_snakecase"] = async () =>
        {
            var (client, handler) = Client(_ => Responses.Ok("{}"));
            var api = RestlyClient.For<ISnakeQueryApi>(client, RestlySettings.SnakeCase());
            await api.Search(new SnakeQuery { SortOrder = "desc", PageSize = 50 });
            return Env(handler, "route", ("target", handler.Request!.RequestUri!.PathAndQuery));
        };

        S["query_camelcase"] = async () =>
        {
            var (client, handler) = Client(_ => Responses.Ok("{}"));
            var api = RestlyClient.For<IAcroQueryApi>(client, RestlySettings.CamelCase());
            await api.Search(new AcroQuery { APIKey = "k", IOSize = 4 });
            return Env(handler, "route", ("target", handler.Request!.RequestUri!.PathAndQuery));
        };

        S["query_deep_nested"] = async () =>
        {
            var (client, handler) = Client(_ => Responses.Ok("{}"));
            var api = RestlyClient.For<IDeepQueryApi>(client);
            await api.Deep(new DeepQuery
            {
                Name = "x",
                Address = new Address { City = "NYC", Zip = 10001 },
                Tags = [1, 2],
                Meta = new Dictionary<string, string> { ["k"] = "v" },
            });
            return Env(handler, "route", ("target", handler.Request!.RequestUri!.PathAndQuery));
        };

        S["edge_query_prefix_nested"] = async () =>
        {
            var (client, handler) = Client(_ => Responses.Ok("{}"));
            var api = RestlyClient.For<IEdgeQueryApi>(client);
            await api.Prefixed(new MyQuery { SortOrder = "desc", Limit = 10, Kind = KindOptions.Bar });
            return Env(handler, "route", ("target", handler.Request!.RequestUri!.PathAndQuery));
        };

        S["edge_query_format_numeric"] = async () =>
        {
            var (client, handler) = Client(_ => Responses.Ok("{}"));
            var api = RestlyClient.For<IEdgeQueryApi>(client);
            await api.Numeric(5);
            return Env(handler, "route", ("target", handler.Request!.RequestUri!.PathAndQuery));
        };

        S["edge_query_serializenull"] = async () =>
        {
            var (client, handler) = Client(_ => Responses.Ok("{}"));
            var api = RestlyClient.For<IEdgeQueryApi>(client);
            await api.Nullable(new NullableQuery { Note = null, Count = 3 });
            return Env(handler, "route", ("target", handler.Request!.RequestUri!.PathAndQuery));
        };

        S["edge_urlparam_formatter_map"] = async () =>
        {
            var settings = new RestlySettings();
            settings.UrlParameterFormatterMap[typeof(DateTime)] = new DateStampFormatter();
            var (client, handler) = Client(_ => Responses.Ok("{}"));
            var api = RestlyClient.For<IEdgeQueryApi>(client, settings);
            await api.At(new DateTime(2024, 1, 2, 0, 0, 0, DateTimeKind.Utc));
            return Env(handler, "route", ("target", handler.Request!.RequestUri!.PathAndQuery));
        };
    }
}
