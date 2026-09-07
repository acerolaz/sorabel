using Microsoft.Extensions.Logging;
using Sorabel.ApiGateway.Domain;

namespace Sorabel.ApiGateway.Infrastructure.Resilience;

/// <summary>
/// Rejoue un transfert uniquement lorsque RetryDecision l'autorise. Une
/// annulation ou un dépassement de délai remonte tel quel : la requête a pu
/// être reçue et traitée, la rejouer produirait une double exécution.
/// </summary>
public sealed class RetryHandler(ILogger logger) : DelegatingHandler
{
    private const int MaxAttempts = 3; // 1 essai + 2 rejeux

    private static readonly TimeSpan[] Backoff =
        [TimeSpan.FromMilliseconds(100), TimeSpan.FromMilliseconds(300)];

    protected override async Task<HttpResponseMessage> SendAsync(
        HttpRequestMessage request, CancellationToken cancellationToken)
    {
        var hasBody = request.Content is not null;

        for (var attempt = 1; ; attempt++)
        {
            try
            {
                return await base.SendAsync(request, cancellationToken);
            }
            catch (HttpRequestException ex)
                when (attempt < MaxAttempts && RetryDecision.CanRetry(ex.HttpRequestError, hasBody))
            {
                logger.LogWarning(
                    "Transfert échoué (tentative {Attempt}, {Error}) — rejeu",
                    attempt, ex.HttpRequestError);

                await Task.Delay(Backoff[attempt - 1], cancellationToken);
            }
        }
    }
}
