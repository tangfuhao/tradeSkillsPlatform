"""Add explicit CSV ingest backlog fields.

Revision ID: 20260416_0003
Revises: 20260416_0002
Create Date: 2026-04-16 16:40:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260416_0003"
down_revision = "20260416_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "csv_ingestion_jobs",
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.add_column("csv_ingestion_jobs", sa.Column("runner_id", sa.String(length=128), nullable=True))
    op.add_column(
        "csv_ingestion_jobs",
        sa.Column("rows_staged", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.execute(
        """
        UPDATE csv_ingestion_jobs
        SET requested_at = COALESCE(started_at, completed_at, CURRENT_TIMESTAMP),
            rows_staged = GREATEST(rows_seen - rows_filtered, 0)
        """
    )
    op.alter_column("csv_ingestion_jobs", "requested_at", nullable=False)
    op.alter_column("csv_ingestion_jobs", "started_at", nullable=True)
    op.create_index("ix_csv_ingestion_job_requested", "csv_ingestion_jobs", ["requested_at"])


def downgrade() -> None:
    op.drop_index("ix_csv_ingestion_job_requested", table_name="csv_ingestion_jobs")
    op.alter_column("csv_ingestion_jobs", "started_at", nullable=False)
    op.drop_column("csv_ingestion_jobs", "rows_staged")
    op.drop_column("csv_ingestion_jobs", "runner_id")
    op.drop_column("csv_ingestion_jobs", "requested_at")
