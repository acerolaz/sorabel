using Sorabel.ApiGateway.Domain;
using Xunit;

namespace Sorabel.ApiGateway.Domain.Tests;

public class BackendIdTests
{
    // Ces littéraux sont le contrat inter-tâches : la Tâche 3 déclare les clusters
    // YARP avec exactement ces identifiants, la Tâche 7 les remappe vers un
    // BackendId via TryFromClusterId. Un renommage silencieux d'une des valeurs
    // doit faire échouer ce test.
    [Theory]
    [InlineData("idp")]
    [InlineData("mcp")]
    [InlineData("text2sql")]
    [InlineData("sql")]
    [InlineData("rag")]
    public void Chaque_backend_connu_expose_sa_valeur_exacte(string expected)
    {
        Assert.True(BackendId.TryFromClusterId(expected, out var id));
        Assert.Equal(expected, id.Value);
    }

    [Fact]
    public void Idp_expose_la_valeur_exacte()
    {
        Assert.Equal("idp", BackendId.Idp.Value);
    }

    [Fact]
    public void Mcp_expose_la_valeur_exacte()
    {
        Assert.Equal("mcp", BackendId.Mcp.Value);
    }

    [Fact]
    public void Text2Sql_expose_la_valeur_exacte()
    {
        Assert.Equal("text2sql", BackendId.Text2Sql.Value);
    }

    [Fact]
    public void Sql_expose_la_valeur_exacte()
    {
        Assert.Equal("sql", BackendId.Sql.Value);
    }

    [Fact]
    public void Rag_expose_la_valeur_exacte()
    {
        Assert.Equal("rag", BackendId.Rag.Value);
    }

    [Fact]
    public void All_contient_exactement_les_cinq_backends_connus()
    {
        var values = BackendId.All.Select(b => b.Value).ToArray();

        Assert.Equal(5, values.Length);
        Assert.Equal(
            new[] { "idp", "mcp", "text2sql", "sql", "rag" },
            values);
    }

    [Theory]
    [InlineData("idp")]
    [InlineData("mcp")]
    [InlineData("text2sql")]
    [InlineData("sql")]
    [InlineData("rag")]
    public void TryFromClusterId_reconnait_chaque_identifiant_connu(string clusterId)
    {
        var found = BackendId.TryFromClusterId(clusterId, out var id);

        Assert.True(found);
        Assert.Equal(clusterId, id.Value);
    }

    [Theory]
    [InlineData("inconnu")]
    [InlineData(null)]
    [InlineData("")]
    public void TryFromClusterId_refuse_un_identifiant_non_reconnu(string? clusterId)
    {
        var found = BackendId.TryFromClusterId(clusterId, out var id);

        Assert.False(found);
        Assert.Equal(default, id);
    }

    // Les ClusterId proviennent de notre propre appsettings.Routes.json : une
    // correspondance stricte à la casse est un choix légitime. Ce test fige ce
    // comportement plutôt que de le laisser implicite.
    [Fact]
    public void TryFromClusterId_est_sensible_a_la_casse()
    {
        var found = BackendId.TryFromClusterId("IDP", out var id);

        Assert.False(found);
    }
}
