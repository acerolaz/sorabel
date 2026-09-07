using Sorabel.ApiGateway.Domain;
using Xunit;

namespace Sorabel.ApiGateway.Domain.Tests;

public class RoutingErrorTests
{
    [Fact]
    public void Backend_injoignable_est_un_502_avec_un_code_metier_stable()
    {
        var error = new RoutingError(RoutingErrorKind.BackendUnreachable);

        Assert.Equal(502, error.StatusCode);
        Assert.Equal("BACKEND_UNREACHABLE", error.ErrorCode);
    }

    [Fact]
    public void Timeout_backend_est_un_504_avec_un_code_metier_stable()
    {
        var error = new RoutingError(RoutingErrorKind.BackendTimeout);

        Assert.Equal(504, error.StatusCode);
        Assert.Equal("BACKEND_TIMEOUT", error.ErrorCode);
    }

    // Le message d'erreur ne doit pas cartographier la topologie interne :
    // ni nom de backend, ni nom d'hôte, ni port.
    [Theory]
    [InlineData(RoutingErrorKind.BackendUnreachable)]
    [InlineData(RoutingErrorKind.BackendTimeout)]
    public void Le_message_ne_nomme_aucun_backend(RoutingErrorKind kind)
    {
        var message = new RoutingError(kind).Message;

        foreach (var interdit in new[] { "mcp", "text2sql", "keycloak", "sorabelsql", "rag", "http", ":8" })
        {
            Assert.DoesNotContain(interdit, message, StringComparison.OrdinalIgnoreCase);
        }
    }
}
