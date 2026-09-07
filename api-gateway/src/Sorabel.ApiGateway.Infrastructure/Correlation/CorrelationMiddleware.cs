using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.Logging;
using Sorabel.ApiGateway.Domain;

namespace Sorabel.ApiGateway.Infrastructure.Correlation;

/// <summary>
/// Attache un identifiant de corrélation à chaque requête : repris de l'appelant
/// s'il est conforme, généré sinon. Il est placé dans HttpContext.Items pour le
/// transform sortant, dans le scope de log, et renvoyé au client.
/// </summary>
public sealed class CorrelationMiddleware(RequestDelegate next, ILogger<CorrelationMiddleware> logger)
{
    public async Task InvokeAsync(HttpContext context)
    {
        var id = CorrelationId.FromHeaderOrNew(context.Request.Headers[CorrelationId.HeaderName]);

        context.Items[CorrelationId.HeaderName] = id;
        context.Response.Headers[CorrelationId.HeaderName] = id.Value;

        using (logger.BeginScope(new Dictionary<string, object> { ["correlation_id"] = id.Value }))
        {
            await next(context);
        }
    }
}
