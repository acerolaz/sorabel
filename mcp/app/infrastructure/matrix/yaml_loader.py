from pathlib import Path
from types import MappingProxyType
from typing import Any

import yaml  # type: ignore[import-untyped]

from app.domain.access_matrix import AccessMatrix, ProfileEntry
from app.domain.models import Scope


class InvalidMatrixError(Exception):
    """La matrice est absente, illisible ou mal formée.

    Levée au démarrage : mieux vaut ne pas démarrer qu'exposer une matrice
    partiellement chargée, qui accorderait ou refuserait au hasard.
    """


def _liste_de_chaines(valeur: Any, chemin: str) -> tuple[str, ...]:
    if not isinstance(valeur, list) or not all(isinstance(item, str) for item in valeur):
        raise InvalidMatrixError(f"{chemin} doit être une liste de chaînes")
    return tuple(valeur)


def load_access_matrix(path: Path) -> AccessMatrix:
    """Charge et valide la matrice versionnée depuis le disque.

    Fail closed : toute anomalie (fichier absent, YAML illisible, structure
    inattendue, clé manquante) lève `InvalidMatrixError` — jamais de matrice
    vide ou partielle renvoyée silencieusement.
    """
    try:
        brut = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise InvalidMatrixError(f"matrice illisible: {path}") from exc

    if not isinstance(brut, dict):
        raise InvalidMatrixError("la matrice doit être un mapping YAML")
    version = brut.get("version")
    if not isinstance(version, int):
        raise InvalidMatrixError("`version` manquante ou non entière")
    profils_bruts = brut.get("profiles")
    if not isinstance(profils_bruts, dict):
        raise InvalidMatrixError("`profiles` manquante ou non mapping")

    profils: dict[str, ProfileEntry] = {}
    for nom, entree in profils_bruts.items():
        if not isinstance(entree, dict):
            raise InvalidMatrixError(f"profiles.{nom} doit être un mapping")
        profils[nom] = ProfileEntry(
            tools=frozenset(_liste_de_chaines(entree.get("tools"), f"profiles.{nom}.tools")),
            scope=Scope(
                rag_collections=_liste_de_chaines(
                    entree.get("rag_collections"), f"profiles.{nom}.rag_collections"
                ),
                sql_tables=_liste_de_chaines(
                    entree.get("sql_tables"), f"profiles.{nom}.sql_tables"
                ),
                masked_columns=_liste_de_chaines(
                    entree.get("masked_columns"), f"profiles.{nom}.masked_columns"
                ),
            ),
        )
    # MappingProxyType : `AccessMatrix` est frozen mais `profiles` est un
    # Mapping — sans cette enveloppe, le dict sous-jacent resterait mutable
    # par l'appelant et l'immuabilité ne serait que déclarative.
    return AccessMatrix(version=version, profiles=MappingProxyType(profils))
