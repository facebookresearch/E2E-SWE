using System;
using System.Collections.Generic;
using System.IO;
using System.Net.Http;
using System.Text;
using System.Threading.Tasks;
using System.Runtime.CompilerServices;
using Restly;
using static Harness.H;

namespace Harness;

[Headers("X-Client: shop")]
public interface IShopApi
{
    [Get("/orgs/{org}/orders")]
    Task<Order> ListOrders(string org, OrderQuery query, [Header("X-Request-Id")] string requestId);

    [Headers("Accept: application/json")]
    [Post("/orgs/{org}/orders")]
    Task<Order> Create(string org, [Body] NewOrder body, [Authorize("Bearer")] string token);

    [Multipart]
    [Post("/uploads")]
    Task<Order> Upload(StreamPart file, string label, DateTime takenAt);
}

internal static class G_workflows
{
    [ModuleInitializer]
    internal static void Register()
    {
        var S = Registry.Scenarios;

        S["workflow_get"] = async () =>
        {
            var (client, handler) = Client(_ => Responses.Ok("{\"id\":1,\"status\":\"open\"}"));
            var api = RestlyClient.For<IShopApi>(client);
            await api.ListOrders("acme", new OrderQuery { SortBy = "date", Limit = 20, Priority = Priority.High }, "req-99");
            return Env(handler, "route",
                ("target", handler.Request!.RequestUri!.PathAndQuery),
                ("headers", HeadersOf(handler)));
        };

        S["workflow_post_auth"] = async () =>
        {
            var (client, handler) = Client(_ => Responses.Ok("{\"id\":2,\"status\":\"new\"}"));
            var api = RestlyClient.For<IShopApi>(client);
            await api.Create("acme", new NewOrder { Sku = "ABC", Qty = 3 }, "TOK123");
            return Env(handler, "route",
                ("method", handler.Request!.Method.Method),
                ("target", handler.Request!.RequestUri!.PathAndQuery),
                ("body", handler.Body),
                ("contentType", ContentType(handler)),
                ("headers", HeadersOf(handler)));
        };

        S["workflow_multipart"] = async () =>
        {
            var (client, handler) = Client(_ => Responses.Ok("{}"));
            var api = RestlyClient.For<IShopApi>(client);
            var part = new StreamPart(new MemoryStream(Encoding.UTF8.GetBytes("img")), "p.jpg", "image/jpeg");
            await api.Upload(part, "vacation", new DateTime(2024, 1, 2, 3, 4, 5, DateTimeKind.Utc));
            return Env(handler, "route", ("contentType", ContentType(handler)), ("body", handler.Body));
        };
    }
}
