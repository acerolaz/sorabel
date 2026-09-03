# tests/test_routers/test_ingest_route.py
import pytest
from httpx import ASGITransport, AsyncClient

from app.application.use_cases.ingest_document import IngestResult
from app.dependencies import get_ingest_document_use_case
from app.domain.errors import UnsupportedFormatError
from app.main import app


class FakeUseCase:
    def __init__(self, result=None, error: Exception | None = None):
        self._result = result
        self._error = error

    async def execute(self, raw_bytes, filename, document_type, product_ref_override=None):
        if self._error is not None:
            raise self._error
        return self._result


@pytest.mark.asyncio
async def test_ingest_route_returns_result_on_success():
    # Arrange
    app.dependency_overrides[get_ingest_document_use_case] = lambda: FakeUseCase(
        result=IngestResult(document_id="REF-1", chunk_count=3, status="created")
    )

    # Act
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/ingest",
            data={"document_type": "datasheet"},
            files={"file": ("REF-1.md", b"content", "text/markdown")},
        )

    # Assert
    assert response.status_code == 200
    assert response.json() == {"document_id": "REF-1", "chunk_count": 3, "status": "created"}
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_ingest_route_returns_422_on_unsupported_format():
    # Arrange
    app.dependency_overrides[get_ingest_document_use_case] = lambda: FakeUseCase(
        error=UnsupportedFormatError("unsupported file extension: 'docx'")
    )

    # Act
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/ingest",
            data={"document_type": "datasheet"},
            files={"file": ("notes.docx", b"content", "application/octet-stream")},
        )

    # Assert
    assert response.status_code == 422
    assert response.json()["error_code"] == "UNSUPPORTED_FORMAT"
    app.dependency_overrides.clear()
