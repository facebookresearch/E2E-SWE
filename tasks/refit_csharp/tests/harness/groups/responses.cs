using System;
using System.Collections.Generic;
using System.Net;
using System.Net.Http;
using System.Threading.Tasks;
using System.Runtime.CompilerServices;
using Restly;
using static Harness.H;

namespace Harness;

public interface IRespApi
{
    [Get("/r")] Task<User> Get();
    [Get("/r")] Task<string> Raw();
    [Get("/r")] Task<int> GetInt();
    [Get("/r")] Task<ApiResponse<User>> Resp();
    [Get("/r")] Task<HttpResponseMessage> Message();
}

public interface IStreamApi
{
    [Get("/s")]
    IAsyncEnumerable<User> Stream();
}

public interface IEdgeRespApi
{
    [Get("/p")]
    Task<Order> Problem();
}

internal static class G_responses
{
    private static async Task<List<object>> Collect(IStreamApi api)
    {
        var items = new List<object>();
        await foreach (var u in api.Stream())
        {
            items.Add(new { id = u.Id, name = u.Name });
        }

        return items;
    }

    [ModuleInitializer]
    internal static void Register()
    {
        var S = Registry.Scenarios;

        S["resp_204_null"] = async () =>
        {
            var (client, handler) = Client(_ => new HttpResponseMessage(HttpStatusCode.NoContent));
            var api = RestlyClient.For<IRespApi>(client);
            var user = await api.Get();
            return Env(handler, "result", ("result", Json(user)));
        };

        S["resp_raw_string"] = async () =>
        {
            var (client, handler) = Client(_ => Responses.Json(HttpStatusCode.OK, "raw text", "text/plain"));
            var api = RestlyClient.For<IRespApi>(client);
            var s = await api.Raw();
            return Env(handler, "raw", ("raw", s));
        };

        S["resp_apiresponse_success"] = async () =>
        {
            var (client, handler) = Client(_ => Responses.Ok("{\"id\":3,\"name\":\"ok\"}"));
            var api = RestlyClient.For<IRespApi>(client);
            var resp = await api.Resp();
            return Env(handler, "apiResponse", ("apiResponse", ApiResponseBlock(resp)));
        };

        S["resp_message_nothrow"] = async () =>
        {
            var (client, handler) = Client(_ => Responses.Json(HttpStatusCode.NotFound, "nope", "text/plain"));
            var api = RestlyClient.For<IRespApi>(client);
            var msg = await api.Message();
            return Env(handler, "route", ("status", (int)msg.StatusCode));
        };

        S["resp_ensure_variants"] = async () =>
        {
            var (client, handler) = Client(_ => Responses.Json(HttpStatusCode.OK, "notjson", "application/json"));
            var api = RestlyClient.For<IRespApi>(client);
            var resp = await api.Resp();
            bool threwStatus = false, threwFul = false;
            try { await resp.EnsureSuccessStatusCodeAsync(); } catch { threwStatus = true; }
            try { await resp.EnsureSuccessfulAsync(); } catch { threwFul = true; }
            return Env(handler, "route",
                ("isSuccessStatusCode", resp.IsSuccessStatusCode),
                ("isSuccessful", resp.IsSuccessful),
                ("threwEnsureStatus", threwStatus),
                ("threwEnsureful", threwFul));
        };

        S["stream_formats"] = async () =>
        {
            var array = await Collect(RestlyClient.For<IStreamApi>(
                new HttpClient(new CaptureHandler(_ => Responses.Json(HttpStatusCode.OK,
                    "[{\"id\":1,\"name\":\"a\"},{\"id\":2,\"name\":\"b\"}]", "application/json")))
                { BaseAddress = new Uri(BaseUrl) }));
            var ndjson = await Collect(RestlyClient.For<IStreamApi>(
                new HttpClient(new CaptureHandler(_ => Responses.Json(HttpStatusCode.OK,
                    "{\"id\":1,\"name\":\"a\"}\n{\"id\":2,\"name\":\"b\"}", "application/x-ndjson")))
                { BaseAddress = new Uri(BaseUrl) }));
            var sse = await Collect(RestlyClient.For<IStreamApi>(
                new HttpClient(new CaptureHandler(_ => Responses.Json(HttpStatusCode.OK,
                    "data: {\"id\":1,\"name\":\"a\"}\n\ndata: {\"id\":2,\"name\":\"b\"}\n\n", "text/event-stream")))
                { BaseAddress = new Uri(BaseUrl) }));
            return new Dictionary<string, object?>
            {
                ["outcome"] = "stream",
                ["array"] = array,
                ["ndjson"] = ndjson,
                ["sse"] = sse,
            };
        };

        S["stream_factory_null"] = async () =>
        {
            // A custom ExceptionFactory returning null must suppress the non-2xx throw and let the body
            // stream, exactly as for Task<T> (an impl that hard-codes a throw in the stream path fails).
            var settings = new RestlySettings { ExceptionFactory = _ => new ValueTask<Exception?>((Exception?)null) };
            var api = RestlyClient.For<IStreamApi>(
                new HttpClient(new CaptureHandler(_ => Responses.Json(HttpStatusCode.NotFound,
                    "[{\"id\":1,\"name\":\"a\"},{\"id\":2,\"name\":\"b\"}]", "application/json")))
                { BaseAddress = new Uri(BaseUrl) },
                settings);
            var items = await Collect(api);
            return new Dictionary<string, object?> { ["outcome"] = "stream", ["items"] = items };
        };

        S["exc_deserialization_success"] = async () =>
        {
            var (client, handler) = Client(_ => Responses.Json(HttpStatusCode.OK, "notanint", "application/json"));
            var api = RestlyClient.For<IRespApi>(client);
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

        S["exc_transport"] = async () =>
        {
            var handler = new ThrowingHandler(new HttpRequestException("boom"));
            var client = new HttpClient(handler) { BaseAddress = new Uri(BaseUrl) };
            var api = RestlyClient.For<IRespApi>(client);
            try
            {
                await api.Get();
                return new Dictionary<string, object?> { ["outcome"] = "exception", ["exception"] = new Dictionary<string, object?> { ["type"] = "NONE" } };
            }
            catch (Exception ex)
            {
                return new Dictionary<string, object?> { ["outcome"] = "exception", ["exception"] = ExceptionBlock(ex) };
            }
        };

        S["exc_factory_null"] = async () =>
        {
            var settings = new RestlySettings { ExceptionFactory = _ => new ValueTask<Exception?>((Exception?)null) };
            var (client, handler) = Client(_ => Responses.Json(HttpStatusCode.NotFound, "{\"id\":9,\"name\":\"z\"}", "application/json"));
            var api = RestlyClient.For<IRespApi>(client, settings);
            var user = await api.Get();
            return Env(handler, "result", ("result", Json(user)));
        };

        S["exc_factory_custom"] = async () =>
        {
            // A custom ExceptionFactory maps a non-2xx to its OWN exception, which must be the one thrown
            // (an impl that hard-codes an ApiException throw and ignores the factory's return fails this).
            var settings = new RestlySettings
            {
                ExceptionFactory = resp => new ValueTask<Exception?>(
                    resp.IsSuccessStatusCode ? null : new InvalidOperationException("custom-from-factory")),
            };
            var (client, handler) = Client(_ => Responses.Json(HttpStatusCode.BadRequest, "{}", "application/json"));
            var api = RestlyClient.For<IRespApi>(client, settings);
            try
            {
                await api.Get();
                return Env(handler, "exception", ("exception", new Dictionary<string, object?> { ["type"] = "NONE" }));
            }
            catch (Exception ex)
            {
                return Env(handler, "exception", ("exception", ExceptionBlock(ex)));
            }
        };

        S["edge_problemdetails_extensions"] = async () =>
        {
            const string problem = "{\"title\":\"bad\",\"status\":400,\"traceId\":\"t-1\",\"retryAfter\":5}";
            var (client, handler) = Client(_ => Responses.Json(HttpStatusCode.BadRequest, problem, "application/problem+json"));
            var api = RestlyClient.For<IEdgeRespApi>(client);
            try
            {
                await api.Problem();
                return Env(handler, "exception", ("exception", new Dictionary<string, object?> { ["type"] = "NONE" }));
            }
            catch (Exception ex)
            {
                return Env(handler, "exception", ("exception", ExceptionBlock(ex)));
            }
        };
    }
}
