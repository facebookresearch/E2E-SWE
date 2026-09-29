using System;
using System.Collections.Generic;
using System.Net;
using System.Net.Http;
using System.Threading.Tasks;
using System.Runtime.CompilerServices;
using Restly;
using static Harness.H;

namespace Harness;

public interface IDeserApi
{
    [Get("/d")]
    Task<int> GetInt();
}

// Isolated group: DeserializationExceptionFactory is a less-common RestlySettings hook, so a solution
// that omits the member only fails this one test rather than cascading a shared group.
internal static class G_deser
{
    [ModuleInitializer]
    internal static void Register()
    {
        var S = Registry.Scenarios;

        S["deser_factory"] = async () =>
        {
            // On a 2xx whose body can't deserialize, a custom DeserializationExceptionFactory maps the
            // failure to its OWN exception, which must be the one thrown.
            var settings = new RestlySettings
            {
                DeserializationExceptionFactory = (response, error) =>
                    new ValueTask<Exception?>(new InvalidOperationException("custom-deser")),
            };
            var (client, handler) = Client(_ => Responses.Json(HttpStatusCode.OK, "notanint", "application/json"));
            var api = RestlyClient.For<IDeserApi>(client, settings);
            try
            {
                await api.GetInt();
                return Env(handler, "exception", ("exception", new Dictionary<string, object?> { ["type"] = "NONE" }));
            }
            catch (Exception ex)
            {
                return Env(handler, "exception", ("exception", ExceptionBlock(ex)));
            }
        };
    }
}
