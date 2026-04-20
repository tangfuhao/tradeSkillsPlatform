"""Add persisted market overview state and coverage index.

Revision ID: 20260420_0004
Revises: 20260416_0003
Create Date: 2026-04-20 10:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260420_0004"
down_revision = "20260416_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "market_overview_states",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("timeframe", sa.String(length=16), nullable=False),
        sa.Column("total_candles_estimate", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("total_symbols", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("coverage_start_ms", sa.BigInteger(), nullable=True),
        sa.Column("coverage_end_ms", sa.BigInteger(), nullable=True),
        sa.Column("coverage_ranges_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("bootstrap_pending_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("backfill_lag_symbol_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("tier1_freshness_ms_p95", sa.BigInteger(), nullable=True),
        sa.Column("tier2_freshness_ms_p95", sa.BigInteger(), nullable=True),
        sa.Column("failed_sync_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("skipped_sync_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("ingest_backlog_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("recent_csv_jobs_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("source_snapshot_id", sa.String(length=32), nullable=True),
        sa.Column("rebuilt_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("timeframe", name="uq_market_overview_state_timeframe"),
    )
    op.create_index("ix_market_overview_state_rebuilt", "market_overview_states", ["rebuilt_at"])
    op.create_index("ix_market_candle_timeframe_open_time", "market_candles", ["timeframe", "open_time_ms"])


def downgrade() -> None:
    op.drop_index("ix_market_candle_timeframe_open_time", table_name="market_candles")
    op.drop_index("ix_market_overview_state_rebuilt", table_name="market_overview_states")
    op.drop_table("market_overview_states")
