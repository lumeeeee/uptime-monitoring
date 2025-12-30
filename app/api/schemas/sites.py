from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, HttpUrl


class SiteBase(BaseModel):
    name: str = Field(..., max_length=255)
    url: HttpUrl = Field(...)
    check_interval_sec: int = Field(..., ge=1)
    timeout_ms: int = Field(..., ge=1)
    retry_count: int = Field(..., ge=0)
    retry_backoff_ms: int = Field(..., ge=0)
    sla_target: int = Field(default=999, ge=0)
    is_active: bool = Field(default=True)


class SiteCreate(SiteBase):
    pass


class SiteUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    url: HttpUrl | None = None
    check_interval_sec: int | None = Field(default=None, ge=1)
    timeout_ms: int | None = Field(default=None, ge=1)
    retry_count: int | None = Field(default=None, ge=0)
    retry_backoff_ms: int | None = Field(default=None, ge=0)
    sla_target: int | None = Field(default=None, ge=0)
    is_active: bool | None = None


class SiteRead(SiteBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
