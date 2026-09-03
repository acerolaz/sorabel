from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    query: str = Field(min_length=1)
    product_ref: str | None = None
    top_k: int = Field(default=20, ge=1, le=50)


class CitationResponse(BaseModel):
    title: str
    product_ref: str
    published_date: str
    document_type: str


class QueryResponse(BaseModel):
    answer: str
    citations: list[CitationResponse]
    confidence: str
    refused: bool
