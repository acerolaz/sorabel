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
        client, ni faire fuiter un détail d'implémentation du journal.
        """
        ...


class RagPort(Protocol):
    """Retrieval documentaire hybride. `collections` porte le périmètre
    autorisé résolu par la matrice d'accès pour le profil appelant — jamais
    choisi par l'appelant lui-même (barrière 2, spec §4.2). `correlation_id`
    est généré à l'entrée de `call_tool` et propagé tel quel au backend pour
    corréler les journaux de bout en bout (spec §8).
    """

    async def answer(
        self, query: str, collections: Sequence[str], correlation_id: str
    ) -> dict[str, Any]: ...

    async def search(
        self, query: str, top_k: int, collections: Sequence[str], correlation_id: str
    ) -> dict[str, Any]: ...

    async def lookup(
        self, product_ref: str, collections: Sequence[str], correlation_id: str
    ) -> dict[str, Any]: ...

    async def document_metadata(
        self, doc_id: str, collections: Sequence[str], correlation_id: str
    ) -> dict[str, Any]: ...

    async def confidence(
        self, query: str, collections: Sequence[str], correlation_id: str
    ) -> dict[str, Any]: ...

    async def document_types(
        self, collections: Sequence[str], correlation_id: str
    ) -> dict[str, Any]: ...


class Text2SqlPort(Protocol):
    """Génération seule de SQL lecture seule — n'exécute jamais. `tables`
    porte le périmètre autorisé résolu par la matrice, jamais choisi par
    l'appelant. `correlation_id` est propagé au backend de génération.
    """

    async def generate_sql(
        self, question: str, profile: str, tables: Sequence[str], correlation_id: str
    ) -> dict[str, Any]: ...


class SqlExecutionPort(Protocol):
    """Exécution seule de SQL (déjà généré ou fourni tel quel), chaîne de
    garde-fous et tools figés. `tables`/`masked_columns` portent le périmètre
    et le masquage résolus par la matrice pour le profil appelant, jamais
    choisis par l'appelant. `correlation_id` est propagé au backend
    d'exécution pour corréler les journaux (spec §8).
    """

    async def run_sql(
        self,
        sql: str,
        profile: str,
        tables: Sequence[str],
        masked_columns: Sequence[str],
        correlation_id: str,
    ) -> dict[str, Any]: ...

    async def stock(
        self, product_ref: str, profile: str, correlation_id: str
    ) -> dict[str, Any]: ...

    async def order_status(
        self, order_id: str, profile: str, correlation_id: str
    ) -> dict[str, Any]: ...

    async def customer_orders(
        self,
        customer_id: str,
        limit: int,
        profile: str,
        masked_columns: Sequence[str],
        correlation_id: str,
    ) -> dict[str, Any]: ...

    async def schema_info(
        self, profile: str, keyword: str | None, tables: Sequence[str], correlation_id: str
    ) -> dict[str, Any]: ...

    async def query_history(
        self, profile: str, limit: int, correlation_id: str
    ) -> dict[str, Any]: ...
