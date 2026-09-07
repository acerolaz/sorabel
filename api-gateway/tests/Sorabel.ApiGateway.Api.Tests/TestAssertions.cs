using Xunit;

namespace Sorabel.ApiGateway.Api.Tests;

/// <summary>
/// Prouve l'invariant plutôt que de le supposer : si une valeur attendue non
/// nulle (payload WireMock, en-tête, champ JSON...) ne l'était pas, l'assertion
/// échoue ici avec un message clair, pas plus loin avec une
/// NullReferenceException sur une ligne arbitraire.
/// </summary>
internal static class TestAssertions
{
    public static T RequireNotNull<T>(T? value) where T : class
    {
        Assert.NotNull(value);
        return value;
    }
}
