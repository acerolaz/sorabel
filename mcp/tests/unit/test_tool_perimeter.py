"""Barrière 2 branchée pour de vrai, sur **tous** les tools (spec §4.2, §11.1).

Un faux port espion enregistre ce que chaque tool transmet réellement au
backend. Trois familles de preuves :

- les 6 tools documentaires transmettent le périmètre de collections **de la
  matrice**, que l'appelant en demande ou non ;
- les 3 tools qui portent un périmètre de tables (`ask_database`,
  `run_sql_query`, `get_schema_info`) transmettent `Scope.sql_tables` ;
- les 4 tools qui rendent des lignes métier transmettent `Scope.masked_columns`
  (E5), et tous transmettent le profil du **token**, jamais celui que l'appelant
  déclare dans ses arguments.

Sans cette couverture par tool, oublier `resolve_collections` dans un seul
d'entre eux (`collections or ()`, par exemple) resterait indétectable : le type
passerait, et le périmètre deviendrait silencieusement « pas de filtre ».
"""

import io
import json
from collections.abc import Sequence
from typing import Any

import pytest
from app.api.governance import GovernedFastMCP
from app.api.tools._context import call_context
from app.api.tools.rag import register_rag_tools
from app.api.tools.sql import register_sql_tools
from app.domain.access_matrix import AccessMatrix, ProfileEntry
from app.domain.catalog import CATALOG_BY_NAME
from app.domain.errors import ToolError, UnauthenticatedError
from app.domain.models import AuditEntry, Scope
from app.infrastructure.audit.stdout_audit_log import StdoutAuditLog
from mcp.server.fastmcp.exceptions import ToolError as SdkToolError

from tests.harness import FakeAuditLog, FakeTokenVerifier, appel_http, entetes

#: Périmètre accordé au profil par la matrice — jamais négociable par l'appelant.
PORTEE_VENTE = Scope(("datasheet", "manuel"), ("products", "orders"), ("purchase_price",))

#: Profil que l'appelant déclare dans les arguments des tools qui portent le
#: paramètre `profile` du contrat publié : il ne doit jamais servir à décider.
PROFIL_MENTI = "administrateur"

#: Tools documentaires et un jeu d'arguments minimal — aucun ne demande de
#: collection : le périmètre transmis doit donc être celui de la matrice.
TOOLS_RAG: tuple[tuple[str, dict[str, Any]], ...] = (
    ("answer_question", {"query": "tension ?"}),
    ("search_documents", {"query": "tension ?"}),
    ("lookup_by_reference", {"product_ref": "REF-8842"}),
    ("get_document_metadata", {"doc_id": "REF-8842:datasheet:1"}),
    ("check_answer_confidence", {"query": "tension ?"}),
    ("list_document_types", {}),
)

#: Tools qui transmettent un périmètre de tables au backend.
TOOLS_TABLES: tuple[tuple[str, dict[str, Any]], ...] = (
    ("ask_database", {"question": "stock de REF-8842 ?", "profile": PROFIL_MENTI}),
    ("run_sql_query", {"sql": "SELECT 1", "profile": PROFIL_MENTI}),
    ("get_schema_info", {"profile": PROFIL_MENTI}),
)

#: Tools qui rendent des lignes métier : le masquage de colonnes déclaré par la
#: matrice doit accompagner l'appel (E5, spec §4.2).
TOOLS_MASQUAGE: tuple[tuple[str, dict[str, Any]], ...] = (
    ("run_sql_query", {"sql": "SELECT 1", "profile": PROFIL_MENTI}),
    ("get_stock", {"product_ref": "REF-8842"}),
    ("get_order_status", {"order_id": "CMD-1"}),
    ("get_customer_order_history", {"customer_id": "CLI-1"}),
)

#: Tools acceptant une demande de collections de la part de l'appelant — les
#: seuls sur lesquels un débordement de périmètre est exprimable.
TOOLS_COLLECTIONS_DEMANDABLES: tuple[tuple[str, dict[str, Any]], ...] = (
    ("search_documents", {"query": "marges ?"}),
    ("lookup_by_reference", {"product_ref": "REF-8842"}),
)


