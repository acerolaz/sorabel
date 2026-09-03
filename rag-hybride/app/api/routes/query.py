from fastapi import APIRouter, Depends

from app.api.schemas.query import CitationResponse, QueryRequest, QueryResponse
from app.application.use_cases.answer_query import AnswerQueryUseCase
from app.dependencies import get_answer_query_use_case

router = APIRouter(prefix="/api/v1", tags=["query"])


@router.post("/query", response_model=QueryResponse)
async def query_documents(
    request: QueryRequest,
    use_case: AnswerQueryUseCase = Depends(get_answer_query_use_case),
) -> QueryResponse:
    """Answer a documentary question via hybrid retrieval.

    Response always carries mandatory citations or an explicit refusal.
    """
    answer = await use_case.execute(request.query, request.product_ref, request.top_k)
    return QueryResponse(
        answer=answer.text,
        citations=[
            CitationResponse(
                title=c.title,
                product_ref=c.product_ref,
                published_date=c.published_date.isoformat(),
                document_type=c.document_type,
            )
            for c in answer.citations
        ],
        confidence=answer.confidence,
        refused=answer.confidence == "refused",
    )
