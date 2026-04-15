import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';

import LifecycleActions from '../components/LifecycleActions';
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
        detail: '显示收益、活动时间与信号流',
      },
      {
        label: '最近信号',
        value: formatCount(data.signals.length),
        detail: signalFeed[0] ? `最新 ${formatTime(signalFeed[0].signal.trigger_time_ms)}` : '还没有实时信号',
      },
      {
        label: '触达标的',
        value: formatCount(new Set(signalFeed.map((item) => item.signal.signal.symbol).filter(Boolean)).size),
        detail: '按策略聚合而不是平铺日志',
      },
    ],
    [data.liveTasks, data.signals.length, monitoredInsights, signalFeed],
  );

  async function handleRuntimeAction(task: LiveTask, action: ExecutionAction) {
    if (action === 'delete') {
      const confirmed = window.confirm(`删除实时运行 ${task.id}？\n\n这会同时删除信号记录与实时组合状态。`);
      if (!confirmed) return;
    }
    if (action === 'stop') {
      const confirmed = window.confirm(`停止实时运行 ${task.id}？\n\n停止后不会再触发新的模拟信号。`);
      if (!confirmed) return;
    }

    const key = `${task.id}:${action}`;
    setPendingKey(key);
    try {
      if (action === 'delete') {
        await deleteLiveTask(task.id);
      } else if (action === 'trigger') {
        await triggerLiveTask(task.id);
      } else {
        await controlLiveTask(task.id, action);
      }
      await load();
    } catch (nextError) {
      setError(getErrorMessage(nextError));
    } finally {
      setPendingKey(null);
    }
  }

  return (
    <div className="page-stack">
      <section className="hero-panel surface">
        <div>
          <p className="section-eyebrow">Live Monitoring</p>
          <h1>按实时运行中的策略来监控信号与模拟收益。</h1>
          <p className="hero-copy">
            每个分组都围绕一条策略展开：运行状态、组合收益、最近信号和控制动作放在一起看，避免再回到平铺日志模式。
          </p>
        </div>
        <div className="hero-meta">
          <span className="info-pill">支持立即触发 / 暂停 / 继续 / 停止 / 删除</span>
          <Link className="action-button is-primary" to="/strategies">
            打开策略面板
          </Link>
        </div>
      </section>

      <section className="metric-grid">
        {stats.map((stat) => (
          <ProductStatTile detail={stat.detail} key={stat.label} label={stat.label} value={stat.value} />
        ))}
      </section>

      {error ? <div className="feedback-banner is-error">实时信号页加载失败：{error}</div> : null}

      <section className="dual-grid">
        <section className="stack-section">
          {monitoredInsights.length ? (
            <section className="surface">
              <div className="section-head">
                <div>
                  <p className="section-eyebrow">Runtime Ledger</p>
                  <h2>实时运行监控台账</h2>
                </div>
                <span className="section-note">按策略集中监控实时运行、收益表现和最近信号，不再拆成一组组独立信息卡。</span>
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
                          <p className="record-title">{insight.skill.title}</p>
                          <p className="record-subtitle">
                            {insight.recentSymbols.length ? insight.recentSymbols.join(' / ') : '等待首个交易标的'}
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
                            {latestSignal ? `${latestSignal.signal.symbol ?? '未指定标的'} / ${describeAction(latestSignal.signal.action as string)}` : '当前 runtime 还没有信号样本'}
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
                            onAction={(action) => void handleRuntimeAction(task, action)}
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
                          <strong>{loading ? '正在读取信号流...' : '当前 runtime 还没有信号样本'}</strong>
                          <p>可以使用“立即触发”来验证当前实时策略的信号输出。</p>
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
                <p>去策略页启动实时模拟后，这里会按策略分组展示信号流和收益表现。</p>
              </div>
            </section>
          )}
        </section>

        <section className="surface">
          <div className="section-head">
            <div>
              <p className="section-eyebrow">Recent Signal Tape</p>
              <h2>最近信号带</h2>
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
              <p>当实时策略开始运行，这里会保留最新信号带作为快速检视入口。</p>
            </div>
          )}
        </section>
      </section>
    </div>
  );
}
