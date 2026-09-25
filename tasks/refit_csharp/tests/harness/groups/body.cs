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

public interface IBodyApi
{
    [Post("/b")]
    Task<User> RawString([Body] string s);

    [Post("/b")]
    Task<User> JsonString([Body(BodySerializationMethod.Json)] string s);

    [Post("/b")]
    Task<User> Form([Body(BodySerializationMethod.UrlEncoded)] FormModel model);

    [Post("/b")]
    Task<User> FormDict([Body(BodySerializationMethod.UrlEncoded)] IDictionary<string, object> data);

    [Post("/b")]
    Task<User> FormString([Body(BodySerializationMethod.UrlEncoded)] string raw);

    [Post("/b")]
    Task JsonLines([Body(BodySerializationMethod.JsonLines)] IEnumerable<CreateUser> items);

    [Multipart]
    [Post("/b")]
    Task<User> Upload(StreamPart file, string note);
}

public interface IEdgeBodyApi
{
    [Multipart]
    [Post("/b")]
    Task<Order> DateGuid(DateTime when, Guid id);

    [Post("/b")]
    Task<Order> Buffered([Body(buffered: true)] NewOrder body);

    [Post("/b")]
    Task<Order> BufferedStream([Body(buffered: true)] Stream body);

    [Post("/b")]
    Task<Order> StreamedStream([Body] Stream body);
}

// A forward-only stream whose length is unknown, so the wrapping HttpContent cannot pre-compute a
// Content-Length unless the body is buffered first ([Body(buffered: true)]).
internal sealed class NonSeekableStream(byte[] data) : Stream
{
    private readonly MemoryStream _inner = new(data);
    public override bool CanRead => true;
    public override bool CanSeek => false;
    public override bool CanWrite => false;
    public override long Length => throw new NotSupportedException();
    public override long Position { get => _inner.Position; set => throw new NotSupportedException(); }
    public override int Read(byte[] buffer, int offset, int count) => _inner.Read(buffer, offset, count);
    public override void Flush() { }
    public override long Seek(long offset, SeekOrigin origin) => throw new NotSupportedException();
    public override void SetLength(long value) => throw new NotSupportedException();
    public override void Write(byte[] buffer, int offset, int count) => throw new NotSupportedException();
}

// Intentionally invalid (two complex candidates for the implicit body) — isolated so it doesn't
// poison the valid interfaces above.
public interface IInvalidBodyApi
{
    [Post("/b")]
    Task<Order> TwoComplex(NewOrder a, Order b);
}

