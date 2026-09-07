using Sorabel.ApiGateway.Domain;
using Xunit;

namespace Sorabel.ApiGateway.Domain.Tests;

public class CorrelationIdTests
{
    [Fact]
    public void New_genere_un_identifiant_non_vide_et_unique()
    {
        var a = CorrelationId.New();
        var b = CorrelationId.New();

        Assert.False(string.IsNullOrWhiteSpace(a.Value));
        Assert.NotEqual(a.Value, b.Value);
    }

    [Fact]
    public void Reprend_un_identifiant_entrant_valide()
    {
        var id = CorrelationId.FromHeaderOrNew("7f3a91e4-1234-4abc-9def-000000000001");

        Assert.Equal("7f3a91e4-1234-4abc-9def-000000000001", id.Value);
    }

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("   ")]
    public void Genere_un_identifiant_quand_l_entete_est_absent(string? header)
    {
        var id = CorrelationId.FromHeaderOrNew(header);

        Assert.False(string.IsNullOrWhiteSpace(id.Value));
    }

    // L'en-tête est contrôlé par l'appelant et finit dans les logs : un retour
    // chariot permettrait d'y injecter une fausse ligne. Une valeur non conforme
    // est remplacée, jamais assainie puis conservée.
    [Theory]
    [InlineData("abc\r\nFAUSSE-LIGNE: injection")]
    [InlineData("abc\ndef")]
    [InlineData("valeur avec espaces")]
    [InlineData("point.virgule;")]
    [InlineData("<script>")]
    public void Remplace_une_valeur_entrante_non_conforme(string header)
    {
        var id = CorrelationId.FromHeaderOrNew(header);

        Assert.NotEqual(header, id.Value);
        Assert.DoesNotContain('\r', id.Value);
        Assert.DoesNotContain('\n', id.Value);
    }

    [Fact]
    public void Remplace_une_valeur_entrante_trop_longue()
    {
        var trop_long = new string('a', 129);

        var id = CorrelationId.FromHeaderOrNew(trop_long);

        Assert.NotEqual(trop_long, id.Value);
    }
}
