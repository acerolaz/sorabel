"""FastAPI app factory for text2sql-ai."""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.routes.generate import router as generate_router
from app.api.routes.health import router as health_router
from app.dependencies import (
    get_business_rules,
    get_few_shot_examples,
    get_schema_repository,
)
from app.domain.errors import JudgeServiceError, LlmServiceError
from app.logging_config import configure_logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Fail fast at boot: load and validate the static schema and its two ingredient
    files once, so a malformed YAML file breaks the container start rather than every
    request."""
    configure_logging()
    get_schema_repository()
    get_business_rules()
    get_few_shot_examples()
    yield


app = FastAPI(title="text2sql-ai", lifespan=lifespan)
app.include_router(generate_router)
app.include_router(health_router)


def _error_response(status_code: int, error_code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error_code": error_code,
            "message": message,
            "correlation_id": str(uuid.uuid4()),
        },
    )


@app.exception_handler(LlmServiceError)
async def handle_llm_unavailable(request: Request, exc: LlmServiceError) -> JSONResponse:
    return _error_response(
        502,
        "LLM_UNAVAILABLE",
        "Le service de génération est temporairement indisponible.",
    )


@app.exception_handler(JudgeServiceError)
async def handle_judge_unavailable(request: Request, exc: JudgeServiceError) -> JSONResponse:
    return _error_response(
        502,
        "JUDGE_UNAVAILABLE",
        "Le service de vérification d'intention est temporairement indisponible.",
    )


@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    """Fallback so an unforeseen failure still honours the uniform error format of
    ../../.claude/rules/api-contracts.md instead of FastAPI's bare {"detail": ...}.
    The message stays generic: it must never confirm the existence of a resource."""
    logger.exception("text2sql_unexpected_error")
    return _error_response(
        500,
        "INTERNAL_ERROR",
        "Une erreur interne est survenue.",
    )
