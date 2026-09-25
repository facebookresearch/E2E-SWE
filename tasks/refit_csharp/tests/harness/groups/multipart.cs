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

public interface IMultipartDepthApi
{
    [Multipart]
    [Post("/m")]
    Task<Order> AllParts(ByteArrayPart data, FileInfoPart doc, IEnumerable<StreamPart> files);

    [Multipart]
    [Post("/m")]
    Task<Order> Names(StreamPart withName, [AliasAs("aliased")] StreamPart withAlias, StreamPart plain);
}

public interface IRawMultipartApi
{
    [Multipart]
    [Post("/m")]
    Task<Order> RawTypes(byte[] payload, Stream blob, FileInfo doc, CreateUser meta);
}

internal static class G_multipart
{
    [ModuleInitializer]
    internal static void Register()
    {
        var S = Registry.Scenarios;

        S["multipart_parts"] = async () =>
        {
            File.WriteAllText("/tmp/mp_doc.txt", "filecontent");
            var (client, handler) = Client(_ => Responses.Ok("{}"));
            var api = RestlyClient.For<IMultipartDepthApi>(client);
            var data = new ByteArrayPart(Encoding.UTF8.GetBytes("BYTES"), "d.bin", "application/octet-stream");
            var doc = new FileInfoPart(new FileInfo("/tmp/mp_doc.txt"), "report.txt", "text/plain");
            var files = new[]
            {
                new StreamPart(new MemoryStream(Encoding.UTF8.GetBytes("one")), "a.txt", "text/plain"),
                new StreamPart(new MemoryStream(Encoding.UTF8.GetBytes("two")), "b.txt", "text/plain"),
            };
            await api.AllParts(data, doc, files);
            return Env(handler, "route", ("body", handler.Body), ("contentType", ContentType(handler)));
        };

        S["multipart_name_precedence"] = async () =>
        {
            var (client, handler) = Client(_ => Responses.Ok("{}"));
            var api = RestlyClient.For<IMultipartDepthApi>(client);
            var withName = new StreamPart(new MemoryStream(Encoding.UTF8.GetBytes("1")), "x.txt", "text/plain", "chosen");
            var withAlias = new StreamPart(new MemoryStream(Encoding.UTF8.GetBytes("2")), "y.txt", "text/plain");
            var plain = new StreamPart(new MemoryStream(Encoding.UTF8.GetBytes("3")), "z.txt", "text/plain");
            await api.Names(withName, withAlias, plain);
            return Env(handler, "route", ("body", handler.Body), ("contentType", ContentType(handler)));
        };

        S["multipart_raw_types"] = async () =>
        {
            File.WriteAllText("/tmp/mp_raw.txt", "docdata");
            var (client, handler) = Client(_ => Responses.Ok("{}"));
            var api = RestlyClient.For<IRawMultipartApi>(client);
            await api.RawTypes(
                Encoding.UTF8.GetBytes("BYTES"),
                new MemoryStream(Encoding.UTF8.GetBytes("STREAMED")),
                new FileInfo("/tmp/mp_raw.txt"),
                new CreateUser { Name = "m", Age = 9 });
            return Env(handler, "route", ("body", handler.Body), ("contentType", ContentType(handler)));
        };
    }
}
