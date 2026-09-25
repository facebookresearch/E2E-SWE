using System;
using System.Collections.Generic;
using System.Net;
using System.Net.Http;
using System.Threading.Tasks;
using System.Runtime.CompilerServices;
using Restly;
using static Harness.H;

namespace Harness;

public interface IUsersApi
{
    [Get("/users/{user}")]
    Task<User> GetUser(string user, string sort);

    [Get("/users/list")]
    Task<User> Search([Query(CollectionFormat.Multi)] int[] ages);

    [Post("/users")]
    Task<User> Create([Body] CreateUser body);

    [Get("/users/{user}")]
    Task<ApiResponse<User>> GetUserResponse(string user);

    [Get("/problem")]
    Task<User> GetProblem();
}

internal static class G_core
{
    [ModuleInitializer]
    internal static void Register()
    {
        var S = Registry.Scenarios;

        S["url_and_query"] = async () =>
        {
            var (client, handler) = Client(_ => Responses.Ok("{\"id\":7,\"name\":\"octo\"}"));
            var api = RestlyClient.For<IUsersApi>(client);
            var user = await api.GetUser("octocat", "desc");
            return Env(handler, "result", ("result", Json(user)));
        };

        S["query_collection_multi"] = async () =>
        {
            var (client, handler) = Client(_ => Responses.Ok("{\"id\":1,\"name\":\"x\"}"));
            var api = RestlyClient.For<IUsersApi>(client);
            await api.Search([10, 20, 30]);
            return Env(handler, "result", ("result", Json(new { ok = true })));
        };

        S["body_json_camelcase"] = async () =>
        {
            var (client, handler) = Client(_ => Responses.Ok("{\"id\":9,\"name\":\"neo\"}"));
            var api = RestlyClient.For<IUsersApi>(client);
            await api.Create(new CreateUser { Name = "octo", Age = 5 });
            return Env(handler, "result", ("result", Json(new { ok = true })));
        };

        S["apiresponse_error_capture"] = async () =>
        {
            var (client, handler) = Client(_ => Responses.Json(HttpStatusCode.NotFound, "nope", "text/plain"));
            var api = RestlyClient.For<IUsersApi>(client);
            var resp = await api.GetUserResponse("ghost");
            return Env(handler, "apiResponse", ("apiResponse", ApiResponseBlock(resp)));
        };

        S["exception_apiexception"] = async () =>
        {
            var (client, handler) = Client(_ => Responses.Json(HttpStatusCode.BadRequest, "bad input", "text/plain"));
            var api = RestlyClient.For<IUsersApi>(client);
            try
            {
                await api.GetUser("x", "y");
                return Env(handler, "exception", ("exception", new Dictionary<string, object?> { ["type"] = "NONE" }));
            }
            catch (Exception ex)
            {
                return Env(handler, "exception", ("exception", ExceptionBlock(ex)));
            }
        };

        S["exception_validation_problem"] = async () =>
        {
            const string problem = "{\"title\":\"invalid\",\"status\":400,\"errors\":{\"Name\":[\"Required\"]}}";
            var (client, handler) = Client(_ => Responses.Json(HttpStatusCode.BadRequest, problem, "application/problem+json"));
            var api = RestlyClient.For<IUsersApi>(client);
            try
            {
                await api.GetProblem();
                return Env(handler, "exception", ("exception", new Dictionary<string, object?> { ["type"] = "NONE" }));
            }
            catch (Exception ex)
            {
                return Env(handler, "exception", ("exception", ExceptionBlock(ex)));
            }
        };

        S["options_metadata"] = async () =>
        {
            var (client, handler) = Client(_ => Responses.Ok("{\"id\":1,\"name\":\"x\"}"));
            var api = RestlyClient.For<IUsersApi>(client);
            await api.GetUser("octocat", "desc");
            return Env(handler, "result", ("result", Json(new { ok = true })));
        };
    }
}
