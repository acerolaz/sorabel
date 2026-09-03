# tests/test_routers/test_query_route.py
from datetime import date

import pytest
from httpx import ASGITransport, AsyncClient

from app.dependencies import get_answer_query_use_case
from app.domain.models import Answer, Citation
from app.main import app


class FakeUseCase:
    def __init__(self, answer: Answer):
        self._answer = answer

    async def execute(self, query, product_ref=None, top_k=20):
        return self._answer


@pytest.mark.asyncio
async def test_query_route_returns_citations_on_high_confidence():
    # Arrange
    answer = Answer(
        text="Réponse.",
        citations=[
            Citation(title="Fiche REF-1", product_ref="REF-1", published_date=date(2026, 1, 1), document_type="manuel")
        ],
        confidence="high",
    )
    app.dependency_overrides[get_answer_query_use_case] = lambda: FakeUseCase(answer)

    # Act
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/query", json={"query": "tension REF-1 ?"})

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert data["refused"] is False
    assert data["citations"][0]["product_ref"] == "REF-1"
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_query_route_returns_refusal_with_no_citations():
    # Arrange
    answer = Answer(
        text="Je ne trouve pas cette information dans le corpus.",
        citations=[],
        confidence="refused",
    )
    app.dependency_overrides[get_answer_query_use_case] = lambda: FakeUseCase(answer)

    # Act
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/query", json={"query": "question hors corpus"})

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert data["refused"] is True
    assert data["citations"] == []
    app.dependency_overrides.clear()
