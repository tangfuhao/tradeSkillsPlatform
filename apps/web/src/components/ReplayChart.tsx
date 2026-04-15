import { useEffect, useMemo, useRef } from 'react';

import {
  CandlestickSeries,
  ColorType,
  createChart,
  createSeriesMarkers,
  CrosshairMode,
  LineStyle,
  type CandlestickData,
  type SeriesMarker,
  type UTCTimestamp,
} from 'lightweight-charts';

import type { MarketCandle, PortfolioFill } from '../types';

type ReplayChartProps = {
  candles: MarketCandle[];
  fills: PortfolioFill[];
  loading?: boolean;
  symbol?: string;
};

function toUtcTimestamp(valueMs: number): UTCTimestamp {
  return Math.floor(valueMs / 1000) as UTCTimestamp;
}

function alignFillToBarTime(fill: PortfolioFill, candles: MarketCandle[]): UTCTimestamp {
  if (!candles.length) {
    return toUtcTimestamp(fill.trigger_time_ms);
  }

  let resolvedOpenTimeMs = candles[0].open_time_ms;
  for (const candle of candles) {
    if (candle.open_time_ms <= fill.trigger_time_ms) {
      resolvedOpenTimeMs = candle.open_time_ms;
      continue;
    }
    break;
  }

  return toUtcTimestamp(resolvedOpenTimeMs);
}

function buildTradeMarkers(candles: MarketCandle[], fills: PortfolioFill[]): SeriesMarker<UTCTimestamp>[] {
  return [...fills]
    .sort((left, right) => left.trigger_time_ms - right.trigger_time_ms)
    .map((fill) => {
      const isBuy = fill.side === 'buy';

      if (fill.action === 'open_position') {
        return {
          id: fill.id,
          time: alignFillToBarTime(fill, candles),
          position: isBuy ? 'belowBar' : 'aboveBar',
          shape: isBuy ? 'arrowUp' : 'arrowDown',
          color: isBuy ? '#55e6ff' : '#ff4fd8',
          text: isBuy ? 'LONG' : 'SHORT',
          size: 1.5,
        } satisfies SeriesMarker<UTCTimestamp>;
      }

      if (fill.action === 'reduce_position') {
        return {
          id: fill.id,
          time: alignFillToBarTime(fill, candles),
          position: isBuy ? 'belowBar' : 'aboveBar',
          shape: 'square',
          color: '#ffbe6b',
          text: 'REDUCE',
          size: 1.2,
        } satisfies SeriesMarker<UTCTimestamp>;
      }

      return {
        id: fill.id,
        time: alignFillToBarTime(fill, candles),
        position: isBuy ? 'belowBar' : 'aboveBar',
        shape: 'circle',
        color: '#ffbe6b',
        text: 'EXIT',
        size: 1.1,
      } satisfies SeriesMarker<UTCTimestamp>;
    });
}

export default function ReplayChart({ candles, fills, loading = false, symbol }: ReplayChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);

  const chartData = useMemo<CandlestickData<UTCTimestamp>[]>(
    () =>
      candles.map((candle) => ({
        time: toUtcTimestamp(candle.open_time_ms),
        open: candle.open,
        high: candle.high,
        low: candle.low,
        close: candle.close,
      })),
    [candles],
  );

  const tradeMarkers = useMemo(() => buildTradeMarkers(candles, fills), [candles, fills]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const chart = createChart(container, {
      width: container.clientWidth || 640,
      height: Math.max(container.clientHeight, 380),
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: '#cfe2ff',
        attributionLogo: true,
      },
      grid: {
        vertLines: { color: 'rgba(255, 255, 255, 0.05)', style: LineStyle.Dotted },
        horzLines: { color: 'rgba(255, 255, 255, 0.05)', style: LineStyle.Dotted },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: {
          color: 'rgba(85, 230, 255, 0.4)',
          style: LineStyle.Dashed,
          width: 1,
          labelBackgroundColor: '#0f1d39',
        },
        horzLine: {
          color: 'rgba(255, 79, 216, 0.28)',
          style: LineStyle.Dashed,
          width: 1,
          labelBackgroundColor: '#2a1239',
        },
      },
      rightPriceScale: {
        borderColor: 'rgba(85, 230, 255, 0.12)',
      },
      timeScale: {
        borderColor: 'rgba(85, 230, 255, 0.12)',
        timeVisible: true,
        secondsVisible: false,
      },
      handleScroll: {
        mouseWheel: true,
        pressedMouseMove: true,
      },
      handleScale: {
        axisPressedMouseMove: true,
        mouseWheel: true,
        pinch: true,
      },
      localization: {
        locale: 'zh-CN',
      },
    });

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#55e6ff',
      downColor: '#ff4fd8',
      wickUpColor: '#55e6ff',
      wickDownColor: '#ff4fd8',
      borderVisible: false,
      lastValueVisible: true,
      priceLineVisible: true,
      priceLineColor: '#3988ff',
    });

    candleSeries.setData(chartData);
    createSeriesMarkers(candleSeries, tradeMarkers);

    if (chartData.length) {
      chart.timeScale().fitContent();
    }

    const resize = () => {
      chart.applyOptions({
        width: container.clientWidth || 640,
        height: Math.max(container.clientHeight, 380),
      });
    };

    resize();
    const resizeObserver = new ResizeObserver(() => resize());
    resizeObserver.observe(container);

    return () => {
      resizeObserver.disconnect();
      chart.remove();
    };
  }, [chartData, tradeMarkers, symbol]);

  return (
    <div className="replay-chart-shell">
      <div className="replay-chart-canvas" ref={containerRef} />
      <div className="replay-chart-overlay">
        {loading ? (
          <div className="replay-chart-status">正在同步 {symbol ?? 'selected symbol'} 的走势与执行标记...</div>
        ) : null}
        {!loading && !candles.length ? <div className="replay-chart-status">当前没有可绘制的 K 线样本。</div> : null}
      </div>
    </div>
  );
}