internal static class G_body
{
    [ModuleInitializer]
    internal static void Register()
    {
        var S = Registry.Scenarios;

        S["body_raw_string"] = async () =>
        {
            var (client, handler) = Client(_ => Responses.Ok("{}"));
            var api = RestlyClient.For<IBodyApi>(client);
            await api.RawString("hello");
            return Env(handler, "route", ("body", handler.Body), ("contentType", ContentType(handler)));
        };

        S["body_json_string"] = async () =>
        {
            var (client, handler) = Client(_ => Responses.Ok("{}"));
            var api = RestlyClient.For<IBodyApi>(client);
            await api.JsonString("hello");
            return Env(handler, "route", ("body", handler.Body), ("contentType", ContentType(handler)));
        };

        S["body_form"] = async () =>
        {
            var (client, handler) = Client(_ => Responses.Ok("{}"));
            var api = RestlyClient.For<IBodyApi>(client);
            await api.Form(new FormModel { UserName = "neo", Age = 5, Note = null });
            return Env(handler, "route", ("body", handler.Body), ("contentType", ContentType(handler)));
        };

        S["body_form_dict"] = async () =>
        {
            var (client, handler) = Client(_ => Responses.Ok("{}"));
            var api = RestlyClient.For<IBodyApi>(client);
            await api.FormDict(new Dictionary<string, object> { ["v"] = 1, ["t"] = "event" });
            return Env(handler, "route", ("body", handler.Body), ("contentType", ContentType(handler)));
        };

        S["body_urlencoded_string"] = async () =>
        {
            var (client, handler) = Client(_ => Responses.Ok("{}"));
            var api = RestlyClient.For<IBodyApi>(client);
            await api.FormString("a b&c=d");
            return Env(handler, "route", ("body", handler.Body), ("contentType", ContentType(handler)));
        };

        S["body_jsonlines"] = async () =>
        {
            var (client, handler) = Client(_ => Responses.Ok("{}"));
            var api = RestlyClient.For<IBodyApi>(client);
            await api.JsonLines(new[] { new CreateUser { Name = "a", Age = 1 }, new CreateUser { Name = "b", Age = 2 } });
            return Env(handler, "route", ("body", handler.Body), ("contentType", ContentType(handler)));
        };

        S["body_multipart"] = async () =>
        {
            var (client, handler) = Client(_ => Responses.Ok("{}"));
            var api = RestlyClient.For<IBodyApi>(client);
            var part = new StreamPart(new MemoryStream(Encoding.UTF8.GetBytes("filedata")), "f.txt", "text/plain");
            await api.Upload(part, "hi");
            return Env(handler, "route", ("body", handler.Body), ("contentType", ContentType(handler)));
        };

        S["edge_multipart_date_guid"] = async () =>
        {
            var (client, handler) = Client(_ => Responses.Ok("{}"));
            var api = RestlyClient.For<IEdgeBodyApi>(client);
            await api.DateGuid(new DateTime(2024, 1, 2, 3, 4, 5, DateTimeKind.Utc), new Guid("d1e9ea6b-2e8b-4699-93e0-0bcbd26c206c"));
            return Env(handler, "route", ("body", handler.Body), ("contentType", ContentType(handler)));
        };

        S["edge_body_buffered_contentlength"] = async () =>
        {
            var (client, handler) = Client(_ => Responses.Ok("{}"));
            var api = RestlyClient.For<IEdgeBodyApi>(client);
            await api.Buffered(new NewOrder { Sku = "X", Qty = 1 });
            return Env(handler, "route", ("hasContentLength", handler.ContentLength is not null));
        };

        S["edge_body_buffered_stream_contentlength"] = async () =>
        {
            // buffered:true must LoadIntoBuffer the unknown-length stream so Content-Length is known;
            // streamed (default) leaves it unset. Asserted as a contrast so a "buffered is a no-op" impl fails.
            var (bufClient, bufHandler) = Client(_ => Responses.Ok("{}"));
            var bufApi = RestlyClient.For<IEdgeBodyApi>(bufClient);
            await bufApi.BufferedStream(new NonSeekableStream(Encoding.UTF8.GetBytes("payload-bytes")));
            var buffered = bufHandler.ContentLength is not null;

            var (strClient, strHandler) = Client(_ => Responses.Ok("{}"));
            var strApi = RestlyClient.For<IEdgeBodyApi>(strClient);
            await strApi.StreamedStream(new NonSeekableStream(Encoding.UTF8.GetBytes("payload-bytes")));
            var streamed = strHandler.ContentLength is not null;

            return new Dictionary<string, object?>
            {
                ["outcome"] = "route",
                ["buffered"] = buffered,
                ["streamed"] = streamed,
            };
        };

        S["edge_implicit_body_multiple_complex"] = async () =>
        {
            var (client, handler) = Client(_ => Responses.Ok("{}"));
            try
            {
                var api = RestlyClient.For<IInvalidBodyApi>(client);
                await api.TwoComplex(new NewOrder(), new Order());
                return new Dictionary<string, object?> { ["outcome"] = "exception", ["exception"] = new Dictionary<string, object?> { ["type"] = "NONE" } };
            }
            catch (Exception ex)
            {
                return new Dictionary<string, object?> { ["outcome"] = "exception", ["exception"] = new Dictionary<string, object?> { ["type"] = ex.GetType().Name } };
            }
        };
    }
}
