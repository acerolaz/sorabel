from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class Citation:
    title: str
    product_ref: str
    published_date: date
    document_type: str
    url: str | None = None


@dataclass(frozen=True)
class Document:
    id: str
    title: str
    product_ref: str
    version: str
    status: str  # "active" | "deprecated"
    document_type: str  # "datasheet" | "manuel" | "procedure_sav"
    published_date: date
    source_path: str
    content_hash: str


@dataclass(frozen=True)
class Chunk:
    id: str
    document_id: str
    content: str
    content_type: str  # "text" | "table"
    title: str
    product_ref: str
    version: str
    status: str  # "active" | "deprecated"
    document_type: str
    published_date: date
    content_hash: str
    source_path: str


@dataclass(frozen=True)
class RetrievalResult:
    chunk: Chunk
    dense_rank: int | None
    sparse_rank: int | None
    fused_score: float
    rerank_score: float | None = None


@dataclass(frozen=True)
class Answer:
    text: str
    citations: list[Citation] = field(default_factory=list)
    confidence: str = "refused"  # "high" | "low" | "refused"
