using System.Diagnostics;
using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.Logging;
using Sorabel.ApiGateway.Domain;
using Yarp.ReverseProxy.Model;

namespace Sorabel.ApiGateway.Infrastructure.Logging;

/// <summary>
/// Une ligne structurée par requête : identifiant de corrélation,
/// méthode, chemin entrant, backend, statut, durée.
///
/// Aucun en-tête n'est journalisé — c'est une liste d'autorisation de champs,
/// pas une liste de blocage à tenir à jour. <see cref="Sorabel.ApiGateway.Domain.SensitiveHeaders"/>
/// n'est donc pas consommé ici (ni ailleurs) : ce type documente, pour un futur
/// contributeur qui ajouterait un jour la journalisation d'en-têtes, ce qui ne
/// doit jamais fuiter — il ne fournit aucun filtrage existant sur lequel s'appuyer.
/// </summary>
public sealed class RequestLoggingMiddleware(RequestDelegate next, ILogger<RequestLoggingMiddleware> logger)
{
    public async Task InvokeAsync(HttpContext context)
    {
        var chrono = Stopwatch.StartNew();
        var chemin = context.Request.Path.Value ?? "/";
        var methode = context.Request.Method;

        try
        {
            await next(context);
        }
        finally
        {
            chrono.Stop();

            // GetReverseProxyFeature() lève si la requête n'a pas été routée
            // (ex. /health) : on lit la feature directement.
            var clusterId = context.Features.Get<IReverseProxyFeature>()?.Cluster?.Config.ClusterId;
            var backend = BackendId.TryFromClusterId(clusterId, out var id) ? id.Value : "-";

            var correlationId = context.Items[CorrelationId.HeaderName] is CorrelationId cid
                ? cid.Value
                : "-";

            logger.LogInformation(
                "correlation_id={CorrelationId} method={Method} path={Path} backend={Backend} status={Status} duration_ms={Duration}",
                correlationId, methode, chemin, backend, context.Response.StatusCode,
                chrono.ElapsedMilliseconds);
        }
    }
}
