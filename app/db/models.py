from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Status(str, enum.Enum):
    UP = "UP"
    DOWN = "DOWN"


class NotificationStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    SENT = "SENT"
    FAILED = "FAILED"


class Target(Base):
    __tablename__ = "targets"
    __table_args__ = (
        Index("ix_targets_is_active", "is_active"),
        Index("ix_targets_updated_at", "updated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False, unique=True)
    check_interval_sec: Mapped[int] = mapped_column(Integer, nullable=False)
    timeout_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=5000)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    retry_backoff_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=500)
    sla_target: Mapped[int] = mapped_column(Integer, nullable=False, default=999)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    check_results: Mapped[list["CheckResult"]] = relationship(
        back_populates="target",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    incidents: Mapped[list["Incident"]] = relationship(
        back_populates="target",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    scheduler_state: Mapped["SchedulerState | None"] = relationship(
        back_populates="target",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class CheckResult(Base):
    __tablename__ = "check_results"
    __table_args__ = (
        Index("ix_check_results_target_time", "target_id", "checked_at"),
        Index("ix_check_results_checked_at", "checked_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    target_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("targets.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[Status] = mapped_column(Enum(Status, name="status_enum"), nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    checked_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    target: Mapped[Target] = relationship(back_populates="check_results", lazy="joined")


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    target_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("targets.id", ondelete="CASCADE"),
        nullable=False,
    )
    start_ts: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    end_ts: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    last_status: Mapped[Status] = mapped_column(Enum(Status, name="status_enum"), nullable=False)
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    target: Mapped[Target] = relationship(back_populates="incidents", lazy="joined")
    notification_events: Mapped[list["NotificationEvent"]] = relationship(
        back_populates="incident",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        Index("ix_incidents_target_resolved", "target_id", "resolved"),
        Index("ix_incidents_start_ts", "start_ts"),
        Index("ix_incidents_end_ts", "end_ts"),
        Index(
            "uq_incidents_open",
            "target_id",
            unique=True,
            postgresql_where=(resolved.is_(False)),
        ),
    )


class NotificationChannel(Base):
    __tablename__ = "notification_channels"
    __table_args__ = (
        Index("ix_notification_channels_type_active", "type", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    notification_events: Mapped[list["NotificationEvent"]] = relationship(
        back_populates="channel",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class NotificationEvent(Base):
    __tablename__ = "notification_events"
    __table_args__ = (
        Index("ix_notification_events_status", "status"),
        Index("ix_notification_events_channel", "channel_id"),
        Index("ix_notification_events_incident", "incident_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    incident_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("incidents.id", ondelete="CASCADE"),
        nullable=False,
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("notification_channels.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[NotificationStatus] = mapped_column(
        Enum(NotificationStatus, name="notification_status_enum"),
        nullable=False,
    )
    error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    incident: Mapped[Incident] = relationship(back_populates="notification_events", lazy="joined")
    channel: Mapped[NotificationChannel] = relationship(back_populates="notification_events", lazy="joined")


class SchedulerState(Base):
    __tablename__ = "scheduler_state"
    __table_args__ = (
        UniqueConstraint("target_id", name="uq_scheduler_state_target"),
        Index("ix_scheduler_state_next_run_at", "next_run_at"),
        Index("ix_scheduler_state_lease_expires_at", "lease_expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    target_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("targets.id", ondelete="CASCADE"),
        nullable=False,
    )
    next_run_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(255))
    lease_expires_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

    target: Mapped[Target] = relationship(back_populates="scheduler_state", lazy="joined")
