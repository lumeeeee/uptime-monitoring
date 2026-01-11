from __future__ import annotations

from fastapi import FastAPI, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routers import health, incidents, metrics, sites, ui, admin
from app.api.routers.telegram import router as telegram_router
from app.api.dependencies import get_db_session
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="Uptime Monitoring API")

# Serve project static files (fonts, images, etc.) mounted at /static
app.mount("/static", StaticFiles(directory="app/web/static"), name="static")

app.include_router(sites.router)
app.include_router(incidents.router)
app.include_router(metrics.router)
app.include_router(ui.router)
app.include_router(admin.router)
app.include_router(health.router)
app.include_router(telegram_router)


@app.get("/", include_in_schema=False)
async def root(request: Request, session: AsyncSession = Depends(get_db_session)):
	"""Serve dashboard at site root by delegating to the UI dashboard handler."""
	return await ui.dashboard(request, session)
