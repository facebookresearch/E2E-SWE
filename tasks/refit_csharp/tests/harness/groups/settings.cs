using System;
using System.Collections.Generic;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;
using System.Runtime.CompilerServices;
using Restly;
using static Harness.H;

namespace Harness;

public interface ITimeoutApi
{
    [Timeout(50)]
    [Get("/t")]
    Task<User> Slow();
}

public interface ICancelApi
{
    [Get("/c")]
    Task<User> Get(CancellationToken token);
}

internal static class G_settings
{
    [ModuleInitializer]
    internal static void Register()
    {
        var S = Registry.Scenarios;

        S["settings_timeout"] = async () =>
        {
            var handler = new DelayHandler(1000, _ => Responses.Ok("{}"));
            var client = new HttpClient(handler) { BaseAddress = new Uri(BaseUrl), Timeout = Timeout.InfiniteTimeSpan };
            var api = RestlyClient.For<ITimeoutApi>(client);
            try
            {
                await api.Slow();
                return new Dictionary<string, object?> { ["outcome"] = "exception", ["exception"] = new Dictionary<string, object?> { ["type"] = "NONE" } };
            }
            catch (Exception ex)
            {
                return new Dictionary<string, object?> { ["outcome"] = "exception", ["exception"] = new Dictionary<string, object?> { ["type"] = ex.GetType().Name } };
            }
        };

        S["settings_cancellation"] = async () =>
        {
            var (client, handler) = Client(_ => Responses.Ok("{}"));
            var api = RestlyClient.For<ICancelApi>(client);
            using var cts = new CancellationTokenSource();
            cts.Cancel();
            try
            {
                await api.Get(cts.Token);
                return new Dictionary<string, object?> { ["outcome"] = "exception", ["exception"] = new Dictionary<string, object?> { ["type"] = "NONE" } };
            }
            catch (Exception ex)
            {
                return new Dictionary<string, object?> { ["outcome"] = "exception", ["exception"] = new Dictionary<string, object?> { ["type"] = ex.GetType().Name } };
            }
        };
    }
}
