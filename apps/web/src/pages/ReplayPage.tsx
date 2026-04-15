import { useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import ReplayChart from '../components/ReplayChart';
import { getBacktest, getBacktestPortfolio, listBacktestTraces, listBacktests, listMarketCandles } from '../api';
import {
  describeAction,
  describeDirection,
  describeStatus,
  formatCount,
  formatCurrency,
  formatPercent,
  formatTime,
  getErrorMessage,
  summarizeDecision,
  summarizeToolSequence,
} from '../lib/formatting';
import { buildReplaySymbolSlices, summarizeCandleRange } from '../lib/replay';
import type { BacktestRun, BacktestTrace, MarketCandle, PortfolioState } from '../types';

function symbolButtonClass(active: boolean): string {
  return `symbol-chip${active ? ' is-active' : ''}`;
}

export default function ReplayPage() {
  const { runId } = useParams<{ runId: string }>();
  const [backtests, setBacktests] = useState<BacktestRun[]>([]);
  const [run, setRun] = useState<BacktestRun | null>(null);
  const [traces, setTraces] = useState<BacktestTrace[]>([]);
  const [portfolio, setPortfolio] = useState<PortfolioState | null>(null);
  const [candles, setCandles] = useState<MarketCandle[]>([]);
  const [selectedSymbol, setSelectedSymbol] = useState<string>('');
  const [loading, setLoading] = useState(true);
  const [candlesLoading, setCandlesLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!runId) return;
    const currentRunId = runId;

    let cancelled = false;

    async function load() {
      setLoading(true);
      try {
        const [nextRuns, nextRun, nextTraces, nextPortfolio] = await Promise.all([
          listBacktests(),
          getBacktest(currentRunId),
          listBacktestTraces(currentRunId),
          getBacktestPortfolio(currentRunId),
        ]);

        if (cancelled) return;
        setBacktests(nextRuns);
        setRun(nextRun);
        setTraces(nextTraces);
        setPortfolio(nextPortfolio);
        setError(null);
      } catch (nextError) {
        if (!cancelled) {
          setError(getErrorMessage(nextError));
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [runId]);

  const symbolSlices = useMemo(() => buildReplaySymbolSlices(traces), [traces]);

  useEffect(() => {
    if (!symbolSlices.length) {
      setSelectedSymbol('');
      return;
    }

    if (!symbolSlices.some((slice) => slice.symbol === selectedSymbol)) {
      setSelectedSymbol(symbolSlices[0].symbol);
    }
  }, [selectedSymbol, symbolSlices]);

  const selectedSlice = useMemo(
    () => symbolSlices.find((slice) => slice.symbol === selectedSymbol) ?? symbolSlices[0] ?? null,
    [selectedSymbol, symbolSlices],
  );

  useEffect(() => {
    if (!run || !selectedSlice?.symbol) {
      setCandles([]);
      return;
    }
    const endTimeMs = run.end_time_ms;

    let cancelled = false;

    async function loadCandles() {
      setCandlesLoading(true);
      try {
        const nextCandles = await listMarketCandles({
          market_symbol: selectedSlice.symbol,
          timeframe: '15m',
          limit: 120,
          end_time_ms: endTimeMs,
        });
        if (!cancelled) {
          setCandles(nextCandles);
        }
      } catch {
        if (!cancelled) {
          setCandles([]);
        }
      } finally {
        if (!cancelled) {
          setCandlesLoading(false);
        }
      }
    }

    loadCandles();
    return () => {
      cancelled = true;
    };
  }, [run, selectedSlice?.symbol]);

  const candleSummary = useMemo(() => summarizeCandleRange(candles), [candles]);
  const returnPct = typeof run?.summary?.total_return_pct === 'number' ? Number(run.summary.total_return_pct) : null;
  const finalEquity = typeof run?.summary?.final_equity === 'number' ? Number(run.summary.final_equity) : portfolio?.account?.equity ?? null;
  const selectedFillCount = selectedSlice?.fills.length ?? 0;

  return (
    <div className="product-page-stack replay-page-layout">
      <section className="replay-overview-panel neon-panel">
        <div>
          <p className="section-kicker">Replay Run</p>
          <h1 className="page-title">{run?.id ?? runId ?? 'Replay'}</h1>
          <p className="page-description">
            从 run 级别进入，再按 symbol 切开；当前页面已经按未来图表叠加做了结构铺垫，下一步就可以把 `lightweight-charts` 接进这个可视化区域。
          </p>
        </div>
        <div className="overview-meta-list">
          <span>{run ? describeStatus(run.status) : loading ? '加载中' : '未找到'}</span>
          <span>{run ? formatTime(run.updated_at_ms) : '--'}</span>
          <Link className="inline-link" to="/replays">
            切换其他回放
          </Link>
        </div>
      </section>

      {error ? <div className="neon-banner neon-banner-error">回放加载失败：{error}</div> : null}

      <section className="replay-workspace-grid">
        <aside className="replay-sidebar neon-panel">
          <div className="section-heading-row">
            <div>
              <p className="section-kicker">Run Selector</p>
              <h2>最近回放</h2>
            </div>
          </div>
          <div className="sidebar-run-list">
            {backtests.map((item) => (
              <Link className={`sidebar-run-card${item.id === runId ? ' is-active' : ''}`} key={item.id} to={`/replays/${item.id}`}>
                <strong>{item.id}</strong>
                <span>{describeStatus(item.status)}</span>
                <small>{formatTime(item.created_at_ms)}</small>
              </Link>
            ))}
          </div>
        </aside>

        <div className="replay-main-stack">
          <section className="stats-grid replay-stats-grid">
            <article className="neon-stat-tile">
              <span>Replay Steps</span>
              <strong>{formatCount(traces.length)}</strong>
              <p>当前 run 中已记录的 Agent 触发步数</p>
            </article>
            <article className="neon-stat-tile">
              <span>Total Return</span>
              <strong>{returnPct == null ? '--' : formatPercent(returnPct)}</strong>
              <p>汇总层面的 run 表现</p>
            </article>
            <article className="neon-stat-tile">
              <span>Final Equity</span>
              <strong>{finalEquity == null ? '--' : formatCurrency(finalEquity)}</strong>
              <p>当前回放结束时的组合权益</p>
            </article>
            <article className="neon-stat-tile">
              <span>Tracked Symbols</span>
              <strong>{formatCount(symbolSlices.length)}</strong>
              <p>本次回放中实际发生决策或持仓变化的标的</p>
            </article>
          </section>

          <section className="neon-panel">
            <div className="section-heading-row">
              <div>
                <p className="section-kicker">Symbol Slices</p>
                <h2>按标的切开这条回放</h2>
              </div>
              <span className="muted-label">支持频繁轮动多 symbol</span>
            </div>
            <div className="symbol-chip-row">
              {symbolSlices.length ? (
                symbolSlices.map((slice) => (
                  <button className={symbolButtonClass(slice.symbol === selectedSlice?.symbol)} key={slice.symbol} type="button" onClick={() => setSelectedSymbol(slice.symbol)}>
                    <strong>{slice.symbol}</strong>
                    <span>{slice.tradeCount} fills / {slice.triggerCount} traces</span>
                  </button>
                ))
              ) : (
                <div className="empty-product-card wide-empty-card">
                  <strong>{loading ? '正在解构回放...' : '这条回放还没有可识别的 symbol 切片'}</strong>
                  <p>如果后端 trace 继续沉淀更多符号级细节，这里会自动成长为完整的 symbol theater。</p>
                </div>
              )}
            </div>
          </section>

          <section className="visualization-grid">
            <article className="neon-panel chart-placeholder-panel">
              <div className="section-heading-row">
                <div>
                  <p className="section-kicker">Chart Dock</p>
                  <h2>{selectedSlice?.symbol ?? '等待选择 symbol'}</h2>
                </div>
                <span className="muted-label">Chart-ready region</span>
              </div>
              <ReplayChart candles={candles} fills={selectedSlice?.fills ?? []} loading={candlesLoading} symbol={selectedSlice?.symbol} />
              <div className="chart-footnote-grid">
                <div className="chart-footnote">
                  <small>价格区间</small>
                  <strong>
                    {candles.length
                      ? `${candleSummary.low?.toFixed(4)} - ${candleSummary.high?.toFixed(4)}`
                      : candlesLoading
                        ? '同步中'
                        : '--'}
                  </strong>
                  <p>
                    {candles.length
                      ? `收盘从 ${candleSummary.firstClose?.toFixed(4)} 变化到 ${candleSummary.lastClose?.toFixed(4)}。`
                      : '图表已接通 candle 数据，缺少样本时会在这里保留空状态。'}
                  </p>
                </div>
                <div className="chart-footnote">
                  <small>执行标记</small>
                  <strong>{formatCount(selectedFillCount)}</strong>
                  <p>青色代表多头入场，洋红代表空头入场，琥珀代表减仓或离场。</p>
                </div>
              </div>
            </article>

            <article className="neon-panel chart-placeholder-panel">
              <div className="section-heading-row">
                <div>
                  <p className="section-kicker">Trade Context</p>
                  <h2>当前标的动作摘要</h2>
                </div>
              </div>
              {selectedSlice ? (
                <div className="symbol-summary-card">
                  <strong>{selectedSlice.symbol}</strong>
                  <p>
                    首次触发 {formatTime(selectedSlice.firstTriggerMs)} / 最近触发 {formatTime(selectedSlice.lastTriggerMs)}
                  </p>
                  <p>成交 {selectedSlice.tradeCount} 次，涉及 {selectedSlice.positions.length} 条仓位快照。</p>
                </div>
              ) : (
                <div className="empty-product-card wide-empty-card">
                  <strong>等待 symbol 上下文</strong>
                  <p>选择某个标的后，这里会展示它的仓位与成交摘要。</p>
                </div>
              )}
            </article>
          </section>

          <section className="neon-panel">
            <div className="section-heading-row">
              <div>
                <p className="section-kicker">Decision Timeline</p>
                <h2>标的级 Agent 叙事</h2>
              </div>
              <span className="muted-label">先叙事，后 raw trace</span>
            </div>
            <div className="timeline-list">
              {selectedSlice?.traces.length ? (
                selectedSlice.traces.map((trace) => (
                  <article className="timeline-card" key={trace.id}>
                    <div className="timeline-card-head">
                      <div>
                        <small>Step {trace.trace_index + 1}</small>
                        <strong>{formatTime(trace.trigger_time_ms)}</strong>
                      </div>
                      <div className="timeline-card-tags">
                        <span>{describeAction(typeof trace.decision.action === 'string' ? trace.decision.action : 'skip')}</span>
                        {typeof trace.decision.direction === 'string' ? <span>{describeDirection(trace.decision.direction)}</span> : null}
                        <span>{trace.tool_calls.length} tools</span>
                      </div>
                    </div>
                    <p>{trace.reasoning_summary || '当前步骤未返回推理摘要。'}</p>
                    <div className="timeline-card-grid">
                      <div>
                        <small>决策摘要</small>
                        <strong>{summarizeDecision(trace.decision)}</strong>
                      </div>
                      <div>
                        <small>工具序列</small>
                        <strong>{summarizeToolSequence(trace.tool_calls)}</strong>
                      </div>
                    </div>
                    {trace.fills.length ? (
                      <div className="fill-pill-row">
                        {trace.fills.map((fill) => (
                          <span className="fill-pill" key={fill.id}>
                            {fill.symbol} / {fill.side} / {fill.quantity.toFixed(4)} @ {fill.price.toFixed(4)}
                          </span>
                        ))}
                      </div>
                    ) : null}
                  </article>
                ))
              ) : (
                <div className="empty-product-card wide-empty-card">
                  <strong>{loading ? '正在读取决策轨迹...' : '当前 symbol 没有可展示的决策时间线'}</strong>
                  <p>如果这条 run 的动作集中在其他标的，切换 symbol 就能进入另一段 Agent 剧情。</p>
                </div>
              )}
            </div>
          </section>
        </div>
      </section>
    </div>
  );
}
