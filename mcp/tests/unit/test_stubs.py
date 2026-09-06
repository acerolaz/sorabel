"""Adapters stub des trois backends (rag-hybride, text2sql-ai, sorabelsql-api) :
le lot doit être démontrable de bout en bout sans une ligne de code réelle
derrière `mcp` (spec §9, §9.2).
"""

from typing import Any

import pytest
from app.domain.errors import NotFoundInCorpusError, SchemaMismatchError
from app.infrastructure.stub.rag_stub import RagStub
from app.infrastructure.stub.sqlapi_stub import SqlApiStub
from app.infrastructure.stub.text2sql_stub import Text2SqlStub

# --- Provenance (spec §9.2) ---------------------------------------------


async def test_chaque_reponse_stub_annonce_sa_provenance() -> None:
    # Act
    resultats: list[dict[str, Any]] = [
        await RagStub().search("tension", 5, ("manuel",), "corr"),
        await Text2SqlStub().generate_sql("stock ?", "sales", ("stock",), "corr"),
        await SqlApiStub().stock("REF-8842", "sales", (), "corr"),
    ]

    # Assert — une donnée fictive ne peut pas passer pour une donnée réelle
    assert all(resultat["source"] == "stub" for resultat in resultats)


@pytest.mark.parametrize(
    "coroutine",
    [
        RagStub().answer("tension nominale", ("manuel",), "corr"),
        RagStub().search("tension", 5, ("manuel",), "corr"),
        RagStub().lookup("REF-8842", ("manuel",), "corr"),
        RagStub().document_metadata("doc-1", ("manuel",), "corr"),
        RagStub().confidence("tension", ("manuel",), "corr"),
        RagStub().document_types(("manuel", "datasheet"), "corr"),
        Text2SqlStub().generate_sql("stock de REF-8842 ?", "sales", ("stock",), "corr"),
        SqlApiStub().run_sql("SELECT 1", "sales", ("stock",), (), "corr"),
        SqlApiStub().stock("REF-8842", "sales", (), "corr"),
        SqlApiStub().order_status("ORD-1", "sales", (), "corr"),
        SqlApiStub().customer_orders("CUST-1", 10, "sales", (), "corr"),
        SqlApiStub().schema_info("sales", None, ("stock",), "corr"),
        SqlApiStub().query_history("sales", 10, "corr"),
    ],
)
async def test_les_13_methodes_des_trois_ports_annoncent_source_stub(
    coroutine: Any,
) -> None:
    # Act
    resultat = await coroutine

    # Assert — exhaustivité : aucune des 13 méthodes n'échappe à la convention
    assert resultat["source"] == "stub"


# --- E1 : refus explicite hors corpus ------------------------------------


async def test_le_stub_rag_refuse_explicitement_une_question_hors_corpus() -> None:
    # Act / Assert — E1 reste exerçable sans backend réel
    with pytest.raises(NotFoundInCorpusError):
        await RagStub().answer("question absente du corpus", ("manuel",), "corr")


# --- Séparation génération / exécution SQL --------------------------------


async def test_le_stub_text2sql_ne_retourne_que_du_sql_jamais_un_resultat() -> None:
    # Act
    resultat = await Text2SqlStub().generate_sql("stock de REF-8842 ?", "sales", ("stock",), "c")

    # Assert — clés exhaustives : la génération ne rend ni ligne ni statut
    # d'exécution, seulement le SQL et son contexte de génération. Une clé en
    # trop ou en moins ferait échouer ce test (contrairement à un simple
    # `"rows" not in resultat`, vrai par construction sur un stub qui ne
    # produit jamais cette clé).
    assert set(resultat.keys()) == {"source", "sql", "tables", "question"}
    assert resultat["sql"].lower().startswith("select")


# --- Forme exacte des retours (clés exhaustives, tâches 13/16/17) ---------


async def test_rag_answer_rend_les_cles_attendues() -> None:
    # Act
    resultat = await RagStub().answer("tension nominale ?", ("manuel",), "corr")

    # Assert
    assert set(resultat.keys()) == {"source", "citations", "confidence", "collections"}
    assert resultat["citations"]
    assert resultat["collections"] == ["manuel"]


async def test_rag_search_rend_les_cles_attendues_et_respecte_top_k() -> None:
    # Act
    resultat = await RagStub().search("tension", 1, ("manuel",), "corr")

    # Assert
    assert set(resultat.keys()) == {"source", "passages", "collections"}
    assert len(resultat["passages"]) == 1


async def test_rag_lookup_rend_les_cles_attendues_et_echo_la_reference() -> None:
    # Act
    resultat = await RagStub().lookup("REF-8842", ("manuel",), "corr")

    # Assert
    assert set(resultat.keys()) == {"source", "product_ref", "citation"}
    assert resultat["product_ref"] == "REF-8842"


async def test_rag_document_metadata_rend_les_cles_attendues_et_echo_le_doc_id() -> None:
    # Act
    resultat = await RagStub().document_metadata("REF-8842:datasheet:1", ("manuel",), "corr")

    # Assert
    assert set(resultat.keys()) == {
        "source",
        "doc_id",
        "title",
        "version",
        "published_date",
        "status",
    }
    assert resultat["doc_id"] == "REF-8842:datasheet:1"


async def test_rag_confidence_rend_les_cles_attendues() -> None:
    # Act
    resultat = await RagStub().confidence("tension nominale", ("manuel",), "corr")

    # Assert
    assert set(resultat.keys()) == {"source", "score"}
    assert resultat["score"] > 0


async def test_rag_document_types_rend_les_cles_attendues() -> None:
    # Act
    resultat = await RagStub().document_types(("manuel", "datasheet"), "corr")

    # Assert
    assert set(resultat.keys()) == {"source", "document_types"}


