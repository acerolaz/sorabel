"""Barrière 2 branchée pour de vrai : le périmètre vient de la matrice (spec §4.2, §11.1).

Deux preuves complémentaires :

- un faux port **espion** montre que ce que reçoit le backend est le périmètre
  du profil, pas ce qu'a demandé (ou omis) l'appelant ;
- une demande qui déborde ce périmètre est refusée en `UNAUTHORIZED_COLLECTION`
  et n'atteint jamais le port.
"""

import io
import json
from collections.abc import Sequence
from typing import Any

import pytest
from app.api.governance import GovernedFastMCP
from app.api.tools._context import call_context
from app.api.tools.rag import register_rag_tools
from app.domain.access_matrix import AccessMatrix, ProfileEntry
from app.domain.errors import ToolError, UnauthenticatedError
from app.domain.models import AuditEntry, Scope
from app.infrastructure.audit.stdout_audit_log import StdoutAuditLog
from mcp.server.fastmcp.exceptions import ToolError as SdkToolError

from tests.unit.harness import FakeAuditLog, FakeTokenVerifier, appel_http

#: Périmètre accordé au profil par la matrice — jamais négociable par l'appelant.
PORTEE_VENTE = Scope(("datasheet", "manuel"), (), ())


class RagEspion:
    """Faux port qui retient le périmètre reçu à chaque appel."""

    def __init__(self) -> None:
        self.perimetres: list[tuple[str, ...]] = []

    async def search(
        self, query: str, top_k: int, collections: Sequence[str], correlation_id: str
    ) -> dict[str, Any]:
        self.perimetres.append(tuple(collections))
        return {"source": "espion", "passages": []}

    async def answer(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError("non sollicité par ces tests")

    async def lookup(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError("non sollicité par ces tests")

    async def document_metadata(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError("non sollicité par ces tests")

    async def confidence(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError("non sollicité par ces tests")

    async def document_types(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError("non sollicité par ces tests")


def _serveur(espion: RagEspion, audit: Any) -> GovernedFastMCP:
    server = GovernedFastMCP(
        matrix=AccessMatrix(
            version=1,
            profiles={
                "sales": ProfileEntry(tools=frozenset({"search_documents"}), scope=PORTEE_VENTE)
            },
        ),
        audit=audit,
        verifier=FakeTokenVerifier({"jeton-de-test": "sales"}),
        name="test",
    )
    register_rag_tools(server, espion)
    return server


@pytest.fixture
def espion() -> RagEspion:
    return RagEspion()


@pytest.fixture
def serveur(espion: RagEspion) -> GovernedFastMCP:
    return _serveur(espion, StdoutAuditLog(stream=io.StringIO()))


async def test_sans_demande_explicite_le_port_recoit_le_perimetre_du_profil(
    espion: RagEspion, serveur: GovernedFastMCP
) -> None:
    # Arrange / Act — l'appelant ne demande aucune collection
    with appel_http():
        await serveur.call_tool("search_documents", {"query": "tension ?"})

    # Assert — le port reçoit le périmètre de la matrice, jamais « pas de filtre »
    assert espion.perimetres == [PORTEE_VENTE.rag_collections]


async def test_une_demande_peut_affiner_le_perimetre_mais_pas_l_elargir(
    espion: RagEspion, serveur: GovernedFastMCP
) -> None:
    # Arrange / Act — sous-ensemble strict du périmètre accordé
    with appel_http():
        await serveur.call_tool(
            "search_documents", {"query": "tension ?", "collections": ["manuel"]}
        )

    # Assert
    assert espion.perimetres == [("manuel",)]


async def test_une_demande_hors_perimetre_est_refusee_sans_atteindre_le_port(
    espion: RagEspion,
) -> None:
    # Arrange
    audit = FakeAuditLog()
    serveur = _serveur(espion, audit)

    # Act
    with appel_http():
        with pytest.raises(SdkToolError) as capture:
            await serveur.call_tool(
                "search_documents", {"query": "marges ?", "collections": ["finance"]}
            )

    # Assert — refus typé, port jamais atteint, refus journalisé (E5)
    cause = capture.value.__cause__
    assert isinstance(cause, ToolError)
    corps = json.loads(str(cause))
    assert corps["error_code"] == "UNAUTHORIZED_COLLECTION"
    assert set(corps) == {"error_code", "message", "correlation_id"}
    assert espion.perimetres == []
    entrees: list[AuditEntry] = audit.entrees
    assert [e.error_code for e in entrees] == ["UNAUTHORIZED_COLLECTION"]


def test_hors_contexte_d_appel_le_pont_refuse_au_lieu_de_supposer() -> None:
    # Arrange — contexte vide : la fonction de tool a été atteinte hors du
    # chemin de la barrière 1 (qui, elle, pose identité et périmètre).

    # Act / Assert — refus explicite, jamais un `assert` que `python -O`
    # supprimerait, ni un périmètre supposé.
    with pytest.raises(UnauthenticatedError) as capture:
        call_context()
    assert json.loads(str(capture.value))["error_code"] == "UNAUTHENTICATED"
