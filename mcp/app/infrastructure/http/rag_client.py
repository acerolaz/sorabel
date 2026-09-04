"""Adapter réel vers `rag-hybride`, via l'URL configurée (spec §9.1, §10).

`rag-hybride` n'expose aujourd'hui que `POST /api/v1/query` et
`POST /api/v1/ingest`. Seule `answer()` parle donc au vrai endpoint ; les
briques sans endpoint (`search`, `lookup`, `document_metadata`,
`confidence`, `document_types`) sont déléguées au stub, chaque délégation
restant visible dans `DELEGATED_TO_STUB` — un test verrouille cette liste
(tâche 17), pour qu'une délégation ne survive pas à l'arrivée de son
endpoint. Le mélange réel/stub tient ici, dans l'adapter : le use case
`answer_question` et le port `RagPort` ignorent totalement cette frontière.

Mapping statut HTTP -> erreur typée (arbitrage A, révisé en ronde de correction 1/5) :

- `>= 500` -> `BackendUnavailableError` : le backend a échoué à traiter une
  requête par ailleurs valide (ex : `EMBEDDING_SERVICE_ERROR` à 502 dans
  `rag-hybride/app/main.py`).
- `4xx` avec un corps JSON portant un `error_code` -> `SchemaMismatchError` :
  spec §7, « table/colonne inconnue **signalée par un backend** » — il faut
  donc un signal explicite du backend, jamais un code de statut nu. Un 404
  seul (ex : `RAG_BASE_URL` mal configurée) n'est **pas** un signal de
  backend : FastAPI ne renvoie 404 que pour un chemin de route inconnu,
  jamais pour une ressource métier sur `/api/v1/query` (qui ne reçoit même
  pas de `collections`, cf. plus bas) ; le traiter en `SchemaMismatchError`
  enverrait l'exploitant sur une fausse piste ("requête invalide au regard
  du schéma") alors qu'il s'agit d'une erreur de configuration réseau.
- autres `4xx` (sans `error_code`, ex : 422 de validation Pydantic, ou 404 de
  route inconnue) -> `BackendUnavailableError`, documenté : ce sont des
  échecs de requête ou de configuration, pas des refus de schéma signalés.

Une exception `httpx` (timeout, DNS, connexion refusée, URL invalide) est
elle aussi toujours convertie en `BackendUnavailableError` (arbitrage C) :
aucune trace d'exception de transport ne doit atteindre le client MCP. Un
corps de réponse non décodable en JSON, ou décodable mais non-objet, est
traité de la même façon : `rag-hybride` n'a alors rien signalé d'exploitable.

Périmètre `collections` (spec §4.2, `ports.py`) : le contrat de port est
absolu même contre un backend qui ne le supporte qu'à moitié. `QueryRequest`
de `rag-hybride` (`rag-hybride/app/api/schemas/query.py`) ne porte **aucun**
champ `collections` aujourd'hui — c'est un projet distinct, hors du lot de
cette tâche (spec §14) et cette limitation amont n'est pas corrigée ici.
Deux conséquences, à ne jamais confondre :

- **Périmètre vide** (`collections == ()`) : honoré **localement**, sans
  appel HTTP. Le contrat du port est catégorique — zéro collection autorisée
  ne peut jamais se rabattre sur le corpus entier. `answer()` lève donc
  `NotFoundInCorpusError` avant tout envoi réseau, comme `RagStub.answer`.
- **Périmètre non vide restreint** (ex : `("manuel",)` alors que le corpus
  couvre aussi `datasheet`, `procedure_sav`) : **non appliqué** côté
  backend, faute de paramètre transmis par le contrat réel. `answer()` ne
  peut aujourd'hui filtrer que le cas trivial (vide) ; un profil dont le
  périmètre RAG serait restreint sans être vide recevrait donc des
  citations hors périmètre. C'est une limitation du contrat amont, signalée
  ici et non résolue par cet adapter — corriger `rag-hybride` est hors
  scope (spec §14).

Écart assumé au plan : le corps émis ne porte pas `top_k`. Le plan envoyait
`top_k: 5` ; `mcp` n'a pas à arbitrer la largeur du retrieval, qui est une
décision de `rag-hybride`. Le défaut de `QueryRequest` (20) s'applique donc —
soit quatre fois plus large que ce que le plan prévoyait, ce qui change le
volume de citations remontées mais aucune propriété de gouvernance.
"""

