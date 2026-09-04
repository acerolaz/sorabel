from app.domain.access_matrix import RULE_UNAUTHENTICATED, AccessMatrix
from app.domain.errors import UnauthenticatedError, UnauthorizedToolError
from app.domain.models import Allowed, Identity


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
    # `decision.error_code` vaut aujourd'hui toujours `UNAUTHORIZED_TOOL` (cf.
    # `AccessMatrix.decide`) : on lève le type dédié plutôt que de le consommer.
    # À revisiter si `decide` se met un jour à distinguer plusieurs codes.
    raise UnauthorizedToolError(correlation_id, matrix_rule=decision.rule)
