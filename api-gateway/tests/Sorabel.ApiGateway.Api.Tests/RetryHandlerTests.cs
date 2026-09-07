using Microsoft.Extensions.Logging.Abstractions;
using Sorabel.ApiGateway.Infrastructure.Resilience;
using Xunit;

namespace Sorabel.ApiGateway.Api.Tests;

[Trait("Level", "2")]
public class RetryHandlerTests
{
    /// Compte les appels et rejoue le scénario demandé.
    private sealed class HandlerCompteur(Func<int, HttpResponseMessage> comportement) : HttpMessageHandler
    {
        public int Appels { get; private set; }

        protected override Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Appels++;
            return Task.FromResult(comportement(Appels));
        }
    }

    private static HttpRequestMessage Requete(bool avecCorps) =>
        new(HttpMethod.Post, "http://backend/appel")
        {
            Content = avecCorps ? new StringContent("{}") : null,
        };

    private static async Task<(int Appels, Exception? Erreur)> Envoyer(
        HttpRequestMessage requete,
        Func<int, HttpResponseMessage> comportement,
        CancellationToken cancellationToken = default)
    {
        using var _ = requete; // libère aussi le StringContent éventuel du corps.
        var inner = new HandlerCompteur(comportement);
        using var invoker = new HttpMessageInvoker(
            new RetryHandler(NullLogger.Instance) { InnerHandler = inner });

        try
        {
            await invoker.SendAsync(requete, cancellationToken);
            return (inner.Appels, null);
        }
        catch (Exception ex)
        {
            return (inner.Appels, ex);
        }
    }

    [Fact]
    public async Task Rejoue_deux_fois_un_echec_de_connexion_sans_corps()
    {
        var (appels, erreur) = await Envoyer(
            Requete(avecCorps: false),
            _ => throw new HttpRequestException(HttpRequestError.ConnectionError));

        Assert.Equal(3, appels); // 1 essai + 2 rejeux
        Assert.IsType<HttpRequestException>(erreur);
    }

    [Fact]
    public async Task S_arrete_des_qu_une_tentative_reussit()
    {
        var (appels, erreur) = await Envoyer(
            Requete(avecCorps: false),
            n => n < 2
                ? throw new HttpRequestException(HttpRequestError.ConnectionError)
                : new HttpResponseMessage(System.Net.HttpStatusCode.OK));

        Assert.Equal(2, appels);
        Assert.Null(erreur);
    }

    // La garantie centrale : un POST avec corps n'est jamais rejoué.
    [Fact]
    public async Task Ne_rejoue_jamais_une_requete_portant_un_corps()
    {
        var (appels, erreur) = await Envoyer(
            Requete(avecCorps: true),
            _ => throw new HttpRequestException(HttpRequestError.ConnectionError));

        Assert.Equal(1, appels);
        Assert.IsType<HttpRequestException>(erreur);
    }

    [Fact]
    public async Task Ne_rejoue_pas_une_annulation_ni_un_timeout()
    {
        var (appels, erreur) = await Envoyer(
            Requete(avecCorps: false),
            _ => throw new TaskCanceledException("délai dépassé"));

        Assert.Equal(1, appels);
        Assert.IsType<TaskCanceledException>(erreur);
    }

    [Fact]
    public async Task Ne_rejoue_pas_une_reponse_5xx_recue()
    {
        var (appels, erreur) = await Envoyer(
            Requete(avecCorps: false),
            _ => new HttpResponseMessage(System.Net.HttpStatusCode.InternalServerError));

        Assert.Equal(1, appels);
        Assert.Null(erreur);
    }

    // Une annulation pendant le backoff (et non au moment de l'appel réseau
    // lui-même) ne doit pas non plus déclencher une deuxième exécution.
    [Fact]
    public async Task N_appelle_pas_une_deuxieme_fois_si_annule_pendant_le_backoff()
    {
        using var cts = new CancellationTokenSource(TimeSpan.FromMilliseconds(20));

        var (appels, erreur) = await Envoyer(
            Requete(avecCorps: false),
            _ => throw new HttpRequestException(HttpRequestError.ConnectionError),
            cts.Token);

        Assert.Equal(1, appels);
        Assert.IsType<TaskCanceledException>(erreur);
    }
}
