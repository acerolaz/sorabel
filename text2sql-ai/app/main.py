"""FastAPI app factory for text2sql-ai."""

from __future__ import annotations

import uuid

import openai
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.routes.generate import router as generate_router
from app.api.routes.health import router as health_router

app = FastAPI(title="text2sql-ai")
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


@app.exception_handler(openai.APIError)
async def handle_llm_unavailable(request: Request, exc: openai.APIError) -> JSONResponse:
    return _error_response(
        502,
        "LLM_UNAVAILABLE",
        "Le service de génération est temporairement indisponible.",
    )
