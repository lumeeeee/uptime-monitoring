from __future__ import annotations

import uuid
from datetime import datetime
from typing import Sequence

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Incident, Status


class IncidentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        target_id: uuid.UUID,
        start_ts: datetime,
        last_status: Status,
    ) -> Incident:
        incident = Incident(
            target_id=target_id,
            start_ts=start_ts,
            end_ts=None,
            last_status=last_status,
            resolved=False,
        )
        self.session.add(incident)
        await self.session.flush()
        return incident

    async def close(
        self,
        incident_id: uuid.UUID,
        *,
        end_ts: datetime,
        last_status: Status,
    ) -> Incident | None:
        incident = await self.session.get(Incident, incident_id)
        if incident is None:
            return None
        incident.end_ts = end_ts
        incident.last_status = last_status
        incident.resolved = True
        await self.session.flush()
        return incident

    async def get(self, incident_id: uuid.UUID) -> Incident | None:
        return await self.session.get(Incident, incident_id)

    async def get_open(self, target_id: uuid.UUID) -> Incident | None:
        return await self.session.scalar(
            select(Incident)
            .where(Incident.target_id == target_id, Incident.resolved.is_(False))
            .order_by(desc(Incident.start_ts))
            .limit(1)
        )

    async def list(
        self,
        target_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 100,
        desc_order: bool = True,
    ) -> Sequence[Incident]:
        order_clause = desc(Incident.start_ts) if desc_order else Incident.start_ts
        rows = await self.session.scalars(
            select(Incident)
            .where(Incident.target_id == target_id)
            .order_by(order_clause)
            .offset(offset)
            .limit(limit)
        )
        return list(rows)
