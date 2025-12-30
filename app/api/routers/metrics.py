from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db_session
from app.api.schemas.metrics import UptimeMetrics
from app.services.metrics import MetricsService

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("/uptime", response_model=UptimeMetrics)
async def get_uptime_metrics(
    target_id: uuid.UUID = Query(...),
    window_hours: int = Query(24, ge=1, le=24 * 30),
    session: AsyncSession = Depends(get_db_session),
) -> UptimeMetrics:
    service = MetricsService(session)
    data = await service.uptime_window(target_id=target_id, window_hours=window_hours)
    return UptimeMetrics(**data)
