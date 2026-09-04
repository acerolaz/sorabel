from collections.abc import Sequence
from typing import Any, Protocol

from app.domain.models import AuditEntry, Identity


class TokenVerifierPort(Protocol):
    """Vérifie un JWT porteur et en dérive l'identité appelante."""

    def verify(self, token: str) -> Identity:
        """Vérifie un JWT et retourne l'identité. Lève InvalidTokenError sinon."""
        ...


class AuditLogPort(Protocol):
    """Journal d'audit (E5) : une ligne par appel, autorisé ou refusé."""

    def record(self, entry: AuditEntry) -> None:
        """Journalise un appel, autorisé ou refusé.

        Contrat : ne lève **jamais**. Appelé depuis le chemin critique de
        `call_tool`, y compris pour journaliser un refus — une exception ici
        ne doit jamais empêcher la réponse (ou l'erreur) d'atteindre le
        client, ni faire fuiter un détail d'implémentation du journal. En cas
        d'échec de sérialisation ou d'écriture, l'implémentation absorbe
        l'erreur ; elle peut la signaler sur `stderr`, jamais sur le canal du
        journal lui-même (spec §8 : stdout est réservé aux lignes d'audit).
        """
        ...


class RagPort(Protocol):
    """Retrieval documentaire hybride. `collections` porte le périmètre
    autorisé résolu par la matrice d'accès pour le profil appelant — jamais
    choisi par l'appelant lui-même (barrière 2, spec §4.2). `correlation_id`
    est généré à l'entrée de `call_tool` et propagé tel quel au backend pour
    corréler les journaux de bout en bout (spec §8).

    Retour : chaque méthode rend un dict dont les clés métier sont propres à
    l'endpoint (citations, confidence, métadonnées...). Une implémentation
    stub place systématiquement `source: "stub"` dans le dict retourné (spec
    §9.2) — une donnée fictive ne peut ainsi jamais être confondue avec une
    donnée réelle, ni côté client ni dans l'audit (`AuditEntry.backend`).
    Un refus documentaire (le corpus ne contient pas la réponse, E1) lève
    `NotFoundInCorpusError(correlation_id)`, jamais un champ `found: false`
    dans le dict. Une indisponibilité du backend lève
    `BackendUnavailableError(correlation_id)`, jamais un champ d'erreur dans
    le dict retourné.
    """

    async def answer(
        self, query: str, collections: Sequence[str], correlation_id: str
    ) -> dict[str, Any]:
        """Réponse composite (citations + confidence) pour `answer_question`."""
        ...

    async def search(
        self, query: str, top_k: int, collections: Sequence[str], correlation_id: str
    ) -> dict[str, Any]:
        """Recherche hybride en langage naturel pour `search_documents`."""
        ...

    async def lookup(
        self, product_ref: str, collections: Sequence[str], correlation_id: str
    ) -> dict[str, Any]:
        """Lookup exact par référence produit pour `lookup_by_reference`."""
        ...

    async def document_metadata(
        self, doc_id: str, collections: Sequence[str], correlation_id: str
    ) -> dict[str, Any]:
        """Métadonnées d'un document pour `get_document_metadata`."""
        ...

    async def confidence(
        self, query: str, collections: Sequence[str], correlation_id: str
    ) -> dict[str, Any]:
        """Score de confiance seul pour `check_answer_confidence`."""
        ...

    async def document_types(
        self, collections: Sequence[str], correlation_id: str
    ) -> dict[str, Any]:
        """Catalogue des types de documents pour `list_document_types`."""
        ...


class Text2SqlPort(Protocol):
    """Génération seule de SQL lecture seule — n'exécute jamais. `tables`
    porte le périmètre autorisé résolu par la matrice, jamais choisi par
    l'appelant. `correlation_id` est propagé au backend de génération.

    Retour : dict avec les clés propres à la génération (SQL généré,
    explication...). Une implémentation stub place `source: "stub"` (spec
    §9.2). Un SQL non générable au regard du schéma accessible lève
    `SchemaMismatchError(correlation_id)` ; une indisponibilité du backend
    lève `BackendUnavailableError(correlation_id)` ; jamais un champ d'erreur
    dans le dict retourné.
    """

    async def generate_sql(
        self, question: str, profile: str, tables: Sequence[str], correlation_id: str
    ) -> dict[str, Any]:
        """Génère du SQL lecture seule pour `ask_database` ; n'exécute jamais."""
        ...


