import type { LiveSignal, Skill, ToolCall } from '../types';

export const LOCALE = 'zh-CN';

const generalStatusLabels: Record<string, string> = {
  ok: '正常',
  healthy: '正常',
  queued: '排队中',
  running: '运行中',
  paused: '已暂停',
  stopping: '停止中',
  stopped: '已停止',
  completed: '已完成',
  failed: '失败',
  active: '已激活',
  stored: '已存储',
  pending: '待处理',
  passed: '已通过',
  validation_failed: '验证失败',
  degraded: '降级',
  skipped: '已跳过',
  not_available: '暂不可用',
};

const actionLabels: Record<string, string> = {
  skip: '跳过',
  watch: '观察',
  open_position: '开仓',
  close_position: '平仓',
  reduce_position: '减仓',
  hold: '持有',
};

const directionLabels: Record<string, string> = {
  long: '做多',
  short: '做空',
  buy: '做多',
  sell: '做空',
};

const scopeLabels: Record<string, string> = {
  historical: '历史回放',
};

const runtimeModeLabels: Record<string, string> = {
  backtest: '历史回放',
  live_signal: '实时信号',
};

const triggerModeLabels: Record<string, string> = {
  bar_close: 'Bar Close',
  wall_clock: 'Wall Clock',
};

export function toDateTimeLocal(value: Date): string {
  const offset = value.getTimezoneOffset();
  const local = new Date(value.getTime() - offset * 60_000);
  return local.toISOString().slice(0, 16);
}

export function translateToken(value?: string | null, dictionary: Record<string, string> = {}): string {
  if (!value) return '--';
  return dictionary[value] ?? value.replace(/_/g, ' ');
}

export function describeExtractionMethod(value?: Skill['extraction_method']): string {
  if (value === 'llm_fallback') return 'LLM 回退';
  return '规则提取';
}

export function formatTime(value?: number | null): string {
  if (typeof value !== 'number' || Number.isNaN(value)) return '--';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '--';
  return new Intl.DateTimeFormat(LOCALE, {
    dateStyle: 'medium',
    timeStyle: 'short',
    hour12: false,
  }).format(date);
}

export function formatPreciseTime(value?: number | null): string {
  if (typeof value !== 'number' || Number.isNaN(value)) return '--';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '--';
  const base = new Intl.DateTimeFormat(LOCALE, {
    dateStyle: 'medium',
    timeStyle: 'medium',
    hour12: false,
  }).format(date);
  return `${base}.${String(date.getMilliseconds()).padStart(3, '0')}`;
}

export function formatCount(value?: number | null): string {
  if (typeof value !== 'number' || Number.isNaN(value)) return '--';
  return new Intl.NumberFormat(LOCALE).format(value);
}

export function formatPercent(value?: number | null): string {
  if (typeof value !== 'number' || Number.isNaN(value)) return '--';
  return `${(value * 100).toFixed(2)}%`;
}

export function formatSignedPercent(value?: number | null): string {
  if (typeof value !== 'number' || Number.isNaN(value)) return '--';
  const prefix = value > 0 ? '+' : '';
  return `${prefix}${(value * 100).toFixed(2)}%`;
}

export function formatCurrency(value?: number | null): string {
  if (typeof value !== 'number' || Number.isNaN(value)) return '--';
  return new Intl.NumberFormat(LOCALE, {
    maximumFractionDigits: 2,
    minimumFractionDigits: 2,
  }).format(value);
}

export function formatSignedCurrency(value?: number | null): string {
  if (typeof value !== 'number' || Number.isNaN(value)) return '--';
  const prefix = value > 0 ? '+' : '';
  return `${prefix}${formatCurrency(value)}`;
}

export function describeStatus(status?: string | null): string {
  return translateToken(status, generalStatusLabels);
}

export function describeAction(action?: string | null): string {
  return translateToken(action, actionLabels);
}

export function describeDirection(direction?: string | null): string {
  return translateToken(direction, directionLabels);
}

export function describeScope(scope?: string | null): string {
  return translateToken(scope, scopeLabels);
}

export function describeRuntimeMode(mode?: string | null): string {
  return translateToken(mode, runtimeModeLabels);
}

export function describeTriggerMode(mode?: string | null): string {
  return translateToken(mode, triggerModeLabels);
}

export function summarizeDecision(decision: Record<string, unknown>): string {
  const action = describeAction(typeof decision.action === 'string' ? decision.action : 'skip');
  const symbol = typeof decision.symbol === 'string' ? decision.symbol : null;
  const direction = describeDirection(typeof decision.direction === 'string' ? decision.direction : null);
  const sizePct = typeof decision.size_pct === 'number' ? formatPercent(decision.size_pct) : null;
  return [action, symbol, direction === '--' ? null : direction, sizePct].filter(Boolean).join(' / ');
}

export function summarizeToolSequence(toolCalls: ToolCall[]): string {
  if (!toolCalls.length) return '暂无工具调用';
  return toolCalls.map((call) => call.tool_name).join(' -> ');
}

export function formatJson(value: unknown): string {
  return JSON.stringify(value, null, 2) ?? 'null';
}

export function isBacktestActive(status?: string): boolean {
  return status === 'queued' || status === 'running' || status === 'stopping';
}

export function countSignalsToday(signals: LiveSignal[]): number {
  const today = new Intl.DateTimeFormat(LOCALE, { dateStyle: 'short' }).format(new Date());
  return signals.filter((signal) => {
    const signalDate = new Date(signal.trigger_time_ms);
    if (Number.isNaN(signalDate.getTime())) return false;
    return new Intl.DateTimeFormat(LOCALE, { dateStyle: 'short' }).format(signalDate) === today;
  }).length;
}

export function getErrorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}

export function formatShortDuration(value?: number | null): string {
  if (typeof value !== 'number' || Number.isNaN(value) || value < 0) return '--';
  if (value < 1000) return `${Math.round(value)}ms`;
  return `${(value / 1000).toFixed(2)}s`;
}

export function formatDurationFromMs(startMs?: number | null, endMs: number = Date.now()): string {
  if (typeof startMs !== 'number' || Number.isNaN(startMs) || endMs <= startMs) return '--';
  const totalMinutes = Math.floor((endMs - startMs) / 60_000);
  const days = Math.floor(totalMinutes / (24 * 60));
  const hours = Math.floor((totalMinutes % (24 * 60)) / 60);
  const minutes = totalMinutes % 60;
  if (days > 0) return `${days}天 ${hours}小时`;
  if (hours > 0) return `${hours}小时 ${minutes}分`;
  return `${minutes}分`;
}

export function formatWindow(startMs?: number | null, endMs?: number | null): string {
  if (typeof startMs !== 'number' || typeof endMs !== 'number') return '--';
  return `${formatTime(startMs)} - ${formatTime(endMs)}`;
}

export function toneForStatus(status?: string | null): 'ok' | 'warn' | 'error' | 'neutral' {
  if (!status) return 'neutral';
  if (['ok', 'healthy', 'completed', 'active', 'stored', 'passed'].includes(status)) {
    return 'ok';
  }
  if (['queued', 'running', 'pending', 'skipped', 'paused', 'stopping', 'stopped'].includes(status)) {
    return 'warn';
  }
  if (['failed', 'validation_failed', 'degraded'].includes(status)) {
    return 'error';
  }
  return 'neutral';
}
