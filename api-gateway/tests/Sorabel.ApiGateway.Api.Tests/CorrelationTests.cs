using Sorabel.ApiGateway.Domain;
using WireMock.RequestBuilders;
using WireMock.ResponseBuilders;
using Xunit;

namespace Sorabel.ApiGateway.Api.Tests;

[Trait("Level", "3")]
public class CorrelationTests : IClassFixture<GatewayFixture>
{
    private readonly GatewayFixture _fixture;

    public CorrelationTests(GatewayFixture fixture) => _fixture = fixture;

    private (HttpClient Client, WireMock.Server.WireMockServer Backend) Arrange()
    {
        var backend = _fixture.StartBackend();
        backend
            .Given(Request.Create().WithPath("/call_tool"))
            .RespondWith(Response.Create().WithStatusCode(200));

        var client = _fixture.CreateClient(new Dictionary<string, string> { ["mcp"] = backend.Url! });
        return (client, backend);
    }

    // Prouve l'invariant plutôt que de le supposer : si WireMock ne renseignait pas
    // la requête ou ses en-têtes, l'assertion échoue ici avec un message clair, pas
    // plus loin avec une NullReferenceException sur une ligne arbitraire.
    private static T RequireNotNull<T>(T? value) where T : class
    {
        Assert.NotNull(value);
        return value;
    }

    [Fact]
    public async Task Genere_un_identifiant_quand_le_client_n_en_fournit_pas()
    {
        var (client, backend) = Arrange();

        var response = await client.GetAsync("/api/v1/mcp/call_tool");

        var renvoye = Assert.Single(response.Headers.GetValues(CorrelationId.HeaderName));
        Assert.False(string.IsNullOrWhiteSpace(renvoye));

        var recue = Assert.Single(backend.LogEntries);
        var requestMessage = RequireNotNull(recue.RequestMessage);
        var headers = RequireNotNull(requestMessage.Headers);
        var transmis = headers[CorrelationId.HeaderName].Single();
        Assert.Equal(renvoye, transmis);
    }

    [Fact]
    public async Task Propage_l_identifiant_fourni_par_l_appelant()
    {
        var (client, backend) = Arrange();
        client.DefaultRequestHeaders.Add(CorrelationId.HeaderName, "trace-de-mcp-42");

        var response = await client.GetAsync("/api/v1/mcp/call_tool");

        var recue = Assert.Single(backend.LogEntries);
        var requestMessage = RequireNotNull(recue.RequestMessage);
        var headers = RequireNotNull(requestMessage.Headers);
        Assert.Equal("trace-de-mcp-42", headers[CorrelationId.HeaderName].Single());
        Assert.Equal("trace-de-mcp-42", response.Headers.GetValues(CorrelationId.HeaderName).Single());
    }

    [Fact]
    public async Task Remplace_un_identifiant_entrant_non_conforme()
    {
        var (client, backend) = Arrange();
        client.DefaultRequestHeaders.TryAddWithoutValidation(CorrelationId.HeaderName, "valeur invalide!");

        await client.GetAsync("/api/v1/mcp/call_tool");

        var recue = Assert.Single(backend.LogEntries);
        var requestMessage = RequireNotNull(recue.RequestMessage);
        var headers = RequireNotNull(requestMessage.Headers);
        var transmis = headers[CorrelationId.HeaderName].Single();
        Assert.NotEqual("valeur invalide!", transmis);
    }
}
