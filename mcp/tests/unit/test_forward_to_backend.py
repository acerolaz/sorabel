"""Barrière 2 : le périmètre transmis au backend vient de la matrice, jamais de
l'appelant (spec §4.2, §6, §7).

`resolve_collections`/`resolve_tables` sont pures : elles reçoivent le `Scope`
en paramètre et ne lisent aucun contexte global (pont `api/` fait en tâche 13).
"""

import pytest
from app.application.use_cases.forward_to_backend import (
    resolve_collections,
    resolve_tables,
)
from app.domain.errors import UnauthorizedCollectionError, UnauthorizedTableError
from app.domain.models import Scope

PERIMETRE = Scope(("procedure_sav", "manuel"), ("products", "stock"), ("margin",))


def test_sans_demande_le_perimetre_du_profil_s_applique() -> None:
    # Arrange / Act — aucune demande explicite (None) : cas nominal.
    resultat = resolve_collections(None, PERIMETRE, "corr")

    # Assert — le périmètre complet de la matrice s'applique, pas un tuple vide.
    assert resultat == ("procedure_sav", "manuel")


def test_une_demande_incluse_dans_le_perimetre_le_restreint() -> None:
    # Arrange / Act
    resultat = resolve_collections(["manuel"], PERIMETRE, "corr")

    # Assert — une demande légitime, strict sous-ensemble, est honorée.
    assert resultat == ("manuel",)


def test_une_demande_hors_perimetre_est_refusee() -> None:
    # Act / Assert
    with pytest.raises(UnauthorizedCollectionError):
        resolve_collections(["datasheet"], PERIMETRE, "corr")


def test_une_demande_ne_peut_pas_elargir_par_melange() -> None:
    # Arrange — une collection autorisée mêlée à une interdite reste un refus :
    # si l'implémentation renvoyait l'intersection au lieu de lever, ce test
    # échouerait (il prouve qu'on ne "sauve" pas la partie autorisée).
    with pytest.raises(UnauthorizedCollectionError):
        resolve_collections(["manuel", "datasheet"], PERIMETRE, "corr")


def test_les_tables_suivent_la_meme_regle() -> None:
    # Assert — restriction légitime honorée.
    assert resolve_tables(["stock"], PERIMETRE, "corr") == ("stock",)
    # Assert — hors périmètre refusé.
    with pytest.raises(UnauthorizedTableError):
        resolve_tables(["orders"], PERIMETRE, "corr")


def test_une_demande_vide_explicite_ne_rend_rien_a_la_difference_de_none() -> None:
    """`()`/`[]` est une demande explicite de zéro collection — un sous-ensemble
    valide (l'ensemble vide est inclus dans tout périmètre), distinct de `None`
    qui signifie « pas de demande, tout le périmètre s'applique »."""
    # Act / Assert
    assert resolve_collections([], PERIMETRE, "corr") == ()
    assert resolve_collections((), PERIMETRE, "corr") == ()


def test_les_doublons_de_la_demande_sont_dedupliques() -> None:
    # Act
    resultat = resolve_collections(["manuel", "manuel"], PERIMETRE, "corr")

    # Assert — pas de doublon dans le résultat.
    assert resultat == ("manuel",)


def test_l_ordre_du_resultat_suit_l_ordre_de_la_matrice_pas_celui_de_la_demande() -> None:
    """Le résultat est déterministe : il suit l'ordre canonique de la matrice,
    jamais l'ordre (arbitraire, potentiellement dupliqué) fourni par l'appelant
    — sans quoi les tests d'audit en aval devraient composer avec un ordre
    non déterministe."""
    # Act — la demande inverse l'ordre du périmètre.
    resultat = resolve_collections(["manuel", "procedure_sav"], PERIMETRE, "corr")

    # Assert — l'ordre rendu est celui de la matrice (procedure_sav, manuel).
    assert resultat == ("procedure_sav", "manuel")


def test_la_casse_n_est_jamais_normalisee() -> None:
    """Une demande mal cassée n'est pas assouplie en une correspondance
    insensible à la casse : elle est traitée comme une valeur inconnue du
    périmètre, donc refusée — jamais un défaut permissif."""
    # Act / Assert
    with pytest.raises(UnauthorizedCollectionError):
        resolve_collections(["Manuel"], PERIMETRE, "corr")


def test_le_refus_porte_une_regle_d_audit_sans_fuite_vers_le_client() -> None:
    # Act
    with pytest.raises(UnauthorizedCollectionError) as exc_info:
        resolve_collections(["datasheet"], PERIMETRE, "corr")

    # Assert — la règle est renseignée pour l'audit...
    assert exc_info.value.matrix_rule is not None
    # ...mais n'apparaît jamais dans le corps JSON rendu au client.
    assert "datasheet" not in str(exc_info.value)
    assert exc_info.value.matrix_rule not in str(exc_info.value)
