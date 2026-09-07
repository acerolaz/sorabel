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

        var factory = CreateFactory(destinations, builder => builder.ConfigureLogging(logging =>
        {
            logging.ClearProviders();
            logging.SetMinimumLevel(LogLevel.Debug);
            logging.AddProvider(new ListLoggerProvider(lignes));
        }));

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

    /// <param name="destinations">clusterId → adresse de base du backend.</param>
    /// <param name="configOverrides">
    /// Clés de configuration arbitraires (ex. "ReverseProxy:Routes:mcp-public:Timeout"),
    /// surchargées de la même façon que les adresses de cluster.
    /// </param>
    public HttpClient CreateClient(
        IReadOnlyDictionary<string, string> destinations,
        IReadOnlyDictionary<string, string> configOverrides) =>
        CreateFactory(destinations, configOverrides).CreateClient();

    private WebApplicationFactory<Program> CreateFactory(
        IReadOnlyDictionary<string, string> destinations,
        Action<IWebHostBuilder>? configureBuilder = null) =>
        CreateFactory(destinations, configOverrides: null, configureBuilder);

    private WebApplicationFactory<Program> CreateFactory(
        IReadOnlyDictionary<string, string> destinations,
        IReadOnlyDictionary<string, string>? configOverrides,
        Action<IWebHostBuilder>? configureBuilder = null)
    {
        var overrides = destinations.ToDictionary(
            kv => $"ReverseProxy:Clusters:{kv.Key}:Destinations:d1:Address",
            kv => (string?)kv.Value);

        if (configOverrides is not null)
        {
            foreach (var (cle, valeur) in configOverrides)
            {
                overrides[cle] = valeur;
            }
        }

        var factory = new WebApplicationFactory<Program>()
            .WithWebHostBuilder(builder =>
            {
                builder.ConfigureAppConfiguration((_, config) => config.AddInMemoryCollection(overrides));
                configureBuilder?.Invoke(builder);
            });

        _factories.Add(factory);
        return factory;
    }

    public void Dispose()
    {
        foreach (var factory in _factories) factory.Dispose();
        foreach (var server in _servers) server.Stop();
    }
}
