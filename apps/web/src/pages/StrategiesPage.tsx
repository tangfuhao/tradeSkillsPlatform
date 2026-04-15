import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';

import LifecycleActions from '../components/LifecycleActions';
import ProductStatTile from '../components/ProductStatTile';
import StrategyComposer from '../components/StrategyComposer';
import {
  controlBacktest,
  controlLiveTask,
  createBacktest,
  createLiveTask,
  deleteBacktest,
  deleteSkill,
  getLiveTaskPortfolio,
  getMarketOverview,
  listBacktests,
  listLiveTasks,
  listSignals,
  listSkills,
  triggerLiveTask,
} from '../api';
import {
  describeStatus,
  formatCount,
  formatSignedCurrency,
  formatSignedPercent,
  formatTime,
  formatWindow,
  getDefaultBacktestWindowMs,
  getErrorMessage,
  toneForStatus,
} from '../lib/formatting';
import { buildStrategyInsights, getProgressLabel, getRunReturnPct, getSkillCadence, getStrategyExcerpt } from '../lib/product';
import type { BacktestRun, ExecutionAction, LiveTask, MarketOverview, PortfolioState, Skill } from '../types';

type StrategiesData = {
  skills: Skill[];
  liveTasks: LiveTask[];
  portfoliosByTaskId: Record<string, PortfolioState>;
  overview: MarketOverview | null;
};

