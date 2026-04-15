import type { MarketOverview } from '../types';
import { toDateTimeLocal } from './formatting';

export const DEFAULT_BACKTEST_INITIAL_CAPITAL = 10_000;

const DAY_MS = 24 * 60 * 60 * 1000;

type BacktestWindowMs = {
  startTimeMs: number;
  endTimeMs: number;
};

type ResolveBacktestLaunchParams = {
  overview: MarketOverview | null;
  startInput: string;
  endInput: string;
  initialCapital: number;
  cadence?: string | null;
};

type ResolvedBacktestLaunch =
  | {
      payload: {
        start_time_ms: number;
        end_time_ms: number;
        initial_capital: number;
      };
      error: null;
    }
  | {
      payload: null;
      error: string;
    };

export function getHistoricalCoverageWindowMs(overview: MarketOverview | null): BacktestWindowMs | null {
  if (overview?.coverage_start_ms == null || overview?.coverage_end_ms == null) return null;
  if (overview.coverage_end_ms <= overview.coverage_start_ms) return null;
  return {
    startTimeMs: overview.coverage_start_ms,
    endTimeMs: overview.coverage_end_ms,
  };
}

export function getHistoricalCoverageWindow(
  overview: MarketOverview | null,
): { start: string; end: string } | null {
  const coverage = getHistoricalCoverageWindowMs(overview);
  if (!coverage) return null;
  return {
    start: toDateTimeLocal(new Date(coverage.startTimeMs)),
    end: toDateTimeLocal(new Date(coverage.endTimeMs)),
  };
}

export function getDefaultBacktestWindowMs(overview: MarketOverview | null): BacktestWindowMs | null {
  const coverage = getHistoricalCoverageWindowMs(overview);
  if (!coverage) return null;
  const startTimeMs = Math.max(coverage.startTimeMs, coverage.endTimeMs - DAY_MS);
  if (startTimeMs >= coverage.endTimeMs) return null;
  return {
    startTimeMs,
    endTimeMs: coverage.endTimeMs,
  };
}

export function getDefaultBacktestWindow(
  overview: MarketOverview | null,
): { start: string; end: string } | null {
  const window = getDefaultBacktestWindowMs(overview);
  if (!window) return null;
  return {
    start: toDateTimeLocal(new Date(window.startTimeMs)),
    end: toDateTimeLocal(new Date(window.endTimeMs)),
  };
}

function parseCadenceMs(cadence?: string | null): number | null {
  if (!cadence) return null;
  const normalized = cadence.trim().toLowerCase();
  const match = normalized.match(/^(\d+)\s*([mhd])$/);
  if (!match) return null;

  const value = Number(match[1]);
  if (!Number.isFinite(value) || value <= 0) return null;

  const unit = match[2];
  if (unit === 'm') return value * 60_000;
  if (unit === 'h') return value * 60 * 60_000;
  if (unit === 'd') return value * 24 * 60 * 60_000;
  return null;
}

export function resolveBacktestLaunchRequest({
  overview,
  startInput,
  endInput,
  initialCapital,
  cadence,
}: ResolveBacktestLaunchParams): ResolvedBacktestLaunch {
  const coverage = getHistoricalCoverageWindowMs(overview);
  if (!coverage) {
    return {
      payload: null,
      error: '当前没有可用的本地历史数据，请先导入 CSV 后再发起回放。',
    };
  }

  const startDate = new Date(startInput);
  const endDate = new Date(endInput);
  const startTimeMs = startDate.getTime();
  const endTimeMs = endDate.getTime();

  if (Number.isNaN(startTimeMs) || Number.isNaN(endTimeMs)) {
    return {
      payload: null,
      error: '回放时间无效，请重新选择开始与结束时间。',
    };
  }
  if (startTimeMs >= endTimeMs) {
    return {
      payload: null,
      error: '回放结束时间必须晚于开始时间。',
    };
  }
  if (!Number.isFinite(initialCapital) || initialCapital <= 0) {
    return {
      payload: null,
      error: '初始资金必须是大于 0 的数字。',
    };
  }
  if (startTimeMs < coverage.startTimeMs || endTimeMs > coverage.endTimeMs) {
    return {
      payload: null,
      error: '所选回放时间必须落在当前本地历史覆盖范围内。',
    };
  }

  const cadenceMs = parseCadenceMs(cadence);
  if (cadenceMs != null && endTimeMs - startTimeMs < cadenceMs) {
    return {
      payload: null,
      error: `回放窗口至少需要覆盖一个完整的 ${cadence} 周期。`,
    };
  }

  return {
    payload: {
      start_time_ms: startTimeMs,
      end_time_ms: endTimeMs,
      initial_capital: initialCapital,
    },
    error: null,
  };
}
