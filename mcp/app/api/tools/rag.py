"""Les 6 tools documentaires (spec §9). Aucune logique métier : chaque fonction
résout le périmètre par la barrière 2 puis délègue au port.

Les docstrings sont reprises telles quelles de `MCP.md` §2, consignes de
priorité comprises : elles *sont* la description lue par le LLM client lors de
`list_tools` (spec §9.3). Elles tiennent sur une ligne — leur mise en forme fait
partie du contrat publié, d'où le `# noqa: E501` plutôt qu'un repli qui
introduirait des sauts de ligne dans le texte lu par le modèle.
"""

from typing import Any

from mcp.server.fastmcp import FastMCP

from app.api.tools._context import call_context
from app.application.use_cases.answer_question import (
    answer_question as answer_question_use_case,
)
from app.application.use_cases.forward_to_backend import resolve_collections
from app.domain.ports import RagPort


def register_rag_tools(server: FastMCP[Any], rag: RagPort) -> None:
    """Enregistre les 6 tools documentaires. Aucune logique métier ici."""

    @server.tool()
    async def answer_question(query: str) -> dict[str, Any]:
        """Agrège les sources documentaires nécessaires pour répondre à une question : passages pertinents, métadonnées des documents cités et catalogue des types de documents. NE RÉDIGE AUCUNE RÉPONSE — c'est au modèle appelant de formuler la réponse à partir des sources retournées, en citant systématiquement titre, référence et date. Si le corpus ne contient pas la réponse, le résultat est une erreur NOT_FOUND_IN_CORPUS : ne jamais la reformuler en réponse plausible. Args: query: Question métier en langage naturel."""  # noqa: E501
        _, scope, correlation_id = call_context()
        collections = resolve_collections(None, scope, correlation_id)
        return await answer_question_use_case(rag, query, collections, correlation_id)

    @server.tool()
    async def search_documents(
        query: str, top_k: int = 5, collections: list[str] | None = None
    ) -> dict[str, Any]:
        """Recherche hybride (dense + BM25 + reranking) dans le corpus documentaire et retourne les passages les plus pertinents avec leurs métadonnées. À utiliser pour une question formulée en langage naturel. Pour une référence produit exacte (ex: 'REF-8842'), préférer lookup_by_reference, plus fiable sur les identifiants. Args: query: Requête en langage naturel. top_k: Nombre maximal de passages retournés (défaut 5). collections: Restriction optionnelle aux collections nommées — ne peut qu'affiner le périmètre du profil, jamais l'élargir."""  # noqa: E501
        _, scope, correlation_id = call_context()
        effectif = resolve_collections(collections, scope, correlation_id)
        return await rag.search(query, top_k, effectif, correlation_id)

    @server.tool()
    async def lookup_by_reference(
        product_ref: str, collections: list[str] | None = None
    ) -> dict[str, Any]:
        """Retourne la fiche documentaire correspondant à une référence produit exacte, par correspondance littérale et sans scoring sémantique. À utiliser EN PRIORITÉ dès qu'une référence produit (ex: 'REF-8842') est connue — search_documents peut confondre deux références proches. Args: product_ref: Référence produit exacte. collections: Restriction optionnelle aux collections nommées."""  # noqa: E501
        _, scope, correlation_id = call_context()
        effectif = resolve_collections(collections, scope, correlation_id)
        return await rag.lookup(product_ref, effectif, correlation_id)

    @server.tool()
    async def get_document_metadata(doc_id: str) -> dict[str, Any]:
        """Retourne les métadonnées d'un document (titre, version, date de publication, statut) sans son contenu. À utiliser pour vérifier qu'un document cité est toujours actif, ou pour dater une information. Args: doc_id: Identifiant du document."""  # noqa: E501
        _, scope, correlation_id = call_context()
        collections = resolve_collections(None, scope, correlation_id)
        return await rag.document_metadata(doc_id, collections, correlation_id)

    @server.tool()
    async def check_answer_confidence(query: str) -> dict[str, Any]:
        """Retourne le score de pertinence du meilleur passage du corpus pour une question, sans retourner ni passage ni réponse. À utiliser pour décider s'il vaut la peine d'interroger le corpus avant d'appeler search_documents ou answer_question. Args: query: Question à évaluer."""  # noqa: E501
        _, scope, correlation_id = call_context()
        collections = resolve_collections(None, scope, correlation_id)
        return await rag.confidence(query, collections, correlation_id)

    @server.tool()
    async def list_document_types() -> dict[str, Any]:
        """Retourne les catégories de documents présentes dans le corpus accessible au profil appelant (ex: 'datasheet', 'manuel', 'procedure_sav'). À appeler pour cadrer une recherche quand la nature du document recherché est incertaine."""  # noqa: E501
        _, scope, correlation_id = call_context()
        collections = resolve_collections(None, scope, correlation_id)
        return await rag.document_types(collections, correlation_id)
