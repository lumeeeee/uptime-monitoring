from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timezone

from app.api.dependencies import get_db_session
from app.db.models import CheckResult
from app.core.config import settings

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


@router.get("/worker-status")
async def worker_status(session: AsyncSession = Depends(get_db_session)) -> dict:
    """Return a simple worker liveness indicator based on the most recent
    check result timestamp. This is a heuristic: if the latest `check_results`
    row is recent enough we consider the worker online.
    """
    last = await session.scalar(select(func.max(CheckResult.checked_at)))
    if last is None:
        return {"status": "offline", "last_check": None, "seconds_since": None}

    now = datetime.now(timezone.utc)
    # seconds since last check
    seconds = (now - last).total_seconds()
    # consider online if we saw a check recently; use a conservative threshold
    threshold = max(30, settings.poll_interval_sec * 10)
    return {
        "status": "online" if seconds <= threshold else "offline",
        "last_check": last.isoformat(),
        "seconds_since": seconds,
        "threshold_seconds": threshold,
    }
