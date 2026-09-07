namespace Sorabel.ApiGateway.Domain;

/// <summary>
/// Liste fermée des backends de la solution. La valeur correspond exactement
/// au ClusterId déclaré dans appsettings.Routes.json.
/// </summary>
public readonly record struct BackendId
{
    public static readonly BackendId Idp = new("idp");
    public static readonly BackendId Mcp = new("mcp");
    public static readonly BackendId Text2Sql = new("text2sql");
    public static readonly BackendId Sql = new("sql");
    public static readonly BackendId Rag = new("rag");

    private BackendId(string value) => Value = value;

    public string Value { get; }

    public static IReadOnlyList<BackendId> All => [Idp, Mcp, Text2Sql, Sql, Rag];

    /// <remarks>
    /// <paramref name="id"/> n'est significatif que si la méthode retourne
    /// <c>true</c> : en cas d'échec, elle vaut <c>default</c>, dont
    /// <see cref="Value"/> est <c>null</c> — jamais à déréférencer sans avoir
    /// vérifié la valeur de retour.
    /// </remarks>
    public static bool TryFromClusterId(string? clusterId, out BackendId id)
    {
        foreach (var candidate in All)
        {
            if (string.Equals(candidate.Value, clusterId, StringComparison.Ordinal))
            {
                id = candidate;
                return true;
            }
        }

        id = default;
        return false;
    }

    public override string ToString() => Value;
}