class SqlExecutionPort(Protocol):
    """Exécution seule de SQL (déjà généré ou fourni tel quel), chaîne de
    garde-fous et tools figés.

    Périmètre et masquage : `tables` (sur `run_sql`/`schema_info`) porte le
    périmètre de tables résolu par la matrice, jamais choisi par l'appelant
    ni par le backend (barrière 2, spec §4.2). La spec §4.2 est catégorique :
    le masquage n'est pas *appliqué* par `mcp` (seul `sorabelsql-api` voit
    les lignes), mais il est déclaré par la matrice et **transmis** au
    backend — ce n'est donc jamais optionnel côté port dès qu'une méthode
    rend des lignes métier. Règle systématique : **toute méthode qui renvoie
    des lignes métier reçoit `masked_columns: Sequence[str]`** — `run_sql`,
    `stock`, `order_status`, `customer_orders`. `query_history` (métadonnées
    de requêtes passées, pas de ligne métier) et `schema_info` (un schéma,
    pas des données) sont les deux seules exceptions, justifiées par la
    nature de leur retour et non par leur statut de tool figé : elles ne
    portent donc pas `masked_columns`.

    `profile: str`, présent sur toutes les méthodes, est une **étiquette
    d'audit/journalisation** (par exemple pour que `sorabelsql-api` inscrive
    le profil dans ses propres logs et les corrèle aux journaux de `mcp`) et
    non une seconde source d'autorisation : la décision d'accès a déjà été
    prise par la matrice avant l'appel au port ; le backend ne doit jamais
    revalider ou élargir le périmètre à partir de `profile` seul.

    `correlation_id` est propagé au backend d'exécution pour corréler les
    journaux (spec §8).

    Retour : dict avec les clés propres à l'endpoint (lignes, statut,
    schéma...). Une implémentation stub place `source: "stub"` (spec §9.2).
    Un SQL rejeté par les garde-fous (hors lecture seule, table non
    autorisée au niveau du backend) lève `SchemaMismatchError(correlation_id)`
    ; une indisponibilité du backend lève `BackendUnavailableError(correlation_id)`
    ; jamais un champ d'erreur dans le dict retourné.
    """

    async def run_sql(
        self,
        sql: str,
        profile: str,
        tables: Sequence[str],
        masked_columns: Sequence[str],
        correlation_id: str,
    ) -> dict[str, Any]:
        """Exécute un SQL déjà généré pour `run_sql_query`, garde-fous compris."""
        ...

    async def stock(
        self,
        product_ref: str,
        profile: str,
        masked_columns: Sequence[str],
        correlation_id: str,
    ) -> dict[str, Any]:
        """Tool figé `get_stock` — renvoie des lignes métier, masquage transmis."""
        ...

    async def order_status(
        self,
        order_id: str,
        profile: str,
        masked_columns: Sequence[str],
        correlation_id: str,
    ) -> dict[str, Any]:
        """Tool figé `get_order_status` — renvoie des lignes métier, masquage transmis."""
        ...

    async def customer_orders(
        self,
        customer_id: str,
        limit: int,
        profile: str,
        masked_columns: Sequence[str],
        correlation_id: str,
    ) -> dict[str, Any]:
        """Tool figé `get_customer_order_history`, avec masquage de colonnes (E5)."""
        ...

    async def schema_info(
        self, profile: str, keyword: str | None, tables: Sequence[str], correlation_id: str
    ) -> dict[str, Any]:
        """Schéma commenté filtré par périmètre pour `get_schema_info` — rend un
        schéma, pas des lignes métier : pas de `masked_columns` à transmettre.
        """
        ...

    async def query_history(self, profile: str, limit: int, correlation_id: str) -> dict[str, Any]:
        """Tool figé `get_query_history` — rend des métadonnées de requêtes
        passées, pas des lignes métier : pas de `masked_columns` à transmettre.
        """
        ...
