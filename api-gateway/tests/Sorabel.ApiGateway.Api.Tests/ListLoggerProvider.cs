using Microsoft.Extensions.Logging;

namespace Sorabel.ApiGateway.Api.Tests;

/// Capture chaque ligne de log formatée, pour pouvoir affirmer ce qui n'y figure pas.
public sealed class ListLoggerProvider(List<string> lignes) : ILoggerProvider
{
    public ILogger CreateLogger(string categoryName) => new ListLogger(lignes);

    public void Dispose() { }

    private sealed class ListLogger(List<string> lignes) : ILogger
    {
        public IDisposable? BeginScope<TState>(TState state) where TState : notnull => null;

        public bool IsEnabled(LogLevel logLevel) => true;

        public void Log<TState>(
            LogLevel logLevel, EventId eventId, TState state, Exception? exception,
            Func<TState, Exception?, string> formatter)
        {
            lock (lignes)
            {
                lignes.Add(formatter(state, exception));
            }
        }
    }
}
