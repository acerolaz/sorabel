namespace Sorabel.ApiGateway.Domain;

/// <summary>
/// En-têtes qui ne doivent jamais apparaître dans un log, sous aucune forme.
/// La gateway relaie le JWT sans le lire ; elle ne doit pas non plus le laisser
/// fuiter par la journalisation.
/// </summary>
public static class SensitiveHeaders
{
    public static IReadOnlySet<string> Names { get; } =
        new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            "Authorization",
            "Proxy-Authorization",
            "Cookie",
            "Set-Cookie",
        };

    public static bool IsSensitive(string headerName) => Names.Contains(headerName);
}
