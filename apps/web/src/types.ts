export type ServicePulse = {
  name: string;
  status: string;
  details?: string;
};

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
  extraction_meta?: {
    method?: 'rule_only' | 'llm_fallback';
    fallback_used?: boolean;
    provider?: string;
    reasoning_summary?: string;
    rule_failure_reasons?: string[];
  };
};

export type Skill = {
  id: string;
  title: string;
  validation_status: string;
  source_hash: string;
  envelope: SkillEnvelope;
  extraction_method: 'rule_only' | 'llm_fallback';
  fallback_used: boolean;
  validation_errors: string[];
  validation_warnings: string[];
  created_at_ms: number;
  updated_at_ms: number;
};

export type BacktestRun = {
  id: string;
  skill_id: string;
  status: string;
  scope: string;
  benchmark_name: string;
  start_time_ms: number;
  end_time_ms: number;
  initial_capital: number;
  summary: Record<string, unknown> | null;
  error_message: string | null;
  created_at_ms: number;
  updated_at_ms: number;
};

export type ToolCall = {
  tool_name: string;
  arguments: Record<string, unknown>;
  status: string;
};

export type BacktestTrace = {
  id: string;
  trace_index: number;
  trigger_time_ms: number;
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
  last_triggered_at_ms: number | null;
  created_at_ms: number;
  updated_at_ms: number;
};

export type LiveSignal = {
  id: string;
  live_task_id: string;
  trigger_time_ms: number;
  delivery_status: string;
  created_at_ms: number;
  signal: {
    action?: string;
    symbol?: string | null;
    direction?: string | null;
    size_pct?: number;
    reason?: string;
    reasoning_summary?: string;
    provider?: string;
    error_message?: string;
  };
};

export type CsvIngestionJob = {
  id: string;
  source_path: string;
  status: string;
  rows_seen: number;
  rows_inserted: number;
  rows_filtered: number;
  coverage_start_ms: number | null;
  coverage_end_ms: number | null;
  completed_at_ms: number | null;
  error_message: string | null;
};

export type MarketSyncCursor = {
  base_symbol: string;
  timeframe: string;
  status: string;
  last_synced_open_time_ms: number | null;
  last_sync_completed_at_ms: number | null;
  notes: Record<string, unknown>;
};

export type MarketOverview = {
  historical_data_dir: string;
  base_timeframe: string;
  total_candles: number;
  total_symbols: number;
  coverage_start_ms: number | null;
  coverage_end_ms: number | null;
  recent_csv_jobs: CsvIngestionJob[];
  sync_cursors: MarketSyncCursor[];
};
