"""initial schema

Revision ID: 0001_initial
Revises: 
Create Date: 2025-12-30
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


status_enum = sa.Enum("UP", "DOWN", name="status_enum")
notification_status_enum = sa.Enum(
    "QUEUED", "SENT", "FAILED", name="notification_status_enum"
)


def upgrade() -> None:
    status_enum.create(op.get_bind(), checkfirst=True)
    notification_status_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "targets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False, unique=True),
        sa.Column("check_interval_sec", sa.Integer(), nullable=False),
        sa.Column("timeout_ms", sa.Integer(), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("retry_backoff_ms", sa.Integer(), nullable=False),
        sa.Column("sla_target", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_targets_is_active", "targets", ["is_active"], unique=False)
    op.create_index("ix_targets_updated_at", "targets", ["updated_at"], unique=False)

    op.create_table(
        "check_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "target_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("targets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", status_enum, nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "checked_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_check_results_target_time",
        "check_results",
        ["target_id", "checked_at"],
        unique=False,
    )
    op.create_index(
        "ix_check_results_checked_at",
        "check_results",
        ["checked_at"],
        unique=False,
    )

    op.create_table(
        "incidents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "target_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("targets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("start_ts", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("end_ts", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_status", status_enum, nullable=False),
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_index(
        "ix_incidents_target_resolved",
        "incidents",
        ["target_id", "resolved"],
        unique=False,
    )
    op.create_index("ix_incidents_start_ts", "incidents", ["start_ts"], unique=False)
    op.create_index("ix_incidents_end_ts", "incidents", ["end_ts"], unique=False)
    op.create_index(
        "uq_incidents_open",
        "incidents",
        ["target_id"],
        unique=True,
        postgresql_where=sa.text("resolved = false"),
    )

    op.create_table(
        "notification_channels",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_notification_channels_type_active",
        "notification_channels",
        ["type", "is_active"],
        unique=False,
    )

    op.create_table(
        "notification_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "incident_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("incidents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "channel_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("notification_channels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", notification_status_enum, nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_notification_events_status",
        "notification_events",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_notification_events_channel",
        "notification_events",
        ["channel_id"],
        unique=False,
    )
    op.create_index(
        "ix_notification_events_incident",
        "notification_events",
        ["incident_id"],
        unique=False,
    )

    op.create_table(
        "scheduler_state",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "target_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("targets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("next_run_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.String(length=255), nullable=True),
        sa.Column("lease_expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.UniqueConstraint("target_id", name="uq_scheduler_state_target"),
    )
    op.create_index(
        "ix_scheduler_state_next_run_at",
        "scheduler_state",
        ["next_run_at"],
        unique=False,
    )
    op.create_index(
        "ix_scheduler_state_lease_expires_at",
        "scheduler_state",
        ["lease_expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_scheduler_state_lease_expires_at", table_name="scheduler_state")
    op.drop_index("ix_scheduler_state_next_run_at", table_name="scheduler_state")
    op.drop_table("scheduler_state")

    op.drop_index("ix_notification_events_incident", table_name="notification_events")
    op.drop_index("ix_notification_events_channel", table_name="notification_events")
    op.drop_index("ix_notification_events_status", table_name="notification_events")
    op.drop_table("notification_events")

    op.drop_index("ix_notification_channels_type_active", table_name="notification_channels")
    op.drop_table("notification_channels")

    op.drop_index("uq_incidents_open", table_name="incidents")
    op.drop_index("ix_incidents_end_ts", table_name="incidents")
    op.drop_index("ix_incidents_start_ts", table_name="incidents")
    op.drop_index("ix_incidents_target_resolved", table_name="incidents")
    op.drop_table("incidents")

    op.drop_index("ix_check_results_checked_at", table_name="check_results")
    op.drop_index("ix_check_results_target_time", table_name="check_results")
    op.drop_table("check_results")

    op.drop_index("ix_targets_updated_at", table_name="targets")
    op.drop_index("ix_targets_is_active", table_name="targets")
    op.drop_table("targets")

    notification_status_enum.drop(op.get_bind(), checkfirst=True)
    status_enum.drop(op.get_bind(), checkfirst=True)
