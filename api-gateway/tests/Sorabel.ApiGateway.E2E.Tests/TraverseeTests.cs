using System.Net;
using Xunit;

namespace Sorabel.ApiGateway.E2E.Tests;

/// <summary>
/// Niveau 4 : la gateway telle qu'elle sera déployée, dans son conteneur, avec
/// sa configuration réelle. Prouve ce que les niveaux 1 à 3 ne peuvent pas —
/// que l'image se construit, se configure et démarre.
///
/// Suppose `make docker-up` déjà exécuté (make test-e2e s'en charge).
/// </summary>
[Trait("Category", "E2E")]
public class TraverseeTests
{
    private static readonly string BaseUrl =
        Environment.GetEnvironmentVariable("API_GATEWAY_URL") ?? "http://localhost:8080";

    private static HttpClient Client() => new() { BaseAddress = new Uri(BaseUrl), Timeout = TimeSpan.FromSeconds(20) };

    [Fact]
    public async Task La_gateway_demarree_repond_sur_health()
    {
        using var client = Client();

        var response = await client.GetAsync("/health");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
    }

    [Fact]
    public async Task Une_requete_traverse_reellement_jusqu_au_backend()
    {
        using var client = Client();

        var response = await client.GetAsync("/internal/v1/text2sql/generate");
        var corps = await response.Content.ReadAsStringAsync();

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);

        // whoami renvoie la ligne de requête reçue : le préfixe doit avoir été retiré.
        Assert.Contains("GET /generate", corps);
        Assert.DoesNotContain("/internal/v1/text2sql", corps);

        // et le correlation ID doit être arrivé jusqu'à lui.
        Assert.Contains("X-Correlation-Id:", corps, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public async Task Un_backend_absent_donne_un_502_au_format_du_contrat()
    {
        using var client = Client();

        var response = await client.GetAsync("/internal/v1/rag/search");
        var corps = await response.Content.ReadAsStringAsync();

        Assert.Equal(HttpStatusCode.BadGateway, response.StatusCode);
        Assert.Contains("BACKEND_UNREACHABLE", corps);
        Assert.Contains("correlation_id", corps);
    }
}
