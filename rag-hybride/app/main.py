import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.routes.ingest import router as ingest_router
from app.api.routes.query import router as query_router
from app.domain.errors import EmbeddingServiceError, UnparsableDocumentError, UnsupportedFormatError

app = FastAPI(title="rag-hybride")
app.include_router(query_router)
app.include_router(ingest_router)


def _error_response(status_code: int, error_code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error_code": error_code,
            "message": message,
            "correlation_id": str(uuid.uuid4()),
        },
    )


@app.exception_handler(UnsupportedFormatError)
async def handle_unsupported_format(request: Request, exc: UnsupportedFormatError) -> JSONResponse:
    return _error_response(422, "UNSUPPORTED_FORMAT", str(exc))


@app.exception_handler(UnparsableDocumentError)
async def handle_unparsable_document(
    request: Request, exc: UnparsableDocumentError
) -> JSONResponse:
    return _error_response(422, "UNPARSABLE_DOCUMENT", str(exc))


@app.exception_handler(EmbeddingServiceError)
async def handle_embedding_service_error(
    request: Request, exc: EmbeddingServiceError
) -> JSONResponse:
    return _error_response(502, "EMBEDDING_SERVICE_ERROR", str(exc))
