using Microsoft.AspNetCore.Http;
using Sorabel.ApiGateway.Domain;
using Yarp.ReverseProxy.Forwarder;

namespace Sorabel.ApiGateway.Infrastructure.Errors;

/// <summary>
/// Fabrique une réponse d'erreur uniquement lorsqu'aucune réponse n'a été reçue
/// du backend. Toute réponse effectivement reçue — y compris 403 ou 500 — a déjà
/// été relayée verbatim par YARP et ne passe pas par ici.
/// </summary>
public sealed class ForwarderErrorMiddleware(RequestDelegate next)
{
    public async Task InvokeAsync(HttpContext context)
    {
        await next(context);

        var feature = context.Features.Get<IForwarderErrorFeature>();
        if (feature is null || context.Response.HasStarted)
        {
            return;
        }

        var error = ForwarderErrorTranslator.Translate(feature.Error);
        if (error is null)
        {
            return;
        }

        var correlationId = context.Items[CorrelationId.HeaderName] is CorrelationId id
            ? id.Value
            : string.Empty;

        context.Response.Clear();
        context.Response.StatusCode = error.StatusCode;
        context.Response.Headers[CorrelationId.HeaderName] = correlationId;

        await context.Response.WriteAsJsonAsync(
            new GatewayErrorResponse(error.ErrorCode, error.Message, correlationId));
    }
}
