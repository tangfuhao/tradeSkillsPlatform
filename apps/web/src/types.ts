export type ServicePulse = {
  name: string;
  status: string;
  details?: string;
};

export type ReviewStatus =
  | 'preview_ready'
  | 'review_pending'
  | 'approved_full_window'
  | 'review_rejected';

export type SkillEnvelope = {
  trigger?: {
    value?: string;
  };
  tool_contract?: {
    required_tools?: string[];
  };
  risk_contract?: {
    max_position_pct?: number;
  };
};

export type Skill = {
  id: string;
  title: string;
  validation_status: string;
  review_status: ReviewStatus;
  source_hash: string;
  envelope: SkillEnvelope;
  preview_window: {
    start: string;
    end: string;
  };
  created_at: string;
  updated_at: string;
};

export type BacktestRun = {
  id: string;
  skill_id: string;
  status: string;
  scope: string;
  benchmark_name: string;
  start_time: string;
  end_time: string;
  initial_capital: number;
  summary: Record<string, unknown> | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
};

export type ToolCall = {
  tool_name: string;
  arguments: Record<string, unknown>;
  status: string;
};

export type BacktestTrace = {
  id: string;
  trace_index: number;
  trigger_time: string;
  reasoning_summary: string;
  decision: Record<string, unknown>;
  tool_calls: ToolCall[];
};

export type LiveTask = {
  id: string;
  skill_id: string;
  status: string;
  cadence: string;
  cadence_seconds: number;
  last_triggered_at: string | null;
  created_at: string;
  updated_at: string;
};

export type LiveSignal = {
  id: string;
  live_task_id: string;
  trigger_time: string;
  delivery_status: string;
  created_at: string;
  signal: {
    action?: string;
    symbol?: string | null;
    direction?: string | null;
    size_pct?: number;
    reason?: string;
    reasoning_summary?: string;
    provider?: string;
  };
};

export type CsvIngestionJob = {
  id: string;
  source_path: string;
  status: string;
  rows_seen: number;
  rows_inserted: number;
  rows_filtered: number;
  coverage_start: string | null;
  coverage_end: string | null;
  completed_at: string | null;
  error_message: string | null;
};

export type MarketSyncCursor = {
  base_symbol: string;
  timeframe: string;
  status: string;
  last_synced_open_time_ms: number | null;
  last_synced_open_time: string | null;
  last_sync_completed_at: string | null;
  notes: Record<string, unknown>;
};

export type MarketOverview = {
  historical_data_dir: string;
  base_timeframe: string;
  total_candles: number;
  total_symbols: number;
  coverage_start: string | null;
  coverage_end: string | null;
  recent_csv_jobs: CsvIngestionJob[];
  sync_cursors: MarketSyncCursor[];
};
