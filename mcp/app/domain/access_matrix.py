from collections.abc import Mapping
from dataclasses import dataclass

from app.domain.catalog import CATALOG_BY_NAME
from app.domain.models import Allowed, Decision, Denied, Scope

#: Refus antérieur à toute consultation de la matrice : le token porté par
#: l'appel est absent, invalide ou expiré. Ce n'est pas une entrée de matrice,
#: d'où le préfixe `fail_closed:` — voir la convention de `AccessMatrix`.
RULE_UNAUTHENTICATED = "fail_closed:unauthenticated"

#: Barrière 2 (spec §4.2) : la demande de l'appelant déborde le périmètre
#: (`Scope.rag_collections` / `Scope.sql_tables`) que la matrice a accordé à
#: son profil pour ce tool. Comme pour `RULE_UNAUTHENTICATED`, ce n'est pas
#: une entrée de matrice mais un défaut de sécurité — d'où le même préfixe
#: `fail_closed:` — et la règle ne distingue jamais « hors périmètre » de
#: « ressource inexistante » : elle n'est de toute façon jamais exposée au
#: client (seul `error_code` l'est, via `ToolError`).
RULE_COLLECTION_OUT_OF_SCOPE = "fail_closed:collection_out_of_scope"
RULE_TABLE_OUT_OF_SCOPE = "fail_closed:table_out_of_scope"


def projection_rule(profile: str) -> str:
    """Règle journalisée pour une projection de catalogue (`list_tools` autorisé).

    Distincte de `matrix:{profile}:{tool}`, produit par `decide()` pour une
    autorisation d'appel précise : une projection ne pointe aucun tool unique,
    elle filtre le catalogue entier pour ce profil.
    """
    return f"projection:{profile}"


@dataclass(frozen=True)
class ProfileEntry:
    """Droits d'un profil : les tools qu'il peut appeler et son périmètre de données."""

    tools: frozenset[str]
    scope: Scope


@dataclass(frozen=True)
class AccessMatrix:
    """Matrice profil × tool × périmètre, source unique d'autorisation.

    Convention de nommage de `Decision.rule` (ruling C8) : `rule` identifie
    *pourquoi* une décision a été prise, jamais une recopie de son
    `error_code`. Deux familles :

    - Autorisation accordée : ``matrix:{profile}:{tool}`` — pointe l'entrée
      exacte de la matrice qui a accordé l'accès.
    - Refus explicite (profil et tool valides, mais le profil n'a pas ce
      tool) : ``matrix:{profile}:{tool}:not_granted``.
    - Refus fail closed (défaut de sécurité, pas une entrée de matrice) :
      ``fail_closed:profile_missing`` (claim de profil absent),
      ``fail_closed:profile_unknown`` (profil non déclaré dans la matrice),
      ``fail_closed:tool_unknown`` (tool hors du catalogue faisant autorité),
      ``fail_closed:unauthenticated`` (`RULE_UNAUTHENTICATED` — token absent,
      invalide ou expiré, antérieur à toute consultation de la matrice).
    - Projection de catalogue (`list_tools` autorisé) : ``projection:{profile}``
      (`projection_rule`) — distincte de `matrix:{profile}:{tool}`, qui pointe
      un tool précis et non un filtrage du catalogue entier.
    """

    version: int
    profiles: Mapping[str, ProfileEntry]

    def decide(self, profile: str | None, tool: str) -> Decision:
        """Autorise ou refuse un appel. Fail closed en toutes circonstances.

        Un refus ne confirme jamais l'existence d'une ressource non
        autorisée : le code d'erreur est toujours `UNAUTHORIZED_TOOL`, quelle
        que soit la raison exacte (profil absent, profil inconnu, tool hors
        catalogue ou tool non accordé) ; seule `rule` — jamais exposée au
        client — distingue ces cas pour l'audit.
        """
        if profile is None:
            return Denied("UNAUTHORIZED_TOOL", "fail_closed:profile_missing")

        entry = self.profiles.get(profile)
        if entry is None:
            return Denied("UNAUTHORIZED_TOOL", "fail_closed:profile_unknown")

        if tool not in CATALOG_BY_NAME:
            return Denied("UNAUTHORIZED_TOOL", "fail_closed:tool_unknown")

        if tool not in entry.tools:
            return Denied("UNAUTHORIZED_TOOL", f"matrix:{profile}:{tool}:not_granted")

        return Allowed(entry.scope, f"matrix:{profile}:{tool}")

    def tools_for(self, profile: str | None) -> tuple[str, ...]:
        """Projection du catalogue pour ce profil, dans l'ordre du catalogue."""
        if profile is None or profile not in self.profiles:
            return ()
        allowed = self.profiles[profile].tools
        return tuple(name for name in CATALOG_BY_NAME if name in allowed)
