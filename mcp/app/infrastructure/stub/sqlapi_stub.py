"""Doublure de `sorabelsql-api` (spec §9.2) : exécute un SQL déjà généré et
sert les tools figés, ne génère jamais.

Une séquence `tables` vide (sur `run_sql`) signifie un périmètre autorisé de
zéro table pour le profil appelant — jamais l'absence de filtre (spec §4.2,
ports.py) : `run_sql` ne peut alors honorer aucune requête ; `schema_info`
rend un schéma vide plutôt que le schéma complet.
"""

from collections.abc import Sequence
from typing import Any

from app.domain.errors import SchemaMismatchError


class SqlApiStub:
    """Doublure de sorabelsql-api : exécute, ne génère jamais."""

    async def run_sql(
        self,
        sql: str,
        profile: str,
        tables: Sequence[str],
        masked_columns: Sequence[str],
        correlation_id: str,
    ) -> dict[str, Any]:
        if not tables:
            raise SchemaMismatchError(correlation_id)
        return {
            "source": "stub",
            "sql": sql,
            "rows": [],
            "row_count": 0,
            "masked_columns": list(masked_columns),
        }

    async def stock(
        self,
        product_ref: str,
        profile: str,
        masked_columns: Sequence[str],
        correlation_id: str,
    ) -> dict[str, Any]:
        return {
            "source": "stub",
            "product_ref": product_ref,
            "quantity": 12,
            "row_count": 1,
            "masked_columns": list(masked_columns),
        }

    async def order_status(
        self,
        order_id: str,
        profile: str,
        masked_columns: Sequence[str],
        correlation_id: str,
    ) -> dict[str, Any]:
        return {
            "source": "stub",
            "order_id": order_id,
            "status": "shipped",
            "row_count": 1,
            "masked_columns": list(masked_columns),
        }

    async def customer_orders(
        self,
        customer_id: str,
        limit: int,
        profile: str,
        masked_columns: Sequence[str],
        correlation_id: str,
    ) -> dict[str, Any]:
        return {
            "source": "stub",
            "customer_id": customer_id,
            "orders": [],
            "row_count": 0,
            "masked_columns": list(masked_columns),
        }

    async def schema_info(
        self, profile: str, keyword: str | None, tables: Sequence[str], correlation_id: str
    ) -> dict[str, Any]:
        return {
            "source": "stub",
            "tables": [{"name": nom, "columns": ["id"]} for nom in tables],
            "keyword": keyword,
        }

    async def query_history(self, profile: str, limit: int, correlation_id: str) -> dict[str, Any]:
        return {"source": "stub", "items": [], "row_count": 0}