class BackendEspion:
    """Faux `RagPort` + `Text2SqlPort` + `SqlExecutionPort` : enregistre ce qu'il reçoit.

    Un seul objet pour les trois ports : les tools ne connaissent que les
    méthodes qui les concernent, et un test peut ainsi inspecter d'un coup tout
    ce qui a franchi la frontière `mcp` → backend.
    """

    def __init__(self) -> None:
        self.appels: list[tuple[str, dict[str, Any]]] = []

    def _note(self, methode: str, **details: Any) -> dict[str, Any]:
        self.appels.append((methode, details))
        return {"source": "espion"}

    @property
    def collections_vues(self) -> list[tuple[str, ...]]:
        return [d["collections"] for _, d in self.appels if "collections" in d]

    @property
    def tables_vues(self) -> list[tuple[str, ...]]:
        return [d["tables"] for _, d in self.appels if "tables" in d]

    @property
    def masquages_vus(self) -> list[tuple[str, ...]]:
        return [d["masked_columns"] for _, d in self.appels if "masked_columns" in d]

    @property
    def profils_vus(self) -> list[str]:
        return [d["profile"] for _, d in self.appels if "profile" in d]

    # --- RagPort -----------------------------------------------------------
    async def answer(
        self, query: str, collections: Sequence[str], correlation_id: str
    ) -> dict[str, Any]:
        # Aucune citation : le composite n'enchaîne donc pas sur `document_metadata`
        # avec un `doc_id` fabriqué par le test — chaque brique reste observable.
        return self._note("answer", collections=tuple(collections)) | {"citations": []}

    async def search(
        self, query: str, top_k: int, collections: Sequence[str], correlation_id: str
    ) -> dict[str, Any]:
        return self._note("search", collections=tuple(collections))

    async def lookup(
        self, product_ref: str, collections: Sequence[str], correlation_id: str
    ) -> dict[str, Any]:
        return self._note("lookup", collections=tuple(collections))

    async def document_metadata(
        self, doc_id: str, collections: Sequence[str], correlation_id: str
    ) -> dict[str, Any]:
        return self._note("document_metadata", collections=tuple(collections))

    async def confidence(
        self, query: str, collections: Sequence[str], correlation_id: str
    ) -> dict[str, Any]:
        return self._note("confidence", collections=tuple(collections))

    async def document_types(
        self, collections: Sequence[str], correlation_id: str
    ) -> dict[str, Any]:
        return self._note("document_types", collections=tuple(collections))

    # --- Text2SqlPort ------------------------------------------------------
    async def generate_sql(
        self, question: str, profile: str, tables: Sequence[str], correlation_id: str
    ) -> dict[str, Any]:
        return self._note("generate_sql", profile=profile, tables=tuple(tables))

    # --- SqlExecutionPort --------------------------------------------------
    async def run_sql(
        self,
        sql: str,
        profile: str,
        tables: Sequence[str],
        masked_columns: Sequence[str],
        correlation_id: str,
    ) -> dict[str, Any]:
        return self._note(
            "run_sql",
            profile=profile,
            tables=tuple(tables),
            masked_columns=tuple(masked_columns),
        )

    async def stock(
        self, product_ref: str, profile: str, masked_columns: Sequence[str], correlation_id: str
    ) -> dict[str, Any]:
        return self._note("stock", profile=profile, masked_columns=tuple(masked_columns))

    async def order_status(
        self, order_id: str, profile: str, masked_columns: Sequence[str], correlation_id: str
    ) -> dict[str, Any]:
        return self._note("order_status", profile=profile, masked_columns=tuple(masked_columns))

    async def customer_orders(
        self,
        customer_id: str,
        limit: int,
        profile: str,
        masked_columns: Sequence[str],
        correlation_id: str,
    ) -> dict[str, Any]:
        return self._note("customer_orders", profile=profile, masked_columns=tuple(masked_columns))

    async def schema_info(
        self, profile: str, keyword: str | None, tables: Sequence[str], correlation_id: str
    ) -> dict[str, Any]:
        return self._note("schema_info", profile=profile, tables=tuple(tables))

    async def query_history(self, profile: str, limit: int, correlation_id: str) -> dict[str, Any]:
        return self._note("query_history", profile=profile)


