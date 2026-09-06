from collections.abc import Sequence
from typing import Any

from app.domain.ports import RagPort


async def answer_question(
    rag: RagPort, query: str, collections: Sequence[str], correlation_id: str
) -> dict[str, Any]:
    """Composite de `MCP.md` §1 : agrège trois briques, ne rédige rien.

    Seule orchestration réelle du projet (spec §9.1) : `answer`,
    `document_metadata` (une fois par citation) et `document_types`, chacune
    recevant le `correlation_id` de l'appel.

    De la réponse du backend, seules **citations et confidence** sont
    conservées (spec §9.1, décision D6) ; sa `source` l'est aussi, pour la
    provenance (§9.2). Une rédaction éventuelle est **écartée ici**, par
    projection explicite des clés retenues plutôt que par retrait des clés
    indésirables — une clé nouvelle du backend ne peut donc pas se propager par
    inadvertance. `mcp` ne génère ni ne relaie aucune réponse rédigée : c'est au
    LLM du client de formuler la réponse à partir des sources, en les citant.
    """
    reponse = await rag.answer(query, collections, correlation_id)
    citations = [
        citation for citation in reponse.get("citations", []) if isinstance(citation, dict)
    ]
    metadonnees = [
        await rag.document_metadata(citation["doc_id"], collections, correlation_id)
        for citation in citations
        if citation.get("doc_id")
    ]
    types = await rag.document_types(collections, correlation_id)
    return {
        "sources": {
            "source": reponse.get("source"),
            "citations": citations,
            "confidence": reponse.get("confidence"),
        },
        "metadata": metadonnees,
        "document_types": types,
    }
