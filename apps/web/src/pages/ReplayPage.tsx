import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { toast } from 'sonner';

import ConfirmDialog from '../components/ConfirmDialog';
import LifecycleActions from '../components/LifecycleActions';
import PageHeader from '../components/PageHeader';
import ProductStatTile from '../components/ProductStatTile';
import ReplayChart from '../components/ReplayChart';
import { controlBacktest, deleteBacktest, getBacktest, getBacktestPortfolio, getSkill, listBacktestTraces, listMarketCandles } from '../api';
import { getBacktestControlActionLabel } from '../lib/backtest';
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

type ConfirmState = {
  title: string;
  description: string;
  confirmLabel: string;
  tone: 'danger' | 'warning';
  onConfirm: () => void;
} | null;

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
  const [confirm, setConfirm] = useState<ConfirmState>(null);

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

  const timelineTraces = useMemo(() => {
    const list = selectedSlice?.traces ?? [];
    return [...list].sort((a, b) => {
      const timeDiff = (b.trigger_time_ms ?? 0) - (a.trigger_time_ms ?? 0);
      if (timeDiff !== 0) return timeDiff;
      return (b.trace_index ?? 0) - (a.trace_index ?? 0);
    });
  }, [selectedSlice?.symbol, selectedSlice?.traces]);

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

  async function executeAction(action: ExecutionAction) {
    if (!run) return;
    setPendingAction(action);
    try {
      if (action === 'delete') {
        await deleteBacktest(run.id);
        toast.success('回测已删除');
        navigate('/replays');
        return;
      }
      await controlBacktest(run.id, action);
      toast.success(`回测已${getBacktestControlActionLabel(action, run.status)}`);
      await load();
    } catch (nextError) {
      toast.error(getErrorMessage(nextError));
    } finally {
      setPendingAction(null);
    }
  }

  function handleAction(action: ExecutionAction) {
    if (!run) return;
    if (action === 'delete') {
      setConfirm({
        title: '删除回测',
        description: '删除后将清除回测时间线、组合状态和执行明细，且无法恢复。',
        confirmLabel: '确认删除',
        tone: 'danger',
        onConfirm: () => {
          setConfirm(null);
          void executeAction(action);
        },
      });
      return;
    }
    if (action === 'stop') {
      setConfirm({
        title: '停止回测',
        description: '系统会在安全检查点结束本次回测，已完成的进度会保留。',
        confirmLabel: '确认停止',
        tone: 'warning',
        onConfirm: () => {
          setConfirm(null);
          void executeAction(action);
        },
      });
      return;
    }
    void executeAction(action);
  }

  const stats = [
    {
      label: '回测进度',
      value: run ? getProgressLabel(run) : '--',
      detail: run ? describeStatus(run.status) : '等待数据',
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
      detail: selectedSlice ? `当前聚焦 ${selectedSlice.symbol}` : '等待产生标的',
    },
  ];

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="回测详情"
        title={skill?.title ?? run?.id ?? runId ?? '回测详情'}
        description={run ? `时间窗口 ${formatWindow(run.start_time_ms, run.end_time_ms)}` : undefined}
        backTo="/replays"
        backLabel="回测列表"
        status={
          <>
            <span className={`status-pill is-${toneForStatus(run?.status)}`}>{describeStatus(run?.status)}</span>
            {skill && <Link className="text-link" to={`/strategies/${skill.id}`}>策略档案</Link>}
          </>
        }
        actions={
          <LifecycleActions
            actions={run?.available_actions ?? []}
            disabled={!run || Boolean(pendingAction)}
            onAction={(action) => handleAction(action)}
            pendingAction={pendingAction}
            status={run?.status}
          />
        }
      />

      <section className="metric-grid">
        {stats.map((stat) => (
          <ProductStatTile detail={stat.detail} key={stat.label} label={stat.label} value={stat.value} />
        ))}
      </section>

      {error ? <div className="feedback-banner is-error">{error}</div> : null}

      <section className="surface">
        <div className="section-head">
          <div>
            <p className="section-eyebrow">回测控制</p>
            <h2>运行状态</h2>
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
            </div>
          </article>
          {run?.error_message && (
            <article className="spec-row">
              <div className="spec-term-block">
                <span className="spec-term">异常信息</span>
              </div>
              <div className="spec-main">
                <strong>{run.error_message}</strong>
                {run.status === 'failed' ? (
                  <p>点击“恢复执行”后，系统会从上次成功 checkpoint 后继续执行；如果首个 checkpoint 前失败，则会从第 1 步重新开始。</p>
                ) : null}
              </div>
              <div className="spec-side">
                <span className="spec-side-label">最近活动</span>
                <strong>{formatTime(run.last_activity_at_ms ?? run.updated_at_ms)}</strong>
              </div>
            </article>
          )}
        </div>
      </section>

      <section className="dual-grid">
        <section className="surface">
          <div className="section-head">
            <div>
              <p className="section-eyebrow">图表区域</p>
              <h2>{selectedSlice?.symbol ?? '等待标的'}</h2>
            </div>
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
                    {slice.tradeCount} 成交 / {slice.triggerCount} 步
                  </span>
                </button>
              ))
            ) : (
              <div className="empty-state compact-empty">
                <strong>{loading ? '正在提取标的切片...' : '还没有形成标的切片'}</strong>
                <p>回测产生交易动作后将自动展示图表。</p>
              </div>
            )}
          </div>
          <ReplayChart candles={candles} fills={selectedSlice?.fills ?? []} loading={candlesLoading} symbol={selectedSlice?.symbol} />
          {candles.length > 0 && (
            <div className="spec-sheet">
              <article className="spec-row is-emphasis">
                <div className="spec-term-block">
                  <span className="spec-term">价格区间</span>
                </div>
                <div className="spec-main">
                  <strong>
                    {candleSummary.low?.toFixed(4)} - {candleSummary.high?.toFixed(4)}
                  </strong>
                  <p>
                    收盘 {candleSummary.firstClose?.toFixed(4)} → {candleSummary.lastClose?.toFixed(4)}
                  </p>
                </div>
                <div className="spec-side">
                  <span className="spec-side-label">当前标的动作</span>
                  <strong>{selectedSlice ? formatCount(selectedSlice.tradeCount) : '--'}</strong>
                  <p>{selectedSlice ? `首次触发 ${formatTime(selectedSlice.firstTriggerMs)}` : ''}</p>
                </div>
              </article>
            </div>
          )}
        </section>

        <section className="surface">
          <div className="section-head">
            <div>
              <p className="section-eyebrow">回测摘要</p>
              <h2>组合概览</h2>
            </div>
          </div>
          <div className="spec-sheet">
            <article className="spec-row is-emphasis">
              <div className="spec-term-block">
                <span className="spec-term">策略</span>
              </div>
              <div className="spec-main">
                <strong>{skill?.title ?? run?.skill_id ?? '--'}</strong>
                <p>{skill ? `节奏 ${getSkillCadence(skill)}` : '读取中'}</p>
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
              </div>
              <div className="spec-side">
                <span className="spec-side-label">最近活动</span>
                <strong>{formatTime(run?.last_activity_at_ms ?? run?.updated_at_ms)}</strong>
              </div>
            </article>
          </div>

          <div className="section-head" style={{ marginTop: 16 }}>
            <div>
              <p className="section-eyebrow">决策时间线</p>
              <h2>当前标的时间线</h2>
            </div>
          </div>
          {timelineTraces.length ? (
            <div className="timeline-list" style={{ maxHeight: 420, overflowY: 'auto', paddingRight: 4 }}>
              {timelineTraces.map((trace) => (
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
                  <p className="timeline-copy">{trace.reasoning_summary || '当前步骤未返回推理摘要。'}</p>
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
              <strong>{loading ? '正在读取决策轨迹...' : '还没有可展示的决策时间线'}</strong>
              <p>选择其他标的，或等待回测继续推进。</p>
            </div>
          )}
        </section>
      </section>

      <ConfirmDialog
        open={confirm !== null}
        onOpenChange={(open) => { if (!open) setConfirm(null); }}
        title={confirm?.title ?? ''}
        description={confirm?.description ?? ''}
        confirmLabel={confirm?.confirmLabel ?? '确认'}
        tone={confirm?.tone ?? 'danger'}
        onConfirm={confirm?.onConfirm ?? (() => {})}
      />
    </div>
  );
}
