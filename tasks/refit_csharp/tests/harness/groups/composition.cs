using System;
using System.Collections.Generic;
using System.Net.Http;
using System.Threading.Tasks;
using System.Runtime.CompilerServices;
using Restly;
using static Harness.H;

namespace Harness;

public interface IPetsBase
{
    [Get("/pets")]
    Task<Order> Pets();
}

public interface IOwnersBase
{
    [Get("/owners")]
    Task<Order> Owners();
}

public interface IComposedApi : IPetsBase, IOwnersBase
{
    [Get("/all")]
    Task<Order> All();
}

public interface IBaseWithNonRestly
{
    // No Restly HTTP attribute -> calling it on a generated client throws NotImplementedException.
    Task<Order> Plain();
}

public interface IDerivedRestly : IBaseWithNonRestly
{
    [Get("/d")]
    Task<Order> D();
}

internal static class G_composition
{
    [ModuleInitializer]
    internal static void Register()
    {
        var S = Registry.Scenarios;

        S["composition_diamond"] = async () =>
        {
            var (client, handler) = Client(_ => Responses.Ok("{}"));
            var api = RestlyClient.For<IComposedApi>(client);
            await api.Pets(); var pets = handler.Request!.RequestUri!.PathAndQuery;
            await api.Owners(); var owners = handler.Request!.RequestUri!.PathAndQuery;
            await api.All(); var all = handler.Request!.RequestUri!.PathAndQuery;
            return Env(handler, "route", ("pets", pets), ("owners", owners), ("all", all));
        };

        S["composition_nonrefit"] = async () =>
        {
            var (client, handler) = Client(_ => Responses.Ok("{}"));
            var api = RestlyClient.For<IDerivedRestly>(client);
            await api.D();
            var d = handler.Request!.RequestUri!.PathAndQuery;
            string exType;
            try { await api.Plain(); exType = "NONE"; }
            catch (Exception ex) { exType = ex.GetType().Name; }
            return Env(handler, "route", ("d", d), ("plainException", exType));
        };
    }
}
