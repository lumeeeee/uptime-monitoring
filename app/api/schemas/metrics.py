from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class UptimeMetrics(BaseModel):
    target_id: uuid.UUID
    window_hours: int = Field(..., ge=1)
    uptime_seconds: float
    downtime_seconds: float
    availability: float | None  # in [0,1]
    sample_count: int
    from_ts: datetime
    to_ts: datetime
    sla_target_per_mille: int | None = Field(default=None, ge=0, le=1000)
    sla_met: bool | None

    class Config:
        orm_mode = True
