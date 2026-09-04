"""Le composite `answer_question` — la seule orchestration réelle du projet (spec §9.1).

Trois briques du `RagPort`, une fois chacune, `correlation_id` propagé, et la
rédaction éventuelle du backend écartée : `mcp` ne relaie aucune réponse
rédigée (décision D6), seulement des sources.
"""

import io
from collections.abc import Sequence
from typing import Any

import pytest
from app.api.governance import GovernedFastMCP
from app.api.tools.rag import register_rag_tools
from app.domain.access_matrix import AccessMatrix, ProfileEntry
from app.domain.models import Scope
from app.infrastructure.audit.stdout_audit_log import StdoutAuditLog
from app.infrastructure.stub.rag_stub import CITATION

from tests.unit.harness import CORRELATION, FakeTokenVerifier, appel_http

#: Rédaction que le backend `rag-hybride` peut renvoyer et que `mcp` ne doit
#: jamais propager — recherchée telle quelle dans la réponse rendue au client.
TEXTE_REDIGE = "La tension nominale de la REF-8842 est de 230 volts."

PORTEE_VENTE = Scope(("datasheet", "manuel"), (), ())


class RagEspion:
    """Faux port qui compte ses appels et retient les `correlation_id` reçus."""

    def __init__(self) -> None:
        self.appels: list[str] = []
        self.correlations: list[str] = []

    async def answer(
        self, query: str, collections: Sequence[str], correlation_id: str
    ) -> dict[str, Any]:
        self.appels.append("answer")
        self.correlations.append(correlation_id)
        return {
            "source": "stub",
            "answer": TEXTE_REDIGE,
            "citations": [CITATION],
            "confidence": "high",
        }

    async def document_metadata(
        self, doc_id: str, collections: Sequence[str], correlation_id: str
    ) -> dict[str, Any]:
        self.appels.append("document_metadata")
        self.correlations.append(correlation_id)
        return {"source": "stub", "doc_id": doc_id}

    async def document_types(
        self, collections: Sequence[str], correlation_id: str
    ) -> dict[str, Any]:
        self.appels.append("document_types")
        self.correlations.append(correlation_id)
        return {"source": "stub", "document_types": list(collections)}

    async def search(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError("le composite ne doit pas appeler search")

    async def lookup(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError("le composite ne doit pas appeler lookup")

    async def confidence(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError("le composite ne doit pas appeler confidence")


@pytest.fixture
def espion() -> RagEspion:
    return RagEspion()


@pytest.fixture
def serveur(espion: RagEspion) -> GovernedFastMCP:
    server = GovernedFastMCP(
        matrix=AccessMatrix(
            version=1,
            profiles={
                "sales": ProfileEntry(tools=frozenset({"answer_question"}), scope=PORTEE_VENTE)
            },
        ),
        audit=StdoutAuditLog(stream=io.StringIO()),
        verifier=FakeTokenVerifier({"jeton-de-test": "sales"}),
        name="test",
    )
    register_rag_tools(server, espion)
    return server


async def test_le_composite_orchestre_les_trois_briques(
    espion: RagEspion, serveur: GovernedFastMCP
) -> None:
    # Arrange / Act
    with appel_http():
        await serveur.call_tool("answer_question", {"query": "tension de REF-8842 ?"})

    # Assert — les trois briques de MCP.md §1, une fois chacune
    assert espion.appels == ["answer", "document_metadata", "document_types"]


async def test_le_composite_propage_le_correlation_id_a_chaque_brique(
    espion: RagEspion, serveur: GovernedFastMCP
) -> None:
    # Arrange / Act
    with appel_http():
        await serveur.call_tool("answer_question", {"query": "tension ?"})

    # Assert
    assert espion.correlations == [CORRELATION] * 3


async def test_le_composite_ecarte_la_redaction_du_backend(serveur: GovernedFastMCP) -> None:
    # Arrange / Act
    with appel_http():
        resultat = await serveur.call_tool("answer_question", {"query": "tension ?"})

    # Assert — les sources sont là, la rédaction du backend n'y est nulle part
    rendu = repr(resultat)
    assert CITATION["doc_id"] in rendu
    assert TEXTE_REDIGE not in rendu
