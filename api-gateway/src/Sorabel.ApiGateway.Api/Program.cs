using Sorabel.ApiGateway.Infrastructure.Correlation;
using Sorabel.ApiGateway.Infrastructure.Errors;
using Sorabel.ApiGateway.Infrastructure.Logging;
using Sorabel.ApiGateway.Infrastructure.Resilience;
using Yarp.ReverseProxy.Forwarder;

// Sonde de santé invoquée par le HEALTHCHECK Docker : l'image aspnet ne
// contient ni curl ni wget, on réutilise donc le binaire lui-même.
if (args.Contains("--healthcheck"))
{
    using var sonde = new HttpClient { Timeout = TimeSpan.FromSeconds(3) };
    try
    {
        var reponse = await sonde.GetAsync("http://localhost:8080/health");
        return reponse.IsSuccessStatusCode ? 0 : 1;
    }
    catch (Exception ex) when (ex is HttpRequestException or TaskCanceledException)
    {
        return 1;
    }
}

var builder = WebApplication.CreateBuilder(args);

builder.Configuration.AddJsonFile("appsettings.Routes.json", optional: false, reloadOnChange: true);

// CreateBuilder(args) a déjà ajouté les variables d'environnement avant ce
// point ; comme la dernière source ajoutée gagne, le fichier de routes
// ci-dessus les écraserait sans ce ré-ajout. C'est ce mécanisme qui permet de
// surcharger une adresse de cluster via
// ReverseProxy__Clusters__<id>__Destinations__d1__Address (cf. docker-compose.yml).
builder.Configuration.AddEnvironmentVariables();

builder.Services.AddSingleton<IForwarderHttpClientFactory, ResilientForwarderHttpClientFactory>();

builder.Services
    .AddReverseProxy()
    .LoadFromConfig(builder.Configuration.GetSection("ReverseProxy"))
    .AddTransforms(CorrelationTransform.Register);
builder.Services.AddRequestTimeouts();

var app = builder.Build();

app.UseRequestTimeouts();
app.UseMiddleware<CorrelationMiddleware>();
app.UseMiddleware<RequestLoggingMiddleware>();
app.UseMiddleware<ForwarderErrorMiddleware>();

app.MapGet("/health", () => Results.Ok(new { status = "healthy" }));
app.MapReverseProxy();

app.Run();
return 0;

// Rendu visible pour WebApplicationFactory<Program> dans les tests.
public partial class Program;
