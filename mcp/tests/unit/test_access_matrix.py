import pytest
from app.domain.access_matrix import AccessMatrix, ProfileEntry
from app.domain.catalog import CATALOG
from app.domain.models import Allowed, Denied, Scope

TOUTES_COLLECTIONS = ("datasheet", "manuel", "procedure_sav")
TABLES = ("products", "stock", "orders")
MASQUEES = ("purchase_price", "margin")

TOOLS_PAR_PROFIL = {
    "support": (
        "search_documents",
        "lookup_by_reference",
        "ask_database",
        "get_stock",
        "get_order_status",
    ),
    "sales": (
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
    "dev": (
        "search_documents",
        "get_document_metadata",
        "check_answer_confidence",
        "list_document_types",
        "get_schema_info",
        "get_query_history",
        "run_sql_query",
    ),
}


@pytest.fixture
def matrix() -> AccessMatrix:
    return AccessMatrix(
        version=1,
        profiles={
            "support": ProfileEntry(
                tools=frozenset(TOOLS_PAR_PROFIL["support"]),
                scope=Scope(("procedure_sav", "manuel"), TABLES, MASQUEES),
            ),
            "sales": ProfileEntry(
                tools=frozenset(TOOLS_PAR_PROFIL["sales"]),
                scope=Scope(TOUTES_COLLECTIONS, TABLES, MASQUEES),
            ),
            "dev": ProfileEntry(
                tools=frozenset(TOOLS_PAR_PROFIL["dev"]),
                scope=Scope(TOUTES_COLLECTIONS, TABLES, MASQUEES),
            ),
        },
    )


@pytest.mark.parametrize("profile", ["support", "sales", "dev"])
@pytest.mark.parametrize("descriptor", CATALOG, ids=lambda d: d.name)
def test_grille_complete_profil_par_tool(matrix, profile, descriptor):
    # Act
    decision = matrix.decide(profile, descriptor.name)

    # Assert — les 39 cases de MCP.md §6.4
    if descriptor.name in TOOLS_PAR_PROFIL[profile]:
        assert isinstance(decision, Allowed)
        assert decision.scope == matrix.profiles[profile].scope
    else:
        assert isinstance(decision, Denied)
        assert decision.error_code == "UNAUTHORIZED_TOOL"


def test_les_effectifs_de_catalogue_par_profil(matrix):
    assert len(matrix.tools_for("support")) == 5
    assert len(matrix.tools_for("sales")) == 10
    assert len(matrix.tools_for("dev")) == 7


def test_profil_inconnu_refuse_tout(matrix):
    assert isinstance(matrix.decide("marketing", "get_stock"), Denied)
    assert matrix.tools_for("marketing") == ()


def test_profil_absent_refuse_tout(matrix):
    assert isinstance(matrix.decide(None, "get_stock"), Denied)
    assert matrix.tools_for(None) == ()


def test_tool_hors_catalogue_refuse_meme_si_present_dans_la_matrice():
    # Arrange — une matrice qui accorde un tool inexistant
    matrix = AccessMatrix(
        version=1,
        profiles={
            "support": ProfileEntry(
                tools=frozenset({"drop_everything"}),
                scope=Scope((), (), ()),
            )
        },
    )

    # Act / Assert — le catalogue fait autorité, pas le YAML
    assert isinstance(matrix.decide("support", "drop_everything"), Denied)


# --- Convention de nommage des `rule` (ruling C8) ---
#
# Ces tests verrouillent la convention documentée dans le rapport de tâche 4 :
# la valeur de `rule` doit identifier *pourquoi* une décision a été prise, pas
# recopier le code d'erreur. Un test qui se contenterait de vérifier
# `isinstance(Denied)` ne protégerait pas cette convention — elle est donc
# vérifiée explicitement, valeur par valeur.


def test_rule_autorisee_identifie_le_profil_et_le_tool_accordes(matrix):
    # Act
    decision = matrix.decide("support", "get_stock")

    # Assert — la règle pointe vers l'entrée exacte de la matrice qui autorise
    assert isinstance(decision, Allowed)
    assert decision.rule == "matrix:support:get_stock"


def test_rule_refusee_profil_absent_a_une_rule_fail_closed_dediee(matrix):
    # Act
    decision = matrix.decide(None, "get_stock")

    # Assert
    assert isinstance(decision, Denied)
    assert decision.rule == "fail_closed:profile_missing"


def test_rule_refusee_profil_inconnu_a_une_rule_fail_closed_dediee(matrix):
    # Act
    decision = matrix.decide("marketing", "get_stock")

    # Assert
    assert isinstance(decision, Denied)
    assert decision.rule == "fail_closed:profile_unknown"


def test_rule_refusee_tool_hors_catalogue_a_une_rule_fail_closed_dediee(matrix):
    # Act
    decision = matrix.decide("support", "drop_everything")

    # Assert
    assert isinstance(decision, Denied)
    assert decision.rule == "fail_closed:tool_unknown"


def test_rule_refusee_tool_non_accorde_identifie_profil_et_tool(matrix):
    # Act — tool réel du catalogue, mais hors du périmètre de "support"
    decision = matrix.decide("support", "run_sql_query")

    # Assert
    assert isinstance(decision, Denied)
    assert decision.rule == "matrix:support:run_sql_query:not_granted"
