"""Pont entre le contexte d'appel (`app/api/context.py`) et les barrières.

Un **seul** helper, partagé par `rag.py` et `sql.py` : la lecture des
`ContextVar` posés par `GovernedFastMCP.call_tool` est identique des deux côtés,
et une politique de sécurité dupliquée est une politique qui finit par diverger.

`resolve_collections`/`resolve_tables` (barrière 2) sont des fonctions **pures**
qui reçoivent le `Scope` en paramètre : c'est ici, dans `api/`, que le contexte
global est lu — jamais dans `application/`, qui n'a pas à connaître `api/`.
"""

from app.api.context import current_correlation_id, current_identity, current_scope
from app.domain.access_matrix import RULE_UNAUTHENTICATED
from app.domain.errors import UnauthenticatedError
from app.domain.models import Identity, Scope


def call_context() -> tuple[Identity, Scope, str]:
    """Identité, périmètre et corrélation de l'appel en cours.

    La barrière 1 les a posés juste avant le dispatch : un contexte vide
    signifie que la fonction du tool a été atteinte hors de ce chemin. C'est
    alors un refus explicite `UNAUTHENTICATED`, jamais un `assert` — que
    `python -O` supprimerait, dégradant le garde en `AttributeError` non typée
    au lieu d'un refus.
    """
    correlation_id = current_correlation_id.get()
    identity = current_identity.get()
    scope = current_scope.get()
    if identity is None or scope is None:
        raise UnauthenticatedError(correlation_id, matrix_rule=RULE_UNAUTHENTICATED)
    return identity, scope, correlation_id
