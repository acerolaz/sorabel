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
    public HttpClient CreateClient(IReadOnlyDictionary<string, string> destinations) =>
        CreateFactory(destinations).CreateClient();

    /// Variante qui capture toutes les lignes de log émises par la gateway.
    public HttpClient CreateClient(
        IReadOnlyDictionary<string, string> destinations,
        out List<string> journal)
    {
        var lignes = new List<string>();
        journal = lignes;

        var overrides = destinations.ToDictionary(
            kv => $"ReverseProxy:Clusters:{kv.Key}:Destinations:d1:Address",
            kv => (string?)kv.Value);

        var factory = new WebApplicationFactory<Program>()
            .WithWebHostBuilder(builder =>
            {
                builder.ConfigureAppConfiguration((_, config) => config.AddInMemoryCollection(overrides));
                builder.ConfigureLogging(logging =>
                {
                    logging.ClearProviders();
                    logging.SetMinimumLevel(LogLevel.Debug);
                    logging.AddProvider(new ListLoggerProvider(lignes));
                });
            });

        _factories.Add(factory);
        return factory.CreateClient();
    }

    /// <summary>
    /// Expose le conteneur DI de l'hôte en mémoire, pour vérifier une
    /// composition de services (ex. quelle implémentation a été résolue)
    /// sans passer par une requête HTTP.
    /// </summary>
    /// <param name="destinations">clusterId → adresse de base du backend.</param>
    public IServiceProvider CreateServices(IReadOnlyDictionary<string, string> destinations) =>
        CreateFactory(destinations).Services;

    private WebApplicationFactory<Program> CreateFactory(IReadOnlyDictionary<string, string> destinations)
    {
        var overrides = destinations.ToDictionary(
            kv => $"ReverseProxy:Clusters:{kv.Key}:Destinations:d1:Address",
            kv => (string?)kv.Value);

        var factory = new WebApplicationFactory<Program>()
            .WithWebHostBuilder(builder => builder.ConfigureAppConfiguration(
                (_, config) => config.AddInMemoryCollection(overrides)));

        _factories.Add(factory);
        return factory;
    }

    public void Dispose()
    {
        foreach (var factory in _factories) factory.Dispose();
        foreach (var server in _servers) server.Stop();
    }
}
