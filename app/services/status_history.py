from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Sequence

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CheckResult, Status


class StatusHistoryService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(
        self,
        *,
        target_id: uuid.UUID,
        status: Status,
        http_status: int | None,
        latency_ms: int | None,
        error: str | None,
        checked_at: datetime | None = None,
    ) -> CheckResult:
        row = CheckResult(
            target_id=target_id,
            status=status,
            http_status=http_status,
            latency_ms=latency_ms,
            error=error,
            checked_at=checked_at or datetime.now(timezone.utc),
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def latest(self, target_id: uuid.UUID) -> CheckResult | None:
        row = await self.session.scalar(
            select(CheckResult)
            .where(CheckResult.target_id == target_id)
            .order_by(desc(CheckResult.checked_at))
            .limit(1)
        )
        return row

    async def list(
        self,
        target_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 200,
        desc_order: bool = True,
    ) -> Sequence[CheckResult]:
        order_clause = desc(CheckResult.checked_at) if desc_order else CheckResult.checked_at
        rows = await self.session.scalars(
            select(CheckResult)
            .where(CheckResult.target_id == target_id)
            .order_by(order_clause)
            .offset(offset)
            .limit(limit)
        )
        return list(rows)
