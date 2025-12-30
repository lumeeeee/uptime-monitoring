from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import asc, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CheckResult, Status, Target


class MetricsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def uptime_window(
        self,
        target_id: uuid.UUID,
        *,
        window_hours: int = 24,
        sla_target_per_mille: int | None = None,
        assume_unknown_as_down: bool = True,
    ) -> dict:
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(hours=window_hours)

        if sla_target_per_mille is None:
            sla_target_per_mille = await self._get_sla_target(target_id)

        # Last known status before window_start to set baseline
        previous = await self.session.scalar(
            select(CheckResult)
            .where(CheckResult.target_id == target_id, CheckResult.checked_at < window_start)
            .order_by(desc(CheckResult.checked_at))
            .limit(1)
        )

        rows = await self.session.scalars(
            select(CheckResult)
            .where(CheckResult.target_id == target_id, CheckResult.checked_at >= window_start)
            .order_by(asc(CheckResult.checked_at))
        )
        checks = list(rows)
        sample_count = len(checks)

        if previous is None and not assume_unknown_as_down and not checks:
            return {
                "target_id": target_id,
                "window_hours": window_hours,
                "uptime_seconds": 0.0,
                "downtime_seconds": 0.0,
                "availability": None,
                "sample_count": 0,
                "from_ts": window_start,
                "to_ts": now,
                "sla_target_per_mille": sla_target_per_mille,
                "sla_met": None,
            }

        current_status = previous.status if previous else (Status.DOWN if assume_unknown_as_down else Status.UP)
        current_ts = window_start
        uptime_seconds = 0.0
        downtime_seconds = 0.0

        for check in checks:
            if check.checked_at < current_ts:
                continue
            delta = (check.checked_at - current_ts).total_seconds()
            if delta > 0:
                if current_status == Status.UP:
                    uptime_seconds += delta
                else:
                    downtime_seconds += delta
            current_status = check.status
            current_ts = check.checked_at

        tail = (now - current_ts).total_seconds()
        if tail > 0:
            if current_status == Status.UP:
                uptime_seconds += tail
            else:
                downtime_seconds += tail

        total = uptime_seconds + downtime_seconds
        availability = uptime_seconds / total if total > 0 else None

        sla_met = None
        if sla_target_per_mille is not None and availability is not None:
            sla_met = availability >= (sla_target_per_mille / 1000)

        return {
            "target_id": target_id,
            "window_hours": window_hours,
            "uptime_seconds": uptime_seconds,
            "downtime_seconds": downtime_seconds,
            "availability": availability,
            "sample_count": sample_count,
            "from_ts": window_start,
            "to_ts": now,
            "sla_target_per_mille": sla_target_per_mille,
            "sla_met": sla_met,
        }

    async def _get_sla_target(self, target_id: uuid.UUID) -> int | None:
        return await self.session.scalar(
            select(Target.sla_target).where(Target.id == target_id)
        )
