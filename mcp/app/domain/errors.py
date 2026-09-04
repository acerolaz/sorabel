import json


class InvalidTokenError(Exception):
    """Le token est absent, mal formé, expiré ou mal signé."""


class ToolError(Exception):
    """Erreur rendue au client dans un CallToolResult `isError`.

    Le serveur bas niveau du SDK MCP transforme en résultat `isError: true`,
    de contenu `str(exception)`, toute exception qui remonte **jusqu'à lui**.
    On place donc dans `__str__` le corps d'erreur uniforme de
    `api-contracts.md`, et rien d'autre.

    Cette propriété ne tient toutefois que pour les erreurs qui l'atteignent
    intactes. Une erreur levée *pendant* le dispatch d'un tool traverse
    d'abord `ToolManager.call_tool`, qui la réenveloppe dans la `ToolError` du
    SDK (`mcp.server.fastmcp.exceptions`) préfixée d'un texte narratif anglais
    — `str()` cesse alors d'être parsable en JSON. C'est
    `GovernedFastMCP.call_tool` qui rétablit le contrat, en relevant l'erreur
    domaine (récupérée par `__cause__`) à la place de l'enveloppe du SDK :
    sans cette reprise, seuls les refus de la barrière 1 respecteraient la
    spec §7.

    `matrix_rule` (ruling C8) porte la règle de matrice appliquée lors de la
    décision d'autorisation qui a produit cette erreur. Il n'est **jamais**
    inclus dans `str(error)` — le corps JSON rendu au client reste strictement
    `{error_code, message, correlation_id}` — mais reste lisible en attribut
    Python pour que la tâche 10 (journal d'audit) renseigne `AuditEntry.rule`
    sans que cette information ne fuite vers l'appelant.
    """

    error_code = "INTERNAL_ERROR"  # Code de repli, hors de la table §7 de la spec.
    message = "Erreur interne"

    def __init__(self, correlation_id: str, *, matrix_rule: str | None = None) -> None:
        self.correlation_id = correlation_id
        self.matrix_rule = matrix_rule
        super().__init__(str(self))

    def __str__(self) -> str:
        return json.dumps(
            {
                "error_code": self.error_code,
                "message": self.message,
                "correlation_id": self.correlation_id,
            },
            ensure_ascii=False,
        )


class UnauthenticatedError(ToolError):
    error_code = "UNAUTHENTICATED"
    message = "Authentification requise"


class UnauthorizedToolError(ToolError):
    error_code = "UNAUTHORIZED_TOOL"
    message = "Accès non autorisé pour ce profil"


class UnauthorizedCollectionError(ToolError):
    error_code = "UNAUTHORIZED_COLLECTION"
    message = "Périmètre documentaire non autorisé pour ce profil"


class UnauthorizedTableError(ToolError):
    error_code = "UNAUTHORIZED_TABLE"
    message = "Périmètre de données non autorisé pour ce profil"


class NotFoundInCorpusError(ToolError):
    error_code = "NOT_FOUND_IN_CORPUS"
    message = "Information absente du corpus documentaire"


class SchemaMismatchError(ToolError):
    error_code = "SCHEMA_MISMATCH"
    message = "Requête invalide au regard du schéma accessible"


class BackendUnavailableError(ToolError):
    error_code = "BACKEND_UNAVAILABLE"
    message = "Service en aval indisponible"
