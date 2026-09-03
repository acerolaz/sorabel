from fastapi import APIRouter, Depends, File, Form, UploadFile

from app.api.schemas.ingest import IngestResponse
from app.application.use_cases.ingest_document import IngestDocumentUseCase
from app.dependencies import get_ingest_document_use_case

router = APIRouter(prefix="/api/v1", tags=["ingest"])


@router.post("/ingest", response_model=IngestResponse)
async def ingest_document(
    document_type: str = Form(...),
    file: UploadFile = File(...),
    product_ref: str | None = Form(default=None),
    use_case: IngestDocumentUseCase = Depends(get_ingest_document_use_case),
) -> IngestResponse:
    """Ingest a source document (Markdown or PDF) into the dual dense/lexical index.

    `product_ref` is an optional explicit override of the product reference,
    useful for PDFs which have no structured frontmatter to extract one from.
    """
    raw_bytes = await file.read()
    result = await use_case.execute(
        raw_bytes, file.filename or "", document_type, product_ref_override=product_ref
    )
    return IngestResponse(
        document_id=result.document_id, chunk_count=result.chunk_count, status=result.status
    )
