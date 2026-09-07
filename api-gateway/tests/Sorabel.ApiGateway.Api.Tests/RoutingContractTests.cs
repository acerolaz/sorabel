using System.Net;
using System.Net.Http.Headers;
using WireMock.RequestBuilders;
using WireMock.ResponseBuilders;
using Xunit;
using static Sorabel.ApiGateway.Api.Tests.TestAssertions;

namespace Sorabel.ApiGateway.Api.Tests;

[Trait("Level", "3")]
public class RoutingContractTests : IClassFixture<GatewayFixture>
{
    private readonly GatewayFixture _fixture;

    public RoutingContractTests(GatewayFixture fixture) => _fixture = fixture;

    // Les 6 routes du contrat, avec le cluster qu'elles doivent atteindre et le
    // chemin que le backend doit recevoir une fois le préfixe retiré.
    public static TheoryData<string, string, string> Routes => new()
    {
        { "idp",      "/api/v1/auth/realms/sorabel-data-gate/token", "/realms/sorabel-data-gate/token" },
        { "mcp",      "/api/v1/mcp/call_tool",                       "/call_tool" },
        { "idp",      "/internal/v1/auth/realms/x/certs",            "/realms/x/certs" },
        { "text2sql", "/internal/v1/text2sql/generate",              "/generate" },
        { "sql",      "/internal/v1/sql/run",                        "/run" },
        { "rag",      "/internal/v1/rag/search",                     "/search" },
    };

    [Theory]
    [MemberData(nameof(Routes))]
    public async Task Atteint_le_bon_backend_avec_le_prefixe_retire(
        string clusterId, string cheminEntrant, string cheminAttendu)
    {
        var backend = _fixture.StartBackend();
        backend
            .Given(Request.Create().WithPath(cheminAttendu))
            .RespondWith(Response.Create().WithStatusCode(200).WithBody("ok"));

        var client = _fixture.CreateClient(new Dictionary<string, string>
        {
            [clusterId] = backend.Url!,
        });

        var response = await client.GetAsync(cheminEntrant);

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Equal("ok", await response.Content.ReadAsStringAsync());

        var recue = Assert.Single(backend.LogEntries);
        var requestMessage = RequireNotNull(recue.RequestMessage);
        Assert.Equal(cheminAttendu, requestMessage.Path);
    }

    // Non-négociable : le JWT traverse la gateway sans être lu ni modifié.
    [Fact]
    public async Task Relaie_l_entete_Authorization_octet_pour_octet()
    {
        const string jeton = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.charge-utile.signature";

        var backend = _fixture.StartBackend();
        backend
            .Given(Request.Create().WithPath("/call_tool"))
            .RespondWith(Response.Create().WithStatusCode(200));

        var client = _fixture.CreateClient(new Dictionary<string, string> { ["mcp"] = backend.Url! });
        client.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", jeton);

        await client.GetAsync("/api/v1/mcp/call_tool");

        var recue = Assert.Single(backend.LogEntries);
        var requestMessage = RequireNotNull(recue.RequestMessage);
        var headers = RequireNotNull(requestMessage.Headers);
        Assert.Equal($"Bearer {jeton}", headers["Authorization"].Single());
    }

    [Fact]
    public async Task Health_repond_sans_toucher_a_un_backend()
    {
        var client = _fixture.CreateClient(new Dictionary<string, string>());

        var response = await client.GetAsync("/health");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
    }
}
