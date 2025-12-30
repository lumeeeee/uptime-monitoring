from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import HTMLResponse
from starlette.templating import Jinja2Templates

from app.api.dependencies import get_db_session
from app.services.incidents import IncidentService
from datetime import timezone, timedelta
from app.services.metrics import MetricsService
from app.services.sites import SiteService
from app.services.status_history import StatusHistoryService
from app.db.models import CheckResult, Status
from sqlalchemy import asc, desc, select

router = APIRouter(prefix="/ui", tags=["ui"])
templates = Jinja2Templates(directory="app/web/templates")


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, session: AsyncSession = Depends(get_db_session)) -> HTMLResponse:
    site_service = SiteService(session)
    history_service = StatusHistoryService(session)
    metrics_service = MetricsService(session)

    sites = await site_service.list(limit=500)
    items = []
    for site in sites:
        latest = await history_service.latest(site.id)
        metrics = await metrics_service.uptime_window(site.id, window_hours=24)
        items.append({
            "site": site,
            "latest": latest,
            "metrics": metrics,
        })

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "items": items,
        },
    )


@router.get("/sites/{site_id}", response_class=HTMLResponse)
async def site_detail(
    site_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    site_service = SiteService(session)
    history_service = StatusHistoryService(session)
    metrics_service = MetricsService(session)
    incident_service = IncidentService(session)

    site = await site_service.get(site_id)
    if site is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Site not found")

    latest = await history_service.latest(site_id)
    metrics = await metrics_service.uptime_window(site_id, window_hours=24)
    incidents = await incident_service.list(site_id, limit=100)

    # format incident timestamps to human-readable strings in UTC+3
    tz_msk = timezone(timedelta(hours=3))
    incidents_serialized = []
    for inc in incidents:
        start_ts = inc.start_ts.astimezone(tz_msk).strftime("%d.%m.%Y %H:%M:%S") if inc.start_ts is not None else None
        end_ts = inc.end_ts.astimezone(tz_msk).strftime("%d.%m.%Y %H:%M:%S") if inc.end_ts is not None else None
        incidents_serialized.append({
            "id": inc.id,
            "start_ts": start_ts,
            "end_ts": end_ts,
            "last_status": inc.last_status.value,
            "resolved": inc.resolved,
        })

    return templates.TemplateResponse(
        "site_detail.html",
        {
            "request": request,
            "site": site,
            "latest": latest,
            "metrics": metrics,
            "incidents": incidents_serialized,
        },
    )


@router.get("/metrics", response_class=HTMLResponse)
async def metrics_page(request: Request, session: AsyncSession = Depends(get_db_session)) -> HTMLResponse:
    site_service = SiteService(session)
    metrics_service = MetricsService(session)

    sites = await site_service.list(limit=500)
    labels: list[str] = []
    uptime_values: list[float] = []
    error_rates: list[float] = []
    # collect per-site uptime (24h)
    for site in sites:
        labels.append(site.name)
        m = await metrics_service.uptime_window(site.id, window_hours=24)
        uptime_values.append((m.get("availability") or 0.0) * 100 if m.get("availability") is not None else 0.0)

    # build latency series per site (up to 100 points each)
    latency_series: list[dict] = []
    for site in sites:
        r = await session.scalars(
            select(CheckResult)
            .where(CheckResult.target_id == site.id)
            .order_by(asc(CheckResult.checked_at))
            .limit(100)
        )
        checks = list(r)
        latency_series.append(
            {
                "site_id": str(site.id),
                "site_name": site.name,
                "labels": [c.checked_at.isoformat() for c in checks],
                "values": [c.latency_ms or 0.0 for c in checks],
                "statuses": [c.status.value for c in checks],
            }
        )
        if checks:
            errors = sum(1 for c in checks if c.status != Status.UP)
            error_rates.append(errors / len(checks) * 100)
        else:
            error_rates.append(0.0)

    return templates.TemplateResponse(
        "metrics.html",
        {
            "request": request,
            "labels": labels,
            "uptime_values": uptime_values,
            "error_rates": error_rates,
            "latency_series": latency_series,
        },
    )
