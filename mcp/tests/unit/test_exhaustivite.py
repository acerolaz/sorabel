"""Verrou d'exhaustivité de la gouvernance (tâche 17).

Sans ce verrou, la structure choisie (catalogue de tools + fonctions
enregistrées + matrice d'accès) ne tient pas : un tool ajouté au catalogue
sans droit déclaré dans la matrice — ou enregistré sans figurer au
catalogue — passerait inaperçu. Ces quatre tests vérifient que les trois
sources (registre SDK, `CATALOG_BY_NAME`, `access_matrix.yaml`) coïncident
exactement, et que la liste des délégations RAG au stub reste explicite.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from app.api.server import build_server
from app.config import get_settings
from app.domain.catalog import CATALOG_BY_NAME
from app.infrastructure.http.rag_client import RagHttpClient
from app.infrastructure.matrix.yaml_loader import load_access_matrix

MATRICE = Path(__file__).resolve().parents[2] / "access_matrix.yaml"

# `build_server()` est appelé avec un environnement entièrement posé par le
# test — jamais avec le `.env` de la machine, qui n'est pas versionné : la
# suite doit passer sur un poste vierge comme en CI (même convention que
# `tests/unit/test_tool_registration.py`).
_ENVIRONNEMENT = {
    "MCP_ENV": "dev",
    "MCP_TOKEN_VERIFIER": "local",
    "MCP_JWT_ISSUER": "https://idp.test/realms/sorabel",
    "MCP_JWT_AUDIENCE": "sorabel-mcp",
    "MCP_DEV_JWT_SECRET": "secret-de-test",
    "MCP_ACCESS_MATRIX_PATH": "access_matrix.yaml",
    "RAG_BACKEND": "stub",
    "TEXT2SQL_BACKEND": "stub",
    "SQLAPI_BACKEND": "stub",
}


@pytest.fixture
def environnement(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    # Arrange — configuration complète et valide, indépendante du poste
    for clef, valeur in _ENVIRONNEMENT.items():
        monkeypatch.setenv(clef, valeur)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def test_tools_enregistres_et_catalogue_coincident(environnement: None) -> None:
    # Act — `list_all_tools()` rend le registre SDK brut, sans projection par
    # profil : c'est le catalogue complet qui doit être comparé ici.
    enregistres = {tool.name for tool in await build_server().list_all_tools()}

    # Assert
    assert enregistres == set(CATALOG_BY_NAME)


def test_tout_tool_de_la_matrice_existe_au_catalogue() -> None:
    # Arrange
    matrix = load_access_matrix(MATRICE)

    # Act
    cites = {tool for entree in matrix.profiles.values() for tool in entree.tools}

    # Assert — un droit accordé à un tool inexistant est une erreur de matrice
    assert cites <= set(CATALOG_BY_NAME)


def test_tout_tool_du_catalogue_est_arbitre_par_au_moins_un_profil() -> None:
    # Arrange
    matrix = load_access_matrix(MATRICE)
    cites = {tool for entree in matrix.profiles.values() for tool in entree.tools}

    # Assert — un tool que personne ne peut appeler est un oubli de matrice
    assert set(CATALOG_BY_NAME) - cites == set()


def test_les_delegations_au_stub_sont_exactement_celles_attendues() -> None:
    # Assert — une délégation oubliée après l'arrivée d'un endpoint casse ici
    assert RagHttpClient.DELEGATED_TO_STUB == frozenset(
        {"search", "lookup", "document_metadata", "confidence", "document_types"}
    )
