"""Adapter réel vers `rag-hybride`, via l'URL configurée (spec §9.1, §10).

`rag-hybride` n'expose aujourd'hui que `POST /api/v1/query` et
`POST /api/v1/ingest`. Seule `answer()` parle donc au vrai endpoint ; les
briques sans endpoint (`search`, `lookup`, `document_metadata`,
`confidence`, `document_types`) sont déléguées au stub, chaque délégation
restant visible dans `DELEGATED_TO_STUB` — un test verrouille cette liste
(tâche 17), pour qu'une délégation ne survive pas à l'arrivée de son
endpoint. Le mélange réel/stub tient ici, dans l'adapter : le use case
`answer_question` et le port `RagPort` ignorent totalement cette frontière.

Mapping statut HTTP -> erreur typée (arbitrage A, spec §7) :

- `>= 500` -> `BackendUnavailableError` : le backend a échoué à traiter une
  requête par ailleurs valide (ex : `EMBEDDING_SERVICE_ERROR` à 502 dans
  `rag-hybride/app/main.py`).
- `404` -> `SchemaMismatchError` : sémantique HTTP standard, la ressource
  référencée (ici une collection) n'existe pas au regard du backend — c'est
  la seule signification de « ressource inconnue » que `rag-hybride` peut
  exprimer sans un contrat de champ `error_code` dédié, qu'il ne définit pas
  encore pour `/api/v1/query`. Un futur endpoint qui signalerait une
  collection inconnue par un `error_code` explicite pourra affiner ce test
  sans changer le port ni le use case.
- autres `4xx` (ex : 422 de validation Pydantic) -> `BackendUnavailableError`,
  documenté : ce ne sont pas des refus de schéma mais des requêtes mal
  formées, qu'aucun rejeu côté `mcp` ne peut corriger ; les traiter en
  indisponibilité évite de les confondre avec un vrai `SCHEMA_MISMATCH`
  (table/colonne/collection connue mais non autorisée ou introuvable).

Une exception `httpx` (timeout, DNS, connexion refusée) est elle aussi
toujours convertie en `BackendUnavailableError` (arbitrage C) : aucune trace
d'exception de transport ne doit atteindre le client MCP.
"""

from collections.abc import Sequence
from typing import Any

import httpx

from app.domain.errors import BackendUnavailableError, NotFoundInCorpusError, SchemaMismatchError
from app.infrastructure.stub.rag_stub import RagStub


class RagHttpClient:
    """Adapter réel vers `rag-hybride`, avec délégation au stub (spec §9.1)."""

    DELEGATED_TO_STUB: frozenset[str] = frozenset(
        {"search", "lookup", "document_metadata", "confidence", "document_types"}
    )

    def __init__(
        self,
        base_url: str,
        timeout_s: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s
        self._transport = transport
        self._stub = RagStub()

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._base_url, timeout=self._timeout_s, transport=self._transport
        )

    async def answer(
        self, query: str, collections: Sequence[str], correlation_id: str
    ) -> dict[str, Any]:
        """Réponse composite réelle, via `POST /api/v1/query`."""
        try:
            async with self._client() as client:
                reponse = await client.post(
                    "/api/v1/query",
                    json={"query": query},
                    headers={"X-Correlation-Id": correlation_id},
                )
        except httpx.HTTPError as exc:
            raise BackendUnavailableError(correlation_id) from exc

        if reponse.status_code >= 500:
            raise BackendUnavailableError(correlation_id)
        if reponse.status_code == 404:
            raise SchemaMismatchError(correlation_id)
        if reponse.status_code >= 400:
            raise BackendUnavailableError(correlation_id)

        corps = reponse.json()
        if corps.get("refused"):
            raise NotFoundInCorpusError(correlation_id)

        # `answer` (le texte rédigé) est délibérément écarté : le serveur MCP
        # ne propage aucun texte généré (spec §9.1, décision D6). Projection
        # explicite des clés retenues, jamais un retrait des clés
        # indésirables, pour qu'une clé nouvelle du backend ne se propage
        # jamais par inadvertance.
        return {
            "source": "live",
            "citations": corps.get("citations", []),
            "confidence": corps.get("confidence"),
        }

    async def search(
        self, query: str, top_k: int, collections: Sequence[str], correlation_id: str
    ) -> dict[str, Any]:
        """Délégué au stub : `rag-hybride` n'expose pas encore de recherche dédiée."""
        return await self._stub.search(query, top_k, collections, correlation_id)

    async def lookup(
        self, product_ref: str, collections: Sequence[str], correlation_id: str
    ) -> dict[str, Any]:
        """Délégué au stub : `rag-hybride` n'expose pas encore de lookup dédié."""
        return await self._stub.lookup(product_ref, collections, correlation_id)

    async def document_metadata(
        self, doc_id: str, collections: Sequence[str], correlation_id: str
    ) -> dict[str, Any]:
        """Délégué au stub : `rag-hybride` n'expose pas encore de métadonnées."""
        return await self._stub.document_metadata(doc_id, collections, correlation_id)

    async def confidence(
        self, query: str, collections: Sequence[str], correlation_id: str
    ) -> dict[str, Any]:
        """Délégué au stub : `rag-hybride` n'expose pas encore ce score isolé."""
        return await self._stub.confidence(query, collections, correlation_id)

    async def document_types(
        self, collections: Sequence[str], correlation_id: str
    ) -> dict[str, Any]:
        """Délégué au stub : `rag-hybride` n'expose pas encore de catalogue."""
        return await self._stub.document_types(collections, correlation_id)
