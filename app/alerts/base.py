from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.db.models import Status


@dataclass(frozen=True)
class AlertEvent:
    target_id: uuid.UUID
    target_name: str
    url: str
    status: Status
    previous_status: Status | None
    incident_id: uuid.UUID | None
    checked_at: datetime
    started_at: datetime | None = None
    ended_at: datetime | None = None
    error: str | None = None


class AlertSender(Protocol):
    async def send(self, event: AlertEvent) -> None:  # pragma: no cover - interface
        ...
