using System.Net.Http;
using Sorabel.ApiGateway.Domain;
using Xunit;

namespace Sorabel.ApiGateway.Domain.Tests;

public class RetryDecisionTests
{
    // Rejouable : le backend n'a certainement rien reçu, et il n'y a pas de corps
    // à retransmettre.
    [Theory]
    [InlineData(HttpRequestError.ConnectionError)]
    [InlineData(HttpRequestError.NameResolutionError)]
    public void Rejoue_les_echecs_de_connexion_sans_corps(HttpRequestError error)
    {
        Assert.True(RetryDecision.CanRetry(error, requestHasBody: false));
    }

    // Non rejouable : YARP transmet le corps en streaming via un contenu à usage
    // unique. Un second essai enverrait un corps vide — corruption silencieuse.
    [Theory]
    [InlineData(HttpRequestError.ConnectionError)]
    [InlineData(HttpRequestError.NameResolutionError)]
    public void Ne_rejoue_jamais_une_requete_portant_un_corps(HttpRequestError error)
    {
        Assert.False(RetryDecision.CanRetry(error, requestHasBody: true));
    }

    // Non rejouable : dans tous ces cas la requête a pu être reçue et traitée.
    // Rejouer produirait une double exécution SQL et une double entrée d'audit.
    [Theory]
    [InlineData(HttpRequestError.Unknown)]
    [InlineData(HttpRequestError.SecureConnectionError)]
    [InlineData(HttpRequestError.HttpProtocolError)]
    [InlineData(HttpRequestError.ResponseEnded)]
    [InlineData(HttpRequestError.InvalidResponse)]
    [InlineData(HttpRequestError.ConfigurationLimitExceeded)]
    [InlineData(HttpRequestError.VersionNegotiationError)]
    [InlineData(HttpRequestError.UserAuthenticationError)]
    [InlineData(HttpRequestError.ProxyTunnelError)]
    [InlineData(HttpRequestError.ExtendedConnectNotSupported)]
    public void Ne_rejoue_aucun_autre_type_d_echec(HttpRequestError error)
    {
        Assert.False(RetryDecision.CanRetry(error, requestHasBody: false));
        Assert.False(RetryDecision.CanRetry(error, requestHasBody: true));
    }
}
