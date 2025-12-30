from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import joinedload, noload

from app.core.config import settings
from app.db.models import CheckResult, Incident, SchedulerState, Status, Target
from app.db.session import SessionLocal
from app.services.checker import CheckRequest, CheckResultDTO, Checker

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


@dataclass(frozen=True)
class TargetSnapshot:
    id: uuid.UUID
    url: str
    timeout_ms: int
    retry_count: int
    retry_backoff_ms: int
    check_interval_sec: int


@dataclass(frozen=True)
class TargetJob:
    scheduler_id: uuid.UUID
    target: TargetSnapshot


class MonitoringWorker:
    def __init__(
        self,
        session_factory: async_sessionmaker = SessionLocal,
        checker: Checker | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._checker = checker or Checker()
        self._worker_id = f"worker-{uuid.uuid4()}"
        self._semaphore = asyncio.Semaphore(settings.checker_concurrency)

    async def run_forever(self) -> None:
        await self._ensure_scheduler_entries()
        logger.info("worker started", extra={"worker_id": self._worker_id})

        while True:
            jobs = await self._acquire_jobs(limit=settings.fetch_batch_size)
            if not jobs:
                await asyncio.sleep(settings.poll_interval_sec)
                continue

            tasks = [asyncio.create_task(self._run_job(job)) for job in jobs]
            await asyncio.gather(*tasks)

    async def _ensure_scheduler_entries(self) -> None:
        now = datetime.now(timezone.utc)
        async with self._session_factory() as session:
            async with session.begin():
                targets = (await session.scalars(select(Target))).all()
                existing = set(
                    await session.scalars(select(SchedulerState.target_id))
                )
                for target in targets:
                    if target.id not in existing:
                        session.add(
                            SchedulerState(
                                target_id=target.id,
                                next_run_at=now,
                            )
                        )

    async def _acquire_jobs(self, limit: int) -> list[TargetJob]:
        now = datetime.now(timezone.utc)
        jobs: list[TargetJob] = []

        async with self._session_factory() as session:
            async with session.begin():
                # Use inner join and lock only scheduler_state rows to avoid FOR UPDATE on nullable side
                stmt = (
                    select(SchedulerState, Target)
                    .join(Target, SchedulerState.target_id == Target.id)
                    .where(
                        Target.is_active.is_(True),
                        SchedulerState.next_run_at <= now,
                        or_(
                            SchedulerState.lease_expires_at.is_(None),
                            SchedulerState.lease_expires_at <= now,
                        ),
                    )
                    .order_by(SchedulerState.next_run_at)
                    .limit(limit)
                    .with_for_update(of=SchedulerState, skip_locked=True)
                )

                rows: Iterable[tuple[SchedulerState, Target]] = (await session.execute(stmt)).all()

                lease_until = now + timedelta(seconds=settings.lease_timeout_sec)
                for state, target in rows:
                    state.lease_owner = self._worker_id
                    state.lease_expires_at = lease_until
                    jobs.append(
                        TargetJob(
                            scheduler_id=state.id,
                            target=TargetSnapshot(
                                id=target.id,
                                url=target.url,
                                timeout_ms=target.timeout_ms,
                                retry_count=target.retry_count,
                                retry_backoff_ms=target.retry_backoff_ms,
                                check_interval_sec=target.check_interval_sec,
                            ),
                        )
                    )
        return jobs

    async def _run_job(self, job: TargetJob) -> None:
        async with self._semaphore:
            try:
                result = await self._run_check(job.target)
                await self._persist_result(job.scheduler_id, result)
            except Exception:  # pragma: no cover - logging catch-all
                logger.exception("job failed", extra={"target_id": str(job.target.id)})

    async def _run_check(self, target: TargetSnapshot) -> CheckResultDTO:
        req = CheckRequest(
            target_id=str(target.id),
            url=target.url,
            timeout_ms=target.timeout_ms,
            retry_count=target.retry_count,
            retry_backoff_ms=target.retry_backoff_ms,
        )
        return await self._checker.check(req)

    async def _persist_result(self, scheduler_id: uuid.UUID, result: CheckResultDTO) -> None:
        async with self._session_factory() as session:
            async with session.begin():
                # Lock only the scheduler_state row. joinedload() causes an outer join
                # which combined with FOR UPDATE triggers asyncpg FeatureNotSupportedError.
                state = await session.scalar(
                    select(SchedulerState)
                    .where(SchedulerState.id == scheduler_id)
                    .with_for_update(of=SchedulerState, skip_locked=False)
                )
                if state is None:
                    return

                # Load the Target in a separate query (no FOR UPDATE on outer join)
                target = await session.get(Target, state.target_id)
                if target is None:
                    return
                check_row = CheckResult(
                    target_id=target.id,
                    status=result.status,
                    http_status=result.http_status,
                    latency_ms=result.latency_ms,
                    error=result.error,
                    checked_at=result.checked_at,
                )
                session.add(check_row)

                await self._update_incident(session, target.id, result)

                state.next_run_at = result.checked_at + timedelta(seconds=target.check_interval_sec)
                state.lease_owner = None
                state.lease_expires_at = None

    async def _update_incident(
        self, session: AsyncSession, target_id: uuid.UUID, result: CheckResultDTO
    ) -> None:
        open_incident = await session.scalar(
            select(Incident)
            .where(Incident.target_id == target_id, Incident.resolved.is_(False))
            .options(noload(Incident.target))
            .with_for_update(of=Incident, skip_locked=True)
        )

        if result.status == Status.DOWN:
            if open_incident is None:
                session.add(
                    Incident(
                        target_id=target_id,
                        start_ts=result.checked_at,
                        end_ts=None,
                        last_status=Status.DOWN,
                        resolved=False,
                    )
                )
            else:
                open_incident.last_status = Status.DOWN
        else:
            if open_incident is not None:
                open_incident.end_ts = result.checked_at
                open_incident.last_status = Status.UP
                open_incident.resolved = True


def main() -> None:
    worker = MonitoringWorker()
    asyncio.run(worker.run_forever())


if __name__ == "__main__":
    main()
