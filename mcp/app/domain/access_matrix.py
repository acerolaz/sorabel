from collections.abc import Mapping
from dataclasses import dataclass

from app.domain.catalog import CATALOG_BY_NAME
from app.domain.models import Allowed, Decision, Denied, Scope


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
      ``fail_closed:tool_unknown`` (tool hors du catalogue faisant autorité).
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
