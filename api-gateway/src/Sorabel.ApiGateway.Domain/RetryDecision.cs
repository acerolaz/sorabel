using System.Net.Http;

namespace Sorabel.ApiGateway.Domain;

/// <summary>
/// Décide si un échec de transfert vers un backend peut être rejoué.
///
/// Le catalogue MCP n'expose que des appels POST, dont certains ont des effets
/// audités (run_sql_query s'exécute et se journalise) ou facturés (ask_database
/// déclenche une génération LLM). Un rejeu produirait une seconde exécution et
/// une seconde entrée d'audit, rendant E5 trompeur.
///
/// Le rejeu est donc restreint aux cas où l'on a la CERTITUDE que le backend
/// n'a rien reçu, et où la requête ne porte pas de corps : YARP transmet le
/// corps entrant en streaming via un contenu à usage unique, qu'un second essai
/// enverrait vide.
/// </summary>
public static class RetryDecision
{
    public static bool CanRetry(HttpRequestError error, bool requestHasBody)
    {
        if (requestHasBody)
        {
            return false;
        }

        return error is HttpRequestError.ConnectionError
                     or HttpRequestError.NameResolutionError;
    }
}
