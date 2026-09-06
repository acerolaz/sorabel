using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;
using WireMock.Server;

namespace Sorabel.ApiGateway.Api.Tests;

/// <summary>
/// Démarre la gateway en mémoire, avec des backends WireMock à la place des
/// vraies destinations. Les adresses sont surchargées par configuration,
/// exactement comme elles le seront en production.
/// </summary>
public sealed class GatewayFixture : IDisposable
{
    private readonly List<WireMockServer> _servers = [];
    private readonly List<WebApplicationFactory<Program>> _factories = [];

    public WireMockServer StartBackend()
    {
        var server = WireMockServer.Start();
        _servers.Add(server);
        return server;
    }

    /// <param name="destinations">clusterId → adresse de base du backend.</param>
    public HttpClient CreateClient(IReadOnlyDictionary<string, string> destinations)
    {
        var overrides = destinations.ToDictionary(
            kv => $"ReverseProxy:Clusters:{kv.Key}:Destinations:d1:Address",
            kv => (string?)kv.Value);

        var factory = new WebApplicationFactory<Program>()
            .WithWebHostBuilder(builder => builder.ConfigureAppConfiguration(
                (_, config) => config.AddInMemoryCollection(overrides)));

        _factories.Add(factory);
        return factory.CreateClient();
    }

    public void Dispose()
    {
        foreach (var factory in _factories) factory.Dispose();
        foreach (var server in _servers) server.Stop();
    }
}
