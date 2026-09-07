using Microsoft.Extensions.Logging;

namespace Sorabel.ApiGateway.Api.Tests;

/// Capture chaque ligne de log formatée, pour pouvoir affirmer ce qui n'y figure pas.
public sealed class ListLoggerProvider(List<string> lignes) : ILoggerProvider
{
    public ILogger CreateLogger(string categoryName) => new ListLogger(lignes);

    public void Dispose() { }

    private sealed class ListLogger(List<string> lignes) : ILogger
    {
        // AsyncLocal, pas un champ d'instance : ILogger est résolu une seule
        // fois par catégorie (partagé entre requêtes), alors que le scope est
        // par appel logique — un champ d'instance ferait fuiter le scope
        // d'une requête vers une autre exécutée en parallèle.
        private static readonly AsyncLocal<string?> ScopeActuel = new();

        // Capture et stringifie l'état de scope : sans quoi un composant qui
        // ne journalise que via BeginScope (jamais via un message direct)
        // resterait invisible du test de fuite (LoggingTests), qui n'inspecte
        // que le texte des lignes journalisées.
        public IDisposable BeginScope<TState>(TState state) where TState : notnull
        {
            var precedent = ScopeActuel.Value;
            ScopeActuel.Value = Formate(state);
            return new ScopeRestaurateur(() => ScopeActuel.Value = precedent);
        }

        // Les scopes structurés (ex. CorrelationMiddleware.BeginScope(new
        // Dictionary<string, object> { ... })) donneraient un ToString() sans
        // intérêt ("System.Collections.Generic.Dictionary`2[...]") : on
        // reconstitue plutôt les paires clé=valeur pour que leur contenu soit
        // effectivement cherchable par les tests de fuite.
        private static string Formate<TState>(TState state) where TState : notnull => state switch
        {
            IEnumerable<KeyValuePair<string, object>> paires =>
                string.Join(",", paires.Select(p => $"{p.Key}={p.Value}")),
            _ => state.ToString() is { } texte ? texte : string.Empty,
        };

        public bool IsEnabled(LogLevel logLevel) => true;

        public void Log<TState>(
            LogLevel logLevel, EventId eventId, TState state, Exception? exception,
            Func<TState, Exception?, string> formatter)
        {
            var message = formatter(state, exception);
            var scope = ScopeActuel.Value;
            var ligne = string.IsNullOrEmpty(scope) ? message : $"{message} [scope={scope}]";

            lock (lignes)
            {
                lignes.Add(ligne);
            }
        }

        private sealed class ScopeRestaurateur(Action onDispose) : IDisposable
        {
            public void Dispose() => onDispose();
        }
    }
}
