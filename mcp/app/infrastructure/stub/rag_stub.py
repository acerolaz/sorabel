"""Doublure du service RAG (`rag-hybride`), en attendant ses endpoints de
briques (spec §9.2) : rend des réponses plausibles et stables, systématiquement
étiquetées `source: "stub"`.

Convention de test explicite : une requête contenant « absente » simule un
hors-corpus (E1). Une séquence `collections` vide signifie un périmètre
autorisé de zéro collection — jamais l'absence de filtre (spec §4.2, ports.py) :
elle produit systématiquement zéro résultat, jamais l'intégralité du corpus.
"""

from collections.abc import Sequence
from typing import Any

from app.domain.errors import NotFoundInCorpusError

CITATION = {
    "doc_id": "REF-8842:datasheet:1",
    "title": "Fiche produit REF-8842",
    "product_ref": "REF-8842",
    "published_date": "2026-01-15",
    "document_type": "datasheet",
}


class RagStub:
    """Doublure du service RAG, en attendant les endpoints de briques.

    Convention de test : une requête contenant « absente » simule un
    hors-corpus. Un périmètre `collections` vide simule un périmètre
    autorisé nul : zéro résultat, jamais l'absence de filtre.
    """

    async def answer(
        self, query: str, collections: Sequence[str], correlation_id: str
    ) -> dict[str, Any]:
        if "absente" in query.lower() or not collections:
            raise NotFoundInCorpusError(correlation_id)
        return {
            "source": "stub",
            "citations": [CITATION],
            "confidence": "high",
            "collections": list(collections),
        }

    async def search(
        self, query: str, top_k: int, collections: Sequence[str], correlation_id: str
    ) -> dict[str, Any]:
        if not collections:
            return {"source": "stub", "passages": [], "collections": []}
        passages = [{"content": "Tension nominale : 230V.", "citation": CITATION}]
        return {
            "source": "stub",
            "passages": passages[:top_k],
            "collections": list(collections),
        }

    async def lookup(
        self, product_ref: str, collections: Sequence[str], correlation_id: str
    ) -> dict[str, Any]:
        if not collections:
            raise NotFoundInCorpusError(correlation_id)
        return {"source": "stub", "product_ref": product_ref, "citation": CITATION}

    async def document_metadata(
        self, doc_id: str, collections: Sequence[str], correlation_id: str
    ) -> dict[str, Any]:
        if not collections:
            raise NotFoundInCorpusError(correlation_id)
        return {
            "source": "stub",
            "doc_id": doc_id,
            "title": CITATION["title"],
            "version": "1",
            "published_date": CITATION["published_date"],
            "status": "active",
        }

    async def confidence(
        self, query: str, collections: Sequence[str], correlation_id: str
    ) -> dict[str, Any]:
        if "absente" in query.lower() or not collections:
            return {"source": "stub", "score": 0.0}
        return {"source": "stub", "score": 0.82}

    async def document_types(
        self, collections: Sequence[str], correlation_id: str
    ) -> dict[str, Any]:
        return {"source": "stub", "document_types": list(collections)}
