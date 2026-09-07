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
///
/// Hypothèse non vérifiée, à documenter plutôt qu'à découvrir en prod :
/// <see cref="HttpRequestError.ConnectionError"/> est supposé se produire sur
/// le chemin d'ÉTABLISSEMENT de la connexion, avant tout octet de requête
/// écrit — c'est ce qui justifie la CERTITUDE ci-dessus. Si cette hypothèse
/// s'avérait fausse (un ConnectionError survenant après un envoi partiel),
/// l'exposition reste bornée aux requêtes sans corps par le garde-fou
/// `requestHasBody` ci-dessus : le pire cas resterait un rejeu d'une requête
/// déjà bornée à être rejouable sans corps, jamais un doublon d'une requête
/// avec effets de bord côté backend.
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
