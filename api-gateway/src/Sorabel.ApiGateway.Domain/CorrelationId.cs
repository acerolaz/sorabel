namespace Sorabel.ApiGateway.Domain;

/// <summary>
/// Identifiant de corrélation propagé de bout en bout par l'en-tête
/// X-Correlation-Id. Une valeur entrante non conforme est remplacée : elle
/// finit dans les logs, où un retour chariot permettrait d'injecter une
/// fausse ligne.
/// </summary>
public readonly record struct CorrelationId
{
    public const string HeaderName = "X-Correlation-Id";

    private const int MaxLength = 128;

    private CorrelationId(string value) => Value = value;

    public string Value { get; }

    public static CorrelationId New() => new(Guid.NewGuid().ToString("D"));

    public static CorrelationId FromHeaderOrNew(string? header)
        => TryParse(header, out var id) ? id : New();

    /// <remarks>
    /// <paramref name="id"/> n'est significatif que si la méthode retourne
    /// <c>true</c> : en cas d'échec, elle vaut <c>default</c>, dont
    /// <see cref="Value"/> est <c>null</c> — jamais à déréférencer sans avoir
    /// vérifié la valeur de retour.
    /// </remarks>
    public static bool TryParse(string? candidate, out CorrelationId id)
    {
        id = default;

        if (string.IsNullOrWhiteSpace(candidate) || candidate.Length > MaxLength)
        {
            return false;
        }

        foreach (var c in candidate)
        {
            if (!char.IsAsciiLetterOrDigit(c) && c is not ('-' or '_'))
            {
                return false;
            }
        }

        id = new CorrelationId(candidate);
        return true;
    }

    public override string ToString() => Value;
}
