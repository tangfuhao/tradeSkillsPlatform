import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { toast } from 'sonner';

import AutoRefreshDot from '../components/AutoRefreshDot';
import ConfirmDialog from '../components/ConfirmDialog';
import LifecycleActions from '../components/LifecycleActions';
import LoadingSkeleton from '../components/LoadingSkeleton';
import PageHeader from '../components/PageHeader';
import ProductStatTile from '../components/ProductStatTile';
import { controlLiveTask, deleteLiveTask, getLiveTaskPortfolio, listLiveTasks, listSignals, listSkills, triggerLiveTask } from '../api';
import {
  describeAction,
  describeDirection,
  describeStatus,
  formatCount,
  formatSignedCurrency,
  formatSignedPercent,
  formatTime,
  getErrorMessage,
  toneForStatus,
} from '../lib/formatting';
import { buildSignalFeed, buildStrategyInsights } from '../lib/product';
import type { ExecutionAction, LiveSignal, LiveTask, PortfolioState, Skill } from '../types';

type SignalsData = {
  skills: Skill[];
  liveTasks: LiveTask[];
  signals: LiveSignal[];
  portfoliosByTaskId: Record<string, PortfolioState>;
};

type ConfirmState = {
  title: string;
  description: string;
  confirmLabel: string;
  tone: 'danger' | 'warning';
  onConfirm: () => void;
} | null;

function signalNarrative(signal: LiveSignal): string {
  return signal.signal.reasoning_summary ?? signal.signal.reason ?? '当前信号没有附带更多说明。';
}

