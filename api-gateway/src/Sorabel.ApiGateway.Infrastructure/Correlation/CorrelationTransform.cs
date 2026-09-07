using Sorabel.ApiGateway.Domain;
using Yarp.ReverseProxy.Transforms;
using Yarp.ReverseProxy.Transforms.Builder;

namespace Sorabel.ApiGateway.Infrastructure.Correlation;

/// <summary>
/// Injecte l'identifiant de corrélation dans la requête sortante. L'en-tête
/// entrant est retiré d'abord : la valeur qui part est toujours celle validée
/// par le middleware, jamais celle fournie telle quelle par l'appelant.
/// </summary>
public static class CorrelationTransform
{
    public static void Register(TransformBuilderContext context)
    {
        context.AddRequestTransform(transformContext =>
        {
            if (transformContext.HttpContext.Items[CorrelationId.HeaderName] is CorrelationId id)
            {
                transformContext.ProxyRequest.Headers.Remove(CorrelationId.HeaderName);
                transformContext.ProxyRequest.Headers.TryAddWithoutValidation(
                    CorrelationId.HeaderName, id.Value);
            }

            return ValueTask.CompletedTask;
        });
    }
}
