"""Verrou d'exhaustivité de la gouvernance (tâche 17).

Sans ce verrou, la structure choisie (catalogue de tools + fonctions
enregistrées + matrice d'accès) ne tient pas : un tool ajouté au catalogue
sans droit déclaré dans la matrice — ou enregistré sans figurer au
catalogue — passerait inaperçu. Ces quatre tests vérifient que les trois
sources (registre SDK, `CATALOG_BY_NAME`, `access_matrix.yaml`) coïncident
exactement, et que la liste des délégations RAG au stub reste explicite.

Un cinquième test y ajoute le seul autre verrou d'exhaustivité de la
gouvernance : le serveur de production n'expose **que** des tools. Il vit ici,
et non dans `tests/unit/test_governance.py`, parce qu'il ne peut garder que ce
sur quoi il porte — et ce qu'il faut garder est `build_server()`, pas une
sous-classe de test.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from app.api.server import build_server
from app.config import get_settings
from app.domain.catalog import CATALOG_BY_NAME
from app.domain.ports import RagPort
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


def test_les_delegations_au_stub_sont_exactement_celles_declarees() -> None:
    """`DELEGATED_TO_STUB` décrit le code, elle ne se contente pas de s'auto-citer.

    L'ensemble observé est **dérivé de l'implémentation** — les méthodes du
    port dont le corps référence `self._stub` — et non recopié littéralement :
    implémenter `search()` contre `rag-hybride` sans retirer `"search"` de la
    constante fait tomber ce test, ce qui est exactement la promesse de la
    spec §9.1 (« une délégation oubliée ne survit pas à l'arrivée de son
    endpoint »).

    Limite assumée, à ne pas confondre avec une garantie : une méthode qui
    appellerait le vrai endpoint tout en gardant `self._stub` en repli resterait
    comptée comme déléguée. La constante reste donc une **déclaration** — ce
    test vérifie qu'elle ne ment pas sur le fait d'atteindre le stub, pas que
    l'endpoint réel n'existe pas.
    """
    # Arrange — les méthodes du port, seules candidates à une délégation
    methodes = {nom for nom in vars(RagPort) if not nom.startswith("_")}

    # Act — `co_names` porte les attributs référencés par le corps compilé
    observees = frozenset(
        nom for nom in methodes if "_stub" in getattr(RagHttpClient, nom).__code__.co_names
    )

    # Assert
    assert RagHttpClient.DELEGATED_TO_STUB == observees
    # …et la dérivation elle-même n'est pas vide de sens : `answer()`, seule
    # méthode réellement câblée sur `rag-hybride`, en est bien absente. Sans
    # cette ligne, une introspection qui rendrait l'ensemble vide des deux
    # côtés passerait pour un succès.
    assert "answer" in methodes - observees


async def test_le_serveur_n_expose_ni_ressource_ni_prompt(environnement: None) -> None:
    """`GovernedFastMCP` ne gouverne ni les ressources ni les prompts.

    La barrière 1 ne surcharge que `list_tools()` et `call_tool()` : une
    ressource ou un prompt enregistré dans `app/api/server.py` serait servi
    sans consultation de la matrice d'accès **et** sans ligne d'audit — un
    chemin de données hors gouvernance (E4, E5). Ce test est le seul rempart
    annoncé contre cette ouverture ; il porte donc sur le serveur réellement
    assemblé par `build_server()`, jamais sur une doublure de test, qu'on
    pourrait laisser vide indéfiniment sans rien garder.
    """
    # Arrange / Act
    serveur = build_server()
    ressources = await serveur.list_resources()
    modeles = await serveur.list_resource_templates()
    prompts = await serveur.list_prompts()

    # Assert
    assert ressources == []
    assert modeles == []
    assert prompts == []
