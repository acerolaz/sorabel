using Microsoft.Extensions.Logging;
using Yarp.ReverseProxy.Forwarder;

namespace Sorabel.ApiGateway.Infrastructure.Resilience;

/// <summary>
/// Greffe le RetryHandler dans la chaîne que YARP utilise pour parler aux
/// backends. YARP ne passe pas par un HttpClient nommé : il fabrique son propre
/// HttpMessageInvoker, et WrapHandler est le point d'extension prévu pour
/// l'entourer.
/// </summary>
public sealed class ResilientForwarderHttpClientFactory(ILoggerFactory loggerFactory)
    : ForwarderHttpClientFactory
{
    protected override HttpMessageHandler WrapHandler(
        ForwarderHttpClientContext context, HttpMessageHandler handler)
        => new RetryHandler(loggerFactory.CreateLogger<RetryHandler>())
        {
            InnerHandler = base.WrapHandler(context, handler),
        };
}
