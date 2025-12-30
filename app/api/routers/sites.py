from __future__ import annotations

import uuid
from typing import Sequence

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db_session
from app.api.schemas.sites import SiteCreate, SiteRead, SiteUpdate
from app.services.sites import SiteService

router = APIRouter(prefix="/sites", tags=["sites"])


@router.get("/", response_model=Sequence[SiteRead])
async def list_sites(
    session: AsyncSession = Depends(get_db_session),
    offset: int = 0,
    limit: int = 100,
) -> Sequence[SiteRead]:
    service = SiteService(session)
    return await service.list(offset=offset, limit=limit)


@router.get("/{site_id}", response_model=SiteRead)
async def get_site(
    site_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> SiteRead:
    service = SiteService(session)
    site = await service.get(site_id)
    if site is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Site not found")
    return site


@router.post("/", response_model=SiteRead, status_code=status.HTTP_201_CREATED)
async def create_site(
    payload: SiteCreate,
    session: AsyncSession = Depends(get_db_session),
) -> SiteRead:
    service = SiteService(session)
    async with session.begin():
        site = await service.create(**payload.dict())
    return site


@router.patch("/{site_id}", response_model=SiteRead)
async def update_site(
    site_id: uuid.UUID,
    payload: SiteUpdate,
    session: AsyncSession = Depends(get_db_session),
) -> SiteRead:
    service = SiteService(session)
    async with session.begin():
        site = await service.update(site_id, **payload.dict(exclude_unset=True))
        if site is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Site not found")
    return site


@router.delete("/{site_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_site(
    site_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> None:
    service = SiteService(session)
    async with session.begin():
        deleted = await service.delete(site_id)
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Site not found")
    return None
