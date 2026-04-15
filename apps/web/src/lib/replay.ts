import type { BacktestTrace, MarketCandle, PortfolioFill, PortfolioPosition } from '../types';

export type ReplaySymbolSlice = {
  symbol: string;
  traces: BacktestTrace[];
  fills: PortfolioFill[];
  positions: PortfolioPosition[];
  triggerCount: number;
  tradeCount: number;
  firstTriggerMs: number | null;
  lastTriggerMs: number | null;
};

function collectPositions(trace: BacktestTrace): PortfolioPosition[] {
  const beforePositions = trace.portfolio_before?.positions ?? [];
  const afterPositions = trace.portfolio_after?.positions ?? [];
  return [...beforePositions, ...afterPositions];
}

function traceMentionsSymbol(trace: BacktestTrace, symbol: string): boolean {
  if (trace.decision.symbol === symbol) return true;
  if (trace.fills.some((fill) => fill.symbol === symbol)) return true;
  return collectPositions(trace).some((position) => position.symbol === symbol);
}

export function buildReplaySymbolSlices(traces: BacktestTrace[]): ReplaySymbolSlice[] {
  const symbols = new Set<string>();

  for (const trace of traces) {
    if (typeof trace.decision.symbol === 'string' && trace.decision.symbol) {
      symbols.add(trace.decision.symbol);
    }

    for (const fill of trace.fills) {
      if (fill.symbol) {
        symbols.add(fill.symbol);
      }
    }

    for (const position of collectPositions(trace)) {
      if (position.symbol) {
        symbols.add(position.symbol);
      }
    }
  }

  return [...symbols]
    .map((symbol) => {
      const symbolTraces = traces.filter((trace) => traceMentionsSymbol(trace, symbol));
      const fills = symbolTraces.flatMap((trace) => trace.fills.filter((fill) => fill.symbol === symbol));
      const positions = symbolTraces.flatMap((trace) => collectPositions(trace).filter((position) => position.symbol === symbol));
      return {
        symbol,
        traces: symbolTraces,
        fills,
        positions,
        triggerCount: symbolTraces.length,
        tradeCount: fills.length,
        firstTriggerMs: symbolTraces[0]?.trigger_time_ms ?? null,
        lastTriggerMs: symbolTraces[symbolTraces.length - 1]?.trigger_time_ms ?? null,
      };
    })
    .sort((left, right) => {
      if (right.tradeCount !== left.tradeCount) {
        return right.tradeCount - left.tradeCount;
      }
      if ((right.lastTriggerMs ?? 0) !== (left.lastTriggerMs ?? 0)) {
        return (right.lastTriggerMs ?? 0) - (left.lastTriggerMs ?? 0);
      }
      return left.symbol.localeCompare(right.symbol);
    });
}

export function summarizeCandleRange(candles: MarketCandle[]): {
  firstClose: number | null;
  lastClose: number | null;
  high: number | null;
  low: number | null;
} {
  if (!candles.length) {
    return {
      firstClose: null,
      lastClose: null,
      high: null,
      low: null,
    };
  }

  return candles.reduce(
    (summary, candle, index) => ({
      firstClose: index === 0 ? candle.close : summary.firstClose,
      lastClose: candle.close,
      high: summary.high === null ? candle.high : Math.max(summary.high, candle.high),
      low: summary.low === null ? candle.low : Math.min(summary.low, candle.low),
    }),
    {
      firstClose: null as number | null,
      lastClose: null as number | null,
      high: null as number | null,
      low: null as number | null,
    },
  );
}
