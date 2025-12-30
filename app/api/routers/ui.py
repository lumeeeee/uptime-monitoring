from __future__ import annotations

import uuid
import csv
import io
from datetime import timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import HTMLResponse, StreamingResponse
from starlette.templating import Jinja2Templates
from fpdf import FPDF

from app.api.dependencies import get_db_session
from app.services.incidents import IncidentService
from app.services.metrics import MetricsService
from app.services.sites import SiteService
from app.services.status_history import StatusHistoryService
from app.db.models import CheckResult, Status
from sqlalchemy import asc, desc, select

router = APIRouter(prefix="/ui", tags=["ui"])
templates = Jinja2Templates(directory="app/web/templates")


async def _collect_metrics(session: AsyncSession):
    site_service = SiteService(session)
    metrics_service = MetricsService(session)

    sites = await site_service.list(limit=500)
    labels: list[str] = []
    uptime_values: list[float] = []
    error_rates: list[float] = []
    latency_series: list[dict] = []
    rows: list[dict] = []

    for site in sites:
        labels.append(site.name)
        metrics = await metrics_service.uptime_window(site.id, window_hours=24)
        availability_pct = None
        if metrics.get("availability") is not None:
            availability_pct = (metrics.get("availability") or 0.0) * 100
        uptime_values.append(availability_pct or 0.0)

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
            error_rate = errors / len(checks) * 100
        else:
            error_rate = 0.0
        error_rates.append(error_rate)

        rows.append(
            {
                "name": site.name,
                "url": site.url,
                "availability_pct": availability_pct,
                "uptime_seconds": metrics.get("uptime_seconds"),
                "downtime_seconds": metrics.get("downtime_seconds"),
                "sla_target_pct": (metrics.get("sla_target_per_mille") / 10) if metrics.get("sla_target_per_mille") is not None else None,
                "sla_met": metrics.get("sla_met"),
                "error_rate_pct": error_rate,
            }
        )

    return {
        "labels": labels,
        "uptime_values": uptime_values,
        "error_rates": error_rates,
        "latency_series": latency_series,
        "rows": rows,
    }


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
    data = await _collect_metrics(session)

    return templates.TemplateResponse(
        "metrics.html",
        {
            "request": request,
            "labels": data["labels"],
            "uptime_values": data["uptime_values"],
            "error_rates": data["error_rates"],
            "latency_series": data["latency_series"],
        },
    )


@router.get("/metrics.csv")
async def metrics_csv(session: AsyncSession = Depends(get_db_session)) -> StreamingResponse:
    data = await _collect_metrics(session)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "name",
        "url",
        "availability_24h_pct",
        "uptime_seconds",
        "downtime_seconds",
        "sla_target_pct",
        "sla_met",
        "error_rate_pct",
    ])
    for row in data["rows"]:
        writer.writerow([
            row["name"],
            row["url"],
            f"{row['availability_pct']:.2f}" if row["availability_pct"] is not None else "",
            row.get("uptime_seconds", ""),
            row.get("downtime_seconds", ""),
            f"{row['sla_target_pct']:.1f}" if row.get("sla_target_pct") is not None else "",
            "yes" if row.get("sla_met") else "no",
            f"{row['error_rate_pct']:.2f}",
        ])
    output.seek(0)
    headers = {"Content-Disposition": "attachment; filename=metrics.csv"}
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers=headers)


@router.get("/metrics.pdf")
async def metrics_pdf(session: AsyncSession = Depends(get_db_session)) -> StreamingResponse:
    data = await _collect_metrics(session)

    pdf = FPDF(format='A4')
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font('Helvetica', 'B', 16)
    pdf.cell(0, 10, 'Отчет по метрикам', ln=1)
    pdf.ln(4)

    # Table header
    pdf.set_font('Helvetica', 'B', 10)
    col_widths = [40, 60, 24, 22, 22, 18, 14, 20]
    headers = ['Сайт', 'URL', 'Доступность 24ч %', 'Uptime (с)', 'Downtime (с)', 'SLA %', 'SLA', 'Ошибки %']
    pdf.set_fill_color(14, 165, 233)
    for w, h in zip(col_widths, headers):
        pdf.cell(w, 8, h, border=1, fill=True)
    pdf.ln()

    # Table rows
    pdf.set_font('Helvetica', '', 9)
    for row in data['rows']:
        vals = [
            str(row.get('name', ''))[:30],
            str(row.get('url', ''))[:60],
            f"{row['availability_pct']:.2f}" if row.get('availability_pct') is not None else '',
            str(row.get('uptime_seconds', '')),
            str(row.get('downtime_seconds', '')),
            f"{row['sla_target_pct']:.1f}" if row.get('sla_target_pct') is not None else '',
            'Да' if row.get('sla_met') else 'Нет',
            f"{row['error_rate_pct']:.2f}",
        ]
        for w, v in zip(col_widths, vals):
            pdf.multi_cell(w, 6, v, border=1, ln=3)
        pdf.ln()

    pdf_bytes = pdf.output(dest='S').encode('latin-1')
    buffer = io.BytesIO(pdf_bytes)
    headers = {"Content-Disposition": "attachment; filename=metrics.pdf"}
    return StreamingResponse(buffer, media_type="application/pdf", headers=headers)
