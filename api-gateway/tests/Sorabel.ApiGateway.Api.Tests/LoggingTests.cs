using System.Net.Http.Headers;
using WireMock.RequestBuilders;
using WireMock.ResponseBuilders;
using Xunit;

namespace Sorabel.ApiGateway.Api.Tests;

[Trait("Level", "3")]
public class LoggingTests : IClassFixture<GatewayFixture>
{
    private readonly GatewayFixture _fixture;

    public LoggingTests(GatewayFixture fixture) => _fixture = fixture;

    [Fact]
    public async Task Journalise_une_ligne_par_requete_relayee()
    {
        var backend = _fixture.StartBackend();
        backend
            .Given(Request.Create().WithPath("/call_tool"))
            .RespondWith(Response.Create().WithStatusCode(200));

        var client = _fixture.CreateClient(
            new Dictionary<string, string> { ["mcp"] = backend.Url! }, out var journal);

        await client.GetAsync("/api/v1/mcp/call_tool");

        var ligne = Assert.Single(journal, l => l.Contains("backend=mcp"));
        Assert.Contains("status=200", ligne);
        Assert.Contains("method=GET", ligne);
        Assert.Contains("/api/v1/mcp/call_tool", ligne);
    }

    // Non-négociable de sécurité : le JWT traverse la gateway sans jamais
    // apparaître dans un log, sous aucune forme.
    [Fact]
    public async Task Ne_journalise_jamais_le_jeton_ni_l_entete_Authorization()
    {
        const string jeton = "eyJhbGciOiJSUzI1NiJ9.SECRET-A-NE-PAS-JOURNALISER.signature";

        var backend = _fixture.StartBackend();
        backend
            .Given(Request.Create().WithPath("/call_tool"))
            .RespondWith(Response.Create().WithStatusCode(200));

        var client = _fixture.CreateClient(
            new Dictionary<string, string> { ["mcp"] = backend.Url! }, out var journal);
        client.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", jeton);

        await client.GetAsync("/api/v1/mcp/call_tool");

        var tout = string.Join("\n", journal);
        Assert.DoesNotContain("SECRET-A-NE-PAS-JOURNALISER", tout);
        Assert.DoesNotContain(jeton, tout);
        Assert.DoesNotContain("Bearer", tout);
    }
}
