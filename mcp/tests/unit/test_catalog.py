from app.domain.catalog import CATALOG, CATALOG_BY_NAME

TOOLS_ATTENDUS = {
    "answer_question",
    "search_documents",
    "lookup_by_reference",
    "get_document_metadata",
    "check_answer_confidence",
    "list_document_types",
    "ask_database",
    "run_sql_query",
    "get_stock",
    "get_order_status",
    "get_customer_order_history",
    "get_schema_info",
    "get_query_history",
}


def test_le_catalogue_contient_exactement_les_treize_tools_du_cadrage() -> None:
    # Assert
    assert {descriptor.name for descriptor in CATALOG} == TOOLS_ATTENDUS
    assert len(CATALOG) == 13


def test_chaque_tool_declare_un_backend_connu() -> None:
    # Assert
    assert {d.backend for d in CATALOG} == {"rag", "text2sql", "sqlapi"}


def test_l_index_par_nom_couvre_tout_le_catalogue() -> None:
    # Assert
    assert set(CATALOG_BY_NAME) == TOOLS_ATTENDUS


def test_le_catalogue_est_un_tuple_immuable() -> None:
    # Assert
    assert isinstance(CATALOG, tuple)


def test_chaque_backend_est_correctement_assigne_par_tool() -> None:
    # Arrange : mapping attendu tool -> backend, saisi en dur (§9 de la spec),
    # pas dérivé de CATALOG lui-même.
    backend_attendu = {
        "answer_question": "rag",
        "search_documents": "rag",
        "lookup_by_reference": "rag",
        "get_document_metadata": "rag",
        "check_answer_confidence": "rag",
        "list_document_types": "rag",
        "ask_database": "text2sql",
        "run_sql_query": "sqlapi",
        "get_stock": "sqlapi",
        "get_order_status": "sqlapi",
        "get_customer_order_history": "sqlapi",
        "get_schema_info": "sqlapi",
        "get_query_history": "sqlapi",
    }

    # Act
    backend_obtenu = {name: descriptor.backend for name, descriptor in CATALOG_BY_NAME.items()}

    # Assert
    assert backend_obtenu == backend_attendu


def test_chaque_tool_declare_une_famille_connue() -> None:
    # Arrange : mapping attendu tool -> family, saisi en dur (§9 de la spec).
    famille_attendue = {
        "answer_question": "rag",
        "search_documents": "rag",
        "lookup_by_reference": "rag",
        "get_document_metadata": "rag",
        "check_answer_confidence": "rag",
        "list_document_types": "rag",
        "ask_database": "sql",
        "run_sql_query": "sql",
        "get_stock": "sql",
        "get_order_status": "sql",
        "get_customer_order_history": "sql",
        "get_schema_info": "sql",
        "get_query_history": "sql",
    }

    # Act
    famille_obtenue = {name: descriptor.family for name, descriptor in CATALOG_BY_NAME.items()}

    # Assert
    assert famille_obtenue == famille_attendue
