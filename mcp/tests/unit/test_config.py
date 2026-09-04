from pathlib import Path

import pytest
from app.config import Settings, get_settings

_ENV_VARS = (
    "MCP_ENV",
    "MCP_TOKEN_VERIFIER",
    "MCP_JWKS_URL",
    "MCP_JWT_ISSUER",
    "MCP_JWT_AUDIENCE",
    "MCP_DEV_JWT_SECRET",
    "MCP_ACCESS_MATRIX_PATH",
    "MCP_HTTP_TIMEOUT_S",
    "RAG_BACKEND",
    "RAG_BASE_URL",
    "TEXT2SQL_BACKEND",
    "TEXT2SQL_BASE_URL",
    "SQLAPI_BACKEND",
    "SQLAPI_BASE_URL",
)


@pytest.fixture(autouse=True)
def _isole_l_environnement(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empêche un runner CI exportant l'une de ces variables de fausser les
    assertions de valeurs par défaut ci-dessous : seul `_env_file=None` ne
    suffit pas, il coupe le fichier `.env` mais pas l'environnement réel.
    """
    for nom in _ENV_VARS:
        monkeypatch.delenv(nom, raising=False)


def test_les_valeurs_par_defaut_sont_les_plus_fermees() -> None:
    # Arrange — aucun .env chargé, environnement réel neutralisé
    settings = Settings(_env_file=None)

    # Assert — stub partout, jamais un backend réel par défaut
    assert settings.rag_backend == "stub"
    assert settings.text2sql_backend == "stub"
    assert settings.sqlapi_backend == "stub"
    assert settings.mcp_dev_jwt_secret == ""


def test_le_chemin_de_matrice_est_resolu_depuis_la_racine_du_projet(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Arrange — se placer dans un répertoire courant sans rapport avec le
    # projet, pour prouver que la résolution ne dépend pas de `Path.cwd()`.
    monkeypatch.chdir(tmp_path)

    # Act
    settings = Settings(_env_file=None)
    resolu = settings.access_matrix_file()

    # Assert — indépendant du répertoire courant d'exécution
    assert resolu.is_absolute()
    assert resolu.name == "access_matrix.yaml"
    assert not resolu.is_relative_to(tmp_path)


def test_un_chemin_de_matrice_absolu_est_respecte(tmp_path: Path) -> None:
    # Arrange
    cible = tmp_path / "autre.yaml"

    # Act
    settings = Settings(_env_file=None, mcp_access_matrix_path=str(cible))

    # Assert
    assert settings.access_matrix_file() == cible


def test_get_settings_met_en_cache_la_meme_instance() -> None:
    # Act
    premier = get_settings()
    second = get_settings()

    # Assert — pas de reconstruction tant que le cache n'est pas vidé
    assert premier is second


def test_get_settings_reconstruit_apres_cache_clear(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    get_settings.cache_clear()
    monkeypatch.setenv("RAG_BACKEND", "http")

    # Act
    settings = get_settings()

    # Assert — la variable d'environnement surchargée est bien reflétée
    assert settings.rag_backend == "http"

    # Cleanup — ne pas laisser un cache pollué pour les tests suivants
    get_settings.cache_clear()