from collections.abc import Sequence
from typing import Any

import httpx

from app.domain.errors import BackendUnavailableError, NotFoundInCorpusError, SchemaMismatchError
from app.infrastructure.stub.rag_stub import RagStub


def _error_code_du_corps(reponse: httpx.Response) -> str | None:
    """`error_code` d'un corps d'erreur, ou `None` si le backend n'a rien signalé.

    Un corps illisible ou non-objet vaut absence de signal : on ne déduit jamais
    un refus de schéma d'un corps qu'on n'a pas su lire.
    """
    try:
        corps = reponse.json()
    except ValueError:
        return None
    if not isinstance(corps, dict):
        return None
    code = corps.get("error_code")
    return code if isinstance(code, str) and code else None


def _corps_json(reponse: httpx.Response, correlation_id: str) -> dict[str, Any]:
    """Corps JSON d'une réponse réussie, ou `BackendUnavailableError`.

    Un 200 non décodable (page HTML d'un proxy, corps vide) ou décodable mais
    non-objet ne doit pas faire remonter une `JSONDecodeError` ou une
    `AttributeError` nue jusqu'au client MCP : le backend n'a rien renvoyé
    d'exploitable, c'est une indisponibilité.
    """
    try:
        corps = reponse.json()
    except ValueError as exc:
        raise BackendUnavailableError(correlation_id) from exc
    if not isinstance(corps, dict):
        raise BackendUnavailableError(correlation_id)
    return corps


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
        # Périmètre vide : zéro collection autorisée ne peut jamais se rabattre
        # sur le corpus entier (contrat de `RagPort`). Honoré ici, sans appel
        # réseau — c'est le seul filtrage que cet adapter peut appliquer, le
        # contrat de `rag-hybride` ne transportant pas les collections.
        if not collections:
            raise NotFoundInCorpusError(correlation_id)

        try:
            async with self._client() as client:
                reponse = await client.post(
                    # `collections` n'est volontairement pas transmis :
                    # `QueryRequest` de `rag-hybride` ne le porte pas (spec §14).
                    # Un périmètre restreint mais non vide n'est donc PAS appliqué
                    # côté backend. Le test verrouillant la forme exacte de ce
                    # corps est le déclencheur : le jour où le champ existera,
                    # il faudra y toucher, ce qui force la relecture d'ici.
                    "/api/v1/query",
                    json={"query": query},
                    headers={"X-Correlation-Id": correlation_id},
                )
        except (httpx.HTTPError, httpx.InvalidURL) as exc:
            # `InvalidURL` n'hérite pas de `HTTPError` : une `RAG_BASE_URL`
            # malformée sortirait nue jusqu'au client MCP sans cette branche.
            raise BackendUnavailableError(correlation_id) from exc

        if reponse.status_code >= 500:
            raise BackendUnavailableError(correlation_id)
        if reponse.status_code >= 400:
            # Spec §7 : `SCHEMA_MISMATCH` désigne une ressource inconnue
            # **signalée par un backend**. Un statut nu ne signale rien — un 404
            # de `rag-hybride` est un chemin de route inconnu, donc une erreur de
            # configuration. Seul un `error_code` explicite dans le corps vaut
            # signal ; tout le reste est une indisponibilité.
            if _error_code_du_corps(reponse) is not None:
                raise SchemaMismatchError(correlation_id)
            raise BackendUnavailableError(correlation_id)

        corps = _corps_json(reponse, correlation_id)
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
