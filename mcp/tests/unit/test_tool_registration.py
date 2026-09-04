"""Assemblage du serveur : les 13 tools du catalogue, leurs docstrings, la config.

`build_server()` est appelé avec un environnement entièrement posé par le test —
jamais avec le `.env` de la machine, qui n'est pas versionné : la suite doit
passer sur un poste vierge comme en CI.
"""

from collections.abc import Iterator

import app.api.server as module_serveur
import pytest
from app.api.server import build_app, build_server
from app.config import get_settings
from app.domain.catalog import CATALOG_BY_NAME
from app.infrastructure.keycloak.local_key_verifier import UnsafeVerifierConfiguration

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


async def test_les_treize_tools_du_catalogue_sont_enregistres(environnement: None) -> None:
    # Arrange
    server = build_server()

    # Act — sans identité, la barrière 1 filtre : on interroge le registre brut
    noms = {tool.name for tool in await server.list_all_tools()}

    # Assert
    assert noms == set(CATALOG_BY_NAME)


async def test_chaque_tool_expose_une_docstring_non_vide(environnement: None) -> None:
    # Arrange
    server = build_server()

    # Act
    tools = await server.list_all_tools()

    # Assert — la description est ce que lit le LLM client
    assert all(tool.description and tool.description.strip() for tool in tools)


def test_le_serveur_refuse_de_demarrer_sans_issuer(
    environnement: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — `build_token_verifier` est la seule porte d'entrée : elle refuse
    # un `iss` vide, garde-fou qu'un appel direct à `build_local_verifier`
    # court-circuiterait.
    monkeypatch.setenv("MCP_JWT_ISSUER", "")
    get_settings.cache_clear()

    # Act / Assert
    with pytest.raises(UnsafeVerifierConfiguration):
        build_server()


def test_le_serveur_refuse_de_demarrer_sans_secret_de_signature(
    environnement: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — un secret vide signerait avec une clé triviale
    monkeypatch.setenv("MCP_DEV_JWT_SECRET", "")
    get_settings.cache_clear()

    # Act / Assert
    with pytest.raises(UnsafeVerifierConfiguration):
        build_server()


def test_le_module_n_instancie_aucune_application_a_l_import() -> None:
    # Arrange / Act — l'app est une fabrique, pas un effet de bord d'import :
    # sinon un `.env` incomplet ferait échouer la simple collecte des tests.
    # Assert
    assert callable(build_app)
    assert not hasattr(module_serveur, "app")


def test_la_fabrique_rend_une_application_asgi_montant_la_route_mcp(
    environnement: None,
) -> None:
    # Arrange / Act — la fabrique est réellement appelée : c'est ce que fera
    # `uvicorn app.api.server:build_app --factory`.
    application = build_app()

    # Assert — transport HTTP streamable monté (spec D2)
    assert "/mcp" in {route.path for route in application.routes}
    assert application.router.lifespan_context is not None
