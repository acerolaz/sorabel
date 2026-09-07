using Sorabel.ApiGateway.Domain;
using Sorabel.ApiGateway.Infrastructure.Errors;
using Xunit;
using Yarp.ReverseProxy.Forwarder;

namespace Sorabel.ApiGateway.Api.Tests;

// Niveau 2 : ForwarderErrorTranslator est une fonction statique pure, sans I/O,
// mais elle adapte un type d'infrastructure (l'énumération YARP ForwarderError)
// vers le domaine — elle vit donc avec les tests orientés Infrastructure plutôt
// que dans Sorabel.ApiGateway.Domain.Tests, qui ne référence pas YARP.
//
// Table exhaustive plutôt que dérivée : chaque membre de ForwarderError (YARP
// 2.3.0, énuméré par réflexion pour construire cette liste, puis recopié en dur
// ici) a une ligne explicite. Le risque visé est le bras `_ => null` : si une
// future version de YARP ajoute un membre, ce test échoue avec un message clair
// (valeur non couverte) plutôt que de router silencieusement vers « ne rien
// fabriquer ».
[Trait("Level", "2")]
public class ForwarderErrorTranslatorTests
{
    public static TheoryData<ForwarderError, RoutingErrorKind?> Membres => new()
    {
        { ForwarderError.None, null },
        { ForwarderError.Request, RoutingErrorKind.BackendUnreachable },
        { ForwarderError.RequestTimedOut, RoutingErrorKind.BackendTimeout },
        { ForwarderError.RequestCanceled, null },
        { ForwarderError.RequestBodyCanceled, null },
        { ForwarderError.RequestBodyClient, null },
        { ForwarderError.RequestBodyDestination, RoutingErrorKind.BackendUnreachable },
        { ForwarderError.ResponseHeaders, null },
        { ForwarderError.ResponseBodyCanceled, null },
        { ForwarderError.ResponseBodyClient, null },
        { ForwarderError.ResponseBodyDestination, null },
        { ForwarderError.UpgradeRequestCanceled, null },
        { ForwarderError.UpgradeRequestClient, null },
        { ForwarderError.UpgradeRequestDestination, RoutingErrorKind.BackendUnreachable },
        { ForwarderError.UpgradeResponseCanceled, null },
        { ForwarderError.UpgradeResponseClient, null },
        { ForwarderError.UpgradeResponseDestination, null },
        { ForwarderError.NoAvailableDestinations, RoutingErrorKind.BackendUnreachable },
        { ForwarderError.RequestCreation, RoutingErrorKind.BackendUnreachable },
        { ForwarderError.UpgradeActivityTimeout, RoutingErrorKind.BackendTimeout },
    };

    [Theory]
    [MemberData(nameof(Membres))]
    public void Traduit_chaque_membre_de_ForwarderError_selon_la_table_attendue(
        ForwarderError erreur, RoutingErrorKind? attendu)
    {
        var resultat = ForwarderErrorTranslator.Translate(erreur);

        Assert.Equal(attendu, resultat?.Kind);
    }

    // Garde-fou explicite sur le nombre de membres : si YARP en ajoute un, cette
    // table doit être mise à jour consciemment, pas silencieusement ignorée par
    // le bras `_ => null` du traducteur.
    [Fact]
    public void Couvre_tous_les_membres_connus_de_ForwarderError()
    {
        var membresConnus = Enum.GetValues<ForwarderError>();

        Assert.Equal(membresConnus.Length, Membres.Count);
    }
}
