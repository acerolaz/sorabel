from dataclasses import dataclass
from typing import Literal

Family = Literal["rag", "sql"]
Backend = Literal["rag", "text2sql", "sqlapi"]


@dataclass(frozen=True)
class ToolDescriptor:
    """Identité d'un tool, indépendamment de son implémentation.

    Source unique consommée par la matrice d'accès et par le filtrage du
    catalogue : un tool absent d'ici n'existe pas pour la gouvernance.
    """

    name: str
    family: Family
    backend: Backend


CATALOG: tuple[ToolDescriptor, ...] = (
    ToolDescriptor("answer_question", "rag", "rag"),
    ToolDescriptor("search_documents", "rag", "rag"),
    ToolDescriptor("lookup_by_reference", "rag", "rag"),
    ToolDescriptor("get_document_metadata", "rag", "rag"),
    ToolDescriptor("check_answer_confidence", "rag", "rag"),
    ToolDescriptor("list_document_types", "rag", "rag"),
    ToolDescriptor("ask_database", "sql", "text2sql"),
    ToolDescriptor("run_sql_query", "sql", "sqlapi"),
    ToolDescriptor("get_stock", "sql", "sqlapi"),
    ToolDescriptor("get_order_status", "sql", "sqlapi"),
    ToolDescriptor("get_customer_order_history", "sql", "sqlapi"),
    ToolDescriptor("get_schema_info", "sql", "sqlapi"),
    ToolDescriptor("get_query_history", "sql", "sqlapi"),
)

CATALOG_BY_NAME: dict[str, ToolDescriptor] = {d.name: d for d in CATALOG}
