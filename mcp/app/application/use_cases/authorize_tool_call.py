from app.domain.access_matrix import AccessMatrix
from app.domain.errors import UnauthenticatedError, UnauthorizedToolError
from app.domain.models import Allowed, Identity

# Règle d'audit d'un refus antérieur à toute consultation de la matrice : le
# token est absent, invalide ou expiré. Ce n'est pas une entrée de matrice, d'où
# le préfixe `fail_closed:` (cf. `AccessMatrix`, ruling C8).
RULE_UNAUTHENTICATED = "fail_closed:unauthenticated"


def authorize_tool_call(
    matrix: AccessMatrix, identity: Identity | None, tool: str, correlation_id: str
) -> Allowed:
    """Barrière 1 : autorise l'appel ou lève une erreur typée.

    Levée avant tout dispatch — la fonction du tool n'est jamais atteinte quand
    la décision est un refus.

    `identity is None` est traité ici comme un refus `UNAUTHENTICATED`, en
    doublure de la vérification faite à l'entrée de `call_tool` : ce use case
    reste sûr quel que soit son appelant (fail closed, spec §5).

    La règle de matrice (`Decision.rule`) voyage jusqu'à l'audit par le mot-clé
    `matrix_rule` de l'erreur, qui n'apparaît jamais dans le corps JSON rendu au
    client — un refus ne confirme donc jamais l'existence d'une ressource non
    autorisée (spec §7).
    """
    if identity is None:
        raise UnauthenticatedError(correlation_id, matrix_rule=RULE_UNAUTHENTICATED)

    decision = matrix.decide(identity.profile, tool)
    if isinstance(decision, Allowed):
        return decision
    raise UnauthorizedToolError(correlation_id, matrix_rule=decision.rule)
