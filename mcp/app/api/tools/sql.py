"""Les 7 tools données (spec §9). Aucune logique métier : chaque fonction résout
périmètre et masquage par la barrière 2, puis délègue au port.

Le paramètre `profile` reste dans la signature des tools qui le déclarent dans
`MCP.md` §2 — c'est le contrat publié — mais il n'est **jamais** utilisé pour
décider : le profil effectif vient du token vérifié (`Identity.profile`). Un
client qui ment sur ce paramètre n'obtient rien de plus.

Docstrings reprises telles quelles de `MCP.md` §2 (spec §9.3) : elles sont la
description lue par le LLM client, mise en forme comprise — d'où le
`# noqa: E501` plutôt qu'un repli qui introduirait des sauts de ligne.
"""

from typing import Any

from mcp.server.fastmcp import FastMCP

from app.api.tools._context import call_context
from app.application.use_cases.forward_to_backend import resolve_tables
from app.domain.ports import SqlExecutionPort, Text2SqlPort


def register_sql_tools(
    server: FastMCP[Any], text2sql: Text2SqlPort, sqlapi: SqlExecutionPort
) -> None:
    """Enregistre les 7 tools données. Aucune logique métier ici."""

    @server.tool()
    async def ask_database(question: str, profile: str) -> dict[str, Any]:
        """Génère une requête SQL en lecture seule à partir d'une question en langage naturel, via l'agent Text-to-SQL dédié. NE L'EXÉCUTE PAS — retourne uniquement le SQL généré ; appeler run_sql_query pour l'exécuter. À utiliser UNIQUEMENT si aucun des tools figés (get_stock, get_order_status, get_customer_order_history) ne couvre le besoin — dernier recours, plus coûteux et moins déterministe. CRITICAL: n'utilise que les noms de tables/colonnes retournés par get_schema_info, ne jamais en inventer. Args: question: Question métier en langage naturel. profile: Profil du client appelant, pour restreindre les tables/colonnes visibles dans le schéma injecté."""  # noqa: E501
        identity, scope, correlation_id = call_context()
        tables = resolve_tables(None, scope, correlation_id)
        return await text2sql.generate_sql(question, identity.profile, tables, correlation_id)

    @server.tool()
    async def run_sql_query(sql: str, profile: str) -> dict[str, Any]:
        """Exécute une requête SQL déjà écrite (typiquement obtenue via ask_database) après validation par la chaîne de garde-fous en lecture seule (rôle DB, blocklist, AST, guardrail sémantique, LIMIT/timeout, réplica). NE GÉNÈRE AUCUN SQL — sql doit être une requête complète et syntaxiquement valide. Args: sql: Requête SQL à valider et exécuter. profile: Profil du client appelant, pour restreindre les tables/colonnes visibles et appliquer le masquage de colonnes."""  # noqa: E501
        identity, scope, correlation_id = call_context()
        tables = resolve_tables(None, scope, correlation_id)
        return await sqlapi.run_sql(
            sql, identity.profile, tables, scope.masked_columns, correlation_id
        )

    @server.tool()
    async def get_stock(product_ref: str) -> dict[str, Any]:
        """Retourne le stock disponible pour une référence produit exacte. À utiliser EN PRIORITÉ dès qu'une référence produit (ex: 'REF-8842') est connue. Plus rapide et plus fiable que ask_database pour ce besoin précis — ne PAS utiliser ask_database si ce tool suffit. Args: product_ref: Référence produit exacte (ex: 'REF-8842')."""  # noqa: E501
        identity, scope, correlation_id = call_context()
        return await sqlapi.stock(
            product_ref, identity.profile, scope.masked_columns, correlation_id
        )

    @server.tool()
    async def get_order_status(order_id: str) -> dict[str, Any]:
        """Retourne le statut d'une commande à partir de son identifiant. À utiliser EN PRIORITÉ dès qu'un order_id est connu. Ne PAS utiliser ask_database pour ce besoin. Args: order_id: Identifiant de commande."""  # noqa: E501
        identity, scope, correlation_id = call_context()
        return await sqlapi.order_status(
            order_id, identity.profile, scope.masked_columns, correlation_id
        )

    @server.tool()
    async def get_customer_order_history(customer_id: str, limit: int = 20) -> dict[str, Any]:
        """Retourne l'historique des commandes d'un client identifié. À utiliser EN PRIORITÉ dès qu'un customer_id est connu. Ne PAS utiliser ask_database pour ce besoin. Args: customer_id: Identifiant client. limit: Nombre maximal de commandes retournées (défaut 20)."""  # noqa: E501
        identity, scope, correlation_id = call_context()
        return await sqlapi.customer_orders(
            customer_id, limit, identity.profile, scope.masked_columns, correlation_id
        )

    @server.tool()
    async def get_schema_info(profile: str, keyword: str | None = None) -> dict[str, Any]:
        """Retourne les tables et colonnes réellement accessibles au profil appelant. À appeler AVANT ask_database si le nom exact d'une table ou d'une colonne n'est pas certain — évite les erreurs de schéma et les hallucinations de noms de colonnes. Args: profile: Profil du client appelant (ex: 'support', 'sales'). keyword: Filtre optionnel sur le nom des tables/colonnes."""  # noqa: E501
        identity, scope, correlation_id = call_context()
        tables = resolve_tables(None, scope, correlation_id)
        return await sqlapi.schema_info(identity.profile, keyword, tables, correlation_id)

    @server.tool()
    async def get_query_history(profile: str, limit: int = 20) -> dict[str, Any]:
        """Retourne les dernières requêtes exécutées ou rejetées pour ce profil. Outil d'audit et de debug côté client — jamais une source de données métier. Args: profile: Profil du client appelant. limit: Nombre maximal d'entrées retournées (défaut 20)."""  # noqa: E501
        identity, _, correlation_id = call_context()
        return await sqlapi.query_history(identity.profile, limit, correlation_id)
