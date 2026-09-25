using System.Net;
using System.Text;

namespace Harness;

// In-proc handler: captures the final HttpRequestMessage Restly produced and returns a caller-supplied
// canned response. CRITICAL: sets response.RequestMessage = request, otherwise Restly's default
// exception factory throws InvalidOperationException on the error paths.
public sealed class CaptureHandler(Func<HttpRequestMessage, HttpResponseMessage> responder) : HttpMessageHandler
{
    public HttpRequestMessage? Request { get; private set; }
    public string? Body { get; private set; }

    // Content headers are snapshotted here, during the send, because the request content is disposed
    // once the call returns (accessing it afterwards throws ObjectDisposedException, e.g. JsonContent).
    public Dictionary<string, string[]> ContentHeaders { get; } = new();
    public long? ContentLength { get; private set; }
    public string? ContentTypeValue { get; private set; }

    protected override async Task<HttpResponseMessage> SendAsync(
        HttpRequestMessage request,
        CancellationToken cancellationToken)
    {
        Request = request;
        if (request.Content is not null)
        {
            // Snapshot content metadata BEFORE reading the body. ReadAsStringAsync buffers the content
            // into memory, which retroactively populates Content-Length even for an unbuffered stream
            // body — so reading first would mask the buffered-vs-streamed distinction.
            foreach (var h in request.Content.Headers)
            {
                ContentHeaders[h.Key] = h.Value.ToArray();
            }

            ContentLength = request.Content.Headers.ContentLength;
            ContentTypeValue = request.Content.Headers.ContentType?.ToString();
            Body = await request.Content.ReadAsStringAsync(cancellationToken).ConfigureAwait(false);
        }

        var response = responder(request);
        response.RequestMessage = request;
        return response;
    }
}

// Handler that throws, for transport-failure scenarios.
public sealed class ThrowingHandler(Exception toThrow) : HttpMessageHandler
{
    protected override Task<HttpResponseMessage> SendAsync(
        HttpRequestMessage request,
        CancellationToken cancellationToken) => throw toThrow;
}

// Handler that waits (honoring cancellation) before responding, for [Timeout]/cancellation scenarios.
public sealed class DelayHandler(int delayMs, Func<HttpRequestMessage, HttpResponseMessage> responder)
    : HttpMessageHandler
{
    protected override async Task<HttpResponseMessage> SendAsync(
        HttpRequestMessage request,
        CancellationToken cancellationToken)
    {
        await Task.Delay(delayMs, cancellationToken).ConfigureAwait(false);
        var response = responder(request);
        response.RequestMessage = request;
        return response;
    }
}

// Custom URL-parameter formatter registered per-type via RestlySettings.UrlParameterFormatterMap.
public sealed class DateStampFormatter : Restly.IUrlParameterFormatter
{
    public string? Format(object? value, System.Reflection.ICustomAttributeProvider attributeProvider, Type type) =>
        value is DateTime d ? d.ToString("yyyyMMdd", System.Globalization.CultureInfo.InvariantCulture) : value?.ToString();
}

public static class Responses
{
    public static HttpResponseMessage Json(
        HttpStatusCode code,
        string body,
        string mediaType = "application/json") =>
        new(code) { Content = new StringContent(body, Encoding.UTF8, mediaType) };

    public static HttpResponseMessage Ok(string body) => Json(HttpStatusCode.OK, body);
}
