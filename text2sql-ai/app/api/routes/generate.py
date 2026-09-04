"""POST /api/v1/generate — the sole Text-to-SQL generation endpoint. Thin: only
translates HTTP <-> the use case, no business logic here."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.schemas.generate import GenerateRequest, GenerateResponse
from app.application.use_cases.generate_sql import GenerateSqlUseCase
from app.dependencies import get_generate_sql_use_case
from app.domain.models import GenerationRequest

router = APIRouter(prefix="/api/v1", tags=["generate"])


@router.post("/generate", response_model=GenerateResponse)
async def generate(
    request: GenerateRequest,
    use_case: GenerateSqlUseCase = Depends(get_generate_sql_use_case),
) -> GenerateResponse:
    outcome = await use_case.execute(
        GenerationRequest(
            question=request.question,
            profile=request.profile,
            allowed_tables=request.allowed_tables,
        )
    )
    return GenerateResponse(
        outcome=outcome.outcome.value,
        sql=outcome.sql,
        intent_reformulation=outcome.intent_reformulation,
        judge_verdict=outcome.judge_verdict.value if outcome.judge_verdict else None,
        attempts=outcome.attempts,
        message=outcome.message,
    )
