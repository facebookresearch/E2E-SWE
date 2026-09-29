using System;
using System.Collections.Generic;
using System.Net.Http;
using System.Threading.Tasks;
using System.Runtime.CompilerServices;
using Restly;
using static Harness.H;

namespace Harness;

public interface IGenericApi<T>
{
    [Get("/g")]
    Task<T> Get();
}

public interface IEdgeGenericApi
{
    [Get("/g")]
    Task<T> GetGeneric<T>();
}

internal static class G_generics
{
    [ModuleInitializer]
    internal static void Register()
    {
        var S = Registry.Scenarios;

        S["generic_interface"] = async () =>
        {
            var (client, handler) = Client(_ => Responses.Ok("{\"id\":11,\"name\":\"gen\"}"));
            var api = RestlyClient.For<IGenericApi<User>>(client);
            var user = await api.Get();
            return Env(handler, "result", ("result", Json(user)));
        };

        S["edge_generic_method"] = async () =>
        {
            var (client, handler) = Client(_ => Responses.Ok("{\"id\":7,\"status\":\"done\"}"));
            var api = RestlyClient.For<IEdgeGenericApi>(client);
            var order = await api.GetGeneric<Order>();
            return Env(handler, "result", ("result", Json(order)));
        };
    }
}
