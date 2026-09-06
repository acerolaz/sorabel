import json

import pytest
from app.domain.errors import (
    BackendUnavailableError,
    InvalidTokenError,
    NotFoundInCorpusError,
    SchemaMismatchError,
    ToolError,
    UnauthenticatedError,
    UnauthorizedCollectionError,
    UnauthorizedTableError,
    UnauthorizedToolError,
)


def test_le_message_d_erreur_est_un_json_au_format_api_contracts():
    # Arrange
    error = UnauthorizedToolError(correlation_id="corr-1")

    # Act
    payload = json.loads(str(error))

    # Assert
    assert payload == {
        "error_code": "UNAUTHORIZED_TOOL",
        "message": "Accès non autorisé pour ce profil",
        "correlation_id": "corr-1",
    }


def test_le_message_ne_nomme_jamais_la_ressource_demandee():
    # Arrange
    error = UnauthorizedToolError(correlation_id="corr-2")

    # Assert — le nom du tool ne doit pas fuiter dans le message rendu au client
    assert "get_customer_order_history" not in str(error)
    assert isinstance(error, ToolError)


def test_la_regle_de_matrice_est_portee_hors_du_json_client():
    # Arrange — la règle de matrice appliquée (ruling C8) doit survivre pour
    # l'audit (tâche 10) sans jamais apparaître dans le corps JSON client.
    error = UnauthorizedToolError(correlation_id="corr-3", matrix_rule="support:get_stock")

    # Act
    payload = json.loads(str(error))

    # Assert
    assert error.matrix_rule == "support:get_stock"
    assert "matrix_rule" not in payload
    assert "support:get_stock" not in str(error)


@pytest.mark.parametrize(
    ("error_class", "expected_code"),
    [
        (UnauthenticatedError, "UNAUTHENTICATED"),
        (UnauthorizedToolError, "UNAUTHORIZED_TOOL"),
        (UnauthorizedCollectionError, "UNAUTHORIZED_COLLECTION"),
        (UnauthorizedTableError, "UNAUTHORIZED_TABLE"),
        (NotFoundInCorpusError, "NOT_FOUND_IN_CORPUS"),
        (SchemaMismatchError, "SCHEMA_MISMATCH"),
        (BackendUnavailableError, "BACKEND_UNAVAILABLE"),
    ],
)
def test_chaque_sous_classe_rend_le_code_d_erreur_attendu(
    error_class: type[ToolError], expected_code: str
) -> None:
    # Arrange
    error = error_class(correlation_id="corr-x")

    # Act
    payload = json.loads(str(error))

    # Assert
    assert payload["error_code"] == expected_code
    assert isinstance(error, ToolError)


def test_invalid_token_error_est_une_exception_distincte_de_tool_error():
    # Assert — InvalidTokenError (ruling C16) n'est pas rendu au client via
    # CallToolResult : il n'hérite donc pas de ToolError et ne porte pas de
    # corps JSON api-contracts.
    assert issubclass(InvalidTokenError, Exception)
    assert not issubclass(InvalidTokenError, ToolError)
