from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import HTMLResponse
from starlette.templating import Jinja2Templates

from app.api.dependencies import get_db_session
from app.services.incidents import IncidentService
from app.services.metrics import MetricsService
from app.services.sites import SiteService
from app.services.status_history import StatusHistoryService

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

    return templates.TemplateResponse(
        "site_detail.html",
        {
            "request": request,
            "site": site,
            "latest": latest,
            "metrics": metrics,
            "incidents": incidents,
        },
    )