def _serveur(espion: BackendEspion, audit: Any) -> GovernedFastMCP:
    """Serveur portant les 13 tools, sur un profil qui a droit à tout le catalogue."""
    server = GovernedFastMCP(
        matrix=AccessMatrix(
            version=1,
            profiles={"sales": ProfileEntry(tools=frozenset(CATALOG_BY_NAME), scope=PORTEE_VENTE)},
        ),
        audit=audit,
        verifier=FakeTokenVerifier({"jeton-de-test": "sales"}),
        name="test",
    )
    register_rag_tools(server, espion)
    register_sql_tools(server, espion, espion)
    return server


@pytest.fixture
def espion() -> BackendEspion:
    return BackendEspion()


@pytest.fixture
def serveur(espion: BackendEspion) -> GovernedFastMCP:
    return _serveur(espion, StdoutAuditLog(stream=io.StringIO()))


@pytest.mark.parametrize(("tool", "arguments"), TOOLS_RAG, ids=[nom for nom, _ in TOOLS_RAG])
async def test_chaque_tool_rag_transmet_le_perimetre_de_la_matrice(
    tool: str, arguments: dict[str, Any], espion: BackendEspion, serveur: GovernedFastMCP
) -> None:
    # Arrange / Act — l'appelant ne demande aucune collection
    with appel_http(entetes()):
        await serveur.call_tool(tool, arguments)

    # Assert — chaque appel au port porte le périmètre du profil, jamais « pas de filtre »
    assert espion.collections_vues
    assert espion.collections_vues == [PORTEE_VENTE.rag_collections] * len(espion.collections_vues)


@pytest.mark.parametrize(("tool", "arguments"), TOOLS_TABLES, ids=[nom for nom, _ in TOOLS_TABLES])
async def test_chaque_tool_sql_transmet_les_tables_de_la_matrice(
    tool: str, arguments: dict[str, Any], espion: BackendEspion, serveur: GovernedFastMCP
) -> None:
    # Arrange / Act
    with appel_http(entetes()):
        await serveur.call_tool(tool, arguments)

    # Assert — périmètre de tables issu du `Scope`, profil issu du token
    assert espion.tables_vues == [PORTEE_VENTE.sql_tables]
    assert espion.profils_vus == ["sales"]


@pytest.mark.parametrize(
    ("tool", "arguments"), TOOLS_MASQUAGE, ids=[nom for nom, _ in TOOLS_MASQUAGE]
)
async def test_chaque_tool_de_lignes_metier_transmet_le_masquage_de_la_matrice(
    tool: str, arguments: dict[str, Any], espion: BackendEspion, serveur: GovernedFastMCP
) -> None:
    # Arrange / Act
    with appel_http(entetes()):
        await serveur.call_tool(tool, arguments)

    # Assert — le masquage déclaré par la matrice accompagne l'appel (E5)
    assert espion.masquages_vus == [PORTEE_VENTE.masked_columns]


async def test_une_demande_peut_affiner_le_perimetre_mais_pas_l_elargir(
    espion: BackendEspion, serveur: GovernedFastMCP
) -> None:
    # Arrange / Act — sous-ensemble strict du périmètre accordé
    with appel_http(entetes()):
        await serveur.call_tool(
            "search_documents", {"query": "tension ?", "collections": ["manuel"]}
        )

    # Assert
    assert espion.collections_vues == [("manuel",)]


@pytest.mark.parametrize(
    ("tool", "arguments"),
    TOOLS_COLLECTIONS_DEMANDABLES,
    ids=[nom for nom, _ in TOOLS_COLLECTIONS_DEMANDABLES],
)
async def test_une_demande_hors_perimetre_est_refusee_sans_atteindre_le_port(
    tool: str, arguments: dict[str, Any], espion: BackendEspion
) -> None:
    # Arrange
    audit = FakeAuditLog()
    serveur = _serveur(espion, audit)

    # Act
    with appel_http(entetes()):
        with pytest.raises(SdkToolError) as capture:
            await serveur.call_tool(tool, arguments | {"collections": ["finance"]})

    # Assert — refus typé, port jamais atteint, refus journalisé (E5)
    cause = capture.value.__cause__
    assert isinstance(cause, ToolError)
    corps = json.loads(str(cause))
    assert corps["error_code"] == "UNAUTHORIZED_COLLECTION"
    assert set(corps) == {"error_code", "message", "correlation_id"}
    assert espion.appels == []
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
