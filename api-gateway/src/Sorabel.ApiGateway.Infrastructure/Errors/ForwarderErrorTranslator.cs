using Sorabel.ApiGateway.Domain;
using Yarp.ReverseProxy.Forwarder;

namespace Sorabel.ApiGateway.Infrastructure.Errors;

/// <summary>
/// Traduit un échec de transfert YARP en erreur de routage du domaine.
/// Retourne null quand la gateway ne doit rien fabriquer — soit qu'il n'y ait
/// pas d'erreur, soit que le client ait abandonné, soit que la réponse ait déjà
/// commencé à partir.
/// </summary>
public static class ForwarderErrorTranslator
{
    public static RoutingError? Translate(ForwarderError error) => error switch
    {
        ForwarderError.None => null,

        // Le backend n'a pas répondu dans le délai de la route.
        ForwarderError.RequestTimedOut
            or ForwarderError.UpgradeActivityTimeout
            => new RoutingError(RoutingErrorKind.BackendTimeout),

        // Aucune connexion établie, ou aucune destination configurée.
        ForwarderError.Request
            or ForwarderError.RequestCreation
            or ForwarderError.NoAvailableDestinations
            or ForwarderError.RequestBodyDestination
            or ForwarderError.UpgradeRequestDestination
            => new RoutingError(RoutingErrorKind.BackendUnreachable),

        // Le client a abandonné, ou la réponse était déjà en cours d'envoi :
        // il n'y a rien à écrire.
        _ => null,
    };
}
