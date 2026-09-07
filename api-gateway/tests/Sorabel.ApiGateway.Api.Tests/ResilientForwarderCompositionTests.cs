using Microsoft.Extensions.DependencyInjection;
using Sorabel.ApiGateway.Infrastructure.Resilience;
using Xunit;
using Yarp.ReverseProxy.Forwarder;

namespace Sorabel.ApiGateway.Api.Tests;

// Pin la composition DI, pas seulement le handler : RetryHandlerTests prouve le
// comportement de RetryHandler en l'isolant derrière son propre
// HttpMessageInvoker, mais ne prouve jamais que YARP l'utilise réellement.
// L'enregistrement de ResilientForwarderHttpClientFactory doit précéder
// AddReverseProxy() dans Program.cs — YARP enregistre son propre
// IForwarderHttpClientFactory par défaut en TryAdd, qui ne cède la place qu'à
// une registration déjà présente. Si cet ordre venait à être inversé, les 5
// tests de RetryHandlerTests resteraient verts (ils n'exercent jamais le vrai
// chemin de forwarding) alors que le rejeu disparaîtrait silencieusement de la
// gateway réelle — ce test est le seul signal qui casserait dans ce scénario.
[Trait("Level", "3")]
public class ResilientForwarderCompositionTests(GatewayFixture fixture) : IClassFixture<GatewayFixture>
{
    [Fact]
    public void Resout_la_fabrique_resiliente_pour_le_forwarder_http()
    {
        var services = fixture.CreateServices(new Dictionary<string, string>());

        var factory = services.GetRequiredService<IForwarderHttpClientFactory>();

        Assert.IsType<ResilientForwarderHttpClientFactory>(factory);
    }
}
