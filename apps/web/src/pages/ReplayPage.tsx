import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';

import LifecycleActions from '../components/LifecycleActions';
import ProductStatTile from '../components/ProductStatTile';
import ReplayChart from '../components/ReplayChart';
import { controlBacktest, deleteBacktest, getBacktest, getBacktestPortfolio, getSkill, listBacktestTraces, listMarketCandles } from '../api';
import {
  describeAction,
  describeDirection,
  describeStatus,
  formatCount,
  formatCurrency,
  formatSignedPercent,
  formatTime,
  formatWindow,
  getErrorMessage,
  toneForStatus,
} from '../lib/formatting';
import { buildReplaySymbolSlices, summarizeCandleRange } from '../lib/replay';
import { getProgressLabel, getRunReturnPct, getSkillCadence } from '../lib/product';
import type { BacktestRun, BacktestTrace, ExecutionAction, MarketCandle, PortfolioState, Skill } from '../types';

function progressWidth(run: BacktestRun | null): string {
  if (!run) return '0%';
  return `${Math.round((run.progress?.percent ?? 0) * 100)}%`;
}

export default function ReplayPage() {
  const { runId } = useParams<{ runId: string }>();
  const navigate = useNavigate();
  const [run, setRun] = useState<BacktestRun | null>(null);
  const [skill, setSkill] = useState<Skill | null>(null);
  const [traces, setTraces] = useState<BacktestTrace[]>([]);
  const [portfolio, setPortfolio] = useState<PortfolioState | null>(null);
  const [candles, setCandles] = useState<MarketCandle[]>([]);
  const [selectedSymbol, setSelectedSymbol] = useState('');
  const [loading, setLoading] = useState(true);
  const [candlesLoading, setCandlesLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pendingAction, setPendingAction] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!runId) return;

    try {
      const nextRun = await getBacktest(runId);
      const [nextTraces, nextPortfolio, nextSkill] = await Promise.all([
        listBacktestTraces(runId),
        getBacktestPortfolio(runId),
        getSkill(nextRun.skill_id).catch(() => null),
      ]);

      setRun(nextRun);
      setTraces(nextTraces);
      setPortfolio(nextPortfolio);
      setSkill(nextSkill);
      setError(null);
    } catch (nextError) {
      setError(getErrorMessage(nextError));
    } finally {
      setLoading(false);
    }
  }, [runId]);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => {
      void load();
    }, 15000);
    return () => window.clearInterval(timer);
  }, [load]);

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
    const currentRun = run;

    let cancelled = false;

    async function loadCandles() {
      setCandlesLoading(true);
      try {
        const nextCandles = await listMarketCandles({
          market_symbol: selectedSlice.symbol,
          timeframe: '15m',
          limit: 120,
          end_time_ms: currentRun.end_time_ms,
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

    void loadCandles();
    return () => {
      cancelled = true;
    };
  }, [run, selectedSlice?.symbol]);

  const candleSummary = useMemo(() => summarizeCandleRange(candles), [candles]);
  const returnPct = getRunReturnPct(run);
  const finalEquity =
    typeof run?.summary?.final_equity === 'number' ? Number(run.summary.final_equity) : portfolio?.account?.equity ?? null;

  async function handleAction(action: ExecutionAction) {
    if (!run) return;
    if (action === 'delete') {
      const confirmed = window.confirm(`删除回测 ${run.id}？\n\n这会同时删除回测时间线、组合状态和执行明细。`);
      if (!confirmed) return;
    }
    if (action === 'stop') {
      const confirmed = window.confirm(`停止回测 ${run.id}？\n\n系统会在安全检查点结束本次回测。`);
      if (!confirmed) return;
    }

    setPendingAction(action);
    try {
      if (action === 'delete') {
        await deleteBacktest(run.id);
        navigate('/replays');
        return;
      }
      await controlBacktest(run.id, action);
      await load();
    } catch (nextError) {
      setError(getErrorMessage(nextError));
    } finally {
      setPendingAction(null);
    }
  }

  const stats = [
    {
      label: '回测进度',
      value: run ? getProgressLabel(run) : '--',
      detail: run ? describeStatus(run.status) : '等待 run 数据',
    },
    {
      label: '收益率',
      value: returnPct == null ? '--' : formatSignedPercent(returnPct),
      detail: run?.summary?.net_pnl ? `净收益 ${formatCurrency(Number(run.summary.net_pnl))}` : '等待汇总结果',
    },
    {
      label: '当前权益',
      value: finalEquity == null ? '--' : formatCurrency(finalEquity),
      detail: portfolio?.account?.last_mark_time_ms ? `更新于 ${formatTime(portfolio.account.last_mark_time_ms)}` : '等待组合快照',
    },
    {
      label: '追踪标的',
      value: formatCount(symbolSlices.length),
      detail: selectedSlice ? `当前聚焦 ${selectedSlice.symbol}` : '等待策略开始产生标的上下文',
    },
  ];

  return (
    <div className="page-stack">
      <section className="hero-panel surface">
        <div>
          <p className="section-eyebrow">Backtest Detail</p>
          <h1>{skill?.title ?? run?.id ?? runId ?? '回测详情'}</h1>
          <p className="hero-copy">
            当前详情页只服务这一条回测：状态、进度、策略关联、图表、组合结果和决策时间线都围绕当前 run 展开。
          </p>
        </div>
        <div className="hero-meta">
          <span className={`status-pill is-${toneForStatus(run?.status)}`}>{describeStatus(run?.status)}</span>
          <span className="info-pill">{run ? formatWindow(run.start_time_ms, run.end_time_ms) : '--'}</span>
          {skill ? (
            <Link className="action-button" to={`/strategies/${skill.id}`}>
              打开策略档案
            </Link>
          ) : null}
        </div>
      </section>

      <section className="metric-grid">
        {stats.map((stat) => (
          <ProductStatTile detail={stat.detail} key={stat.label} label={stat.label} value={stat.value} />
        ))}
      </section>

      {error ? <div className="feedback-banner is-error">回测详情加载失败：{error}</div> : null}

      <section className="surface">
        <div className="section-head">
          <div>
            <p className="section-eyebrow">Run Control</p>
            <h2>当前回测控制</h2>
          </div>
          <div className="action-cluster">
            <Link className="action-button" to="/replays">
              返回回测列表
            </Link>
            <LifecycleActions
              actions={run?.available_actions ?? []}
              disabled={!run || Boolean(pendingAction)}
              onAction={(action) => void handleAction(action)}
              pendingAction={pendingAction}
            />
          </div>
        </div>
        <div className="spec-sheet">
          <article className="spec-row is-emphasis">
            <div className="spec-term-block">
              <span className="spec-term">回测状态</span>
            </div>
            <div className="spec-main">
              <strong>{run ? describeStatus(run.status) : '--'}</strong>
              <p>{run?.pending_action ? `待执行动作：${run.pending_action}` : '当前没有挂起控制动作。'}</p>
            </div>
            <div className="spec-side">
              <span className="spec-side-label">进度</span>
              <strong>{run ? getProgressLabel(run) : '--'}</strong>
              <div className="progress-bar">
                <span className="progress-fill" style={{ width: progressWidth(run) }} />
              </div>
            </div>
          </article>
          <article className="spec-row">
            <div className="spec-term-block">
              <span className="spec-term">执行窗口</span>
            </div>
            <div className="spec-main">
              <strong>{run ? formatWindow(run.start_time_ms, run.end_time_ms) : '--'}</strong>
              <p>{skill ? `策略节奏 ${getSkillCadence(skill)}` : '等待策略资料'}</p>
            </div>
            <div className="spec-side">
              <span className="spec-side-label">关联策略</span>
              <strong>{skill?.title ?? run?.skill_id ?? '--'}</strong>
              <p>{skill ? '回测详情只追踪当前 run 与其所属策略。' : '策略档案读取中。'}</p>
            </div>
          </article>
          <article className="spec-row">
            <div className="spec-term-block">
              <span className="spec-term">异常信息</span>
            </div>
            <div className="spec-main">
              <strong>{run?.error_message ?? '无'}</strong>
              <p>失败或中断时，这里保留错误文本，便于定位。</p>
            </div>
            <div className="spec-side">
              <span className="spec-side-label">最近活动</span>
              <strong>{formatTime(run?.last_activity_at_ms ?? run?.updated_at_ms)}</strong>
              <p>更新时间与最后处理触发点会一起计入。</p>
            </div>
          </article>
        </div>
      </section>

      <section className="dual-grid">
        <section className="surface">
          <div className="section-head">
            <div>
              <p className="section-eyebrow">Chart Region</p>
              <h2>{selectedSlice?.symbol ?? '等待标的'}</h2>
            </div>
            <span className="section-note">成交标记与 K 线在同一画布内查看。</span>
          </div>
          <div className="symbol-tabs">
            {symbolSlices.length ? (
              symbolSlices.map((slice) => (
                <button
                  className={`symbol-tab${slice.symbol === selectedSlice?.symbol ? ' is-active' : ''}`}
                  key={slice.symbol}
                  onClick={() => setSelectedSymbol(slice.symbol)}
                  type="button"
                >
                  <strong>{slice.symbol}</strong>
                  <span>
                    {slice.tradeCount} fills / {slice.triggerCount} steps
                  </span>
                </button>
              ))
            ) : (
              <div className="empty-state compact-empty">
                <strong>{loading ? '正在提取标的切片...' : '这条回测还没有形成标的切片'}</strong>
                <p>一旦 run 产生更多交易动作，这里会自动切换成可按 symbol 浏览的图表工作区。</p>
              </div>
            )}
          </div>
          <ReplayChart candles={candles} fills={selectedSlice?.fills ?? []} loading={candlesLoading} symbol={selectedSlice?.symbol} />
          <div className="spec-sheet">
            <article className="spec-row is-emphasis">
              <div className="spec-term-block">
                <span className="spec-term">价格区间</span>
              </div>
              <div className="spec-main">
                <strong>
                  {candles.length
                    ? `${candleSummary.low?.toFixed(4)} - ${candleSummary.high?.toFixed(4)}`
                    : candlesLoading
                      ? '同步中'
                      : '--'}
                </strong>
                <p>
                  {candles.length
                    ? `收盘 ${candleSummary.firstClose?.toFixed(4)} → ${candleSummary.lastClose?.toFixed(4)}`
                    : '等待 K 线样本。'}
                </p>
              </div>
              <div className="spec-side">
                <span className="spec-side-label">当前标的动作</span>
                <strong>{selectedSlice ? formatCount(selectedSlice.tradeCount) : '--'}</strong>
                <p>{selectedSlice ? `首次触发 ${formatTime(selectedSlice.firstTriggerMs)}` : '等待选择标的。'}</p>
              </div>
            </article>
          </div>
        </section>

        <section className="surface">
          <div className="section-head">
            <div>
              <p className="section-eyebrow">Run Dossier</p>
              <h2>当前回测摘要</h2>
            </div>
          </div>
          <div className="spec-sheet">
            <article className="spec-row is-emphasis">
              <div className="spec-term-block">
                <span className="spec-term">策略</span>
              </div>
              <div className="spec-main">
                <strong>{skill?.title ?? run?.skill_id ?? '--'}</strong>
                <p>{skill ? `节奏 ${getSkillCadence(skill)}` : '读取策略档案中'}</p>
              </div>
              <div className="spec-side">
                <span className="spec-side-label">最终权益</span>
                <strong>{finalEquity == null ? '--' : formatCurrency(finalEquity)}</strong>
                <p>{returnPct == null ? '等待结果' : `收益率 ${formatSignedPercent(returnPct)}`}</p>
              </div>
            </article>
            <article className="spec-row">
              <div className="spec-term-block">
                <span className="spec-term">持仓数量</span>
              </div>
              <div className="spec-main">
                <strong>{formatCount(portfolio?.positions?.length ?? 0)}</strong>
                <p>组合快照来自当前回测作用域。</p>
              </div>
              <div className="spec-side">
                <span className="spec-side-label">最近活动</span>
                <strong>{formatTime(run?.last_activity_at_ms ?? run?.updated_at_ms)}</strong>
                <p>更新时间与最后处理触发点会一起计入。</p>
              </div>
            </article>
          </div>

          <div className="section-head">
            <div>
              <p className="section-eyebrow">Decision Timeline</p>
              <h2>当前标的时间线</h2>
            </div>
          </div>
          {selectedSlice?.traces.length ? (
            <div className="timeline-list">
              {selectedSlice.traces.map((trace) => (
                <article className="timeline-item" key={trace.id}>
                  <div className="timeline-head">
                    <div>
                      <strong>Step {trace.trace_index + 1}</strong>
                      <span>{formatTime(trace.trigger_time_ms)}</span>
                    </div>
                    <div className="meta-row">
                      <span className="info-pill">{describeAction(typeof trace.decision.action === 'string' ? trace.decision.action : 'skip')}</span>
                      {typeof trace.decision.direction === 'string' ? (
                        <span className="info-pill">{describeDirection(trace.decision.direction)}</span>
                      ) : null}
                    </div>
                  </div>
                  <p className="timeline-copy">{trace.reasoning_summary || '当前步骤未返回额外推理摘要。'}</p>
                  {trace.fills.length ? (
                    <div className="meta-row">
                      {trace.fills.map((fill) => (
                        <span className="info-pill" key={fill.id}>
                          {fill.symbol} / {fill.side} / {fill.quantity.toFixed(4)}
                        </span>
                      ))}
                    </div>
                  ) : null}
                </article>
              ))}
            </div>
          ) : (
            <div className="empty-state compact-empty">
              <strong>{loading ? '正在读取决策轨迹...' : '当前标的还没有可展示的决策时间线'}</strong>
              <p>选择其他 symbol，或者等待回测继续推进。</p>
            </div>
          )}
        </section>
      </section>
    </div>
  );
}
