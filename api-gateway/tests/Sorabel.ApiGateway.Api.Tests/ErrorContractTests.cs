using System.Net;
using System.Text.Json;
using Sorabel.ApiGateway.Domain;
using WireMock.RequestBuilders;
using WireMock.ResponseBuilders;
using Xunit;
using static Sorabel.ApiGateway.Api.Tests.TestAssertions;

namespace Sorabel.ApiGateway.Api.Tests;

[Trait("Level", "3")]
public class ErrorContractTests : IClassFixture<GatewayFixture>
{
    private readonly GatewayFixture _fixture;

    public ErrorContractTests(GatewayFixture fixture) => _fixture = fixture;

    [Fact]
    public async Task Backend_eteint_donne_un_502_au_format_du_contrat()
    {
        // Port fermé : personne n'écoute, la connexion est refusée.
        var client = _fixture.CreateClient(new Dictionary<string, string>
        {
            ["mcp"] = "http://127.0.0.1:1/",
        });

        var response = await client.GetAsync("/api/v1/mcp/call_tool");

        Assert.Equal(HttpStatusCode.BadGateway, response.StatusCode);

        using var payload = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        var racine = payload.RootElement;

        Assert.Equal("BACKEND_UNREACHABLE", racine.GetProperty("error_code").GetString());
        Assert.False(string.IsNullOrWhiteSpace(racine.GetProperty("message").GetString()));
        Assert.False(string.IsNullOrWhiteSpace(racine.GetProperty("correlation_id").GetString()));
    }

    [Fact]
    public async Task Le_message_d_erreur_ne_revele_pas_la_topologie_interne()
    {
        var client = _fixture.CreateClient(new Dictionary<string, string>
        {
            ["mcp"] = "http://127.0.0.1:1/",
        });

        var corps = await (await client.GetAsync("/api/v1/mcp/call_tool")).Content.ReadAsStringAsync();

        using var payload = JsonDocument.Parse(corps);
        var message = RequireNotNull(payload.RootElement.GetProperty("message").GetString());

        Assert.DoesNotContain("127.0.0.1", message);
        Assert.DoesNotContain("mcp", message, StringComparison.OrdinalIgnoreCase);
    }

    // Complète la matrice du §8 de la spec (backend éteint → 502 ; backend lent
    // → 504 ; backend 403 → relayé verbatim) — ce test documente ce qui se
    // passe RÉELLEMENT aujourd'hui pour le cas « backend lent », qui n'était
    // exercé nulle part avant ce correctif.
    //
    // CONSTAT EMPIRIQUE (voir final-fix-report.md pour le détail) : ce test
    // ne peut PAS affirmer 504/BACKEND_TIMEOUT, parce que ce n'est pas ce qui
    // se produit avec le câblage actuel. Quand `ReverseProxy:Routes:*:Timeout`
    // expire via `UseRequestTimeouts()`, YARP classe l'échec en
    // `ForwarderError.RequestCanceled` — le même code que « le client a
    // abandonné » — et non `RequestTimedOut`. `ForwarderErrorTranslator`
    // traduit `RequestCanceled` en `null` (comportement volontaire et
    // correctement testé par ForwarderErrorTranslatorTests : ne rien fabriquer
    // quand le client a réellement abandonné). Résultat : rien n'écrit de
    // contrat d'erreur, et il ne reste que ce que YARP/le hôte de test ont
    // laissé sur la réponse.
    //
    // Autrement dit : la chaîne RequestTimedOut → BackendTimeout → 504 décrite
    // par la spec n'est atteignable par AUCUN mécanisme actuellement câblé
    // dans Program.cs. C'est un écart de conception (classification d'erreur),
    // pas un problème d'ordre de middleware — le réordonnancement demandé de
    // ne pas toucher n'y changerait rien. Corriger la classification (faire
    // dépendre le mapping de la raison du timeout plutôt que du seul code
    // ForwarderError, ou changer le mécanisme de timeout par route) est une
    // décision de conception hors du périmètre de cette vague de correctifs.
    [Fact]
    public async Task Backend_lent_est_classe_RequestCanceled_et_ne_produit_aucun_contrat_504()
    {
        var backend = _fixture.StartBackend();
        backend
            .Given(Request.Create().WithPath("/call_tool"))
            .RespondWith(Response.Create().WithStatusCode(200).WithDelay(TimeSpan.FromSeconds(2)));

        var client = _fixture.CreateClient(
            new Dictionary<string, string> { ["mcp"] = backend.Url! },
            new Dictionary<string, string> { ["ReverseProxy:Routes:mcp-public:Timeout"] = "00:00:01" });

        var response = await client.GetAsync("/api/v1/mcp/call_tool");
        var corps = await response.Content.ReadAsStringAsync();

        // Ce n'est PAS le contrat visé par la spec (§8 : backend lent → 504).
        // C'est la preuve, par une assertion qui échouera si le comportement
        // change, que la chaîne 504 n'est aujourd'hui jamais empruntée : ni
        // code d'erreur métier, ni corps JSON — TestServer ne renvoie ici
        // qu'un statut 400 vide, un artefact de l'hôte de test face à une
        // requête dont le HttpContext a été annulé sans qu'aucune réponse
        // n'ait été écrite (en Kestrel réel, l'attendu serait une connexion
        // simplement interrompue, pas un 400 — non vérifié faute d'accès
        // réseau dans cet environnement).
        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
        Assert.Equal(string.Empty, corps);

        // Ce que ce test établit malgré tout, et qui répond à la question
        // ouverte de la revue de branche sur l'ordre des middlewares :
        // CorrelationMiddleware pose l'en-tête AVANT d'appeler next(), donc il
        // survit même à ce chemin d'échec — la question de l'ordre des
        // middlewares n'est donc pas la cause du problème constaté ici.
        var correlationHeader = Assert.Single(response.Headers.GetValues(CorrelationId.HeaderName));
        Assert.False(string.IsNullOrWhiteSpace(correlationHeader));
    }

    // Garde-fou central : une réponse effectivement reçue n'est JAMAIS réécrite.
    // Sans quoi le client ne pourrait plus distinguer un refus d'autorisation
    // (403 de mcp) d'une panne, et le mécanisme isError/reason d'E1/E5 serait
    // détruit.
    [Theory]
    [InlineData(403, "UNAUTHORIZED_TOOL")]
    [InlineData(404, "NOT_FOUND_IN_CORPUS")]
    [InlineData(500, "INTERNAL")]
    [InlineData(503, "OVERLOADED")]
    public async Task Relaie_verbatim_toute_reponse_recue_du_backend(int statut, string codeMetier)
    {
        var corpsBackend = $$"""{"error_code":"{{codeMetier}}","message":"venant du backend"}""";

        var backend = _fixture.StartBackend();
        backend
            .Given(Request.Create().WithPath("/call_tool"))
            .RespondWith(Response.Create()
                .WithStatusCode(statut)
                .WithHeader("Content-Type", "application/json")
                .WithBody(corpsBackend));

        var client = _fixture.CreateClient(new Dictionary<string, string> { ["mcp"] = backend.Url! });

        var response = await client.GetAsync("/api/v1/mcp/call_tool");

        Assert.Equal(statut, (int)response.StatusCode);
        Assert.Equal(corpsBackend, await response.Content.ReadAsStringAsync());
    }
}
