using System.Net;
using System.Text.Json;
using WireMock.RequestBuilders;
using WireMock.ResponseBuilders;
using Xunit;

namespace Sorabel.ApiGateway.Api.Tests;

[Trait("Level", "3")]
public class ErrorContractTests : IClassFixture<GatewayFixture>
{
    private readonly GatewayFixture _fixture;

    public ErrorContractTests(GatewayFixture fixture) => _fixture = fixture;

    // Prouve l'invariant plutôt que de le supposer : si le payload ne portait pas
    // le champ attendu, l'assertion échoue ici avec un message clair, pas plus
    // loin avec une NullReferenceException sur une ligne arbitraire.
    private static T RequireNotNull<T>(T? value) where T : class
    {
        Assert.NotNull(value);
        return value;
    }

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
