import json

from app.domain.errors import ToolError, UnauthorizedToolError


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
