from pydantic import BaseModel


class IngestResponse(BaseModel):
    document_id: str
    chunk_count: int
    status: str
