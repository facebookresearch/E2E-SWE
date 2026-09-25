using System;
using System.Collections.Generic;
using System.Net.Http;
using System.Threading.Tasks;
using System.Runtime.CompilerServices;
using Restly;
using static Harness.H;

namespace Harness;

public interface IPropApi
{
    [Get("/p")]
    Task<User> WithProp([Property("trace-id")] string id);

    [Property("tenant")]
    string Tenant { get; set; }

    [Get("/p")]
    Task<User> WithIfaceProp();
}

internal static class G_settings_property
{
    [ModuleInitializer]
    internal static void Register()
    {
        var S = Registry.Scenarios;

        S["settings_property_param"] = async () =>
        {
            var (client, handler) = Client(_ => Responses.Ok("{}"));
            var api = RestlyClient.For<IPropApi>(client);
            await api.WithProp("t123");
            return Env(handler, "route");
        };

        S["settings_property_interface"] = async () =>
        {
            var (client, handler) = Client(_ => Responses.Ok("{}"));
            var api = RestlyClient.For<IPropApi>(client);
            api.Tenant = "acme";
            await api.WithIfaceProp();
            return Env(handler, "route");
        };
    }
}