async def test_sqlapi_run_sql_rend_les_cles_attendues() -> None:
    # Act
    resultat = await SqlApiStub().run_sql("SELECT 1", "sales", ("stock",), ("margin",), "corr")

    # Assert
    assert set(resultat.keys()) == {"source", "sql", "rows", "row_count", "masked_columns"}


async def test_sqlapi_stock_rend_les_cles_attendues() -> None:
    # Act
    resultat = await SqlApiStub().stock("REF-8842", "sales", ("margin",), "corr")

    # Assert
    assert set(resultat.keys()) == {
        "source",
        "product_ref",
        "quantity",
        "row_count",
        "masked_columns",
    }
    assert resultat["product_ref"] == "REF-8842"


async def test_sqlapi_order_status_rend_les_cles_attendues() -> None:
    # Act
    resultat = await SqlApiStub().order_status("ORD-1", "sales", ("margin",), "corr")

    # Assert
    assert set(resultat.keys()) == {"source", "order_id", "status", "row_count", "masked_columns"}
    assert resultat["order_id"] == "ORD-1"


async def test_sqlapi_customer_orders_rend_les_cles_attendues() -> None:
    # Act
    resultat = await SqlApiStub().customer_orders("CUST-1", 10, "sales", ("margin",), "corr")

    # Assert
    assert set(resultat.keys()) == {
        "source",
        "customer_id",
        "orders",
        "row_count",
        "masked_columns",
    }
    assert resultat["customer_id"] == "CUST-1"


async def test_sqlapi_schema_info_rend_les_cles_attendues_sans_masked_columns() -> None:
    # Act
    resultat = await SqlApiStub().schema_info("sales", "stock", ("stock", "orders"), "corr")

    # Assert — schema_info ne porte jamais masked_columns (contrat ports.py)
    assert set(resultat.keys()) == {"source", "tables", "keyword"}


async def test_sqlapi_query_history_rend_les_cles_attendues_sans_masked_columns() -> None:
    # Act
    resultat = await SqlApiStub().query_history("sales", 10, "corr")

    # Assert — query_history ne porte jamais masked_columns (contrat ports.py)
    assert set(resultat.keys()) == {"source", "items", "row_count"}


# --- masked_columns transmis tel quel (spec §4.2) -------------------------


async def test_run_sql_transmet_les_masked_columns_recus_sans_les_alterer() -> None:
    # Arrange
    colonnes = ("margin", "cost_price")

    # Act
    resultat = await SqlApiStub().run_sql("SELECT 1", "sales", ("stock",), colonnes, "corr")

    # Assert — falsifiable : un stub qui ignorerait l'argument (ex: liste
    # vide en dur) ferait échouer cette assertion.
    assert resultat["masked_columns"] == ["margin", "cost_price"]


async def test_customer_orders_transmet_les_masked_columns_recus() -> None:
    # Act
    resultat = await SqlApiStub().customer_orders("CUST-1", 10, "sales", ("email",), "corr")

    # Assert
    assert resultat["masked_columns"] == ["email"]


# --- Séquence vide = zéro résultat, jamais l'absence de filtre -----------


async def test_rag_answer_avec_perimetre_vide_refuse_au_lieu_de_tout_rendre() -> None:
    # Act / Assert — si le stub interprétait () comme "pas de filtre", cette
    # question (qui ne contient pas "absente") passerait sans lever.
    with pytest.raises(NotFoundInCorpusError):
        await RagStub().answer("tension nominale ?", (), "corr")


async def test_rag_search_avec_perimetre_vide_ne_rend_aucun_passage() -> None:
    # Act
    resultat = await RagStub().search("tension nominale", 5, (), "corr")

    # Assert — pas la liste complète des passages, une liste vide
    assert resultat["passages"] == []


async def test_rag_lookup_avec_perimetre_vide_refuse() -> None:
    # Act / Assert
    with pytest.raises(NotFoundInCorpusError):
        await RagStub().lookup("REF-8842", (), "corr")


async def test_rag_document_metadata_avec_perimetre_vide_refuse() -> None:
    # Act / Assert
    with pytest.raises(NotFoundInCorpusError):
        await RagStub().document_metadata("REF-8842:datasheet:1", (), "corr")


async def test_rag_confidence_avec_perimetre_vide_rend_un_score_nul() -> None:
    # Act
    resultat = await RagStub().confidence("tension nominale", (), "corr")

    # Assert — pas le score habituel (0.82 dans ce stub), un score nul
    assert resultat["score"] == 0.0


async def test_rag_document_types_avec_perimetre_vide_ne_rend_aucun_type() -> None:
    # Act
    resultat = await RagStub().document_types((), "corr")

    # Assert
    assert resultat["document_types"] == []


async def test_text2sql_avec_perimetre_de_tables_vide_refuse_au_lieu_de_deviner() -> None:
    # Act / Assert — si le stub se rabattait sur une table par défaut
    # ("products"), cette levée n'aurait jamais lieu : c'est le
    # comportement que ce test vise à interdire.
    with pytest.raises(SchemaMismatchError):
        await Text2SqlStub().generate_sql("stock de REF-8842 ?", "sales", (), "corr")


async def test_sqlapi_run_sql_avec_perimetre_de_tables_vide_refuse() -> None:
    # Act / Assert
    with pytest.raises(SchemaMismatchError):
        await SqlApiStub().run_sql("SELECT 1", "sales", (), (), "corr")


async def test_sqlapi_schema_info_avec_perimetre_de_tables_vide_ne_rend_aucune_table() -> None:
    # Act
    resultat = await SqlApiStub().schema_info("sales", None, (), "corr")

    # Assert — pas le schéma complet, un schéma vide
    assert resultat["tables"] == []