export default function SignalsPage() {
  const [data, setData] = useState<SignalsData>({
    skills: [],
    liveTasks: [],
    signals: [],
    portfoliosByTaskId: {},
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pendingKey, setPendingKey] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<ConfirmState>(null);
  const [lastRefreshMs, setLastRefreshMs] = useState<number | null>(null);
  const lastRefreshRef = useRef<number | null>(null);

  const load = useCallback(async () => {
    try {
      const [skills, liveTasks, signals] = await Promise.all([
        listSkills(),
        listLiveTasks(),
        listSignals(),
      ]);
      const trackedTasks = liveTasks.filter((task) => task.status === 'active' || task.status === 'paused');
      const portfolioEntries = await Promise.all(
        trackedTasks.map(async (task) => [task.id, await getLiveTaskPortfolio(task.id)] as const),
      );

      setData({
        skills,
        liveTasks,
        signals,
        portfoliosByTaskId: Object.fromEntries(portfolioEntries),
      });
      setError(null);
      const now = Date.now();
      lastRefreshRef.current = now;
      setLastRefreshMs(now);
    } catch (nextError) {
      setError(getErrorMessage(nextError));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => {
      void load();
    }, 15000);
    return () => window.clearInterval(timer);
  }, [load]);

  const signalFeed = useMemo(
    () => buildSignalFeed(data.signals, data.liveTasks, data.skills),
    [data.liveTasks, data.signals, data.skills],
  );

  const insights = useMemo(
    () => buildStrategyInsights(data.skills, data.liveTasks, data.signals, [], data.portfoliosByTaskId),
    [data.liveTasks, data.portfoliosByTaskId, data.signals, data.skills],
  );

  const monitoredInsights = insights.filter((insight) => insight.liveTask);
  const hasActiveTasks = data.liveTasks.some((t) => t.status === 'active');

  const stats = useMemo(
    () => [
      {
        label: '监控策略',
        value: formatCount(monitoredInsights.length),
        detail: monitoredInsights[0]?.skill.title ?? '等待实时策略',
      },
      {
        label: '实时任务',
        value: formatCount(data.liveTasks.filter((task) => task.status === 'active' || task.status === 'paused').length),
        detail: '收益、活动时间与信号流',
      },
      {
        label: '最近信号',
        value: formatCount(data.signals.length),
        detail: signalFeed[0] ? `最新 ${formatTime(signalFeed[0].signal.trigger_time_ms)}` : '还没有实时信号',
      },
      {
        label: '触达标的',
        value: formatCount(new Set(signalFeed.map((item) => item.signal.signal.symbol).filter(Boolean)).size),
        detail: '按策略聚合',
      },
    ],
    [data.liveTasks, data.signals.length, monitoredInsights, signalFeed],
  );

  async function executeRuntimeAction(task: LiveTask, action: ExecutionAction) {
    const key = `${task.id}:${action}`;
    setPendingKey(key);
    try {
      if (action === 'delete') {
        await deleteLiveTask(task.id);
        toast.success('实时任务已删除');
      } else if (action === 'trigger') {
        await triggerLiveTask(task.id);
        toast.success('触发成功，已走同一套 sync 门禁');
      } else {
        await controlLiveTask(task.id, action);
        toast.success(`实时任务已${action === 'pause' ? '暂停' : action === 'resume' ? '继续' : '停止'}`);
      }
      await load();
    } catch (nextError) {
      toast.error(getErrorMessage(nextError));
    } finally {
      setPendingKey(null);
    }
  }

  function handleRuntimeAction(task: LiveTask, action: ExecutionAction) {
    if (action === 'delete') {
      setConfirm({
        title: '删除实时运行',
        description: '删除后将清除信号记录与实时组合状态，且无法恢复。',
        confirmLabel: '确认删除',
        tone: 'danger',
        onConfirm: () => {
          setConfirm(null);
          void executeRuntimeAction(task, action);
        },
      });
      return;
    }
    if (action === 'stop') {
      setConfirm({
        title: '停止实时运行',
        description: '停止后不会再触发新的模拟信号，已有信号将保留。',
        confirmLabel: '确认停止',
        tone: 'warning',
        onConfirm: () => {
          setConfirm(null);
          void executeRuntimeAction(task, action);
        },
      });
      return;
    }
    void executeRuntimeAction(task, action);
  }

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="实时监控"
        title="信号与实时运行"
        description="按策略分组监控实时运行、收益表现和信号流。"
        status={
          hasActiveTasks ? (
            <span className="live-pulse">
              <span className="live-pulse-dot" />
              <span className="info-pill is-ok" style={{ fontSize: '0.78rem' }}>实时运行中</span>
            </span>
          ) : undefined
        }
        actions={
          <>
            <AutoRefreshDot lastRefreshMs={lastRefreshMs} />
            <Link className="action-button" to="/strategies">策略面板</Link>
          </>
        }
      />

      {loading && !data.skills.length ? (
        <LoadingSkeleton variant="stat" />
      ) : (
        <section className="metric-grid">
          {stats.map((stat) => (
            <ProductStatTile detail={stat.detail} key={stat.label} label={stat.label} value={stat.value} />
          ))}
        </section>
      )}

      {error ? <div className="feedback-banner is-error">{error}</div> : null}

      <section className="dual-grid">
        <section className="stack-section">
          {loading && !monitoredInsights.length ? (
            <section className="surface">
              <LoadingSkeleton rows={3} />
            </section>
          ) : monitoredInsights.length ? (
            <section className="surface">
              <div className="section-head">
                <div>
                  <p className="section-eyebrow">运行台账</p>
                  <h2>实时运行监控</h2>
                </div>
              </div>

              <div className="table-head monitor-ledger-head">
                <span>策略</span>
                <span>运行状态</span>
                <span>收益表现</span>
                <span>信号流</span>
                <span>最后活动</span>
              </div>

              <div className="record-list">
                {monitoredInsights.map((insight) => {
                  const task = insight.liveTask;
                  if (!task) return null;
                  const account = insight.livePortfolio?.account;
                  const recentSignals = insight.signals.slice(0, 4);
                  const latestSignal = recentSignals[0] ?? null;
                  return (
                    <article className="record-row monitor-ledger-row" key={insight.skill.id}>
                      <div className="monitor-row-main">
                        <div className="record-cell">
                          <p className="record-title">
                            <span className={`status-dot is-${toneForStatus(task.status)}`} />
                            {insight.skill.title}
                          </p>
                          <p className="record-subtitle">
                            {insight.recentSymbols.length ? insight.recentSymbols.join(' / ') : '等待首个标的'}
                          </p>
                        </div>
                        <div className="record-cell">
                          <span className={`status-pill is-${toneForStatus(task.status)}`}>{describeStatus(task.status)}</span>
                          <p className="record-subtitle">节奏 {task.cadence}</p>
                        </div>
                        <div className="record-cell">
                          <strong>{formatSignedPercent(account?.total_return_pct)}</strong>
                          <p className="record-subtitle">
                            权益 {formatSignedCurrency(account?.equity)} / 已实现 {formatSignedCurrency(account?.realized_pnl)}
                          </p>
                        </div>
                        <div className="record-cell">
                          <strong>{formatCount(insight.signals.length)} 条</strong>
                          <p className="record-subtitle">
                            {latestSignal ? `${latestSignal.signal.symbol ?? '未指定'} / ${describeAction(latestSignal.signal.action as string)}` : '暂无信号'}
                          </p>
                        </div>
                        <div className="record-cell">
                          <strong>{formatTime(task.last_activity_at_ms ?? task.last_triggered_at_ms)}</strong>
                          <p className="record-subtitle">
                            未实现 {formatSignedCurrency(account?.unrealized_pnl)}
                          </p>
                        </div>
                      </div>

                      <div className="record-footer">
                        <div className="action-cluster">
                          <Link className="action-button" to={`/strategies/${insight.skill.id}`}>
                            策略档案
                          </Link>
                          <LifecycleActions
                            actions={task.available_actions}
                            disabled={(pendingKey?.startsWith(`${task.id}:`) ?? false) || loading}
                            onAction={(action) => handleRuntimeAction(task, action)}
                            pendingAction={pendingKey?.startsWith(`${task.id}:`) ? pendingKey.split(':')[1] ?? null : null}
                          />
                        </div>
                      </div>

                      {recentSignals.length ? (
                        <details className="expander">
                          <summary>展开查看最近信号</summary>
                          <div className="timeline-list">
                            {recentSignals.map((signal) => (
                              <article className="timeline-item" key={signal.id}>
                                <div className="timeline-head">
                                  <div>
                                    <strong>{signal.signal.symbol ?? '未指定标的'}</strong>
                                    <span>{formatTime(signal.trigger_time_ms)}</span>
                                  </div>
                                  <div className="meta-row">
                                    <span className="info-pill">{describeAction(signal.signal.action as string)}</span>
                                    {typeof signal.signal.direction === 'string' ? (
                                      <span className="info-pill">{describeDirection(signal.signal.direction)}</span>
                                    ) : null}
                                  </div>
                                </div>
                                <p className="timeline-copy">{signalNarrative(signal)}</p>
                              </article>
                            ))}
                          </div>
                        </details>
                      ) : (
                        <div className="empty-state compact-empty">
                          <strong>{loading ? '正在读取信号流...' : '暂无信号样本'}</strong>
                          <p>使用「立即触发」验证当前策略在最新同步 slot 上的信号输出。</p>
                        </div>
                      )}
                    </article>
                  );
                })}
              </div>
            </section>
          ) : (
            <section className="surface">
              <div className="empty-state">
                <strong>{loading ? '正在连接实时运行...' : '当前没有可监控的实时策略'}</strong>
                <p>去策略页启动实时模拟后，信号流将在此处展示。</p>
              </div>
            </section>
          )}
        </section>

        <section className="surface">
          <div className="section-head">
            <div>
              <p className="section-eyebrow">信号带</p>
              <h2>最近信号</h2>
            </div>
          </div>
          {signalFeed.length ? (
            <div className="timeline-list">
              {signalFeed.slice(0, 12).map((item) => (
                <article className="timeline-item" key={item.signal.id}>
                  <div className="timeline-head">
                    <div>
                      <strong>{item.signal.signal.symbol ?? '未指定标的'}</strong>
                      <span>{formatTime(item.signal.trigger_time_ms)}</span>
                    </div>
                    <span className={`status-pill is-${toneForStatus(item.liveTask?.status ?? item.signal.delivery_status)}`}>
                      {describeStatus(item.liveTask?.status ?? item.signal.delivery_status)}
                    </span>
                  </div>
                  <p className="timeline-copy">{signalNarrative(item.signal)}</p>
                  <div className="meta-row">
                    <span className="info-pill">{describeAction(item.signal.signal.action as string)}</span>
                    {typeof item.signal.signal.direction === 'string' ? (
                      <span className="info-pill">{describeDirection(item.signal.signal.direction)}</span>
                    ) : null}
                    {item.skill ? (
                      <Link className="text-link" to={`/strategies/${item.skill.id}`}>
                        {item.skill.title}
                      </Link>
                    ) : null}
                  </div>
                </article>
              ))}
            </div>
          ) : (
            <div className="empty-state compact-empty">
              <strong>还没有实时信号</strong>
              <p>实时策略运行后，最新信号将自动出现在这里。</p>
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
