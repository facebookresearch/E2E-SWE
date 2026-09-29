using System.IO;
using System.Net;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using Restly;

namespace Harness;

// Scenario registry. Each per-group Scenarios.cs registers its scenarios here via a [ModuleInitializer]
// (runs before Main). A group project compiles exactly one group's scenarios, so only that group's
// scenarios are present in that harness binary.
public static class Registry
{
    public static readonly Dictionary<string, Func<Task<object>>> Scenarios = new();
}

// Shared helpers used by every scenario. Groups do `using static Harness.H;` so scenario bodies call
// these unqualified (Client, Env, Json, …).
public static class H
{
    public const string BaseUrl = "http://api.example.com";

    // Stable camelCase convention for embedded result values, so pytest can compare plain lowercase JSON.
    public static readonly JsonSerializerOptions ResultOptions = new(JsonSerializerDefaults.Web);

    public static (HttpClient, CaptureHandler) Client(
        Func<HttpRequestMessage, HttpResponseMessage> responder,
        RestlySettings? settings = null)
    {
        var handler = new CaptureHandler(responder);
        var client = new HttpClient(handler) { BaseAddress = new Uri(BaseUrl) };
        return (client, handler);
    }

    public static (HttpClient, CaptureHandler) ClientWithBase(
        string baseUrl,
        Func<HttpRequestMessage, HttpResponseMessage> responder)
    {
        var handler = new CaptureHandler(responder);
        var client = new HttpClient(handler) { BaseAddress = new Uri(baseUrl) };
        return (client, handler);
    }

    public static JsonElement Json(object? value) => JsonSerializer.SerializeToElement(value, ResultOptions);

    public static Dictionary<string, string> HeadersOf(CaptureHandler handler) =>
        handler.Request!.Headers.ToDictionary(h => h.Key, h => string.Join(",", h.Value));

    public static string? ContentType(CaptureHandler handler) => handler.ContentTypeValue;

    public static Dictionary<string, object?> Env(
        CaptureHandler? handler,
        string outcome,
        params (string Key, object? Value)[] extra)
    {
        var env = new Dictionary<string, object?>
        {
            ["request"] = handler?.Request is null ? null : RequestBlock(handler),
            ["outcome"] = outcome,
        };
        foreach (var (key, value) in extra)
        {
            env[key] = value;
        }

        return env;
    }

    public static Dictionary<string, object?> RequestBlock(CaptureHandler handler)
    {
        var request = handler.Request!;
        var requestHeaders = request.Headers.ToDictionary(h => h.Key, h => h.Value.ToArray());
        var options = new Dictionary<string, string?>();
        foreach (var kv in (IEnumerable<KeyValuePair<string, object?>>)request.Options)
        {
            options[kv.Key] = kv.Value?.ToString();
        }

        return new Dictionary<string, object?>
        {
            ["method"] = request.Method.Method,
            ["uri"] = request.RequestUri?.ToString(),
            ["target"] = request.RequestUri?.PathAndQuery,
            ["requestHeaders"] = requestHeaders,
            ["contentHeaders"] = handler.ContentHeaders,
            ["hasBody"] = handler.Body is not null,
            ["body"] = handler.Body,
            ["options"] = options,
        };
    }

    public static Dictionary<string, object?> ApiResponseBlock<T>(ApiResponse<T> resp)
    {
        return new Dictionary<string, object?>
        {
            ["statusCode"] = (int)resp.StatusCode,
            ["isSuccessStatusCode"] = resp.IsSuccessStatusCode,
            ["isSuccessful"] = resp.IsSuccessful,
            ["hasContent"] = resp.Content is not null,
            ["reasonPhrase"] = resp.ReasonPhrase,
            ["content"] = resp.Content is null ? null : Json(resp.Content),
            ["errorType"] = resp.Error?.GetType().Name,
            ["errorStatus"] = resp.Error is ApiException ae ? (int?)ae.StatusCode : null,
        };
    }

    public static Dictionary<string, object?> ExceptionBlock(Exception ex)
    {
        var block = new Dictionary<string, object?>
        {
            ["type"] = ex.GetType().Name,
            ["message"] = ex.Message,
            ["innerType"] = ex.InnerException?.GetType().Name,
        };

        if (ex is ApiException apiEx)
        {
            block["statusCode"] = (int)apiEx.StatusCode;
            block["content"] = apiEx.Content;
        }

        if (ex is ValidationApiException { Content: { } problem })
        {
            block["problemDetails"] = new Dictionary<string, object?>
            {
                ["title"] = problem.Title,
                ["status"] = problem.Status,
                ["detail"] = problem.Detail,
                ["type"] = problem.Type,
                ["errors"] = problem.Errors,
                // Extensions values may be typed as object (real refit) or JsonElement (a valid
                // [JsonExtensionData] alternative) — cast to object so ToString works for both.
                ["extensions"] = problem.Extensions is null
                    ? new Dictionary<string, string?>()
                    : problem.Extensions.ToDictionary(kv => kv.Key, kv => ((object?)kv.Value)?.ToString()),
            };
        }

        return block;
    }
}

public static class Program
{
    public static async Task<int> Main(string[] args)
    {
        var id = args.Length > 0 ? args[0] : "";
        if (id == "--list")
        {
            foreach (var key in Registry.Scenarios.Keys)
            {
                Console.WriteLine(key);
            }

            return 0;
        }

        if (!Registry.Scenarios.TryGetValue(id, out var scenario))
        {
            Console.WriteLine(JsonSerializer.Serialize(new { harnessError = $"unknown scenario '{id}'" }));
            return 2;
        }

        try
        {
            var observation = await scenario();
            Console.WriteLine(JsonSerializer.Serialize(observation));
            return 0;
        }
        catch (Exception ex)
        {
            Console.WriteLine(JsonSerializer.Serialize(new { harnessError = $"{ex.GetType().Name}: {ex.Message}" }));
            return 3;
        }
    }
}
