from pathlib import Path
from types import MappingProxyType

import pytest
from app.domain.models import Allowed
from app.infrastructure.matrix.yaml_loader import InvalidMatrixError, load_access_matrix

MATRICE_REELLE = Path(__file__).resolve().parents[2] / "access_matrix.yaml"

# Table de valeurs attendues, recopiée à la main depuis MCP.md §6.4 — ne doit
# jamais être dérivée du fichier chargé ni d'une constante partagée avec la
# fixture, sinon le test est vrai par construction.
PROFILS_ATTENDUS: dict[str, dict[str, tuple[str, ...]]] = {
    "support": {
        "tools": (
            "search_documents",
            "lookup_by_reference",
            "ask_database",
            "get_stock",
            "get_order_status",
        ),
        "rag_collections": ("procedure_sav", "manuel"),
        "sql_tables": ("products", "stock", "orders"),
        "masked_columns": ("purchase_price", "margin"),
    },
    "sales": {
        "tools": (
            "answer_question",
            "search_documents",
            "lookup_by_reference",
            "get_document_metadata",
            "check_answer_confidence",
            "list_document_types",
            "ask_database",
            "get_stock",
            "get_order_status",
            "get_customer_order_history",
        ),
        "rag_collections": ("datasheet", "manuel", "procedure_sav"),
        "sql_tables": ("products", "stock", "orders"),
        "masked_columns": ("purchase_price", "margin"),
    },
    "dev": {
        "tools": (
            "search_documents",
            "get_document_metadata",
            "check_answer_confidence",
            "list_document_types",
            "get_schema_info",
            "get_query_history",
            "run_sql_query",
        ),
        "rag_collections": ("datasheet", "manuel", "procedure_sav"),
        "sql_tables": ("products", "stock", "orders"),
        "masked_columns": ("purchase_price", "margin"),
    },
}


def test_charge_la_matrice_reelle_du_depot() -> None:
    # Act
    matrix = load_access_matrix(MATRICE_REELLE)

    # Assert — les effectifs de MCP.md §6.4
    assert matrix.version == 1
    assert len(matrix.tools_for("support")) == 5
    assert len(matrix.tools_for("sales")) == 10
    assert len(matrix.tools_for("dev")) == 7


def test_le_perimetre_du_profil_support_est_restreint_a_deux_collections() -> None:
    # Act
    decision = load_access_matrix(MATRICE_REELLE).decide("support", "search_documents")

    # Assert
    assert isinstance(decision, Allowed)
    assert decision.scope.rag_collections == ("procedure_sav", "manuel")
    assert decision.scope.masked_columns == ("purchase_price", "margin")


def test_un_fichier_malforme_echoue_au_chargement(tmp_path: Path) -> None:
    # Arrange — `tools` doit être une liste, pas une chaîne
    fichier = tmp_path / "matrice.yaml"
    fichier.write_text("version: 1\nprofiles:\n  support:\n    tools: get_stock\n", "utf-8")

    # Act / Assert — jamais de matrice vide silencieuse
    with pytest.raises(InvalidMatrixError):
        load_access_matrix(fichier)


def test_un_fichier_absent_echoue_au_chargement(tmp_path: Path) -> None:
    with pytest.raises(InvalidMatrixError):
        load_access_matrix(tmp_path / "inexistant.yaml")


@pytest.mark.parametrize("profil", ["support", "sales", "dev"])
def test_la_matrice_reelle_correspond_exactement_a_la_spec_section_6(profil: str) -> None:
    """Verrou de non-régression sur MCP.md §6.4 : chaque profil, ses tools et
    son périmètre, comparés à une table écrite en dur ici — indépendante du
    fichier chargé et de toute constante partagée avec la fixture des tests
    unitaires de `decide`."""
    # Arrange
    matrix = load_access_matrix(MATRICE_REELLE)
    attendu = PROFILS_ATTENDUS[profil]

    # Act
    tools = matrix.tools_for(profil)
    decision = matrix.decide(profil, tools[0])

    # Assert — tools accordés (l'ordre suit le catalogue, on compare en set)
    assert set(tools) == set(attendu["tools"])
    assert len(tools) == len(attendu["tools"])

    # Assert — périmètre de données du profil
    assert isinstance(decision, Allowed)
    assert decision.scope.rag_collections == attendu["rag_collections"]
    assert decision.scope.sql_tables == attendu["sql_tables"]
    assert decision.scope.masked_columns == attendu["masked_columns"]


def test_la_map_de_profils_chargee_est_immuable() -> None:
    """AccessMatrix est frozen, mais `profiles` reste un Mapping : sans
    MappingProxyType, le dict sous-jacent resterait mutable par l'appelant."""
    # Arrange
    matrix = load_access_matrix(MATRICE_REELLE)

    # Assert — vrai type immuable, pas seulement l'interface Mapping
    assert isinstance(matrix.profiles, MappingProxyType)

    # Act / Assert — toute tentative de mutation lève
    with pytest.raises(TypeError):
        matrix.profiles["support"] = matrix.profiles["dev"]  # type: ignore[index]
