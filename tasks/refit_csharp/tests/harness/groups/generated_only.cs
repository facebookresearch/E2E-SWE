using System;
using System.Collections.Generic;
using System.Net.Http;
using System.Threading.Tasks;
using System.Runtime.CompilerServices;
using Restly;
using static Harness.H;

namespace Harness;

public interface IEncodedApi
{
    [Get("/e")]
    Task<User> Query([Encoded] string raw);

    [Get("/e/{seg}")]
    Task<User> Path([Encoded] string seg);
}

public interface IQueryNameApi
{
    [Get("/qn")]
    Task<User> Flag([QueryName] string flag);

    [Get("/qn")]
    Task<User> Flags([QueryName] string[] flags);
}

internal static class G_generated_only
{
    [ModuleInitializer]
    internal static void Register()
    {
        var S = Registry.Scenarios;

        S["encoded"] = async () =>
        {
            var (client, handler) = Client(_ => Responses.Ok("{}"));
            var api = RestlyClient.For<IEncodedApi>(client);
            await api.Query("a+b%20c");
            return Env(handler, "route", ("target", handler.Request!.RequestUri!.PathAndQuery));
        };

        S["encoded_path"] = async () =>
        {
            var (client, handler) = Client(_ => Responses.Ok("{}"));
            var api = RestlyClient.For<IEncodedApi>(client);
            await api.Path("a%2Fb");
            return Env(handler, "route", ("target", handler.Request!.RequestUri!.PathAndQuery));
        };

        S["queryname"] = async () =>
        {
            var (client, handler) = Client(_ => Responses.Ok("{}"));
            var api = RestlyClient.For<IQueryNameApi>(client);
            await api.Flag("archived");
            var single = handler.Request!.RequestUri!.PathAndQuery;
            await api.Flags(["a", "b"]);
            var multi = handler.Request!.RequestUri!.PathAndQuery;
            return Env(handler, "route", ("single", single), ("multi", multi));
        };
    }
}
