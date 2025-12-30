from __future__ import annotations

import uuid
import csv
import io
import os
import logging
from datetime import timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import HTMLResponse, StreamingResponse, FileResponse
from starlette.templating import Jinja2Templates
from fpdf import FPDF
import tempfile

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

    # Try to register a TTF font that supports Cyrillic (common locations)
    font_registered = False
    font_paths = [
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
        '/usr/share/fonts/dejavu/DejaVuSans.ttf',
        'C:\\Windows\\Fonts\\DejaVuSans.ttf',
        'C:\\Windows\\Fonts\\arial.ttf',
    ]
    for p in font_paths:
        if os.path.exists(p):
            try:
                pdf.add_font('DejaVu', '', p, uni=True)
                pdf.set_font('DejaVu', '', 12)
                font_registered = True
                break
            except Exception:
                logging.exception('Failed to register font %s', p)

    # If no font capable of Cyrillic was found, fall back to an ASCII-safe layout
    if font_registered:
        title_text = 'Отчет по метрикам'
        header_labels = ['Сайт', 'URL', 'Доступность 24ч %', 'Uptime (с)', 'Downtime (с)', 'SLA %', 'SLA', 'Ошибки %']
    else:
        pdf.set_font('Helvetica', 'B', 16)
        title_text = 'Metrics Report'
        header_labels = ['Site', 'URL', 'Availability 24h %', 'Uptime (s)', 'Downtime (s)', 'SLA %', 'SLA', 'Errors %']

    # Title
    font_name = 'DejaVu' if font_registered else 'Helvetica'
    pdf.set_font(font_name, 'B', 16)
    pdf.cell(0, 10, title_text, ln=1)
    pdf.ln(4)

    # Table header
    pdf.set_font(font_name, 'B', 10)
    col_widths = [40, 60, 24, 22, 22, 18, 14, 20]
    pdf.set_fill_color(14, 165, 233)
    for w, label in zip(col_widths, header_labels):
        pdf.cell(w, 8, label, border=1, fill=True)
    pdf.ln()

    # Table rows (simple, no wrapping to avoid API differences)
    pdf.set_font(font_name, '', 9)
    for row in data['rows']:
        vals = [
            str(row.get('name', ''))[:40],
            str(row.get('url', ''))[:80],
            f"{row['availability_pct']:.2f}" if row.get('availability_pct') is not None else '',
            str(row.get('uptime_seconds', '')),
            str(row.get('downtime_seconds', '')),
            f"{row['sla_target_pct']:.1f}" if row.get('sla_target_pct') is not None else '',
            ('Да' if row.get('sla_met') else 'Нет') if font_registered else ('Yes' if row.get('sla_met') else 'No'),
            f"{row['error_rate_pct']:.2f}",
        ]
        for w, v in zip(col_widths, vals):
            text = v if isinstance(v, str) else str(v)
            # truncate to avoid overflow
            pdf.cell(w, 8, text[:int(w * 2)], border=1)
        pdf.ln()

    try:
        pdf_output = pdf.output(dest='S')
        # fpdf2 may return `bytes`, `bytearray` or `str` depending on version
        if isinstance(pdf_output, (bytes, bytearray)):
            pdf_bytes = bytes(pdf_output)
        else:
            pdf_bytes = str(pdf_output).encode('latin-1', errors='replace')
    except Exception:
        logging.exception('Failed to generate PDF output')
        raise HTTPException(status_code=500, detail='Failed to generate PDF')

    # Write to a temporary file and return using FileResponse to ensure correct binary transfer
    try:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.pdf')
        tmp_name = tmp.name
        tmp.close()
        with open(tmp_name, 'wb') as f:
            f.write(pdf_bytes)
        return FileResponse(tmp_name, media_type='application/pdf', filename='metrics.pdf')
    except Exception:
        logging.exception('Failed to write temporary PDF file')
        raise HTTPException(status_code=500, detail='Failed to generate PDF')
