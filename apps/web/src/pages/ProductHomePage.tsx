import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';

import ProductStatTile from '../components/ProductStatTile';
import StrategyComposer from '../components/StrategyComposer';
import { getLiveTaskPortfolio, getMarketOverview, listBacktests, listLiveTasks, listSignals, listSkills } from '../api';
import {
  describeStatus,
  formatCount,
  formatDurationFromMs,
  formatSignedCurrency,
  formatSignedPercent,
  formatTime,
  formatWindow,
  getErrorMessage,
  toneForStatus,
} from '../lib/formatting';
import { buildStrategyInsights, getProgressLabel, getRunReturnPct, getSkillCadence } from '../lib/product';
import type { BacktestRun, LiveTask, MarketOverview, PortfolioState, Skill } from '../types';

type HomeData = {
  skills: Skill[];
  backtests: BacktestRun[];
  liveTasks: LiveTask[];
  portfoliosByTaskId: Record<string, PortfolioState>;
  overview: MarketOverview | null;
};

function progressWidth(run: BacktestRun): string {
  return `${Math.max(4, Math.min(100, Math.round((run.progress?.percent ?? 0) * 100)))}%`;
}

export default function ProductHomePage() {
  const [data, setData] = useState<HomeData>({
    skills: [],
    backtests: [],
    liveTasks: [],
    portfoliosByTaskId: {},
    overview: null,
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [skills, backtests, signals, liveTasks, overview] = await Promise.all([
        listSkills(),
        listBacktests(),
        listSignals(),
        listLiveTasks(),
        getMarketOverview(),
      ]);

      const trackedTasks = liveTasks.filter((task) => task.status === 'active' || task.status === 'paused');
      const portfolioEntries = await Promise.all(
        trackedTasks.map(async (task) => [task.id, await getLiveTaskPortfolio(task.id)] as const),
      );

      setData({
        skills,
        backtests,
        liveTasks,
        portfoliosByTaskId: Object.fromEntries(portfolioEntries),
        overview,
      });
      setError(null);

      return { signals };
    } catch (nextError) {
      setError(getErrorMessage(nextError));
      return { signals: [] };
    } finally {
      setLoading(false);
    }
  }, []);

  const [signals, setSignals] = useState<Awaited<ReturnType<typeof listSignals>>>([]);

  useEffect(() => {
    let cancelled = false;

    async function refresh() {
      const result = await load();
      if (!cancelled) {
        setSignals(result.signals);
      }
    }

    void refresh();
    const timer = window.setInterval(() => {
      void refresh();
    }, 15000);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [load]);

  const insights = useMemo(
    () =>
      buildStrategyInsights(data.skills, data.liveTasks, signals, data.backtests, data.portfoliosByTaskId),
    [data.backtests, data.liveTasks, data.portfoliosByTaskId, data.skills, signals],
  );

  const activeLiveInsight = insights.find((insight) => insight.liveTask?.status === 'active' || insight.liveTask?.status === 'paused') ?? null;
  const recentBacktests = data.backtests.slice(0, 5);
  const recentStrategies = insights.slice(0, 5);

  const stats = useMemo(
    () => [
      {
        label: '实时策略',
        value: formatCount(data.liveTasks.filter((task) => task.status === 'active' || task.status === 'paused').length),
        detail: activeLiveInsight?.skill.title ?? '当前没有实时模拟任务',
      },
      {
        label: '进行中回测',
        value: formatCount(data.backtests.filter((run) => ['queued', 'running', 'paused', 'stopping'].includes(run.status)).length),
        detail: recentBacktests[0] ? `最新回测 ${recentBacktests[0].id}` : '等待第一条回测',
      },
      {
        label: '策略库存',
        value: formatCount(data.skills.length),
        detail: `${formatCount(data.skills.filter((skill) => skill.validation_status === 'passed').length)} 条可执行策略`,
      },
      {
        label: '历史覆盖',
        value: formatCount(data.overview?.total_symbols ?? 0),
        detail: data.overview ? `${data.overview.base_timeframe} 数据底座` : '市场概览读取中',
      },
    ],
    [activeLiveInsight, data.backtests, data.liveTasks, data.overview, data.skills, recentBacktests],
  );

  const livePortfolio = activeLiveInsight?.livePortfolio?.account;
  const liveTask = activeLiveInsight?.liveTask ?? null;

  return (
    <div className="page-stack">
      <section className="hero-panel surface">
        <div>
          <p className="section-eyebrow">Operations Overview</p>
          <h1>把首页收紧成真正的策略工作台。</h1>
          <p className="hero-copy">
            首页只保留四块最高频信息：当前实时模拟、最近回测、最近策略、以及新的策略 Skill 入口。
          </p>
        </div>
        <div className="hero-meta">
          <span className="info-pill">策略关联：1 条策略 → 多个回测 + 最多 1 个实时运行</span>
          <span className="info-pill">策略创建后不可编辑</span>
          <Link className="action-button is-primary" to="/strategies">
            进入策略管理
          </Link>
        </div>
      </section>

      <section className="metric-grid">
        {stats.map((stat) => (
          <ProductStatTile detail={stat.detail} key={stat.label} label={stat.label} value={stat.value} />
        ))}
      </section>

      {error ? <div className="feedback-banner is-error">首页加载失败：{error}</div> : null}

      <section className="dashboard-grid">
        <div className="dashboard-main">
          <section className="surface emphasis-surface">
            <div className="section-head">
              <div>
                <p className="section-eyebrow">Live Runtime</p>
                <h2>当前实时策略模拟</h2>
              </div>
              <Link className="text-link" to="/signals">
                打开实时监控
              </Link>
            </div>
            {activeLiveInsight && liveTask ? (
              <div className="live-highlight">
                <div className="live-highlight-header">
                  <div>
                    <p className="record-title">{activeLiveInsight.skill.title}</p>
                    <div className="meta-row">
                      <span className={`status-pill is-${toneForStatus(liveTask.status)}`}>{describeStatus(liveTask.status)}</span>
                      <span className="info-pill">节奏 {liveTask.cadence}</span>
                      <span className="info-pill">已运行 {formatDurationFromMs(liveTask.created_at_ms)}</span>
                    </div>
                  </div>
                  <div className="summary-side">
                    <strong>{formatSignedPercent(livePortfolio?.total_return_pct)}</strong>
                    <span>模拟总收益</span>
                  </div>
                </div>
                <div className="metric-inline-grid">
                  <div className="metric-inline">
                    <span>当前权益</span>
                    <strong>{formatSignedCurrency(livePortfolio?.equity)}</strong>
                  </div>
                  <div className="metric-inline">
                    <span>已实现收益</span>
                    <strong>{formatSignedCurrency(livePortfolio?.realized_pnl)}</strong>
                  </div>
                  <div className="metric-inline">
                    <span>未实现收益</span>
                    <strong>{formatSignedCurrency(livePortfolio?.unrealized_pnl)}</strong>
                  </div>
                  <div className="metric-inline">
                    <span>最后活动</span>
                    <strong>{formatTime(liveTask.last_activity_at_ms ?? liveTask.last_triggered_at_ms)}</strong>
                  </div>
                </div>
                <div className="split-note">
                  <span>最近信号 {formatCount(activeLiveInsight.signals.length)} 条</span>
                  <span>{activeLiveInsight.recentSymbols.length ? activeLiveInsight.recentSymbols.slice(0, 4).join(' / ') : '等待首个交易标的'}</span>
                </div>
              </div>
            ) : (
              <div className="empty-state">
                <strong>{loading ? '正在扫描实时任务...' : '当前没有正在运行的实时策略'}</strong>
                <p>去策略页启动一条实时模拟后，这里会显示运行时长、收益、最近活动与策略入口。</p>
              </div>
            )}
          </section>

          <section className="surface">
            <div className="section-head">
              <div>
                <p className="section-eyebrow">Recent Backtests</p>
                <h2>最近回测</h2>
              </div>
              <Link className="text-link" to="/replays">
                查看全部
              </Link>
            </div>
            {recentBacktests.length ? (
              <>
                <div className="table-head compact-ledger-head">
                  <span>策略 / 回测</span>
                  <span>状态 / 进度</span>
                  <span>结果</span>
                </div>
                <div className="record-list">
                  {recentBacktests.map((run) => {
                  const owner = data.skills.find((skill) => skill.id === run.skill_id) ?? null;
                  const returnPct = getRunReturnPct(run);
                  return (
                    <Link className="record-row" key={run.id} to={`/replays/${run.id}`}>
                      <div className="record-main compact-record-main">
                        <div>
                          <p className="record-title">{owner?.title ?? run.skill_id}</p>
                          <p className="record-subtitle">{formatWindow(run.start_time_ms, run.end_time_ms)}</p>
                        </div>
                        <div className="meta-row">
                          <span className={`status-pill is-${toneForStatus(run.status)}`}>{describeStatus(run.status)}</span>
                          <span className="info-pill">{run.pending_action ? `待执行 ${run.pending_action}` : getProgressLabel(run)}</span>
                          <span className="info-pill">{returnPct == null ? '等待结果' : formatSignedPercent(returnPct)}</span>
                        </div>
                      </div>
                      <div className="progress-shell">
                        <div className="progress-bar">
                          <span className="progress-fill" style={{ width: progressWidth(run) }} />
                        </div>
                        <span className="record-subtitle">最后活动 {formatTime(run.last_activity_at_ms ?? run.updated_at_ms)}</span>
                      </div>
                    </Link>
                  );
                  })}
                </div>
              </>
            ) : (
              <div className="empty-state compact-empty">
                <strong>还没有回测记录</strong>
                <p>策略页支持一键发起最近 24 小时回测，完成后会立即回到这里。</p>
              </div>
            )}
          </section>
        </div>

        <div className="dashboard-side">
          <section className="surface">
            <div className="section-head">
              <div>
                <p className="section-eyebrow">Recent Strategies</p>
                <h2>最近策略</h2>
              </div>
              <Link className="text-link" to="/strategies">
                策略列表
              </Link>
            </div>
            {recentStrategies.length ? (
              <>
                <div className="table-head compact-ledger-head compact-ledger-head-two">
                  <span>策略</span>
                  <span>运行摘要</span>
                </div>
                <div className="mini-record-list">
                  {recentStrategies.map((insight) => (
                  <Link className="mini-record" key={insight.skill.id} to={`/strategies/${insight.skill.id}`}>
                    <div className="mini-record-head">
                      <strong>{insight.skill.title}</strong>
                      <span className={`status-pill is-${toneForStatus(insight.skill.validation_status)}`}>
                        {describeStatus(insight.skill.validation_status)}
                      </span>
                    </div>
                    <p>{getSkillCadence(insight.skill)}</p>
                    <div className="meta-row">
                      <span className="info-pill">{formatCount(insight.completedBacktestCount)} 次完成回测</span>
                      <span className="info-pill">
                        {insight.liveTask ? describeStatus(insight.liveTask.status) : '无实时运行'}
                      </span>
                    </div>
                  </Link>
                  ))}
                </div>
              </>
            ) : (
              <div className="empty-state compact-empty">
                <strong>还没有策略库存</strong>
                <p>直接在右侧粘贴 Skill，即可创建新的不可编辑策略版本。</p>
              </div>
            )}
          </section>

          <StrategyComposer
            description="直接在产品首页录入策略 Skill；创建成功后会自动进入策略工作台。"
            onCreated={() => {
              setLoading(true);
              void load().then((result) => setSignals(result.signals));
            }}
            submitLabel="立即创建策略"
            title="直接输入策略 Skill"
            variant="desk"
          />
        </div>
      </section>
    </div>
  );
}
