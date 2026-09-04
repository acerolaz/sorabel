from pathlib import Path

from app.config import Settings


def test_les_valeurs_par_defaut_sont_les_plus_fermees() -> None:
    # Arrange — aucun .env chargé
    settings = Settings(_env_file=None)

    # Assert — stub partout, jamais un backend réel par défaut
    assert settings.rag_backend == "stub"
    assert settings.text2sql_backend == "stub"
    assert settings.sqlapi_backend == "stub"
    assert settings.mcp_dev_jwt_secret == ""


def test_le_chemin_de_matrice_est_resolu_depuis_la_racine_du_projet() -> None:
    # Act
    settings = Settings(_env_file=None)

    # Assert — indépendant du répertoire courant d'exécution
    assert settings.access_matrix_file().is_absolute()
    assert settings.access_matrix_file().name == "access_matrix.yaml"


def test_un_chemin_de_matrice_absolu_est_respecte(tmp_path: Path) -> None:
    # Arrange
    cible = tmp_path / "autre.yaml"

    # Act
    settings = Settings(_env_file=None, mcp_access_matrix_path=str(cible))

    # Assert
    assert settings.access_matrix_file() == cible
