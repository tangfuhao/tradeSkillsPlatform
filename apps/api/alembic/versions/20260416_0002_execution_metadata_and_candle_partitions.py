"""Add execution metadata and partition-friendly candle storage.

Revision ID: 20260416_0002
Revises: 20260416_0001
Create Date: 2026-04-16 00:30:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260416_0002"
down_revision = "20260416_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "backtest_runs",
        sa.Column("revision", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )
    op.add_column("backtest_runs", sa.Column("claim_token", sa.String(length=64), nullable=True))
    op.add_column("backtest_runs", sa.Column("claim_owner", sa.String(length=128), nullable=True))
    op.add_column("backtest_runs", sa.Column("claim_acquired_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("backtest_runs", sa.Column("claim_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("backtest_runs", sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("backtest_runs", sa.Column("run_started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("backtest_runs", sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_backtest_run_status_claim", "backtest_runs", ["status", "claim_expires_at"])
    op.create_index("ix_backtest_run_claim_owner", "backtest_runs", ["claim_owner"])

    op.add_column(
        "live_tasks",
        sa.Column("revision", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )
    op.add_column("live_tasks", sa.Column("last_claimed_slot_as_of_ms", sa.BigInteger(), nullable=True))
    op.add_column("live_tasks", sa.Column("execution_claim_token", sa.String(length=64), nullable=True))
    op.add_column("live_tasks", sa.Column("execution_claim_owner", sa.String(length=128), nullable=True))
    op.add_column("live_tasks", sa.Column("execution_claimed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("live_tasks", sa.Column("execution_claim_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_live_task_status_claim", "live_tasks", ["status", "execution_claim_expires_at"])
    op.create_index("ix_live_task_claim_owner", "live_tasks", ["execution_claim_owner"])

    op.add_column("live_signals", sa.Column("execution_time_ms", sa.BigInteger(), nullable=True))
    op.add_column("live_signals", sa.Column("dispatch_as_of_ms", sa.BigInteger(), nullable=True))
    op.add_column(
        "live_signals",
        sa.Column("trigger_origin", sa.String(length=32), nullable=False, server_default=sa.text("'manual'")),
    )
    op.execute(
        """
        UPDATE live_signals
        SET execution_time_ms = COALESCE(
            NULLIF(signal_json ->> 'execution_time_ms', '')::bigint,
            FLOOR(EXTRACT(EPOCH FROM trigger_time) * 1000)::bigint
        )
        """
    )
    op.execute(
        """
        UPDATE live_signals
        SET dispatch_as_of_ms = NULLIF(signal_json #>> '{coverage,dispatch_as_of_ms}', '')::bigint
        """
    )
    op.execute(
        """
        UPDATE live_signals
        SET trigger_origin = COALESCE(NULLIF(signal_json ->> 'trigger_origin', ''), 'manual')
        """
    )
    op.execute(
        """
        DELETE FROM live_signals a
        USING (
            SELECT ctid,
                   row_number() OVER (
                       PARTITION BY live_task_id, execution_time_ms
                       ORDER BY created_at ASC, id ASC
                   ) AS row_rank
            FROM live_signals
        ) ranked
        WHERE a.ctid = ranked.ctid
          AND ranked.row_rank > 1
        """
    )
    op.alter_column("live_signals", "execution_time_ms", nullable=False)
    op.create_unique_constraint("uq_live_signal_task_slot", "live_signals", ["live_task_id", "execution_time_ms"])
    op.create_index("ix_live_signal_task_created", "live_signals", ["live_task_id", "created_at"])

    op.create_unique_constraint("uq_run_trace_run_index", "run_traces", ["run_id", "trace_index"])
    op.create_index("ix_run_trace_run_created", "run_traces", ["run_id", "created_at"])
    op.create_index("ix_portfolio_fill_created_at", "portfolio_fills", ["created_at"])

    op.execute("ALTER TABLE market_candles RENAME TO market_candles_heap")
    op.execute(
        """
        CREATE TABLE market_candles (
            exchange VARCHAR(16) NOT NULL,
            market_symbol VARCHAR(128) NOT NULL,
            base_symbol VARCHAR(64) NOT NULL,
            quote_asset VARCHAR(16) NOT NULL,
            instrument_type VARCHAR(16) NOT NULL,
            timeframe VARCHAR(16) NOT NULL,
            open_time_ms BIGINT NOT NULL,
            open DOUBLE PRECISION NOT NULL,
            high DOUBLE PRECISION NOT NULL,
            low DOUBLE PRECISION NOT NULL,
            close DOUBLE PRECISION NOT NULL,
            vol DOUBLE PRECISION NOT NULL,
            vol_ccy DOUBLE PRECISION,
            vol_quote DOUBLE PRECISION,
            confirm BOOLEAN NOT NULL,
            is_old_contract BOOLEAN NOT NULL,
            source VARCHAR(32) NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
            PRIMARY KEY (exchange, market_symbol, timeframe, open_time_ms)
        ) PARTITION BY RANGE (open_time_ms)
        """
    )
    op.execute("CREATE TABLE market_candles_default PARTITION OF market_candles DEFAULT")
    op.execute(
        """
        INSERT INTO market_candles (
            exchange,
            market_symbol,
            base_symbol,
            quote_asset,
            instrument_type,
            timeframe,
            open_time_ms,
            open,
            high,
            low,
            close,
            vol,
            vol_ccy,
            vol_quote,
            confirm,
            is_old_contract,
            source,
            created_at,
            updated_at
        )
        SELECT
            exchange,
            market_symbol,
            base_symbol,
            quote_asset,
            instrument_type,
            timeframe,
            open_time_ms,
            open,
            high,
            low,
            close,
            vol,
            vol_ccy,
            vol_quote,
            confirm,
            is_old_contract,
            source,
            created_at,
            updated_at
        FROM market_candles_heap
        ON CONFLICT DO NOTHING
        """
    )
    op.execute("DROP TABLE market_candles_heap CASCADE")
    op.create_index("ix_market_candle_partition_lookup", "market_candles", ["open_time_ms"])
    op.create_index("ix_market_candle_symbol_time", "market_candles", ["market_symbol", "timeframe", "open_time_ms"])
    op.create_index("ix_market_candle_base_time", "market_candles", ["base_symbol", "timeframe", "open_time_ms"])
    op.create_index("ix_market_candles_exchange", "market_candles", ["exchange"])
    op.create_index("ix_market_candles_market_symbol", "market_candles", ["market_symbol"])
    op.create_index("ix_market_candles_base_symbol", "market_candles", ["base_symbol"])
    op.create_index("ix_market_candles_open_time_ms", "market_candles", ["open_time_ms"])


def downgrade() -> None:
    op.drop_index("ix_market_candles_open_time_ms", table_name="market_candles")
    op.drop_index("ix_market_candles_base_symbol", table_name="market_candles")
    op.drop_index("ix_market_candles_market_symbol", table_name="market_candles")
    op.drop_index("ix_market_candles_exchange", table_name="market_candles")
    op.drop_index("ix_market_candle_base_time", table_name="market_candles")
    op.drop_index("ix_market_candle_symbol_time", table_name="market_candles")
    op.drop_index("ix_market_candle_partition_lookup", table_name="market_candles")
    op.execute(
        """
        CREATE TABLE market_candles_heap (
            id SERIAL PRIMARY KEY,
            exchange VARCHAR(16) NOT NULL,
            market_symbol VARCHAR(128) NOT NULL,
            base_symbol VARCHAR(64) NOT NULL,
            quote_asset VARCHAR(16) NOT NULL,
            instrument_type VARCHAR(16) NOT NULL,
            timeframe VARCHAR(16) NOT NULL,
            open_time_ms BIGINT NOT NULL,
            open DOUBLE PRECISION NOT NULL,
            high DOUBLE PRECISION NOT NULL,
            low DOUBLE PRECISION NOT NULL,
            close DOUBLE PRECISION NOT NULL,
            vol DOUBLE PRECISION NOT NULL,
            vol_ccy DOUBLE PRECISION,
            vol_quote DOUBLE PRECISION,
            confirm BOOLEAN NOT NULL,
            is_old_contract BOOLEAN NOT NULL,
            source VARCHAR(32) NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
            CONSTRAINT uq_market_candle UNIQUE (exchange, market_symbol, timeframe, open_time_ms)
        )
        """
    )
    op.execute(
        """
        INSERT INTO market_candles_heap (
            exchange,
            market_symbol,
            base_symbol,
            quote_asset,
            instrument_type,
            timeframe,
            open_time_ms,
            open,
            high,
            low,
            close,
            vol,
            vol_ccy,
            vol_quote,
            confirm,
            is_old_contract,
            source,
            created_at,
            updated_at
        )
        SELECT
            exchange,
            market_symbol,
            base_symbol,
            quote_asset,
            instrument_type,
            timeframe,
            open_time_ms,
            open,
            high,
            low,
            close,
            vol,
            vol_ccy,
            vol_quote,
            confirm,
            is_old_contract,
            source,
            created_at,
            updated_at
        FROM market_candles
        ORDER BY open_time_ms ASC
        """
    )
    op.execute("DROP TABLE market_candles CASCADE")
    op.execute("ALTER TABLE market_candles_heap RENAME TO market_candles")
    op.create_index("ix_market_candle_symbol_time", "market_candles", ["market_symbol", "timeframe", "open_time_ms"])
    op.create_index("ix_market_candle_base_time", "market_candles", ["base_symbol", "timeframe", "open_time_ms"])
    op.create_index("ix_market_candles_exchange", "market_candles", ["exchange"])
    op.create_index("ix_market_candles_market_symbol", "market_candles", ["market_symbol"])
    op.create_index("ix_market_candles_base_symbol", "market_candles", ["base_symbol"])
    op.create_index("ix_market_candles_open_time_ms", "market_candles", ["open_time_ms"])

    op.drop_index("ix_portfolio_fill_created_at", table_name="portfolio_fills")
    op.drop_index("ix_run_trace_run_created", table_name="run_traces")
    op.drop_constraint("uq_run_trace_run_index", "run_traces", type_="unique")

    op.drop_index("ix_live_signal_task_created", table_name="live_signals")
    op.drop_constraint("uq_live_signal_task_slot", "live_signals", type_="unique")
    op.drop_column("live_signals", "trigger_origin")
    op.drop_column("live_signals", "dispatch_as_of_ms")
    op.drop_column("live_signals", "execution_time_ms")

    op.drop_index("ix_live_task_claim_owner", table_name="live_tasks")
    op.drop_index("ix_live_task_status_claim", table_name="live_tasks")
    op.drop_column("live_tasks", "execution_claim_expires_at")
    op.drop_column("live_tasks", "execution_claimed_at")
    op.drop_column("live_tasks", "execution_claim_owner")
    op.drop_column("live_tasks", "execution_claim_token")
    op.drop_column("live_tasks", "last_claimed_slot_as_of_ms")
    op.drop_column("live_tasks", "revision")

    op.drop_index("ix_backtest_run_claim_owner", table_name="backtest_runs")
    op.drop_index("ix_backtest_run_status_claim", table_name="backtest_runs")
    op.drop_column("backtest_runs", "finished_at")
    op.drop_column("backtest_runs", "run_started_at")
    op.drop_column("backtest_runs", "last_heartbeat_at")
    op.drop_column("backtest_runs", "claim_expires_at")
    op.drop_column("backtest_runs", "claim_acquired_at")
    op.drop_column("backtest_runs", "claim_owner")
    op.drop_column("backtest_runs", "claim_token")
    op.drop_column("backtest_runs", "revision")
