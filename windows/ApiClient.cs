using System;
using System.Net;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

namespace LocalFlowRemote
{
    /// <summary>
    /// The Mac's remote-dictation server (server.py), over Tailscale -- same
    /// endpoints the Android app uses: /v1/health, /v1/transcribe,
    /// /v1/preview, /v1/restart.
    /// </summary>
    internal static class ApiClient
    {
        private static readonly HttpClient Http = new() { Timeout = TimeSpan.FromSeconds(120) };
        // the live preview must never queue behind a slow request
        private static readonly HttpClient PreviewHttp = new() { Timeout = TimeSpan.FromSeconds(5) };
        private static readonly HttpClient HealthHttp = new() { Timeout = TimeSpan.FromSeconds(6) };

        public sealed record Result(bool Ok, string Text, int Status, string Error);

        public static string BaseUrl(Config c)
        {
            var h = c.Host.Trim().TrimEnd('/');
            if (!h.StartsWith("http://", StringComparison.OrdinalIgnoreCase)
                && !h.StartsWith("https://", StringComparison.OrdinalIgnoreCase))
                h = "http://" + h;
            var u = new UriBuilder(h);
            // keep a port typed into the address, else use the Port setting
            if (!h.Substring(h.IndexOf("//", StringComparison.Ordinal) + 2).Contains(':'))
                u.Port = c.Port;
            return u.Uri.GetLeftPart(UriPartial.Authority);
        }

        private static HttpRequestMessage Req(Config c, HttpMethod m, string path, byte[]? body = null)
        {
            var r = new HttpRequestMessage(m, BaseUrl(c) + path);
            r.Headers.Authorization = new AuthenticationHeaderValue("Bearer", c.Token.Trim());
            if (body != null)
            {
                r.Content = new ByteArrayContent(body);
                r.Content.Headers.ContentType = new MediaTypeHeaderValue("application/octet-stream");
            }
            return r;
        }

        private static string Describe(int status, string body) => status switch
        {
            401 => "the pairing token is wrong",
            503 => "the Mac is still loading its speech model",
            413 => "the recording is too long",
            _ => $"the Mac answered HTTP {status}" + (body.Length > 0 && body.Length < 160 ? $" ({body})" : ""),
        };

        private static string Describe(Exception e) => e switch
        {
            TaskCanceledException => "the Mac didn't answer in time",
            HttpRequestException h when h.InnerException != null => h.InnerException.Message,
            UriFormatException => "the Mac's address isn't valid",
            _ => e.Message,
        };

        private static async Task<Result> Call(HttpClient client, HttpRequestMessage req, CancellationToken ct)
        {
            try
            {
                using var resp = await client.SendAsync(req, ct).ConfigureAwait(false);
                var body = await resp.Content.ReadAsStringAsync(ct).ConfigureAwait(false);
                int status = (int)resp.StatusCode;
                if (!resp.IsSuccessStatusCode) return new Result(false, "", status, Describe(status, body));
                string text = "";
                try
                {
                    using var doc = JsonDocument.Parse(body);
                    if (doc.RootElement.TryGetProperty("text", out var t)) text = t.GetString() ?? "";
                }
                catch (JsonException) { }
                return new Result(true, text, status, "");
            }
            catch (Exception e) when (e is not OperationCanceledException || !ct.IsCancellationRequested)
            {
                return new Result(false, "", 0, Describe(e));
            }
        }

        public static Task<Result> Transcribe(Config c, byte[] pcm, CancellationToken ct = default) =>
            Call(Http, Req(c, HttpMethod.Post, "/v1/transcribe", pcm), ct);

        public static Task<Result> Preview(Config c, byte[] pcm, CancellationToken ct = default) =>
            Call(PreviewHttp, Req(c, HttpMethod.Post, "/v1/preview", pcm), ct);

        public static Task<Result> Health(Config c, CancellationToken ct = default) =>
            Call(HealthHttp, Req(c, HttpMethod.Get, "/v1/health"), ct);

        public static Task<Result> RestartMac(Config c) =>
            Call(HealthHttp, Req(c, HttpMethod.Post, "/v1/restart", Array.Empty<byte>()), default);
    }
}
