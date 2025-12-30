from __future__ import annotations

from fastapi import FastAPI

from app.api.routers import health, incidents, metrics, sites, ui

app = FastAPI(title="Uptime Monitoring API")

app.include_router(sites.router)
app.include_router(incidents.router)
app.include_router(metrics.router)
app.include_router(ui.router)
app.include_router(health.router)
