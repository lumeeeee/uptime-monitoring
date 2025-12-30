from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.db.models import Status


class IncidentRead(BaseModel):
    id: uuid.UUID
    target_id: uuid.UUID
    start_ts: datetime
    end_ts: datetime | None
    last_status: Status
    resolved: bool

    class Config:
        from_attributes = True
