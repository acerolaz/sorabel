"""GET /api/v1/health — container healthcheck. No dependencies to probe (this
service has no database)."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1", tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
