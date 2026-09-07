namespace Sorabel.ApiGateway.Domain;

/// <summary>
/// En-têtes qui ne doivent jamais apparaître dans un log, sous aucune forme.
/// La gateway relaie le JWT sans le lire ; elle ne doit pas non plus le laisser
/// fuiter par la journalisation.
///
/// STATUT : ce type n'est actuellement consommé par rien dans le code — ni
/// <c>RequestLoggingMiddleware</c>, ni aucun autre composant, ne l'utilisent
/// pour filtrer quoi que ce soit. Ce n'est pas un oubli : <c>RequestLoggingMiddleware</c>
/// applique une garantie strictement plus forte (une liste d'autorisation de
/// six champs scalaires — corrélation, méthode, chemin, backend, statut,
/// durée — jamais un en-tête, quel qu'il soit) plutôt qu'une liste de blocage
/// à tenir à jour. Ce type reste néanmoins présent, à la demande de la spec et
/// du plan d'implémentation, comme garde-fou documentaire : si un futur
/// contributeur ajoute un jour la journalisation d'en-têtes bruts, il ne doit
/// PAS supposer qu'un filtrage existe déjà ailleurs — il n'y en a aucun, et
/// <see cref="Names"/> devra alors être consulté explicitement à ce moment-là.
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