export default function StrategiesPage() {
  const [data, setData] = useState<StrategiesData>({
    skills: [],
    liveTasks: [],
    portfoliosByTaskId: {},
    overview: null,
  });
  const [signals, setSignals] = useState<Awaited<ReturnType<typeof listSignals>>>([]);
  const [backtests, setBacktests] = useState<Awaited<ReturnType<typeof listBacktests>>>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pendingKey, setPendingKey] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [skills, liveTasks, signalsResult, backtestsResult, overview] = await Promise.all([
        listSkills(),
        listLiveTasks(),
        listSignals(),
        listBacktests(),
        getMarketOverview(),
      ]);

      const trackedTasks = liveTasks.filter((task) => task.status === 'active' || task.status === 'paused');
      const portfolioEntries = await Promise.all(
        trackedTasks.map(async (task) => [task.id, await getLiveTaskPortfolio(task.id)] as const),
      );

      setData({
        skills,
        liveTasks,
        portfoliosByTaskId: Object.fromEntries(portfolioEntries),
        overview,
      });
      setSignals(signalsResult);
      setBacktests(backtestsResult);
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

  const insights = useMemo(
    () => buildStrategyInsights(data.skills, data.liveTasks, signals, backtests, data.portfoliosByTaskId),
    [backtests, data.liveTasks, data.portfoliosByTaskId, data.skills, signals],
  );

  const defaultBacktestWindow = getDefaultBacktestWindowMs(data.overview);

  const stats = useMemo(
    () => [
      {
        label: '策略总数',
        value: formatCount(insights.length),
        detail: '策略创建后不可编辑，只能派生新版本',
      },
      {
        label: '实时持有',
        value: formatCount(insights.filter((insight) => insight.liveTask?.status === 'active' || insight.liveTask?.status === 'paused').length),
        detail: '每条策略最多一个实时运行',
      },
      {
        label: '已完成回测',
        value: formatCount(backtests.filter((run) => run.status === 'completed').length),
        detail: '回测与实时都锚定到策略实体',
      },
      {
        label: '近 24h 窗口',
        value: defaultBacktestWindow ? formatTime(defaultBacktestWindow.endTimeMs) : '--',
        detail: defaultBacktestWindow ? '一键回测默认使用最近 24 小时' : '等待市场数据覆盖窗口',
      },
    ],
    [backtests, defaultBacktestWindow, insights],
  );

  async function handleStrategyAction(skill: Skill, action: ExecutionAction) {
    const key = `${skill.id}:${action}`;
    if (action === 'delete') {
      const confirmed = window.confirm(
        `删除策略 ${skill.title}？\n\n这会级联删除该策略关联的所有回测、实时运行、信号和组合状态。`,
      );
      if (!confirmed) return;
    }
    if (action === 'create_backtest') {
      if (!defaultBacktestWindow) {
        setError('当前没有足够的历史行情覆盖范围，无法发起默认回测。');
        return;
      }
      const confirmed = window.confirm(
        `为策略 ${skill.title} 发起最近 24 小时回测？\n\n窗口：${formatWindow(
          defaultBacktestWindow.startTimeMs,
          defaultBacktestWindow.endTimeMs,
        )}`,
      );
      if (!confirmed) return;
    }

    setPendingKey(key);
    try {
      if (action === 'create_backtest' && defaultBacktestWindow) {
        await createBacktest({
          skill_id: skill.id,
          start_time_ms: defaultBacktestWindow.startTimeMs,
          end_time_ms: defaultBacktestWindow.endTimeMs,
          initial_capital: 10_000,
        });
      } else if (action === 'create_live_task') {
        await createLiveTask({ skill_id: skill.id });
      } else if (action === 'delete') {
        await deleteSkill(skill.id);
      }
      await load();
    } catch (nextError) {
      setError(getErrorMessage(nextError));
    } finally {
      setPendingKey(null);
    }
  }

  async function handleLiveAction(task: LiveTask, action: ExecutionAction) {
    const key = `${task.id}:${action}`;
    if (action === 'stop') {
      const confirmed = window.confirm(`停止实时运行 ${task.id}？\n\n这会中断后续触发，但不会删除已有信号。`);
      if (!confirmed) return;
    }
    setPendingKey(key);
    try {
      if (action === 'trigger') {
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

  async function handleBacktestAction(run: BacktestRun, action: ExecutionAction) {
    const key = `${run.id}:${action}`;
    if (action === 'delete') {
      const confirmed = window.confirm(`删除回测 ${run.id}？\n\n这会删除该回测的 traces 与组合状态。`);
      if (!confirmed) return;
    }
    if (action === 'stop') {
      const confirmed = window.confirm(`停止回测 ${run.id}？\n\n系统会在安全检查点结束当前回测。`);
      if (!confirmed) return;
    }

    setPendingKey(key);
    try {
      if (action === 'delete') {
        await deleteBacktest(run.id);
      } else {
        await controlBacktest(run.id, action);
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
          <p className="section-eyebrow">Strategy Operations</p>
          <h1>把策略页变成真正的管理面，而不是纯展示目录。</h1>
          <p className="hero-copy">
            这里围绕策略本体进行管理：创建不可编辑策略、发起回测、启动或停止实时运行、以及执行级联删除。
          </p>
        </div>
        <div className="hero-meta">
          <span className="info-pill">删除策略会同时删除所有回测与实时运行</span>
          <span className="info-pill">策略本体只读，修改请创建新版本</span>
        </div>
      </section>

      <section className="metric-grid">
        {stats.map((stat) => (
          <ProductStatTile detail={stat.detail} key={stat.label} label={stat.label} value={stat.value} />
        ))}
      </section>

      {error ? <div className="feedback-banner is-error">策略页加载失败：{error}</div> : null}

      <section className="management-grid">
        <section className="stack-section">
          {insights.length ? (
            <section className="surface">
              <div className="section-head">
                <div>
                  <p className="section-eyebrow">Strategy Ledger</p>
                  <h2>策略管理台账</h2>
                </div>
                <span className="section-note">以策略为锚点查看实时运行、回测和可执行动作，不再拆成大量独立卡片。</span>
              </div>

              <div className="table-head strategy-ledger-head">
                <span>策略</span>
                <span>版本状态</span>
                <span>实时运行</span>
                <span>最近回测</span>
                <span>关联上下文</span>
              </div>

              <div className="record-list">
                {insights.map((insight) => {
                  const liveTask = insight.liveTask;
                  const liveAccount = insight.livePortfolio?.account;
                  return (
                    <article className="record-row strategy-ledger-row" key={insight.skill.id}>
                      <div className="strategy-row-main">
                        <div className="record-cell">
                          <p className="record-title">{insight.skill.title}</p>
                          <p className="record-subtitle">{getStrategyExcerpt(insight.skill)}</p>
                        </div>
                        <div className="record-cell">
                          <span className={`status-pill is-${toneForStatus(insight.skill.validation_status)}`}>
                            {describeStatus(insight.skill.validation_status)}
                          </span>
                          <p className="record-subtitle">节奏 {getSkillCadence(insight.skill)} / Immutable</p>
                        </div>
                        <div className="record-cell">
                          <strong>{liveTask ? describeStatus(liveTask.status) : '未启动'}</strong>
                          <p className="record-subtitle">
                            {liveTask
                              ? `收益 ${formatSignedPercent(liveAccount?.total_return_pct)} / 权益 ${formatSignedCurrency(liveAccount?.equity)}`
                              : '当前没有实时运行实例。'}
                          </p>
                        </div>
                        <div className="record-cell">
                          <strong>{insight.latestBacktest ? describeStatus(insight.latestBacktest.status) : '暂无'}</strong>
                          <p className="record-subtitle">
                            {insight.latestBacktest
                              ? `${getProgressLabel(insight.latestBacktest)} / ${formatSignedPercent(getRunReturnPct(insight.latestBacktest))}`
                              : '还没有回测记录。'}
                          </p>
                        </div>
                        <div className="record-cell">
                          <strong>
                            {formatCount(insight.backtests.length)} 回测 / {formatCount(insight.signals.length)} 信号
                          </strong>
                          <p className="record-subtitle">
                            {insight.recentSymbols.length ? insight.recentSymbols.join(' / ') : '等待交易标的上下文'}
                          </p>
                        </div>
                      </div>

                      <div className="record-footer">
                        <div className="action-cluster">
                          <Link className="action-button" to={`/strategies/${insight.skill.id}`}>
                            只读档案
                          </Link>
                          <LifecycleActions
                            actions={insight.skill.available_actions}
                            disabled={(pendingKey?.startsWith(`${insight.skill.id}:`) ?? false) || loading}
                            onAction={(action) => void handleStrategyAction(insight.skill, action)}
                            pendingAction={pendingKey?.startsWith(`${insight.skill.id}:`) ? pendingKey.split(':')[1] ?? null : null}
                          />
                        </div>
                      </div>

                      <details className="expander">
                        <summary>展开查看关联执行</summary>
                        <div className="expander-stack">
                          <section className="expander-section">
                            <div className="expander-section-head">
                              <div>
                                <p className="section-eyebrow">Linked Live</p>
                                <p className="record-title">实时运行</p>
                              </div>
                              <span className="section-note">每条策略最多保留一个实时实例。</span>
                            </div>
                            {liveTask ? (
                              <div className="spec-sheet">
                                <article className="spec-row is-emphasis">
                                  <div className="spec-term-block">
                                    <span className="spec-term">运行实例</span>
                                  </div>
                                  <div className="spec-main">
                                    <strong>{liveTask.id}</strong>
                                    <p>
                                      {describeStatus(liveTask.status)} / 最后活动{' '}
                                      {formatTime(liveTask.last_activity_at_ms ?? liveTask.last_triggered_at_ms)}
                                    </p>
                                  </div>
                                  <div className="spec-side">
                                    <span className="spec-side-label">模拟收益</span>
                                    <strong>{formatSignedPercent(liveAccount?.total_return_pct)}</strong>
                                    <p>
                                      权益 {formatSignedCurrency(liveAccount?.equity)} / 已实现{' '}
                                      {formatSignedCurrency(liveAccount?.realized_pnl)}
                                    </p>
                                  </div>
                                </article>
                                <article className="spec-row">
                                  <div className="spec-term-block">
                                    <span className="spec-term">控制动作</span>
                                  </div>
                                  <div className="spec-main">
                                    <strong>{formatCount(liveTask.available_actions.filter((action) => action !== 'delete').length)}</strong>
                                    <p>可以直接暂停、继续、停止或立即触发当前实时实例。</p>
                                  </div>
                                  <div className="spec-side">
                                    <span className="spec-side-label">actions</span>
                                    <div className="runtime-ledger-actions">
                                      <LifecycleActions
                                        actions={liveTask.available_actions.filter((action) => action !== 'delete')}
                                        disabled={(pendingKey?.startsWith(`${liveTask.id}:`) ?? false) || loading}
                                        onAction={(action) => void handleLiveAction(liveTask, action)}
                                        pendingAction={pendingKey?.startsWith(`${liveTask.id}:`) ? pendingKey.split(':')[1] ?? null : null}
                                      />
                                    </div>
                                  </div>
                                </article>
                              </div>
                            ) : (
                              <div className="empty-state compact-empty">
                                <strong>当前没有实时运行实例</strong>
                                <p>策略级动作里可以直接启动一条新的实时模拟。</p>
                              </div>
                            )}
                          </section>

                          <section className="expander-section">
                            <div className="expander-section-head">
                              <div>
                                <p className="section-eyebrow">Linked Backtests</p>
                                <p className="record-title">最近回测</p>
                              </div>
                              <span className="section-note">仅展示最近 3 条关联回测。</span>
                            </div>
                            {insight.backtests.length ? (
                              <>
                                <div className="table-head linked-backtest-head">
                                  <span>回测</span>
                                  <span>状态</span>
                                  <span>结果</span>
                                  <span>动作</span>
                                </div>
                                <div className="record-list">
                                  {insight.backtests.slice(0, 3).map((run) => (
                                    <article className="record-row linked-backtest-row" key={run.id}>
                                      <div className="linked-backtest-main">
                                        <div className="record-cell">
                                          <p className="record-title">{run.id}</p>
                                          <p className="record-subtitle">{formatWindow(run.start_time_ms, run.end_time_ms)}</p>
                                        </div>
                                        <div className="record-cell">
                                          <span className={`status-pill is-${toneForStatus(run.status)}`}>{describeStatus(run.status)}</span>
                                          <p className="record-subtitle">
                                            {run.pending_action ? `待执行 ${run.pending_action}` : getProgressLabel(run)}
                                          </p>
                                        </div>
                                        <div className="record-cell">
                                          <strong>{getRunReturnPct(run) == null ? '等待结果' : formatSignedPercent(getRunReturnPct(run))}</strong>
                                          <p className="record-subtitle">
                                            最后活动 {formatTime(run.last_activity_at_ms ?? run.updated_at_ms)}
                                          </p>
                                        </div>
                                        <div className="record-cell linked-backtest-actions">
                                          <div className="action-cluster">
                                            <Link className="text-link" to={`/replays/${run.id}`}>
                                              打开详情
                                            </Link>
                                            <LifecycleActions
                                              actions={run.available_actions}
                                              disabled={(pendingKey?.startsWith(`${run.id}:`) ?? false) || loading}
                                              onAction={(action) => void handleBacktestAction(run, action)}
                                              pendingAction={pendingKey?.startsWith(`${run.id}:`) ? pendingKey.split(':')[1] ?? null : null}
                                            />
                                          </div>
                                        </div>
                                      </div>
                                    </article>
                                  ))}
                                </div>
                              </>
                            ) : (
                              <div className="empty-state compact-empty">
                                <strong>还没有回测记录</strong>
                                <p>可以直接从策略级动作发起最近 24 小时回测。</p>
                              </div>
                            )}
                          </section>
                        </div>
                      </details>
                    </article>
                  );
                })}
              </div>
            </section>
          ) : (
            <section className="surface">
              <div className="empty-state">
                <strong>{loading ? '正在读取策略库存...' : '当前还没有策略'}</strong>
                <p>直接在右侧输入 Skill，即可创建新的策略版本。</p>
              </div>
            </section>
          )}
        </section>

        <div className="management-side">
          <StrategyComposer
            description="创建完成后立即进入策略工作台；策略会成为不可编辑的执行锚点。"
            onCreated={() => {
              setLoading(true);
              void load();
            }}
            title="新增策略"
          />
        </div>
      </section>
    </div>
  );
}
