using Sorabel.ApiGateway.Infrastructure.Correlation;
using Sorabel.ApiGateway.Infrastructure.Errors;
using Sorabel.ApiGateway.Infrastructure.Logging;
using Sorabel.ApiGateway.Infrastructure.Resilience;
using Yarp.ReverseProxy.Forwarder;

var builder = WebApplication.CreateBuilder(args);

builder.Configuration.AddJsonFile("appsettings.Routes.json", optional: false, reloadOnChange: true);

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

// Rendu visible pour WebApplicationFactory<Program> dans les tests.
public partial class Program;
