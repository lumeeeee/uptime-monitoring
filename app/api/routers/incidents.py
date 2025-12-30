from __future__ import annotations

import uuid
from typing import Sequence

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db_session
from app.api.schemas.incidents import IncidentRead
from app.services.incidents import IncidentService

router = APIRouter(prefix="/incidents", tags=["incidents"])


@router.get("/", response_model=Sequence[IncidentRead])
async def list_incidents(
    target_id: uuid.UUID = Query(...),
    offset: int = 0,
    limit: int = 100,
    session: AsyncSession = Depends(get_db_session),
) -> Sequence[IncidentRead]:
    service = IncidentService(session)
    return await service.list(target_id=target_id, offset=offset, limit=limit)


@router.get("/{incident_id}", response_model=IncidentRead)
async def get_incident(
    incident_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> IncidentRead:
    service = IncidentService(session)
    incident = await service.get(incident_id)
    if incident is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found")
    return incident
