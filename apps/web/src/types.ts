export type SkillRuntimeMode = 'backtest' | 'live_signal' | string;
export type ExecutionAction =
  | 'pause'
  | 'resume'
  | 'stop'
  | 'delete'
  | 'trigger'
  | 'create_backtest'
  | 'create_live_task'
  | string;

export type SkillTrigger = {
  type?: string;
  value?: string;
  trigger_on?: 'bar_close' | 'wall_clock' | string;
  timezone?: string;
};

export type SkillToolContract = {
  required_tools?: string[];
  optional_tools?: string[];
};

export type SkillOutputContract = {
  schema?: string;
  required_fields?: string[];
};

export type SkillRiskContract = {
  max_position_pct?: number;
  requires_stop_loss?: boolean;
  max_daily_loss_pct?: number;
  max_concurrent_positions?: number;
  allow_hedging?: boolean;
};

export type SkillRuntimeProfile = {
  needs_market_scan?: boolean;
  needs_python_sandbox?: boolean;
};

export type ServicePulse = {
  name: string;
  status: string;
  details?: string;
};

export type SkillEnvelope = {
  schema_version?: string;
  runtime_modes?: SkillRuntimeMode[];
  trigger?: SkillTrigger;
  market_context?: Record<string, unknown>;
  tool_contract?: SkillToolContract;
  output_contract?: SkillOutputContract;
  risk_contract?: SkillRiskContract;
  state_contract?: Record<string, unknown>;
  runtime_profile?: SkillRuntimeProfile;
  extraction_meta?: {
    method?: 'rule_only' | 'llm_fallback';
    fallback_used?: boolean;
    provider?: string;
    reasoning_summary?: string;
    rule_failure_reasons?: string[];
  };
  extraction_notes?: string[];
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
  immutable: boolean;
  raw_text: string;
  available_actions: ExecutionAction[];
  active_live_task_id: string | null;
  created_at_ms: number;
  updated_at_ms: number;
};

export type ExecutionProgress = {
  total_steps: number;
  completed_steps: number;
  percent: number;
  last_processed_trace_index: number | null;
  last_processed_trigger_time_ms: number | null;
};

export type ExecutionTiming = {
  started_at_ms?: number | null;
  completed_at_ms?: number | null;
  duration_ms?: number | null;
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
  progress: ExecutionProgress;
  pending_action: string | null;
  available_actions: ExecutionAction[];
  last_activity_at_ms: number | null;
  summary: Record<string, unknown> | null;
  error_message: string | null;
  created_at_ms: number;
  updated_at_ms: number;
};

export type ToolCall = {
  tool_name: string;
  arguments: Record<string, unknown>;
  status: string;
  execution_timing?: ExecutionTiming | null;
};

export type PortfolioAccount = {
  initial_capital?: number;
  cash_balance?: number;
  equity?: number;
  realized_pnl?: number;
  unrealized_pnl?: number;
  total_return_pct?: number;
  last_mark_time_ms?: number | null;
};

export type PortfolioPosition = {
  symbol: string;
  direction: string;
  quantity: number;
  avg_entry_price: number;
  mark_price: number;
  position_notional: number;
  unrealized_pnl: number;
  unrealized_pnl_pct: number;
  stop_loss?: Record<string, unknown> | null;
  take_profit?: Record<string, unknown> | null;
  opened_at_ms?: number | null;
  updated_at_ms?: number | null;
};

export type PortfolioFill = {
  id: string;
  symbol: string;
  action: string;
  side: string;
  quantity: number;
  price: number;
  notional: number;
  realized_pnl: number;
  closed_trade_pnl?: number | null;
  closed_trade_win?: boolean | null;
  trigger_time_ms: number;
  trace_index?: number | null;
  execution_reference?: string;
};

export type PortfolioState = {
  scope_kind?: string;
  scope_id?: string;
  skill_id?: string;
  account?: PortfolioAccount;
  positions?: PortfolioPosition[];
  recent_fills?: PortfolioFill[];
};

export type BacktestTrace = {
  id: string;
  trace_index: number;
  trigger_time_ms: number;
  reasoning_summary: string;
  decision: Record<string, unknown>;
  execution_timing?: ExecutionTiming | null;
  tool_calls: ToolCall[];
  portfolio_before?: PortfolioState | null;
  portfolio_after?: PortfolioState | null;
  fills: PortfolioFill[];
};

export type LiveTask = {
  id: string;
  skill_id: string;
  status: string;
  cadence: string;
  cadence_seconds: number;
  available_actions: ExecutionAction[];
  last_activity_at_ms: number | null;
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
    execution_time_ms?: number | null;
    portfolio_before?: PortfolioState | null;
    portfolio_after?: PortfolioState | null;
    fills?: PortfolioFill[];
    [key: string]: unknown;
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

export type MarketCandle = {
  market_symbol: string;
  base_symbol: string;
  timeframe: string;
  open_time_ms: number;
  open: number;
  high: number;
  low: number;
  close: number;
  vol: number;
  vol_ccy?: number | null;
  vol_quote?: number | null;
  confirm: boolean;
  source: string;
};
