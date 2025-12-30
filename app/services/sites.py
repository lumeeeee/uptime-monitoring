from __future__ import annotations

import uuid
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Target


class SiteService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        name: str,
        url: str,
        check_interval_sec: int,
        timeout_ms: int,
        retry_count: int,
        retry_backoff_ms: int,
        sla_target: int = 999,
        is_active: bool = True,
    ) -> Target:
        target = Target(
            name=name,
            url=url,
            check_interval_sec=check_interval_sec,
            timeout_ms=timeout_ms,
            retry_count=retry_count,
            retry_backoff_ms=retry_backoff_ms,
            sla_target=sla_target,
            is_active=is_active,
        )
        self.session.add(target)
        await self.session.flush()
        return target

    async def get(self, target_id: uuid.UUID) -> Target | None:
        return await self.session.get(Target, target_id)

    async def list(self, *, offset: int = 0, limit: int = 100) -> Sequence[Target]:
        rows = await self.session.scalars(
            select(Target)
            .order_by(Target.created_at)
            .offset(offset)
            .limit(limit)
        )
        return list(rows)

    async def list_active(self, *, limit: int = 1000) -> Sequence[Target]:
        rows = await self.session.scalars(
            select(Target)
            .where(Target.is_active.is_(True))
            .order_by(Target.updated_at.desc())
            .limit(limit)
        )
        return list(rows)

    async def update(
        self,
        target_id: uuid.UUID,
        *,
        name: str | None = None,
        url: str | None = None,
        check_interval_sec: int | None = None,
        timeout_ms: int | None = None,
        retry_count: int | None = None,
        retry_backoff_ms: int | None = None,
        sla_target: int | None = None,
        is_active: bool | None = None,
    ) -> Target | None:
        target = await self.session.get(Target, target_id)
        if target is None:
            return None

        if name is not None:
            target.name = name
        if url is not None:
            target.url = url
        if check_interval_sec is not None:
            target.check_interval_sec = check_interval_sec
        if timeout_ms is not None:
            target.timeout_ms = timeout_ms
        if retry_count is not None:
            target.retry_count = retry_count
        if retry_backoff_ms is not None:
            target.retry_backoff_ms = retry_backoff_ms
        if sla_target is not None:
            target.sla_target = sla_target
        if is_active is not None:
            target.is_active = is_active

        await self.session.flush()
        return target

    async def delete(self, target_id: uuid.UUID) -> bool:
        target = await self.session.get(Target, target_id)
        if target is None:
            return False
        await self.session.delete(target)
        await self.session.flush()
        return True
