from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db_session

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(session: AsyncSession = Depends(get_db_session)) -> dict:
    await session.execute(select(1))
    return {"status": "ok"}
@router.get("/healthz", include_in_schema=False)
async def healthz() -> dict:
    """Lightweight liveness probe that does not touch external resources.

    Use this for container `HEALTHCHECK` so brief DB outages don't mark the
    container as unhealthy.
    """
    return {"status": "ok"}
