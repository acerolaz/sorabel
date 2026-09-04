from collections.abc import Sequence

from app.domain.access_matrix import (
    RULE_COLLECTION_OUT_OF_SCOPE,
    RULE_TABLE_OUT_OF_SCOPE,
)
from app.domain.errors import UnauthorizedCollectionError, UnauthorizedTableError
from app.domain.models import Scope


def _resolve(requested: Sequence[str] | None, granted: tuple[str, ...]) -> tuple[str, ...] | None:
    """Périmètre effectif, ou `None` si la demande déborde `granted`.

    - `requested is None` (pas de demande explicite) : le périmètre accordé
      s'applique intégralement — c'est le cas nominal.
    - `requested` vide (`()`/`[]`, demande explicite de zéro ressource) :
      l'ensemble vide est un sous-ensemble valide de tout périmètre, donc
      honoré tel quel — distinct de `None`.
    - Sinon : la demande ne peut que *restreindre*, jamais élargir. Une seule
      valeur hors `granted` invalide la demande entière (pas d'intersection
      silencieuse qui « sauverait » la partie autorisée).
    - Comparaison exacte, sans normalisation de casse : une valeur mal cassée
      est une valeur inconnue du périmètre, donc refusée — jamais assouplie
      en un défaut permissif.
    - Le résultat est dédupliqué et rendu dans l'ordre canonique de
      `granted`, jamais dans l'ordre (arbitraire) de la demande : la sortie
      est déterministe quelle que soit la façon dont l'appelant a formulé sa
      demande.
    """
    if requested is None:
        return granted
    demande = set(requested)
    if not demande <= set(granted):
        return None
    return tuple(item for item in granted if item in demande)


def resolve_collections(
    requested: Sequence[str] | None, scope: Scope, correlation_id: str
) -> tuple[str, ...]:
    """Barrière 2 côté RAG (spec §4.2) : le périmètre transmis au backend vient
    de la matrice, jamais de l'appelant — une demande ne peut qu'affiner celui
    du profil, jamais l'élargir.

    Pure : reçoit `scope` en paramètre, ne lit aucun contexte global.
    """
    resolu = _resolve(requested, scope.rag_collections)
    if resolu is None:
        raise UnauthorizedCollectionError(correlation_id, matrix_rule=RULE_COLLECTION_OUT_OF_SCOPE)
    return resolu


def resolve_tables(
    requested: Sequence[str] | None, scope: Scope, correlation_id: str
) -> tuple[str, ...]:
    """Barrière 2 côté SQL (spec §4.2) : même règle que `resolve_collections`,
    appliquée à `Scope.sql_tables`.

    Pure : reçoit `scope` en paramètre, ne lit aucun contexte global.
    """
    resolu = _resolve(requested, scope.sql_tables)
    if resolu is None:
        raise UnauthorizedTableError(correlation_id, matrix_rule=RULE_TABLE_OUT_OF_SCOPE)
    return resolu
